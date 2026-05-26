"""
イベントページ（tennis.views.event_view）の特性テスト。

候補2（ParticipantFlag の共通/固有 2クエリ→1クエリ統合）の前提となる
安全網。リファクタで変えてはいけない context 出力を固定する：

  - flag_states_on / flag_states_val      … クラブ共通フラグ {ep_id: {flag_def_id: ...}}
  - event_flag_states_on / event_flag_states_val … イベント固有フラグ
  - fixed_rows / guest_rows               … 参加者テーブル行
  - display_settings_source               … "db" / "default"
  - is_admin                              … URL による幹事判定
"""
from __future__ import annotations

import datetime

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tennis.models import EventDisplaySetting

# テンプレが {% static %} を使い、本番設定の WhiteNoise manifest ストレージは
# collectstatic 済みを要求する。テストでは通常ストレージに差し替える（本番設定は不変）。
_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
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


@_NO_MANIFEST_STORAGES
class EventViewContextTests(TestCase):
    def setUp(self):
        self.club = make_club()
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future, title="練習A")

        self.m_a = make_member(self.club, "Aさん", member_no=1)
        self.m_b = make_member(self.club, "Bさん", member_no=2)
        self.ep_a = make_ep(self.event, member=self.m_a, attendance="yes")
        self.ep_b = make_ep(self.event, member=self.m_b, attendance="no")
        self.guest = make_ep(self.event, display_name="ゲスト太郎", attendance="yes")

        # クラブ共通フラグ：F1=check, F2=digit
        self.f1 = make_club_flag(self.club, "車出せる", 1, input_mode="check")
        self.f2 = make_club_flag(self.club, "ボール数", 2, input_mode="digit")
        # イベント固有フラグ：EF1=check
        self.ef1 = make_event_flag(self.event, "懇親会", 1, input_mode="check")

        # A: F1 ON / F2 値=3、 B: EF1 ON
        make_participant_flag(self.ep_a, club_flag=self.f1, is_on=True)
        make_participant_flag(self.ep_a, club_flag=self.f2, is_on=False, value=3)
        make_participant_flag(self.ep_b, event_flag=self.ef1, is_on=True)

    def _get_public(self):
        url = reverse("tennis:event_public", args=[self.club.public_token, self.event.id])
        return self.client.get(url)

    def _get_admin(self):
        url = reverse(
            "tennis:event_admin",
            args=[self.club.public_token, self.club.admin_token, self.event.id],
        )
        return self.client.get(url)

    # ---- クラブ共通フラグ ----
    def test_club_flag_states(self):
        ctx = self._get_public().context
        on = ctx["flag_states_on"]
        val = ctx["flag_states_val"]

        self.assertEqual(on[self.ep_a.id][self.f1.id], True)
        self.assertEqual(on[self.ep_a.id][self.f2.id], False)
        self.assertEqual(val[self.ep_a.id][self.f2.id], 3)
        # B はクラブフラグ未設定 → キー無し
        self.assertNotIn(self.ep_b.id, on)

    # ---- イベント固有フラグ ----
    def test_event_flag_states(self):
        ctx = self._get_public().context
        eon = ctx["event_flag_states_on"]
        self.assertEqual(eon[self.ep_b.id][self.ef1.id], True)
        # A はイベントフラグ未設定
        self.assertNotIn(self.ep_a.id, eon)

    def test_participant_flags_loaded_in_single_query(self):
        # 候補2: 共通/固有フラグを1クエリに統合した効果を固定
        url = reverse("tennis:event_public", args=[self.club.public_token, self.event.id])
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        pf_selects = [
            q for q in ctx.captured_queries
            if "tennis_participantflag" in q["sql"].lower() and q["sql"].lstrip().lower().startswith("select")
        ]
        self.assertEqual(len(pf_selects), 1)

    def test_flag_definitions_in_context(self):
        ctx = self._get_public().context
        self.assertEqual([f.id for f in ctx["flags"]], [self.f1.id, self.f2.id])
        self.assertEqual([f.id for f in ctx["event_flags"]], [self.ef1.id])

    # ---- 参加者行 ----
    def test_withdrawn_flag_for_deleted_member(self):
        # 退会（メンバー削除）したEPは guest_rows に withdrawn=True で出る
        m = make_member(self.club, "退会者", member_no=9, is_fixed=False)
        ep = make_ep(self.event, member=m, attendance="yes")
        m.delete()  # pre_delete シグナルで member_deleted=True、member_id=None

        ctx = self._get_public().context
        rows = {r["ep_id"]: r for r in ctx["guest_rows"]}
        self.assertIn(ep.id, rows)
        self.assertTrue(rows[ep.id]["withdrawn"])
        # 通常ゲスト（未削除）は withdrawn=False
        self.assertFalse(rows[self.guest.id]["withdrawn"])

    def test_past_event_grays_all_guests(self):
        # 過去イベント（開催日が今日より前）ではゲスト行を全てグレーアウト
        past = make_event(self.club, date=timezone.localdate() - datetime.timedelta(days=1))
        g = make_ep(past, display_name="一見さん", attendance="yes")
        url = reverse("tennis:event_public", args=[self.club.public_token, past.id])
        ctx = self.client.get(url).context

        grows = {r["ep_id"]: r for r in ctx["guest_rows"]}
        self.assertTrue(grows[g.id]["withdrawn"])  # 過去イベントのゲストはグレー
        # 固定メンバー（現役）はグレーにしない
        self.assertTrue(all(not r["withdrawn"] for r in ctx["fixed_rows"]))

    def test_future_event_guest_not_grayed(self):
        # 未来イベントの通常ゲストはグレーにしない（setUp の event は未来日）
        ctx = self._get_public().context
        grows = {r["ep_id"]: r for r in ctx["guest_rows"]}
        self.assertFalse(grows[self.guest.id]["withdrawn"])

    def test_fixed_and_guest_rows(self):
        ctx = self._get_public().context
        fixed = {r["member_id"]: r for r in ctx["fixed_rows"]}
        self.assertEqual(fixed[self.m_a.id]["attendance"], "yes")
        self.assertEqual(fixed[self.m_a.id]["ep_id"], self.ep_a.id)
        self.assertEqual(fixed[self.m_b.id]["attendance"], "no")

        guests = ctx["guest_rows"]
        self.assertEqual(len(guests), 1)
        self.assertEqual(guests[0]["display_name"], "ゲスト太郎")

    def test_unregistered_fixed_member_has_null_ep(self):
        # EP を持たない固定メンバー → ep_id None・attendance None
        m_c = make_member(self.club, "Cさん", member_no=3)
        ctx = self._get_public().context
        row = next(r for r in ctx["fixed_rows"] if r["member_id"] == m_c.id)
        self.assertIsNone(row["ep_id"])
        self.assertIsNone(row["attendance"])

    # ---- 表示設定 ----
    def test_display_settings_default(self):
        ctx = self._get_public().context
        self.assertEqual(ctx["display_settings_source"], "default")

    def test_display_settings_db(self):
        EventDisplaySetting.objects.create(
            event=self.event, show_flags=False, show_event_flags=True
        )
        ctx = self._get_public().context
        self.assertEqual(ctx["display_settings_source"], "db")

    # ---- admin 判定 ----
    def test_is_admin_false_on_public_url(self):
        self.assertFalse(self._get_public().context["is_admin"])

    def test_is_admin_true_on_admin_url(self):
        self.assertTrue(self._get_admin().context["is_admin"])

    def test_admin_token_mismatch_is_bad_request(self):
        url = reverse(
            "tennis:event_admin",
            args=[self.club.public_token, "wrongtoken", self.event.id],
        )
        self.assertEqual(self.client.get(url).status_code, 400)


@_NO_MANIFEST_STORAGES
class EventViewNoFlagsTests(TestCase):
    """フラグ未定義イベントでも空 dict を返すことを固定。"""

    def setUp(self):
        self.club = make_club()
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future)
        m = make_member(self.club, "Aさん", member_no=1)
        make_ep(self.event, member=m, attendance="yes")

    def test_empty_flag_states(self):
        url = reverse("tennis:event_public", args=[self.club.public_token, self.event.id])
        ctx = self.client.get(url).context
        self.assertEqual(dict(ctx["flag_states_on"]), {})
        self.assertEqual(dict(ctx["flag_states_val"]), {})
        self.assertEqual(dict(ctx["event_flag_states_on"]), {})
        self.assertEqual(dict(ctx["event_flag_states_val"]), {})
