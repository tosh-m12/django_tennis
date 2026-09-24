import json
import re
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from tennis.models import Club, ClubOrganizer, ClubAcquisition
from tennis import analytics, organizer_email
from .factories import make_club, make_member


@override_settings(GA4_MEASUREMENT_ID="G-TEST123456", GA4_HOSTS=["testserver"],
                   ALLOWED_HOSTS=["testserver"], ORIGIN_VERIFY_ENABLED=False,
                   CANONICAL_HOST="", TURNSTILE_ENABLED=False, APP_RATE_LIMIT_ENABLED=False,
                   STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AnalyticsTests(TestCase):
    def config(self, response):
        found = re.search(r'<script id="analytics-config" type="application/json">(.*?)</script>', response.content.decode(), re.S)
        return json.loads(found.group(1)) if found else None

    def test_home_strips_queries_and_referrer_details(self):
        response = self.client.get('/?email=private@example.com', HTTP_REFERER='https://www.google.com/search?q=private@example.com')
        config = self.config(response)
        self.assertEqual(config, {"page": "/", "referrer": "https://google.com/", "events": []})
        self.assertNotContains(response, 'googletagmanager.com')
        response = self.client.get('/', HTTP_REFERER='https://deucenet.app/c/secret/private-token/')
        self.assertEqual(self.config(response)['referrer'], '')

    @override_settings(GA4_HOSTS=["deucenet.app"])
    def test_other_hosts_never_send(self):
        self.assertIsNone(self.config(self.client.get('/')))
        self.assertEqual(self.client.get('/analytics/frame/').status_code, 204)

    def test_frame_contains_no_referrer_or_user_data(self):
        response = self.client.get('/analytics/frame/?secret=private', HTTP_REFERER='https://deucenet.app/c/private/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertNotContains(response, 'private')
        self.assertContains(response, 'G-TEST123456')

    def test_demo_counts_success_once_per_mode_not_gate_or_refresh(self):
        with self.settings(TURNSTILE_ENABLED=True):
            self.assertEqual(self.client.get('/demo?mode=admin').status_code, 200)
            self.assertNotIn(analytics.QUEUE, self.client.session)
        for mode in ['admin', 'member']:
            response = self.client.get('/demo?mode=' + mode, follow=True)
            self.assertEqual(self.config(response)['events'], [{'name': 'demo_start', 'mode': mode}])
            self.assertIsNone(self.config(self.client.get('/demo?mode=' + mode, follow=True)))

    def register(self):
        self.client.cookies['_ga'] = 'GA1.1.123456789.987654321'
        with patch.object(organizer_email, 'delivery_enabled', return_value=True), patch.object(organizer_email, 'send_confirmation_email'), patch.object(organizer_email, 'throttle_ok', return_value=True):
            response = self.client.post('/', {'club_name': 'private club', 'display_name': 'private person', 'email': 'private@example.com'}, follow=True)
        self.assertEqual(self.config(response)['events'], [{'name': 'registration_email_sent'}])
        self.assertEqual(self.config(self.client.get('/'))['events'], [])
        return ClubOrganizer.objects.get(email='private@example.com')

    def test_confirmation_once_across_devices_and_email_changes(self):
        org = self.register()
        other = Client()
        data = {'oid': org.pk, 'email': org.email}
        url = reverse('tennis:verify_email', args=['test-token'])
        with patch.object(organizer_email, 'read_confirm_token', return_value=(data, None)):
            response = other.get(url)
            self.assertEqual(self.config(response)['events'], [{'name': 'sign_up', 'client_id': '123456789.987654321'}])
            self.assertIsNone(self.config(other.get(url)))
        org.refresh_from_db()
        org.pending_email = 'new@example.com'
        org.save()
        with patch.object(organizer_email, 'read_confirm_token', return_value=({'oid': org.pk, 'email': 'new@example.com'}, None)):
            self.assertIsNone(self.config(other.get(url)))

    def test_existing_organizer_confirmation_is_not_signup(self):
        club = make_club()
        org = ClubOrganizer.objects.create(club=club, member=make_member(club, 'owner'), email='existing@example.com')
        with patch.object(organizer_email, 'read_confirm_token', return_value=({'oid': org.pk, 'email': org.email}, None)):
            self.assertIsNone(self.config(self.client.get(reverse('tennis:verify_email', args=['token']))))

    def test_failed_confirmation_is_not_signup(self):
        with patch.object(organizer_email, 'read_confirm_token', return_value=(None, 'expired')):
            self.assertIsNone(self.config(self.client.get(reverse('tennis:verify_email', args=['token']))))

    def test_first_event_is_counted_only_once(self):
        org = self.register()
        club = org.club
        url = reverse('tennis:club_create_event')
        data = {'club_id': club.pk, 'admin_token': club.admin_token, 'date': '2026-10-01'}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(self.client.session[analytics.QUEUE][0]['name'], 'first_event_created')
        session = self.client.session
        session.pop(analytics.QUEUE)
        session.save()
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertNotIn(analytics.QUEUE, self.client.session)
        self.assertIsNotNone(ClubAcquisition.objects.get(club=club).first_event_at)
