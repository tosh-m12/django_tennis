"""Regression coverage for constant-query ranking and member history pages."""
import datetime as dt

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tennis.models import MatchScore
from tennis.views import (
    _build_score_maps, _member_rank_trend, _ranking_preset_default_config,
)
from .factories import make_club, make_ep, make_event, make_member, make_published_schedule, make_score


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class RankingQueryGrowthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.club = make_club()
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)
        self.today = timezone.localdate()
        self.member_url = reverse("tennis:member_detail", args=[self.club.public_token, self.a.pk])
        self.ranking_url = reverse("tennis:ranking", args=[self.club.public_token])

    def add_match(self, index, *, date=None, scored=True):
        event = make_event(self.club, date=date or self.today - dt.timedelta(days=index % 60))
        a = make_ep(event, member=self.a)
        b = make_ep(event, member=self.b)
        schedule = make_published_schedule(event, [
            {"round": 1, "matches": [{"court": 1, "team1": [a.pk], "team2": [b.pk]}]}
        ], game_type="singles")
        if scored:
            make_score(schedule, 1, 1, 6, 2)
        return schedule

    def get_counted(self, url):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        scores = [q for q in queries if 'FROM "tennis_matchscore"' in q['sql']]
        self.assertEqual(len(scores), 1)
        return response, len(queries)

    def test_queries_do_not_grow_from_one_to_500_schedules(self):
        counts = None
        previous = 0
        for size in (1, 100, 500):
            for i in range(previous, size):
                self.add_match(i, scored=i % 10 != 9)
            # Session/access bookkeeping must be equally warm at each size.
            self.client.get(self.member_url)
            member, member_count = self.get_counted(self.member_url)
            ranking, ranking_count = self.get_counted(self.ranking_url)
            stats = {gt: data for gt, _, data in member.context['stats_blocks']}['singles']
            self.assertEqual(stats['matches'], size - size // 10)
            self.assertEqual(stats['wins'], size - size // 10)
            self.assertEqual(len(member.context['matches_history']), size)
            singles = ranking.context['ranking_singles']
            row = next(r for r in singles['ranked'] + singles['others'] if r['member_id'] == self.a.pk)
            self.assertEqual(row['matches'], stats['matches'])
            if counts is None:
                counts = (member_count, ranking_count)
            else:
                self.assertEqual((member_count, ranking_count), counts)
            previous = size

    def test_scores_are_fresh_on_the_next_request(self):
        schedule = self.add_match(0)
        first = self.client.get(self.member_url)
        self.assertEqual(first.context['matches_history'][0]['my_score'], 6)
        MatchScore.objects.filter(match_schedule=schedule).update(side_a_score=1, side_b_score=6)
        second = self.client.get(self.member_url)
        self.assertEqual(second.context['matches_history'][0]['my_score'], 1)
        self.assertEqual(second.context['matches_history'][0]['result'], '負')

    def test_reused_history_preserves_trend_window_and_empty_scores(self):
        schedules = [
            self.add_match(0, date=self.today - dt.timedelta(days=400)),
            self.add_match(1, date=self.today - dt.timedelta(days=100)),
            self.add_match(2),
            self.add_match(3, scored=False),
            self.add_match(4, date=self.today + dt.timedelta(days=1)),
        ]
        config = _ranking_preset_default_config()
        config['min_matches'] = 1
        start = self.today - dt.timedelta(days=180)
        expected = _member_rank_trend(self.club, self.a.pk, config, start, self.today)
        maps = _build_score_maps(schedules)
        self.assertEqual(maps[schedules[3].pk], {})
        actual = _member_rank_trend(
            self.club, self.a.pk, config, start, self.today,
            schedules=list(reversed(schedules)), score_maps=maps,
        )
        self.assertEqual(actual, expected)
        self.assertTrue(actual['singles'])
        self.assertTrue(all(start <= point['date'] <= self.today for point in actual['singles']))
