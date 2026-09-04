# 🎵 Music CLI

> **The simplest, ad-free music player for your terminal.**  
> Stream any song, album, or playlist from YouTube Music with live synchronized lyrics, instant queue management, and zero account setup.

---

## ⚡ Quick Install (Get Started in 10 Seconds)

No signups, accounts, or complex setup required. Just paste one line into your terminal:

### 🍎 Mac & 🐧 Linux
Open your **Terminal** and run:
```bash
curl -fsSL https://cdn.jsdelivr.net/gh/ghiffarsabda/music-cli@main/install.sh | bash
```

### 🪟 Windows
Open **PowerShell** and run:
```powershell
irm https://cdn.jsdelivr.net/gh/ghiffarsabda/music-cli@main/install.ps1 | iex
```

> **Done!** Restart your terminal, type **`music`**, and press Enter to start listening.

---

## 🎧 How to Use

### 1. Interactive Search (Easiest Way)
Just type:
```bash
music
```
- A clean search box will appear in the center of your screen.
- Start typing any song name, artist, album, or playlist (e.g. `Bohemian Rhapsody`, `Coldplay`, `Lofi`).
- Use <kbd>↑</kbd> and <kbd>↓</kbd> arrows to highlight a song and press <kbd>Enter</kbd>.
- A menu will pop up asking what you want to do:
  - Press <kbd>1</kbd> or <kbd>Enter</kbd> to **Play Now**
  - Press <kbd>2</kbd> to **Add to Queue** (keeps your current music playing)

---

### 2. Play a Song Directly
Know what you want to listen to? Play it right from the command line:
```bash
music "Somewhere Only We Know"
```
Or without quotes for short names:
```bash
music Starboy
```

---

### 3. Play a Playlist or Album
Want non-stop music for studying or working?
```bash
# Search and choose from popular playlists
music playlist "Lofi Chill Beats"

# Shuffle the playlist randomly
music playlist "Synthwave Radio" --shuffle

# Play directly from a YouTube or YouTube Music link
music playlist "https://music.youtube.com/playlist?list=..."
```

---

### 4. Stop All Music
If you closed your terminal while music was playing and want to turn it off:
```bash
music stop
```

---

## ⌨️ Player Controls Cheat Sheet

While music is playing, control everything using your keyboard:

| Key | What it does |
|:---:|---|
| <kbd>Space</kbd> | **Play / Pause** |
| <kbd>P</kbd> | **Previous track** (replays song if playing for >3s) |
| <kbd>N</kbd> | **Next track** (skips to the next song in queue) |
| <kbd>/</kbd> | **Search for new songs** without stopping the current music |
| <kbd>→</kbd> / <kbd>←</kbd> | Fast-forward / rewind by **5 seconds** |
| <kbd>+</kbd> / <kbd>-</kbd> | Increase / decrease volume by **5%** |
| <kbd>M</kbd> | **Mute / Unmute** |
| <kbd>Q</kbd> | **Quit** and close the player |

### 🎶 Managing the Queue
The **Up Next Queue** is always visible right below your player box:
- <kbd>↑</kbd> / <kbd>↓</kbd> — Select a song in the queue
- <kbd>Shift + ↑</kbd> / <kbd>Shift + ↓</kbd> (or <kbd>K</kbd> / <kbd>J</kbd>) — **Move song up or down** in the queue
- <kbd>x</kbd> or <kbd>Del</kbd> — **Remove** the highlighted song from the queue
- <kbd>Enter</kbd> — **Play now** (jump straight to this song)
- <kbd>c</kbd> — **Clear** the entire upcoming queue

---

## ✨ Features You'll Love

- 🛡️ **Built-in Ad Blocker**: Blocks annoying YouTube video ads automatically. It even skips sponsored promos and non-music talking intros inside songs.
- 🎤 **Live Karaoke Lyrics**: Real-time synchronized scrolling lyrics highlight line-by-line as the artist sings.
- ⚡ **Lightning Fast & Lightweight**: Uses virtually no memory or CPU compared to opening a heavy web browser tab.
- 🔒 **100% Private & Local**: Your listening history is saved only on your own computer. It is never tracked or sent to the cloud.
- 📴 **Offline-First Search**: Previously played songs show up instantly (0ms) as you type, even before web results finish loading.

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>Do I need a Google account or YouTube Premium?</b></summary>
<br>
<b>No!</b> Everything works right out of the box without logging in or signing up. Guest mode is enabled by default.
</details>

<details>
<summary><b>Is it free?</b></summary>
<br>
<b>Yes, 100% free and open-source.</b> There are no subscriptions, paywalls, or hidden fees.
</details>

<details>
<summary><b>How do I see my recently played songs?</b></summary>
<br>
Run <code>music history</code> to view your recent tracks, or select a number to replay any past song. To wipe your history, run <code>music history --clear</code>.
</details>

<details>
<summary><b>Can I connect my YouTube Premium account? (Optional)</b></summary>
<br>
If you want to access your private account playlists, you can optionally run <code>music login</code>. You can log out anytime with <code>music login --logout</code>.
</details>

<details>
<summary><b>Windows shows: <code>irm : unable to connect to remote server</code>?</b></summary>
<br>
This happens on some Windows machines when PowerShell defaults to older TLS security protocols or if your local internet provider (e.g. IndiHome / Telkomsel) blocks GitHub's raw address.
<br><br>
<b>Solution 1 (Recommended):</b> Paste this exact line into PowerShell:
<pre><code>[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://cdn.jsdelivr.net/gh/ghiffarsabda/music-cli@main/install.ps1 -UseBasicParsing | iex</code></pre>
<b>Solution 2:</b> Or use Windows built-in <code>curl.exe</code>:
<pre><code>curl.exe -fsSL https://cdn.jsdelivr.net/gh/ghiffarsabda/music-cli@main/install.ps1 | powershell -</code></pre>
</details>

---

## 🛠️ Advanced & Developer Usage

<details>
<summary><b>Alternative Installation Methods (pipx / manual)</b></summary>

### Using `pipx` (Recommended for Python developers)
```bash
pipx install git+https://github.com/ghiffarsabda/music-cli.git
```

### Manual Git Clone & Editable Install
```bash
git clone https://github.com/ghiffarsabda/music-cli.git
cd music-cli
pip install -e .
```
</details>

<details>
<summary><b>System Requirements & Dependencies</b></summary>

- **Python**: Version 3.9 or newer
- **`mpv`**: Lightweight audio engine (automatically installed by the one-line installer)
- **`yt-dlp`**: Audio stream resolver (automatically installed via Python dependencies)
</details>

<details>
<summary><b>Configuration Settings</b></summary>

View current configuration:
```bash
music config
```

Change default settings:
```bash
# Set default startup volume (0 to 100)
music config set volume 80

# Disable lyrics by default
music config set show_lyrics false

# Disable built-in ad blocker
music config set ad_blocker false
```
</details>
