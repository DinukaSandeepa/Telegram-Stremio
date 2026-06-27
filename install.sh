#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/weebzone/Telegram-Stremio"
REPO_BRANCH="${REPO_BRANCH:-dev}"
INSTALL_DIR="${INSTALL_DIR:-/opt/telegram-stremio}"

C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'; C_RED=$'\033[31m'

info()  { echo "${C_BLUE}::${C_RESET} $*"; }
ok()    { echo "${C_GREEN}✓${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}!${C_RESET} $*"; }
die()   { echo "${C_RED}✗ $*${C_RESET}" >&2; exit 1; }

if [ -e /dev/tty ]; then TTY=/dev/tty; else TTY=/dev/stdin; fi

banner() {
cat <<'EOF'

  ╔════════════════════════════════════════════╗
  ║        Telegram-Stremio  Installer          ║
  ║      self-hosted media server for Stremio   ║
  ╚════════════════════════════════════════════╝

EOF
}

require_root() {
  [ "$(id -u)" -eq 0 ] || die "Please run as root (use sudo)."
}

detect_os() {
  [ -r /etc/os-release ] || die "Unsupported OS (no /etc/os-release)."
  . /etc/os-release
  OS_ID="${ID:-}"; OS_LIKE="${ID_LIKE:-}"
  case "$OS_ID $OS_LIKE" in
    *debian*|*ubuntu*) ok "Detected ${PRETTY_NAME:-$OS_ID}" ;;
    *) warn "Untested OS (${PRETTY_NAME:-$OS_ID}); continuing anyway." ;;
  esac
}

ensure_pkg() {
  local pkg="$1"
  command -v "$pkg" >/dev/null 2>&1 && return 0
  info "Installing $pkg ..."
  apt-get update -qq
  apt-get install -y -qq "$pkg"
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    ok "Docker already installed."
  else
    info "Installing Docker ..."
    curl -fsSL https://get.docker.com | sh
    ok "Docker installed."
  fi
  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    die "Docker Compose plugin not found after install."
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
}

fetch_repo() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing install at $INSTALL_DIR ..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_BRANCH"
    git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"
  else
    info "Cloning into $INSTALL_DIR ..."
    git clone --depth 1 -b "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi
  ok "Source ready."
}

ask() {
  local prompt="$1" default="${2:-}" silent="${3:-}" var
  while :; do
    if [ -n "$default" ]; then
      printf "%s [%s]: " "$prompt" "$default" >"$TTY"
    else
      printf "%s: " "$prompt" >"$TTY"
    fi
    if [ "$silent" = "secret" ]; then
      read -r var <"$TTY"; echo >"$TTY"
    else
      read -r var <"$TTY"
    fi
    var="${var:-$default}"
    if [ -z "$var" ]; then warn "This value is required." >"$TTY"; continue; fi
    REPLY_VALUE="$var"; return 0
  done
}

ask_optional() {
  printf "%s (optional, press Enter to skip): " "$1" >"$TTY"
  local var; read -r var <"$TTY"
  REPLY_VALUE="$var"
}

configure() {
  local cfg="$INSTALL_DIR/config.env"
  if [ -f "$cfg" ]; then
    printf "%s" "config.env already exists. Overwrite? [y/N]: " >"$TTY"
    local a; read -r a <"$TTY"
    case "$a" in y|Y) ;; *) warn "Keeping existing config.env."; return 0 ;; esac
  fi

  echo >"$TTY"
  info "Enter your configuration. Values come from the README setup guide." >"$TTY"
  echo >"$TTY"

  ask "API_ID (from my.telegram.org)"; local API_ID="$REPLY_VALUE"
  ask "API_HASH (from my.telegram.org)"; local API_HASH="$REPLY_VALUE"
  ask "BOT_TOKEN (from @BotFather)"; local BOT_TOKEN="$REPLY_VALUE"
  ask "OWNER_ID (your numeric Telegram ID)"; local OWNER_ID="$REPLY_VALUE"
  ask "DATABASE (two MongoDB URIs, comma-separated)"; local DATABASE="$REPLY_VALUE"
  ask "PORT" "8000"; local PORT="$REPLY_VALUE"
  ask_optional "USER_SESSION_STRING (only for Global Search)"; local USER_SESSION_STRING="$REPLY_VALUE"

  cat >"$cfg" <<EOF
API_ID="$API_ID"
API_HASH="$API_HASH"
BOT_TOKEN="$BOT_TOKEN"
USER_SESSION_STRING="$USER_SESSION_STRING"
OWNER_ID="$OWNER_ID"
DATABASE="$DATABASE"
PORT="$PORT"
EOF
  chmod 600 "$cfg"
  CFG_PORT="$PORT"
  ok "Wrote $cfg"
}

launch() {
  info "Building and starting the container ..."
  ( cd "$INSTALL_DIR" && $COMPOSE up -d --build )
  ok "Container is up."
}

finish() {
  local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$ip" ] || ip="<your-server-ip>"
  echo
  echo "${C_GREEN}${C_BOLD}Installation complete!${C_RESET}"
  echo
  echo "  Web panel : ${C_BOLD}http://$ip:${CFG_PORT:-8000}${C_RESET}"
  echo "  Login     : admin / admin  ${C_YELLOW}(change this first!)${C_RESET}"
  echo "  Addon URL : http://$ip:${CFG_PORT:-8000}/stremio/manifest.json"
  echo
  echo "  Manage with:"
  echo "    cd $INSTALL_DIR && $COMPOSE logs -f       # view logs"
  echo "    cd $INSTALL_DIR && $COMPOSE restart       # restart"
  echo "    cd $INSTALL_DIR && $COMPOSE down          # stop"
  echo
}

main() {
  banner
  require_root
  detect_os
  ensure_pkg curl
  ensure_pkg git
  ensure_docker
  fetch_repo
  configure
  launch
  finish
}

main "$@"
