"""
Wearable OAuth helpers — Fitbit + Google Fit product path.

Fixes vs legacy app_v5 inline OAuth:
  - Fitbit token exchange uses HTTP Basic client authentication
  - Google: access_type=offline + prompt=consent for refresh tokens
  - Automatic token refresh before sync
  - Localhost HTTP allowed via OAUTHLIB_INSECURE_TRANSPORT when debug
  - Clear status when credentials missing
  - Garmin marked unsupported (OAuth1) instead of broken OAuth2 attempt
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from flask import session, url_for, request
from requests_oauthlib import OAuth2Session

# Allow http://127.0.0.1 redirects in local/dev
if os.getenv("FLASK_DEBUG", "1") == "1" or os.getenv("OAUTHLIB_INSECURE_TRANSPORT") == "1":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def oauth_config() -> Dict[str, dict]:
    return {
        "fitbit": {
            "client_id": os.getenv("FITBIT_CLIENT_ID"),
            "client_secret": os.getenv("FITBIT_CLIENT_SECRET"),
            "auth_uri": "https://www.fitbit.com/oauth2/authorize",
            "token_uri": "https://api.fitbit.com/oauth2/token",
            "scope": ["activity", "heartrate", "sleep", "weight", "profile"],
            "label": "Fitbit",
            "supported": True,
        },
        "googlefit": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scope": [
                "openid",
                "https://www.googleapis.com/auth/fitness.activity.read",
                "https://www.googleapis.com/auth/fitness.heart_rate.read",
                "https://www.googleapis.com/auth/fitness.sleep.read",
            ],
            "label": "Google Fit",
            "supported": True,
        },
        "garmin": {
            "client_id": os.getenv("GARMIN_CLIENT_ID"),
            "client_secret": os.getenv("GARMIN_CLIENT_SECRET"),
            "auth_uri": "",
            "token_uri": "",
            "scope": [],
            "label": "Garmin",
            "supported": False,
            "note": "Garmin uses OAuth1 — not wired in this build. Use CSV import.",
        },
    }


def provider_status() -> Dict[str, dict]:
    out = {}
    for key, cfg in oauth_config().items():
        out[key] = {
            "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
            "supported": cfg.get("supported", False),
            "label": cfg.get("label", key),
            "note": cfg.get("note", ""),
        }
    return out


def redirect_uri(provider: str) -> str:
    return request.url_root.rstrip("/") + url_for("oauth_callback", provider=provider)


def begin_auth(provider: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (auth_url, error)."""
    cfg = oauth_config().get(provider)
    if not cfg:
        return None, "Unknown provider."
    if not cfg.get("supported"):
        return None, cfg.get("note") or f"{provider} is not supported."
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        return None, (
            f"{cfg['label']} credentials missing. Set "
            f"{'FITBIT_CLIENT_ID/SECRET' if provider == 'fitbit' else 'GOOGLE_CLIENT_ID/SECRET'} "
            "and register the redirect URI in the provider console."
        )

    cb = redirect_uri(provider)
    extra = {}
    if provider == "googlefit":
        extra = {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
    oauth = OAuth2Session(cfg["client_id"], redirect_uri=cb, scope=cfg.get("scope") or [])
    auth_url, state = oauth.authorization_url(cfg["auth_uri"], **extra)
    session[f"oauth_state_{provider}"] = state
    session[f"oauth_redirect_{provider}"] = cb
    return auth_url, None


def _fitbit_fetch_token(cfg: dict, authorization_response: str, redirect_uri_: str) -> dict:
    """Fitbit requires Basic auth with client_id:client_secret for token exchange."""
    oauth = OAuth2Session(
        cfg["client_id"],
        state=session.get(f"oauth_state_fitbit"),
        redirect_uri=redirect_uri_,
    )
    auth_header = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    token = oauth.fetch_token(
        cfg["token_uri"],
        authorization_response=authorization_response,
        code=None,
        client_secret=cfg["client_secret"],
        include_client_id=True,
        headers={"Authorization": f"Basic {auth_header}"},
    )
    return token


def finish_auth(provider: str) -> Tuple[Optional[dict], Optional[str]]:
    cfg = oauth_config().get(provider)
    if not cfg or not cfg.get("supported"):
        return None, "Provider not available."
    cb = session.get(f"oauth_redirect_{provider}") or redirect_uri(provider)
    try:
        if provider == "fitbit":
            token = _fitbit_fetch_token(cfg, request.url, cb)
        else:
            oauth = OAuth2Session(
                cfg["client_id"],
                state=session.get(f"oauth_state_{provider}"),
                redirect_uri=cb,
            )
            token = oauth.fetch_token(
                cfg["token_uri"],
                client_secret=cfg["client_secret"],
                authorization_response=request.url,
                include_client_id=True,
            )
        token["obtained_at"] = int(time.time())
        return token, None
    except Exception as e:
        return None, (
            f"OAuth failed: {e}. Check that redirect URI `{cb}` is registered exactly, "
            "and that client id/secret match the provider console."
        )


def _token_expired(token: dict) -> bool:
    if not token.get("expires_at") and token.get("expires_in") and token.get("obtained_at"):
        token["expires_at"] = token["obtained_at"] + int(token["expires_in"])
    exp = token.get("expires_at")
    if not exp:
        return False
    return time.time() > (float(exp) - 60)


def refresh_token_if_needed(provider: str, token: dict) -> Tuple[dict, Optional[str]]:
    if not _token_expired(token):
        return token, None
    cfg = oauth_config()[provider]
    if not token.get("refresh_token"):
        return token, "Token expired and no refresh_token — please reconnect."
    try:
        if provider == "fitbit":
            oauth = OAuth2Session(cfg["client_id"], token=token)
            auth_header = base64.b64encode(
                f"{cfg['client_id']}:{cfg['client_secret']}".encode()
            ).decode()
            new_token = oauth.refresh_token(
                cfg["token_uri"],
                refresh_token=token["refresh_token"],
                headers={"Authorization": f"Basic {auth_header}"},
            )
        else:
            oauth = OAuth2Session(cfg["client_id"], token=token)
            new_token = oauth.refresh_token(
                cfg["token_uri"],
                client_id=cfg["client_id"],
                client_secret=cfg["client_secret"],
            )
        new_token["obtained_at"] = int(time.time())
        # Preserve refresh_token if provider omits it on refresh
        if "refresh_token" not in new_token and token.get("refresh_token"):
            new_token["refresh_token"] = token["refresh_token"]
        return new_token, None
    except Exception as e:
        return token, f"Token refresh failed: {e}. Reconnect your watch."


def sync_provider(provider: str, token: dict) -> Tuple[Dict[str, Any], Optional[dict], Optional[str]]:
    """
    Returns (synced_fields, updated_token_or_None, error).
    """
    cfg = oauth_config().get(provider)
    if not cfg or not cfg.get("supported"):
        return {}, None, "Provider not supported."
    token, err = refresh_token_if_needed(provider, token)
    updated = token
    if err and "expired" in err.lower():
        return {}, None, err

    oauth = OAuth2Session(cfg["client_id"], token=token)
    today = dt.date.today().isoformat()
    synced: Dict[str, Any] = {}

    try:
        if provider == "fitbit":
            r_act = oauth.get(f"https://api.fitbit.com/1/user/-/activities/date/{today}.json")
            r_slp = oauth.get(f"https://api.fitbit.com/1.2/user/-/sleep/date/{today}.json")
            if r_act.status_code == 401:
                return {}, None, "Fitbit unauthorized — reconnect."
            if r_act.status_code == 200:
                act = r_act.json()
                summary = act.get("summary", {})
                synced["steps"] = summary.get("steps")
                synced["active_minutes"] = (
                    summary.get("veryActiveMinutes", 0) + summary.get("fairlyActiveMinutes", 0)
                )
            if r_slp.status_code == 200:
                mins = r_slp.json().get("summary", {}).get("totalMinutesAsleep", 0)
                synced["sleep"] = round(mins / 60, 1) if mins else None

        elif provider == "googlefit":
            now_ms = int(dt.datetime.now().timestamp() * 1000)
            start_ms = int(
                dt.datetime.combine(dt.date.today(), dt.time.min).timestamp() * 1000
            )
            body = {
                "aggregateBy": [
                    {"dataTypeName": "com.google.step_count.delta"},
                    {"dataTypeName": "com.google.active_minutes"},
                ],
                "bucketByTime": {"durationMillis": 86400000},
                "startTimeMillis": start_ms,
                "endTimeMillis": now_ms,
            }
            r = oauth.post(
                "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate",
                json=body,
            )
            if r.status_code == 401:
                return {}, None, "Google Fit unauthorized — reconnect."
            if r.status_code == 200:
                for bucket in r.json().get("bucket", []):
                    for ds in bucket.get("dataset", []):
                        dtype = ds.get("dataSourceId", "") + str(ds.get("point", ""))
                        name = ""
                        # dataTypeName is in the request mapping order; inspect points
                        for pt in ds.get("point", []):
                            for val in pt.get("value", []):
                                iv = val.get("intVal")
                                if iv is None:
                                    continue
                                # Heuristic: step counts are usually large; active minutes small
                                if iv > 100 or "step_count" in json.dumps(ds):
                                    synced["steps"] = synced.get("steps", 0) + iv
                                else:
                                    synced["active_minutes"] = synced.get("active_minutes", 0) + iv
                # Better parse using dataTypeName from aggregateBy echo
                synced = {}
                for bucket in r.json().get("bucket", []):
                    for ds in bucket.get("dataset", []):
                        points = ds.get("point", [])
                        total = 0
                        for pt in points:
                            for val in pt.get("value", []):
                                total += val.get("intVal", 0) or int(val.get("fpVal", 0) or 0)
                        # Match by original request order via dataSourceId
                        src = ds.get("dataSourceId", "")
                        if "step_count" in src:
                            synced["steps"] = synced.get("steps", 0) + total
                        elif "active_minutes" in src:
                            synced["active_minutes"] = synced.get("active_minutes", 0) + total
                        elif not src and points:
                            # Fallback: first dataset steps-ish
                            if "steps" not in synced:
                                synced["steps"] = total
                            else:
                                synced["active_minutes"] = total

        return synced, updated, None
    except Exception as e:
        return {}, updated, str(e)
