from navdata_converter.model import ChartFixCoordinate, NavModel, ProcedureChart, SourceRef
from navdata_converter.source import _feet, _load_terminal_coordinate_pages, _rows, _surface, navaid_country, parse_dms, romanize_name, waypoint_country


def test_parse_latitude_and_longitude_with_fixed_degree_width():
    assert round(parse_dms("N271940"), 6) == 27.327778
    assert round(parse_dms("E1163551"), 6) == 116.5975
    assert round(parse_dms("W0733000"), 6) == -73.5


def test_csv_reader_supports_utf8_chart_index(tmp_path):
    chart = tmp_path / "Charts.csv"
    chart.write_text("ChartName,ChartTypeEx_CH\n赤峰/玉龙,标准仪表离场图\n", encoding="utf-8")
    assert next(_rows(chart))["ChartName"] == "赤峰/玉龙"


def test_surface_mapping_uses_fenix_enumerations():
    assert _surface("水泥混凝土") == "ASP"
    assert _surface("草地") == "GRE"


def test_naip_dimensions_convert_meters_to_fenix_feet():
    assert _feet("2400") == 7874
    assert _feet("3000") == 9843


def test_naip_runway_elevations_use_val_elev_not_zero_threshold_field():
    assert _feet("1416.2") == 4646


def test_romanize_name_matches_observed_fenix_spelling():
    assert romanize_name("\u970d\u6797\u90ed\u52d2") == "HUOLINGUOLEI"
    assert romanize_name("DGL") == "DGL"


def test_navaid_country_prefers_serviced_airport_and_falls_back_to_fir():
    assert navaid_country("ZBHZ", "") == "ZB"
    assert navaid_country("", "\u6c88\u9633\u60c5\u62a5\u533a") == "ZY"


def test_waypoint_country_uses_naip_fir_prefix():
    assert waypoint_country("\u5e7f\u5dde\u60c5\u62a5\u533a") == "ZG"
    assert waypoint_country("", 27.438889, 122.421944) == "RC"
    assert waypoint_country("", 31.83, 125.0) == "RK"
    assert waypoint_country("", 31.91, 106.05) == "CN"
    assert waypoint_country("", 48.515, 115.786667, "SARUL") == "ZB"


def test_nav_model_keeps_rejected_source_records_for_reporting(tmp_path):
    model = NavModel(tmp_path)
    assert model.rejected_records == []


def test_terminal_coordinate_pages_preserve_pdf_sources(monkeypatch, tmp_path):
    airport_directory = tmp_path / "Terminal" / "ZYYK"
    airport_directory.mkdir(parents=True)
    chart = ProcedureChart(
        "ZYYK", "ZYYK-4Y01.pdf", 1, "terminal-coordinate-page", "coordinates", "text-hash", (), (), (), (),
        (ChartFixCoordinate("YK401", 40.5944444444, 121.8038888889, "N40 35 40 E121 48 14"),),
        SourceRef("ignored", 1, 1, "pdf-hash"),
    )
    monkeypatch.setattr("navdata_converter.source.extract_airport_coordinate_pages", lambda _: [chart])
    model = NavModel(tmp_path)

    _load_terminal_coordinate_pages(model)

    assert [(item.airport, item.ident, item.source.file, item.source.page, item.source.sha256) for item in model.terminal_waypoints] == [
        ("ZYYK", "YK401", "Terminal/ZYYK/ZYYK-4Y01.pdf", 1, "pdf-hash"),
    ]


def test_terminal_coordinate_page_with_no_pairs_is_explicitly_rejected(monkeypatch, tmp_path):
    airport_directory = tmp_path / "Terminal" / "ZBAD"
    airport_directory.mkdir(parents=True)
    chart = ProcedureChart("ZBAD", "ZBAD-4Y01.pdf", 1, "terminal-coordinate-page", "coordinates", "text-hash", (), (), (), (), (), SourceRef("ignored"))
    monkeypatch.setattr("navdata_converter.source.extract_airport_coordinate_pages", lambda _: [chart])
    model = NavModel(tmp_path)

    _load_terminal_coordinate_pages(model)

    assert [(item.kind, item.key) for item in model.rejected_records] == [("terminal-coordinate-page", "ZBAD")]


def test_terminal_database_charts_are_retained_as_procedure_evidence(monkeypatch, tmp_path):
    from navdata_converter.source import _load_terminal_database_charts

    airport_directory = tmp_path / "Terminal" / "ZBAD"
    airport_directory.mkdir(parents=True)
    chart = ProcedureChart("ZBAD", "ZBAD-4Z01.pdf", 1, "terminal-database-coding", "database", "text-hash", (), (), (), (), (), SourceRef("ignored"))
    monkeypatch.setattr("navdata_converter.source.extract_airport_database_charts", lambda _: [chart])
    model = NavModel(tmp_path)

    _load_terminal_database_charts(model)

    assert model.procedure_charts == [chart]


def test_terminal_approach_charts_are_retained_as_index_evidence(monkeypatch, tmp_path):
    from navdata_converter.source import _load_terminal_approach_charts

    airport_directory = tmp_path / "Terminal" / "ZYYK"
    airport_directory.mkdir(parents=True)
    chart = ProcedureChart("ZYYK", "ZYYK-5A.pdf", 1, "instrument-approach-index", "ILS Z RWY04", "text-hash", (), ("04",), (), (), (), SourceRef("ignored"))
    monkeypatch.setattr("navdata_converter.source.extract_airport_approach_charts", lambda _: [chart])
    model = NavModel(tmp_path)

    _load_terminal_approach_charts(model)

    assert model.procedure_charts == [chart]


def test_terminal_standard_procedure_charts_are_retained_as_waypoint_evidence(monkeypatch, tmp_path):
    from navdata_converter.source import _load_terminal_standard_procedure_charts

    airport_directory = tmp_path / "Terminal" / "ZYYK"
    airport_directory.mkdir(parents=True)
    chart = ProcedureChart("ZYYK", "ZYYK-3A.pdf", 1, "standard-terminal-procedure", "SID", "text-hash", (), (), ("YK551",), (), (), SourceRef("ignored"))
    monkeypatch.setattr("navdata_converter.source.extract_airport_standard_procedure_charts", lambda _: [chart])
    model = NavModel(tmp_path)

    _load_terminal_standard_procedure_charts(model)

    assert model.procedure_charts == [chart]
