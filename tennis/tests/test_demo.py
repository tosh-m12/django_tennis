from __future__ import annotations

import datetime as dt

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tennis.demo_seed import sweep_stale_demo_clubs
from tennis.models import Club, EventParticipant

from .factories import make_club, make_ep, make_event, make_member


class DemoCleanupTests(TestCase):
    def _make_stale_demo(self, name: str) -> Club:
        return Club.objects.create(
            name=name,
            is_demo=True,
            demo_last_seen=timezone.now() - dt.timedelta(hours=2),
        )

    def test_sweep_can_limit_cleanup_batch(self):
        stale = [self._make_stale_demo(f"デモ{i}") for i in range(3)]

        deleted = sweep_stale_demo_clubs(batch_size=1)

        self.assertEqual(deleted, 1)
        self.assertEqual(Club.objects.filter(id__in=[c.id for c in stale]).count(), 2)

    def test_demo_entry_only_sweeps_one_stale_club(self):
        stale = [self._make_stale_demo(f"デモ{i}") for i in range(3)]

        response = self.client.get(reverse("tennis:demo"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Club.objects.filter(id__in=[c.id for c in stale]).count(), 2)
        self.assertTrue(Club.objects.filter(is_demo=True, id=self.client.session["demo_club_id"]).exists())

    def test_club_cascade_skips_redundant_member_history_updates(self):
        club = make_club()
        event = make_event(club, date=timezone.localdate())
        member = make_member(club, "削除対象", member_no=1)
        make_ep(event, member=member, attendance="yes")

        with CaptureQueriesContext(connection) as queries:
            club.delete()

        redundant_updates = [
            q["sql"]
            for q in queries.captured_queries
            if q["sql"].startswith('UPDATE "tennis_eventparticipant" SET "member_deleted"')
        ]
        self.assertEqual(redundant_updates, [])
        self.assertFalse(EventParticipant.objects.exists())
