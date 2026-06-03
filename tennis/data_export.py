"""
データ集計表の Excel(.xlsx) / CSV束(ZIP) 出力 — 縦持ち(long)1枚形式。

1件＝1行（誰が・どのイベントで・何が・どうだったか）を1シートに積む。
並べ替え・フィルタ・検索置換で一括修正しやすい。アップロード時に機械可読で
同定できるよう、機械列（row_key / event / item）と人間列を併記する。

列: row_key, 名前, event, イベント, item, 項目, 値
  row_key : メンバー=`m:<member_id>` / ゲスト=`g:<display_name>`
  event   : `event:<event_id>`
  item    : `attendance` / `clubflag:<flag_id>` / `eventflag:<flag_id>`
  値      : 出欠=参加/不参加/未定/空、フラグ=✓/空 または 0-9（ここだけ編集する）
"""
from __future__ import annotations

import csv
import io
import zipfile

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

FORMAT_VERSION = "2"

# 出欠コード ↔ 日本語ラベル（人間が編集しやすいよう日本語で出す）
ATT_CODE_TO_JP = {"yes": "参加", "no": "不参加", "maybe": "未定", None: ""}
ATT_JP_TO_CODE = {"参加": "yes", "不参加": "no", "未定": "maybe", "": None}

# 縦持ちシートの列（機械列は Excel で隠す）
LONG_HEADER = ["row_key", "名前", "event", "イベント", "item", "項目", "値"]
HIDDEN_COLS = (1, 3, 5)  # row_key(A), event(C), item(E) を隠す


def _row_key(row):
    if row.get("member_id"):
        return f"m:{row['member_id']}"
    return f"g:{row['display_name']}"


def _event_label(ev):
    label = ev.date.strftime("%-m/%-d")
    if ev.title:
        label += f" {ev.title}"
    return label


def build_long_rows(data):
    """build_club_data_matrices の結果を縦持ち行のリストに変換する。"""
    events = data["events"]
    rows = []

    # 出欠
    for r in data["attendance_table"]:
        rk = _row_key(r["row"])
        name = r["row"]["display_name"]
        for ev, cell in zip(events, r["cells"]):
            rows.append([rk, name, f"event:{ev.id}", _event_label(ev),
                         "attendance", "出欠", ATT_CODE_TO_JP.get(cell["attendance"], "")])

    # 共通フラグ
    for t in data["club_flag_tables"]:
        f = t["flag"]
        for r in t["rows"]:
            rk = _row_key(r["row"])
            name = r["row"]["display_name"]
            for ev, cell in zip(events, r["cells"]):
                rows.append([rk, name, f"event:{ev.id}", _event_label(ev),
                             f"clubflag:{f.id}", f"フラグ:{f.name}", cell["text"]])

    # 固有フラグ（イベントごと・列=フラグ）
    for blk in data["event_flag_blocks"]:
        ev = blk["event"]
        flags = blk["flags"]
        for r in blk["rows"]:
            rk = _row_key(r["row"])
            name = r["row"]["display_name"]
            for f, cell in zip(flags, r["cells"]):
                rows.append([rk, name, f"event:{ev.id}", _event_label(ev),
                             f"eventflag:{f.id}", f"固有:{f.name}", cell["text"]])

    return rows


def _meta_rows(club, start_d, end_d, generated_at, snapshot_token):
    return [
        ["format_version", FORMAT_VERSION],
        ["club_id", str(club.id)],
        ["club_name", club.name],
        ["period_start", start_d.isoformat()],
        ["period_end", end_d.isoformat()],
        ["generated_at", generated_at],
        ["snapshot_token", snapshot_token],
    ]


def build_workbook(club, start_d, end_d, data, generated_at):
    wb = Workbook()
    meta_ws = wb.active
    meta_ws.title = "メタ"
    for row in _meta_rows(club, start_d, end_d, generated_at, data["snapshot_token"]):
        meta_ws.append(row)

    ws = wb.create_sheet(title="データ")
    ws.append(LONG_HEADER)
    for r in build_long_rows(data):
        ws.append(r)
    for ci in HIDDEN_COLS:
        ws.column_dimensions[get_column_letter(ci)].hidden = True
    ws.column_dimensions[get_column_letter(2)].width = 14   # 名前
    ws.column_dimensions[get_column_letter(4)].width = 16   # イベント
    ws.column_dimensions[get_column_letter(6)].width = 14   # 項目
    ws.column_dimensions[get_column_letter(7)].width = 10   # 値
    ws.freeze_panes = "A2"
    return wb


def workbook_bytes(club, start_d, end_d, data, generated_at):
    buf = io.BytesIO()
    build_workbook(club, start_d, end_d, data, generated_at).save(buf)
    return buf.getvalue()


def csv_zip_bytes(club, start_d, end_d, data, generated_at):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        meta_io = io.StringIO()
        w = csv.writer(meta_io)
        for row in _meta_rows(club, start_d, end_d, generated_at, data["snapshot_token"]):
            w.writerow(row)
        zf.writestr("00_meta.csv", "﻿" + meta_io.getvalue())

        data_io = io.StringIO()
        w = csv.writer(data_io)
        w.writerow(LONG_HEADER)
        for r in build_long_rows(data):
            w.writerow(r)
        zf.writestr("01_データ.csv", "﻿" + data_io.getvalue())
    return buf.getvalue()
