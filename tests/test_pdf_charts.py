from pathlib import Path

import pytest

from navdata_converter.model import ChartFixCoordinate, ChartRouteFix, ChartStandardProcedureRoute, ChartTerminalLeg, ProcedureChart, SourceRef
from navdata_converter.pdf_charts import _PROCEDURE, _RUNWAY, _WAYPOINT, _cached_extract, _chart_from_payload, _chart_from_text, _chart_rows, _chart_to_payload, _positioned_database_text, _standard_procedure_routes, approach_procedure_name_candidates, extract_ad219_ils, extract_airport_ad219_ils, extract_airport_approach_charts, extract_airport_database_charts, extract_airport_standard_procedure_charts, extract_coordinate_page_points, extract_fix_coordinates, extract_positioned_coordinate_page_points, extract_positioned_route_fixes, extract_terminal_leg_evidence, extract_vector_route_fixes


def test_extracts_observable_procedure_and_fix_labels():
    text = "KAKAT-01D  TGO-01D  R039 KAKAT CHF"
    assert _PROCEDURE.findall(text) == ["KAKAT-01D", "TGO-01D"]
    assert {item for item in _WAYPOINT.findall(text) if item not in {"RNP"}} >= {"KAKAT", "CHF"}
    assert _RUNWAY.findall("RWY03 RWY 21L") == ["03", "21L"]


def test_extracts_standard_arrival_route_table_without_inferring_geometry():
    text = """
    跑道 进场程序代号 导航数据代号 航迹简述
    P439-A1 P439A1 P439-CZ823-CZ700
    01
    P439-C3 P439C3 P439-CZ823-CZ622-CZ621
    """

    assert [(route.procedure_label, route.navigation_code, route.fixes) for route in _standard_procedure_routes(text)] == [
        ("P439-A1", "P439A1", ("P439", "CZ823", "CZ700")),
        ("P439-C3", "P439C3", ("P439", "CZ823", "CZ622", "CZ621")),
    ]


def test_extracts_only_printed_ad219_localizer_glide_path_and_dme_fields():
    text = """
    LOC 21 ILS CAT I ICF 108.5 MHz N420837.2 E1184955.1
    距03号跑道入口 212°MAG/385m
    GP 21 329.9 MHz N421006.4 E1185038.3
    3.2°下滑角 RDH15m
    DME 21 ICF CH 22X (108.5 MHz) N421006.4 E1185038.1 跑道中线西135m，入口内265m，616m 与 GP 21 合装
    """

    extracted = extract_ad219_ils(text, "ZBCF", SourceRef("Terminal/ZBCF/airport.pdf", 12, 12, "hash"))

    assert len(extracted) == 1
    ils = extracted[0]
    assert (ils.airport, ils.runway, ils.ident, ils.frequency_mhz, ils.category) == ("ZBCF", "21", "ICF", 108.5, "I")
    assert (ils.localizer_latitude, ils.localizer_longitude) == pytest.approx((42.14366666666667, 118.83197222222222))
    assert ils.localizer_course_magnetic == 212.0
    assert ils.glide_slope_degrees == 3.2
    assert ils.crossing_height_meters == 15.0
    assert (ils.glide_slope_latitude, ils.glide_slope_longitude) == pytest.approx((42.168444444444445, 118.84397222222222))
    assert (ils.dme_latitude, ils.dme_longitude, ils.dme_elevation_meters) == pytest.approx((42.168444444444445, 118.84391666666667, 616.0))
    assert ils.source == SourceRef("Terminal/ZBCF/airport.pdf", 12, 12, "hash")


