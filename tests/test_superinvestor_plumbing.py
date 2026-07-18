"""The 13F discovery channel reads config['superinvestors']; that key lives in
advisor.yaml, not scout.yaml, so the funnel must merge it in or the highest-
signal discovery source is a silent no-op."""
from __future__ import annotations


def test_advisor_config_actually_has_superinvestors():
    from src.shared.config_loader import load_advisor_config

    investors = load_advisor_config().get("superinvestors", [])
    assert isinstance(investors, list) and len(investors) >= 3, investors
    assert all("cik" in inv for inv in investors), investors


def test_13f_sourcer_reads_superinvestors_from_config(monkeypatch):
    from src.advisor import superinvestor_tracker as st

    seen = {}

    def fake_new_positions(cik, name):
        seen[name] = cik
        return [{"change_type": "new_position", "ticker": "XYZ", "shares": 1, "value_usd": 1}]

    monkeypatch.setattr(st, "get_new_superinvestor_positions", fake_new_positions)
    config = {"superinvestors": [{"name": "Test Fund", "cik": "0001"}]}
    candidates = st.get_new_positions_as_candidates(config)

    assert seen == {"Test Fund": "0001"}
    assert candidates and candidates[0]["ticker"] == "XYZ"
    assert candidates[0]["source"].startswith("superinvestor_13f/")


def test_empty_superinvestors_yields_no_candidates(monkeypatch):
    from src.advisor import superinvestor_tracker as st

    assert st.get_new_positions_as_candidates({"superinvestors": []}) == []
    assert st.get_new_positions_as_candidates({}) == []
