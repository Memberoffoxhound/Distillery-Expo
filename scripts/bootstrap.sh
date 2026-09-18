#!/usr/bin/env sh
# Distillery Expo — bootstrap (system toolchain + deps + Expo)
#
# Bare-machine one-liner (or local ./scripts/bootstrap.sh) that installs
# everything with progress and lands in Expo:
#
#   curl -fsSL https://raw.githubusercontent.com/Memberoffoxhound/Distillery-Expo/main/scripts/bootstrap.sh | sh
#
# Or after clone (update-aware):
#   ./scripts/bootstrap.sh
#
# Design:
#   - Fedora-first (dnf + sudo) with clear [N/M] progress — never silent
#   - Steam Deck / SteamOS / Arch (pacman); macOS (Darwin + brew)
#   - No apt-only paths, no glibc-only assumptions
#   - Safe to re-run
#   - If already inside Distillery-Expo (or $DISTILLERY_HOME), use it and
#     git fetch + pull --ff-only before refreshing deps; else clone to ~/Distillery-Expo

set -eu

TOTAL_STEPS=7
STEP=0

info()  { printf '%s\n' "$*"; }
warn()  { printf 'warn: %s\n' "$*" >&2; }
die()   { printf 'error: %s\n' "$*" >&2; exit 1; }

step() {
  STEP=$((STEP + 1))
  printf '\n[%s/%s] %s\n' "$STEP" "$TOTAL_STEPS" "$*"
}

detect_os() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux*)  echo linux ;;
    Darwin*) echo macos ;;
    *)       echo other ;;
  esac
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

# Fedora / RHEL-ish: dnf present (prefer over apt — never apt-only)
is_fedora_like() {
  have_cmd dnf || have_cmd microdnf || {
    [ -f /etc/fedora-release ] || [ -f /etc/redhat-release ]
  }
}

# SteamOS / Arch / EndeavourOS / Manjaro / CachyOS / etc.
os_release_id() {
  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf '%s' "${ID:-}"
  fi
}

os_release_id_like() {
  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf '%s' "${ID_LIKE:-}"
  fi
}

is_arch_like() {
  have_cmd pacman || {
    _id=$(os_release_id)
    _like=$(os_release_id_like)
    case "$_id" in
      steamos|arch|endeavouros|manjaro|cachyos|garuda|archarm) return 0 ;;
    esac
    case " $_like " in
      *" arch "*|*" archlinux "*) return 0 ;;
    esac
    return 1
  }
}

is_steamos() {
  _id=$(os_release_id)
  [ "$_id" = "steamos" ] && return 0
  # Deck often exposes steamos even when ID is steamos; also check helper
  have_cmd steamos-readonly && return 0
  return 1
}

maybe_disable_steamos_readonly() {
  if ! have_cmd steamos-readonly; then
    return 0
  fi
  # Steam Deck ships a read-only root; pacman needs it writable.
  info "  SteamOS detected — ensuring writable root (steamos-readonly disable) …"
  info "  (may prompt for sudo password; Steam Deck default password is often empty / set by you)"
  if have_cmd sudo; then
    if ! sudo steamos-readonly disable; then
      warn "  steamos-readonly disable failed — if pacman fails, run: sudo steamos-readonly disable"
    else
      info "  steamos-readonly: disabled for this install"
    fi
  else
    if ! steamos-readonly disable; then
      warn "  steamos-readonly disable failed — run as root or with sudo, then re-run bootstrap"
    fi
  fi
}

# Run pacman / pacman-key as root when sudo exists (Deck Desktop).
pacman_sudo() {
  if have_cmd sudo; then
    sudo "$@"
  else
    "$@"
  fi
}

