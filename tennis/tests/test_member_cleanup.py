"""
メンバー整理（統合・完全削除）のテスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis import data_cleanup
from tennis.models import Member, EventParticipant, ParticipantFlag, MatchSchedule

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_club_flag,
    make_participant_flag,
    make_published_schedule,
)

_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class MemberMergeTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.e1 = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.e2 = make_event(self.club, date=datetime.date(2026, 5, 8))
        self.A = make_member(self.club, "山田", member_no=1)   # 統合先
        self.B = make_member(self.club, "やまだ", member_no=2)  # 統合元（重複）
        self.flag_car = make_club_flag(self.club, "車", 1)
        self.flag_rain = make_club_flag(self.club, "雨", 2)

        # e1: A も B も参加（競合）。A=不参加+車, B=参加+雨
        self.A_e1 = make_ep(self.e1, member=self.A, attendance="no")
        make_participant_flag(self.A_e1, club_flag=self.flag_car, is_on=True)
        self.B_e1 = make_ep(self.e1, member=self.B, attendance="yes")
        make_participant_flag(self.B_e1, club_flag=self.flag_rain, is_on=True)

        # e2: B のみ参加（移動するだけ）
        self.B_e2 = make_ep(self.e2, member=self.B, attendance="maybe")

        # e1 の対戦表が B_e1 を参照（C は別ゲスト）
        self.C = make_ep(self.e1, display_name="ゲストC", attendance="yes")
        self.ms = make_published_schedule(
            self.e1,
            [{"round": 1, "matches": [{"court": 1, "team1": [self.B_e1.id], "team2": [self.C.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )

    def test_preview_counts(self):
        r = data_cleanup.preview_merge(self.club, [f"m:{self.B.id}"], f"m:{self.A.id}")
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["moves"], 1)       # e2
        self.assertEqual(r["conflicts"], 1)   # e1
        self.assertEqual(r["conflict_details"][0]["result_att"], "yes")

    def test_apply_merge(self):
        data_cleanup.apply_merge(self.club, [f"m:{self.B.id}"], f"m:{self.A.id}")

        # B は削除
        self.assertFalse(Member.objects.filter(id=self.B.id).exists())
        # A は e1, e2 に EP を持つ
        a_eps = {ep.event_id: ep for ep in EventParticipant.objects.filter(member=self.A)}
        self.assertIn(self.e1.id, a_eps)
        self.assertIn(self.e2.id, a_eps)
        # e1 競合：出欠は yes、フラグは車+雨 の和集合
        a_e1 = a_eps[self.e1.id]
        self.assertEqual(a_e1.attendance, "yes")
        flag_ids = set(ParticipantFlag.objects.filter(event_participant=a_e1)
                       .values_list("club_flag_definition_id", flat=True))
        self.assertEqual(flag_ids, {self.flag_car.id, self.flag_rain.id})
        # e2 は移動（attendance maybe 維持）
        self.assertEqual(a_eps[self.e2.id].attendance, "maybe")
        # B_e1 は削除済み
        self.assertFalse(EventParticipant.objects.filter(id=self.B_e1.id).exists())
        # 対戦表は B_e1 → A_e1 に付け替わっている
        ms = MatchSchedule.objects.get(id=self.ms.id)
        team1 = ms.schedule_json[0]["matches"][0]["team1"]
        self.assertIn(a_e1.id, team1)
        self.assertNotIn(self.B_e1.id, team1)

    def test_guest_merged_into_member(self):
        # ゲストC を A に統合（e1 で A も参加しているので競合）
        data_cleanup.apply_merge(self.club, [f"g:ゲストC"], f"m:{self.A.id}")
        # ゲストC の EP は A 側へ集約され、C 単体EPは消える
        self.assertFalse(
            EventParticipant.objects.filter(id=self.C.id).exists()
        )
        ms = MatchSchedule.objects.get(id=self.ms.id)
        team2 = ms.schedule_json[0]["matches"][0]["team2"]
        a_e1 = EventParticipant.objects.get(member=self.A, event=self.e1)
        self.assertIn(a_e1.id, team2)


@_NO_MANIFEST_STORAGES
class MemberDeleteTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.e1 = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.M = make_member(self.club, "消える人", member_no=1)
        self.ep = make_ep(self.e1, member=self.M, attendance="yes")
        self.flag = make_club_flag(self.club, "車", 1)
        make_participant_flag(self.ep, club_flag=self.flag, is_on=True)
        self.other = make_ep(self.e1, display_name="相手", attendance="yes")
        self.ms = make_published_schedule(
            self.e1,
            [{"round": 1, "matches": [{"court": 1, "team1": [self.ep.id], "team2": [self.other.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )

    def test_preview_warns_history(self):
        r = data_cleanup.preview_delete(self.club, self.M.id)
        self.assertEqual(r["ep_count"], 1)
        self.assertEqual(r["flag_count"], 1)
        self.assertTrue(r["has_history"])
        self.assertTrue(any("対戦表" in w for w in r["warnings"]))

    def test_apply_delete_removes_everything(self):
        data_cleanup.apply_delete(self.club, self.M.id)
        self.assertFalse(Member.objects.filter(id=self.M.id).exists())
        self.assertFalse(EventParticipant.objects.filter(id=self.ep.id).exists())
        self.assertFalse(ParticipantFlag.objects.filter(event_participant_id=self.ep.id).exists())
        # 対戦表から ep_id が除去されている
        ms = MatchSchedule.objects.get(id=self.ms.id)
        team1 = ms.schedule_json[0]["matches"][0]["team1"]
        self.assertNotIn(self.ep.id, team1)


@_NO_MANIFEST_STORAGES
class MemberCleanupViewTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.e1 = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.A = make_member(self.club, "本体", member_no=1)
        self.B = make_member(self.club, "重複", member_no=2)
        make_ep(self.e1, member=self.B, attendance="yes")

    def _url(self, name):
        return reverse(name, args=[self.club.public_token, self.club.admin_token])

    def test_page_renders_with_counts(self):
        resp = self.client.get(self._url("tennis:club_member_cleanup"))
        self.assertEqual(resp.status_code, 200)
        names = [r["display_name"] for r in resp.context["rows"]]
        self.assertIn("本体", names)
        self.assertIn("重複", names)

    def test_merge_preview_then_apply(self):
        # プレビュー
        resp = self.client.post(self._url("tennis:club_member_merge_preview"), {
            "target_key": f"m:{self.A.id}", "source_keys": [f"m:{self.B.id}"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["result"]["moves"], 1)
        # 適用
        resp2 = self.client.post(self._url("tennis:club_member_merge_apply"), {})
        self.assertEqual(resp2.status_code, 302)
        self.assertFalse(Member.objects.filter(id=self.B.id).exists())
        self.assertTrue(EventParticipant.objects.filter(member=self.A, event=self.e1).exists())

    def test_admin_token_required(self):
        url = reverse("tennis:club_member_cleanup", args=[self.club.public_token, "wrong"])
        self.assertEqual(self.client.get(url).status_code, 400)
