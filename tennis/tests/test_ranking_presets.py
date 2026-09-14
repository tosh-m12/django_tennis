"""
戦績ランキングのプリセット制ルール（勝率重視/勝ち点制/勝利数重視）のテスト。

- _compute_ranking_from の config 分岐（win% / 勝ち点 / ソート順 / 最低試合数）
- _resolve_club_ranking_config のデフォルト/保存値解決
- save_club_ranking_setting 保存API（正常系/認可/バリデーション）
"""
from __future__ import annotations

import datetime
import json

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import ClubRankingSetting, Event
from tennis.views import (
    build_month_rankings,
    _ranking_preset_default_config,
    _resolve_club_ranking_config,
)

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


def _cfg(preset, **over):
    c = _ranking_preset_default_config(preset)
    c.update(over)
    return c


def _build_singles_event(club, date, rounds):
    """
    rounds: list of (ep1, ep2, s1, s2)。各ラウンド1コートのシングルス1試合を作る。
    """
    ev = make_event(club, date=date)
    schedule = [
        {"round": i, "matches": [{"court": 1, "team1": [e1.id], "team2": [e2.id]}], "rests": []}
        for i, (e1, e2, _s1, _s2) in enumerate(rounds, start=1)
    ]
    ms = make_published_schedule(
        ev, schedule, game_type="singles", court_count=1, round_count=len(rounds)
    )
    for i, (_e1, _e2, s1, s2) in enumerate(rounds, start=1):
        make_score(ms, i, 1, s1, s2)
    return ev


class PresetOrderingTests(TestCase):
    """同じデータでもプリセットによって並び順が変わることを確認。"""

    def setUp(self):
        self.club = make_club()
        ev = make_event(self.club, date=datetime.date(2026, 5, 1))
        high = make_member(self.club, "HIGH", member_no=1)   # 高勝率・少試合
        vol = make_member(self.club, "VOL", member_no=2)     # 多勝利・勝率50%
        fill = make_member(self.club, "FILL", member_no=3)   # 対戦相手（順位は問わない）
        ep_high = make_ep(ev, member=high, attendance="yes")
        ep_vol = make_ep(ev, member=vol, attendance="yes")
        ep_fill = make_ep(ev, member=fill, attendance="yes")

        rounds = [
            # HIGH: 2戦2勝（勝率100%, 勝2, 勝ち点6）
            (ep_high, ep_fill, 6, 0),
            (ep_high, ep_fill, 6, 0),
            # VOL: 6戦3勝3敗（勝率50%, 勝3, 勝ち点9）
            (ep_vol, ep_fill, 6, 0),
            (ep_vol, ep_fill, 6, 0),
            (ep_vol, ep_fill, 6, 0),
            (ep_vol, ep_fill, 0, 6),
            (ep_vol, ep_fill, 0, 6),
            (ep_vol, ep_fill, 0, 6),
        ]
        self._ev = _build_singles_event(self.club, datetime.date(2026, 5, 2), rounds)

    def _ranked_names(self, preset):
        qs = Event.objects.filter(club=self.club)
        result = build_month_rankings(qs, ["singles"], _cfg(preset, min_matches=2))
        return [r["name"] for r in result["singles"]["ranked"]]

    def test_winrate_orders_high_before_vol(self):
        names = self._ranked_names("winrate")
        self.assertLess(names.index("HIGH"), names.index("VOL"))

    def test_points_orders_vol_before_high(self):
        names = self._ranked_names("points")
        self.assertLess(names.index("VOL"), names.index("HIGH"))

    def test_wins_orders_vol_before_high(self):
        names = self._ranked_names("wins")
        self.assertLess(names.index("VOL"), names.index("HIGH"))