# After steamos-readonly disable (or on a fresh Arch image), the keyring DB
# is often empty / not writable until init + populate. Must run before -Sy.
die_pacman_keyring_help() {
  die "pacman keyring / package install failed (common on Steam Deck after unlocking the read-only root).

On Steam Deck Desktop, fix the keyring, then re-run ./scripts/bootstrap.sh:

  sudo steamos-readonly disable
  sudo pacman-key --init
  sudo pacman-key --populate archlinux
  # if these keyrings exist on your Deck:
  sudo pacman-key --populate steamos
  sudo pacman-key --populate holo
  sudo pacman -Sy --needed python python-pip python-virtualenv nodejs npm

Prefer fixing pacman. If you must unblock without it: install Node LTS
(https://nodejs.org) and Python 3 with venv another way, then re-run
./scripts/bootstrap.sh (it will skip toolchain install when tools are present)."
}

keyring_files_exist() {
  _kr=$1
  [ -d /usr/share/pacman/keyrings ] || return 1
  [ -e "/usr/share/pacman/keyrings/${_kr}.gpg" ] && return 0
  [ -e "/usr/share/pacman/keyrings/${_kr}-revoked" ] && return 0
  # Some images ship a directory or multiple files prefixed by the name
  for _f in /usr/share/pacman/keyrings/"${_kr}"*; do
    [ -e "$_f" ] && return 0
  done
  return 1
}

ensure_pacman_keyring() {
  info "  pacman keyring: init …"
  if ! pacman_sudo pacman-key --init; then
    warn "  pacman-key --init failed"
    die_pacman_keyring_help
  fi
  info "  pacman keyring: init OK"

  _populated=0
  for _kr in archlinux steamos holo; do
    if keyring_files_exist "$_kr"; then
      info "  pacman keyring: populate ${_kr} …"
      if pacman_sudo pacman-key --populate "$_kr"; then
        info "  pacman keyring: populate ${_kr} OK"
        _populated=1
      else
        warn "  pacman-key --populate ${_kr} failed"
      fi
    fi
  done

  # Fresh Arch containers always expect archlinux; try once more if nothing matched.
  if [ "$_populated" = "0" ]; then
    info "  pacman keyring: populate archlinux (no keyring files detected earlier) …"
    if pacman_sudo pacman-key --populate archlinux; then
      info "  pacman keyring: populate archlinux OK"
      _populated=1
    else
      warn "  pacman-key --populate archlinux failed"
    fi
  fi

  if [ "$_populated" = "0" ]; then
    die_pacman_keyring_help
  fi
}

die_missing_pkg_manager() {
  die "Missing python3/node/npm and no supported package manager found.

Install the toolchain, then re-run ./scripts/bootstrap.sh (or ./scripts/dev-up):

  Fedora / RHEL:   sudo dnf install -y python3 python3-pip nodejs npm
  Arch / SteamOS:  sudo steamos-readonly disable   # Steam Deck only
                   sudo pacman-key --init
                   sudo pacman-key --populate archlinux
                   sudo pacman -Sy --needed python python-pip python-virtualenv nodejs npm
  macOS:           brew install python node
                   (install Homebrew from https://brew.sh if needed)

Or install python3, pip/venv, node, and npm another way, then re-run."
}

REPO_URL="${DISTILLERY_REPO_URL:-https://github.com/Memberoffoxhound/Distillery-Expo.git}"
HOME_DIR="${HOME:-/tmp}"
DEFAULT_HOME="${DISTILLERY_HOME:-$HOME_DIR/Distillery-Expo}"

OS=$(detect_os)

info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  Distillery Expo — bootstrap (os=$OS)"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "This updates an existing install (or clones), installs system tools if needed,"
info "refreshes deps, and starts Expo. Safe to re-run. Progress at each step."
info ""

# --- [1] Resolve repo root (clone if needed) ---
step "Locate Distillery-Expo checkout"

ROOT=""

# Prefer: script lives inside a real checkout (./scripts/bootstrap.sh)
# When piped via curl|sh, $0 is often "sh" and this path does not exist.
case "$0" in
  */bootstrap.sh|bootstrap.sh)
    _script_dir=$(CDPATH= cd -- "$(dirname "$0")" 2>/dev/null && pwd) || _script_dir=""
    if [ -n "$_script_dir" ] && [ -f "$_script_dir/../pyproject.toml" ] \
      && [ -f "$_script_dir/../apps/web/package.json" ]; then
      ROOT=$(CDPATH= cd -- "$_script_dir/.." && pwd)
      info "  Using existing checkout (via script path): $ROOT"
    fi
    ;;
esac

# Prefer: already cwd inside the repo
if [ -z "$ROOT" ] && [ -f "./pyproject.toml" ] && [ -f "./apps/web/package.json" ] \
  && [ -f "./scripts/dev-up" ]; then
  ROOT=$(CDPATH= cd -- . && pwd)
  info "  Using current directory: $ROOT"
fi

# Prefer: DISTILLERY_HOME / default clone target already present
if [ -z "$ROOT" ] && [ -f "$DEFAULT_HOME/pyproject.toml" ] \
  && [ -f "$DEFAULT_HOME/apps/web/package.json" ]; then
  ROOT=$(CDPATH= cd -- "$DEFAULT_HOME" && pwd)
  info "  Using existing install at: $ROOT"
fi

# Else clone
if [ -z "$ROOT" ]; then
  info "  Not inside Distillery-Expo — cloning to $DEFAULT_HOME …"
  parent=$(dirname "$DEFAULT_HOME")
  mkdir -p "$parent"
  if [ -d "$DEFAULT_HOME/.git" ]; then
    ROOT=$(CDPATH= cd -- "$DEFAULT_HOME" && pwd)
    info "  Found incomplete/prior checkout — using $ROOT"
  else
    if have_cmd git; then
      info "  git clone $REPO_URL"
      if ! git clone --progress "$REPO_URL" "$DEFAULT_HOME"; then
        die "git clone failed. Check network access and the repository URL, then retry."
      fi
      ROOT=$(CDPATH= cd -- "$DEFAULT_HOME" && pwd)
    else
      die "git is missing and Distillery-Expo is not present. Install git, then re-run bootstrap."
    fi
  fi
fi

cd "$ROOT"
info "  Repo root: $ROOT"

# --- [2] Update existing checkout (git fetch + ff-only pull) ---
step "Update checkout (git fetch + pull --ff-only)"

update_existing_checkout() {
  if ! have_cmd git; then
    warn "  git not found — skipping update (deps refresh still runs)"
    return 0
  fi
  if [ ! -d "$ROOT/.git" ]; then
    info "  Not a git checkout — skipping pull (tarball / copied tree)"
    return 0
  fi
  info "  Fetching from remotes …"
  if ! git -C "$ROOT" fetch --all --prune --progress 2>&1; then
    warn "  git fetch failed (offline / auth?) — continuing with local tree"
    return 0
  fi
  branch=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)
  info "  Branch: $branch"
  # Prefer fast-forward only so we never invent merges on a user tree
  if git -C "$ROOT" pull --ff-only --progress 2>&1; then
    info "  Checkout up to date (ff-only pull OK)"
    info "  HEAD: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  else
    warn "  ff-only pull failed (local commits / divergence?). Keeping local tree; resolve manually if needed."
    info "  HEAD remains: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  fi
}

