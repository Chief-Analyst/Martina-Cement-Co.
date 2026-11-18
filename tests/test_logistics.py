from martina.config import RULES
from martina.logistics import clock as C
from martina.logistics import rules as R
from martina.logistics.sim import STAGES


def test_window_time_skips_the_night():
    # 2 hours from 17:00 in a 07:00 to 18:00 window ends 08:00 next day
    t = C.advance_window(17 * 60, 120, 7 * 60, 18 * 60)
    assert t == C.DAY + 8 * 60
    assert C.window_minutes_between(17 * 60, C.DAY + 8 * 60, 7 * 60, 18 * 60) == 120


def test_trip_timelines_are_ordered(feed):
    for trips in list(feed.sim.trips.values())[:20]:
        for tr in trips:
            assert tr.t_assign <= tr.t_load_start <= tr.t_gate_out < tr.t_arrive <= tr.t_offloaded
            assert tr.t_offloaded < tr.t_depart < tr.t_back
            assert tr.site_hours >= 0


def test_snapshot_is_complete(feed):
    df = feed.snapshot()
    assert len(df) == len(feed.world.trucks)
    assert set(df["stage"]) <= set(STAGES)
    site = df[df["stage"] == "At site"]
    assert (site["cico_h"] >= 0).all()


def test_models_train_and_predict(feed):
    rep = feed.learner.report
    assert rep and rep["rows"] >= 400
    for key in ("risk", "site", "eta", "back"):
        assert key in rep["metrics"]
    risk = R._risk_batch(feed, range(10), feed.now())
    assert ((risk >= 0) & (risk <= 1)).all()


def test_views(feed):
    df = feed.snapshot()
    ex = R.exceptions(df, feed)
    assert list(ex["sev"]) == sorted(ex["sev"])
    rd = R.readiness(feed)
    assert set(rd["status"]) <= {"Ready", "Caution", "Hold"}
    held = rd[rd["status"] == "Hold"]
    assert all("hold" in r.lower() or "not ready" in r.lower() for r in held["reasons"])
    assert len(R.transporters(feed)) == len(feed.world.transporters)
    assert len(R.points(feed)) > 0


def test_journal_and_reports(feed):
    assert len(feed.journal) > 0
    assert len(feed.reports) >= 2
    rep = feed.write_report_now()
    assert "Decisions and actions" in rep["text"]


def test_rerouting_options(feed):
    w = R.reroute_watch(feed.snapshot())
    if len(w):
        opts, row = R.reroute_options(feed, w["truck_id"].iloc[0], "60")
        assert row is not None
        if len(opts):
            assert (opts["km"] <= 60 * RULES.road_factor + 1).all()
