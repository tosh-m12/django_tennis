"""
club_data ページ（幹事専用のデータ集計表）の特性テスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis.models import (
    ClubFlagDefinition,
    EventFlagDefinition,
    Member,
)

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_club_flag,
    make_event_flag,
    make_participant_flag,
)

_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class ClubDataAuthTests(TestCase):
    def setUp(self):
        self.club = make_club()

    def test_admin_token_mismatch_returns_400(self):
        url = reverse("tennis:club_data", args=[self.club.public_token, "wrong-token"])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 400)

    def test_admin_url_with_correct_token_renders(self):
        url = reverse("tennis:club_data", args=[self.club.public_token, self.club.admin_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attendance_table", resp.context)


@_NO_MANIFEST_STORAGES
class ClubDataPeriodAndRowsTests(TestCase):
    def setUp(self):
        self.club = make_club()
        # 3イベントをそれぞれ別日に
        self.ev_may1 = make_event(self.club, date=datetime.date(2026, 5, 1), title="練習A")
        self.ev_may15 = make_event(self.club, date=datetime.date(2026, 5, 15), title="練習B")
        self.ev_jun1 = make_event(self.club, date=datetime.date(2026, 6, 1), title="練習C")

        # メンバー（固定2／非固定1）
        self.m_fixed1 = make_member(self.club, "固定A", member_no=1, is_fixed=True)
        self.m_fixed2 = make_member(self.club, "固定B", member_no=2, is_fixed=True)
        self.m_guest = make_member(self.club, "ゲスト太郎", member_no=3, is_fixed=False)

        # 5/1: 固定A=yes / 固定B=no / ゲスト=yes
        make_ep(self.ev_may1, member=self.m_fixed1, attendance="yes")
        make_ep(self.ev_may1, member=self.m_fixed2, attendance="no")
        make_ep(self.ev_may1, member=self.m_guest, attendance="yes")
        # 5/15: 固定A=maybe
        make_ep(self.ev_may15, member=self.m_fixed1, attendance="maybe")
        # 6/1: 固定B=yes
        make_ep(self.ev_jun1, member=self.m_fixed2, attendance="yes")

    def _get(self, **params):
        url = reverse("tennis:club_data", args=[self.club.public_token, self.club.admin_token])
        return self.client.get(url, params)

    def test_explicit_period_filters_events(self):
        resp = self._get(start="2026-05-01", end="2026-05-31")
        events = resp.context["events"]
        ev_ids = [e.id for e in events]
        self.assertIn(self.ev_may1.id, ev_ids)
        self.assertIn(self.ev_may15.id, ev_ids)
        self.assertNotIn(self.ev_jun1.id, ev_ids)  # 6/1は範囲外

    def test_all_members_shown_even_without_participation(self):
        # 6月だけを範囲に → 固定Aは6月に参加していないが行に出る
        resp = self._get(start="2026-06-01", end="2026-06-30")
        names = [r["display_name"] for r in resp.context["rows"]]
        self.assertIn("固定A", names)
        self.assertIn("固定B", names)
        self.assertIn("ゲスト太郎", names)

    def test_attendance_cell_values(self):
        resp = self._get(start="2026-05-01", end="2026-05-31")
        att = resp.context["attendance_table"]
        # 固定Aの行を取り出す
        row_a = next(r for r in att if r["row"]["display_name"] == "固定A")
        # 列順: ev_may1, ev_may15
        self.assertEqual(row_a["cells"][0]["attendance"], "yes")
        self.assertEqual(row_a["cells"][1]["attendance"], "maybe")
        # 固定B
        row_b = next(r for r in att if r["row"]["display_name"] == "固定B")
        self.assertEqual(row_b["cells"][0]["attendance"], "no")
        self.assertIsNone(row_b["cells"][1]["attendance"])  # 5/15は不参加


@_NO_MANIFEST_STORAGES
class ClubDataFlagsTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.m = make_member(self.club, "A", member_no=1, is_fixed=True)
        self.ep = make_ep(self.event, member=self.m, attendance="yes")

        # アクティブな共通フラグ
        self.f_active = make_club_flag(self.club, "車", 1, input_mode="check")
        make_participant_flag(self.ep, club_flag=self.f_active, is_on=True)

        # 削除済み共通フラグ（is_active=False）にデータあり
        self.f_inactive = ClubFlagDefinition.objects.create(
            club=self.club, name="旧フラグ", display_order=2,
            input_mode="check", is_active=False,
        )
        make_participant_flag(self.ep, club_flag=self.f_inactive, is_on=True)

        # イベント固有フラグ
        self.ef = make_event_flag(self.event, "懇親会", 1, input_mode="check")
        make_participant_flag(self.ep, event_flag=self.ef, is_on=True)

    def _get(self):
        url = reverse("tennis:club_data", args=[self.club.public_token, self.club.admin_token])
        return self.client.get(url, {"start": "2026-05-01", "end": "2026-05-31"})

    def test_deleted_club_flag_with_data_appears(self):
        ctx = self._get().context
        flag_names = [t["flag"].name for t in ctx["club_flag_tables"]]
        self.assertIn("車", flag_names)
        self.assertIn("旧フラグ", flag_names)
        # is_active が False のフラグは「削除済み・履歴」マーク用に is_active=False
        inactive = next(t for t in ctx["club_flag_tables"] if t["flag"].name == "旧フラグ")
        self.assertFalse(inactive["is_active"])

    def test_event_flag_block_renders(self):
        ctx = self._get().context
        blocks = ctx["event_flag_blocks"]
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block["event"].id, self.event.id)
        self.assertEqual([f.id for f in block["flags"]], [self.ef.id])
        # セル値：A の懇親会 = "✓"
        a_row = next(r for r in block["rows"] if r["row"]["display_name"] == "A")
        self.assertEqual(a_row["cells"][0]["text"], "✓")


@_NO_MANIFEST_STORAGES
class ClubDataWithdrawnTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 1))
        # 退会者のEP（member削除済み想定：member_id=None, member_deleted=True）
        from tennis.models import EventParticipant
        self.ep_withdrawn = EventParticipant.objects.create(
            event=self.event,
            member=None,
            display_name="退会さん",
            attendance="yes",
            member_deleted=True,
        )

    def test_withdrawn_member_appears_with_flag(self):
        url = reverse("tennis:club_data", args=[self.club.public_token, self.club.admin_token])
        ctx = self.client.get(url, {"start": "2026-05-01", "end": "2026-05-31"}).context
        rows = ctx["rows"]
        wrow = next(r for r in rows if r["display_name"] == "退会さん")
        self.assertTrue(wrow["withdrawn"])
        # 出欠も yes として表に出ている
        att_row = next(r for r in ctx["attendance_table"] if r["row"]["display_name"] == "退会さん")
        self.assertEqual(att_row["cells"][0]["attendance"], "yes")