update_existing_checkout

# --- [3] System toolchain ---
step "Check / install system toolchain (python3, pip, venv, node, npm)"

need_python=0
need_node=0
need_npm=0
need_venv=0

have_cmd python3 || need_python=1
have_cmd node || need_node=1
have_cmd npm || need_npm=1

# venv module: python3 -m venv must work
if have_cmd python3; then
  if ! python3 -c "import venv" 2>/dev/null; then
    need_venv=1
  fi
else
  need_venv=1
fi

# pip: either pip3 or ensurepip/venv will provide it later — still install pip pkgs when missing
need_pip=0
if have_cmd python3; then
  if ! python3 -m pip --version >/dev/null 2>&1 && ! have_cmd pip3; then
    need_pip=1
  fi
else
  need_pip=1
fi

install_needed=0
[ "$need_python" = "1" ] && install_needed=1
[ "$need_node" = "1" ] && install_needed=1
[ "$need_npm" = "1" ] && install_needed=1
[ "$need_venv" = "1" ] && install_needed=1
[ "$need_pip" = "1" ] && install_needed=1

if [ "$install_needed" = "0" ]; then
  info "  All system tools present:"
  info "    python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
  info "    node $(node -v 2>/dev/null || echo '?') · npm $(npm -v 2>/dev/null || echo '?')"
