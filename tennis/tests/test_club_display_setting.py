"""
ClubDisplaySetting（クラブ単位デフォルト表示設定）と
イベント表示設定のフォールバック挙動のテスト。
"""
from __future__ import annotations

import json
import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis.models import ClubDisplaySetting, EventDisplaySetting
from tennis.views import (
    HARDCODED_DISPLAY_SETTINGS_DEFAULT,
    _resolve_club_display_settings,
    _resolve_event_display_settings,
)

from .factories import make_club, make_event


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class ResolveDisplaySettingsTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 1))

    def test_resolve_club_default_falls_back_to_hardcoded(self):
        """ClubDisplaySetting 行が無いクラブは ハードコード値を返す。"""
        d = _resolve_club_display_settings(self.club)
        self.assertEqual(d, HARDCODED_DISPLAY_SETTINGS_DEFAULT)

    def test_resolve_club_default_uses_db_row(self):
        """ClubDisplaySetting があればそれを返す。"""
        ClubDisplaySetting.objects.create(
            club=self.club,
            show_flags=False,
            show_event_flags=True,
            show_class=False,
            show_schedule=True,
        )
        d = _resolve_club_display_settings(self.club)
        self.assertEqual(d, {
            "common_flags": False,
            "event_flags": True,
            "class": False,
            "schedule": True,
        })

    def test_resolve_event_uses_event_setting_when_present(self):
        """EventDisplaySetting あり → source="db"、event 値を返す。"""
        EventDisplaySetting.objects.create(
            event=self.event,
            show_flags=False, show_event_flags=True,
            show_class=False, show_schedule=False,
        )
        d, src = _resolve_event_display_settings(self.event)
        self.assertEqual(src, "db")
        self.assertEqual(d, {
            "common_flags": False,
            "event_flags": True,
            "class": False,
            "schedule": False,
        })

    def test_resolve_event_falls_back_to_club_default(self):
        """EventDisplaySetting なし & ClubDisplaySetting あり → クラブ値・source="default"。"""
        ClubDisplaySetting.objects.create(
            club=self.club,
            show_flags=False, show_event_flags=True,
            show_class=True, show_schedule=False,
        )
        d, src = _resolve_event_display_settings(self.event)
        self.assertEqual(src, "default")  # 既存テスト互換
        self.assertEqual(d, {
            "common_flags": False,
            "event_flags": True,
            "class": True,
            "schedule": False,
        })

    def test_resolve_event_falls_back_to_hardcoded(self):
        """何も無ければハードコード値・source="default"。"""
        d, src = _resolve_event_display_settings(self.event)
        self.assertEqual(src, "default")
        self.assertEqual(d, HARDCODED_DISPLAY_SETTINGS_DEFAULT)


@_NO_MANIFEST_STORAGES
class SaveClubDisplaySettingApiTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.url = reverse("tennis:save_club_display_setting")

    def _post(self, **payload_overrides):
        body = {
            "club_id": str(self.club.id),
            "admin_token": self.club.admin_token,
            "settings_json": json.dumps({
                "common_flags": False,
                "event_flags": True,
                "class": False,
                "schedule": True,
            }),
        }
        body.update(payload_overrides)
        return self.client.post(self.url, body)

    def test_save_creates_row_and_persists_values(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["settings"], {
            "common_flags": False,
            "event_flags": True,
            "class": False,
            "schedule": True,
        })

        row = ClubDisplaySetting.objects.get(club=self.club)
        self.assertFalse(row.show_flags)
        self.assertTrue(row.show_event_flags)
        self.assertFalse(row.show_class)
        self.assertTrue(row.show_schedule)

    def test_save_updates_existing_row(self):
        ClubDisplaySetting.objects.create(club=self.club)  # 全部 default(True/False/True/True)
        self._post()
        row = ClubDisplaySetting.objects.get(club=self.club)
        self.assertFalse(row.show_flags)
        self.assertTrue(row.show_event_flags)

    def test_save_requires_admin_token(self):
        resp = self._post(admin_token="wrong")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ClubDisplaySetting.objects.filter(club=self.club).exists())

    def test_save_rejects_missing_keys(self):
        resp = self._post(settings_json=json.dumps({"common_flags": True}))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "bad_settings_keys")

    def test_save_rejects_bad_json(self):
        resp = self._post(settings_json="{not-json")
        self.assertEqual(resp.status_code, 400)


@_NO_MANIFEST_STORAGES
class SettingsPageDisplayDefaultContextTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.url = reverse(
            "tennis:club_settings",
            args=[self.club.public_token, self.club.admin_token],
        )

    def test_context_default_when_no_row(self):
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["default_display_settings"], HARDCODED_DISPLAY_SETTINGS_DEFAULT)

    def test_context_reflects_db_row(self):
        ClubDisplaySetting.objects.create(
            club=self.club,
            show_flags=False, show_event_flags=True,
            show_class=False, show_schedule=False,
        )
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["default_display_settings"], {
            "common_flags": False,
            "event_flags": True,
            "class": False,
            "schedule": False,
        })
