"""
アプリ内データクレンジング（フェーズ2）：メンバーの統合（名寄せ）と完全削除。

安全方針:
- 変更は transaction.atomic で一括（部分適用なし）。
- 適用前の対象データを AuditLog.payload_json にスナップショットとして残す（手動復元の材料）。
- 統合は識別子の付け替えで実現（出欠・フラグ・対戦表 schedule_json/draft_json を寄せる）。
- 完全削除は物理削除（EP も削除＝過去の出欠/フラグも消える）。対戦表からは ep_id を除去。
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Max

from .models import (
    Member,
    Event,
    EventParticipant,
    ParticipantFlag,
    ClubFlagDefinition,
    EventFlagDefinition,
    MatchSchedule,
    MatchScheduleDraft,
    AuditLog,
)

# 出欠の強さ（統合の競合解決：強い方を採用）
ATT_PRIORITY = {"yes": 3, "maybe": 2, "no": 1, None: 0, "": 0}


def _stronger_attendance(a, b):
    return a if ATT_PRIORITY.get(a or None, 0) >= ATT_PRIORITY.get(b or None, 0) else b


# ============================================================
# 一覧（記録件数つき）
# ============================================================

def member_summaries(club):
    """
    メンバー＋ゲストの一覧を記録件数つきで返す。クレンジング画面用。
    各要素: key, kind('member'|'guest'), member_id, display_name, is_fixed, member_no,
            ep_count, flag_count, last_date, has_match_history
    """
    eps = list(
        EventParticipant.objects.filter(event__club=club).select_related("event")
    )
    ep_ids = [ep.id for ep in eps]

    flag_by_ep = {}
    if ep_ids:
        for ep_id in ParticipantFlag.objects.filter(
            event_participant_id__in=ep_ids
        ).values_list("event_participant_id", flat=True):
            flag_by_ep[ep_id] = flag_by_ep.get(ep_id, 0) + 1

    scheduled = _scheduled_ep_ids(club)

    # 集計バケツ
    def _blank():
        return {"ep_count": 0, "flag_count": 0, "last_date": None, "has_match_history": False}

    by_member = {}
    by_guest = {}
    for ep in eps:
        bucket = by_member.setdefault(ep.member_id, _blank()) if ep.member_id \
            else by_guest.setdefault((ep.display_name or "").strip(), _blank())
        bucket["ep_count"] += 1
        bucket["flag_count"] += flag_by_ep.get(ep.id, 0)
        d = ep.event.date
        if bucket["last_date"] is None or d > bucket["last_date"]:
            bucket["last_date"] = d
        if ep.id in scheduled:
            bucket["has_match_history"] = True

    rows = []
    for m in Member.objects.filter(club=club).order_by("-is_fixed", "member_no", "id"):
        b = by_member.get(m.id, _blank())
        rows.append({
            "key": f"m:{m.id}", "kind": "member", "member_id": m.id,
            "display_name": m.display_name, "is_fixed": m.is_fixed, "member_no": m.member_no,
            **b,
        })
    for name in sorted(by_guest.keys()):
        b = by_guest[name]
        rows.append({
            "key": f"g:{name}", "kind": "guest", "member_id": None,
            "display_name": name or "(無名ゲスト)", "is_fixed": False, "member_no": None,
            **b,
        })
    return rows


def _scheduled_ep_ids(club) -> set:
    """対戦表（公開＋ドラフト）の team1/team2/rests に登場する ep_id 集合。"""
    out: set = set()
    for ms in MatchSchedule.objects.filter(event__club=club):
        _collect_ids(ms.schedule_json, out)
    for dr in MatchScheduleDraft.objects.filter(event__club=club):
        _collect_ids(dr.draft_json, out)
    return out


def _collect_ids(schedule_json, sink: set):
    for r in (schedule_json or []):
        for m in (r.get("matches") or []):
            for key in ("team1", "team2"):
                for p in (m.get(key) or []):
                    v = _as_int(p)
                    if v is not None:
                        sink.add(v)
        for p in (r.get("rests") or []):
            v = _as_int(p)
            if v is not None:
                sink.add(v)


def _as_int(p):
    if isinstance(p, int):
        return p
    if isinstance(p, str) and p.isdigit():
        return int(p)
    return None


# ============================================================
# 統合（名寄せ）
# ============================================================

def _resolve_source_eps(club, source_key):
    """統合元 key の EP 群（メンバー or ゲスト）。"""
    if source_key.startswith("m:"):
        return list(EventParticipant.objects.filter(
            event__club=club, member_id=int(source_key[2:])
        ).select_related("event"))
    if source_key.startswith("g:"):
        name = source_key[2:]
        return list(EventParticipant.objects.filter(
            event__club=club, member__isnull=True, display_name=name
        ).select_related("event"))
    return []


def preview_merge(club, source_keys, target_key):
    """
    統合プレビュー（DB変更なし）。戻り値:
      errors[], target{}, moves(件), conflicts(件), conflict_details[], total_after{}
    """
    errors = []
    if not target_key.startswith("m:"):
        errors.append("統合先はメンバーを選んでください。")
        return {"errors": errors}
    try:
        target = Member.objects.get(id=int(target_key[2:]), club=club)
    except Member.DoesNotExist:
        return {"errors": ["統合先メンバーが見つかりません。"]}

    sources = [k for k in source_keys if k and k != target_key]
    if not sources:
        errors.append("統合元を1人以上選んでください。")
        return {"errors": errors}

    target_eps = {ep.event_id: ep for ep in EventParticipant.objects.filter(
        event__club=club, member=target)}

    moves = 0
    conflicts = 0
    conflict_details = []
    for sk in sources:
        for ep in _resolve_source_eps(club, sk):
            if ep.event_id in target_eps:
                conflicts += 1
                tep = target_eps[ep.event_id]
                merged = _stronger_attendance(tep.attendance, ep.attendance)
                conflict_details.append({
                    "event": str(ep.event),
                    "src_att": ep.attendance or "（空）",
                    "tgt_att": tep.attendance or "（空）",
                    "result_att": merged or "（空）",
                })
            else:
                moves += 1

    return {
        "errors": [],
        "target": {"key": target_key, "display_name": target.display_name},
        "sources": sources,
        "moves": moves,
        "conflicts": conflicts,
        "conflict_details": conflict_details,
    }


def apply_merge(club, source_keys, target_key, actor_kind="admin"):
    """統合を atomic に適用。統合元のメンバーは削除。適用件数を返す。"""
    target = Member.objects.get(id=int(target_key[2:]), club=club)
    sources = [k for k in source_keys if k and k != target_key]

    moved = 0
    merged_conflicts = 0
    remap = {}            # 削除する競合EPの ep_id -> 統合先EP ep_id
    snapshot = {"target": target_key, "sources": [], "club_id": club.id}

    with transaction.atomic():
        target_eps = {
            ep.event_id: ep
            for ep in EventParticipant.objects.select_for_update().filter(event__club=club, member=target)
        }
        for sk in sources:
            src_eps = _resolve_source_eps(club, sk)
            snapshot["sources"].append({
                "key": sk,
                "eps": [_ep_snapshot(ep) for ep in src_eps],
            })
            for ep in src_eps:
                tep = target_eps.get(ep.event_id)
                if tep is None:
                    # 競合なし：そのまま統合先メンバーへ付け替え
                    ep.member = target
                    ep.display_name = target.display_name
                    ep.member_deleted = False
                    ep.save(update_fields=["member", "display_name", "member_deleted", "updated_at"])
                    target_eps[ep.event_id] = ep
                    moved += 1
                else:
                    # 競合：出欠を強い方に、フラグを和集合で統合先へ寄せ、統合元EPを削除
                    _merge_attendance(tep, ep)
                    _merge_flags(tep, ep)
                    remap[ep.id] = tep.id
                    ep.delete()
                    merged_conflicts += 1

        if remap:
            _rewrite_schedules(club, remap=remap)

        # 統合元のメンバーを削除（ゲストは Member 行が無いので何もしない）
        for sk in sources:
            if sk.startswith("m:"):
                Member.objects.filter(id=int(sk[2:]), club=club).delete()

        AuditLog.objects.create(
            club=club, actor_token_kind=actor_kind, action="member_merge",
            payload_json={
                "target": target_key, "sources": sources,
                "moved": moved, "merged_conflicts": merged_conflicts,
                "before": snapshot,
            },
        )
    return moved + merged_conflicts


def _merge_attendance(tep, src_ep):
    new = _stronger_attendance(tep.attendance, src_ep.attendance)
    tep.attendance = new or None
    tep.participates_match = (new == "yes")
    tep.save(update_fields=["attendance", "participates_match", "updated_at"])


def _merge_flags(tep, src_ep):
    """src_ep のフラグを tep へ和集合で寄せる。"""
    tgt_flags = {}
    for pf in ParticipantFlag.objects.filter(event_participant=tep):
        scope = "club" if pf.club_flag_definition_id else "event"
        fid = pf.club_flag_definition_id or pf.event_flag_definition_id
        tgt_flags[(scope, fid)] = pf
    for pf in ParticipantFlag.objects.filter(event_participant=src_ep):
        scope = "club" if pf.club_flag_definition_id else "event"
        fid = pf.club_flag_definition_id or pf.event_flag_definition_id
        tgt = tgt_flags.get((scope, fid))
        if tgt is None:
            # 統合先に無い → 付け替え
            pf.event_participant = tep
            pf.save(update_fields=["event_participant", "updated_at"])
            tgt_flags[(scope, fid)] = pf
        else:
            # 両方あり → 和集合（check は OR、digit は統合先優先で空なら元を採用）
            new_on = bool(tgt.is_on) or bool(pf.is_on)
            new_val = tgt.value if tgt.value is not None else pf.value
            if tgt.is_on != new_on or tgt.value != new_val:
                tgt.is_on = new_on
                tgt.value = new_val
                tgt.save(update_fields=["is_on", "value", "updated_at"])
            # 元 pf は src_ep 削除時にカスケード削除される


def _ep_snapshot(ep):
    return {
        "ep_id": ep.id, "event_id": ep.event_id, "attendance": ep.attendance,
        "display_name": ep.display_name,
        "flags": [
            {"scope": ("club" if pf.club_flag_definition_id else "event"),
             "flag_id": pf.club_flag_definition_id or pf.event_flag_definition_id,
             "is_on": pf.is_on, "value": pf.value}
            for pf in ParticipantFlag.objects.filter(event_participant=ep)
        ],
    }


# ============================================================
# 完全削除
# ============================================================

def preview_delete(club, member_id):
    try:
        m = Member.objects.get(id=int(member_id), club=club)
    except Member.DoesNotExist:
        return {"errors": ["メンバーが見つかりません。"]}
    eps = list(EventParticipant.objects.filter(event__club=club, member=m))
    ep_ids = [ep.id for ep in eps]
    flag_count = ParticipantFlag.objects.filter(event_participant_id__in=ep_ids).count() if ep_ids else 0
    scheduled = _scheduled_ep_ids(club)
    has_history = any(ep.id in scheduled for ep in eps)
    warnings = []
    if m.is_fixed:
        warnings.append("このメンバーは固定メンバーです。")
    if has_history:
        warnings.append("対戦表（試合）に登場した記録があります。削除すると過去の対戦表からも外れます。")
    return {
        "errors": [],
        "member": {"id": m.id, "display_name": m.display_name, "is_fixed": m.is_fixed},
        "ep_count": len(eps), "flag_count": flag_count, "has_history": has_history,
        "warnings": warnings,
    }


def apply_delete(club, member_id, actor_kind="admin"):
    """メンバーを完全削除（EP・フラグも物理削除、対戦表から ep_id を除去）。"""
    with transaction.atomic():
        m = Member.objects.select_for_update().get(id=int(member_id), club=club)
        eps = list(EventParticipant.objects.filter(event__club=club, member=m))
        ep_ids = {ep.id for ep in eps}
        snapshot = {"member": {"id": m.id, "display_name": m.display_name},
                    "eps": [_ep_snapshot(ep) for ep in eps]}
        if ep_ids:
            _rewrite_schedules(club, remove=ep_ids)
            EventParticipant.objects.filter(id__in=ep_ids).delete()  # フラグは CASCADE
        m.delete()
        AuditLog.objects.create(
            club=club, actor_token_kind=actor_kind, action="member_delete_full",
            payload_json={"deleted": snapshot},
        )
    return len(ep_ids)


# ============================================================
# 対戦表の ep_id 書き換え
# ============================================================

def _rewrite_schedules(club, remap=None, remove=None):
    remap = remap or {}
    remove = remove or set()
    for ms in MatchSchedule.objects.select_for_update().filter(event__club=club):
        new_json, dirty = _rewrite_json(ms.schedule_json, remap, remove)
        if dirty:
            ms.schedule_json = new_json
            ms.save(update_fields=["schedule_json", "updated_at"])
    for dr in MatchScheduleDraft.objects.select_for_update().filter(event__club=club):
        new_json, dirty = _rewrite_json(dr.draft_json, remap, remove)
        if dirty:
            dr.draft_json = new_json
            dr.save(update_fields=["draft_json", "updated_at"])


def _rewrite_list(ids, remap, remove):
    out = []
    dirty = False
    for p in ids:
        v = _as_int(p)
        if v is None:
            out.append(p)
            continue
        if v in remove:
            dirty = True
            continue
        nv = remap.get(v, v)
        if nv != v:
            dirty = True
        if nv not in out:  # 重複防止
            out.append(nv)
        else:
            dirty = True
    return out, dirty


def _rewrite_json(schedule_json, remap, remove):
    if not schedule_json:
        return schedule_json, False
    dirty = False
    for r in schedule_json:
        for m in (r.get("matches") or []):
            for key in ("team1", "team2"):
                if key in m and m[key]:
                    new_list, d = _rewrite_list(m[key], remap, remove)
                    if d:
                        m[key] = new_list
                        dirty = True
        if r.get("rests"):
            new_rests, d = _rewrite_list(r["rests"], remap, remove)
            if d:
                r["rests"] = new_rests
                dirty = True
    return schedule_json, dirty


# ============================================================
# フラグ整理（リネーム・削除・統合）— フェーズ3
# ============================================================

def _flag_key(scope, fid):
    return f"{scope}:{fid}"


def _parse_flag_key(key):
    """'club:<id>' / 'event:<id>' -> (scope, id) or (None, None)。"""
    if key.startswith("club:"):
        try:
            return "club", int(key[5:])
        except ValueError:
            return None, None
    if key.startswith("event:"):
        try:
            return "event", int(key[6:])
        except ValueError:
            return None, None
    return None, None


def _get_flag_def(club, scope, fid):
    if scope == "club":
        return ClubFlagDefinition.objects.filter(club=club, id=fid).first()
    if scope == "event":
        return EventFlagDefinition.objects.filter(event__club=club, id=fid).first()
    return None


def flag_summaries(club):
    """
    クラブの共通フラグ＋固有フラグを使用件数つきで返す。フラグ整理画面用。
    各要素: key, scope('club'|'event'), flag_id, name, input_mode, is_active,
            usage, event_label(固有のみ), event_id(固有のみ)
    """
    rows = []
    club_flags = list(ClubFlagDefinition.objects.filter(club=club).order_by("display_order", "id"))
    usage_club = _flag_usage_map("club", [f.id for f in club_flags])
    for f in club_flags:
        rows.append({
            "key": _flag_key("club", f.id), "scope": "club", "flag_id": f.id,
            "name": f.name, "input_mode": f.input_mode, "is_active": f.is_active,
            "usage": usage_club.get(f.id, 0), "event_label": "", "event_id": None,
        })

    ev_flags = list(
        EventFlagDefinition.objects.filter(event__club=club)
        .select_related("event").order_by("event__date", "event_id", "display_order", "id")
    )
    usage_ev = _flag_usage_map("event", [f.id for f in ev_flags])
    for f in ev_flags:
        rows.append({
            "key": _flag_key("event", f.id), "scope": "event", "flag_id": f.id,
            "name": f.name, "input_mode": f.input_mode, "is_active": f.is_active,
            "usage": usage_ev.get(f.id, 0),
            "event_label": str(f.event), "event_id": f.event_id,
        })
    return rows


def _flag_usage_map(scope, ids):
    if not ids:
        return {}
    field = "club_flag_definition_id" if scope == "club" else "event_flag_definition_id"
    out = {}
    for fid in ParticipantFlag.objects.filter(**{f"{field}__in": ids}).values_list(field, flat=True):
        out[fid] = out.get(fid, 0) + 1
    return out


def rename_flag(club, flag_key, new_name, actor_kind="admin"):
    """フラグ定義の名前を変更（非破壊）。"""
    scope, fid = _parse_flag_key(flag_key)
    new_name = (new_name or "").strip()
    if not new_name:
        return {"errors": ["名前を入力してください。"]}
    fdef = _get_flag_def(club, scope, fid)
    if not fdef:
        return {"errors": ["フラグが見つかりません。"]}
    old = fdef.name
    if old == new_name:
        return {"ok": True, "unchanged": True}
    with transaction.atomic():
        fdef.name = new_name
        fdef.save(update_fields=["name"])
        AuditLog.objects.create(
            club=club, actor_token_kind=actor_kind, action="flag_rename",
            payload_json={"key": flag_key, "old": old, "new": new_name},
        )
    return {"ok": True, "old": old, "new": new_name}


def preview_flag_delete(club, flag_key):
    scope, fid = _parse_flag_key(flag_key)
    fdef = _get_flag_def(club, scope, fid)
    if not fdef:
        return {"errors": ["フラグが見つかりません。"]}
    usage = _flag_usage_map(scope, [fid]).get(fid, 0)
    return {
        "errors": [],
        "flag": {"key": flag_key, "name": fdef.name, "scope": scope},
        "usage": usage,
    }


def apply_flag_delete(club, flag_key, actor_kind="admin"):
    scope, fid = _parse_flag_key(flag_key)
    with transaction.atomic():
        fdef = _get_flag_def(club, scope, fid)
        if not fdef:
            return 0
        field = "club_flag_definition_id" if scope == "club" else "event_flag_definition_id"
        pfs = list(ParticipantFlag.objects.filter(**{field: fid})
                   .values("event_participant_id", "is_on", "value"))
        AuditLog.objects.create(
            club=club, actor_token_kind=actor_kind, action="flag_delete",
            payload_json={"key": flag_key, "name": fdef.name, "records": pfs},
        )
        fdef.delete()  # ParticipantFlag は CASCADE
    return len(pfs)


def preview_flag_merge(club, source_key, target_key):
    s_scope, s_id = _parse_flag_key(source_key)
    t_scope, t_id = _parse_flag_key(target_key)
    if source_key == target_key:
        return {"errors": ["統合元と統合先が同じです。"]}
    sdef = _get_flag_def(club, s_scope, s_id)
    tdef = _get_flag_def(club, t_scope, t_id)
    if not sdef or not tdef:
        return {"errors": ["フラグが見つかりません。"]}
    if s_scope != t_scope:
        return {"errors": ["共通フラグ同士・固有フラグ同士でのみ統合できます。"]}
    if s_scope == "event" and sdef.event_id != tdef.event_id:
        return {"errors": ["固有フラグは同じイベント内でのみ統合できます。"]}
    if sdef.input_mode != tdef.input_mode:
        return {"errors": ["入力方式（チェック/数字）が異なるフラグは統合できません。"]}

    field = "club_flag_definition_id" if s_scope == "club" else "event_flag_definition_id"
    src_eps = set(ParticipantFlag.objects.filter(**{field: s_id})
                  .values_list("event_participant_id", flat=True))
    tgt_eps = set(ParticipantFlag.objects.filter(**{field: t_id})
                  .values_list("event_participant_id", flat=True))
    moves = len(src_eps - tgt_eps)
    conflicts = len(src_eps & tgt_eps)
    return {
        "errors": [],
        "source": {"key": source_key, "name": sdef.name},
        "target": {"key": target_key, "name": tdef.name},
        "moves": moves, "conflicts": conflicts,
    }


def apply_flag_merge(club, source_key, target_key, actor_kind="admin"):
    pre = preview_flag_merge(club, source_key, target_key)
    if pre.get("errors"):
        return pre
    s_scope, s_id = _parse_flag_key(source_key)
    _, t_id = _parse_flag_key(target_key)
    field = "club_flag_definition_id" if s_scope == "club" else "event_flag_definition_id"

    moved = conflicts = 0
    with transaction.atomic():
        sdef = _get_flag_def(club, s_scope, s_id)
        tdef = _get_flag_def(club, s_scope, t_id)
        snapshot = list(ParticipantFlag.objects.filter(**{field: s_id})
                        .values("event_participant_id", "is_on", "value"))
        tgt_by_ep = {
            pf.event_participant_id: pf
            for pf in ParticipantFlag.objects.filter(**{field: t_id})
        }
        for pf in ParticipantFlag.objects.filter(**{field: s_id}):
            tgt = tgt_by_ep.get(pf.event_participant_id)
            if tgt is None:
                # 統合先に無い → 付け替え
                if s_scope == "club":
                    pf.club_flag_definition = tdef
                else:
                    pf.event_flag_definition = tdef
                pf.save(update_fields=["club_flag_definition", "event_flag_definition", "updated_at"])
                tgt_by_ep[pf.event_participant_id] = pf
                moved += 1
            else:
                # 競合 → 和集合（check は OR、digit は統合先優先で空なら元）
                new_on = bool(tgt.is_on) or bool(pf.is_on)
                new_val = tgt.value if tgt.value is not None else pf.value
                if tgt.is_on != new_on or tgt.value != new_val:
                    tgt.is_on = new_on
                    tgt.value = new_val
                    tgt.save(update_fields=["is_on", "value", "updated_at"])
                conflicts += 1
                # 元 pf は sdef 削除時にカスケード削除
        AuditLog.objects.create(
            club=club, actor_token_kind=actor_kind, action="flag_merge",
            payload_json={"source": source_key, "target": target_key,
                          "moved": moved, "conflicts": conflicts, "before": snapshot},
        )
        sdef.delete()
    return {"ok": True, "moved": moved, "conflicts": conflicts}
