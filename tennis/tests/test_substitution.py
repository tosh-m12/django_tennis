"""
代打（tennis.views.substitute_slot）の特性テスト。

現状の挙動を固定する：
  - 公開済み対戦表のスロットを差し替えると、元の人は rests に移り、新しい人が試合枠へ
  - 差し替えた試合(round,court)のスコアは削除される
  - published は True のまま維持
  - draft（未公開 MatchSchedule）があると 409 draft_exists
  - 出欠が yes でない人は代打にできない（409 not_attendance_yes）
  - 必須パラメータ欠落は 400
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse

from tennis.models import MatchSchedule, MatchScore

from .factories import (
    make_club,
    make_event,
    make_ep,
    make_published_schedule,
    make_score,
    set_member_session,
)


class SubstituteSlotTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 20))

        # ダブルス想定：team1=[ep1,ep2], team2=[ep3,ep4], rests=[ep5]
        self.ep1 = make_ep(self.event, display_name="P1", attendance="yes", participates_match=True)
        self.ep2 = make_ep(self.event, display_name="P2", attendance="yes", participates_match=True)
        self.ep3 = make_ep(self.event, display_name="P3", attendance="yes", participates_match=True)
        self.ep4 = make_ep(self.event, display_name="P4", attendance="yes", participates_match=True)
        self.ep5 = make_ep(self.event, display_name="P5(控え)", attendance="yes", participates_match=True)

        schedule = [{
            "round": 1,
            "matches": [{
                "court": 1,
                "team1": [self.ep1.id, self.ep2.id],
                "team2": [self.ep3.id, self.ep4.id],
                "score1": None, "score2": None,
            }],
            "rests": [self.ep5.id],
        }]
        self.ms = make_published_schedule(
            self.event, schedule, game_type="doubles", court_count=1, round_count=1
        )
        make_score(self.ms, 1, 1, 6, 3)  # この試合にスコアあり

        self.url = reverse("tennis:substitute_slot")
        set_member_session(self.client, self.club.id)

    def _post(self, **extra):
        data = {
            "event_id": self.event.id,
            "round_no": 1,
            "court_no": 1,
            "team": 1,
            "slot_index": 0,
            "new_ep_id": self.ep5.id,
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_substitute_moves_rest_player_in_and_clears_score(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["publish_state"], "published")

        self.ms.refresh_from_db()
        rnd = self.ms.schedule_json[0]
        team1 = rnd["matches"][0]["team1"]
        # 控え ep5 が team1[0] に入り、元の ep1 は rests へ
        self.assertEqual(team1[0], self.ep5.id)
        self.assertEqual(team1[1], self.ep2.id)
        self.assertIn(self.ep1.id, rnd["rests"])
        self.assertNotIn(self.ep5.id, rnd["rests"])

        # 公開状態は維持
        self.assertTrue(self.ms.published)
        # 該当試合のスコアは削除
        self.assertFalse(
            MatchScore.objects.filter(match_schedule=self.ms, round_no=1, court_no=1).exists()
        )

    def test_substitute_with_non_yes_attendance_rejected(self):
        self.ep5.attendance = "no"
        self.ep5.save(update_fields=["attendance"])
        resp = self._post()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "not_attendance_yes")

    def test_draft_exists_blocks_substitution(self):
        # 未公開スケジュールは OneToOne のため一旦公開を未公開に変える
        self.ms.published = False
        self.ms.save(update_fields=["published"])
        resp = self._post()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "draft_exists")

    def test_missing_params_returns_400(self):
        resp = self.client.post(self.url, {"event_id": self.event.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_request")

    def test_swap_when_new_ep_already_in_another_match(self):
        # new_ep が別コートの試合に居る場合は「入替」になる。
        # 2コート構成を別途用意する。
        ep6 = make_ep(self.event, display_name="P6", attendance="yes", participates_match=True)
        ep7 = make_ep(self.event, display_name="P7", attendance="yes", participates_match=True)
        ep8 = make_ep(self.event, display_name="P8", attendance="yes", participates_match=True)

        schedule = [{
            "round": 1,
            "matches": [
                {"court": 1, "team1": [self.ep1.id, self.ep2.id], "team2": [self.ep3.id, self.ep4.id]},
                {"court": 2, "team1": [self.ep5.id, ep6.id], "team2": [ep7.id, ep8.id]},
            ],
            "rests": [],
        }]
        # 既存の公開対戦表を作り直す
        self.ms.schedule_json = schedule
        self.ms.court_count = 2
        self.ms.save(update_fields=["schedule_json", "court_count"])
        make_score(self.ms, 1, 2, 4, 1)  # コート2にもスコア

        # コート1 team1 slot0(=ep1) に、コート2に居る ep5 を投入
        resp = self._post(court_no=1, team=1, slot_index=0, new_ep_id=self.ep5.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        self.ms.refresh_from_db()
        matches = self.ms.schedule_json[0]["matches"]
        # ep5 が コート1 team1[0] に入り、押し出された ep1 は ep5 が居た位置（コート2 team1[0]）へ
        self.assertEqual(matches[0]["team1"][0], self.ep5.id)
        self.assertEqual(matches[1]["team1"][0], self.ep1.id)
        # rests は変化なし（ep5 は元々 rests に居ない）
        self.assertEqual(self.ms.schedule_json[0]["rests"], [])

        # スコアは対象コート(1)のみ削除、相手コート(2)は残る（現状挙動）
        self.assertFalse(
            MatchScore.objects.filter(match_schedule=self.ms, round_no=1, court_no=1).exists()
        )
        self.assertTrue(
            MatchScore.objects.filter(match_schedule=self.ms, round_no=1, court_no=2).exists()
        )

    def test_substitute_player_not_in_round_appends_old_to_rests(self):
        # new_ep がそのラウンドのどこにも居ない場合：押し出された old_ep が rests に追加される
        ep9 = make_ep(self.event, display_name="P9(未スケジュール)", attendance="yes", participates_match=True)
        resp = self._post(new_ep_id=ep9.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        self.ms.refresh_from_db()
        rnd = self.ms.schedule_json[0]
        self.assertEqual(rnd["matches"][0]["team1"][0], ep9.id)
        # 元の ep1 が rests に追加され、元から居た ep5 も残る
        self.assertIn(self.ep1.id, rnd["rests"])
        self.assertIn(self.ep5.id, rnd["rests"])

    def test_same_player_is_noop(self):
        # 既に team1[0] に居る ep1 を指定 → 変化なし・published 維持
        resp = self._post(new_ep_id=self.ep1.id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.ms.refresh_from_db()
        self.assertEqual(self.ms.schedule_json[0]["matches"][0]["team1"][0], self.ep1.id)
        # スコアは消えない（no-op）
        self.assertTrue(
            MatchScore.objects.filter(match_schedule=self.ms, round_no=1, court_no=1).exists()
        )
