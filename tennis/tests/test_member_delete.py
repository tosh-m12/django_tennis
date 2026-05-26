"""
メンバー削除（tennis.views.club_delete_member）のテスト。

仕様：
  - 非固定メンバー(is_fixed=False)のみ削除可。固定メンバーは拒否。
  - 削除しても EventParticipant（出欠・戦績）は残る（member は SET_NULL で NULL になる）。
  - 幹事トークン必須。
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tennis.models import EventParticipant, Member

from .factories import make_club, make_event, make_member, make_ep


class ClubDeleteMemberTests(TestCase):
    def setUp(self):
        self.club = make_club()
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future)
        self.url = reverse("tennis:club_delete_member")

    def _post(self, member, *, token=None):
        return self.client.post(self.url, {
            "club_id": self.club.id,
            "member_id": member.id,
            "admin_token": token if token is not None else self.club.admin_token,
        })

    def test_delete_non_fixed_member(self):
        m = make_member(self.club, "ゲスト花子", is_fixed=False, member_no=1)
        resp = self._post(m)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertFalse(Member.objects.filter(id=m.id).exists())

    def test_event_participant_survives_with_null_member(self):
        # 出欠・戦績(EP)は残り、member だけ NULL になる
        m = make_member(self.club, "ゲスト太郎", is_fixed=False, member_no=2)
        ep = make_ep(self.event, member=m, display_name="ゲスト太郎", attendance="yes")

        resp = self._post(m)
        self.assertEqual(resp.status_code, 200)

        ep.refresh_from_db()
        self.assertIsNone(ep.member_id)              # member は外れる
        self.assertEqual(ep.display_name, "ゲスト太郎")  # 表示名(履歴)は残る
        self.assertEqual(ep.attendance, "yes")        # 出欠も残る
        self.assertTrue(EventParticipant.objects.filter(id=ep.id).exists())

    def test_fixed_member_cannot_be_deleted(self):
        m = make_member(self.club, "固定さん", is_fixed=True, member_no=3)
        resp = self._post(m)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "fixed_member")
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_wrong_admin_token_forbidden(self):
        m = make_member(self.club, "ゲスト", is_fixed=False, member_no=4)
        resp = self._post(m, token="wrong")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "forbidden")
        self.assertTrue(Member.objects.filter(id=m.id).exists())

    def test_missing_params(self):
        resp = self.client.post(self.url, {"club_id": self.club.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "missing")
