#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SagTask — One-line installer for Hermes Agent
#
# Downloads the pre-built sagtask.tar.gz from GitHub releases and extracts
# it to ~/.hermes/plugins/sagtask/. Supports checksum verification and
# version detection to skip redundant installs.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
#
# Or download and run locally:
#   chmod +x install.sh && ./install.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

OWNER="ethanchen669"
REPO="sagtask"
PLUGIN_DIR="${HOME}/.hermes/plugins/sagtask"
TMPDIR=$(mktemp -d)

cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

echo "→ SagTask installer"
echo ""

# ── Detect existing installation ────────────────────────────────────────────

if [[ -d "$PLUGIN_DIR" ]]; then
    if [[ -e "$PLUGIN_DIR/.git" ]]; then
        echo "  Replacing existing git installation with release version..."
        rm -rf "$PLUGIN_DIR"
    else
        CURRENT_VER=""
        [[ -f "$PLUGIN_DIR/VERSION" ]] && CURRENT_VER=$(cat "$PLUGIN_DIR/VERSION")
    fi
fi

# ── Fetch latest release info ───────────────────────────────────────────────

AUTH_HEADER=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    AUTH_HEADER=(-H "Authorization: token ${GITHUB_TOKEN}")
elif command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    GH_TOKEN=$(gh auth token 2>/dev/null || true)
    [[ -n "${GH_TOKEN:-}" ]] && AUTH_HEADER=(-H "Authorization: token ${GH_TOKEN}")
fi

RELEASE_JSON=$(curl -fsSL "${AUTH_HEADER[@]}" "https://api.github.com/repos/${OWNER}/${REPO}/releases/latest" 2>&1) || {
    echo "✗ Failed to fetch release info (GitHub API rate limit or network error)."
    echo "  Fix: export GITHUB_TOKEN=<your-token> and retry, or install gh CLI."
    exit 1
}
VERSION=$(echo "$RELEASE_JSON" | grep -o '"tag_name": "[^"]*"' | cut -d'"' -f4)

if [[ -z "$VERSION" ]]; then
    echo "✗ No release found. Check https://github.com/${OWNER}/${REPO}/releases"
    exit 1
fi

if [[ "${CURRENT_VER:-}" == "${VERSION#v}" ]]; then
    echo "✓ Already at latest version (${VERSION}). Nothing to do."
    exit 0
fi

echo "  Version: ${VERSION}${CURRENT_VER:+ (upgrading from ${CURRENT_VER})}"

# ── Download release asset ──────────────────────────────────────────────────

ASSET_URL=$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": "[^"]*sagtask-[^"]*\.tar\.gz"' | cut -d'"' -f4)

if [[ -z "$ASSET_URL" ]]; then
    # Fallback: use source tarball if no asset uploaded
    echo "  ⚠ No release asset found, falling back to source tarball..."
    ASSET_URL=$(echo "$RELEASE_JSON" | grep -o '"tarball_url": "[^"]*"' | cut -d'"' -f4)
    USE_SOURCE_TARBALL=true
else
    USE_SOURCE_TARBALL=false
fi

echo "→ Downloading..."
curl -fsSL "$ASSET_URL" -o "$TMPDIR/sagtask.tar.gz"

# ── Verify checksum (if available) ──────────────────────────────────────────

SHA_URL=$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": "[^"]*\.sha256"' | cut -d'"' -f4)
if [[ -n "${SHA_URL:-}" ]]; then
    curl -fsSL "$SHA_URL" -o "$TMPDIR/expected.sha256"
    EXPECTED=$(cat "$TMPDIR/expected.sha256" | cut -d' ' -f1)
    ACTUAL=$(sha256sum "$TMPDIR/sagtask.tar.gz" | cut -d' ' -f1)
    if [[ "$EXPECTED" != "$ACTUAL" ]]; then
        echo "✗ Checksum mismatch!"
        echo "  Expected: ${EXPECTED}"
        echo "  Got:      ${ACTUAL}"
        exit 1
    fi
    echo "  ✓ Checksum verified"
fi

# ── Extract ─────────────────────────────────────────────────────────────────

cd "$TMPDIR"
tar -xzf sagtask.tar.gz

if [[ "$USE_SOURCE_TARBALL" == "true" ]]; then
    # Source tarball: find src/sagtask/ inside
    EXTRACT_DIR=$(find . -mindepth 1 -maxdepth 1 -type d | head -1)
    SOURCE_DIR="${EXTRACT_DIR}/src/sagtask"
else
    # Release asset: sagtask/ is at root of tarball
    SOURCE_DIR="./sagtask"
fi

if [[ ! -f "${SOURCE_DIR}/__init__.py" ]]; then
    echo "✗ Invalid archive structure: __init__.py not found"
    exit 1
fi

# ── Install ─────────────────────────────────────────────────────────────────

rm -rf "$PLUGIN_DIR"
mkdir -p "$(dirname "$PLUGIN_DIR")"
cp -r "$SOURCE_DIR" "$PLUGIN_DIR"

# ── Enable in config ────────────────────────────────────────────────────────

CONFIG_FILE="${HOME}/.hermes/config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    if ! grep -q "sagtask" "$CONFIG_FILE" 2>/dev/null; then
        echo "  → Adding 'sagtask' to plugins.enabled in config.yaml"
        echo "  ⚠ Please verify sagtask is in plugins.enabled in ${CONFIG_FILE}"
    fi
else
    echo "  ⚠ No config.yaml found. Add 'sagtask' to plugins.enabled after setup."
fi

# ── Verify ──────────────────────────────────────────────────────────────────

echo "→ Verifying installation..."
[[ -f "${PLUGIN_DIR}/__init__.py" ]] || { echo "✗ __init__.py missing"; exit 1; }
[[ -f "${PLUGIN_DIR}/plugin.yaml" ]] || { echo "✗ plugin.yaml missing"; exit 1; }
echo "  ✓ Files verified"

# ── Done ────────────────────────────────────────────────────────────────────

if pgrep -f "hermes.*gateway" > /dev/null 2>&1; then
    echo ""
    echo "  ⚠ Hermes gateway is running. Restart to load plugin:"
    echo "    hermes gateway restart"
fi

echo ""
echo "✓ SagTask ${VERSION} installed → ${PLUGIN_DIR}"
