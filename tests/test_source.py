from navdata_converter.source import parse_dms


def test_parse_latitude_and_longitude_with_fixed_degree_width():
    assert round(parse_dms("N271940"), 6) == 27.327778
    assert round(parse_dms("E1163551"), 6) == 116.5975
    assert round(parse_dms("W0733000"), 6) == -73.5
