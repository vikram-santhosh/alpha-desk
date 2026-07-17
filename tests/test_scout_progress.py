from __future__ import annotations

from src.shared import scout_progress as sp


def test_start_initializes_pending_stages():
    sp.start("top_buys")
    snap = sp.snapshot()
    assert snap["active"] is True
    assert snap["mode"] == "top_buys"
    assert [s["key"] for s in snap["stages"]] == [k for k, _ in sp.STAGES]
    assert all(s["status"] == "pending" for s in snap["stages"])


def test_stage_completes_all_earlier_stages():
    sp.start("top_buys")
    sp.stage("screening", "scoring")
    by_key = {s["key"]: s for s in sp.snapshot()["stages"]}
    assert by_key["config"]["status"] == "done"
    assert by_key["source"]["status"] == "done"
    assert by_key["market_data"]["status"] == "done"
    assert by_key["screening"]["status"] == "running"
    assert by_key["screening"]["detail"] == "scoring"
    assert by_key["synthesis"]["status"] == "pending"


def test_finish_marks_complete():
    sp.start("top_buys")
    sp.stage("publish")
    sp.finish()
    snap = sp.snapshot()
    assert snap["active"] is False
    assert snap["finished_at"] is not None
    assert all(s["status"] in ("done", "skipped") for s in snap["stages"])


def test_finish_with_error_marks_running_stage_error():
    sp.start("top_buys")
    sp.stage("market_data")
    sp.finish(error="boom")
    snap = sp.snapshot()
    assert snap["error"] == "boom"
    by_key = {s["key"]: s for s in snap["stages"]}
    assert by_key["market_data"]["status"] == "error"
    assert by_key["synthesis"]["status"] == "skipped"
