#!/usr/bin/env python3
"""
DataForSEO API cost estimation, approval, and budget tracking.

Provides cost-aware guardrails for DataForSEO API usage:
- Estimate costs before API calls
- Threshold-based approval workflow
- Session and daily budget tracking
- Spending history and summaries

Config: ~/.config/claude-seo/dataforseo-costs.json
Ledger: ~/.config/claude-seo/dataforseo-ledger.json
Set CLAUDE_SEO_CONFIG_DIR to point both somewhere else (used by the tests).

Usage:
    python dataforseo_costs.py estimate <endpoint> [--count N]
    python dataforseo_costs.py check <endpoint> [--count N]
    python dataforseo_costs.py log <endpoint> <cost> [--note TEXT]
    python dataforseo_costs.py summary [--days N]
    python dataforseo_costs.py today
    python dataforseo_costs.py config [--mode always|threshold|none] [--threshold AMOUNT] [--daily-limit AMOUNT]
    python dataforseo_costs.py reset

--count is the number of ITEMS in a single batched call (e.g. keywords in
one search_volume task), not a count of repeated calls. DataForSEO Labs and
Keywords Data endpoints bill per task plus a small per-item fee, so batching
1000 keywords into one --count 1000 call is always cheaper than 1000 calls
at --count 1 each.

Original concept: Matej Marjanovic (Pro Hub Challenge)
Security fixes: config path corrected to ~/.config/claude-seo/
"""

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

# ----- paths -----
# CLAUDE_SEO_CONFIG_DIR lets tests (and anyone running an isolated budget) point
# the ledger somewhere other than the real one. Resolved at import.
CONFIG_DIR = Path(
    os.environ.get("CLAUDE_SEO_CONFIG_DIR") or Path.home() / ".config" / "claude-seo"
)
CONFIG_FILE = CONFIG_DIR / "dataforseo-costs.json"
LEDGER_FILE = CONFIG_DIR / "dataforseo-ledger.json"
LOCK_FILE = CONFIG_DIR / "dataforseo-ledger.lock"

# ----- per-item cost model (USD, standard queue) -----
# Source: https://dataforseo.com/pricing -- verified as of 2026-09-05.
# DataForSEO Labs and a handful of other endpoints bill per task PLUS per
# item (e.g. per keyword) rather than a flat fee per call. Modeling that
# distinction matters: a 1000-keyword Labs task costs $0.132, not the $0.05
# flat rate the old table charged -- underestimating it 2.6x let a call that
# size slip past the budget gate unnoticed. Endpoints not listed here still
# bill flat-per-call and are looked up in COST_TABLE below.
COST_MODEL = {
    # DataForSEO Labs moved from a flat $0.05/call to $0.012/task + $0.00012/item
    # on 2026-07-01 (~20% list-price increase plus the new per-item component).
    "dataforseo_labs_google_keyword_ideas": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_keyword_suggestions": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_related_keywords": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_bulk_keyword_difficulty": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_search_intent": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_competitors_domain": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_domain_rank_overview": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_bulk_traffic_estimation": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_ranked_keywords": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_relevant_pages": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_domain_intersection": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_subdomains": {"per_task": 0.012, "per_item": 0.00012},
    "dataforseo_labs_google_top_searches": {"per_task": 0.012, "per_item": 0.00012},
    # Keywords Data search_volume bills per task (batch of keywords), not per
    # keyword -- $0.05 -> $0.06 standard queue ($0.09 on live). No per-item
    # component: the task price already covers the whole batch.
    "kw_data_google_ads_search_volume": {"per_task": 0.06, "per_item": 0.0},
    # SERP was not part of the 2026-07-01 increase; modeled here too so it is
    # never accidentally caught by a future flat-fee migration.
    "serp_organic_live_advanced": {"per_task": 0.002, "per_item": 0.0},
}

