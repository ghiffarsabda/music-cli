#!/usr/bin/env bash
# ==============================================================================
#  music-cli: Cross-platform One-line Installer (Linux & macOS)
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/ghiffarsabda/music-cli/main/install.sh | bash
# ==============================================================================

set -e

# ANSI styling
BOLD="\033[1m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "\n${BOLD}${CYAN}♫  m u s i c  -  c l i${RESET} Installer"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

# 1. Check Python (>= 3.9 required)
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ Error: python3 is not installed.${RESET}"
    echo -e "Please install Python 3.9 or higher and re-run this script."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    echo -e "${RED}✗ Error: Python 3.9+ required (found Python $PY_VERSION).${RESET}"
    exit 1
fi
echo -e "${GREEN}✓${RESET} Found Python ${BOLD}$PY_VERSION${RESET}"

# 2. Check for mpv backend
if ! command -v mpv &>/dev/null; then
    echo -e "\n${YELLOW}⚠ mpv player is not detected.${RESET}"
    echo -e "music-cli requires mpv for seamless audio streaming."
    
    OS_TYPE="$(uname -s)"
    if [ "$OS_TYPE" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            echo -e "${CYAN}→ Installing mpv via Homebrew...${RESET}"
            brew install mpv
        else
            echo -e "Install Homebrew first, then run: ${BOLD}brew install mpv${RESET}"
        fi
    elif [ "$OS_TYPE" = "Linux" ]; then
        if command -v apt-get &>/dev/null; then
            echo -e "${CYAN}→ Installing mpv via apt (may prompt for sudo password)...${RESET}"
            sudo apt-get update -y && sudo apt-get install -y mpv
        elif command -v pacman &>/dev/null; then
            echo -e "${CYAN}→ Installing mpv via pacman...${RESET}"
            sudo pacman -S --noconfirm mpv
        elif command -v dnf &>/dev/null; then
            echo -e "${CYAN}→ Installing mpv via dnf...${RESET}"
            sudo dnf install -y mpv
        elif command -v zypper &>/dev/null; then
            echo -e "${CYAN}→ Installing mpv via zypper...${RESET}"
            sudo zypper install -y mpv
        else
            echo -e "Please install mpv using your package manager (e.g. sudo apt install mpv)."
        fi
    fi
else
    echo -e "${GREEN}✓${RESET} Found mpv audio backend"
fi

# 3. Setup isolated virtual environment in ~/.local/share/music-cli
# (Prevents PEP 668 externally-managed-environment errors on modern distros)
INSTALL_DIR="${HOME}/.local/share/music-cli"
BIN_DIR="${HOME}/.local/bin"

echo -e "\n${CYAN}→ Setting up isolated environment in ${BOLD}${INSTALL_DIR}${RESET}..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"

python3 -m venv "${INSTALL_DIR}/venv"

# 4. Install / Update music-cli
echo -e "${CYAN}→ Installing music-cli and dependencies...${RESET}"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip --quiet
"${INSTALL_DIR}/venv/bin/pip" install --upgrade "git+https://github.com/ghiffarsabda/music-cli.git" --quiet

# 5. Create symlink to ~/.local/bin/music
ln -sf "${INSTALL_DIR}/venv/bin/music" "${BIN_DIR}/music"
chmod +x "${BIN_DIR}/music"

echo -e "${GREEN}✓${RESET} Created executable at ${BOLD}${BIN_DIR}/music${RESET}"

# 6. Check if ~/.local/bin is in PATH
PATH_UPDATED=0
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    SHELL_NAME="$(basename "$SHELL")"
    RC_FILE=""
    if [ "$SHELL_NAME" = "zsh" ]; then
        RC_FILE="${HOME}/.zshrc"
    elif [ "$SHELL_NAME" = "bash" ]; then
        RC_FILE="${HOME}/.bashrc"
    elif [ -f "${HOME}/.profile" ]; then
        RC_FILE="${HOME}/.profile"
    fi

    if [ -n "$RC_FILE" ]; then
        echo -e "\n${CYAN}→ Adding ~/.local/bin to PATH in ${BOLD}${RC_FILE}${RESET}..."
        echo '' >> "$RC_FILE"
        echo '# music-cli path' >> "$RC_FILE"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$RC_FILE"
        PATH_UPDATED=1
    fi
fi

# 7. Success message
echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${GREEN}🎉 music-cli installed successfully!${RESET}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

if [ "$PATH_UPDATED" -eq 1 ]; then
    echo -e "${YELLOW}Notice: PATH updated. Run this command or restart your terminal:${RESET}"
    echo -e "  ${BOLD}source $RC_FILE${RESET}\n"
fi

echo -e "To launch music-cli, simply type:"
echo -e "  ${BOLD}${CYAN}music${RESET}\n"
