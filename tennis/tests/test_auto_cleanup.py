"""
未使用メンバーの自動整理（_run_member_auto_cleanup）のテスト。
仕様：
  - 永続セーフ：EPのうち1つでも attendance="yes" のものがあるメンバーは削除されない
  - 削除条件：上記以外の非固定メンバー で、最後の操作から DELETION_DAYS(21) 以上経過
  - 警告条件：上記以外の非固定メンバー で、最後の操作から INACTIVITY_DAYS(14)〜
              DELETION_DAYS-1(20) の間
  - 「最後の操作」= max(Member.updated_at, EP.updated_at, ParticipantFlag.updated_at)
  - 欠席/未定/フラグ操作/コメント編集 などはすべて延長要因
  - 削除時に AuditLog に1件記録
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import AuditLog, EventParticipant, Member, ParticipantFlag
from tennis.views import _run_member_auto_cleanup, DELETION_DAYS, INACTIVITY_DAYS

from .factories import (
    make_club,
    make_club_flag,
    make_ep,
    make_event,
    make_member,
    make_participant_flag,
)


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


def _backdate_member(member, days_ago: int) -> Member:
    """Member の created_at と updated_at を共に過去にする（操作タイミングを古くする）。"""
    target = timezone.now() - dt.timedelta(days=days_ago)
    Member.objects.filter(id=member.id).update(created_at=target, updated_at=target)
    member.refresh_from_db()
    return member


def _backdate_ep(ep, days_ago: int):
    """EventParticipant の updated_at を過去にする。"""
    target = timezone.now() - dt.timedelta(days=days_ago)
    EventParticipant.objects.filter(id=ep.id).update(updated_at=target, created_at=target)
    ep.refresh_from_db()
    return ep


def _backdate_pf(pf, days_ago: int):
    target = timezone.now() - dt.timedelta(days=days_ago)
    ParticipantFlag.objects.filter(id=pf.id).update(updated_at=target)
    pf.refresh_from_db()
    return pf


class AutoCleanupRulesTests(TestCase):
    """ヘルパ関数 _run_member_auto_cleanup の挙動を直接テスト。"""

    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=timezone.localdate())

    # --- 基本：EPゼロの場合 ---

    def test_non_fixed_no_ep_after_21_days_is_deleted(self):
        m = make_member(self.club, "削除対象", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 1)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertFalse(Member.objects.filter(id=m.id).exists())

    def test_no_ep_warning_between_14_and_20_days(self):
        m = make_member(self.club, "警告対象", member_no=1, is_fixed=False)
        _backdate_member(m, INACTIVITY_DAYS)  # 14日前 → あと7日
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["display_name"], "警告対象")
        self.assertEqual(warnings[0]["days_left"], DELETION_DAYS - INACTIVITY_DAYS)

    def test_no_ep_no_warning_under_14_days(self):
        m = make_member(self.club, "新規", member_no=1, is_fixed=False)
        _backdate_member(m, INACTIVITY_DAYS - 1)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_fixed_member_never_deleted(self):
        m = make_member(self.club, "固定さん", member_no=1, is_fixed=True)
        _backdate_member(m, DELETION_DAYS + 5)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    # --- 永続セーフ：yes 出欠があれば削除されない ---

    def test_yes_attendance_protects_forever(self):
        m = make_member(self.club, "yes有り", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 10)
        ep = make_ep(self.event, member=m, attendance="yes")
        _backdate_ep(ep, DELETION_DAYS + 10)  # EPも古い
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_mix_yes_and_no_protected(self):
        m = make_member(self.club, "yesも有り", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        ev2 = make_event(self.club, date=timezone.localdate() - dt.timedelta(days=2))
        ep1 = make_ep(self.event, member=m, attendance="no")
        ep2 = make_ep(ev2, member=m, attendance="yes")
        _backdate_ep(ep1, DELETION_DAYS + 5)
        _backdate_ep(ep2, DELETION_DAYS + 5)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    # --- 欠席/未定のみ：時間経過で削除 ---

    def test_only_no_attendance_after_21_days_is_deleted(self):
        m = make_member(self.club, "欠席のみ", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        ep = make_ep(self.event, member=m, attendance="no")
        _backdate_ep(ep, DELETION_DAYS + 1)  # EPも21日以上前
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertFalse(Member.objects.filter(id=m.id).exists())

    def test_only_maybe_attendance_after_21_days_is_deleted(self):
        m = make_member(self.club, "未定のみ", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        ep = make_ep(self.event, member=m, attendance="maybe")
        _backdate_ep(ep, DELETION_DAYS + 1)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertFalse(Member.objects.filter(id=m.id).exists())

    # --- 延長：欠席を最近入力 → カウントダウン進まず保護 ---

    def test_recent_no_attendance_extends_grace(self):
        m = make_member(self.club, "最近欠席を入力", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)  # Memberは古い
        # でも欠席を今日入力 → EP.updated_at = 今
        make_ep(self.event, member=m, attendance="no")
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_no_attendance_15_days_ago_triggers_warning(self):
        m = make_member(self.club, "15日前に欠席", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        ep = make_ep(self.event, member=m, attendance="no")
        _backdate_ep(ep, 15)  # 15日前 → あと6日で削除
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["display_name"], "15日前に欠席")
        self.assertEqual(warnings[0]["days_left"], DELETION_DAYS - 15)
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    # --- フラグ操作も延長要因 ---

    def test_recent_flag_set_extends_grace(self):
        m = make_member(self.club, "最近フラグ", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 5)
        ep = make_ep(self.event, member=m, attendance="no")
        _backdate_ep(ep, DELETION_DAYS + 1)  # EPは古い
        # でもフラグを今日付ける → PF.updated_at = 今
        flag = make_club_flag(self.club, "車", 1, input_mode="check")
        make_participant_flag(ep, club_flag=flag, is_on=True)
        warnings = _run_member_auto_cleanup(self.club)
        self.assertEqual(warnings, [])
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    # --- AuditLog ---

    def test_auditlog_recorded_on_delete(self):
        m = make_member(self.club, "削除＋ログ", member_no=1, is_fixed=False)
        _backdate_member(m, DELETION_DAYS + 1)
        _run_member_auto_cleanup(self.club)
        logs = list(AuditLog.objects.filter(action="auto_cleanup_member", club=self.club))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].payload_json["display_name"], "削除＋ログ")
        self.assertEqual(logs[0].payload_json["member_id"], m.id)

    # --- 他クラブ非干渉 ---

    def test_other_club_unaffected(self):
        other = make_club(name="別クラブ")
        m_other = make_member(other, "他クラブ古参", member_no=1, is_fixed=False)
        _backdate_member(m_other, DELETION_DAYS + 10)
        _run_member_auto_cleanup(self.club)
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
        url = reverse("tennis:club_home", args=[self.club.public_token])
        ctx = self.client.get(url).context
        self.assertEqual(ctx.get("cleanup_warnings"), [])
