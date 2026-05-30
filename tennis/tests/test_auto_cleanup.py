"""
未使用メンバーの自動整理（_run_member_auto_cleanup）のテスト。
仕様：
  - 非固定 + EPゼロ + 登録から DELETION_DAYS(21日) 以上 → 削除
  - 非固定 + EPゼロ + 登録から INACTIVITY_DAYS(14日)〜DELETION_DAYS-1(20日) → 警告
  - それ以外は対象外
  - 削除時に AuditLog に1件記録
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import AuditLog, Member
from tennis.views import _run_member_auto_cleanup, DELETION_DAYS, INACTIVITY_DAYS

from .factories import make_club, make_event, make_ep, make_member


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


def _backdate_member(member, days_ago: int) -> Member:
    target = timezone.now() - dt.timedelta(days=days_ago)
    Member.objects.filter(id=member.id).update(created_at=target)
    member.refresh_from_db()
    return member


class AutoCleanupRulesTests(TestCase):
    """ヘルパ関数 _run_member_auto_cleanup の挙動を直接テスト。"""

    def setUp(self):
        self.club = make_club()

    def test_non_fixed_no_ep_after_21_days_is_deleted(self):
        m = make_member(self.club, "削除対象", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 1)  # 22日前

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(warnings, [])
        self.assertFalse(Member.objects.filter(id=m.id).exists())

    def test_warning_between_14_and_20_days(self):
        m = make_member(self.club, "警告対象", member_no=1, is_fixed=False)
        _backdate_member(m, INACTIVITY_DAYS)  # 14日前 → あと7日

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["display_name"], "警告対象")
        self.assertEqual(warnings[0]["days_left"], DELETION_DAYS - INACTIVITY_DAYS)  # 7
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_warning_countdown_last_day(self):
        m = make_member(self.club, "明日削除", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS - 1)  # 20日前 → あと1日

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["days_left"], 1)
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_no_warning_under_14_days(self):
        m = make_member(self.club, "新規", member_no=1, is_fixed=False)
        _backdate_member(m, INACTIVITY_DAYS - 1)  # 13日前 → 警告なし

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_fixed_member_never_deleted(self):
        m = make_member(self.club, "固定さん", member_no=1, is_fixed=True)
        _backdate_member(m, DELETION_DAYS + 5)  # 26日前

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_member_with_ep_is_protected(self):
        ev = make_event(self.club, date=timezone.localdate())
        m = make_member(self.club, "出席履歴あり", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        # EP を作る（attendance なし・コメントなしの空EPでも保護）
        make_ep(ev, member=m)

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_auditlog_recorded_on_delete(self):
        m = make_member(self.club, "削除＋ログ", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 1)

        _run_member_auto_cleanup(self.club)

        logs = list(AuditLog.objects.filter(action="auto_cleanup_member", club=self.club))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].payload_json["display_name"], "削除＋ログ")
        self.assertEqual(logs[0].payload_json["member_id"], m.id)

    def test_other_club_unaffected(self):
        # 別クラブの古い未使用メンバーは対象外
        other = make_club(name="別クラブ")
        m_other = make_member(other, "他クラブ古参", member_no=1, is_fixed=False)
        _backdate_member(m_other, DELETION_DAYS + 10)

        warnings = _run_member_auto_cleanup(self.club)

        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m_other.id).exists())


@_NO_MANIFEST_STORAGES
class AutoCleanupBannerIntegrationTests(TestCase):
    """幹事ページに警告バナーが出ること（context経由）"""

    def setUp(self):
        self.club = make_club()
        self.warn_member = make_member(self.club, "警告太郎", member_no=1, is_fixed=False)
        _backdate_member(self.warn_member, INACTIVITY_DAYS + 2)  # 16日前 → あと5日

    def test_settings_page_carries_warnings(self):
        url = reverse("tennis:club_settings", args=[self.club.public_token, self.club.admin_token])
        ctx = self.client.get(url).context
        warns = ctx.get("cleanup_warnings", [])
        names = [w["display_name"] for w in warns]
        self.assertIn("警告太郎", names)

    def test_club_data_page_carries_warnings(self):
        url = reverse("tennis:club_data", args=[self.club.public_token, self.club.admin_token])
        ctx = self.client.get(url).context
        warns = ctx.get("cleanup_warnings", [])
        names = [w["display_name"] for w in warns]
        self.assertIn("警告太郎", names)

    def test_public_club_home_no_warnings(self):
        # 一般URLでは cleanup_warnings は空（is_admin が False）
        url = reverse("tennis:club_home", args=[self.club.public_token])
        ctx = self.client.get(url).context
        self.assertEqual(ctx.get("cleanup_warnings"), [])
