from martina.config import RULES
from martina.orderbook import analytics as A
from martina.orderbook import operations as O
from martina.orderbook.pipeline import norm_filters

ALL = norm_filters({})


def test_kpis_add_up(store):
    k = A.kpis(ALL)
    assert k["open_t"] > 0 and 0 < k["fill_rate"] < 1.5
    assert abs(k["open_contract_t"] + k["open_release_t"] - k["open_t"]) < 1e-6
    assert abs(k["open_cement_t"] + k["open_mortar_t"] - k["open_t"]) < 1e-6


def test_filters_narrow_the_book(store):
    lagos = norm_filters({"region": ["Lagos"]})
    assert A.kpis(lagos)["open_t"] < A.kpis(ALL)["open_t"]
    assert set(A.backlog_by(lagos, "region")["region"]) == {"Lagos"}


def test_cover_bands_follow_the_rules(store):
    c = A.cover_risk(ALL)
    crit = c[c["band"] == "CRITICAL"]
    assert (crit["cover_days"] < RULES.cover_critical_days).all()
    assert (c.loc[c["channel"] == "Project", "band"] == "PROJECT").all()


def test_release_plan_never_releases_more_than_contracts(store):
    rp = O.release_planning(ALL, 3)
    assert (rp["to_release_t"] <= rp["contract_t"] + 1e-6).all()
    assert (rp["to_release_t"] >= 0).all() and (rp["short_t"] >= 0).all()


def test_partials_and_fifo(store):
    pa = O.partial_releases(ALL, "aged")
    assert (pa["age_days"] >= RULES.partial_alert_days).all()
    fi = O.fifo_watch(ALL, RULES.fifo_wait_days, "flag")
    assert set(fi["priority"]) <= {"HIGH", "MEDIUM"}
    assert (fi["age_days"] >= RULES.fifo_wait_days).all()


def test_views_are_cached(store):
    from martina.cache import VIEWS
    A.kpis(ALL)
    hits = VIEWS.hits
    A.kpis(ALL)
    assert VIEWS.hits == hits + 1
