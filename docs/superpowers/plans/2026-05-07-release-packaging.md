# Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement dual-track release packaging (GitHub Release Asset + pip install) for SagTask, with automated builds, version management, and secure distribution.

**Architecture:** Build script creates minimal tarballs from runtime-only files. install.sh upgraded to download release assets with checksum verification. pyproject.toml restructured for hatchling build backend with entry-point plugin discovery. GitHub Actions automates release on tag push.

**Tech Stack:** Python (hatchling build), Bash (scripts), GitHub Actions CI/CD

---

## File Structure

```
sagtask/
├── src/sagtask/
│   ├── __init__.py          (existing, unchanged)
│   ├── plugin.yaml          (existing, unchanged)
│   └── VERSION              ← NEW: single-line version number
├── scripts/
│   ├── build-release.sh     ← NEW: build release tarball + checksum
│   └── bump-version.sh      ← NEW: sync version across files
├── install.sh               ← MODIFY: add asset download, checksum, version detection
├── pyproject.toml            ← MODIFY: hatchling backend, entry-points
├── CHANGELOG.md              ← NEW: version history
└── .github/workflows/
    ├── test.yml              (existing, unchanged)
    └── release.yml           ← NEW: automated release on tag push
```

---

### Task 1: Create VERSION file and update pyproject.toml

**Files:**
- Create: `src/sagtask/VERSION`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create VERSION file**

```bash
echo "1.2.0" > src/sagtask/VERSION
```

- [ ] **Step 2: Verify VERSION file content**

Run: `cat src/sagtask/VERSION`
Expected: `1.2.0`

- [ ] **Step 3: Update pyproject.toml for hatchling build backend**

Replace the entire `pyproject.toml` with:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sagtask-hermes"
version = "1.2.0"
description = "Long-running task management plugin for Hermes Agent"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [{name = "ethanchen669"}]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
]

[project.urls]
Repository = "https://github.com/ethanchen669/sagtask"

[project.entry-points."hermes_agent.plugins"]
sagtask = "sagtask:register"

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov>=4.0"]

[tool.hatch.build.targets.wheel]
packages = ["src/sagtask"]

[tool.hatch.build.targets.sdist]
include = ["src/sagtask/", "README.md", "LICENSE"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "e2e: end-to-end tests requiring hermes CLI",
]
addopts = "--tb=short -q"

