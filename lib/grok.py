#!/usr/bin/python3
"""Collect Grok Build usage into one Omarchy agents-panel JSON record."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AGENT_ID = "grok"
AGENT_NAME = "Grok"
AUTH_HELP = "Run `grok login` to restore Grok Build usage."
BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
TOKEN_AUTH = "xai-grok-cli"


def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok")).expanduser()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def local_date(ts: float | None = None) -> str:
    when = dt.datetime.fromtimestamp(ts) if ts is not None else dt.datetime.now()
    return when.date().isoformat()


def recent_dates() -> list[str]:
    today = dt.datetime.now().date()
    return [(today - dt.timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def number(value: Any) -> int:
    try:
        return max(0, round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


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
        "tierLabel": "",
        "usageStatusText": "",
        "authHelpText": "",
        "limits": [],
    }
    record.update(empty_stats())
    record.update(overrides)
    return record


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


def load_auth() -> dict[str, Any]:
    path = grok_home() / "auth.json"
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict) or not parsed:
        return {}
    # File is keyed by issuer::client. Take the first (usually only) session.
    entry = next(iter(parsed.values()))
    return entry if isinstance(entry, dict) else {}


def save_auth(updated: dict[str, Any]) -> None:
    path = grok_home() / "auth.json"
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(parsed, dict) or not parsed:
        return
    key = next(iter(parsed))
    parsed[key] = updated
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(parsed, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def token_expired(entry: dict[str, Any], skew_s: int = 60) -> bool:
    raw = str(entry.get("expires_at") or "").strip()
    if not raw:
        return False
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed <= now_utc() + dt.timedelta(seconds=skew_s)
    except ValueError:
        return False


def refresh_auth(entry: dict[str, Any]) -> dict[str, Any]:
    issuer = str(entry.get("oidc_issuer") or "https://auth.x.ai").rstrip("/")
    client_id = str(entry.get("oidc_client_id") or "").strip()
    refresh = str(entry.get("refresh_token") or "").strip()
    if not refresh:
        return entry
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        }
    ).encode()
    req = urllib.request.Request(
        issuer + "/oauth2/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return entry
    if not isinstance(payload, dict) or not payload.get("access_token"):
        return entry
    updated = dict(entry)
    updated["key"] = payload["access_token"]
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    expires_in = payload.get("expires_in")
    if expires_in:
        updated["expires_at"] = (now_utc() + dt.timedelta(seconds=int(expires_in))).isoformat()
    try:
        save_auth(updated)
    except OSError:
        pass
    return updated


def client_version() -> str:
    path = grok_home() / "version.json"
    try:
        parsed = json.loads(path.read_text())
        return str(parsed.get("version") or "1.0.4")
    except Exception:
        return "1.0.4"


def http_json(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.load(error)
        except Exception:
            body = {}
        return error.code, body
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 0, {}


def probe_billing(entry: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "limits": [], "tierLabel": "", "help": AUTH_HELP}
    key = str(entry.get("key") or "").strip()
    if not key:
        result["help"] = AUTH_HELP
        return result
    if token_expired(entry):
        entry = refresh_auth(entry)
        key = str(entry.get("key") or "").strip()
    headers = {
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "X-XAI-Token-Auth": TOKEN_AUTH,
        "x-grok-client-version": client_version(),
    }
    user_id = str(entry.get("user_id") or "").strip()
    if user_id:
        headers["x-userid"] = user_id
    status, payload = http_json(BILLING_URL, headers)
    if status == 401:
        entry = refresh_auth(entry)
        key = str(entry.get("key") or "").strip()
        headers["Authorization"] = "Bearer " + key
        status, payload = http_json(BILLING_URL, headers)
    if status != 200 or not isinstance(payload, dict):
        result["help"] = "Grok billing unavailable. Try `grok login` if this persists."
        return result
    config = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    percent = config.get("creditUsagePercent")
    if percent is None:
        products = config.get("productUsage")
        if isinstance(products, list):
            for item in products:
                if isinstance(item, dict) and str(item.get("product") or "").lower() in ("grokbuild", "grok-build", "build"):
                    percent = item.get("usagePercent")
                    break
            if percent is None and products and isinstance(products[0], dict):
                percent = products[0].get("usagePercent")
    try:
        used = max(0.0, min(1.0, float(percent) / (100.0 if float(percent) > 1 else 1.0)))
    except (TypeError, ValueError):
        used = None
    period = config.get("currentPeriod") if isinstance(config.get("currentPeriod"), dict) else {}
    resets = period.get("end") or period.get("resetsAt") or period.get("reset_at")
    if used is not None:
        result["ok"] = True
        result["limits"] = [{"label": "Weekly (7-day)", "percent": used, "resetsAt": str(resets or "")}]
    display = config.get("subscription_tier_display")
    claims = jwt_payload(str(entry.get("key") or ""))
    tier = claims.get("plan") or claims.get("subscription_tier")
    if isinstance(display, str) and display.strip():
        result["tierLabel"] = display.strip()
    elif isinstance(tier, str) and tier.strip() and not str(tier).isdigit():
        result["tierLabel"] = tier.strip()
    else:
        result["tierLabel"] = "Grok Build"
    result["help"] = ""
    return result


def scan_sessions() -> dict[str, Any]:
    stats = empty_stats()
    today = local_date()
    recent = {day: 0 for day in recent_dates()}
    today_by_model: dict[str, int] = {}
    model_usage: dict[str, dict[str, int]] = {}
    active: set[str] = set()
    total_prompts = 0
    today_prompts = 0
    today_sessions = 0
    total_sessions = 0
    root = grok_home() / "sessions"
    if not root.is_dir():
        return stats
    for path in root.rglob("signals.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        prompts = number(data.get("userMessageCount"))
        tokens = number(data.get("contextTokensUsed")) or number(data.get("totalTokensBeforeCompaction"))
        if prompts <= 0 and tokens <= 0:
            continue
        model = str(data.get("primaryModelId") or "").strip()
        if not model:
            used = data.get("modelsUsed")
            if isinstance(used, list) and used:
                model = str(used[0])
        if not model:
            model = "grok"
        day = local_date(path.stat().st_mtime)
        bucket = model_usage.setdefault(model, empty_bucket())
        bucket["inputTokens"] += tokens
        total_sessions += 1
        total_prompts += prompts
        active.add(day)
        if day in recent:
            recent[day] += tokens
        if day == today:
            today_sessions += 1
            today_prompts += prompts
            today_by_model[model] = today_by_model.get(model, 0) + tokens
    stats.update(
        {
            "todayPrompts": today_prompts,
            "todaySessions": today_sessions,
            "todayTotalTokens": sum(today_by_model.values()),
            "todayTokensByModel": today_by_model,
            "recentDays": [{"date": day, "messageCount": recent[day]} for day in recent_dates()],
            "totalPrompts": total_prompts,
            "totalSessions": total_sessions,
            "activeDays": len(active),
            "activeDates": sorted(active),
            "modelUsage": model_usage,
        }
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the Grok usage record as JSON")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limits-only", action="store_true")
    args = parser.parse_args()
    auth = load_auth()
    stats = empty_stats() if args.limits_only else scan_sessions()
    billing = probe_billing(auth) if auth else {"ok": False, "limits": [], "tierLabel": "", "help": AUTH_HELP}
    has_stats = number(stats.get("totalPrompts")) > 0 or number(stats.get("totalSessions")) > 0
    record = base_record(
        ready=has_stats or bool(billing.get("ok")),
        hasLocalStats=has_stats,
        tierLabel=str(billing.get("tierLabel") or ("Grok Build" if has_stats else "")),
        usageStatusText="" if billing.get("ok") or has_stats else "Grok usage unavailable",
        authHelpText="" if billing.get("ok") else str(billing.get("help") or AUTH_HELP),
        limits=billing.get("limits") or [],
    )
    record.update(stats)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
