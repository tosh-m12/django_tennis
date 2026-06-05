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

    def test_history_split_singles_doubles(self):
        # ダブルスのイベントを追加して履歴が分かれることを確認
        ev_d = make_event(self.club, date=datetime.date(2026, 5, 1))
        ep_a_d = make_ep(ev_d, member=self.a, attendance="yes")
        ep_b_d = make_ep(ev_d, member=self.b, attendance="yes")
        ep_c_d = make_ep(ev_d, display_name="C", attendance="yes")
        ep_d_d = make_ep(ev_d, display_name="D", attendance="yes")
        ms_d = make_published_schedule(
            ev_d,
            [{"round": 1, "matches": [{"court": 1,
                                       "team1": [ep_a_d.id, ep_c_d.id],
                                       "team2": [ep_b_d.id, ep_d_d.id]}],
              "rests": []}],
            game_type="doubles", court_count=1, round_count=1,
        )
        make_score(ms_d, 1, 1, 6, 3)

        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        hb = {k: hist for (k, _, hist) in ctx["history_blocks"]}
        self.assertEqual(len(hb["singles"]), 3)
        self.assertEqual(len(hb["doubles"]), 1)
        # ダブルスの方はパートナーが入っている
        self.assertEqual(hb["doubles"][0]["partners"], ["C"])

    def test_history_shows_all_matches_ignoring_get_period(self):
        # 別日のシングルス試合を追加
        ev_extra = make_event(self.club, date=datetime.date(2026, 5, 1))
        ep_a2 = make_ep(ev_extra, member=self.a, attendance="yes")
        ep_b2 = make_ep(ev_extra, member=self.b, attendance="yes")
        ms_extra = make_published_schedule(
            ev_extra,
            [{"round": 1, "matches": [{"court": 1, "team1": [ep_a2.id], "team2": [ep_b2.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms_extra, 1, 1, 6, 0)

        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        # GET で期間を絞っても履歴は全件（期間選択は廃止＝無視される）
        resp = self.client.get(url, {"start": "2026-04-01", "end": "2026-04-30"})
        ctx = resp.context
        hb = {k: hist for (k, _, hist) in ctx["history_blocks"]}
        self.assertEqual(len(hb["singles"]), 4)  # 4月3 + 5月1 すべて

    def test_stats_use_club_period_context(self):
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        # クラブ統一期間（既定90日）の情報が context に入る
        self.assertEqual(ctx["stats_period_days"], 90)
        today = timezone.localdate()
        self.assertEqual(ctx["stats_end_date"], today)
        self.assertEqual(ctx["stats_start_date"], today - datetime.timedelta(days=90))
        # 期間選択フォームは廃止
        self.assertNotContains(self.client.get(url), 'name="start"')

    def test_singles_only_member_doubles_block_absent(self):
        """シングルスにしか記録が無いメンバーは、ダブルスのカードや履歴を出さない。"""
        url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.id])
        ctx = self.client.get(url).context
        # シングルスのみ
        keys_stats = [k for (k, _, _) in ctx["stats_blocks"]]
        keys_hist = [k for (k, _, _) in ctx["history_blocks"]]
        self.assertEqual(keys_stats, ["singles"])
        self.assertEqual(keys_hist, ["singles"])
        self.assertFalse(ctx["no_records"])

    def test_no_records_flag_for_member_without_matches(self):
        """試合が1つも無いメンバーは no_records=True、stats/history_blocks は空。"""
        c = make_member(self.club, "C", member_no=3)
        url = reverse("tennis:member_detail", args=[self.club.public_token, c.id])
        ctx = self.client.get(url).context
        self.assertEqual(ctx["stats_blocks"], [])
        self.assertEqual(ctx["history_blocks"], [])
        self.assertTrue(ctx["no_records"])


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
