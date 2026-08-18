"""Turnstile、オリジン検証、レート制限のテスト。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from tennis.models import Club
from tennis.security import verify_turnstile
from tennis_project.middleware import OriginVerifyMiddleware, WriteRateLimitMiddleware


class _SiteverifyResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class TurnstileValidationTests(TestCase):
    @override_settings(
        TURNSTILE_ENABLED=True,
        TURNSTILE_SECRET_KEY="test-secret",
        TURNSTILE_EXPECTED_HOSTNAME="deucenet.app",
    )
    def test_siteverify_success_requires_matching_action_and_hostname(self):
        request = RequestFactory().post(
            "/", {"cf-turnstile-response": "valid-token"}
        )
        result = {
            "success": True,
            "action": "club-create",
            "hostname": "deucenet.app",
        }
        with patch("tennis.security.urlopen", return_value=_SiteverifyResponse(result)):
            self.assertTrue(verify_turnstile(request, expected_action="club-create"))
            self.assertFalse(verify_turnstile(request, expected_action="demo-create"))

    @override_settings(TURNSTILE_ENABLED=True, TURNSTILE_SECRET_KEY="test-secret")
    def test_missing_token_fails_closed_without_network_call(self):
        request = RequestFactory().post("/", {})
        with patch("tennis.security.urlopen") as mocked:
            self.assertFalse(verify_turnstile(request, expected_action="club-create"))
            mocked.assert_not_called()


class OriginVerifyMiddlewareTests(TestCase):
    @override_settings(ORIGIN_VERIFY_ENABLED=True, ORIGIN_VERIFY_SECRET="origin-secret")
    def test_secret_header_is_required_except_healthcheck(self):
        middleware = OriginVerifyMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        factory = RequestFactory()

        denied = middleware(factory.get("/"))
        self.assertEqual(denied.status_code, 403)

        allowed = middleware(factory.get("/", HTTP_X_ORIGIN_VERIFY="origin-secret"))
        self.assertEqual(allowed.status_code, 200)

        health = middleware(factory.get("/healthz"))
        self.assertEqual(health.status_code, 200)


class WriteRateLimitMiddlewareTests(TestCase):
    @override_settings(
        APP_RATE_LIMIT_ENABLED=True,
        WRITE_RATE_LIMIT=2,
        WRITE_RATE_WINDOW_SECONDS=60,
    )
    def test_third_write_is_rejected(self):
        cache.clear()
        middleware = WriteRateLimitMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        factory = RequestFactory()

        responses = []
        for _ in range(3):
            request = factory.post("/api/example/", REMOTE_ADDR="203.0.113.10")
            request.session = SimpleNamespace(session_key="same-session")
            responses.append(middleware(request))

        self.assertEqual([response.status_code for response in responses], [200, 200, 429])
        self.assertEqual(responses[-1]["Retry-After"], "60")


@override_settings(
    TURNSTILE_ENABLED=True,
    TURNSTILE_SITE_KEY="test-site-key",
    TURNSTILE_SECRET_KEY="test-secret",
    TURNSTILE_EXPECTED_HOSTNAME="",
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class TurnstilePageTests(TestCase):
    def test_demo_get_shows_gate_without_creating_records(self):
        response = self.client.get(reverse("tennis:demo"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-action="demo-create"')
        self.assertFalse(Club.objects.filter(is_demo=True).exists())

    def test_club_creation_without_token_is_rejected(self):
        response = self.client.post(reverse("tennis:index"), {"club_name": "新クラブ"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "確認に失敗しました", status_code=400)
        self.assertFalse(Club.objects.filter(name="新クラブ").exists())
