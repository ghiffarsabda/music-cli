"""MPV player controller using JSON-RPC Unix domain socket."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from music.auth import get_mpv_auth_args
from music.config import get_config_val


class MpvPlayer:
    """Controls an mpv instance running in background via Unix domain socket IPC."""

    def __init__(self, initial_volume: int = 80):
        self.initial_volume = initial_volume
        self.sock_path = os.path.join(tempfile.gettempdir(), f"music_cli_{os.getpid()}_{id(self)}.sock")
        self.process: Optional[subprocess.Popen] = None
        self.sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._is_running = False
        self._cached_duration: float = 0.0
        self._cached_volume: int = initial_volume
        self._last_time_pos: float = 0.0
        self._is_eof = False
        self._play_start_time: float = 0.0
        self._req_id = 0
        self._sock_file = None

    def start(self) -> bool:
        """Start mpv process and establish IPC socket connection."""
        if self._is_running:
            return True

        if os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError:
                pass

        mpv_bin = shutil.which("mpv")
        if not mpv_bin:
            raise RuntimeError("mpv executable not found. Please ensure mpv is installed.")

        yt_dlp_bin = get_config_val("yt_dlp_path", shutil.which("yt-dlp") or "yt-dlp")
        node_bin = get_config_val("node_path", shutil.which("node") or "")
        js_runtime_opt = f"js-runtimes=node:{node_bin}" if node_bin else ""
        cmd = [
            mpv_bin,
            "--no-video",
            "--idle=yes",
            f"--input-ipc-server={self.sock_path}",
            f"--volume={self.initial_volume}",
            f"--script-opts=ytdl_hook-ytdl_path={yt_dlp_bin}",
            "--ytdl-raw-options-append=remote-components=ejs:github",
            "--ytdl-format=bestaudio/best",
            "--gapless-audio=yes",
            "--prefetch-playlist=yes",
            "--keep-open=no",
            "--force-window=no",
            "--terminal=no",
            "--msg-level=all=no",
        ]

        if js_runtime_opt:
            cmd.append(f"--ytdl-raw-options-append={js_runtime_opt}")

        # Add auth cookies/options for mpv
        for opt in get_mpv_auth_args():
            cmd.append(opt)

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

        # Wait for socket to become available
        connected = False
        for _ in range(40):
            if os.path.exists(self.sock_path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(1.5)
                    s.connect(self.sock_path)
                    self.sock = s
                    self._sock_file = s.makefile("r", encoding="utf-8")
                    connected = True
                    break
                except (socket.error, OSError):
                    time.sleep(0.05)
            time.sleep(0.05)

        if not connected:
            self.stop()
            raise RuntimeError("Failed to connect to mpv IPC socket.")

        self._is_running = True
        return True

    def _send_command(self, command: List[Any]) -> Optional[Any]:
        """Send a JSON-RPC command to mpv and return the result matching request_id."""
        with self._lock:
            if not self.sock or not self._sock_file or not self._is_running:
                return None

            try:
                self._req_id += 1
                curr_id = self._req_id
                payload = json.dumps({"command": command, "request_id": curr_id}) + "\n"
                self.sock.sendall(payload.encode("utf-8"))

                # Read responses until we find the one with matching request_id
                for _ in range(30):
                    line = self._sock_file.readline()
                    if not line:
                        return None
                    try:
                        data = json.loads(line)
                        if data.get("request_id") == curr_id:
                            return data.get("data")
                    except json.JSONDecodeError:
                        continue
                return None
            except (socket.timeout, socket.error, OSError):
                return None

    def play(self, url: str) -> bool:
        """Load and start playing a media URL."""
        self._cached_duration = 0.0
        self._last_time_pos = 0.0
        self._is_eof = False
        self._play_start_time = time.time()
        res = self._send_command(["loadfile", url, "replace"])
        return res is not None or self.process_is_alive()

    def append_track(self, url: str) -> bool:
        """Append track to mpv playlist for seamless gapless prebuffering."""
        res = self._send_command(["loadfile", url, "append"])
        return res is not None

    def next_track(self) -> bool:
        """Advance immediately to next pre-buffered track in playlist."""
        self._cached_duration = 0.0
        self._last_time_pos = 0.0
        self._play_start_time = time.time()
        res = self._send_command(["playlist-next"])
        return res is not None

    def get_playlist_pos(self) -> int:
        """Get index of currently playing item in playlist (0-indexed)."""
        pos = self._send_command(["get_property", "playlist-pos"])
        return int(pos) if isinstance(pos, (int, float)) else -1

    def get_playlist_count(self) -> int:
        """Get total number of tracks in mpv playlist."""
        count = self._send_command(["get_property", "playlist-count"])
        return int(count) if isinstance(count, (int, float)) else 0

    def pause(self) -> None:
        """Pause playback."""
        self._send_command(["set_property", "pause", True])

    def resume(self) -> None:
        """Resume playback."""
        self._send_command(["set_property", "pause", False])

    def toggle_pause(self) -> None:
        """Toggle pause/play."""
        self._send_command(["cycle", "pause"])

    def seek(self, seconds: float) -> None:
        """Relative seek forward or backward in seconds."""
        self._send_command(["seek", seconds, "relative"])

    def seek_to(self, seconds: float) -> None:
        """Seek to absolute position."""
        self._send_command(["seek", max(0.0, seconds), "absolute"])

    def restart(self) -> None:
        """Restart current track from beginning."""
        self.seek_to(0.0)
        self.resume()

    def set_volume(self, volume: int) -> None:
        """Set volume percentage (0-100)."""
        vol = max(0, min(100, volume))
        self._cached_volume = vol
        self._send_command(["set_property", "volume", vol])

    def adjust_volume(self, delta: int) -> int:
        """Increase or decrease volume by delta."""
        curr = self.get_volume()
        new_vol = max(0, min(100, curr + delta))
        self.set_volume(new_vol)
        return new_vol

    def toggle_mute(self) -> None:
        """Toggle mute."""
        self._send_command(["cycle", "mute"])

    def get_volume(self) -> int:
        """Get current volume."""
        res = self._send_command(["get_property", "volume"])
        if isinstance(res, (int, float)):
            self._cached_volume = int(res)
        return self._cached_volume

    def get_status(self) -> Dict[str, Any]:
        """Fetch current playback snapshot: position, duration, paused, state."""
        if not self.process_is_alive():
            return {
                "state": "stopped",
                "time_pos": self._last_time_pos,
                "duration": self._cached_duration,
                "paused": False,
                "volume": self._cached_volume,
                "muted": False,
            }

        paused = bool(self._send_command(["get_property", "pause"]))
        muted = bool(self._send_command(["get_property", "mute"]))
        time_pos = self._send_command(["get_property", "time-pos"])
        duration = self._send_command(["get_property", "duration"])
        eof_reached = bool(self._send_command(["get_property", "eof-reached"]))
        idle_active = bool(self._send_command(["get_property", "idle-active"]))

        if isinstance(duration, (int, float)) and duration > 0:
            self._cached_duration = float(duration)

        if isinstance(time_pos, (int, float)):
            self._last_time_pos = float(time_pos)

        # Determine playback state
        if eof_reached:
            state = "finished"
        elif idle_active and self._last_time_pos == 0.0:
            if self._play_start_time > 0 and (time.time() - self._play_start_time) > 12.0:
                state = "error"
            else:
                state = "loading"
        elif idle_active and self._last_time_pos > 0.0:
            state = "finished"
        elif paused:
            state = "paused"
        elif time_pos is not None:
            state = "playing"
        else:
            state = "buffering"

        return {
            "state": state,
            "time_pos": self._last_time_pos,
            "duration": self._cached_duration,
            "paused": paused,
            "volume": self._cached_volume,
            "muted": muted,
        }

    def process_is_alive(self) -> bool:
        """Check if mpv subprocess is still alive."""
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        """Gracefully stop playback and terminate mpv."""
        self._is_running = False
        try:
            if self._sock_file:
                try:
                    self._sock_file.close()
                except Exception:
                    pass
                self._sock_file = None
            if self.sock:
                try:
                    payload = json.dumps({"command": ["quit"]}) + "\n"
                    self.sock.sendall(payload.encode("utf-8"))
                except Exception:
                    pass
                self.sock.close()
                self.sock = None
        except Exception:
            pass

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        if os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError:
                pass
