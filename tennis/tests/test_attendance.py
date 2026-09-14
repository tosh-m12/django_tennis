"""
出欠登録（tennis.views.update_attendance）の特性テスト。

現状の挙動を固定する：
  - attendance="yes" にすると（直前が yes 以外なら）participates_match が True になる
  - "yes" 以外にすると participates_match は強制 False
  - 不正な attendance 値は 400
  - 公開済み対戦表があると一般ユーザーは変更不可（403 published_locked）、幹事は可
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tennis.models import EventParticipant

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_published_schedule,
    set_admin_session,
    set_member_session,
)


class UpdateAttendanceTests(TestCase):
    def setUp(self):
        self.club = make_club()
        # 「終了イベント」ガードを避けるため未来日（実行日に依存しない）
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future)
        self.member = make_member(self.club, "テスト太郎")
        self.ep = make_ep(self.event, member=self.member, attendance=None)
        self.url = reverse("tennis:update_attendance")
        set_member_session(self.client, self.club.id)

    def _post(self, **extra):
        data = {"event_id": self.event.id, "ep_id": self.ep.id}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_yes_sets_participates_match_true(self):
        resp = self._post(attendance="yes")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["attendance"], "yes")
        self.assertTrue(body["participates_match"])

        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "yes")
        self.assertTrue(self.ep.participates_match)

    def test_no_forces_participates_match_false(self):
        # まず yes → 試合参加 True にしておく
        self.ep.attendance = "yes"
        self.ep.participates_match = True
        self.ep.save()

        resp = self._post(attendance="no")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["participates_match"])

        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "no")
        self.assertFalse(self.ep.participates_match)

    def test_reselect_yes_preserves_manual_match_off(self):
        # 出席のまま再度yesを選んでも、幹事が手動で外した試合参加(False)は維持される。
        # フロントはこの応答値(participates_match)で表示を同期するため、ここが正の挙動。
        self.ep.attendance = "yes"
        self.ep.participates_match = False  # 幹事が手動で「不参加」にした想定
        self.ep.save()

        resp = self._post(attendance="yes")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["participates_match"])

        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "yes")
        self.assertFalse(self.ep.participates_match)

    def test_reattend_after_absence_recouples_to_join(self):
        # 欠席→再出席は「最初と同様に参加」へ連動する
        self.ep.attendance = "no"
        self.ep.participates_match = False
        self.ep.save()

        resp = self._post(attendance="yes")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["participates_match"])
        self.ep.refresh_from_db()
        self.assertTrue(self.ep.participates_match)

    def test_bad_attendance_returns_400(self):
        resp = self._post(attendance="invalid")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_attendance")

    def test_target_by_member_id_creates_ep(self):
        member2 = make_member(self.club, "未登録花子")
        resp = self.client.post(
            self.url,
            {"event_id": self.event.id, "member_id": member2.id, "attendance": "yes"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            EventParticipant.objects.filter(event=self.event, member=member2).exists()
        )

    def test_published_blocks_non_admin(self):
        make_published_schedule(self.event, [], game_type="doubles")
        resp = self._post(attendance="no")
        self.assertEqual(resp.status_code, 403)
        # _json_forbidden は code を "error" キーに格納する（現状仕様）
        self.assertEqual(resp.json().get("error"), "published_locked")

    def test_published_allows_admin(self):
        make_published_schedule(self.event, [], game_type="doubles")
        set_admin_session(self.client, self.event.id)
        resp = self._post(attendance="no")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
