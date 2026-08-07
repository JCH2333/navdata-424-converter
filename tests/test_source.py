from navdata_converter.source import _feet, _rows, _surface, parse_dms, romanize_name


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
