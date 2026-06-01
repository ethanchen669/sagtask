"""SagTask self-update via GitHub releases."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

OWNER = "ethanchen669"
REPO = "sagtask"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"


def _get_plugin_dir() -> Path:
    return Path.home() / ".hermes" / "plugins" / "sagtask"


def _get_skill_dir() -> Path:
    return Path.home() / ".hermes" / "skills" / "sagtask"


def _all_plugin_dirs() -> list[Path]:
    """Return all sagtask plugin directories: default + all profiles."""
    dirs = [_get_plugin_dir()]
    profiles_root = Path.home() / ".hermes" / "profiles"
    if profiles_root.is_dir():
        for profile in sorted(profiles_root.iterdir()):
            if profile.is_dir() and (profile / "plugins").is_dir():
                dirs.append(profile / "plugins" / "sagtask")
    return dirs


def _all_skill_dirs() -> list[Path]:
    """Return all sagtask skill directories: default + all profiles."""
    dirs = [_get_skill_dir()]
    profiles_root = Path.home() / ".hermes" / "profiles"
    if profiles_root.is_dir():
        for profile in sorted(profiles_root.iterdir()):
            if profile.is_dir() and (profile / "skills").is_dir():
                dirs.append(profile / "skills" / "sagtask")
    return dirs


def _current_version() -> Optional[str]:
    vf = _get_plugin_dir() / "VERSION"
    if vf.exists():
        return vf.read_text().strip()
    return None


def _is_git_install() -> bool:
    return (_get_plugin_dir() / ".git").exists()


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _fetch_latest_release() -> dict:
    req = urllib.request.Request(API_URL, headers=_github_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=_github_headers())
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_asset(release: dict, suffix: str) -> Optional[str]:
    for asset in release.get("assets", []):
        if asset["name"].endswith(suffix):
            return asset["browser_download_url"]
    return None


def check_for_update() -> Tuple[Optional[str], Optional[str]]:
    """Return (current_version, latest_version) or (None, None) on error."""
    try:
        current = _current_version()
        release = _fetch_latest_release()
        latest = release["tag_name"].lstrip("v")
        return current, latest
    except Exception as e:
        logger.debug("Update check failed: %s", e)
        return None, None


def perform_update() -> str:
    """Download and install the latest release. Returns a status message."""
    if _is_git_install():
        return (
            "Git-based installation detected. Run `cd ~/.hermes/plugins/sagtask && git pull` instead."
        )

    current = _current_version()

    try:
        release = _fetch_latest_release()
    except Exception as e:
        return f"Failed to fetch release info: {e}"

    latest = release["tag_name"].lstrip("v")
    if current == latest:
        return f"Already at latest version ({latest})."

    # Find tarball asset
    asset_url = _find_asset(release, ".tar.gz")
    if not asset_url:
        return "No release asset found."

    tmpdir = tempfile.mkdtemp()
    try:
        tarball = Path(tmpdir) / "sagtask.tar.gz"
        _download(asset_url, tarball)

        # Verify checksum if available
        sha_url = _find_asset(release, ".sha256")
        if sha_url:
            sha_file = Path(tmpdir) / "expected.sha256"
            _download(sha_url, sha_file)
            expected = sha_file.read_text().split()[0]
            actual = _sha256(tarball)
            if expected != actual:
                return f"Checksum mismatch! Expected {expected[:16]}..., got {actual[:16]}..."

        # Extract
        subprocess.run(
            ["tar", "-xzf", str(tarball), "-C", tmpdir],
            check=True, capture_output=True,
        )
        source = Path(tmpdir) / "sagtask"
        if not (source / "__init__.py").exists():
            return "Invalid archive: __init__.py not found."

        # Install to default + all profiles
        installed = []
        for plugin_dir in _all_plugin_dirs():
            if plugin_dir.exists():
                shutil.rmtree(plugin_dir)
            plugin_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, plugin_dir)
            installed.append(str(plugin_dir))

        # Install skill metadata to default + all profiles
        if (source / "SKILL.md").exists():
            for skill_dir in _all_skill_dirs():
                skill_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / "SKILL.md", skill_dir)

        profiles_msg = f" ({len(installed)} locations)" if len(installed) > 1 else ""
        return f"Updated {current} → {latest}{profiles_msg}. Restart Hermes to load the new version."

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
