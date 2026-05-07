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
