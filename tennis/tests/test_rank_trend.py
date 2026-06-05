"""
個人ページの「過去180日・試合日ごとのランキング推移」グラフのテスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import ClubRankingSetting
from tennis.views import _member_rank_trend, _rank_trend_svg, _resolve_club_ranking_config

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_published_schedule,
    make_score,
)

_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class RankTrendTests(TestCase):
    def setUp(self):
        self.club = make_club()
        # 最低試合数1で当日のランキングに乗りやすく
        ClubRankingSetting.objects.create(club=self.club, preset="winrate", min_matches=1)
        self.today = timezone.localdate()
        self.start = self.today - datetime.timedelta(days=180)
        # 期間内の2日に試合（A全勝）
        d1 = self.today - datetime.timedelta(days=30)
        ev1 = make_event(self.club, date=d1)
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)
        ep_a1 = make_ep(ev1, member=self.a, attendance="yes")
        ep_b1 = make_ep(ev1, member=self.b, attendance="yes")
        ms1 = make_published_schedule(
            ev1,
            [{"round": 1, "matches": [{"court": 1, "team1": [ep_a1.id], "team2": [ep_b1.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms1, 1, 1, 6, 0)  # A 勝ち

        ev2 = make_event(self.club, date=self.today)
        ep_a2 = make_ep(ev2, member=self.a, attendance="yes")
        ep_b2 = make_ep(ev2, member=self.b, attendance="yes")
        ms2 = make_published_schedule(
            ev2,
            [{"round": 1, "matches": [{"court": 1, "team1": [ep_a2.id], "team2": [ep_b2.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms2, 1, 1, 6, 2)  # A 勝ち

    def _config(self):
        return _resolve_club_ranking_config(self.club)

    def test_trend_has_point_per_match_day(self):
        trends = _member_rank_trend(self.club, self.a.id, self._config(), self.start, self.today)
        # シングルスは試合のあった2日ぶん
        self.assertEqual(len(trends["singles"]), 2)
        # どちらの試合日もA全勝なので1位
        self.assertEqual([p["rank"] for p in trends["singles"]], [1, 1])
        # ダブルスは試合無し
        self.assertEqual(trends["doubles"], [])

    def test_opponent_rank(self):
        trends = _member_rank_trend(self.club, self.b.id, self._config(), self.start, self.today)
        self.assertEqual(trends["singles"][-1]["rank"], 2)

    def test_step_svg_generated(self):
        trends = _member_rank_trend(self.club, self.a.id, self._config(), self.start, self.today)
        svg = _rank_trend_svg(trends["singles"], self.start, self.today)
        self.assertIn("<svg", svg)
        self.assertIn("<polyline", svg)   # 階段の線
        self.assertIn("1位", svg)
        self.assertIn("現在", svg)

    def test_all_out_of_rank_returns_empty(self):
        pts = [{"date": self.today, "rank": None, "total": 0}]
        self.assertEqual(_rank_trend_svg(pts, self.start, self.today), "")

    def test_axis_bottom_is_club_last_place(self):
        # 3人目Cを当日参加させ、クラブ最下位=3 にする（Aは常に1位）
        c = make_member(self.club, "C", member_no=3)
        ev = make_event(self.club, date=self.today)
        ep_b = make_ep(ev, member=self.b, attendance="yes")
        ep_c = make_ep(ev, member=c, attendance="yes")
        ms = make_published_schedule(
            ev,
            [{"round": 1, "matches": [{"court": 1, "team1": [ep_b.id], "team2": [ep_c.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms, 1, 1, 6, 0)  # B が C に勝ち
        trends = _member_rank_trend(self.club, self.a.id, self._config(), self.start, self.today)
        self.assertEqual(trends["singles"][-1]["total"], 3)   # 最新は3人ランク
        svg = _rank_trend_svg(trends["singles"], self.start, self.today)
        self.assertIn("3位", svg)   # 軸下端＝クラブ最下位(3位)
        self.assertIn("1位", svg)   # 軸上端

    def test_member_page_renders_trend_below_stats(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        sb = {k: st for (k, _, st) in resp.context["stats_blocks"]}
        self.assertIn("singles", sb)
        self.assertIn("<svg", sb["singles"]["trend_svg"])
        html = resp.content.decode()
        self.assertIn("過去180日のランキング推移", html)
        self.assertIn("rank-trend-svg", html)