# ----- cost table (USD per call, standard queue) -----
# Fallback for endpoints not yet migrated to COST_MODEL above -- still a flat
# fee per call, item_count is ignored (an endpoint here that turns out to
# bill per item should move up into COST_MODEL instead of being patched here).
# Source: https://dataforseo.com/pricing -- verified as of 2026-09-05.
# Prices are approximate; actual costs may vary by parameters.
# Labs and kw_data_google_ads_search_volume moved to COST_MODEL (see above).
COST_TABLE = {
    # SERP (unaffected by the 2026-07-01 increase)
    "serp_organic_live_regular": 0.001,
    "serp_google_images_live_advanced": 0.002,
    "serp_google_images_live_regular": 0.001,
    "serp_youtube_organic_live_advanced": 0.002,
    "serp_youtube_video_info_live_advanced": 0.002,
    "serp_youtube_video_comments_live_advanced": 0.002,
    "serp_youtube_video_subtitles_live_advanced": 0.002,
    # Keywords Data (+20% on 2026-07-01)
    "kw_data_google_trends_explore": 0.012,
    # On-Page (+20% on 2026-07-01)
    "on_page_instant_pages": 0.012,
    "on_page_content_parsing": 0.012,
    "on_page_lighthouse": 0.024,
    # Backlinks (+20% on 2026-07-01)
    "backlinks_summary": 0.024,
    "backlinks_backlinks": 0.024,
    "backlinks_anchors": 0.024,
    "backlinks_referring_domains": 0.024,
    "backlinks_bulk_spam_score": 0.012,
    "backlinks_timeseries_summary": 0.024,
    "backlinks_domain_intersection": 0.06,
    # Domain Analytics (+20% on 2026-07-01)
    "domain_analytics_technologies_domain_technologies": 0.012,
    "domain_analytics_whois_overview": 0.006,
    # Content Analysis (+20% on 2026-07-01)
    "content_analysis_search": 0.024,
    "content_analysis_summary": 0.024,
    "content_analysis_phrase_trends": 0.024,
    # Business Data (not part of the 2026-07-01 increase)
    "business_data_business_listings_search": 0.05,
    # AI / GEO (not part of the 2026-07-01 increase)
    "ai_optimization_chat_gpt_scraper": 0.05,
    "ai_opt_llm_ment_search": 0.05,
    "ai_opt_llm_ment_top_domains": 0.05,
    "ai_opt_llm_ment_top_pages": 0.05,
    "ai_opt_llm_ment_agg_metrics": 0.05,
    "ai_opt_llm_ment_cross_agg_metrics": 0.05,
    # Merchant (e-commerce) -- Amazon rose 50% on 2026-07-01, Google unaffected
    "merchant_google_products_search": 0.02,
    "merchant_amazon_products_search": 0.03,
    "merchant_google_sellers_search": 0.02,
}

# Conservative fallback for an endpoint with no known price at all (neither
# COST_MODEL nor COST_TABLE). Deliberately at the high end of the table so an
# unrecognized endpoint is more likely to trip approval than sail through.
DEFAULT_COST = 0.06


def estimate(endpoint: str, item_count: int = 1) -> float:
    """Estimate the USD cost of one call to `endpoint`.

    `item_count` is the number of items in a SINGLE task/call (e.g. keywords
    batched into one search_volume request), not a count of repeated calls --
    DataForSEO Labs and Keywords Data bill per task, so batching keywords into
    one call is always cheaper than calling once per keyword.

    Resolution order: COST_MODEL (per-task + per-item) -> COST_TABLE (flat
    per-call, item_count ignored) -> DEFAULT_COST.
    """
    model = COST_MODEL.get(endpoint)
    if model is not None:
        return round(model["per_task"] + model["per_item"] * item_count, 6)
    unit_cost = COST_TABLE.get(endpoint)
    if unit_cost is not None:
        return round(unit_cost, 6)
    return DEFAULT_COST


def _known_endpoint(endpoint):
    """True if `endpoint` has a real price in COST_MODEL or COST_TABLE."""
    return endpoint in COST_MODEL or endpoint in COST_TABLE


def _fuzzy_matches(endpoint):
    """Substring-match `endpoint` against every known endpoint name."""
    return [k for k in list(COST_MODEL) + list(COST_TABLE) if endpoint in k]


def _cost_breakdown(endpoint):
    """Extra JSON fields describing how an endpoint's cost was derived."""
    model = COST_MODEL.get(endpoint)
    if model is not None:
        return {"per_task_usd": model["per_task"], "per_item_usd": model["per_item"]}
    unit_cost = COST_TABLE.get(endpoint)
    if unit_cost is not None:
        return {"unit_cost_usd": unit_cost}
    return {}


# Endpoints that always require confirmation regardless of mode
WARN_ENDPOINTS = {
    "backlinks_backlinks",
    "backlinks_domain_intersection",
    "ai_optimization_chat_gpt_scraper",
    "ai_opt_llm_ment_search",
    "merchant_amazon_products_search",
}

DEFAULT_CONFIG = {
    "mode": "threshold",
    "threshold": 0.50,
    "daily_limit": 10.00,
    "warn_endpoints": list(WARN_ENDPOINTS),
}


def _load_config():
    """Load or create configuration."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # Merge defaults for missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)


def _save_config(cfg):
    """Save configuration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


class LedgerError(RuntimeError):
    """The ledger could not be read or written safely."""


