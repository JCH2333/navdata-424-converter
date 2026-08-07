from pathlib import Path

from navdata_converter.model import ChartFixCoordinate, ChartRouteFix, ChartTerminalLeg, ProcedureChart, SourceRef
from navdata_converter.pdf_charts import _PROCEDURE, _RUNWAY, _WAYPOINT, _cached_extract, _chart_from_text, _chart_rows, approach_procedure_name_candidates, extract_airport_approach_charts, extract_airport_database_charts, extract_airport_standard_procedure_charts, extract_coordinate_page_points, extract_fix_coordinates, extract_positioned_coordinate_page_points, extract_positioned_route_fixes, extract_terminal_leg_evidence, extract_vector_route_fixes


def test_extracts_observable_procedure_and_fix_labels():
    text = "KAKAT-01D  TGO-01D  R039 KAKAT CHF"
    assert _PROCEDURE.findall(text) == ["KAKAT-01D", "TGO-01D"]
    assert {item for item in _WAYPOINT.findall(text) if item not in {"RNP"}} >= {"KAKAT", "CHF"}
    assert _RUNWAY.findall("RWY03 RWY 21L") == ["03", "21L"]


def test_expands_slash_separated_runways_in_approach_chart_title():
    chart = _chart_from_text(Path("ZGUH-6A.pdf"), "ZGUH", "instrument-approach-index", "VOR/DME RWY16/34", 1, "", "hash")

    assert chart.runways == ("16", "34")


def test_derives_conservative_fenix_approach_name_candidates_from_chart_title():
    assert approach_procedure_name_candidates("RNAV ILS/DME z RWY01", ("01",)) == ("I01", "I01-Z")
    assert approach_procedure_name_candidates("RNP x RWY18L(AR)", ("18L",)) == ("R18L", "R18L-X")
    assert approach_procedure_name_candidates("RNP ILS/DME y RWY22", ("22",)) == ("I22", "R22", "I22-Y", "R22-Y")
    assert approach_procedure_name_candidates("VOR/DME RWY04", ("04",)) == ("D04",)
    assert approach_procedure_name_candidates("RNAV ILS/DME RWY01L", ("01L",)) == ("I01L",)
    assert approach_procedure_name_candidates("RNP w RWY13", ("13",)) == ("R13", "R13-W")
    assert approach_procedure_name_candidates("RNP ILS/DME RWY22", ("22",)) == ("I22", "R22")
    assert approach_procedure_name_candidates("NDB/DME RWY12", ("12",)) == ("Q12",)
    assert approach_procedure_name_candidates("VOR/DME z RWY08", ("08",)) == ("D08",)
    assert approach_procedure_name_candidates("RNP y RWY16R(AR)", ("16L", "16R")) == ("R16R", "R16R-Y")
    assert approach_procedure_name_candidates("RNP x RWY10(AR)", ("10",), "ZYTL") == ("R10", "R10-X", "R10-AR-X")


def test_extracts_explicit_chart_coordinates_without_inventing_a_leg():
    coordinates = extract_fix_coordinates("CF401 N42 11.3 E118 48.6; CF402 N4212.0E11849.2")

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in coordinates] == [
        ("CF401", 42.188333, 118.81),
        ("CF402", 42.2, 118.82),
    ]


def test_extracts_database_chart_rows_with_their_confirming_procedure_heading():
    evidence = extract_terminal_leg_evidence("CF YK551 Y 037 MAX220 RNP1\nRWY04 离场 P389-09D\nDF YK404 L 900 RNP1\nTF P389 RNP1\nCF YK551 Y 037 MAX220 RNP1\nRWY04 离场 BM-09D(by ATC)\nDF YK404 L 900 RNP1")

    assert [(item.procedure_label, item.runway, item.leg_type, item.fix_ident) for item in evidence] == [
        ("P389-09D", "04", "CF", "YK551"),
        ("P389-09D", "04", "DF", "YK404"),
        ("P389-09D", "04", "TF", "P389"),
        ("BM-09D", "04", "CF", "YK551"),
        ("BM-09D", "04", "DF", "YK404"),
    ]


