from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from navdata_converter.version import __version__


ROOT = Path(__file__).resolve().parent


def build(output: Path) -> Path:
    files = sorted([path for path in (ROOT / "src").rglob("*.py")] + [ROOT / "README.md", ROOT / "pyproject.toml"])
    manifest = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"navdata-424-converter-v{__version__}.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
        archive.writestr("update-manifest.json", json.dumps({"version": __version__, "files": manifest}, ensure_ascii=False, sort_keys=True))
    return package


if __name__ == "__main__":
    artifact = build(ROOT / "dist")
    print(artifact)
    print(hashlib.sha256(artifact.read_bytes()).hexdigest())
