from __future__ import annotations

import logging

import yaml

from src.shared import config_loader


def test_reconcile_holdings_uses_portfolio_positions_and_warns(caplog):
    caplog.set_level(logging.WARNING)

    holdings = config_loader.reconcile_holdings(
        portfolio_config={
            "holdings": [
                {"ticker": "amzn", "shares": 50, "cost_basis": 178.50},
                {"ticker": "RKLB", "shares": 200, "cost_basis": 24.50},
            ]
        },
        advisor_config={
            "holdings": [
                {"ticker": "AMZN", "category": "core", "thesis": "AWS re-acceleration"},
                {"ticker": "NVDA", "category": "core", "thesis": "AI accelerator leader"},
            ]
        },
    )

    assert [h["ticker"] for h in holdings] == ["AMZN", "RKLB"]
    assert holdings[0] == {
        "ticker": "AMZN",
        "shares": 50,
        "cost_basis": 178.50,
        "entry_price": 178.50,
        "category": "core",
        "thesis": "AWS re-acceleration",
    }
    assert holdings[1]["category"] == "core"
    assert holdings[1]["thesis"] == ""
    assert holdings[1]["entry_price"] == 24.50

    warning_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "Portfolio holdings missing advisor metadata: RKLB" in warning_text
    assert "Advisor holdings metadata not present in portfolio.yaml" in warning_text
    assert "NVDA" in warning_text


def test_load_advisor_config_with_portfolio_replaces_advisor_holdings(monkeypatch, tmp_path):
    (tmp_path / "portfolio.yaml").write_text(
        yaml.safe_dump(
            {
                "holdings": [
                    {"ticker": "MSFT", "shares": 15, "cost_basis": 378.0},
                    {"ticker": "VTI", "shares": 25, "cost_basis": 265.0},
                ]
            }
        )
    )
    (tmp_path / "advisor.yaml").write_text(
        yaml.safe_dump(
            {
                "holdings": [
                    {"ticker": "MSFT", "category": "core", "thesis": "Azure + Copilot"},
                    {"ticker": "META", "category": "core", "thesis": "AI ads"},
                ],
                "strategy": {"min_cagr_pct": 25},
            }
        )
    )
    monkeypatch.setattr(config_loader, "CONFIG_DIR", tmp_path)

    config = config_loader.load_advisor_config_with_portfolio()

    assert [holding["ticker"] for holding in config["holdings"]] == ["MSFT", "VTI"]
    assert config["holdings"][0]["thesis"] == "Azure + Copilot"
    assert config["holdings"][0]["shares"] == 15
    assert config["holdings"][1]["thesis"] == ""
    assert config["strategy"] == {"min_cagr_pct": 25}
