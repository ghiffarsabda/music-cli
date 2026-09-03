# 🎵 Music CLI

A sleek, lightweight terminal application to stream music directly from **YouTube Music**.

No account or login is required to play songs. If you have a **YouTube Music / YouTube Premium** subscription, you can easily connect your account to enjoy uninterrupted, ad-free streaming!

---

## ✨ Features

- ⚡ **Instant Streaming**: Just run `music "song name"` and start listening immediately.
- 🎯 **Interactive TUI Player**: Real-time progress bar, track/artist/album metadata, and playback status.
- ⌨️ **Live Keyboard Controls**: Play/pause, seek, volume adjustments, mute, replay, and exit without leaving the terminal.
- 🔍 **Interactive Search**: Browse top matching songs with `music -s "query"` or `music search "query"`.
- 🛡️ **Optional Authentication & Ad-Free Mode**:
  - Direct browser cookie extraction (`music login --browser chrome`)
  - Netscape `cookies.txt` import (`music login --cookies file.txt`)
  - Ad-free streaming for YouTube Premium accounts
  - Standard ad-supported guest mode by default (zero setup required)
- 📜 **Playback History**: View and replay recent tracks with `music history`.
- ⚙️ **Configurable**: Customize default volume, audio quality, and default browser.

---

## 🚀 Quick Start

### 1. Basic Playback (Top Result)

```bash
music "Never Gonna Give You Up"
```
Or short queries:
```bash
music Bohemian Rhapsody
```

### 2. Search & Select

Want to choose between studio versions, live versions, or remasters? Use the search flag `-s` or the `search` command:

```bash
music "Hotel California" -s
# or
music search "Hotel California"
```

### 3. Direct YouTube / YouTube Music URL

```bash
music url "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
```

---

## ⌨️ Interactive Player Controls

While a track is playing in your terminal:

| Key | Action |
|---|---|
| <kbd>Space</kbd> | Toggle Play / Pause |
| <kbd>→</kbd> / <kbd>←</kbd> | Seek forward / backward 5 seconds |
| <kbd>]</kbd> / <kbd>[</kbd> | Seek forward / backward 30 seconds |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Increase / decrease volume by 5% |
| <kbd>m</kbd> | Toggle Mute |
| <kbd>r</kbd> | Replay current track from start |
| <kbd>q</kbd> | Stop playback and quit |

---

## 🔐 Authentication (YouTube Premium / Skip Ads)

By default, `music-cli` runs in **Guest / Standard Mode** (no login needed).

If you have a YouTube Premium account, you can enable ad-free playback using either of the following methods:

### Option A: Extract from your browser (Recommended)

Extract session cookies directly from your installed browser:

```bash
# Supported browsers: chrome, firefox, brave, edge, chromium, opera, vivaldi
music login --browser chrome
```

### Option B: Import `cookies.txt`

If you use a browser extension (such as *Get cookies.txt LOCALLY*), export your cookies to a file and import it:

```bash
music login --cookies ~/Downloads/youtube.com_cookies.txt
```

### Manage Authentication

- **Check login status**:
  ```bash
  music login --status
  ```
- **Log out (return to guest mode)**:
  ```bash
  music login --logout
  ```

---

## 📜 History & Configuration

### View Recently Played Songs

```bash
# View recent tracks and replay by number
music history

# Clear playback history
music history --clear
```

### View & Edit Configuration

```bash
# View all settings
music config

# Set default volume (0-100)
music config set volume 85

# Change default browser for authentication
music config set browser firefox
```

---

## 📦 Requirements

- Python 3.9+
- [`mpv`](https://mpv.io) (Audio playback backend)
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
