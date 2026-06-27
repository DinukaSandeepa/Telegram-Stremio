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

banner() {
cat <<'EOF'

  ╔════════════════════════════════════════════╗
  ║        Telegram-Stremio  Installer          ║
  ║   self-hosted media server for Stremio      ║
  ╚════════════════════════════════════════════╝

EOF
}

require_root() { [ "$(id -u)" -eq 0 ] || die "Please run as root (use sudo)."; }

detect_os() {
  [ -r /etc/os-release ] || die "Unsupported OS (no /etc/os-release)."
  . /etc/os-release
  case "${ID:-} ${ID_LIKE:-}" in
    *debian*|*ubuntu*) ok "Detected ${PRETTY_NAME:-$ID}" ;;
    *) warn "Untested OS (${PRETTY_NAME:-$ID}); continuing." ;;
  esac
}

ensure_pkg() {
  command -v "$1" >/dev/null 2>&1 && return 0
  info "Installing $1 ..."
  apt-get update -qq && apt-get install -y -qq "$1"
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    ok "Docker already installed."
  else
    info "Installing Docker ..."
    curl -fsSL https://get.docker.com | sh
    ok "Docker installed."
  fi
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
  else die "Docker Compose not found."; fi
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

launch() {
  [ -f "$INSTALL_DIR/config.env" ] || : > "$INSTALL_DIR/config.env"
  info "Building and starting the container ..."
  ( cd "$INSTALL_DIR" && $COMPOSE up -d --build )
  ok "Container is up."
}

finish() {
  local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$ip" ] || ip="<your-server-ip>"
  echo
  echo "${C_GREEN}${C_BOLD}Deployment complete!${C_RESET}"
  echo
  echo "  ${C_BOLD}Open the setup wizard in your browser:${C_RESET}"
  echo "    ${C_BLUE}http://$ip:8000${C_RESET}"
  echo
  echo "  Fill in your Telegram + database details there and click Save."
  echo "  The server configures itself and restarts automatically."
  echo
  echo "  Manage with:"
  echo "    cd $INSTALL_DIR && $COMPOSE logs -f     # view logs"
  echo "    cd $INSTALL_DIR && $COMPOSE restart     # restart"
  echo "    cd $INSTALL_DIR && $COMPOSE down        # stop"
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
  launch
  finish
}

main "$@"