[tool.coverage.run]
source = ["src/sagtask"]
omit = ["tests/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/ -v`
Expected: All 26 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/VERSION pyproject.toml
git commit -m "chore: add VERSION file, switch to hatchling build backend"
```

---

### Task 2: Create build-release.sh script

**Files:**
- Create: `scripts/build-release.sh`

- [ ] **Step 1: Create scripts directory**

```bash
mkdir -p scripts
```

- [ ] **Step 2: Write build-release.sh**

Create `scripts/build-release.sh`:

```bash
#!/usr/bin/env bash
# scripts/build-release.sh — Build release artifact for GitHub
set -euo pipefail

VERSION="${1:?Usage: build-release.sh <version>}"
ARTIFACT="sagtask-${VERSION}.tar.gz"
BUILD_DIR=$(mktemp -d)

trap "rm -rf $BUILD_DIR" EXIT

echo "→ Building SagTask release ${VERSION}"

# 1. Copy runtime files only
mkdir -p "${BUILD_DIR}/sagtask"
cp src/sagtask/__init__.py "${BUILD_DIR}/sagtask/"
cp src/sagtask/plugin.yaml "${BUILD_DIR}/sagtask/"
echo "${VERSION}" > "${BUILD_DIR}/sagtask/VERSION"

# 2. Update version in plugin.yaml
sed -i.bak "s/^version: .*/version: ${VERSION}/" "${BUILD_DIR}/sagtask/plugin.yaml"
rm -f "${BUILD_DIR}/sagtask/plugin.yaml.bak"

# 3. Create tarball
mkdir -p dist
tar -czf "dist/${ARTIFACT}" -C "${BUILD_DIR}" sagtask/

# 4. Generate checksum
(cd dist && sha256sum "${ARTIFACT}" > "${ARTIFACT}.sha256")

echo "✓ Built: dist/${ARTIFACT}"
echo "  SHA256: $(cat "dist/${ARTIFACT}.sha256" | cut -d' ' -f1)"
echo ""
echo "  Upload to GitHub release:"
echo "    gh release create v${VERSION} dist/${ARTIFACT} dist/${ARTIFACT}.sha256"
```

- [ ] **Step 3: Make script executable**

```bash
chmod +x scripts/build-release.sh
```

- [ ] **Step 4: Test the build script**

Run: `bash scripts/build-release.sh 1.2.0`
Expected: Creates `dist/sagtask-1.2.0.tar.gz` and `dist/sagtask-1.2.0.tar.gz.sha256`

- [ ] **Step 5: Verify tarball contents**

Run: `tar -tzf dist/sagtask-1.2.0.tar.gz`
Expected:
```
sagtask/
sagtask/__init__.py
sagtask/plugin.yaml
sagtask/VERSION
```

- [ ] **Step 6: Verify version in extracted plugin.yaml**

Run: `tar -xzf dist/sagtask-1.2.0.tar.gz -O sagtask/plugin.yaml | head -2`
Expected: `name: sagtask` and `version: 1.2.0`

- [ ] **Step 7: Clean up dist**

```bash
rm -rf dist/
```

- [ ] **Step 8: Commit**

```bash
git add scripts/build-release.sh
git commit -m "feat: add build-release.sh for creating release tarballs"
```

---

### Task 3: Create bump-version.sh script

**Files:**
- Create: `scripts/bump-version.sh`

- [ ] **Step 1: Write bump-version.sh**

Create `scripts/bump-version.sh`:

```bash
#!/usr/bin/env bash
# scripts/bump-version.sh — Bump version across all files
set -euo pipefail

NEW_VERSION="${1:?Usage: bump-version.sh <new-version>}"

echo "→ Bumping version to ${NEW_VERSION}"

# plugin.yaml
sed -i.bak "s/^version: .*/version: ${NEW_VERSION}/" src/sagtask/plugin.yaml
rm -f src/sagtask/plugin.yaml.bak

# pyproject.toml
sed -i.bak "s/^version = .*/version = \"${NEW_VERSION}\"/" pyproject.toml
rm -f pyproject.toml.bak

# VERSION file
echo "${NEW_VERSION}" > src/sagtask/VERSION

echo "✓ Version bumped to ${NEW_VERSION}"
echo "  Next: git commit && git tag v${NEW_VERSION} && git push --tags"
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x scripts/bump-version.sh
```

- [ ] **Step 3: Test bump-version.sh (dry run)**

Run: `bash scripts/bump-version.sh 1.2.1`
Expected: All three files updated to 1.2.1

- [ ] **Step 4: Verify plugin.yaml updated**

Run: `head -2 src/sagtask/plugin.yaml`
Expected: `version: 1.2.1`

- [ ] **Step 5: Verify pyproject.toml updated**

Run: `grep '^version' pyproject.toml`
Expected: `version = "1.2.1"`

- [ ] **Step 6: Verify VERSION updated**

Run: `cat src/sagtask/VERSION`
Expected: `1.2.1`

- [ ] **Step 7: Revert test bump**

Run: `bash scripts/bump-version.sh 1.2.0`
Expected: All files back to 1.2.0

- [ ] **Step 8: Commit**

```bash
git add scripts/bump-version.sh
git commit -m "feat: add bump-version.sh for version synchronization"
```

---

### Task 4: Improve install.sh

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Rewrite install.sh**

Replace the entire `install.sh` with:

```bash
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
        echo "✗ ${PLUGIN_DIR} is a git installation. Use: git -C ${PLUGIN_DIR} pull"
        exit 1
    fi
    CURRENT_VER=""
    [[ -f "$PLUGIN_DIR/VERSION" ]] && CURRENT_VER=$(cat "$PLUGIN_DIR/VERSION")
fi

# ── Fetch latest release info ───────────────────────────────────────────────

RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${OWNER}/${REPO}/releases/latest")
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
```

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n install.sh`
Expected: No output (no syntax errors)

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat: improve install.sh with asset download, checksum verification, version detection"
```

---

### Task 5: Create CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write CHANGELOG.md**

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to SagTask will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-05-06

### Added
- Input validation for task_id (alphanumeric + hyphens, max 64 chars)
- Subprocess timeout protection (30s) on all Git operations
- Configurable GitHub owner via `SAGTASK_GITHUB_OWNER` environment variable
- Exception logging (replaced silent `except Exception: pass` blocks)
- Test suite: 26 tests covering validation, lifecycle, and edge cases
- CI pipeline via GitHub Actions (`.github/workflows/test.yml`)

### Fixed
- `_get_current_step` UnboundLocalError when phases is empty
- Hardcoded `charlenchen` GitHub username — now configurable

## [1.1.0] - 2026-04-15

### Added
- Cross-pollination context injection via `pre_llm_call` hook
- Artifact scanning for generated files (markdown, code, JSON)
- Task relation system (`sag_task_relate` tool)

## [1.0.0] - 2026-03-20

### Added
- Initial release
- Per-task Git repositories with lazy initialization
- Multi-phase task lifecycle (create, advance, pause, resume, complete)
- Human-in-the-loop approval gates
- 11 tool handlers for task management
- Cross-session recovery via task state persistence
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG.md with version history"
```

---

### Task 6: Create GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Write release.yml**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Extract version from tag
        id: version
        run: echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

      - name: Build release artifact
        run: |
          mkdir -p dist
          bash scripts/build-release.sh ${{ steps.version.outputs.version }}

      - name: Create GitHub Release
        run: |
          gh release create ${{ github.ref_name }} \
            dist/sagtask-${{ steps.version.outputs.version }}.tar.gz \
            dist/sagtask-${{ steps.version.outputs.version }}.tar.gz.sha256 \
            --title "SagTask ${{ github.ref_name }}" \
            --generate-notes
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: No output (valid YAML)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add automated release workflow on tag push"
```

---

### Task 7: Test the full build flow

**Files:** None (verification only)

- [ ] **Step 1: Run existing tests to ensure nothing broke**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/ -v`
Expected: All 26 tests pass

- [ ] **Step 2: Test build-release.sh**

Run: `bash scripts/build-release.sh 1.2.0`
Expected: Creates `dist/sagtask-1.2.0.tar.gz` and `dist/sagtask-1.2.0.tar.gz.sha256`

- [ ] **Step 3: Verify tarball only contains runtime files**

Run: `tar -tzf dist/sagtask-1.2.0.tar.gz`
Expected:
```
sagtask/
sagtask/__init__.py
sagtask/plugin.yaml
sagtask/VERSION
```

- [ ] **Step 4: Verify checksum file is valid**

Run: `cd dist && sha256sum -c sagtask-1.2.0.tar.gz.sha256`
Expected: `sagtask-1.2.0.tar.gz: OK`

- [ ] **Step 5: Test bump-version.sh round-trip**

Run: `bash scripts/bump-version.sh 1.3.0 && cat src/sagtask/VERSION && bash scripts/bump-version.sh 1.2.0 && cat src/sagtask/VERSION`
Expected: `1.3.0` then `1.2.0`

- [ ] **Step 6: Clean up dist**

```bash
rm -rf dist/
```

- [ ] **Step 7: Commit any remaining changes**

```bash
git add -A
git status
```

Review changes, then commit if needed.

---

## Release Process (Post-Implementation)

After all tasks are complete, the release workflow is:

```bash
# 1. Confirm tests pass
python -m pytest tests/ --cov -v

# 2. Update version
bash scripts/bump-version.sh 1.3.0

# 3. Update CHANGELOG
vim CHANGELOG.md

# 4. Commit and tag
git add -A
git commit -m "chore: release v1.3.0"
git tag v1.3.0
git push origin main --tags

# 5. GitHub Actions auto:
#    - Builds sagtask-1.3.0.tar.gz
#    - Generates sha256 checksum
#    - Creates GitHub Release
#    - Publishes to PyPI
```
