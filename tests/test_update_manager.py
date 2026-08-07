import hashlib
import io
import json
import zipfile

from navdata_converter.update_manager import Release, validate_package


def test_update_package_requires_matching_manifest(tmp_path):
    package = tmp_path / "update.zip"
    payload = b"print('ok')\n"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("src/navdata_converter/version.py", payload)
        archive.writestr("update-manifest.json", json.dumps({"version": "0.1.1", "files": {"src/navdata_converter/version.py": hashlib.sha256(payload).hexdigest()}}))
    release = Release("0.1.1", package.name, "https://example.invalid/update.zip", hashlib.sha256(package.read_bytes()).hexdigest(), package.stat().st_size)
    validate_package(package, release)
