from pathlib import Path
from types import SimpleNamespace

from navdata_converter import cli


def test_pdf_cache_argument_is_forwarded_to_naip_loader(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("navdata_converter.cli.load_naip", lambda root, cache: calls.append((root, cache)) or "model")

    result = cli._load_model(SimpleNamespace(naip_root=str(tmp_path / "source"), pdf_cache=str(tmp_path / "cache")))

    assert result == "model"
    assert calls == [(tmp_path / "source", tmp_path / "cache")]
