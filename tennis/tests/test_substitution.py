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
