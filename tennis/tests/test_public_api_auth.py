"""公開APIのクラブ越境防止テスト。"""
from __future__ import annotations

import datetime
import json

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import EventDisplaySetting

from .factories import make_club, make_club_flag, make_ep, make_event, make_member


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class PublicApiAuthorizationTests(TestCase):
    def setUp(self):
        future = timezone.localdate() + datetime.timedelta(days=7)
        self.club = make_club(name="対象クラブ")
        self.event = make_event(self.club, date=future)
        self.member = make_member(self.club, "対象メンバー", member_no=1)
        self.ep = make_ep(self.event, member=self.member, attendance=None)
        self.flag = make_club_flag(self.club, "球数", 1, input_mode="digit")

        self.other_club = make_club(name="別クラブ")
        self.other_event = make_event(self.other_club, date=future)

    def _event_url(self, club=None, event=None):
        club = club or self.club
        event = event or self.event
        return reverse("tennis:event_public", args=[club.public_token, event.id])

    @staticmethod
    def _csrf_post(client, url, data):
        token = client.cookies["csrftoken"].value
        return client.post(url, data, HTTP_X_CSRFTOKEN=token)

    def test_csrf_valid_other_club_session_cannot_update_target_club(self):
        attacker = Client(enforce_csrf_checks=True)
        response = attacker.get(self._event_url(self.other_club, self.other_event))
        self.assertEqual(response.status_code, 200)

        response = self._csrf_post(
            attacker,
            reverse("tennis:update_attendance"),
            {"event_id": self.event.id, "ep_id": self.ep.id, "attendance": "yes"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "club_access_required")
        self.ep.refresh_from_db()
        self.assertIsNone(self.ep.attendance)

    def test_csrf_valid_target_club_session_can_update(self):
        member = Client(enforce_csrf_checks=True)
        response = member.get(self._event_url())
        self.assertEqual(response.status_code, 200)

        response = self._csrf_post(
            member,
            reverse("tennis:update_attendance"),
            {"event_id": self.event.id, "ep_id": self.ep.id, "attendance": "yes"},
        )

        self.assertEqual(response.status_code, 200)
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "yes")

    def test_public_write_endpoints_reject_direct_id_only_requests(self):
        endpoints = [
            ("tennis:update_attendance", {
                "event_id": self.event.id, "ep_id": self.ep.id, "attendance": "yes",
            }),
            ("tennis:update_comment", {
                "event_id": self.event.id, "ep_id": self.ep.id, "comment": "書換",
            }),
            ("tennis:update_participant_display_name", {
                "event_id": self.event.id, "ep_id": self.ep.id, "display_name": "書換",
            }),
            ("tennis:update_member_display_name", {
                "club_id": self.club.id, "member_id": self.member.id, "display_name": "書換",
            }),
            ("tennis:set_participates_match", {
                "event_id": self.event.id, "ep_id": self.ep.id, "checked": "1",
            }),
            ("tennis:toggle_participant_flag", {
                "event_id": self.event.id, "ep_id": self.ep.id,
                "flag_id": self.flag.id, "checked": "1", "flag_scope": "club",
            }),
            ("tennis:set_participant_flag_value", {
                "event_id": self.event.id, "ep_id": self.ep.id,
                "flag_id": self.flag.id, "value": "3", "flag_scope": "club",
            }),
            ("tennis:add_guest_participant", {
                "event_id": self.event.id, "display_name": "侵入者",
            }),
            ("tennis:save_match_score", {
                "event_id": self.event.id, "round_no": "1", "court_no": "1",
                "side": "a", "value": "6",
            }),
            ("tennis:substitute_slot", {
                "event_id": self.event.id, "round_no": "1", "court_no": "1",
                "team": "1", "slot_index": "0", "new_ep_id": self.ep.id,
            }),
        ]

        for url_name, data in endpoints:
            with self.subTest(url_name=url_name):
                response = self.client.post(reverse(url_name), data)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"], "club_access_required")

        self.member.refresh_from_db()
        self.ep.refresh_from_db()
        self.assertEqual(self.member.display_name, "対象メンバー")
        self.assertIsNone(self.ep.attendance)
        self.assertEqual(self.ep.comment, "")

    def test_member_detail_public_url_authorizes_member_name_update(self):
        detail_url = reverse(
            "tennis:member_detail", args=[self.club.public_token, self.member.id]
        )
        self.assertEqual(self.client.get(detail_url).status_code, 200)

        response = self.client.post(
            reverse("tennis:update_member_display_name"),
            {
                "club_id": self.club.id,
                "member_id": self.member.id,
                "display_name": "変更後",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, "変更後")

    def test_public_text_inputs_have_server_side_limits(self):
        self.client.get(self._event_url())

        response = self.client.post(
            reverse("tennis:update_comment"),
            {"event_id": self.event.id, "ep_id": self.ep.id, "comment": "あ" * 501},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "comment_too_long")

        response = self.client.post(
            reverse("tennis:add_guest_participant"),
            {"event_id": self.event.id, "display_name": "名" * 101},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "name_too_long")

        self.ep.refresh_from_db()
        self.assertEqual(self.ep.comment, "")

    def test_event_display_setting_requires_admin_session(self):
        self.client.get(self._event_url())
        payload = {
            "event_id": self.event.id,
            "settings_json": json.dumps({
                "common_flags": True,
                "event_flags": True,
                "class": True,
                "schedule": True,
            }),
        }

        response = self.client.post(reverse("tennis:save_event_display_setting"), payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "admin_only")
        self.assertFalse(EventDisplaySetting.objects.filter(event=self.event).exists())

        admin_url = reverse(
            "tennis:event_admin",
            args=[self.club.public_token, self.club.admin_token, self.event.id],
        )
        self.assertEqual(self.client.get(admin_url).status_code, 200)
        response = self.client.post(reverse("tennis:save_event_display_setting"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EventDisplaySetting.objects.filter(event=self.event).exists())
