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
