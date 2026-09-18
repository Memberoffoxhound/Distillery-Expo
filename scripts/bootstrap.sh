#!/usr/bin/env sh
# Distillery Expo — one-curl bootstrap (system toolchain + deps + Expo)
#
# Phil bar: one curl|sh that installs everything with progress and lands in Expo.
#
#   curl -fsSL https://raw.githubusercontent.com/Memberoffoxhound/Distillery-Expo/main/scripts/bootstrap.sh | sh
#
# Or after clone:
#   ./scripts/bootstrap.sh
#
# Design:
#   - Fedora-first (dnf + sudo) with clear [N/M] progress — never silent
#   - Portable toward macOS (Darwin + brew); friendly message if brew missing
#   - No apt-only paths, no glibc-only assumptions
#   - Safe to re-run
#   - If already inside Distillery-Expo, use it; else clone to ~/Distillery-Expo
#     (or $DISTILLERY_HOME)
#
# Private-repo note: curl raw / git clone may need `gh auth login` or a token.

set -eu

TOTAL_STEPS=6
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

REPO_URL="${DISTILLERY_REPO_URL:-https://github.com/Memberoffoxhound/Distillery-Expo.git}"
HOME_DIR="${HOME:-/tmp}"
DEFAULT_HOME="${DISTILLERY_HOME:-$HOME_DIR/Distillery-Expo}"

OS=$(detect_os)

info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  Distillery Expo — bootstrap (os=$OS)"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "This installs system tools (if needed), repo deps, and starts Expo."
info "Safe to re-run. Progress is printed at each step."
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
        die "git clone failed. Private repo? Run: gh auth login   (or set a token / GIT_ASKPASS) then retry."
      fi
      ROOT=$(CDPATH= cd -- "$DEFAULT_HOME" && pwd)
    else
      die "git is missing and Distillery-Expo is not present. Install git, then re-run bootstrap."
    fi
  fi
fi

cd "$ROOT"
info "  Repo root: $ROOT"

# --- [2] System toolchain ---
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

# pip: either pip3 or ensurepip/venv will provide it later — still install pip pkgs on Fedora
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
      if is_fedora_like || have_cmd dnf; then
        DNF=dnf
        have_cmd dnf || DNF=microdnf
        pkgs=""
        [ "$need_python" = "1" ] && pkgs="$pkgs python3"
        [ "$need_pip" = "1" ] && pkgs="$pkgs python3-pip"
        [ "$need_venv" = "1" ] && pkgs="$pkgs python3-pip"
        # Fedora: python3-venv is often part of python3; ensure pip + ensurepip path
        # Also install python3-devel is NOT required for venv on Fedora typically
        # Explicit: python3 + python3-pip covers venv on modern Fedora
        [ "$need_node" = "1" ] && pkgs="$pkgs nodejs"
        [ "$need_npm" = "1" ] && pkgs="$pkgs npm"
        # Always include python3-pip when any python piece missing
        case " $pkgs " in
          *" python3 "*|*" python3-pip "*) ;;
        esac
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
        # Deduplicate spaces
        pkgs=$(printf '%s' "$pkgs" | tr -s ' ' | sed 's/^ //;s/ $//')
        info "  Fedora/dnf install: $pkgs"
        info "  (may prompt for sudo password)"
        # shellcheck disable=SC2086
        if have_cmd sudo; then
          sudo "$DNF" install -y $pkgs
        else
          "$DNF" install -y $pkgs
        fi
      else
        die "Missing python3/node/npm and no dnf found. On Fedora: sudo dnf install python3 python3-pip nodejs npm. On macOS: install Homebrew then re-run. Or install the tools manually and re-run ./scripts/bootstrap.sh / ./scripts/dev-up."
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
  python3 -c "import venv" 2>/dev/null || die "python3 venv module still missing (try: sudo dnf install python3 python3-pip)"
  info "  Installed OK:"
  info "    python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  info "    node $(node -v) · npm $(npm -v)"
fi

# --- [3] Python venv ---
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

# --- [4] pip install ---
step "Install Python package (pip install -e \".[dev]\")"

info "  Upgrading pip …"
python -m pip install --upgrade pip
info "  Installing editable package + dev extras (this may take a minute) …"
python -m pip install -e ".[dev]"
info "  Python deps ready."

# --- [5] npm install ---
step "Install web deps (npm install in apps/web)"

WEB_DIR="$ROOT/apps/web"
if [ ! -d "$WEB_DIR" ]; then
  die "apps/web missing under $ROOT — checkout looks incomplete"
fi
info "  Running npm install in $WEB_DIR …"
(cd "$WEB_DIR" && npm install)
info "  Web deps ready."

# --- [6] Launch Expo via dev-up ---
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