class CountDrawsAndPointsTests(TestCase):
    """引き分けの勝率算入と勝ち点計算（配点上書き含む）。"""

    def setUp(self):
        self.club = make_club()
        ev = make_event(self.club, date=datetime.date(2026, 5, 3))
        x = make_member(self.club, "X", member_no=1)
        f = make_member(self.club, "F", member_no=2)
        ep_x = make_ep(ev, member=x, attendance="yes")
        ep_f = make_ep(ev, member=f, attendance="yes")
        # X: 1勝2分（3試合）
        rounds = [
            (ep_x, ep_f, 6, 0),  # win
            (ep_x, ep_f, 3, 3),  # draw
            (ep_x, ep_f, 3, 3),  # draw
        ]
        self._ev = _build_singles_event(self.club, datetime.date(2026, 5, 4), rounds)

    def _x_row(self, config):
        qs = Event.objects.filter(club=self.club)
        ranked = build_month_rankings(qs, ["singles"], config)["singles"]["ranked"]
        return next(r for r in ranked if r["name"] == "X")

    def test_win_pct_count_draws_off(self):
        # 1勝 / 3試合 = 33.3%
        row = self._x_row(_cfg("winrate", count_draws=False, min_matches=1))
        self.assertEqual(row["win_pct"], 33.3)

    def test_win_pct_count_draws_on(self):
        # (1 + 0.5*2) / 3 = 66.7%
        row = self._x_row(_cfg("winrate", count_draws=True, min_matches=1))
        self.assertEqual(row["win_pct"], 66.7)

    def test_points_default_3_1_0(self):
        # 1勝*3 + 2分*1 + 0敗*0 = 5
        row = self._x_row(_cfg("points", min_matches=1))
        self.assertEqual(row["points"], 5)

    def test_points_override_2_1_0(self):
        # 1勝*2 + 2分*1 = 4
        row = self._x_row(_cfg("points", points_win=2.0, points_draw=1.0, points_loss=0.0, min_matches=1))
        self.assertEqual(row["points"], 4)


class MinMatchesPresetDefaultTests(TestCase):
    """プリセット別の最低試合数デフォルト（勝率重視=6, 勝ち点/勝利数=3）。"""

    def setUp(self):
        self.club = make_club()
        ev = make_event(self.club, date=datetime.date(2026, 5, 5))
        p = make_member(self.club, "P", member_no=1)
        f = make_member(self.club, "F", member_no=2)
        ep_p = make_ep(ev, member=p, attendance="yes")
        ep_f = make_ep(ev, member=f, attendance="yes")
        # P: 5試合（全勝）→ 勝率重視(6)では others、勝ち点/勝利数(3)では ranked
        rounds = [(ep_p, ep_f, 6, 0) for _ in range(5)]
        self._ev = _build_singles_event(self.club, datetime.date(2026, 5, 6), rounds)

    def _split(self, preset):
        qs = Event.objects.filter(club=self.club)
        res = build_month_rankings(qs, ["singles"], _ranking_preset_default_config(preset))["singles"]
        return (
            [r["name"] for r in res["ranked"]],
            [r["name"] for r in res["others"]],
        )

    def test_winrate_default_6_excludes_5_match_player(self):
        ranked, others = self._split("winrate")
        self.assertNotIn("P", ranked)
        self.assertIn("P", others)

    def test_points_default_3_includes_5_match_player(self):
        ranked, _others = self._split("points")
        self.assertIn("P", ranked)


@_NO_MANIFEST_STORAGES
class ResolveRankingConfigTests(TestCase):
    """_resolve_club_ranking_config の解決（設定なし→デフォルト / あり→保存値）。"""

    def test_no_setting_returns_winrate_default(self):
        club = make_club()
        cfg = _resolve_club_ranking_config(club)
        self.assertEqual(cfg["preset"], "winrate")
        self.assertEqual(cfg["min_matches"], 6)
        self.assertFalse(cfg["count_draws"])

    def test_existing_setting_returned(self):
        club = make_club()
        ClubRankingSetting.objects.create(
            club=club, preset="points", count_draws=True,
            points_win=2, points_draw=1, points_loss=0, min_matches=4,
        )
        cfg = _resolve_club_ranking_config(club)
        self.assertEqual(cfg["preset"], "points")
        self.assertTrue(cfg["count_draws"])
        self.assertEqual(cfg["points_win"], 2.0)
        self.assertEqual(cfg["min_matches"], 4)