else
  info "  Missing tools — will install (progress below)."
  [ "$need_python" = "1" ] && info "    - python3"
  [ "$need_pip" = "1" ] && info "    - pip"
  [ "$need_venv" = "1" ] && info "    - venv"
  [ "$need_node" = "1" ] && info "    - nodejs"
  [ "$need_npm" = "1" ] && info "    - npm"

  case "$OS" in
    linux)
      if is_fedora_like || have_cmd dnf || have_cmd microdnf; then
        DNF=dnf
        have_cmd dnf || DNF=microdnf
        pkgs=""
        [ "$need_python" = "1" ] && pkgs="$pkgs python3"
        [ "$need_pip" = "1" ] && pkgs="$pkgs python3-pip"
        [ "$need_venv" = "1" ] && pkgs="$pkgs python3-pip"
        [ "$need_node" = "1" ] && pkgs="$pkgs nodejs"
        [ "$need_npm" = "1" ] && pkgs="$pkgs npm"
        if [ "$need_venv" = "1" ] || [ "$need_pip" = "1" ] || [ "$need_python" = "1" ]; then
          case " $pkgs " in
            *" python3 "*) ;;
            *) pkgs="python3 $pkgs" ;;
          esac
          case " $pkgs " in
            *" python3-pip "*) ;;
            *) pkgs="$pkgs python3-pip" ;;
          esac
        fi
        pkgs=$(printf '%s' "$pkgs" | tr -s ' ' | sed 's/^ //;s/ $//')
        info "  Fedora/dnf install: $pkgs"
        info "  (may prompt for sudo password)"
        # shellcheck disable=SC2086
        if have_cmd sudo; then
          sudo "$DNF" install -y $pkgs
        else
          "$DNF" install -y $pkgs
        fi
      elif is_arch_like || have_cmd pacman; then
        # Arch / Steam Deck (SteamOS) / EndeavourOS …
        # Packages: python (provides python3), python-pip, python-virtualenv, nodejs, npm
        pkgs=""
        if [ "$need_python" = "1" ] || [ "$need_pip" = "1" ] || [ "$need_venv" = "1" ]; then
          pkgs="$pkgs python python-pip python-virtualenv"
        fi
        if [ "$need_node" = "1" ] || [ "$need_npm" = "1" ]; then
          pkgs="$pkgs nodejs npm"
        fi
        pkgs=$(printf '%s' "$pkgs" | tr -s ' ' | sed 's/^ //;s/ $//')
        if [ -z "$pkgs" ]; then
          die "Internal: install needed but no pacman packages selected"
        fi
        if is_steamos || have_cmd steamos-readonly; then
          info "  Steam Deck / SteamOS — writable root, then keyring, then pacman"
          maybe_disable_steamos_readonly
        else
          info "  Arch/pacman install: $pkgs"
        fi
        # Keyring must be writable/populated before -Sy (Deck + fresh Arch).
        ensure_pacman_keyring
        info "  pacman -Sy --needed $pkgs"
        info "  (may prompt for sudo password)"
        # shellcheck disable=SC2086
        if ! pacman_sudo pacman -Sy --needed --noconfirm $pkgs; then
          warn "  pacman -Sy failed after keyring setup"
          die_pacman_keyring_help
        fi
      else
        die_missing_pkg_manager
      fi
      ;;
    macos)
      if have_cmd brew; then
        pkgs=""
        if [ "$need_python" = "1" ] || [ "$need_pip" = "1" ] || [ "$need_venv" = "1" ]; then
          pkgs="$pkgs python"
        fi
        if [ "$need_node" = "1" ] || [ "$need_npm" = "1" ]; then
          pkgs="$pkgs node"
        fi
        pkgs=$(printf '%s' "$pkgs" | tr -s ' ' | sed 's/^ //;s/ $//')
        if [ -z "$pkgs" ]; then
          die "Internal: install needed but no brew packages selected"
        fi
        info "  Homebrew install: $pkgs"
        # shellcheck disable=SC2086
        brew install $pkgs
      else
        die "macOS: Homebrew not found. Install from https://brew.sh then re-run:
  brew install python node
  ./scripts/bootstrap.sh"
      fi
      ;;
    *)
      die "Unsupported OS ($OS). Install python3, pip/venv, node, and npm, then re-run from the Distillery-Expo repo."
      ;;
  esac

  # Re-check
  have_cmd python3 || die "python3 still missing after install"
  have_cmd node || die "node still missing after install"
  have_cmd npm || die "npm still missing after install"
  python3 -c "import venv" 2>/dev/null || die "python3 venv module still missing (Fedora: sudo dnf install python3 python3-pip · Arch/SteamOS: sudo pacman -S python python-virtualenv)"
  info "  Installed OK:"
  info "    python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  info "    node $(node -v) · npm $(npm -v)"
fi

# --- [4] Python venv ---
step "Python virtualenv (.venv)"

VENV_DIR="${DISTILLERY_VENV:-$ROOT/.venv}"
if [ ! -d "$VENV_DIR" ]; then
  info "  Creating venv at $VENV_DIR …"
  python3 -m venv "$VENV_DIR"
else
  info "  venv already present at $VENV_DIR"
fi

# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"
info "  Using $(command -v python) ($(python -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"

# --- [5] pip install ---
step "Install Python package (pip install -e \".[dev]\")"

info "  Upgrading pip …"
python -m pip install --upgrade pip
info "  Installing editable package + dev extras (this may take a minute) …"
python -m pip install -e ".[dev]"
info "  Python deps ready."

# --- [6] npm install ---
step "Install web deps (npm install in apps/web)"

WEB_DIR="$ROOT/apps/web"
if [ ! -d "$WEB_DIR" ]; then
  die "apps/web missing under $ROOT — checkout looks incomplete"
fi
info "  Running npm install in $WEB_DIR …"
(cd "$WEB_DIR" && npm install)
info "  Web deps ready."

# --- [7] Launch Expo via dev-up ---
step "Start Expo (API + web) via scripts/dev-up"

if [ ! -x "$ROOT/scripts/dev-up" ]; then
  chmod +x "$ROOT/scripts/dev-up" 2>/dev/null || true
fi

# Toolchain is present; force reinstall flags off — deps just installed.
# dev-up is idempotent and prints the Expo URL.
info "  Handing off to ./scripts/dev-up …"
info ""
"$ROOT/scripts/dev-up"

info ""
info "Bootstrap finished. Open the Expo URL printed above."
info "Re-run anytime:  ./scripts/bootstrap.sh"
info "Day-to-day (toolchain already present):  ./scripts/dev-up"
