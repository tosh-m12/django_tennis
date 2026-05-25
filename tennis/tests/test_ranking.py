"""
月間ランキング集計（tennis.views.build_month_ranking）の特性テスト。

現状の集計仕様を固定する：
  - スコアが両方入っている試合のみ集計対象
  - member_id あり → ("m", member_id) キーで集計、ゲスト名 → ("g", name)
  - matches >= min_matches(既定3) を ranked、未満を others
  - 並びは win_pct → gp_pct → wins → diff → matches → name の降順（name は昇順）
"""
from __future__ import annotations

import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tennis.views import build_month_ranking, build_month_rankings
from tennis.models import Event

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_published_schedule,
    make_score,
)


class BuildMonthRankingTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 1))

        self.m_a = make_member(self.club, "Aさん")
        self.m_b = make_member(self.club, "Bさん")
        self.ep_a = make_ep(self.event, member=self.m_a, attendance="yes")
        self.ep_b = make_ep(self.event, member=self.m_b, attendance="yes")

        # 3ラウンド・1コート、A vs B（singles 形式の team リスト）
        schedule = [
            {"round": 1, "matches": [{"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]}], "rests": []},
            {"round": 2, "matches": [{"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]}], "rests": []},
            {"round": 3, "matches": [{"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]}], "rests": []},
        ]
        self.ms = make_published_schedule(
            self.event, schedule, game_type="singles", court_count=1, round_count=3
        )
        # A が全勝
        make_score(self.ms, 1, 1, 6, 0)
        make_score(self.ms, 2, 1, 6, 1)
        make_score(self.ms, 3, 1, 6, 2)

    def _events_qs(self):
        return Event.objects.filter(club=self.club)

    def test_ranked_contains_both_with_correct_stats(self):
        result = build_month_ranking(self._events_qs(), "singles", min_matches=3)
        ranked = result["ranked"]
        self.assertEqual(len(ranked), 2)
        self.assertEqual(result["others"], [])

        by_name = {r["name"]: r for r in ranked}
        a = by_name["Aさん"]
        b = by_name["Bさん"]

        self.assertEqual(a["matches"], 3)
        self.assertEqual(a["wins"], 3)
        self.assertEqual(a["losses"], 0)
        self.assertEqual(a["gf"], 18)  # 6+6+6
        self.assertEqual(a["ga"], 3)   # 0+1+2
        self.assertEqual(a["win_pct"], 100.0)
        self.assertEqual(a["rank"], 1)

        self.assertEqual(b["wins"], 0)
        self.assertEqual(b["losses"], 3)
        self.assertEqual(b["win_pct"], 0.0)
        self.assertEqual(b["rank"], 2)

    def test_sorted_by_win_pct_desc(self):
        ranked = build_month_ranking(self._events_qs(), "singles")["ranked"]
        self.assertEqual([r["name"] for r in ranked], ["Aさん", "Bさん"])

    def test_below_min_matches_goes_to_others(self):
        # 1試合だけのゲストを追加
        ep_guest = make_ep(self.event, display_name="ゲスト太郎", attendance="yes")
        sched = list(self.ms.schedule_json)
        sched.append(
            {"round": 4, "matches": [{"court": 1, "team1": [ep_guest.id], "team2": [self.ep_a.id]}], "rests": []}
        )
        self.ms.schedule_json = sched
        self.ms.save(update_fields=["schedule_json"])
        make_score(self.ms, 4, 1, 6, 0)

        result = build_month_ranking(self._events_qs(), "singles", min_matches=3)
        others_names = [r["name"] for r in result["others"]]
        self.assertIn("ゲスト太郎", others_names)
        # A は 4 試合になり ranked のまま
        self.assertIn("Aさん", [r["name"] for r in result["ranked"]])

    def test_match_without_both_scores_is_skipped(self):
        # スコア未入力の試合は集計されない
        self.ms.schedule_json = self.ms.schedule_json + [
            {"round": 9, "matches": [{"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]}], "rests": []}
        ]
        self.ms.save(update_fields=["schedule_json"])
        # round 9 にはスコアを入れない
        result = build_month_ranking(self._events_qs(), "singles", min_matches=3)
        a = next(r for r in result["ranked"] if r["name"] == "Aさん")
        self.assertEqual(a["matches"], 3)  # 9R は加算されない

    def test_other_game_type_excluded(self):
        # doubles で集計すると singles の対戦表は対象外 → 空
        result = build_month_ranking(self._events_qs(), "doubles")
        self.assertEqual(result["ranked"], [])
        self.assertEqual(result["others"], [])

    def test_empty_events(self):
        result = build_month_ranking(Event.objects.none(), "singles")
        self.assertEqual(result, {"ranked": [], "others": []})


class BuildMonthRankingsConsolidationTests(TestCase):
    """候補1: build_month_rankings の単一パス集計が個別呼び出しと等価かつ低クエリであることを固定。"""

    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 5, 1))
        m_a = make_member(self.club, "Aさん")
        m_b = make_member(self.club, "Bさん")
        ep_a = make_ep(self.event, member=m_a, attendance="yes")
        ep_b = make_ep(self.event, member=m_b, attendance="yes")
        schedule = [
            {"round": i, "matches": [{"court": 1, "team1": [ep_a.id], "team2": [ep_b.id]}], "rests": []}
            for i in range(1, 4)
        ]
        ms = make_published_schedule(
            self.event, schedule, game_type="singles", court_count=1, round_count=3
        )
        for i, (a, b) in enumerate([(6, 0), (6, 1), (6, 2)], start=1):
            make_score(ms, i, 1, a, b)

    def _qs(self):
        return Event.objects.filter(club=self.club)

    def test_consolidated_equals_separate_calls(self):
        combined = build_month_rankings(self._qs(), ["singles", "doubles"])
        self.assertEqual(combined["singles"], build_month_ranking(self._qs(), "singles"))
        self.assertEqual(combined["doubles"], build_month_ranking(self._qs(), "doubles"))

    def test_consolidated_uses_fewer_queries(self):
        with CaptureQueriesContext(connection) as combined_ctx:
            build_month_rankings(self._qs(), ["singles", "doubles"])
        with CaptureQueriesContext(connection) as separate_ctx:
            build_month_ranking(self._qs(), "singles")
            build_month_ranking(self._qs(), "doubles")
        self.assertLess(len(combined_ctx), len(separate_ctx))

    def test_empty_events_returns_both_types(self):
        result = build_month_rankings(Event.objects.none(), ["singles", "doubles"])
        self.assertEqual(
            result,
            {"singles": {"ranked": [], "others": []}, "doubles": {"ranked": [], "others": []}},
        )
