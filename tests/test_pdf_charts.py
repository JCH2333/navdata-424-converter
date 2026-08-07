from navdata_converter.pdf_charts import _PROCEDURE, _RUNWAY, _WAYPOINT, _chart_rows, extract_airport_approach_charts, extract_airport_database_charts, extract_coordinate_page_points, extract_fix_coordinates, extract_positioned_coordinate_page_points, extract_terminal_leg_evidence


def test_extracts_observable_procedure_and_fix_labels():
    text = "KAKAT-01D  TGO-01D  R039 KAKAT CHF"
    assert _PROCEDURE.findall(text) == ["KAKAT-01D", "TGO-01D"]
    assert {item for item in _WAYPOINT.findall(text) if item not in {"RNP"}} >= {"KAKAT", "CHF"}
    assert _RUNWAY.findall("RWY03 RWY 21L") == ["03", "21L"]


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
