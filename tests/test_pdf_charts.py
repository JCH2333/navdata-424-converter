from navdata_converter.pdf_charts import _PROCEDURE, _WAYPOINT


def test_extracts_observable_procedure_and_fix_labels():
    text = "KAKAT-01D  TGO-01D  R039 KAKAT CHF"
    assert _PROCEDURE.findall(text) == ["KAKAT-01D", "TGO-01D"]
    assert {item for item in _WAYPOINT.findall(text) if item not in {"RNP"}} >= {"KAKAT", "CHF"}