def _lock(handle, exclusive):
    """Take an advisory lock on an open handle, blocking until acquired.

    Never degrades to running unlocked: a spend ledger that silently drops
    entries is worse than one that refuses to run.
    """
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    elif msvcrt is not None:
        # msvcrt has no shared mode, so readers take an exclusive lock too.
        # LK_LOCK retries 10 times at 1s intervals, then raises OSError.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        raise LedgerError(
            "No file-locking primitive available (neither fcntl nor msvcrt). "
            "Refusing to touch the spend ledger unlocked."
        )


def _unlock(handle):
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_UN)
    elif msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _read_ledger():
    """Read the ledger. Caller must hold the lock."""
    if not LEDGER_FILE.exists():
        return {"entries": []}
    try:
        with open(LEDGER_FILE) as f:
            ledger = json.load(f)
    except json.JSONDecodeError as exc:
        raise LedgerError(
            f"Spend ledger {LEDGER_FILE} is not valid JSON ({exc}). Refusing to "
            "continue from a zero balance, which would under-report spend. "
            "Inspect the file, then repair or remove it."
        ) from exc
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), list):
        raise LedgerError(
            f"Spend ledger {LEDGER_FILE} has an unexpected shape (no 'entries' "
            "list). Inspect the file, then repair or remove it."
        )
    return ledger


def _write_ledger(ledger):
    """Write the ledger atomically. Caller must hold the exclusive lock.

    tempfile + os.replace so a crash mid-write can never leave a truncated,
    unparseable ledger behind (same idiom as scripts/google_auth.py).
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=str(CONFIG_DIR), prefix=".dataforseo-ledger.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, LEDGER_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


@contextmanager
def _locked_ledger(write=False):
    """Yield the ledger under ONE lock held across the whole read-modify-write.

    Taking the lock to read, dropping it, then re-taking it to write loses
    entries: two concurrent writers both read the same ledger and the second
    overwrites the first. The lock has to span both halves.

    The lock lives in a separate .lock file on purpose. The atomic write
    replaces the ledger's inode, so a lock held on the ledger itself would not
    protect the replacement.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a+") as lock_handle:
        _lock(lock_handle, exclusive=write)
        try:
            ledger = _read_ledger()
            yield ledger
            if write:
                _write_ledger(ledger)
        finally:
            _unlock(lock_handle)


def _ledger_snapshot():
    """Read the ledger under a shared lock. For read-only commands."""
    with _locked_ledger() as ledger:
        return ledger


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _today_spend(ledger):
    """Calculate today's total spend."""
    today = _today_str()
    return sum(
        e["cost"] for e in ledger["entries"]
        if e["timestamp"].startswith(today)
    )


def cmd_estimate(args):
    """Estimate cost for an API call."""
    endpoint = args.endpoint
    count = args.count or 1

    if not _known_endpoint(endpoint):
        matches = _fuzzy_matches(endpoint)
        if matches:
            result = {
                "status": "unknown_endpoint",
                "endpoint": endpoint,
                "suggestions": matches,
                "message": f"Unknown endpoint '{endpoint}'. Did you mean: {', '.join(matches)}?"
            }
        else:
            result = {
                "status": "unknown_endpoint",
                "endpoint": endpoint,
                "message": f"Unknown endpoint '{endpoint}'. Cost not in database."
            }
        json.dump(result, sys.stdout, indent=2)
        return

    total = estimate(endpoint, count)
    result = {
        "status": "estimated",
        "endpoint": endpoint,
        "item_count": count,
        "total_cost_usd": round(total, 4),
    }
    result.update(_cost_breakdown(endpoint))
    json.dump(result, sys.stdout, indent=2)


