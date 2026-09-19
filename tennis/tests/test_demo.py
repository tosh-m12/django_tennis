from __future__ import annotations

import datetime as dt

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tennis.demo_seed import create_seeded_demo_club, sweep_stale_demo_clubs
from tennis.models import Club, EventParticipant, MatchSchedule, MatchScore

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

    def test_demo_entry_does_not_sweep_stale_clubs(self):
        stale = [self._make_stale_demo(f"デモ{i}") for i in range(3)]

        response = self.client.get(reverse("tennis:demo"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Club.objects.filter(id__in=[c.id for c in stale]).count(), 3)
        self.assertTrue(Club.objects.filter(is_demo=True, id=self.client.session["demo_club_id"]).exists())

    def test_demo_entry_replaces_outdated_session_without_deleting_old_club(self):
        old_club = Club.objects.create(
            name="旧デモ",
            is_demo=True,
            demo_last_seen=timezone.now(),
            demo_seed_version=0,
        )
        session = self.client.session
        session["demo_club_id"] = old_club.id
        session.save()

        response = self.client.get(reverse("tennis:demo"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Club.objects.filter(id=old_club.id).exists())
        self.assertNotEqual(self.client.session["demo_club_id"], old_club.id)

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

    def test_demo_seed_uses_bounded_database_round_trips(self):
        with CaptureQueriesContext(connection) as queries:
            club = create_seeded_demo_club()

        self.assertLessEqual(len(queries), 30)
        self.assertEqual(club.members.count(), 20)
        self.assertEqual(club.events.count(), 32)
        self.assertEqual(MatchSchedule.objects.filter(event__club=club).count(), 21)
        self.assertTrue(MatchScore.objects.filter(match_schedule__event__club=club).exists())


class DemoModeTests(TestCase):
    def test_modes_reuse_own_club_and_preserve_changes(self):
        member = self.client.get(reverse('tennis:demo'))
        club = Club.objects.get(pk=self.client.session['demo_club_id'])
        club.name = '編集したデモ'
        club.save()
        admin = self.client.get(reverse('tennis:demo'), {'mode': 'admin'})
        self.assertEqual(admin.url, reverse('tennis:club_home_admin', args=[club.admin_path_token, club.admin_token]))
        page = self.client.get(admin.url)
        self.assertContains(page, '編集したデモ')
        self.assertContains(page, '?mode=member')
        self.assertContains(page, '?mode=admin')
        again = self.client.get(reverse('tennis:demo'), {'mode': 'member'})
        self.assertEqual(again.url, member.url)
        self.assertEqual(Club.objects.filter(is_demo=True).count(), 1)

    def test_post_can_start_admin_demo(self):
        response = self.client.post(reverse('tennis:demo'), {'mode': 'admin'})
        club = Club.objects.get(pk=self.client.session['demo_club_id'])
        self.assertEqual(response.url, reverse('tennis:club_home_admin', args=[club.admin_path_token, club.admin_token]))

    def test_real_club_in_session_is_never_promoted_to_demo_admin(self):
        real = make_club()
        session = self.client.session
        session['demo_club_id'] = real.id
        session.save()
        response = self.client.get(reverse('tennis:demo'), {'mode': 'admin'})
        self.assertNotIn(real.admin_token, response.url)
        self.assertNotEqual(self.client.session['demo_club_id'], real.id)
        page = self.client.get(reverse('tennis:club_home', args=[real.public_token]))
        self.assertNotContains(page, '?mode=admin')
        self.assertNotContains(page, real.admin_token)

    def test_other_visitor_does_not_receive_existing_demo_admin_url(self):
        from django.test import Client
        self.client.get(reverse('tennis:demo'))
        club = Club.objects.get(pk=self.client.session['demo_club_id'])
        other = Client()
        page = other.get(reverse('tennis:club_home', args=[club.public_token]))
        self.assertNotContains(page, '?mode=admin')
        response = other.get(reverse('tennis:demo'), {'mode': 'admin'})
        self.assertNotIn(club.admin_token, response.url)

    def test_demo_email_and_url_reset_are_blocked_before_mutation(self):
        from unittest.mock import patch
        from tennis.models import ClubOrganizer
        club = make_club()
        club.is_demo = True
        club.save()
        member = make_member(club, 'デモ幹事', member_no=1)
        data = {'club_id': club.id, 'admin_token': club.admin_token, 'member_id': member.id,
                'email': 'demo@example.com', 'display_name': 'デモ幹事', 'reset_kind': 'public'}
        with patch('tennis.organizer_email.send_mail') as send:
            for name in ('organizer_set_email', 'organizer_resend_confirmation', 'organizer_self_register', 'club_reset_url'):
                with self.subTest(name=name):
                    response = self.client.post(reverse('tennis:' + name), data)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()['error'], 'demo_disabled')
            send.assert_not_called()
        original = club.public_token
        club.refresh_from_db()
        self.assertEqual(club.public_token, original)
        self.assertFalse(ClubOrganizer.objects.filter(club=club).exists())
