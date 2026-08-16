#!/usr/bin/python3
"""Collect Hermes Agent spend into one Omarchy agents-panel JSON record."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

AGENT_ID = "hermes"
AGENT_NAME = "Hermes"
AUTH_HELP = "Run `hermes setup --portal` or `hermes login` to restore Nous spend."
PORTAL_URL = "https://portal.nousresearch.com"


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def local_date_from_unix(value: Any) -> str:
    try:
        seconds = float(value or 0)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        return dt.datetime.fromtimestamp(seconds).date().isoformat()
    except (TypeError, ValueError, OSError):
        return dt.datetime.now().date().isoformat()


def recent_dates() -> list[str]:
    today = dt.datetime.now().date()
    return [(today - dt.timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def number(value: Any) -> int:
    try:
        return max(0, round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def money(value: Any) -> float:
    try:
        amount = float(value or 0)
        return amount if amount == amount else 0.0  # NaN guard
    except (TypeError, ValueError):
        return 0.0


def jwt_payload(token: str) -> dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        parsed = json.loads(base64.urlsafe_b64decode(padded))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def empty_bucket() -> dict[str, int]:
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
    }


def empty_stats() -> dict[str, Any]:
    return {
        "todayPrompts": 0,
        "todaySessions": 0,
        "todayTotalTokens": 0,
        "todayTokensByModel": {},
        "recentDays": [],
        "totalPrompts": 0,
        "totalSessions": 0,
        "activeDays": 0,
        "activeDates": [],
        "modelUsage": {},
    }


def base_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "id": AGENT_ID,
        "name": AGENT_NAME,
        "updatedAt": now_utc().isoformat(),
        "ready": False,
        "hasLocalStats": False,
        "scope": "account",
        "hasPromptStats": True,
        "tierLabel": "",
        "usageStatusText": "",
        "authHelpText": "",
        "limits": [],
    }
    record.update(empty_stats())
    record.update(overrides)
    return record


def load_nous_token() -> str:
    path = hermes_home() / "auth.json"
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    providers = parsed.get("providers") if isinstance(parsed.get("providers"), dict) else {}
    nous = providers.get("nous") if isinstance(providers.get("nous"), dict) else {}
    token = str(nous.get("access_token") or nous.get("agent_key") or "").strip()
    if not token:
        pool = parsed.get("credential_pool") if isinstance(parsed.get("credential_pool"), dict) else {}
        entries = pool.get("nous")
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            token = str(entries[0].get("access_token") or entries[0].get("agent_key") or "").strip()
    return token


def fetch_portal_account(token: str) -> dict[str, Any]:
    if not token:
        return {}
    req = urllib.request.Request(
        PORTAL_URL.rstrip("/") + "/api/oauth/account",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode())
        return payload if isinstance(payload, dict) else {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}


def money_opt(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return None if amount != amount else amount


def scan_db() -> tuple[dict[str, Any], float]:
    stats = empty_stats()
    db = hermes_home() / "state.db"
    if not db.is_file():
        return stats, 0.0
    today = dt.datetime.now().date().isoformat()
    recent = {day: 0 for day in recent_dates()}
    today_by_model: dict[str, int] = {}
    model_usage: dict[str, dict[str, int]] = {}
    active: set[str] = set()
    spent = 0.0
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error:
        return stats, 0.0
    try:
        rows = con.execute(
            """
            SELECT u.model AS model,
                   u.input_tokens AS input_tokens,
                   u.output_tokens AS output_tokens,
                   u.cache_read_tokens AS cache_read_tokens,
                   u.cache_write_tokens AS cache_write_tokens,
                   COALESCE(NULLIF(u.actual_cost_usd, 0), u.estimated_cost_usd, 0) AS cost,
                   u.first_seen AS first_seen,
                   u.last_seen AS last_seen,
                   COALESCE(s.started_at, u.first_seen, u.last_seen) AS started_at,
                   s.id AS session_id,
                   COALESCE(s.message_count, 0) AS message_count
            FROM session_model_usage u
            LEFT JOIN sessions s ON s.id = u.session_id
            """
        ).fetchall()
        session_days: dict[str, str] = {}
        session_prompts: dict[str, int] = {}
        for row in rows:
            model = str(row["model"] or "unknown")
            inp = number(row["input_tokens"])
            out = number(row["output_tokens"])
            cache_r = number(row["cache_read_tokens"])
            cache_w = number(row["cache_write_tokens"])
            total = inp + out + cache_r + cache_w
            spent += money(row["cost"])
            bucket = model_usage.setdefault(model, empty_bucket())
            bucket["inputTokens"] += inp
            bucket["outputTokens"] += out
            bucket["cacheReadInputTokens"] += cache_r
            bucket["cacheCreationInputTokens"] += cache_w
            day = local_date_from_unix(row["last_seen"] or row["first_seen"] or row["started_at"])
            sid = str(row["session_id"] or "")
            if sid:
                session_days[sid] = day
                session_prompts[sid] = number(row["message_count"])
            if total <= 0:
                continue
            active.add(day)
            if day in recent:
                recent[day] += total
            if day == today:
                today_by_model[model] = today_by_model.get(model, 0) + total
        today_sessions = sum(1 for day in session_days.values() if day == today)
        today_prompts = 0
        try:
            today_prompts = number(
                con.execute(
                    """
                    SELECT COUNT(*) FROM messages
                    WHERE role = 'user' AND date(timestamp, 'unixepoch', 'localtime') = date('now', 'localtime')
                    """
                ).fetchone()[0]
            )
        except sqlite3.Error:
            today_prompts = sum(session_prompts[sid] for sid, day in session_days.items() if day == today)
        stats.update(
            {
                "todayPrompts": today_prompts,
                "todaySessions": today_sessions,
                "todayTotalTokens": sum(today_by_model.values()),
                "todayTokensByModel": today_by_model,
                "recentDays": [{"date": day, "messageCount": recent[day]} for day in recent_dates()],
                "totalPrompts": sum(session_prompts.values()),
                "totalSessions": len(session_days),
                "activeDays": len(active),
                "activeDates": sorted(active),
                "modelUsage": model_usage,
            }
        )
    finally:
        con.close()
    return stats, spent


def portal_spend(claims: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    sub = account.get("subscription") if isinstance(account.get("subscription"), dict) else {}
    access = account.get("paid_service_access") if isinstance(account.get("paid_service_access"), dict) else {}
    spent = money(access.get("member_spend_usd") if access.get("member_spend_usd") is not None else claims.get("member_spend_usd"))
    plan = sub.get("plan")
    tier = sub.get("tier") if sub.get("tier") is not None else claims.get("subscription_tier")
    if isinstance(plan, str) and plan.strip():
        label = f"Nous · {plan.strip()}"
    elif tier not in (None, ""):
        label = f"Nous · tier {tier}"
    else:
        label = "Nous"
    remaining = money_opt(access.get("total_usable_credits"))
    if remaining is None:
        sub_left = money_opt(sub.get("credits_remaining")) or 0.0
        purchased = money_opt(access.get("purchased_credits_remaining") or account.get("purchased_credits_remaining")) or 0.0
        if sub_left or purchased:
            remaining = sub_left + purchased
    out: dict[str, Any] = {"tierLabel": label, "spent": spent}
    if remaining is not None:
        funded = remaining + spent
        monthly = money_opt(sub.get("monthly_credits")) or 0.0
        if monthly > funded:
            funded = monthly
        out["balance"] = {
            "remaining": remaining,
            "funded": funded,
            "spent": spent,
            "currency": "USD",
            "estimated": False,
        }
        period_end = sub.get("current_period_end")
        if isinstance(period_end, str) and period_end.strip():
            out["resetsAt"] = period_end.strip()
    else:
        cap_n = money_opt(claims.get("member_spend_cap_usd")) or 0.0
        rem_n = money_opt(claims.get("member_spend_cap_remaining_usd"))
        if cap_n > 0 and rem_n is not None:
            out["balance"] = {
                "remaining": rem_n,
                "funded": cap_n,
                "spent": spent,
                "currency": "USD",
                "estimated": False,
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the Hermes usage record as JSON")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limits-only", action="store_true")
    args = parser.parse_args()
    stats, db_spent = empty_stats(), 0.0
    if not args.limits_only:
        stats, db_spent = scan_db()
    token = load_nous_token()
    claims = jwt_payload(token)
    account = fetch_portal_account(token)
    portal = portal_spend(claims, account)
    spent = portal.get("spent") or db_spent
    remaining = (portal.get("balance") or {}).get("remaining")
    has_stats = number(stats.get("totalSessions")) > 0 or spent > 0 or remaining is not None
    record = base_record(
        ready=has_stats,
        hasLocalStats=number(stats.get("totalSessions")) > 0,
        tierLabel=str(portal.get("tierLabel") or ("Nous" if has_stats else "")),
        usageStatusText="" if has_stats else "Hermes usage unavailable",
        authHelpText="" if has_stats else AUTH_HELP,
    )
    if portal.get("balance"):
        record["balance"] = portal["balance"]
    elif spent > 0:
        record["usageStatusText"] = f"${spent:.2f} spent"
    record.update(stats)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
