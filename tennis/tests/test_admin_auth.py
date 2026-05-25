"""
club系管理APIの認可応答 標準化テスト（候補7）。

旧実装は status(400/403)・error文字列がバラついていた。本テストは
統一後の挙動を固定する：幹事トークン不一致 → 403 {"ok": False, "error": "forbidden"}。

フロントは r.ok / data.ok / data.error の有無で判定しており、認可エラーの
具体値で機能分岐していないことを調査済み（変更はフロント機能に影響しない）。
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .factories import (
    make_club,
    make_event,
    make_member,
    make_club_flag,
)
from tennis.models import ClubMemberClass


WRONG = "wrong-admin-token"


class AdminAuthRejectionTests(TestCase):
    """各エンドポイントで「幹事トークン不一致 → 403 forbidden」に統一されていること。"""

    def setUp(self):
        self.club = make_club()
        self.future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=self.future)
        self.flag = make_club_flag(self.club, "車", 1)
        self.member = make_member(self.club, "Aさん", member_no=1)
        self.klass = ClubMemberClass.objects.create(club=self.club, name="初級", display_order=1)

    def _assert_forbidden(self, url_name, data):
        resp = self.client.post(reverse(url_name), data)
        self.assertEqual(resp.status_code, 403, f"{url_name}: status")
        body = resp.json()
        self.assertFalse(body.get("ok", False), f"{url_name}: ok should be False")
        self.assertEqual(body.get("error"), "forbidden", f"{url_name}: error")

    def test_add_flag(self):
        self._assert_forbidden("tennis:club_add_flag",
                               {"club_id": self.club.id, "name": "新", "admin_token": WRONG})

    def test_delete_flag(self):
        self._assert_forbidden("tennis:club_delete_flag",
                               {"club_id": self.club.id, "flag_id": self.flag.id, "admin_token": WRONG})

    def test_rename_flag(self):
        self._assert_forbidden("tennis:club_rename_flag",
                               {"flag_id": self.flag.id, "name": "新", "admin_token": WRONG})

    def test_set_flag_input_mode(self):
        self._assert_forbidden("tennis:club_set_flag_input_mode",
                               {"club_id": self.club.id, "flag_input_mode": "check", "admin_token": WRONG})

    def test_rename_club(self):
        self._assert_forbidden("tennis:club_rename_club",
                               {"club_id": self.club.id, "name": "新名", "admin_token": WRONG})

    def test_create_event(self):
        self._assert_forbidden("tennis:club_create_event",
                               {"club_id": self.club.id, "date": "2026-06-01", "admin_token": WRONG})

    def test_cancel_event(self):
        self._assert_forbidden("tennis:club_cancel_event",
                               {"event_id": self.event.id, "admin_token": WRONG})

    def test_delete_event(self):
        self._assert_forbidden("tennis:club_delete_event",
                               {"event_id": self.event.id, "admin_token": WRONG})

    def test_add_member(self):
        self._assert_forbidden("tennis:club_add_member",
                               {"club_id": self.club.id, "display_name": "X", "admin_token": WRONG})

    def test_rename_member(self):
        self._assert_forbidden("tennis:club_rename_member",
                               {"club_id": self.club.id, "member_id": self.member.id,
                                "display_name": "X", "admin_token": WRONG})

    def test_toggle_member_fixed(self):
        self._assert_forbidden("tennis:club_toggle_member_fixed",
                               {"club_id": self.club.id, "member_id": self.member.id,
                                "checked": "1", "admin_token": WRONG})

    def test_add_class(self):
        self._assert_forbidden("tennis:club_add_class",
                               {"club_id": self.club.id, "name": "中級", "admin_token": WRONG})

    def test_rename_class(self):
        self._assert_forbidden("tennis:club_rename_class",
                               {"club_id": self.club.id, "class_id": self.klass.id,
                                "name": "中級", "admin_token": WRONG})

    def test_delete_class(self):
        self._assert_forbidden("tennis:club_delete_class",
                               {"club_id": self.club.id, "class_id": self.klass.id, "admin_token": WRONG})

    def test_set_member_class(self):
        self._assert_forbidden("tennis:club_set_member_class",
                               {"club_id": self.club.id, "member_id": self.member.id,
                                "class_id": self.klass.id, "admin_token": WRONG})


class AdminAuthHappyPathTests(TestCase):
    """正しい admin_token なら成功する（認可ヘルパが正常系を阻害しないこと）。"""

    def setUp(self):
        self.club = make_club()
        self.member = make_member(self.club, "Aさん", member_no=1)
        self.klass = ClubMemberClass.objects.create(club=self.club, name="初級", display_order=1)

    def test_rename_club_succeeds(self):
        resp = self.client.post(reverse("tennis:club_rename_club"),
                                {"club_id": self.club.id, "name": "新クラブ名",
                                 "admin_token": self.club.admin_token})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.club.refresh_from_db()
        self.assertEqual(self.club.name, "新クラブ名")

    def test_add_class_succeeds(self):
        resp = self.client.post(reverse("tennis:club_add_class"),
                                {"club_id": self.club.id, "name": "中級",
                                 "admin_token": self.club.admin_token})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_add_member_succeeds(self):
        resp = self.client.post(reverse("tennis:club_add_member"),
                                {"club_id": self.club.id, "display_name": "新メンバー",
                                 "admin_token": self.club.admin_token})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
