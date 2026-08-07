from __future__ import annotations

import datetime as dt
import shutil
import subprocess
from pathlib import Path

from .validation import sha256, validate_candidate


FILES = ("nd.db3", "cycle.json", "cycle_info.txt")


def simulator_running() -> bool:
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FlightSimulator2024.exe", "/NH"], capture_output=True, text=True, check=False)
    return "FlightSimulator2024.exe".lower() in result.stdout.lower()


def deploy(candidate: Path, target: Path) -> Path:
    if simulator_running():
        raise RuntimeError("FlightSimulator2024.exe 正在运行，无法覆盖 Fenix 导航数据")
    validate_candidate(candidate)
    if not (candidate / "conversion-report.json").is_file():
        raise RuntimeError("候选缺少转换报告，拒绝部署")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target.parent / "backups" / f"fenix_navdata_{stamp}"
    backup.mkdir(parents=True)
    for name in FILES:
        source = target / name
        if source.exists():
            shutil.copy2(source, backup / name)
    try:
        for name in FILES:
            shutil.copy2(candidate / name, target / name)
        for name in FILES:
            if sha256(candidate / name) != sha256(target / name):
                raise RuntimeError(f"部署后的 SHA-256 不一致: {name}")
    except Exception:
        for name in FILES:
            saved = backup / name
            if saved.exists():
                shutil.copy2(saved, target / name)
        raise
    return backup


def restore(backup: Path, target: Path) -> None:
    if simulator_running():
        raise RuntimeError("FlightSimulator2024.exe 正在运行，无法恢复")
    for name in FILES:
        source = backup / name
        if not source.is_file():
            raise FileNotFoundError(f"备份不完整: {source}")
        shutil.copy2(source, target / name)
