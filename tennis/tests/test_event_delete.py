"""
イベント削除 API（club_delete_event）の成功シナリオと CASCADE 退行検知。
認可エラーは test_admin_auth.py 側で担保。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis.models import (
    Event,
    EventDisplaySetting,
    EventFlagDefinition,
    EventParticipant,
    MatchSchedule,
    MatchScore,
    ParticipantFlag,
)

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
class DeleteEventSuccessTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.event = make_event(self.club, date=datetime.date(2026, 4, 1))
        self.a = make_member(self.club, "A", member_no=1)
        self.b = make_member(self.club, "B", member_no=2)
        self.ep_a = make_ep(self.event, member=self.a, attendance="yes")
        self.ep_b = make_ep(self.event, member=self.b, attendance="yes")

        # 関連レコードを十分作って、CASCADE で全部消えることを担保
        EventDisplaySetting.objects.create(event=self.event)
        EventFlagDefinition.objects.create(
            event=self.event, name="testflag", display_order=1
        )
        ms = make_published_schedule(
            self.event,
            [{"round": 1, "matches": [{"court": 1, "team1": [self.ep_a.id], "team2": [self.ep_b.id]}], "rests": []}],
            game_type="singles", court_count=1, round_count=1,
        )
        make_score(ms, 1, 1, 6, 0)

        self.url = reverse("tennis:club_delete_event")

    def _post(self, **overrides):
        body = {
            "event_id": str(self.event.id),
            "admin_token": self.club.admin_token,
        }
        body.update(overrides)
        return self.client.post(self.url, body)

    def test_delete_with_valid_admin_token_returns_ok(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertFalse(Event.objects.filter(id=self.event.id).exists())

    def test_delete_cascades_related_rows(self):
        ev_id = self.event.id

        # 削除前は存在
        self.assertTrue(EventParticipant.objects.filter(event_id=ev_id).exists())
        self.assertTrue(EventDisplaySetting.objects.filter(event_id=ev_id).exists())
        self.assertTrue(EventFlagDefinition.objects.filter(event_id=ev_id).exists())
        self.assertTrue(MatchSchedule.objects.filter(event_id=ev_id).exists())
        self.assertTrue(MatchScore.objects.filter(match_schedule__event_id=ev_id).exists())

        self._post()

        # 削除後はすべて消えている
        self.assertFalse(Event.objects.filter(id=ev_id).exists())
        self.assertFalse(EventParticipant.objects.filter(event_id=ev_id).exists())
        self.assertFalse(EventDisplaySetting.objects.filter(event_id=ev_id).exists())
        self.assertFalse(EventFlagDefinition.objects.filter(event_id=ev_id).exists())
        self.assertFalse(MatchSchedule.objects.filter(event_id=ev_id).exists())
        self.assertFalse(MatchScore.objects.filter(match_schedule__event_id=ev_id).exists())
        # ParticipantFlag 経路（EP 経由）も消える
        self.assertFalse(ParticipantFlag.objects.filter(event_participant__event_id=ev_id).exists())

    def test_delete_missing_event_id_returns_400(self):
        resp = self.client.post(self.url, {"admin_token": self.club.admin_token})
        self.assertEqual(resp.status_code, 400)

    def test_delete_unknown_event_returns_404(self):
        resp = self.client.post(
            self.url,
            {"event_id": "99999999", "admin_token": self.club.admin_token},
        )
        self.assertEqual(resp.status_code, 404)
