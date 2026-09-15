import datetime

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tennis.models import Club


class ClubLastAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.club = Club.objects.create(name="アクセス確認クラブ")

    def test_public_club_page_records_last_access(self):
        response = self.client.get(
            reverse("tennis:club_home", args=[self.club.public_token])
        )

        self.assertEqual(response.status_code, 200)
        self.club.refresh_from_db()
        self.assertIsNotNone(self.club.last_accessed_at)
        self.assertLess(timezone.now() - self.club.last_accessed_at, datetime.timedelta(seconds=5))

    def test_admin_club_page_records_last_access(self):
        response = self.client.get(
            reverse(
                "tennis:club_settings",
                args=[self.club.admin_path_token, self.club.admin_token],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.club.refresh_from_db()
        self.assertIsNotNone(self.club.last_accessed_at)

    def test_repeated_access_within_five_minutes_does_not_write_again(self):
        url = reverse("tennis:club_home", args=[self.club.public_token])
        self.client.get(url)
        fixed_time = timezone.now() - datetime.timedelta(days=1)
        Club.objects.filter(pk=self.club.pk).update(last_accessed_at=fixed_time)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.club.refresh_from_db()
        self.assertEqual(self.club.last_accessed_at, fixed_time)

    def test_invalid_club_url_does_not_change_another_club(self):
        before = timezone.now() - datetime.timedelta(days=1)
        Club.objects.filter(pk=self.club.pk).update(last_accessed_at=before)

        response = self.client.get(
            reverse("tennis:club_home", args=["0" * 32])
        )

        self.assertEqual(response.status_code, 404)
        self.club.refresh_from_db()
        self.assertEqual(self.club.last_accessed_at, before)
