#!/usr/bin/python3
"""Collect Antigravity (agy) quota into one Omarchy agents-panel JSON record."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AGENT_ID = "antigravity"
AGENT_NAME = "Agy"
AUTH_HELP = "Run `agy` and sign in with Google to restore Antigravity quota."
HOSTS = (
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
)
SECRET_ATTRS = ("service", "gemini", "username", "antigravity")
SECRET_LABEL = "Password for 'antigravity' on 'gemini'"
AGY_BIN = Path(os.environ.get("AGY_BIN") or (Path.home() / ".local/bin/agy"))
TOKEN_SKEW_S = 120


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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
        "authHelpText": AUTH_HELP,
        "limits": [],
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
    record.update(overrides)
    return record


def secret_lookup() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", *SECRET_ATTRS],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def secret_store(payload: dict[str, Any]) -> None:
    try:
        subprocess.run(
            ["secret-tool", "store", "--label=" + SECRET_LABEL, *SECRET_ATTRS],
            input=json.dumps(payload, separators=(",", ":")),
            text=True,
            check=False,
            timeout=8,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def parse_expiry(raw: Any) -> dt.datetime | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        seconds = float(raw)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    text = str(raw).strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def extract_oauth_client() -> tuple[str, str]:
    """Read the installed-app OAuth client out of the official agy binary."""
    try:
        blob = AGY_BIN.read_bytes()
    except OSError:
        return "", ""
    ids = re.findall(rb"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com", blob)
    secrets = re.findall(rb"GOCSPX-[A-Za-z0-9_-]+", blob)
    client_id = ""
    for item in ids:
        text = item.decode()
        if text.startswith("1071006060591-"):
            client_id = text
            break
    if not client_id and ids:
        client_id = ids[0].decode()
    client_secret = secrets[0].decode() if secrets else ""
    return client_id, client_secret


def refresh_access(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = extract_oauth_client()
    if not refresh_token or not client_id:
        return {}
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_token() -> tuple[str, str]:
    stored = secret_lookup()
    token = stored.get("token") if isinstance(stored.get("token"), dict) else stored
    if not isinstance(token, dict):
        return "", "not_logged_in"
    access = str(token.get("access_token") or "").strip()
    refresh = str(token.get("refresh_token") or "").strip()
    expiry = parse_expiry(token.get("expiry") or token.get("expiry_date") or token.get("expires_at"))
    stale = (not access) or (expiry is not None and expiry <= now_utc() + dt.timedelta(seconds=TOKEN_SKEW_S))
    if stale and refresh:
        fresh = refresh_access(refresh)
        new_access = str(fresh.get("access_token") or "").strip()
        if new_access:
            access = new_access
            if fresh.get("refresh_token"):
                refresh = str(fresh["refresh_token"])
            expires_in = fresh.get("expires_in")
            new_expiry = (
                (now_utc() + dt.timedelta(seconds=int(expires_in))).isoformat()
                if expires_in
                else token.get("expiry")
            )
            updated = {
                "token": {
                    "access_token": access,
                    "token_type": str(fresh.get("token_type") or token.get("token_type") or "Bearer"),
                    "refresh_token": refresh,
                    "expiry": new_expiry,
                },
                "auth_method": stored.get("auth_method") or "consumer",
            }
            secret_store(updated)
    if not access:
        return "", "not_logged_in"
    return access, ""


def post_json(host: str, method: str, token: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(
        f"{host}/v1internal:{method}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "antigravity",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
            return response.status, payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode())
        except Exception:
            payload = {}
        return error.code, payload if isinstance(payload, dict) else {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 0, {}


def load_quota(token: str) -> dict[str, Any]:
    last_error = "quota_unavailable"
    for host in HOSTS:
        status, assist = post_json(host, "loadCodeAssist", token, {"metadata": {"ideType": "ANTIGRAVITY"}})
        if status == 401:
            return {"error": "expired"}
        if status != 200:
            last_error = f"assist_{status or 'net'}"
            continue
        project = str(assist.get("cloudaicompanionProject") or "").strip()
        if not project:
            last_error = "no_project"
            continue
        status, summary = post_json(host, "retrieveUserQuotaSummary", token, {"project": project})
        if status == 401:
            return {"error": "expired"}
        if status != 200:
            last_error = f"summary_{status or 'net'}"
            continue
        return {"assist": assist, "summary": summary, "host": host}
    return {"error": last_error}


def remaining_fraction(bucket: dict[str, Any]) -> float | None:
    remaining = bucket.get("remaining") if isinstance(bucket.get("remaining"), dict) else bucket
    raw = remaining.get("remainingFraction") if isinstance(remaining, dict) else None
    if raw is None:
        raw = bucket.get("remainingFraction")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return max(0.0, min(1.0, value))


def reset_at(bucket: dict[str, Any]) -> str:
    remaining = bucket.get("remaining") if isinstance(bucket.get("remaining"), dict) else {}
    raw = bucket.get("resetTime") or remaining.get("resetTime") or remaining.get("reset_at") or ""
    return str(raw or "")


def friendly_group(name: str) -> str:
    text = str(name or "").strip()
    low = text.lower()
    if "claude" in low or "gpt" in low:
        return "Claude/GPT"
    if "gemini" in low:
        return "Gemini"
    return text or "Quota"


def friendly_window(name: str) -> str:
    low = str(name or "").lower()
    if "five" in low or "5 hour" in low or "5-hour" in low or "session" in low:
        return "5-hour"
    if "week" in low:
        return "Weekly"
    return str(name or "Limit").strip() or "Limit"


def limits_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    limits: list[dict[str, Any]] = []
    groups = summary.get("groups") if isinstance(summary.get("groups"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        family = friendly_group(str(group.get("displayName") or group.get("name") or ""))
        buckets = group.get("buckets") if isinstance(group.get("buckets"), list) else []
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            remaining = remaining_fraction(bucket)
            if remaining is None:
                continue
            window = friendly_window(str(bucket.get("displayName") or bucket.get("bucketId") or ""))
            limits.append(
                {
                    "label": f"{family} · {window}",
                    "percent": round(1.0 - remaining, 4),
                    "resetsAt": reset_at(bucket),
                }
            )
    if not limits:
        buckets = summary.get("buckets") if isinstance(summary.get("buckets"), list) else []
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            remaining = remaining_fraction(bucket)
            if remaining is None:
                continue
            name = str(bucket.get("displayName") or bucket.get("modelId") or bucket.get("bucketId") or "Quota")
            if name.startswith("tab_") or name.startswith("chat_"):
                continue
            limits.append({"label": name, "percent": round(1.0 - remaining, 4), "resetsAt": reset_at(bucket)})
    limits.sort(key=lambda item: (-float(item["percent"]), item["label"]))
    return limits


def tier_label(assist: dict[str, Any]) -> str:
    current = assist.get("currentTier") if isinstance(assist.get("currentTier"), dict) else {}
    name = str(current.get("name") or "Antigravity").strip()
    tier_id = str(current.get("id") or "").strip()
    if tier_id in ("free-tier", "free"):
        return f"{name} · free"
    if tier_id:
        pretty = tier_id.replace("-tier", "").replace("-", " ")
        return f"{name} · {pretty}"
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the Antigravity usage record as JSON")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limits-only", action="store_true")
    args = parser.parse_args()
    token, auth_error = resolve_token()
    if not token:
        print(json.dumps(base_record(usageStatusText="Antigravity not signed in"), separators=(",", ":"), sort_keys=True))
        return 0
    quota = load_quota(token)
    if quota.get("error") == "expired":
        # One retry after a forced refresh.
        stored = secret_lookup()
        inner = stored.get("token") if isinstance(stored.get("token"), dict) else stored
        refresh = str((inner or {}).get("refresh_token") or "")
        fresh = refresh_access(refresh) if refresh else {}
        token = str(fresh.get("access_token") or "")
        if token:
            quota = load_quota(token)
        else:
            quota = {"error": "expired"}
    if quota.get("error") or not isinstance(quota.get("summary"), dict):
        print(
            json.dumps(
                base_record(
                    usageStatusText="Antigravity quota unavailable",
                    authHelpText=AUTH_HELP,
                ),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    assist = quota.get("assist") if isinstance(quota.get("assist"), dict) else {}
    limits = limits_from_summary(quota["summary"])
    record = base_record(
        ready=bool(limits),
        tierLabel=tier_label(assist),
        usageStatusText="",
        authHelpText="" if limits else AUTH_HELP,
        limits=limits,
    )
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
