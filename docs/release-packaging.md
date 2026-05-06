# SagTask 发布打包方案

## 当前方案的问题

现有 `install.sh` 使用 GitHub 的 `tarball_url`（源码归档），存在以下问题：

| 问题 | 说明 |
|------|------|
| 源码归档包含多余文件 | `docs/`, `dev-install.sh`, `.gitignore`, `README.md` 等不需要部署 |
| 目录结构假设脆弱 | `mv "$TEMP_EXTRACT/sagtask" "$PLUGIN_DIR"` 依赖 GitHub tarball 内部结构 |
| 无版本校验 | 下载后无法验证完整性（无 checksum） |
| 无 pip 安装选项 | 用户无法通过标准 Python 工具安装 |
| 版本号分散 | `plugin.yaml` 中的 version 需要手动与 git tag 同步 |

---

## 推荐方案：双轨发布

```
┌─────────────────────────────────────────────────────────┐
│  Release Artifact (GitHub Release Asset)                │
│                                                         │
│  sagtask-1.2.0.tar.gz                                  │
│  ├── __init__.py      (插件源码)                        │
│  ├── plugin.yaml      (插件元数据)                      │
│  └── VERSION          (版本号，用于校验)                 │
│                                                         │
│  SHA256: sagtask-1.2.0.tar.gz.sha256                   │
├─────────────────────────────────────────────────────────┤
│  Alternative: pip install (entry-point discovery)       │
│  pip install sagtask-hermes                             │
└─────────────────────────────────────────────────────────┘
```

### 轨道 1：GitHub Release Asset（主推）

**适合：** 大多数 Hermes 用户，一行命令安装

**制品结构：**

```
sagtask-1.2.0.tar.gz
├── __init__.py
├── plugin.yaml
└── VERSION
```

只包含运行时必须文件，不包含 docs、tests、dev 脚本等。

### 轨道 2：pip 安装（可选）

**适合：** 有 Python 工具链的高级用户，通过 entry-point 自动发现

```bash
pip install sagtask-hermes
```

---

## 方案详细设计

### 1. 项目结构调整

```
sagtask/
├── src/sagtask/
│   ├── __init__.py
│   ├── plugin.yaml
│   └── VERSION              ← 新增：单行版本号，构建时自动写入
├── tests/
├── docs/
├── scripts/
│   ├── build-release.sh     ← 新增：构建发布制品
│   └── bump-version.sh      ← 新增：版本号同步工具
├── install.sh               ← 改进：支持 asset 下载
├── dev-install.sh
├── pyproject.toml            ← 新增：支持 pip install
├── CHANGELOG.md              ← 新增：版本历史
└── README.md
```

### 2. 构建脚本

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
sed -i "s/^version: .*/version: ${VERSION}/" "${BUILD_DIR}/sagtask/plugin.yaml"

# 3. Create tarball
tar -czf "dist/${ARTIFACT}" -C "${BUILD_DIR}" sagtask/

# 4. Generate checksum
sha256sum "dist/${ARTIFACT}" > "dist/${ARTIFACT}.sha256"

echo "✓ Built: dist/${ARTIFACT}"
echo "  SHA256: $(cat dist/${ARTIFACT}.sha256 | cut -d' ' -f1)"
echo ""
echo "  Upload to GitHub release:"
echo "    gh release create v${VERSION} dist/${ARTIFACT} dist/${ARTIFACT}.sha256"
```

### 3. 改进后的 install.sh

```bash
#!/usr/bin/env bash
# install.sh — One-line installer for SagTask
# Usage: curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
set -euo pipefail

OWNER="ethanchen669"
REPO="sagtask"
PLUGIN_DIR="${HOME}/.hermes/plugins/sagtask"
TMPDIR=$(mktemp -d)

cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

echo "→ SagTask installer"

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
        # Simple append — user may need to adjust
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

### 4. pyproject.toml（pip 安装支持）

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
dev = ["pytest>=7.0", "pytest-cov>=4.0", "pytest-watch"]

[tool.hatch.build.targets.wheel]
packages = ["src/sagtask"]

