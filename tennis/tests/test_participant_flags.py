"""
フラグ値保存（tennis.views.set_participant_flag_value）のテスト。

候補#1 の修正を担保：
  - 共通フラグ(club, digit) は従来どおり保存できる
  - イベント固有フラグ(event, digit) も flag_scope=event で正しく保存できる（修正前は不可）
  - scope ごとに ParticipantFlag の FK が正しく分かれる
  - クリア("")・不正値・scope不一致の扱い
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tennis.models import ParticipantFlag

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_club_flag,
    make_event_flag,
)


class SetFlagValueTests(TestCase):
    def setUp(self):
        self.club = make_club()
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future)
        self.member = make_member(self.club, "Aさん", member_no=1)
        self.ep = make_ep(self.event, member=self.member, attendance="yes")
        self.url = reverse("tennis:set_participant_flag_value")

    def _post(self, **extra):
        data = {"event_id": self.event.id, "ep_id": self.ep.id}
        data.update(extra)
        return self.client.post(self.url, data)

    # ---- 共通フラグ(club) digit：従来挙動の維持 ----
    def test_club_digit_value_saved(self):
        flag = make_club_flag(self.club, "球数", 1, input_mode="digit")
        resp = self._post(flag_id=flag.id, value="5", flag_scope="club")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        pf = ParticipantFlag.objects.get(event_participant=self.ep, club_flag_definition=flag)
        self.assertEqual(pf.value, 5)
        self.assertTrue(pf.is_on)
        self.assertIsNone(pf.event_flag_definition_id)

    def test_club_default_scope_when_omitted(self):
        # flag_scope 未指定なら club 扱い（後方互換）
        flag = make_club_flag(self.club, "球数", 1, input_mode="digit")
        resp = self._post(flag_id=flag.id, value="2")
        self.assertEqual(resp.status_code, 200)
        pf = ParticipantFlag.objects.get(event_participant=self.ep, club_flag_definition=flag)
        self.assertEqual(pf.value, 2)

    # ---- ★固有フラグ(event) digit：修正の核心 ----
    def test_event_digit_value_saved(self):
        ef = make_event_flag(self.event, "差し入れ数", 1, input_mode="digit")
        resp = self._post(flag_id=ef.id, value="3", flag_scope="event")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["flag_scope"], "event")
        pf = ParticipantFlag.objects.get(event_participant=self.ep, event_flag_definition=ef)
        self.assertEqual(pf.value, 3)
        self.assertTrue(pf.is_on)
        self.assertIsNone(pf.club_flag_definition_id)

    def test_event_digit_does_not_create_club_flag(self):
        # 固有フラグ保存が共通フラグ側に誤って書き込まないこと（修正前の誤動作の回帰防止）
        ef = make_event_flag(self.event, "EF", 1, input_mode="digit")
        self._post(flag_id=ef.id, value="7", flag_scope="event")
        self.assertFalse(
            ParticipantFlag.objects.filter(
                event_participant=self.ep, club_flag_definition__isnull=False
            ).exists()
        )

    # ---- クリア / 不正値 ----
    def test_clear_value(self):
        flag = make_club_flag(self.club, "球数", 1, input_mode="digit")
        self._post(flag_id=flag.id, value="5", flag_scope="club")
        resp = self._post(flag_id=flag.id, value="", flag_scope="club")
        self.assertEqual(resp.status_code, 200)
        pf = ParticipantFlag.objects.get(event_participant=self.ep, club_flag_definition=flag)
        self.assertIsNone(pf.value)
        self.assertFalse(pf.is_on)

    def test_bad_value_rejected(self):
        flag = make_club_flag(self.club, "球数", 1, input_mode="digit")
        resp = self._post(flag_id=flag.id, value="12", flag_scope="club")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_value")

    # ---- scope 分離：event scope に club flag の id を渡すと見つからない ----
    def test_event_scope_with_club_flag_id_not_found(self):
        club_flag = make_club_flag(self.club, "C", 1, input_mode="digit")
        resp = self._post(flag_id=club_flag.id, value="1", flag_scope="event")
        self.assertEqual(resp.status_code, 404)
