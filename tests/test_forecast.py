from martina.orderbook.forecast import FORECASTER, HORIZON


def test_forecast_shape_and_ranges(store):
    r = FORECASTER.train()
    fc = r["forecast"]
    assert (fc.groupby("region").size() == HORIZON).all()
    assert (fc["low"] <= fc["likely"] + 1e-6).all() and (fc["likely"] <= fc["high"] + 1e-6).all()
    assert "All regions" in r["scores"]
    assert len(r["customers"]) > 0