def test_extracts_ad219_localizer_when_category_and_longitude_follow_page_break():
    text = """
    LOC 05 IHD 109.3 MHz N363204.6
    ILS CAT I E1142612.1 距05号跑道末端 052°MAG
    GP 05 332.0 MHz N363109.3 E1142453.5 3°下滑角 RDH15m
    DME 05 IHD CH 30X (109.3 MHz) N363108.4 E1142451.4 78m 与 GP 05 合装
    """

    extracted = extract_ad219_ils(text, "ZBHD", SourceRef("Terminal/ZBHD/邯郸.pdf", 14, 14, "hash"))

    assert [(item.runway, item.ident, item.frequency_mhz, item.localizer_course_magnetic, item.dme_elevation_meters) for item in extracted] == [
        ("05", "IHD", 109.3, 52.0, 78.0),
    ]


def test_extracts_ad219_localizer_with_two_or_three_fractional_frequency_digits():
    text = """
    LOC 04 ILS CAT I IXP 111.55 MHz N283021.8 E1093149.7 045°MAG
    GP 04 332.75 MHz N282921.3 E1093043.6 3°下滑角 RDH16 m
    DME 04 IXP CH 52Y (111.55 MHz) N282921.3 E1093043.6 714m 与 GP 04 合装
    LOC 22 ILS CAT I IXF 108.950 MHz N282903.2 E1093031.6 225°MAG
    GP 22 334.85 MHz N283003.8 E1093137.7 3°下滑角 RDH16.5 m
    DME 22 IXF CH 40Y (108.950 MHz) N283003.8 E1093137.7 712m 与 GP 22 合装
    """

    extracted = extract_ad219_ils(text, "ZGXX", SourceRef("Terminal/ZGXX/湘西边城.pdf", 17, 17, "hash"))

    assert [(item.runway, item.ident, item.frequency_mhz) for item in extracted] == [
        ("04", "IXP", 111.55),
        ("22", "IXF", 108.95),
    ]


def test_ad219_extractor_continues_across_headerless_table_pages(monkeypatch, tmp_path):
    airport = tmp_path / "ZBHD"
    airport.mkdir()
    (airport / "邯郸.pdf").write_bytes(b"fixture")

    class Page:
        def __init__(self, text):
            self.text = text

        def get_text(self):
            return self.text

    class Document:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __iter__(self):
            return iter([
                Page("ZBHD AD 2.19 无线电导航和着陆设施"),
                Page("""
                    LOC 23 ILS CAT I IKK 108.5 MHz N362839.0 E1142520.0 230°MAG
                    GP 23 330.5 MHz N362800.0 E1142600.0 3°下滑角 RDH15 m
                    DME 23 IKK CH 22X (108.5 MHz) N362800.0 E1142600.0 120m 与 GP 23 合装
                """),
                Page("ZBHD AD 2.20 本场规定 LOC 05 ILS CAT I OLD 108.5 MHz N360000.0 E1140000.0"),
            ])

    monkeypatch.setattr("navdata_converter.pdf_charts.pymupdf.open", lambda _: Document())

    extracted = extract_airport_ad219_ils(airport)

    assert [(item.runway, item.ident, item.source.page) for item in extracted] == [("23", "IKK", 1)]


def test_expands_slash_separated_runways_in_approach_chart_title():
    chart = _chart_from_text(Path("ZGUH-6A.pdf"), "ZGUH", "instrument-approach-index", "VOR/DME RWY16/34", 1, "", "hash")

    assert chart.runways == ("16", "34")


def test_retains_explicit_missed_approach_heading_from_chart_text():
    chart = _chart_from_text(Path("ZSWY-9B.pdf"), "ZSWY", "instrument-approach-index", "RNP RWY21(AR)", 1, "复飞程序", "hash")

    assert chart.has_missed_approach is True


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


