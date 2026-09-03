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

### 0. Interactive Home Screen (OpenCode Style)

Just run `music` alone to launch the centered interactive search bar:

```bash
music
```

- 🔍 **Centered Search Bar**: Start typing any song, artist, or playlist title.
- 📋 **Live Dropdown Suggestions**: Real-time debounced auto-complete and search results for tracks and playlists.
- 🕒 **Recent History & Quick Picks**: Instant access to your recent playback history and curated popular genres when the search bar is empty.
- 🔀 **Filter Toggling**: Press <kbd>Tab</kbd> to cycle search filter (`All` ➔ `Tracks` ➔ `Playlists`).
- ⌨️ **Intuitive Keyboard Navigation**: <kbd>↑</kbd> / <kbd>↓</kbd> to navigate dropdown, <kbd>Enter</kbd> to play instantly, <kbd>Esc</kbd> to exit.

### 1. Direct Playback (Top Result)

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

### 4. Play from a Selected Playlist

Stream entire YouTube Music playlists with gapless transitions and live track indicators (`Playlist: <Title> (3/20)`):

```bash
# Search for playlists and pick one from an interactive table
music playlist "Lofi Hip Hop"

# Play a playlist in random/shuffle mode
music playlist "Synthwave Chill" --shuffle

# Pick a specific starting song from the playlist
music playlist "Top Hits 2024" -s

# Stream directly from a YouTube or YouTube Music playlist URL
music playlist "https://music.youtube.com/playlist?list=PL..."
```

---

## ⌨️ Interactive Player Controls

While a track is playing in your terminal:

| Key | Action |
|---|---|
| <kbd>Space</kbd> | Toggle Play / Pause |
| <kbd>n</kbd> / <kbd>&gt;</kbd> | **Skip to Next track** (Autoplay queue) |
| <kbd>a</kbd> | **Toggle Autoplay ON / OFF** |
| <kbd>b</kbd> | **Toggle AdBlock ON / OFF** |
| <kbd>l</kbd> | **Toggle Synced Lyrics ON / OFF** |
| <kbd>→</kbd> / <kbd>←</kbd> | Seek forward / backward 5 seconds |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Increase / decrease volume by 5% |
| <kbd>m</kbd> | Toggle Mute |
| <kbd>r</kbd> | Replay current track from start |
| <kbd>q</kbd> | Stop playback and quit |

---

## 🎤 Time-Synchronized Lyrics (Karaoke Mode)

`music-cli` integrates synchronized LRC lyrics powered by the open-source **LRCLIB** database (with YouTube Music fallback):
- **Live Karaoke Teleprompter**: The terminal centers and highlights the active sung line in real-time (`[bold bright_yellow]▶ Line text[/bold bright_yellow]`), alongside previous and upcoming lines.
- **Instrumental Detection**: Automatically indicates `♪ (Instrumental Intro) ♪` and `♪ (Outro) ♪`.
- **Toggle Anytime**: Press <kbd>l</kbd> during playback to toggle the lyrics display on or off.

```bash
# Stream with lyrics disabled
music "Hotel California" --no-lyrics

# Configure default
music config set show_lyrics true
```

---

## 🛡️ Built-in Ad Blocker (uBlock & SponsorBlock Integration)

`music-cli` comes with **out-of-the-box ad blocking enabled by default**:
1. **Direct Stream Media Extraction**: YouTube video ads (pre-roll, mid-roll, post-roll) are eliminated because `music-cli` extracts only the media audio stream directly from YouTube CDN (`googlevideo.com`).
2. **In-Stream Sponsor & Ad Skipping**: Automatically detects and skips sponsored segments ("This song is brought to you by..."), self-promotions, interaction reminders, and non-music video intros/skits using the community-verified SponsorBlock database.
3. **Domain Blocklist**: Blocks DoubleClick, Google AdSense, and telemetry endpoints inspired by uBlock Origin / EasyList filters.

Toggle dynamically during playback by pressing <kbd>b</kbd>, or disable via `--no-adblock`:
```bash
# Disable ad blocker for a session
music "Bohemian Rhapsody" --no-adblock

# Toggle globally
music config set ad_blocker false
```

---

## 🔐 Authentication (YouTube Premium / Skip Ads)

By default, `music-cli` runs in **Guest / Standard Mode** (no login needed).

If you have a YouTube Music / YouTube Premium subscription across multiple Google accounts, you can authenticate via an interactive hyperlink:

### 1. Interactive Hyperlink & Multi-Account Login

Simply run:
```bash
music login
```
This displays:
1. **Clickable Hyperlink**:
   `https://accounts.google.com/AccountChooser?continue=https://music.youtube.com`
2. **Account Switcher**: An interactive numbered list of all Google accounts detected on your machine (e.g. `ghiffarsabda@gmail.com`, work emails, etc.).
3. **One-key actions**:
   - Type `1-N` to immediately link that account.
   - Type `o` to open the Google Account Chooser link in your browser.
   - Type `c` to import an exported `cookies.txt` file.

You can also open the browser directly from the command:
```bash
music login --open
```

### 2. Manage Authentication
- **Check login status**:
  ```bash
  music login --status
  ```
- **Log out (return to standard guest mode)**:
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
