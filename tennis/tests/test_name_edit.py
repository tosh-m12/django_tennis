"""
イベントページからの表示名編集（tennis.views.update_participant_display_name）のテスト。

仕様（ユーザー合意）：
  - 固定メンバー: Member.display_name を更新し、全 EventParticipant に伝播（クラブ全体反映）
  - ゲスト(member無し): その EventParticipant.display_name のみ更新
  - EP未作成の固定メンバー: member_id 指定で EP を作って更新
  - 一般/幹事どちらも可。公開後/終了後でも編集可（ガードしない）
"""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tennis.models import EventParticipant, Member

from .factories import (
    make_club,
    make_event,
    make_member,
    make_ep,
    make_published_schedule,
    set_member_session,
)


class UpdateParticipantNameTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.future = timezone.localdate() + datetime.timedelta(days=7)
        self.event = make_event(self.club, date=self.future)
        self.other_event = make_event(self.club, date=self.future + datetime.timedelta(days=1))
        self.url = reverse("tennis:update_participant_display_name")

        self.member = make_member(self.club, "旧名", member_no=1)
        self.ep = make_ep(self.event, member=self.member, attendance="yes")
        # 同じメンバーの別イベント参加（伝播確認用）
        self.ep_other = make_ep(self.other_event, member=self.member, attendance="yes")
        set_member_session(self.client, self.club.id)

    def test_fixed_member_rename_propagates_clubwide(self):
        resp = self.client.post(self.url, {
            "event_id": self.event.id, "ep_id": self.ep.id, "display_name": "新名",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["display_name"], "新名")

        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, "新名")
        # 同メンバーの全EP（別イベント含む）に伝播
        self.ep.refresh_from_db()
        self.ep_other.refresh_from_db()
        self.assertEqual(self.ep.display_name, "新名")
        self.assertEqual(self.ep_other.display_name, "新名")

    def test_rename_by_member_id_creates_ep_when_unregistered(self):
        # EP を持たない固定メンバー（未登録行）→ member_id 指定で EP 作成＋更新
        m2 = make_member(self.club, "未登録さん", member_no=2)
        self.assertFalse(EventParticipant.objects.filter(event=self.event, member=m2).exists())

        resp = self.client.post(self.url, {
            "event_id": self.event.id, "member_id": m2.id, "display_name": "登録名",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(EventParticipant.objects.filter(event=self.event, member=m2).exists())
        m2.refresh_from_db()
        self.assertEqual(m2.display_name, "登録名")

    def test_guest_rename_event_scoped_only(self):
        guest = make_ep(self.event, display_name="ゲスト旧", attendance="yes")
        resp = self.client.post(self.url, {
            "event_id": self.event.id, "ep_id": guest.id, "display_name": "ゲスト新",
        })
        self.assertEqual(resp.status_code, 200)
        guest.refresh_from_db()
        self.assertEqual(guest.display_name, "ゲスト新")
        self.assertIsNone(guest.member_id)
        # メンバーは作られない
        self.assertFalse(Member.objects.filter(club=self.club, display_name="ゲスト新").exists())

    def test_empty_name_rejected(self):
        resp = self.client.post(self.url, {
            "event_id": self.event.id, "ep_id": self.ep.id, "display_name": "   ",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "empty_name")

    def test_missing_target_rejected(self):
        resp = self.client.post(self.url, {"event_id": self.event.id, "display_name": "X"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "missing_target")

    def test_editable_even_when_published(self):
        # 公開済みでも一般ユーザー（adminセッション無し）が編集可能
        make_published_schedule(self.event, [], game_type="doubles")
        resp = self.client.post(self.url, {
            "event_id": self.event.id, "ep_id": self.ep.id, "display_name": "公開後でも変更",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, "公開後でも変更")

    def test_get_not_allowed(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)
