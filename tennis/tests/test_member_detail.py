"""
メンバー個人ページ（tennis.views.member_detail）と関連APIのテスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import Member

from .factories import (
    make_club,
    make_event,
    make_ep,
    make_member,
    make_published_schedule,
    make_score,
)


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class MemberDetailRenderTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.m = make_member(self.club, "Aさん", member_no=1, is_fixed=True)

    def test_public_url_renders(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.m.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_admin"])
        self.assertEqual(resp.context["member"].id, self.m.id)

    def test_admin_url_renders(self):
        url = reverse(
            "tennis:member_detail_admin",
            args=[self.club.public_token, self.club.admin_token, self.m.id],
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_admin"])

    def test_admin_token_mismatch_400(self):
        url = reverse(
            "tennis:member_detail_admin",
            args=[self.club.public_token, "wrongtoken", self.m.id],
        )
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_other_club_member_404(self):
        other = make_club()
        url = reverse("tennis:member_detail", args=[other.public_token, self.m.id])
        # Aさん は self.club のメンバーで other 内では見つからない
        self.assertEqual(self.client.get(url).status_code, 404)


@_NO_MANIFEST_STORAGES
class MemberDetailStatsTests(TestCase):
    """戦績集計が schedule_json + MatchScore から正しく計算される。"""

    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 4, 1))
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)
        self.ep_a = make_ep(self.event, member=self.a, attendance="yes")
        self.ep_b = make_ep(self.event, member=self.b, attendance="yes")

        # シングルス：A vs B、A 全勝（3試合）
        schedule = [
            {"round": i, "matches": [
                {"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]},
            ], "rests": []}
            for i in range(1, 4)
        ]
        self.ms = make_published_schedule(
            self.event, schedule, game_type="singles", court_count=1, round_count=3
        )
        for i, (s1, s2) in enumerate([(6, 0), (6, 2), (6, 3)], start=1):
            make_score(self.ms, i, 1, s1, s2)

    def test_singles_stats_for_a(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        sb = {k: st for (k, _, st) in ctx["stats_blocks"]}
        s = sb["singles"]
        self.assertEqual(s["matches"], 3)
        self.assertEqual(s["wins"], 3)
        self.assertEqual(s["losses"], 0)
        self.assertEqual(s["gf"], 18)
        self.assertEqual(s["ga"], 5)
        self.assertEqual(s["win_pct"], 100.0)

    def test_history_for_a_has_three_entries(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        hist = ctx["matches_history"]
        self.assertEqual(len(hist), 3)
        # 対戦相手は B
        for h in hist:
            self.assertEqual(h["opponents"], ["B"])
            self.assertTrue(h["has_score"])

    def test_b_stats_show_losses(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.b.id])
        ctx = self.client.get(url).context
        sb = {k: st for (k, _, st) in ctx["stats_blocks"]}
        s = sb["singles"]
        self.assertEqual(s["wins"], 0)
        self.assertEqual(s["losses"], 3)
        self.assertEqual(s["win_pct"], 0.0)


class UpdateMemberDisplayNameTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.m = make_member(self.club, "旧名", member_no=1, is_fixed=False)
        # 他イベントに同メンバーのEPを作って伝播を確認
        self.event = make_event(self.club, date=timezone.localdate())
        self.ep = make_ep(self.event, member=self.m, attendance="yes")
        self.url = reverse("tennis:update_member_display_name")

    def test_rename_propagates_to_eps(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "member_id": self.m.id,
            "display_name": "新名",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.m.refresh_from_db()
        self.ep.refresh_from_db()
        self.assertEqual(self.m.display_name, "新名")
        self.assertEqual(self.ep.display_name, "新名")

    def test_empty_name_rejected(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "member_id": self.m.id,
            "display_name": "  ",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "empty_name")

    def test_missing_params_rejected(self):
        resp = self.client.post(self.url, {"display_name": "X"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "missing_params")

    def test_other_club_member_404(self):
        other = make_club()
        resp = self.client.post(self.url, {
            "club_id": other.id,
            "member_id": self.m.id,
            "display_name": "X",
        })
        self.assertEqual(resp.status_code, 404)
