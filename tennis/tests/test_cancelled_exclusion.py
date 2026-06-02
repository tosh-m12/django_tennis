"""
中止イベントの試合は戦績ランキングと個人戦績に計上されない。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import (
    make_club,
    make_ep,
    make_event,
    make_member,
    make_published_schedule,
    make_score,
)


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


def _make_singles_event_with_score(club, date_, a, b, a_score=6, b_score=2, cancelled=False):
    """A vs B のシングルス 1試合（A 勝ち）を作る。"""
    ev = make_event(club, date=date_, cancelled=cancelled)
    ep_a = make_ep(ev, member=a, attendance="yes")
    ep_b = make_ep(ev, member=b, attendance="yes")
    ms = make_published_schedule(
        ev,
        [{"round": 1, "matches": [{"court": 1, "team1": [ep_a.id], "team2": [ep_b.id]}], "rests": []}],
        game_type="singles", court_count=1, round_count=1,
    )
    make_score(ms, 1, 1, a_score, b_score)
    return ev


@_NO_MANIFEST_STORAGES
class CancelledEventExclusionTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)

        # 4月：通常イベント3試合（A 全勝）
        for d in (1, 2, 3):
            _make_singles_event_with_score(
                self.club, datetime.date(2026, 4, d), self.a, self.b
            )

        # 4/10：中止イベント（A 勝ちの試合があるが、中止フラグあり）
        _make_singles_event_with_score(
            self.club, datetime.date(2026, 4, 10), self.a, self.b, cancelled=True
        )

    def test_member_detail_excludes_cancelled_event_matches(self):
        """個人ページ戦績に中止イベントの試合は計上されない。"""
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        sb = {k: st for (k, _, st) in ctx["stats_blocks"]}
        s = sb["singles"]
        # 3試合分のみ集計（中止1試合は含まれない）
        self.assertEqual(s["matches"], 3)
        self.assertEqual(s["wins"], 3)

    def test_member_detail_history_excludes_cancelled_event(self):
        """個人ページ試合履歴にも中止イベントの試合は出ない。"""
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        hb = {k: hist for (k, _, hist) in ctx["history_blocks"]}
        # シングルス履歴は3件（中止1件除外）
        self.assertEqual(len(hb["singles"]), 3)

    def test_ranking_excludes_cancelled_event_matches(self):
        """戦績ランキングも中止イベントを除外して集計。"""
        url = reverse("tennis:ranking", args=[self.club.public_token])
        ctx = self.client.get(url, {"start": "2026-04-01", "end": "2026-04-30"}).context
        ranked = ctx["ranking_singles"]["ranked"]
        # A の試合数は3（中止1除外）
        a_row = next(r for r in ranked if r["name"] == "A")
        self.assertEqual(a_row["matches"], 3)
        self.assertEqual(a_row["wins"], 3)
        b_row = next(r for r in ranked if r["name"] == "B")
        self.assertEqual(b_row["matches"], 3)
        self.assertEqual(b_row["losses"], 3)

    def test_cancelling_event_after_score_input_removes_from_ranking(self):
        """既存の試合があるイベントを後から中止にしたら、再描画で集計から外れる。"""
        # 4/1 を中止にする
        ev = self.club.events.get(date=datetime.date(2026, 4, 1))
        ev.cancelled = True
        ev.save(update_fields=["cancelled", "updated_at"])

        url = reverse("tennis:ranking", args=[self.club.public_token])
        ctx = self.client.get(url, {"start": "2026-04-01", "end": "2026-04-30"}).context
        ranked = ctx["ranking_singles"]["ranked"]
        # A の試合数は 2 に減る（4/1 中止 + 4/10 中止 = 2 除外）。
        # min_matches=3 なので、ranked に出ない可能性あり → others 確認
        all_rows = ranked + ctx["ranking_singles"]["others"]
        a_row = next(r for r in all_rows if r["name"] == "A")
        self.assertEqual(a_row["matches"], 2)
