from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from .version import __version__


REPOSITORY = "JCH2333/navdata-424-converter"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases"
MAX_SIZE = 100 * 1024 * 1024
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Release:
    version: str
    asset_name: str
    asset_url: str
    sha256: str
    size: int


def _tuple(value: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError(f"无效版本号: {value}")
    return tuple(map(int, match.groups()))


def check_prerelease(opener=urlopen) -> Release | None:
    request = Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "navdata-424-converter"})
    with opener(request, timeout=8) as response:
        releases = json.loads(response.read(2 * 1024 * 1024))
    for release in releases:
        if not release.get("prerelease") or release.get("draft"):
            continue
        version = str(release.get("tag_name", "")).lstrip("v")
        if _tuple(version) <= _tuple(__version__):
            continue
        asset_name = f"navdata-424-converter-v{version}.zip"
        asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
        digest = str((asset or {}).get("digest") or "")
        if not asset or not digest.startswith("sha256:"):
            continue
        return Release(version, asset_name, asset["browser_download_url"], digest[7:], int(asset["size"]))
    return None


def validate_package(path: Path, release: Release) -> None:
    if path.stat().st_size > MAX_SIZE or path.stat().st_size != release.size:
        raise RuntimeError("更新包大小无效")
    if hashlib.sha256(path.read_bytes()).hexdigest() != release.sha256:
        raise RuntimeError("更新包 SHA-256 校验失败")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) > 500 or any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise RuntimeError("更新包包含不安全路径")
        manifest = json.loads(archive.read("update-manifest.json"))
        if manifest.get("version") != release.version:
            raise RuntimeError("更新包清单版本不匹配")
        for name, expected in manifest.get("files", {}).items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RuntimeError(f"更新包内部校验失败: {name}")
