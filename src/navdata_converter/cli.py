from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .deployment import deploy, restore
from .fenix import ConversionBlocked, build_rejection_report, convert
from .source import load_naip
from .validation import validate_candidate
from .pdf_charts import extract_airport_charts, extract_chart
from .reference_diff import compare_databases
from .reference_delta import inspect_reference_delta


def _chart_payload(chart: object) -> dict[str, object]:
    return asdict(chart)


def _convert(args: argparse.Namespace) -> int:
    model = load_naip(Path(args.naip_root))
    try:
        report = convert(Path(args.official_navdata), model, Path(args.output), Path(args.reference) if args.reference else None, allow_incomplete=args.allow_incomplete)
    except ConversionBlocked as error:
        report = build_rejection_report(model, Path(args.output))
        print(f"转换被安全阻止: {error}\n报告: {report}")
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="424/NAIP 到 Fenix 导航数据转换器（测试版）")
    commands = parser.add_subparsers(dest="command", required=True)
    conversion = commands.add_parser("convert")
    conversion.add_argument("--official-navdata", required=True)
    conversion.add_argument("--naip-root", required=True)
    conversion.add_argument("--output", required=True)
    conversion.add_argument("--reference")
    conversion.add_argument("--allow-incomplete", action="store_true", help="generate a non-deployable diagnostic candidate")
    conversion.set_defaults(handler=_convert)
    validation = commands.add_parser("validate")
    validation.add_argument("--candidate", required=True)
    validation.add_argument("--reference")
    validation.set_defaults(handler=lambda a: print(json.dumps(validate_candidate(Path(a.candidate), Path(a.reference) if a.reference else None), ensure_ascii=False, indent=2)) or 0)
    deployment = commands.add_parser("deploy")
    deployment.add_argument("--candidate", required=True)
    deployment.add_argument("--target", required=True)
    deployment.set_defaults(handler=lambda a: print(deploy(Path(a.candidate), Path(a.target))) or 0)
    recovery = commands.add_parser("restore")
    recovery.add_argument("--backup", required=True)
    recovery.add_argument("--target", required=True)
    recovery.set_defaults(handler=lambda a: restore(Path(a.backup), Path(a.target)) or 0)
    inspection = commands.add_parser("inspect-pdf")
    inspection.add_argument("--pdf", required=True)
    inspection.add_argument("--airport", required=True)
    inspection.add_argument("--chart-type", default="")
    inspection.set_defaults(handler=lambda a: print(json.dumps([_chart_payload(item) for item in extract_chart(Path(a.pdf), a.airport, a.chart_type)], ensure_ascii=False, indent=2)) or 0)
    airport_inspection = commands.add_parser("inspect-airport-pdfs")
    airport_inspection.add_argument("--airport-directory", required=True)
    airport_inspection.set_defaults(handler=lambda a: print(json.dumps([_chart_payload(item) for item in extract_airport_charts(Path(a.airport_directory))], ensure_ascii=False, indent=2)) or 0)
    difference = commands.add_parser("diff-reference")
    difference.add_argument("--candidate", required=True)
    difference.add_argument("--reference", required=True)
    difference.set_defaults(handler=lambda a: print(json.dumps(compare_databases(Path(a.candidate), Path(a.reference)), ensure_ascii=False, indent=2)) or 0)
    delta = commands.add_parser("inspect-reference-delta")
    delta.add_argument("--official-navdata", required=True)
    delta.add_argument("--reference", required=True)
    delta.set_defaults(handler=lambda a: print(json.dumps(inspect_reference_delta(Path(a.official_navdata), Path(a.reference)), ensure_ascii=False, indent=2)) or 0)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
