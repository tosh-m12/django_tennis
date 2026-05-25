"""
対戦表生成（tennis.utils）の特性テスト。

random を使う関数なので「厳密な並び」ではなく、現状コードが保証している
構造的な不変条件（invariant）を固定する：
  - team1/team2/rests は ep_id(int) のみ
  - playing と rests を合わせると毎ラウンド全員が現れる（重複なし）
  - ダブルスは team1=2人/team2=2人、シングルスは 1人/1人
  - 人数・コート不足時の戻り値（[]）
"""
from __future__ import annotations

import random

from django.test import SimpleTestCase

from tennis.utils import (
    generate_doubles_schedule,
    generate_singles_schedule,
)


class DoublesScheduleTests(SimpleTestCase):
    def setUp(self):
        random.seed(12345)  # 再現性のため固定

    def test_eight_players_two_courts_all_play(self):
        players = [1, 2, 3, 4, 5, 6, 7, 8]
        sched = generate_doubles_schedule(players, num_rounds=4, num_courts=2)

        self.assertEqual(len(sched), 4)
        for rnd in sched:
            # 8人/2コート → 2試合・休憩0
            self.assertEqual(len(rnd["matches"]), 2)
            self.assertEqual(rnd["rests"], [])
            seen = []
            for m in rnd["matches"]:
                self.assertEqual(len(m["team1"]), 2)
                self.assertEqual(len(m["team2"]), 2)
                seen += m["team1"] + m["team2"]
            # 全員ちょうど1回ずつ登場・重複なし
            self.assertEqual(sorted(seen), players)

    def test_players_exceeding_courts_go_to_rests(self):
        players = [1, 2, 3, 4, 5, 6]
        sched = generate_doubles_schedule(players, num_rounds=3, num_courts=1)

        for rnd in sched:
            playing = []
            for m in rnd["matches"]:
                playing += m["team1"] + m["team2"]
            # 1コート → 4人プレイ・2人休憩
            self.assertEqual(len(playing), 4)
            self.assertEqual(len(rnd["rests"]), 2)
            # playing + rests = 全員（重複なし）
            self.assertEqual(sorted(playing + rnd["rests"]), players)

    def test_all_ids_are_int(self):
        sched = generate_doubles_schedule([1, 2, 3, 4], num_rounds=2, num_courts=1)
        for rnd in sched:
            for m in rnd["matches"]:
                for pid in m["team1"] + m["team2"]:
                    self.assertIsInstance(pid, int)
            for pid in rnd["rests"]:
                self.assertIsInstance(pid, int)

    def test_too_few_players_returns_empty(self):
        self.assertEqual(generate_doubles_schedule([1, 2, 3], 4, 1), [])

    def test_string_id_raises(self):
        with self.assertRaises(ValueError):
            generate_doubles_schedule(["1", "2", "3", "4"], 2, 1)


class SinglesScheduleTests(SimpleTestCase):
    def setUp(self):
        random.seed(67890)

    def test_four_players_two_courts(self):
        players = [10, 20, 30, 40]
        sched = generate_singles_schedule(players, num_rounds=3, num_courts=2)

        self.assertEqual(len(sched), 3)
        for rnd in sched:
            self.assertEqual(len(rnd["matches"]), 2)
            seen = []
            for m in rnd["matches"]:
                self.assertEqual(len(m["team1"]), 1)
                self.assertEqual(len(m["team2"]), 1)
                seen += m["team1"] + m["team2"]
            self.assertEqual(sorted(seen), players)
            self.assertEqual(rnd["rests"], [])

    def test_odd_players_one_rests(self):
        players = [1, 2, 3, 4, 5]
        sched = generate_singles_schedule(players, num_rounds=2, num_courts=1)
        for rnd in sched:
            playing = []
            for m in rnd["matches"]:
                playing += m["team1"] + m["team2"]
            self.assertEqual(len(playing), 2)  # 1コート=1試合
            self.assertEqual(len(rnd["rests"]), 3)
            self.assertEqual(sorted(playing + rnd["rests"]), players)

    def test_too_few_players_returns_empty(self):
        self.assertEqual(generate_singles_schedule([1], 4, 1), [])