def test_extracts_database_leg_course_altitude_turn_and_speed_columns():
    evidence = extract_terminal_leg_evidence(
        "CF YK551\nY\n037\nMAX220\nRWY04 \u79bb\u573a P389-09D\nDF YK404\nL\n900\nCA\n037\n300\nMAX220\nRWY04 \u79bb\u573a P387-09D"
    )

    assert [(item.leg_type, item.course_degrees, item.altitude_meters, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("CF", 37.0, None, None, 220),
        ("DF", None, 900.0, "L", None),
        ("CA", 37.0, 300.0, None, 220),
    ]


def test_extracts_fix_from_next_line_when_pdf_table_columns_are_separate():
    evidence = extract_terminal_leg_evidence("CF\nYK551\nRWY04 离场 P389-09D\nDF\nYK404\nTF\nP389")

    assert [(item.leg_type, item.fix_ident) for item in evidence] == [("CF", "YK551"), ("DF", "YK404"), ("TF", "P389")]


def test_extracts_database_label_without_chinese_title_spacing():
    evidence = extract_terminal_leg_evidence("RWY03 离场TGO-9ZD\nCA\n032\nCF\nP300\nTF\nLELOG")

    assert [(item.procedure_label, item.runway, item.leg_type, item.fix_ident) for item in evidence] == [
        ("TGO-9ZD", "03", "CA", None),
        ("TGO-9ZD", "03", "CF", "P300"),
        ("TGO-9ZD", "03", "TF", "LELOG"),
    ]
    assert {item.procedure_kind for item in evidence} == {"离场"}


def test_extracts_direction_from_shared_runway_database_heading():
    evidence = extract_terminal_leg_evidence("RWY16L/16R/34L/34R \u79bb\u573aBOTPU-2W\nCF TJ931\nTF TJ932")

    assert [(item.procedure_label, item.runway, item.procedure_kind, item.leg_type, item.fix_ident) for item in evidence] == [
        ("BOTPU-2W", "16L", "\u79bb\u573a", "CF", "TJ931"),
        ("BOTPU-2W", "16L", "\u79bb\u573a", "TF", "TJ932"),
    ]


def test_extracts_database_approach_transition_main_and_missed_segments():
    evidence = extract_terminal_leg_evidence(
        "TF P464\nRNP1\n"
        "RWY11 进近过渡 HZ505\nIF\nHZ505\nTF\nHZ507\n"
        "RWY11 进近\nIF\nHZ507\nTF\nHZ508\n"
        "RWY11 复飞\nCF\nHZ512\nTF\nHZ513"
    )

    assert [(item.procedure_label, item.procedure_kind, item.transition, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R11", "进近过渡", "HZ505", "IF", "HZ505"),
        ("R11", "进近过渡", "HZ505", "TF", "HZ507"),
        ("R11", "进近", "", "IF", "HZ507"),
        ("R11", "进近", "", "TF", "HZ508"),
        ("R11", "复飞", "", "CF", "HZ512"),
        ("R11", "复飞", "", "TF", "HZ513"),
    ]


def test_extracts_explicit_database_approach_variants_and_matching_missed_approach():
    evidence = extract_terminal_leg_evidence(
        "RWY30 进近-Z\nTF MZ402\nCF MZ410\nRWY30 复飞-Z\nDF MZ406\n"
        "RWY30 进近-Y\nTF MZ405\nRWY30 复飞-Y\nDF MZ406"
    )

    assert [(item.procedure_label, item.procedure_kind, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R30-Z", "进近", "TF", "MZ402"),
        ("R30-Z", "进近", "CF", "MZ410"),
        ("R30-Z", "复飞", "DF", "MZ406"),
        ("R30-Y", "进近", "TF", "MZ405"),
        ("R30-Y", "复飞", "DF", "MZ406"),
    ]


def test_extracts_database_leg_after_rotated_text_residue():
    evidence = extract_terminal_leg_evidence(
        "RWY30 进近-Z\n急     TF MZ401\n使 CF MZ410\nRWY30 复飞-Z\nDF MZ406"
    )

    assert [(item.procedure_label, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R30-Z", "TF", "MZ401"),
        ("R30-Z", "CF", "MZ410"),
        ("R30-Z", "DF", "MZ406"),
    ]


def test_extracts_rf_center_endpoint_and_turn_from_database_row():
    evidence = extract_terminal_leg_evidence("RWY10 离场 P363-9D\nRF[XHC20, 4] XH604 L MAX220")

    assert [(item.leg_type, item.center_ident, item.fix_ident, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("RF", "XHC20", "XH604", "L", 220),
    ]


def test_splits_multiple_rf_rows_compressed_into_one_pdf_text_line():
    evidence = extract_terminal_leg_evidence("RWY07 离场 ELNEX-07D\nRF[RTX63, 4.1] TX610 R RF[RTX63, 4.1] TX614 R")

    assert [(item.center_ident, item.fix_ident, item.turn_direction) for item in evidence] == [
        ("RTX63", "TX610", "R"), ("RTX63", "TX614", "R"),
    ]


def test_pairs_coordinate_page_columns_only_when_counts_match():
    text = "YK401\nBM\nN40°35'40\"E121°48'14\"\nN39°39.4'E121°44.8'"

    points = extract_coordinate_page_points(text)

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in points] == [
        ("YK401", 40.594444, 121.803889),
        ("BM", 39.656667, 121.746667),
    ]


def test_pairs_coordinate_rows_by_rendered_position_when_pdf_text_order_is_wrong():
    words = [
        (42.0, 288.2, 60.0, 300.0, "BH413", 0, 0, 0),
        (42.0, 304.0, 60.0, 316.0, "BH414", 0, 1, 0),
        # The second coordinate object is emitted first by the PDF stream.
        (76.0, 304.0, 160.0, 316.0, 'N21°11\'44"E109°36\'58"', 1, 0, 0),
        (76.0, 288.2, 160.0, 300.0, 'N21°03\'09"E109°38\'13"', 1, 1, 0),
    ]

    points = extract_positioned_coordinate_page_points(words)

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in points] == [
        ("BH413", 21.0525, 109.636944),
        ("BH414", 21.195556, 109.616111),
    ]


def test_pairs_three_column_coordinate_table_despite_baseline_offsets():
    words = [
        (33.0, 72.3, 50.0, 80.0, "DER16", 0, 0, 0),
        (156.0, 72.1, 170.0, 80.0, "DQ504", 0, 1, 0),
        (95.0, 73.8, 145.0, 80.0, 'N27°46\'37.4"E99°41\'03"', 1, 0, 0),
        (216.0, 73.9, 270.0, 80.0, 'N27°39\'46.3"E99°43\'51"', 1, 1, 0),
    ]

    points = extract_positioned_coordinate_page_points(words)

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in points] == [
        ("DER16", 27.777056, 99.684167),
        ("DQ504", 27.662861, 99.730833),
    ]


def test_extracts_role_labelled_route_fixes_without_promoting_unrelated_text():
    words = [
        (100.0, 10.0, 114.0, 18.0, "IAF", 1, 0, 0),
        (100.0, 19.0, 126.0, 27.0, "YK603", 1, 1, 0),
        (200.0, 10.0, 210.0, 18.0, "FAF", 2, 0, 0),
        (212.0, 19.0, 235.0, 27.0, "INOP", 2, 1, 0),
        (100.0, 80.0, 130.0, 88.0, "YK999", 3, 0, 0),
    ]

    assert extract_positioned_route_fixes(words) == (ChartRouteFix("YK603", "IAF"),)


def test_extracts_identifier_next_to_black_vector_route_stroke():
    words = [
        (40.0, 18.0, 66.0, 26.0, "HZ412", 1, 0, 0),
        (80.0, 70.0, 106.0, 78.0, "NOTE", 2, 0, 0),
    ]
    drawings = [{"type": "s", "color": (0.0, 0.0, 0.0), "width": 0.42, "items": [("l", (30.0, 22.0), (72.0, 22.0))]}]

    assert extract_vector_route_fixes(words, drawings) == (ChartRouteFix("HZ412", "VECTOR"),)


def test_vector_route_evidence_ignores_long_map_outline_strokes():
    words = [(90.0, 18.0, 116.0, 26.0, "MAP01", 1, 0, 0)]
    drawings = [{"type": "s", "color": (0.0, 0.0, 0.0), "width": 0.42, "items": [("l", (0.0, 22.0), (200.0, 22.0))]}]

    assert extract_vector_route_fixes(words, drawings) == ()


def test_chart_rows_decode_utf8_index(tmp_path):
    index = tmp_path / "Charts.csv"
    index.write_text("ChartName,PAGE_NUMBER\n航路点坐标,4Y01\n", encoding="utf-8")

    assert _chart_rows(index) == [{"ChartName": "航路点坐标", "PAGE_NUMBER": "4Y01"}]


def test_database_chart_selection_uses_only_database_coding_index_rows(monkeypatch, tmp_path):
    airport = tmp_path / "ZBAD"
    airport.mkdir()
    (airport / "Charts.csv").write_text(
        "ChartName,PAGE_NUMBER\n数据库编码,4Z01\n航路点坐标,4Y01\n", encoding="utf-8"
    )
    (airport / "ZBAD-4Z01.pdf").write_bytes(b"placeholder")
    calls = []
    monkeypatch.setattr("navdata_converter.pdf_charts.extract_database_chart", lambda pdf, *args: calls.append(pdf.name) or [])

    assert extract_airport_database_charts(airport) == []
    assert calls == ["ZBAD-4Z01.pdf"]


def test_approach_chart_selection_uses_chart_type_and_preserves_index_name(monkeypatch, tmp_path):
    airport = tmp_path / "ZYYK"
    airport.mkdir()
    (airport / "Charts.csv").write_text(
        "ChartName,ChartTypeEx_CH,PAGE_NUMBER\n"
        "ILS Z RWY04,\u4eea\u8868\u8fdb\u8fd1\u56fe,5A\n"
        "SID RWY04,\u6807\u51c6\u4eea\u8868\u79bb\u573a\u56fe,3A\n",
        encoding="utf-8",
    )
    (airport / "ZYYK-5A.pdf").write_bytes(b"placeholder")
    calls = []
    monkeypatch.setattr(
        "navdata_converter.pdf_charts.extract_approach_chart",
        lambda pdf, airport_code, chart_type, chart_name: calls.append((pdf.name, airport_code, chart_type, chart_name)) or [],
    )

    assert extract_airport_approach_charts(airport) == []
    assert calls == [("ZYYK-5A.pdf", "ZYYK", "instrument-approach-index", "ILS Z RWY04")]


def test_standard_procedure_chart_selection_uses_sid_and_star_index_types(monkeypatch, tmp_path):
    airport = tmp_path / "ZYYK"
    airport.mkdir()
    (airport / "Charts.csv").write_text(
        "ChartName,ChartTypeEx_CH,PAGE_NUMBER\n"
        "SID RWY04,\u6807\u51c6\u4eea\u8868\u79bb\u573a\u56fe,3A\n"
        "STAR RWY22,\u6807\u51c6\u4eea\u8868\u8fdb\u573a\u56fe,4A\n"
        "\u6570\u636e\u5e93\u7f16\u7801,\u6807\u51c6\u4eea\u8868\u8fdb\u573a\u56fe,4Z01\n"
        "ILS RWY04,\u4eea\u8868\u8fdb\u8fd1\u56fe,5A\n",
        encoding="utf-8",
    )
    (airport / "ZYYK-3A.pdf").write_bytes(b"placeholder")
    (airport / "ZYYK-4A.pdf").write_bytes(b"placeholder")
    (airport / "ZYYK-4Z01.pdf").write_bytes(b"placeholder")
    calls = []
    monkeypatch.setattr("navdata_converter.pdf_charts.extract_approach_chart", lambda pdf, airport_code, chart_type, chart_name: calls.append((pdf.name, chart_type, chart_name)) or [])

    assert extract_airport_standard_procedure_charts(airport) == []
    assert calls == [("ZYYK-3A.pdf", "standard-terminal-procedure", "SID RWY04"), ("ZYYK-4A.pdf", "standard-terminal-procedure", "STAR RWY22")]


def test_pdf_evidence_cache_restores_every_chart_field_without_reopening_pdf(tmp_path):
    pdf = tmp_path / "ZYYK-4Z01.pdf"
    pdf.write_bytes(b"immutable source bytes")
    source = SourceRef(str(pdf), 1, 1, "source-hash")
    expected = ProcedureChart(
        "ZYYK", pdf.name, 1, "terminal-database-coding", "database", "text-hash", ("BM-09D",), ("04",), ("YK551",),
        (ChartTerminalLeg("BM-09D", "04", "CF", "YK551", "CF YK551", "departure", 37.0, 900.0, "L", 220),),
        (ChartFixCoordinate("YK551", 40.5, 122.4, "N40 30 E122 24"),), source,
    )
    calls = 0

    def extractor(*_args):
        nonlocal calls
        calls += 1
        return [expected]

    cache = tmp_path / "cache"
    first = _cached_extract(pdf, "ZYYK", "terminal-database-coding", "database", cache, extractor)
    second = _cached_extract(pdf, "ZYYK", "terminal-database-coding", "database", cache, extractor)

    assert first == second == [expected]
    assert calls == 1