def cmd_check(args):
    """Check if an API call should proceed (cost + approval logic)."""
    cfg = _load_config()
    ledger = _ledger_snapshot()
    endpoint = args.endpoint
    count = args.count or 1
    if not _known_endpoint(endpoint):
        result = {
            "status": "needs_approval",
            "endpoint": endpoint,
            "approval_reason": "unknown_endpoint",
            "message": f"Unknown endpoint '{endpoint}': cost not in database. Requires explicit approval.",
            "estimated_cost_usd": DEFAULT_COST,
        }
        json.dump(result, sys.stdout, indent=2)
        return
    total = estimate(endpoint, count)
    today_total = _today_spend(ledger)
    daily_limit = cfg.get("daily_limit", 10.00)
    mode = cfg.get("mode", "threshold")
    threshold = cfg.get("threshold", 0.50)

    # Check daily limit
    if today_total + total > daily_limit:
        result = {
            "status": "blocked",
            "reason": "daily_limit_exceeded",
            "today_spend_usd": round(today_total, 4),
            "this_call_usd": round(total, 4),
            "daily_limit_usd": daily_limit,
            "message": f"Daily limit ${daily_limit:.2f} would be exceeded. Today's spend: ${today_total:.2f}, this call: ${total:.2f}."
        }
        json.dump(result, sys.stdout, indent=2)
        return

    # Check approval mode
    needs_approval = False
    approval_reason = None

    if endpoint in cfg.get("warn_endpoints", WARN_ENDPOINTS):
        needs_approval = True
        approval_reason = "warn_endpoint"
    elif mode == "always":
        needs_approval = True
        approval_reason = "mode_always"
    elif mode == "threshold" and total >= threshold:
        needs_approval = True
        approval_reason = "above_threshold"
    # mode == "none" -> never needs approval

    result = {
        "status": "needs_approval" if needs_approval else "approved",
        "endpoint": endpoint,
        "item_count": count,
        "total_cost_usd": round(total, 4),
        "today_spend_usd": round(today_total, 4),
        "daily_remaining_usd": round(daily_limit - today_total, 4),
    }
    result.update(_cost_breakdown(endpoint))
    if needs_approval:
        result["approval_reason"] = approval_reason
        result["message"] = (
            f"This call costs ~${total:.2f}. "
            f"Today's spend: ${today_total:.2f}/${daily_limit:.2f}. "
            f"Reason: {approval_reason}. Proceed?"
        )
    json.dump(result, sys.stdout, indent=2)


def cmd_log(args):
    """Log a completed API call cost.

    Rotation (Phase C) changes which account pays for a call, so each entry
    records which credential slot paid for it. Defaults to 1 -- the only
    slot a single-key setup ever has -- so a summary walking entries logged
    before this field existed can still treat a missing "slot" as 1 rather
    than crashing on a KeyError.
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "endpoint": args.endpoint,
        "cost": args.cost,
        "slot": getattr(args, "slot", None) or 1,
    }
    if args.note:
        entry["note"] = args.note
    # Read and write inside one lock, so a concurrent log cannot overwrite this
    # entry with a ledger it read before this one was appended.
    with _locked_ledger(write=True) as ledger:
        ledger["entries"].append(entry)

    result = {
        "status": "logged",
        "entry": entry,
        "today_total_usd": round(_today_spend(ledger), 4),
    }
    json.dump(result, sys.stdout, indent=2)


def cmd_summary(args):
    """Show spending summary for recent days."""
    ledger = _ledger_snapshot()
    days = args.days or 7
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    recent = [e for e in ledger["entries"] if e["timestamp"] >= cutoff]

    # Group by day
    by_day = {}
    for e in recent:
        day = e["timestamp"][:10]
        by_day.setdefault(day, []).append(e)

    daily_totals = {}
    for day, entries in sorted(by_day.items()):
        daily_totals[day] = {
            "total_usd": round(sum(e["cost"] for e in entries), 4),
            "calls": len(entries),
        }

    # Rotation (Phase C) means a call can be paid for by any configured
    # slot. e.get("slot", 1) rather than e["slot"] so an entry logged
    # before this field existed is reconciled as slot 1, not a KeyError.
    by_slot: dict = {}
    for e in recent:
        slot = e.get("slot", 1)
        bucket = by_slot.setdefault(slot, {"total_usd": 0.0, "calls": 0})
        bucket["total_usd"] += e["cost"]
        bucket["calls"] += 1
    slot_totals = {
        str(slot): {"total_usd": round(v["total_usd"], 4), "calls": v["calls"]}
        for slot, v in sorted(by_slot.items())
    }

    result = {
        "status": "summary",
        "period_days": days,
        "daily_totals": daily_totals,
        "slot_totals": slot_totals,
        "grand_total_usd": round(sum(e["cost"] for e in recent), 4),
        "total_calls": len(recent),
    }
    json.dump(result, sys.stdout, indent=2)


def cmd_today(args):
    """Show today's spending."""
    ledger = _ledger_snapshot()
    cfg = _load_config()
    today = _today_str()
    today_entries = [e for e in ledger["entries"] if e["timestamp"].startswith(today)]

    # Group by endpoint
    by_endpoint = {}
    for e in today_entries:
        ep = e["endpoint"]
        by_endpoint.setdefault(ep, {"cost": 0, "calls": 0})
        by_endpoint[ep]["cost"] += e["cost"]
        by_endpoint[ep]["calls"] += 1

    total = sum(e["cost"] for e in today_entries)
    daily_limit = cfg.get("daily_limit", 10.00)

    result = {
        "status": "today",
        "date": today,
        "total_usd": round(total, 4),
        "daily_limit_usd": daily_limit,
        "remaining_usd": round(daily_limit - total, 4),
        "calls": len(today_entries),
        "by_endpoint": {k: {"cost_usd": round(v["cost"], 4), "calls": v["calls"]} for k, v in by_endpoint.items()},
    }
    json.dump(result, sys.stdout, indent=2)


