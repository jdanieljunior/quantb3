"""Testes de point-in-time para a camada IBRX Model Watch."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from pathlib import Path
from tempfile import TemporaryDirectory

from config.settings import FEATURE_NAMES
from src.events.features import EVENT_FEATURE_NAMES, build_market_event_features
from src.features.engineering import build_features
from src.events.staging import read_watch_staging


class MarketEventFeaturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dates = pd.date_range("2026-01-01", periods=16, freq="D")
        self.tickers = ["PETR4.SA", "VALE3.SA"]

    def test_pending_event_never_becomes_feature(self) -> None:
        events = pd.DataFrame([{
            "ticker": "PETR4.SA", "event_type": "CORPORATE_ACTION",
            "event_class": "POINT", "published_at": "2026-01-03",
            "status": "PENDING_VALIDATION",
        }])
        features = build_market_event_features(self.dates, self.tickers, events)
        self.assertEqual(float(features["evt_corporate_5d"].to_numpy().sum()), 0.0)

    def test_confirmed_status_without_confirmation_boolean_is_rejected(self) -> None:
        events = pd.DataFrame([{
            "ticker": "PETR4.SA", "event_type": "CORPORATE_ACTION",
            "event_class": "POINT", "published_at": "2026-01-03",
            "status": "CONFIRMED", "confirmed": False,
        }])
        features = build_market_event_features(self.dates, self.tickers, events)
        self.assertEqual(float(features["evt_corporate_5d"].to_numpy().sum()), 0.0)

    def test_disclosure_date_blocks_look_ahead(self) -> None:
        events = pd.DataFrame([{
            "ticker": "PETR4.SA", "event_type": "CORPORATE_ACTION",
            "event_class": "POINT", "published_at": "2026-01-08",
            "effective_date": "2026-01-02", "valid_from": "2026-01-02",
            "status": "CONFIRMED",
        }])
        result = build_market_event_features(self.dates, self.tickers, events)["evt_corporate_5d"]
        self.assertEqual(result.loc[:"2026-01-07", "PETR4.SA"].sum(), 0.0)
        self.assertEqual(result.loc["2026-01-08", "PETR4.SA"], 1.0)
        self.assertEqual(result.loc["2026-01-13", "PETR4.SA"], 1.0)
        self.assertEqual(result.loc["2026-01-14", "PETR4.SA"], 0.0)

    def test_ticker_event_does_not_spill_to_other_assets(self) -> None:
        events = pd.DataFrame([{
            "ticker": "PETR4.SA", "event_type": "IBRX_COMPOSITION",
            "event_class": "POINT", "published_at": "2026-01-05",
            "status": "CONFIRMED",
        }])
        result = build_market_event_features(self.dates, self.tickers, events)["evt_ibrx_composition_5d"]
        self.assertGreater(result["PETR4.SA"].sum(), 0.0)
        self.assertEqual(result["VALE3.SA"].sum(), 0.0)

    def test_regime_is_market_wide_and_has_explicit_end(self) -> None:
        events = pd.DataFrame([{
            "ticker": None, "event_type": "HIGH_VOLATILITY_REGIME",
            "event_class": "REGIME", "published_at": "2026-01-05",
            "valid_from": "2026-01-01", "valid_to": "2026-01-07",
            "status": "CONFIRMED",
        }])
        result = build_market_event_features(self.dates, self.tickers, events)["regime_high_volatility"]
        self.assertEqual(result.loc[:"2026-01-04"].to_numpy().sum(), 0.0)
        self.assertTrue((result.loc["2026-01-05":"2026-01-07"] == 1.0).all().all())
        self.assertEqual(result.loc["2026-01-08":].to_numpy().sum(), 0.0)

    def test_promoted_event_without_available_from_fails_closed(self) -> None:
        events = pd.DataFrame([{
            "ticker": "PETR4.SA", "event_type": "CORPORATE_ACTION",
            "event_class": "POINT", "published_at": "2026-01-03",
            "available_from": None, "status": "CONFIRMED", "confirmed": True,
        }])
        features = build_market_event_features(self.dates, self.tickers, events)
        self.assertEqual(float(features["evt_corporate_5d"].to_numpy().sum()), 0.0)

    def test_core_features_stay_unchanged_without_events(self) -> None:
        dates = pd.date_range("2025-01-01", periods=90, freq="B")
        prices = pd.DataFrame({"PETR4.SA": np.linspace(20, 30, len(dates))}, index=dates)
        volumes = pd.DataFrame({"PETR4.SA": np.full(len(dates), 1_000_000)}, index=dates)
        benchmark = pd.Series(np.linspace(100, 110, len(dates)), index=dates)
        features = build_features(prices, volumes, benchmark)
        self.assertEqual(list(features), FEATURE_NAMES)
        self.assertTrue(set(EVENT_FEATURE_NAMES).isdisjoint(features))


class WatchStagingTest(unittest.TestCase):
    def test_false_boolean_is_not_coerced_to_true(self) -> None:
        header = (
            "event_id,event_type,ticker,alert_date,official_disclosure_date,"
            "effective_from,effective_to,validation_status,oos_enabled,confirmed,"
            "official_source_url,secondary_source_url,source_message_id,event_stage,"
            "validated_as_of,notes\n"
        )
        row = "evt-1,OPA,PETR4.SA,,,,,PENDENTE,false,false,,,,,,\n"
        with TemporaryDirectory() as folder:
            path = Path(folder) / "watch.csv"
            path.write_text(header + row, encoding="utf-8-sig")
            records = read_watch_staging(path)
        self.assertFalse(records[0]["oos_enabled"])
        self.assertFalse(records[0]["confirmed"])


if __name__ == "__main__":
    unittest.main()
