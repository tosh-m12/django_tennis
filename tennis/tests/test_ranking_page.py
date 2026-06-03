"""
戦績表ページ（tennis.views.ranking_page）のテスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import ClubRankingSetting

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
class RankingPageAccessTests(TestCase):
    def setUp(self):
        self.club = make_club()

    def test_public_url_renders(self):
        url = reverse("tennis:ranking", args=[self.club.public_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_admin"])

    def test_admin_url_renders(self):
        url = reverse("tennis:ranking_admin", args=[self.club.public_token, self.club.admin_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_admin"])

    def test_admin_token_mismatch_400(self):
        url = reverse("tennis:ranking_admin", args=[self.club.public_token, "wrongtoken"])
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_ranking_page_does_not_show_ranking_link_in_topbar(self):
        """戦績ページ自身のトップバーには「戦績」リンクを表示しない。"""
        url = reverse("tennis:ranking", args=[self.club.public_token])
        resp = self.client.get(url)
        # context に current_page="ranking" が入っている
        self.assertEqual(resp.context.get("current_page"), "ranking")
        # 戻る/設定リンクは出るが、自身への戦績リンクは出ない
        self.assertNotContains(resp, 'id="topbar-ranking-link"')

    def test_home_shows_ranking_link_in_topbar(self):
        """ホームのトップバーには「戦績」リンクを表示する。"""
        url = reverse("tennis:club_home", args=[self.club.public_token])
        resp = self.client.get(url)
        self.assertContains(resp, 'id="topbar-ranking-link"')


@_NO_MANIFEST_STORAGES
class RankingPagePeriodTests(TestCase):
    """期間フィルタが効くこと。"""

    def setUp(self):
        self.club = make_club()
        # このテストは3試合前提（期間フィルタの検証が目的）。旧来の最低3試合に設定。
        ClubRankingSetting.objects.create(club=self.club, preset="winrate", min_matches=3)
        # 4月に3試合（A全勝）
        self.event_apr = make_event(self.club, date=datetime.date(2026, 4, 5))
        a = make_member(self.club, "A", member_no=1)
        b = make_member(self.club, "B", member_no=2)
        ep_a = make_ep(self.event_apr, member=a, attendance="yes")
        ep_b = make_ep(self.event_apr, member=b, attendance="yes")
        ms = make_published_schedule(
            self.event_apr,
            [{"round": i, "matches": [
                {"court": 1, "team1": [ep_a.id], "team2": [ep_b.id]}],
              "rests": []}
             for i in range(1, 4)],
            game_type="singles", court_count=1, round_count=3,
        )
        for i, (s1, s2) in enumerate([(6, 0), (6, 1), (6, 2)], start=1):
            make_score(ms, i, 1, s1, s2)

    def test_default_period_is_current_month(self):
        url = reverse("tennis:ranking", args=[self.club.public_token])
        ctx = self.client.get(url).context
        today = timezone.localdate()
        first = today.replace(day=1)
        self.assertEqual(ctx["start_date"], first)
        # period_label = "YYYY年M月"
        self.assertIn(str(today.year), ctx["period_label"])
        self.assertIn(f"{today.month}月", ctx["period_label"])

    def test_explicit_period_filters(self):
        url = reverse("tennis:ranking", args=[self.club.public_token])
        # 4月だけに絞れば A は ranked に出る（3試合）
        resp = self.client.get(url, {"start": "2026-04-01", "end": "2026-04-30"})
        ctx = resp.context
        ranked_names = [r["name"] for r in ctx["ranking_singles"]["ranked"]]
        self.assertIn("A", ranked_names)
        # 1月に絞ると ranked は空
        resp2 = self.client.get(url, {"start": "2026-01-01", "end": "2026-01-31"})
        self.assertEqual(resp2.context["ranking_singles"]["ranked"], [])


@_NO_MANIFEST_STORAGES
class ClubHomeNoLongerCarriesRankingTests(TestCase):
    """club_home の context から ranking 関連キーが消えている。"""

    def setUp(self):
        self.club = make_club()

    def test_home_no_longer_renders_ranking_section(self):
        url = reverse("tennis:club_home", args=[self.club.public_token])
        resp = self.client.get(url)
        self.assertNotContains(resp, "当月戦績")
        self.assertNotContains(resp, "rank-table")
