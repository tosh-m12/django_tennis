"""
_build_player_stats と event_view での stats context の動作確認。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.views import _build_player_stats

from .factories import (
    make_club,
    make_event,
    make_ep,
    make_member,
    make_published_schedule,
    set_admin_session,
)


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


class BuildPlayerStatsTests(TestCase):
    """純粋ロジックのテスト：schedule_json から正しく集計できる。"""

    def test_empty_schedule_returns_empty(self):
        self.assertEqual(_build_player_stats(None, {}), [])
        self.assertEqual(_build_player_stats([], {}), [])

    def test_basic_doubles_3_rounds(self):
        # 4人、3ラウンド、1コート。A,B vs C,D を3R連続
        sched = [
            {"round": 1, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": []},
            {"round": 2, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": []},
            {"round": 3, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": []},
        ]
        names = {1: "A", 2: "B", 3: "C", 4: "D"}
        out = _build_player_stats(sched, names)
        by = {s["name"]: s for s in out}
        # 全員が3試合、休憩0、最大連続試合3、最大連続休憩0
        for name in ("A", "B", "C", "D"):
            self.assertEqual(by[name]["matches"], 3)
            self.assertEqual(by[name]["rests"], 0)
            self.assertEqual(by[name]["max_play_streak"], 3)
            self.assertEqual(by[name]["max_rest_streak"], 0)

    def test_rest_rotation(self):
        # 5人、3ラウンド、1コートで毎ラウンド1人休憩を回す
        sched = [
            {"round": 1, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": [5]},
            {"round": 2, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 5]}], "rests": [4]},
            {"round": 3, "matches": [{"court": 1, "team1": [1, 5], "team2": [3, 4]}], "rests": [2]},
        ]
        names = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
        out = _build_player_stats(sched, names)
        by = {s["name"]: s for s in out}
        # A,C は全試合参加
        self.assertEqual(by["A"]["matches"], 3)
        self.assertEqual(by["A"]["rests"], 0)
        # B: 2試合 / 1休憩 (R3休憩)
        self.assertEqual(by["B"]["matches"], 2)
        self.assertEqual(by["B"]["rests"], 1)
        # D: 2試合 / 1休憩 (R2休憩)
        self.assertEqual(by["D"]["matches"], 2)
        self.assertEqual(by["D"]["rests"], 1)
        # E: 2試合 / 1休憩 (R1休憩)
        self.assertEqual(by["E"]["matches"], 2)
        self.assertEqual(by["E"]["rests"], 1)

    def test_max_rest_streak(self):
        # 1人が2連続休憩
        sched = [
            {"round": 1, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": [5]},
            {"round": 2, "matches": [{"court": 1, "team1": [1, 2], "team2": [3, 4]}], "rests": [5]},
            {"round": 3, "matches": [{"court": 1, "team1": [1, 5], "team2": [3, 4]}], "rests": [2]},
        ]
        names = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
        out = _build_player_stats(sched, names)
        by = {s["name"]: s for s in out}
        self.assertEqual(by["E"]["max_rest_streak"], 2)
        self.assertEqual(by["E"]["matches"], 1)
        self.assertEqual(by["E"]["rests"], 2)


@_NO_MANIFEST_STORAGES
class EventViewStatsContextTests(TestCase):
    """event_view 経由で stats が幹事モード時にのみ contextに渡る。"""

    def setUp(self):
        self.club = make_club()
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=future)

        # 4人参加
        self.members = [
            make_member(self.club, n, member_no=i + 1)
            for i, n in enumerate(["A", "B", "C", "D"])
        ]
        self.eps = [make_ep(self.event, member=m, attendance="yes") for m in self.members]

        # 2ラウンドの公開対戦表
        schedule = [
            {"round": 1, "matches": [
                {"court": 1, "team1": [self.eps[0].id, self.eps[1].id],
                 "team2": [self.eps[2].id, self.eps[3].id]}
            ], "rests": []},
            {"round": 2, "matches": [
                {"court": 1, "team1": [self.eps[0].id, self.eps[2].id],
                 "team2": [self.eps[1].id, self.eps[3].id]}
            ], "rests": []},
        ]
        make_published_schedule(self.event, schedule, game_type="doubles",
                                court_count=1, round_count=2)

    def _public_url(self):
        return reverse("tennis:event_public", args=[self.club.public_token, self.event.id])

    def _admin_url(self):
        return reverse("tennis:event_admin",
                       args=[self.club.public_token, self.club.admin_token, self.event.id])

    def test_public_view_stats_is_none(self):
        ctx = self.client.get(self._public_url()).context
        self.assertIsNone(ctx["stats"])

    def test_admin_view_stats_is_present(self):
        ctx = self.client.get(self._admin_url()).context
        stats = ctx["stats"]
        self.assertIsNotNone(stats)
        self.assertEqual(len(stats), 4)
        # 全員が2試合、休憩0
        for s in stats:
            self.assertEqual(s["matches"], 2)
            self.assertEqual(s["rests"], 0)