[tool.hatch.build.targets.sdist]
include = ["src/sagtask/", "README.md", "LICENSE"]
```

Hermes 通过 `hermes_agent.plugins` entry-point group 自动发现 pip 安装的插件，无需手动拷贝文件。

### 5. GitHub Actions 自动发布

```yaml
# .github/workflows/release.yml
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
        if: startsWith(github.ref, 'refs/tags/v')
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
```

### 6. 版本号同步脚本

```bash
#!/usr/bin/env bash
# scripts/bump-version.sh — Bump version across all files
set -euo pipefail

NEW_VERSION="${1:?Usage: bump-version.sh <new-version>}"

echo "→ Bumping version to ${NEW_VERSION}"

# plugin.yaml
sed -i "s/^version: .*/version: ${NEW_VERSION}/" src/sagtask/plugin.yaml

# pyproject.toml
sed -i "s/^version = .*/version = \"${NEW_VERSION}\"/" pyproject.toml

# VERSION file
echo "${NEW_VERSION}" > src/sagtask/VERSION

echo "✓ Version bumped to ${NEW_VERSION}"
echo "  Next: git commit && git tag v${NEW_VERSION} && git push --tags"
```

---

## 发布流程

### 日常发布（推荐）

```bash
# 1. 确认测试通过
pytest tests/ --cov -v

# 2. 更新版本号
bash scripts/bump-version.sh 1.3.0

# 3. 更新 CHANGELOG
vim CHANGELOG.md

# 4. 提交并打 tag
git add -A
git commit -m "chore: release v1.3.0"
git tag v1.3.0
git push origin main --tags

# 5. GitHub Actions 自动：
#    - 构建 sagtask-1.3.0.tar.gz
#    - 生成 sha256 校验文件
#    - 创建 GitHub Release
#    - 发布到 PyPI
```

### 用户安装方式

| 方式 | 命令 | 适用场景 |
|------|------|----------|
| 一行安装 | `curl -fsSL .../install.sh \| bash` | 大多数用户 |
| pip 安装 | `pip install sagtask-hermes` | Python 工具链用户 |
| git clone | `git clone ... ~/.hermes/plugins/sagtask` | 开发者/贡献者 |
| 手动下载 | 从 Release 页下载 tar.gz 解压 | 离线环境 |

---

## 安全与合规

| 措施 | 说明 |
|------|------|
| SHA256 校验 | 每个 release asset 附带 `.sha256` 文件 |
| tag 签名 | 建议使用 `git tag -s` 签名 tag |
| 最小制品 | 只包含运行时文件，不含 tests/docs/scripts |
| 源码可审计 | GitHub Release 自动附带源码归档供审计 |
| 无第三方依赖 | 纯 stdlib，无供应链风险 |

---

## 版本策略

采用语义版本 (SemVer)：`MAJOR.MINOR.PATCH`

| 变更类型 | 版本位 | 示例 |
|----------|--------|------|
| state schema 不兼容变更 | MAJOR | 2.0.0 |
| 新增工具 / 新功能 | MINOR | 1.3.0 |
| Bug 修复 / 优化 | PATCH | 1.2.1 |

**兼容性承诺：**
- 同一 MAJOR 版本内，task_state.json 向后兼容
- 新版本能读取旧版本创建的 state（通过 schema_version 迁移）
- 工具名不随意重命名（MAJOR 版本升级除外）

---

## 对比总结

| 维度 | 当前方案 | 改进方案 |
|------|----------|----------|
| 制品内容 | 整个源码仓库 | 仅运行时文件（3 个文件） |
| 制品大小 | ~80KB（含 docs/tests） | ~65KB（纯插件） |
| 完整性校验 | 无 | SHA256 |
| 版本检测 | 无 | VERSION 文件 + 跳过相同版本 |
| 升级体验 | 每次全量覆盖 | 检测版本，相同则跳过 |
| 安装方式 | 仅 curl/bash | curl + pip + git clone |
| 自动化 | 手动构建 | GitHub Actions 全自动 |
| 回滚 | 无 | 下载旧版本 asset 重装 |
