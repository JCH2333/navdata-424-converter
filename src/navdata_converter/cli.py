from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .deployment import deploy, restore
from .fenix import ConversionBlocked, build_rejection_report, convert
from .source import load_naip
from .validation import validate_candidate
from .pdf_charts import extract_airport_charts, extract_airport_coordinate_pages, extract_chart
from .reference_diff import compare_databases
from .reference_delta import inspect_approach_chart_coverage, inspect_database_fix_coverage, inspect_reference_delta, inspect_terminal_waypoint_coverage


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
    inspection.set_defaults(handler=lambda a: print(json.dumps([_chart_payload(item) for item in extract_chart(Path(a.pdf), a.airport, a.chart_type)], ensure_ascii=True, indent=2)) or 0)
    airport_inspection = commands.add_parser("inspect-airport-pdfs")
    airport_inspection.add_argument("--airport-directory", required=True)
    airport_inspection.set_defaults(handler=lambda a: print(json.dumps([_chart_payload(item) for item in extract_airport_charts(Path(a.airport_directory))], ensure_ascii=True, indent=2)) or 0)
    coordinate_inspection = commands.add_parser("inspect-coordinate-pages")
    coordinate_inspection.add_argument("--airport-directory", required=True)
    coordinate_inspection.set_defaults(handler=lambda a: print(json.dumps([_chart_payload(item) for item in extract_airport_coordinate_pages(Path(a.airport_directory))], ensure_ascii=True, indent=2)) or 0)
    difference = commands.add_parser("diff-reference")
    difference.add_argument("--candidate", required=True)
    difference.add_argument("--reference", required=True)
    difference.set_defaults(handler=lambda a: print(json.dumps(compare_databases(Path(a.candidate), Path(a.reference)), ensure_ascii=False, indent=2)) or 0)
    delta = commands.add_parser("inspect-reference-delta")
    delta.add_argument("--official-navdata", required=True)
    delta.add_argument("--reference", required=True)
    delta.set_defaults(handler=lambda a: print(json.dumps(inspect_reference_delta(Path(a.official_navdata), Path(a.reference)), ensure_ascii=False, indent=2)) or 0)
    terminal_coverage = commands.add_parser("inspect-terminal-waypoint-coverage")
    terminal_coverage.add_argument("--naip-root", required=True)
    terminal_coverage.add_argument("--official-navdata", required=True)
    terminal_coverage.add_argument("--reference", required=True)
    terminal_coverage.set_defaults(handler=lambda a: print(json.dumps(
        inspect_terminal_waypoint_coverage(load_naip(Path(a.naip_root)), Path(a.official_navdata), Path(a.reference)), ensure_ascii=False, indent=2
    )) or 0)
    approach_coverage = commands.add_parser("inspect-approach-chart-coverage")
    approach_coverage.add_argument("--naip-root", required=True)
    approach_coverage.add_argument("--official-navdata", required=True)
    approach_coverage.add_argument("--reference", required=True)
    approach_coverage.set_defaults(handler=lambda a: print(json.dumps(
        inspect_approach_chart_coverage(load_naip(Path(a.naip_root)), Path(a.official_navdata), Path(a.reference)), ensure_ascii=False, indent=2
    )) or 0)
    database_fix_coverage = commands.add_parser("inspect-database-fix-coverage")
    database_fix_coverage.add_argument("--naip-root", required=True)
    database_fix_coverage.add_argument("--official-navdata", required=True)
    database_fix_coverage.add_argument("--reference", required=True)
    database_fix_coverage.set_defaults(handler=lambda a: print(json.dumps(
        inspect_database_fix_coverage(load_naip(Path(a.naip_root)), Path(a.official_navdata), Path(a.reference)), ensure_ascii=False, indent=2
    )) or 0)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
