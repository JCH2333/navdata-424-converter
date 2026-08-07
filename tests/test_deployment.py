from navdata_converter.deployment import simulator_running


def test_simulator_probe_returns_boolean():
    assert isinstance(simulator_running(), bool)
