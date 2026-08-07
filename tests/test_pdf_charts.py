from navdata_converter.pdf_charts import _PROCEDURE, _RUNWAY, _WAYPOINT, extract_fix_coordinates


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
