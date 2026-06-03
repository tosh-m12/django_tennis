"""
フラグ整理（リネーム・削除・統合）のテスト。
"""
from __future__ import annotations

import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis import data_cleanup
from tennis.models import ClubFlagDefinition, ParticipantFlag

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_club_flag,
    make_participant_flag,
)

_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class FlagCleanupServiceTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.e1 = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.e2 = make_event(self.club, date=datetime.date(2026, 5, 8))
        self.m1 = make_member(self.club, "A", member_no=1)
        self.m2 = make_member(self.club, "B", member_no=2)
        # 重複フラグ：車 / 車あり（同じ意味）。check モード。
        self.car = make_club_flag(self.club, "車", 1)
        self.car2 = make_club_flag(self.club, "車あり", 2)
        # 記録：car は m1@e1, m2@e2。car2 は m1@e1（競合）, m2@e1。
        self.ep_m1_e1 = make_ep(self.e1, member=self.m1, attendance="yes")
        self.ep_m2_e1 = make_ep(self.e1, member=self.m2, attendance="yes")
        self.ep_m2_e2 = make_ep(self.e2, member=self.m2, attendance="yes")
        make_participant_flag(self.ep_m1_e1, club_flag=self.car, is_on=True)
        make_participant_flag(self.ep_m2_e2, club_flag=self.car, is_on=True)
        make_participant_flag(self.ep_m1_e1, club_flag=self.car2, is_on=True)  # 競合
        make_participant_flag(self.ep_m2_e1, club_flag=self.car2, is_on=True)

    def test_summaries_usage(self):
        rows = {r["name"]: r for r in data_cleanup.flag_summaries(self.club)}
        self.assertEqual(rows["車"]["usage"], 2)
        self.assertEqual(rows["車あり"]["usage"], 2)

    def test_rename(self):
        data_cleanup.rename_flag(self.club, f"club:{self.car.id}", "クルマ")
        self.car.refresh_from_db()
        self.assertEqual(self.car.name, "クルマ")

    def test_merge_preview_and_apply(self):
        src = f"club:{self.car2.id}"
        tgt = f"club:{self.car.id}"
        pre = data_cleanup.preview_flag_merge(self.club, src, tgt)
        self.assertEqual(pre["errors"], [])
        self.assertEqual(pre["moves"], 1)      # m2@e1 は car に無い → 移動
        self.assertEqual(pre["conflicts"], 1)  # m1@e1 は両方 → まとめる

        data_cleanup.apply_flag_merge(self.club, src, tgt)
        # car2 は削除
        self.assertFalse(ClubFlagDefinition.objects.filter(id=self.car2.id).exists())
        # car の記録は m1@e1, m2@e2, m2@e1 の3件
        eps = set(ParticipantFlag.objects.filter(club_flag_definition=self.car)
                  .values_list("event_participant_id", flat=True))
        self.assertEqual(eps, {self.ep_m1_e1.id, self.ep_m2_e2.id, self.ep_m2_e1.id})

    def test_merge_different_mode_rejected(self):
        digit = make_club_flag(self.club, "回数", 3, input_mode="digit")
        res = data_cleanup.preview_flag_merge(self.club, f"club:{digit.id}", f"club:{self.car.id}")
        self.assertTrue(res["errors"])

    def test_delete(self):
        n = data_cleanup.apply_flag_delete(self.club, f"club:{self.car.id}")
        self.assertEqual(n, 2)
        self.assertFalse(ClubFlagDefinition.objects.filter(id=self.car.id).exists())


@_NO_MANIFEST_STORAGES
class FlagCleanupViewTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.e1 = make_event(self.club, date=datetime.date(2026, 5, 1))
        self.m1 = make_member(self.club, "A", member_no=1)
        self.ep = make_ep(self.e1, member=self.m1, attendance="yes")
        self.car = make_club_flag(self.club, "車", 1)
        self.car2 = make_club_flag(self.club, "車あり", 2)
        make_participant_flag(self.ep, club_flag=self.car2, is_on=True)

    def _url(self, name):
        return reverse(name, args=[self.club.public_token, self.club.admin_token])

    def test_page_renders(self):
        resp = self.client.get(self._url("tennis:club_flag_cleanup"))
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.context["rows"]]
        self.assertIn("車", names)
        self.assertIn("車あり", names)

    def test_merge_flow(self):
        resp = self.client.post(self._url("tennis:club_flag_merge_preview"), {
            "source_key": f"club:{self.car2.id}", "target_key": f"club:{self.car.id}",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["result"]["moves"], 1)
        resp2 = self.client.post(self._url("tennis:club_flag_merge_apply"), {})
        self.assertEqual(resp2.status_code, 302)
        self.assertFalse(ClubFlagDefinition.objects.filter(id=self.car2.id).exists())
        self.assertTrue(ParticipantFlag.objects.filter(event_participant=self.ep, club_flag_definition=self.car).exists())

    def test_admin_token_required(self):
        url = reverse("tennis:club_flag_cleanup", args=[self.club.public_token, "wrong"])
        self.assertEqual(self.client.get(url).status_code, 400)
