"""DataForSEO cost model regressions: per-item pricing, Vietnam-relevant budget gate."""

from __future__ import annotations

import argparse
import json
import os
import sys

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import dataforseo_costs as dfc  # noqa: E402


def test_labs_1000_items_matches_task_plus_item_pricing() -> None:
    # $0.012/task + $0.00012/item * 1000 items = $0.132, not the old flat $0.05.
    assert dfc.estimate("dataforseo_labs_google_keyword_ideas", 1000) == pytest.approx(0.132)


def test_labs_default_item_count_is_task_price_plus_one_item() -> None:
    assert dfc.estimate("dataforseo_labs_google_keyword_ideas") == pytest.approx(0.01212)


def test_labs_200_items_is_cheaper_than_old_flat_fifty_cents() -> None:
    # Documented in the phase notes: 200 items was over-estimated at the old flat
    # $0.05; the real per-item model prices it lower.
    assert dfc.estimate("dataforseo_labs_google_keyword_ideas", 200) == pytest.approx(0.036)


def test_all_labs_endpoints_share_the_same_migrated_model() -> None:
    labs_endpoints = [k for k in dfc.COST_MODEL if k.startswith("dataforseo_labs_")]
    assert labs_endpoints, "expected DataForSEO Labs endpoints in COST_MODEL"
    for endpoint in labs_endpoints:
        assert dfc.estimate(endpoint, 1000) == pytest.approx(0.132)


def test_search_volume_bills_per_task_not_per_keyword() -> None:
    # Same cost whether the batch is 1 keyword or 1000 -- no per-item component.
    assert dfc.estimate("kw_data_google_ads_search_volume", 1) == pytest.approx(0.06)
    assert dfc.estimate("kw_data_google_ads_search_volume", 1000) == pytest.approx(0.06)


def test_serp_price_unchanged_by_the_2026_07_increase() -> None:
    assert dfc.estimate("serp_organic_live_advanced") == pytest.approx(0.002)


def test_cost_table_is_fallback_for_unmigrated_endpoints() -> None:
    # Not in COST_MODEL, but still priced via the flat COST_TABLE fallback.
    assert "on_page_instant_pages" not in dfc.COST_MODEL
    assert dfc.estimate("on_page_instant_pages", 50) == pytest.approx(0.012)


def test_unknown_endpoint_returns_conservative_default_cost() -> None:
    assert dfc.estimate("not_a_real_endpoint") == dfc.DEFAULT_COST


def test_labs_no_longer_duplicated_in_cost_table() -> None:
    # Migrated endpoints must not also sit in the flat-fee fallback table --
    # that would make COST_TABLE's stale price win by accident in any code
    # path that reads COST_TABLE directly instead of calling estimate().
    labs_in_model = {k for k in dfc.COST_MODEL if k.startswith("dataforseo_labs_")}
    labs_in_table = {k for k in dfc.COST_TABLE if k.startswith("dataforseo_labs_")}
    assert labs_in_model
    assert not labs_in_table


def test_cli_estimate_reports_task_plus_item_breakdown(capsys) -> None:
    args = argparse.Namespace(endpoint="dataforseo_labs_google_keyword_ideas", count=1000)
    dfc.cmd_estimate(args)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "estimated"
    assert result["total_cost_usd"] == pytest.approx(0.132)
    assert result["per_task_usd"] == pytest.approx(0.012)
    assert result["per_item_usd"] == pytest.approx(0.00012)