def test_extracts_inline_database_leg_attributes_from_one_printed_row():
    evidence = extract_terminal_leg_evidence(
        "RWY03 离场 BZ-51N\nCF WY502 Y 027 1100 RNP1\nDF WY819 2000 MAX333 RNP1\nTF WY814 2900 RNP1"
    )

    assert [(item.leg_type, item.course_degrees, item.altitude_meters, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("CF", 27.0, 1100.0, None, None),
        ("DF", None, 2000.0, None, 333),
        ("TF", None, 2900.0, None, None),
    ]


def test_splits_multiple_printed_database_legs_in_one_row_before_reading_attributes():
    evidence = extract_terminal_leg_evidence(
        "RWY32 离场 TUNV-9W\nCA 324 2100 RNP1 DF AL507 R 3000 MAX230 RNP1"
    )

    assert [(item.leg_type, item.fix_ident, item.course_degrees, item.altitude_meters, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("CA", None, 324.0, 2100.0, None, None),
        ("DF", "AL507", None, 3000.0, "R", 230),
    ]


def test_rehydrates_legacy_cached_compressed_database_leg_with_current_boundaries():
    source = SourceRef("Terminal/ZYYY/ZYYY-4Z01.pdf", page=1, sha256="hash")
    chart = ProcedureChart(
        "ZYYY", "ZYYY-4Z01.pdf", 1, "terminal-database-coding", "数据库编码", "hash",
        (), ("32",), (),
        (ChartTerminalLeg("TUNV-9W", "32", "CA", None, "CA 324 2100 RNP1 DF AL507 R 3000 MAX230 RNP1", "离场", 324.0, 2100.0),),
        (), source,
    )

    rehydrated = _chart_from_payload(_chart_to_payload(chart))

    assert [(item.leg_type, item.fix_ident, item.raw, item.altitude_meters, item.speed_limit_knots) for item in rehydrated.terminal_legs] == [
        ("CA", None, "CA 324 2100 RNP1", 2100.0, None),
        ("DF", "AL507", "DF AL507 R 3000 MAX230 RNP1", 3000.0, 230),
    ]


def test_extracts_if_and_rf_altitudes_without_using_rf_arc_radius():
    evidence = extract_terminal_leg_evidence(
        "RWY18L 进近 R18L-X\nIF AA173 2400 RNAV1\nRF[AR081, 3.1] AR045 L 2600 MAX180 RNP1"
    )

    assert [(item.leg_type, item.fix_ident, item.altitude_meters, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("IF", "AA173", 2400.0, None, None),
        ("RF", "AR045", 2600.0, "L", 180),
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


def test_extracts_numeric_only_database_procedure_revision():
    evidence = extract_terminal_leg_evidence("RWY17 进场UPGE94\nIF UPGED\nTF DL403")

    assert [(item.procedure_label, item.leg_type) for item in evidence] == [("UPGE-94", "IF"), ("UPGE-94", "TF")]


def test_normalizes_compound_database_procedure_headings():
    evidence = extract_terminal_leg_evidence("RWY16 离场 SHGRL1-DQ770\nIF DER16\nRWY34 进场 RNV34-P186\nTF P186")

    assert [(item.procedure_label, item.procedure_kind, item.leg_type) for item in evidence] == [
        ("SHG-770", "离场", "IF"), ("R34-186", "进场", "TF"),
    ]


def test_normalizes_dashless_database_procedure_label_from_printed_heading():
    evidence = extract_terminal_leg_evidence("RWY36L/36R \u79bb\u573aIDKE5Y\nCA 001\nDF AA111 L\nTF AA112")

    assert [(item.procedure_label, item.runway, item.procedure_kind, item.leg_type, item.fix_ident) for item in evidence] == [
        ("IDKE-5Y", "36L", "\u79bb\u573a", "CA", None),
        ("IDKE-5Y", "36L", "\u79bb\u573a", "DF", "AA111"), ("IDKE-5Y", "36L", "\u79bb\u573a", "TF", "AA112"),
        ("IDKE-5Y", "36R", "\u79bb\u573a", "CA", None), ("IDKE-5Y", "36R", "\u79bb\u573a", "DF", "AA111"),
        ("IDKE-5Y", "36R", "\u79bb\u573a", "TF", "AA112"),
    ]


def test_extracts_shared_runways_when_the_heading_is_adjacent_to_chinese_text():
    evidence = extract_terminal_leg_evidence("RWY02/20\u79bb\u573aAPU-99D\nTF TL603")

    assert [(item.runway, item.fix_ident) for item in evidence] == [("02", "TL603"), ("20", "TL603")]


def test_extracts_direction_from_shared_runway_database_heading():
    evidence = extract_terminal_leg_evidence("RWY16L/16R/34L/34R \u79bb\u573aBOTPU-2W\nCF TJ931\nTF TJ932")

    assert [(item.procedure_label, item.runway, item.procedure_kind, item.leg_type, item.fix_ident) for item in evidence] == [
        ("BOTPU-2W", "16L", "\u79bb\u573a", "CF", "TJ931"),
        ("BOTPU-2W", "16L", "\u79bb\u573a", "TF", "TJ932"),
        ("BOTPU-2W", "16R", "\u79bb\u573a", "CF", "TJ931"),
        ("BOTPU-2W", "16R", "\u79bb\u573a", "TF", "TJ932"),
        ("BOTPU-2W", "34L", "\u79bb\u573a", "CF", "TJ931"),
        ("BOTPU-2W", "34L", "\u79bb\u573a", "TF", "TJ932"),
        ("BOTPU-2W", "34R", "\u79bb\u573a", "CF", "TJ931"),
        ("BOTPU-2W", "34R", "\u79bb\u573a", "TF", "TJ932"),
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


def test_extracts_database_approach_transition_with_adjacent_via_text():
    evidence = extract_terminal_leg_evidence("RWY26 \u8fdb\u8fd1\u8fc7\u6e21via DH504\nIF DH504\nTF DH503")

    assert [(item.procedure_label, item.procedure_kind, item.transition, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R26", "\u8fdb\u8fd1\u8fc7\u6e21", "DH504", "IF", "DH504"),
        ("R26", "\u8fdb\u8fd1\u8fc7\u6e21", "DH504", "TF", "DH503"),
    ]


def test_extracts_database_approach_transition_with_adjacent_fix():
    evidence = extract_terminal_leg_evidence("RWY26 \u8fdb\u8fd1\u8fc7\u6e21ES406\nIF ES406\nTF ES404")

    assert [(item.procedure_label, item.procedure_kind, item.transition, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R26", "\u8fdb\u8fd1\u8fc7\u6e21", "ES406", "IF", "ES406"),
        ("R26", "\u8fdb\u8fd1\u8fc7\u6e21", "ES406", "TF", "ES404"),
    ]


def test_extracts_database_approach_transition_with_printed_rnp_ils_or_ar_prefix():
    evidence = extract_terminal_leg_evidence(
        "RWY15 RNP ILS 进近过渡 IS96A\nIF AK966\nTF AK618\n"
        "RWY10 AR z y进近过渡 TL106\nIF TL106\nTF TL102\n"
        "RWY15 过渡MH503\nIF MH503\nTF MH502"
    )

    assert [(item.procedure_label, item.procedure_kind, item.transition, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R15", "进近过渡", "IS96A", "IF", "AK966"),
        ("R15", "进近过渡", "IS96A", "TF", "AK618"),
        ("R10", "进近过渡", "TL106", "IF", "TL106"),
        ("R10", "进近过渡", "TL106", "TF", "TL102"),
        ("R15", "进近过渡", "MH503", "IF", "MH503"),
        ("R15", "进近过渡", "MH503", "TF", "MH502"),
    ]


def test_splits_explicit_combined_approach_and_missed_heading_at_first_missed_leg():
    evidence = extract_terminal_leg_evidence(
        "RWY14 \u8fdb\u8fd1\u8fc7\u6e21 AL604\nIF AL604\nTF AL603\n"
        "RWY14 \u8fdb\u8fd1\u53ca\u590d\u98de\nIF AL603\nTF AL602\nTF AL600\nCF AL607\nDF AL605"
    )

    assert [(item.procedure_kind, item.leg_type, item.fix_ident) for item in evidence] == [
        ("\u8fdb\u8fd1\u8fc7\u6e21", "IF", "AL604"), ("\u8fdb\u8fd1\u8fc7\u6e21", "TF", "AL603"),
        ("\u8fdb\u8fd1", "IF", "AL603"), ("\u8fdb\u8fd1", "TF", "AL602"), ("\u8fdb\u8fd1", "TF", "AL600"),
        ("\u590d\u98de", "CF", "AL607"), ("\u590d\u98de", "DF", "AL605"),
    ]


def test_preserves_whitespace_separated_approach_variant_from_database_heading():
    evidence = extract_terminal_leg_evidence("RWY01 \u8fdb\u8fd1 z\nIF AA420\nTF AA496\nTF AA495")

    assert [(item.procedure_label, item.procedure_kind, item.leg_type) for item in evidence] == [
        ("R01-Z", "\u8fdb\u8fd1", "IF"), ("R01-Z", "\u8fdb\u8fd1", "TF"), ("R01-Z", "\u8fdb\u8fd1", "TF"),
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


def test_rebuilds_interleaved_database_rf_table_row_from_word_positions():
    words = [
        (57.5, 428.9, 66.0, 435.0, "TF", 28, 0, 0),
        (105.1, 428.9, 126.1, 435.0, "XH606", 28, 1, 0),
        (39.8, 441.4, 76.8, 447.5, "RF[XHC26,", 29, 0, 0),
        (105.0, 441.4, 126.1, 447.5, "XH678", 29, 1, 0),
        (78.7, 441.4, 85.0, 447.5, "5]", 29, 0, 1),
        (240.9, 441.4, 245.5, 447.5, "R", 29, 2, 0),
        (315.3, 441.4, 341.0, 447.5, "MAX230", 29, 3, 0),
        (358.9, 441.4, 382.3, 447.5, "RNP0.3", 29, 4, 0),
    ]

    text = _positioned_database_text(words)

    assert "RF[XHC26, 5] XH678 R MAX230 RNP0.3" in text
    evidence = extract_terminal_leg_evidence("RWY10 离场 OMBON-9D\n" + text)
    assert [(item.leg_type, item.center_ident, item.fix_ident, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("TF", None, "XH606", None, None),
        ("RF", "XHC26", "XH678", "R", 230),
    ]


def test_rebuilds_database_heading_when_left_margin_text_has_a_shifted_baseline():
    words = [
        (5.5, 252.26, 14.5, 271.26, "\u51b5", 42, 0, 0),
        (172.83, 253.70, 198.16, 261.26, "RWY22", 42, 1, 0),
        (198.57, 254.80, 210.50, 260.47, "\u8fdb\u8fd1", 42, 2, 0),
        (212.22, 254.80, 227.23, 260.47, "\u8fc7\u6e21", 42, 3, 0),
        (227.59, 253.70, 248.33, 261.26, "SH705", 42, 4, 0),
    ]

    text = _positioned_database_text(words)

    assert "RWY22 \u8fdb\u8fd1 \u8fc7\u6e21 SH705" in text
    evidence = extract_terminal_leg_evidence(text + "\nIF SH705\nTF SH703\nRWY22 \u8fdb\u8fd1\u3001\u590d\u98de\nIF SH703\nCF SH704")
    assert [(item.procedure_label, item.procedure_kind, item.transition, item.leg_type, item.fix_ident) for item in evidence] == [
        ("R22", "\u8fdb\u8fd1\u8fc7\u6e21", "SH705", "IF", "SH705"),
        ("R22", "\u8fdb\u8fd1\u8fc7\u6e21", "SH705", "TF", "SH703"),
        ("R22", "\u8fdb\u8fd1", "", "IF", "SH703"),
        ("R22", "\u590d\u98de", "", "CF", "SH704"),
    ]


def test_extracts_inline_holding_course_altitude_turn_and_speed():
    evidence = extract_terminal_leg_evidence("RWY03 进场 KAKAT-9ZA\nHM CF402 Y 097 L 2122 MAX205")

    assert [(item.leg_type, item.fix_ident, item.course_degrees, item.altitude_meters, item.turn_direction, item.speed_limit_knots) for item in evidence] == [
        ("HM", "CF402", 97.0, 2122.0, "L", 205),
    ]


def test_extracts_holding_to_fix_course_altitude_and_turn():
    evidence = extract_terminal_leg_evidence(
        "RWY23 离场 NUBKI-19D\n1800\nHF TN653 Y 257 L\nor by ATC\nTF P212"
    )

    assert [(item.leg_type, item.fix_ident, item.course_degrees, item.altitude_meters, item.turn_direction) for item in evidence] == [
        ("HF", "TN653", 257.0, 1800.0, "L"),
        ("TF", "P212", None, None, None),
    ]


def test_pairs_coordinate_page_columns_only_when_counts_match():
    text = "YK401\nBM\nN40°35'40\"E121°48'14\"\nN39°39.4'E121°44.8'"

    points = extract_coordinate_page_points(text)

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in points] == [
        ("YK401", 40.594444, 121.803889),
        ("BM", 39.656667, 121.746667),
    ]


def test_pairs_coordinate_page_row_without_terminal_longitude_quote():
    points = extract_positioned_coordinate_page_points([
        (32.3, 199.2, 52.3, 205.2, "XY608", 11, 0, 0),
        (57.8, 199.2, 124.1, 205.2, "N32°35.4'E114°20.1", 60, 0, 0),
    ])

    assert [(item.ident, round(item.latitude, 6), round(item.longitude, 6)) for item in points] == [
        ("XY608", 32.59, 114.335),
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


def test_extracts_identifier_next_to_black_filled_vector_route_path():
    words = [(40.0, 18.0, 66.0, 26.0, "HZ413", 1, 0, 0)]
    drawings = [{"type": "f", "fill": (0.0, 0.0, 0.0), "items": [("l", (30.0, 22.0), (72.0, 22.0))]}]

    assert extract_vector_route_fixes(words, drawings) == (ChartRouteFix("HZ413", "VECTOR"),)


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
    monkeypatch.setattr(
        "navdata_converter.pdf_charts.extract_approach_chart",
        lambda pdf, airport_code, chart_type, chart_name, *, include_vector_evidence=False:
        calls.append((pdf.name, chart_type, chart_name, include_vector_evidence)) or [],
    )

    assert extract_airport_standard_procedure_charts(airport) == []
    assert calls == [
        ("ZYYK-3A.pdf", "standard-terminal-procedure", "SID RWY04", False),
        ("ZYYK-4A.pdf", "standard-terminal-procedure", "STAR RWY22", False),
    ]

    calls.clear()
    assert extract_airport_standard_procedure_charts(airport, include_vector_evidence=True) == []
    assert calls == [
        ("ZYYK-3A.pdf", "standard-terminal-procedure", "SID RWY04", True),
        ("ZYYK-4A.pdf", "standard-terminal-procedure", "STAR RWY22", True),
    ]


def test_pdf_evidence_cache_restores_every_chart_field_without_reopening_pdf(tmp_path):
    pdf = tmp_path / "ZYYK-4Z01.pdf"
    pdf.write_bytes(b"immutable source bytes")
    source = SourceRef(str(pdf), 1, 1, "source-hash")
    expected = ProcedureChart(
        "ZYYK", pdf.name, 1, "terminal-database-coding", "database", "text-hash", ("BM-09D",), ("04",), ("YK551",),
        (ChartTerminalLeg("BM-09D", "04", "CF", "YK551", "CF YK551", "departure", 37.0, 900.0, "L", 220),),
        (ChartFixCoordinate("YK551", 40.5, 122.4, "N40 30 E122 24"),), source,
        standard_routes=(ChartStandardProcedureRoute("YK551-A1", "YK551A1", ("YK551", "YK552")),),
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
