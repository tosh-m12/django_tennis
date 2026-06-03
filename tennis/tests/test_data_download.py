"""
データ集計表のダウンロード（Excel/CSV）のテスト。
"""
from __future__ import annotations

import datetime
import io
import zipfile

from django.test import TestCase, override_settings
from django.urls import reverse

from openpyxl import load_workbook

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
class DataDownloadTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.ev = make_event(self.club, date=datetime.date(2026, 5, 1), title="練習会")
        self.m = make_member(self.club, "山田", member_no=1)
        self.ep = make_ep(self.ev, member=self.m, attendance="yes")
        self.flag = make_club_flag(self.club, "車", 1)
        make_participant_flag(self.ep, club_flag=self.flag, is_on=True)
        self.params = {"start": "2026-05-01", "end": "2026-05-31"}

    def _url(self, fmt):
        url = reverse("tennis:club_data_download", args=[self.club.public_token, self.club.admin_token])
        return url, {**self.params, "format": fmt}

    def test_admin_token_required(self):
        url = reverse("tennis:club_data_download", args=[self.club.public_token, "wrong"])
        self.assertEqual(self.client.get(url, self.params).status_code, 400)

    def test_xlsx_download(self):
        url, p = self._url("xlsx")
        resp = self.client.get(url, p)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        self.assertIn(".xlsx", resp["Content-Disposition"])
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertIn("メタ", wb.sheetnames)
        self.assertIn("出欠", wb.sheetnames)
        # 出欠シート：機械ヘッダに row_key と event:<id>、データに 参加
        ws = wb["出欠"]
        machine = [c.value for c in ws[1]]
        self.assertEqual(machine[0], "__rowkey__")
        self.assertIn(f"event:{self.ev.id}", machine)
        # 山田の行（m:<id>）に「参加」
        body = [[c.value for c in row] for row in ws.iter_rows(min_row=3)]
        yamada = next(r for r in body if r[0] == f"m:{self.m.id}")
        self.assertEqual(yamada[1], "山田")
        self.assertEqual(yamada[2], "参加")
        # 共通フラグシートがある
        self.assertTrue(any(n.startswith("共通_") for n in wb.sheetnames))

    def test_csv_zip_download(self):
        url, p = self._url("csv")
        resp = self.client.get(url, p)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        self.assertIn("00_meta.csv", names)
        self.assertTrue(any("出欠" in n for n in names))
        meta = zf.read("00_meta.csv").decode("utf-8")
        self.assertIn("snapshot_token", meta)
        self.assertIn(str(self.club.id), meta)

    def test_snapshot_token_changes_when_data_changes(self):
        from tennis.views import build_club_data_matrices
        t1 = build_club_data_matrices(
            self.club, datetime.date(2026, 5, 1), datetime.date(2026, 5, 31)
        )["snapshot_token"]
        self.ep.attendance = "no"
        self.ep.save(update_fields=["attendance", "updated_at"])
        t2 = build_club_data_matrices(
            self.club, datetime.date(2026, 5, 1), datetime.date(2026, 5, 31)
        )["snapshot_token"]
        self.assertNotEqual(t1, t2)
