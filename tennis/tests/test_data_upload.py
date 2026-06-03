"""
データ集計表アップロード（縦持ち long 形式・差分プレビュー→確定→反映）のテスト。
ダウンロード→編集→アップロードの往復を実ファイルで検証する。
"""
from __future__ import annotations

import datetime
import io

from django.test import TestCase, override_settings
from django.urls import reverse

from openpyxl import load_workbook

from tennis.models import ParticipantFlag

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

PERIOD = {"start": "2026-05-01", "end": "2026-05-31"}


@_NO_MANIFEST_STORAGES
class DataUploadRoundTripTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.ev = make_event(self.club, date=datetime.date(2026, 5, 1), title="練習")
        self.m = make_member(self.club, "山田", member_no=1)
        self.ep = make_ep(self.ev, member=self.m, attendance="yes")
        self.flag = make_club_flag(self.club, "車", 1)

    def _download_xlsx(self):
        url = reverse("tennis:club_data_download", args=[self.club.public_token, self.club.admin_token])
        resp = self.client.get(url, {**PERIOD, "format": "xlsx"})
        self.assertEqual(resp.status_code, 200)
        return load_workbook(io.BytesIO(resp.content))

    def _set_value(self, wb, row_key, item, new_value):
        """データシートで (row_key, item) の行の『値』列(7)を書き換える。"""
        ws = wb["データ"]
        for r in range(2, ws.max_row + 1):
            if ws.cell(row=r, column=1).value == row_key and ws.cell(row=r, column=5).value == item:
                ws.cell(row=r, column=7).value = new_value
                return
        raise AssertionError(f"row not found: {row_key} {item}")

    def _to_bytes(self, wb):
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _upload(self, content, name="edit.xlsx"):
        url = reverse("tennis:club_data_upload", args=[self.club.public_token, self.club.admin_token])
        f = io.BytesIO(content)
        f.name = name
        return self.client.post(url, {"file": f})

    def _apply(self):
        url = reverse("tennis:club_data_apply", args=[self.club.public_token, self.club.admin_token])
        return self.client.post(url, {})

    def test_attendance_round_trip(self):
        wb = self._download_xlsx()
        self._set_value(wb, f"m:{self.m.id}", "attendance", "不参加")
        resp = self._upload(self._to_bytes(wb))
        result = resp.context["result"]
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["new_code"], "no")
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "yes")  # まだ未反映
        self._apply()
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "no")

    def test_flag_round_trip(self):
        wb = self._download_xlsx()
        self._set_value(wb, f"m:{self.m.id}", f"clubflag:{self.flag.id}", "✓")
        resp = self._upload(self._to_bytes(wb))
        self.assertEqual(resp.context["result"]["errors"], [])
        self.assertEqual(len(resp.context["result"]["changes"]), 1)
        self._apply()
        pf = ParticipantFlag.objects.get(event_participant=self.ep, club_flag_definition=self.flag)
        self.assertTrue(pf.is_on)

    def test_bad_value_blocks_apply(self):
        wb = self._download_xlsx()
        self._set_value(wb, f"m:{self.m.id}", "attendance", "出る")
        resp = self._upload(self._to_bytes(wb))
        self.assertTrue(resp.context["result"]["errors"])
        self.assertFalse(resp.context["can_apply"])
        self._apply()
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "yes")

    def test_wrong_club_file_rejected(self):
        other = make_club()
        wb = self._download_xlsx()
        meta = wb["メタ"]
        for r in range(1, meta.max_row + 1):
            if meta.cell(row=r, column=1).value == "club_id":
                meta.cell(row=r, column=2).value = str(other.id)
        resp = self._upload(self._to_bytes(wb))
        self.assertTrue(resp.context["result"]["errors"])

    def test_snapshot_mismatch_blocks_apply(self):
        wb = self._download_xlsx()
        self._set_value(wb, f"m:{self.m.id}", "attendance", "不参加")
        self._upload(self._to_bytes(wb))
        self.ep.attendance = "maybe"
        self.ep.save(update_fields=["attendance", "updated_at"])
        resp = self._apply()
        self.assertIn("再ダウンロード", resp.context["error"])
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.attendance, "maybe")

    def test_non_xlsx_garbage_is_parse_error(self):
        resp = self._upload(b"not a real file", name="x.xlsx")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["error"])
