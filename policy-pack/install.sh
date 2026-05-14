#!/usr/bin/env bash
# Apohara Aegis — Veea Policy Pack for Regulated Agents
# Installer v0.1.0
#
# Usage: ./install.sh [--dest <dir>]
#   --dest  Installation directory (default: ./apohara-aegis-pack)
#
# Prerequisites: python 3.11+, go 1.22+ (to build Lobster Trap), curl
# Lobster Trap has no pre-built binary releases; this script clones and
# builds from source.  If go is not installed, the script will exit with
# a clear error rather than pretending to download a binary.

set -euo pipefail

DEST="${1:-}"
if [[ "$DEST" == "--dest" ]]; then
  DEST="${2:-./apohara-aegis-pack}"
fi
DEST="${DEST:-./apohara-aegis-pack}"

LT_REPO="https://github.com/veeainc/lobstertrap"
POLICY_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/policy.yaml"
LOG_PREFIX="[apohara-aegis-pack]"

info()  { echo "${LOG_PREFIX} $*"; }
warn()  { echo "${LOG_PREFIX} WARNING: $*" >&2; }
abort() { echo "${LOG_PREFIX} ERROR: $*" >&2; exit 1; }

# ── 1. Prerequisite checks ────────────────────────────────────────────────────

check_python() {
  local py_bin
  py_bin=$(command -v python3 2>/dev/null || true)
  [[ -z "$py_bin" ]] && abort "python3 not found. Install Python 3.11+."
  local version
  version=$("$py_bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  local major minor
  major=$(echo "$version" | cut -d. -f1)
  minor=$(echo "$version" | cut -d. -f2)
  [[ "$major" -lt 3 || ( "$major" -eq 3 && "$minor" -lt 11 ) ]] \
    && abort "Python 3.11+ required, found $version."
  info "Python $version — OK"
}

check_go() {
  command -v go &>/dev/null \
    || abort "go not found. Install Go 1.22+ from https://go.dev/dl/ — required to build Lobster Trap from source."
  local goversion
  goversion=$(go version | awk '{print $3}' | sed 's/go//')
  info "Go $goversion — OK"
}

check_curl() {
  command -v curl &>/dev/null || abort "curl not found. Install curl."
  info "curl — OK"
}

check_git() {
  command -v git &>/dev/null || abort "git not found. Install git."
  info "git — OK"
}

info "Checking prerequisites..."
check_python
check_go
check_curl
check_git

# ── 2. Build Lobster Trap from source ────────────────────────────────────────

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Cloning Lobster Trap from $LT_REPO ..."
git clone --depth 1 "$LT_REPO" "$TMPDIR/lobstertrap" 2>&1 | sed "s/^/${LOG_PREFIX} /"

info "Building static binary (go build)..."
pushd "$TMPDIR/lobstertrap" > /dev/null
  # Try Makefile target first; fall back to plain go build.
  if make build-static 2>/dev/null; then
    LT_BINARY="$(find . -name 'lobstertrap' -type f | head -1)"
  else
    go build -o lobstertrap ./...
    LT_BINARY="./lobstertrap"
  fi
popd > /dev/null

[[ -z "${LT_BINARY:-}" || ! -f "$TMPDIR/lobstertrap/$LT_BINARY" ]] \
  && abort "Build succeeded but binary not found. Check $TMPDIR/lobstertrap."

info "Build succeeded."

# ── 3. Install ────────────────────────────────────────────────────────────────

mkdir -p "$DEST"
cp "$TMPDIR/lobstertrap/$LT_BINARY" "$DEST/lobstertrap"
chmod +x "$DEST/lobstertrap"
cp "$POLICY_FILE" "$DEST/policy.yaml"

info "Installed to $DEST/"
info "  $DEST/lobstertrap  — proxy binary"
info "  $DEST/policy.yaml  — Aegis policy (9 ingress + 2 egress rules)"

# ── 4. Final instructions ─────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────────────────────"
echo "  Apohara Aegis policy pack installed."
echo ""
echo "  Start the proxy in front of your LLM backend:"
echo ""
echo "    $DEST/lobstertrap serve \\"
echo "      --policy  $DEST/policy.yaml \\"
echo "      --backend http://localhost:8000 \\"
echo "      --listen  :8080"
echo ""
echo "  Then point agents at http://localhost:8080 instead of the"
echo "  backend directly.  All requests are inspected; the audit log"
echo "  is written to stdout (redirect to a file for persistence)."
echo ""
echo "  Verify the proxy is live:"
echo "    curl -s http://localhost:8080/healthz"
echo ""
echo "  See policy-pack/README.md for curl-based attack verification."
echo "─────────────────────────────────────────────────────────────────"
