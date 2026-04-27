#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SagTask — One-line installer for Hermes Agent
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
#
# Or download and run locally:
#   chmod +x install.sh && ./install.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PLUGIN_DIR="${HOME}/.hermes/plugins/sagtask"
REPO_URL="https://github.com/ethanchen669/sagtask.git"
HERMES_PLUGINS="${HOME}/.hermes/plugins"

echo "→ SagTask installer"
echo ""

# ── Detect install mode ────────────────────────────────────────────────────

if [[ -d "$PLUGIN_DIR" ]]; then
    if [[ -d "${PLUGIN_DIR}/.git" ]]; then
        echo "✓ ${PLUGIN_DIR} already exists (git clone)"
        echo "  Pulling latest changes..."
        cd "$PLUGIN_DIR"
        git pull origin main
        echo "✓ Updated to $(git log -1 --oneline)"
    else
        echo "✗ ${PLUGIN_DIR} exists but is not a git clone."
        echo "  Remove it first: rm -rf ${PLUGIN_DIR}"
        exit 1
    fi
else
    echo "→ Cloning SagTask into ${PLUGIN_DIR}..."
    mkdir -p "$HERMES_PLUGINS"
    git clone "$REPO_URL" "$PLUGIN_DIR"
    echo "✓ Cloned $(git -C "$PLUGIN_DIR" log -1 --oneline)"
fi

# ── Verify ────────────────────────────────────────────────────────────────

if [[ ! -f "${PLUGIN_DIR}/__init__.py" ]]; then
    echo "✗ __init__.py not found — installation may be corrupt."
    exit 1
fi

if [[ ! -f "${PLUGIN_DIR}/plugin.yaml" ]]; then
    echo "✗ plugin.yaml not found — this may not be a SagTask installation."
    exit 1
fi

echo "✓ Plugin files verified"

# ── Check if gateway is running ──────────────────────────────────────────

if pgrep -f "hermes.*gateway" > /dev/null 2>&1; then
    echo ""
    echo "⚠  Hermes gateway is running."
    echo "   Restart it to load the new plugin:"
    echo ""
    echo "   hermes gateway restart"
    echo "   # or"
    echo "   pkill -f hermes.*gateway && hermes gateway run"
else
    echo "✓ No gateway process detected (not running or not installed as a daemon)."
fi

echo ""
echo "✓ SagTask installed successfully!"
echo ""
echo "Next: Start/restart your Hermes gateway, then type 'task_list' to verify."