@_NO_MANIFEST_STORAGES
class RankingNameLinkTests(TestCase):
    """戦績表の名前 → 個人ページリンク（メンバーのみ、ゲストはテキスト）。"""

    def setUp(self):
        self.club = make_club()
        # メンバーは min 1 で ranked に出るよう設定
        ClubRankingSetting.objects.create(club=self.club, preset="winrate", min_matches=1)
        ev = make_event(
            self.club, date=timezone.localdate() - datetime.timedelta(days=20)
        )
        self.member = make_member(self.club, "メンバーA", member_no=1)
        ep_m = make_ep(ev, member=self.member, attendance="yes")
        ep_g = make_ep(ev, display_name="ゲストB", attendance="yes")
        schedule = [
            {"round": i, "matches": [{"court": 1, "team1": [ep_m.id], "team2": [ep_g.id]}], "rests": []}
            for i in range(1, 3)
        ]
        ms = make_published_schedule(ev, schedule, game_type="singles", court_count=1, round_count=2)
        make_score(ms, 1, 1, 6, 0)
        make_score(ms, 2, 1, 6, 1)

    def test_rows_carry_member_id(self):
        qs = Event.objects.filter(club=self.club)
        ranked = build_month_rankings(qs, ["singles"], _cfg("winrate", min_matches=1))["singles"]["ranked"]
        by_name = {r["name"]: r for r in ranked}
        self.assertEqual(by_name["メンバーA"]["member_id"], self.member.id)
        self.assertIsNone(by_name["ゲストB"]["member_id"])

    def test_ranking_page_links_member_not_guest(self):
        url = reverse("tennis:ranking", args=[self.club.public_token])
        html = self.client.get(url, {"start": "2026-05-01", "end": "2026-05-31"}).content.decode()
        member_url = reverse("tennis:member_detail", args=[self.club.public_token, self.member.id])
        self.assertIn(f'href="{member_url}"', html)
        # ゲストはリンクにならない（名前は出るがアンカー無し）
        self.assertIn("ゲストB", html)
        self.assertNotIn(f">ゲストB</a>", html)

    def test_ranking_page_admin_uses_admin_link(self):
        url = reverse("tennis:ranking_admin", args=[self.club.public_token, self.club.admin_token])
        html = self.client.get(url, {"start": "2026-05-01", "end": "2026-05-31"}).content.decode()
        admin_url = reverse(
            "tennis:member_detail_admin",
            args=[self.club.public_token, self.club.admin_token, self.member.id],
        )
        self.assertIn(f'href="{admin_url}"', html)


@_NO_MANIFEST_STORAGES
class RankingRuleSummaryTests(TestCase):
    """集計ルールの要約（戦績ページ・一般ヘルプの連動表示）。"""

    def test_summary_reflects_preset(self):
        from tennis.views import _ranking_rule_summary
        s = _ranking_rule_summary(_ranking_preset_default_config("points"))
        self.assertEqual(s["preset"], "points")
        self.assertEqual(s["label"], "勝ち点制")
        self.assertIn("勝ち点", s["sort"])
        self.assertEqual(s["min_matches"], 3)

    def test_ranking_page_context_has_rule(self):
        club = make_club()
        ClubRankingSetting.objects.create(club=club, preset="wins", min_matches=3)
        url = reverse("tennis:ranking", args=[club.public_token])
        ctx = self.client.get(url).context
        self.assertEqual(ctx["ranking_rule"]["preset"], "wins")
        self.assertEqual(ctx["ranking_rule"]["label"], "勝利数重視型")

    def test_user_help_context_has_rule(self):
        club = make_club()
        url = reverse("tennis:club_user_help", args=[club.public_token])
        ctx = self.client.get(url).context
        # 設定なし → 勝率重視型
        self.assertEqual(ctx["ranking_rule"]["preset"], "winrate")


@_NO_MANIFEST_STORAGES
class SaveRankingSettingTests(TestCase):
    """save_club_ranking_setting 保存API。"""

    def setUp(self):
        self.club = make_club()
        self.url = reverse("tennis:save_club_ranking_setting")

    def _payload(self, **over):
        p = {
            "preset": "points",
            "count_draws": True,
            "points_win": 2.5,
            "points_draw": 1.0,
            "points_loss": 0.0,
            "min_matches": 4,
            "period_days": 60,
        }
        p.update(over)
        return p

    def test_save_happy_path(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "admin_token": self.club.admin_token,
            "settings_json": json.dumps(self._payload()),
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        obj = ClubRankingSetting.objects.get(club=self.club)
        self.assertEqual(obj.preset, "points")
        self.assertTrue(obj.count_draws)
        self.assertEqual(float(obj.points_win), 2.5)
        self.assertEqual(obj.min_matches, 4)
        self.assertEqual(obj.period_days, 60)

    def test_wrong_admin_token_forbidden(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "admin_token": "WRONG",
            "settings_json": json.dumps(self._payload()),
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ClubRankingSetting.objects.filter(club=self.club).exists())

    def test_bad_preset_rejected(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "admin_token": self.club.admin_token,
            "settings_json": json.dumps(self._payload(preset="nope")),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_preset")

    def test_negative_points_rejected(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "admin_token": self.club.admin_token,
            "settings_json": json.dumps(self._payload(points_win=-1)),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_points")

    def test_non_half_step_points_rejected(self):
        resp = self.client.post(self.url, {
            "club_id": self.club.id,
            "admin_token": self.club.admin_token,
            "settings_json": json.dumps(self._payload(points_draw=0.3)),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_points")

    def test_bad_period_days_rejected(self):
        for bad in (0, -5, 4000):
            resp = self.client.post(self.url, {
                "club_id": self.club.id,
                "admin_token": self.club.admin_token,
                "settings_json": json.dumps(self._payload(period_days=bad)),
            })
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["error"], "bad_period_days")