def cmd_config(args):
    """View or update configuration."""
    cfg = _load_config()

    changed = False
    if args.mode:
        if args.mode not in ("always", "threshold", "none"):
            print(json.dumps({"status": "error", "message": "Mode must be: always, threshold, or none"}))
            sys.exit(1)
        cfg["mode"] = args.mode
        changed = True
    if args.threshold is not None:
        cfg["threshold"] = args.threshold
        changed = True
    if args.daily_limit is not None:
        cfg["daily_limit"] = args.daily_limit
        changed = True

    if changed:
        _save_config(cfg)

    result = {
        "status": "updated" if changed else "current",
        "config": cfg,
    }
    json.dump(result, sys.stdout, indent=2)


def cmd_reset(args):
    """Reset today's ledger entries (requires --confirm)."""
    if not args.confirm:
        result = {
            "status": "blocked",
            "message": "Reset requires --confirm flag. This clears today's cost entries.",
        }
        json.dump(result, sys.stdout, indent=2)
        return

    today = _today_str()
    # One lock across the whole read-modify-write, so a concurrent log is either
    # cleared by this reset or survives it, never silently discarded.
    with _locked_ledger(write=True) as ledger:
        today_entries = [e for e in ledger["entries"] if e["timestamp"].startswith(today)]
        removed_total = sum(e["cost"] for e in today_entries)
        removed_count = len(today_entries)

        ledger["entries"] = [e for e in ledger["entries"] if not e["timestamp"].startswith(today)]

        # Immutable audit entry for the reset itself
        ledger["entries"].append({
            "timestamp": datetime.now().isoformat(),
            "endpoint": "_audit_reset",
            "cost": 0,
            "note": f"Reset cleared {removed_count} entries totaling ${removed_total:.4f}",
        })

    result = {
        "status": "reset",
        "date": today,
        "entries_removed": removed_count,
        "amount_cleared_usd": round(removed_total, 4),
    }
    json.dump(result, sys.stdout, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="DataForSEO API cost estimation and budget tracking"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # estimate
    p_est = sub.add_parser("estimate", help="Estimate cost for an API call")
    p_est.add_argument("endpoint", help="DataForSEO MCP tool name")
    p_est.add_argument("--count", type=int, default=1, help="Items in one batched call (default: 1)")

    # check
    p_chk = sub.add_parser("check", help="Check if call should proceed")
    p_chk.add_argument("endpoint", help="DataForSEO MCP tool name")
    p_chk.add_argument("--count", type=int, default=1, help="Items in one batched call (default: 1)")

    # log
    p_log = sub.add_parser("log", help="Log a completed API call cost")
    p_log.add_argument("endpoint", help="DataForSEO MCP tool name")
    p_log.add_argument("cost", type=float, help="Actual cost in USD")
    p_log.add_argument("--note", help="Optional note")
    p_log.add_argument(
        "--slot",
        type=int,
        default=1,
        help="Credential slot index that paid for this call (default: 1)",
    )

    # summary
    p_sum = sub.add_parser("summary", help="Show spending summary")
    p_sum.add_argument("--days", type=int, default=7, help="Number of days")

    # today
    sub.add_parser("today", help="Show today's spending")

    # config
    p_cfg = sub.add_parser("config", help="View or update configuration")
    p_cfg.add_argument("--mode", choices=["always", "threshold", "none"])
    p_cfg.add_argument("--threshold", type=float)
    p_cfg.add_argument("--daily-limit", type=float, dest="daily_limit")

    # reset
    p_reset = sub.add_parser("reset", help="Reset today's ledger entries")
    p_reset.add_argument("--confirm", action="store_true", help="Confirm reset (required)")

    args = parser.parse_args()
    dispatch = {
        "estimate": cmd_estimate,
        "check": cmd_check,
        "log": cmd_log,
        "summary": cmd_summary,
        "today": cmd_today,
        "config": cmd_config,
        "reset": cmd_reset,
    }
    try:
        dispatch[args.command](args)
    except LedgerError as exc:
        # Fail closed and loudly. Callers parse stdout as JSON, so keep the
        # contract even on the error path.
        json.dump({"status": "error", "message": str(exc)}, sys.stdout, indent=2)
        sys.exit(1)


if __name__ == "__main__":
    main()
