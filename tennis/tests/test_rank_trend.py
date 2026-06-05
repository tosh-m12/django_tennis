"""
個人ページの「過去3ヶ月ランキング推移」グラフのテスト。
"""
from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import ClubRankingSetting
from tennis.views import _member_rank_trends, _rank_trend_svg, _resolve_club_ranking_config

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
        # 月内の最低試合数を1にして当月のランキングに乗りやすくする
        ClubRankingSetting.objects.create(club=self.club, preset="winrate", min_matches=1)
        self.today = timezone.localdate()
        ev = make_event(self.club, date=self.today)  # 当月のイベント
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)
        ep_a = make_ep(ev, member=self.a, attendance="yes")
        ep_b = make_ep(ev, member=self.b, attendance="yes")
        ms = make_published_schedule(
            ev,
            [{"round": 1, "matches": [{"court": 1, "team1": [ep_a.id], "team2": [ep_b.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms, 1, 1, 6, 0)  # A 勝ち

    def test_trends_current_month_rank(self):
        config = _resolve_club_ranking_config(self.club)
        trends = _member_rank_trends(self.club, self.a.id, self.today, config)
        self.assertEqual(len(trends["singles"]), 3)          # 3ヶ月分
        self.assertEqual(trends["singles"][-1]["rank"], 1)   # 当月は1位
        # B は2位
        tb = _member_rank_trends(self.club, self.b.id, self.today, config)
        self.assertEqual(tb["singles"][-1]["rank"], 2)

    def test_svg_generated_with_rank(self):
        config = _resolve_club_ranking_config(self.club)
        trends = _member_rank_trends(self.club, self.a.id, self.today, config)
        svg = _rank_trend_svg(trends["singles"])
        self.assertIn("<svg", svg)
        self.assertIn("1位", svg)
        self.assertIn("</svg>", svg)

    def test_all_out_of_rank_returns_empty(self):
        pts = [{"label": "1月", "rank": None, "total": 0} for _ in range(3)]
        self.assertEqual(_rank_trend_svg(pts), "")

    def test_member_page_renders_trend_below_stats(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        sb = {k: st for (k, _, st) in resp.context["stats_blocks"]}
        self.assertIn("singles", sb)
        self.assertIn("<svg", sb["singles"]["trend_svg"])
        # ページ本文に推移グラフのタイトルとSVGが含まれる
        html = resp.content.decode()
        self.assertIn("過去3ヶ月のランキング推移", html)
        self.assertIn("rank-trend-svg", html)
