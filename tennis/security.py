"""一般公開向けのTurnstile検証と軽量レート制限。"""
from __future__ import annotations

import hashlib
import json
import logging
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


log = logging.getLogger(__name__)

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def get_client_ip(request) -> str:
    """オリジン検証済みの場合だけCloudflareの接続元IPヘッダーを信頼する。"""
    if getattr(request, "origin_verified", False):
        cloudflare_ip = (request.META.get("HTTP_CF_CONNECTING_IP") or "").strip()
        if cloudflare_ip:
            return cloudflare_ip
    return (request.META.get("REMOTE_ADDR") or "unknown").strip()


def rate_limit_exceeded(request, *, scope: str, limit: int, window_seconds: int) -> bool:
    """固定窓で回数を数える。Redis設定時は全ワーカーで共有される。"""
    if not getattr(settings, "APP_RATE_LIMIT_ENABLED", False):
        return False

    limit = max(1, int(limit))
    window_seconds = max(1, int(window_seconds))
    # セッションを作り直しても上限を回避できないよう、接続元IPを基準にする。
    identity = get_client_ip(request)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    key = f"tennis:rate:{scope}:{digest}"

    if cache.add(key, 1, timeout=window_seconds):
        return False

    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count > limit


def verify_turnstile(request, *, expected_action: str) -> bool:
    """Cloudflare SiteverifyでTurnstileトークンを検証する。障害時も失敗扱い。"""
    if not getattr(settings, "TURNSTILE_ENABLED", False):
        return True

    token = (request.POST.get("cf-turnstile-response") or "").strip()
    secret = (getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()
    if not secret or not token or len(token) > 2048:
        return False

    payload = {
        "secret": secret,
        "response": token,
        "remoteip": get_client_ip(request),
    }
    body = urlencode(payload).encode("utf-8")
    verify_request = Request(
        TURNSTILE_SITEVERIFY_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        timeout = float(getattr(settings, "TURNSTILE_TIMEOUT_SECONDS", 5))
        with urlopen(verify_request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Turnstile verification failed: %s", exc.__class__.__name__)
        return False

    if not result.get("success"):
        return False
    if expected_action and result.get("action") != expected_action:
        return False

    expected_hostname = (
        getattr(settings, "TURNSTILE_EXPECTED_HOSTNAME", "") or ""
    ).strip()
    if expected_hostname and result.get("hostname") != expected_hostname:
        return False
    return True
