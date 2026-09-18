#!/usr/bin/env sh
# Smoke: prove pacman-key init/populate order before package install.
# Intended for Arch containers (and Deck-like images). No SteamOS helpers required.
#
#   docker run --rm -v "$PWD:/src:ro" -w /src archlinux:latest \
#     sh scripts/smoke-pacman-keyring.sh
#
# Exit 0 only if keyring setup + a signed pacman install succeed.

set -eu

info() { printf '%s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

keyring_files_exist() {
  _kr=$1
  [ -d /usr/share/pacman/keyrings ] || return 1
  [ -e "/usr/share/pacman/keyrings/${_kr}.gpg" ] && return 0
  [ -e "/usr/share/pacman/keyrings/${_kr}-revoked" ] && return 0
  for _f in /usr/share/pacman/keyrings/"${_kr}"*; do
    [ -e "$_f" ] && return 0
  done
  return 1
}

have_cmd pacman || die "pacman missing — run inside Arch/SteamOS"
have_cmd pacman-key || die "pacman-key missing"

info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  Distillery Expo — pacman keyring smoke"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "  host: $(uname -a 2>/dev/null || echo unknown)"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  info "  os-release ID=${ID:-?} VERSION_ID=${VERSION_ID:-?}"
fi
info "  keyrings dir:"
ls -la /usr/share/pacman/keyrings 2>/dev/null | sed 's/^/    /' || info "    (missing)"

info ""
info "[1/4] pacman-key --init"
pacman-key --init
info "  OK"

info "[2/4] pacman-key --populate (archlinux / steamos / holo if present)"
_populated=0
for _kr in archlinux steamos holo; do
  if keyring_files_exist "$_kr"; then
    info "  populate ${_kr} …"
    pacman-key --populate "$_kr"
    info "  populate ${_kr} OK"
    _populated=1
  else
    info "  skip ${_kr} (no keyring files)"
  fi
done
if [ "$_populated" = "0" ]; then
  info "  fallback populate archlinux …"
  pacman-key --populate archlinux
  _populated=1
fi
[ "$_populated" = "1" ] || die "no keyring populated"

info "[3/4] pacman -Sy (refresh DBs with signatures)"
pacman -Sy --noconfirm

info "[4/4] pacman install smoke package (which)"
# Prefer a tiny already-common package; --needed keeps re-runs cheap
pacman -S --needed --noconfirm which
have_cmd which || die "which still missing after pacman install"
info "  which → $(command -v which)"

info ""
info "SMOKE PASS: keyring init → populate → signed pacman install OK"
exit 0
