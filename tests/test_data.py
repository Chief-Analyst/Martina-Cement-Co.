import numpy as np
from datetime import datetime

from martina.data import schema
from martina.data.synthetic import generate


def test_tables_match_the_schema(store):
    assert schema.validate(store.frames) == []


def test_generator_is_repeatable():
    a, _ = generate(seed=3, now=datetime(2026, 1, 15, 10), n_customers=40, fleet_size=20)
    b, _ = generate(seed=3, now=datetime(2026, 1, 15, 10), n_customers=40, fleet_size=20)
    for k in a:
        assert a[k].equals(b[k]), k


def test_order_quantities_are_consistent(store):
    o = store.frames["orders"]
    assert (o["done_t"] <= o["qty_t"] + 1e-6).all()
    rel = o[o["level"] == "release"].groupby("contract_id")["qty_t"].sum()
    con = o[o["level"] == "contract"].set_index("order_id")["done_t"]
    joined = con.to_frame("released").join(rel.rename("rel_sum"), how="inner")
    assert np.allclose(joined["released"], joined["rel_sum"])


def test_lifts_never_exceed_releases(store):
    o = store.frames["orders"]
    lifted = store.frames["lifts"].groupby("release_id")["qty_t"].sum()
    done = o[o["level"] == "release"].set_index("order_id")["done_t"]
    j = done.to_frame("done").join(lifted.rename("lifted"), how="inner")
    assert np.allclose(j["done"], j["lifted"])
