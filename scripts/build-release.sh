#!/usr/bin/env bash
# scripts/build-release.sh — Build release artifact for GitHub
set -euo pipefail

VERSION="${1:?Usage: build-release.sh <version>}"
ARTIFACT="sagtask-${VERSION}.tar.gz"
BUILD_DIR=$(mktemp -d)

trap "rm -rf $BUILD_DIR" EXIT

echo "→ Building SagTask release ${VERSION}"

# 1. Copy entire package tree (excluding __pycache__)
mkdir -p "${BUILD_DIR}/sagtask"
rsync -a --exclude='__pycache__' src/sagtask/ "${BUILD_DIR}/sagtask/"
echo "${VERSION}" > "${BUILD_DIR}/sagtask/VERSION"

# 2. Update version in plugin.yaml
sed -i.bak "s/^version: .*/version: ${VERSION}/" "${BUILD_DIR}/sagtask/plugin.yaml"
rm -f "${BUILD_DIR}/sagtask/plugin.yaml.bak"

# 3. Create tarball
mkdir -p dist
tar -czf "dist/${ARTIFACT}" -C "${BUILD_DIR}" sagtask/

# 4. Generate checksum (use shasum on macOS, sha256sum on Linux)
if command -v sha256sum &>/dev/null; then
    (cd dist && sha256sum "${ARTIFACT}" > "${ARTIFACT}.sha256")
elif command -v shasum &>/dev/null; then
    (cd dist && shasum -a 256 "${ARTIFACT}" > "${ARTIFACT}.sha256")
fi

echo "✓ Built: dist/${ARTIFACT}"
echo "  SHA256: $(cat "dist/${ARTIFACT}.sha256" | cut -d' ' -f1)"
echo ""
echo "  Upload to GitHub release:"
echo "    gh release create v${VERSION} dist/${ARTIFACT} dist/${ARTIFACT}.sha256"
