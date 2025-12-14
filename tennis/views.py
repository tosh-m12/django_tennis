# tennis/views.py
from __future__ import annotations

import calendar, json, random
from datetime import date as dt_date
from datetime import datetime
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt


from .models import (
    Club, Event, Participant,
    Attendance, ClubFlagDefinition, AttendanceFlag,
    MatchScore,
)


# -------------------------
# helpers
# -------------------------

def _get_club_by_public(public_token: str) -> Club:
    return get_object_or_404(Club, public_token=public_token)

def _require_admin(club: Club, admin_token: str) -> None:
    if club.admin_token != admin_token:
        raise Http404("admin token mismatch")

def _month_range(year: int, month: int) -> tuple[dt_date, dt_date]:
    first = dt_date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = dt_date(year, month, last_day)
    return first, last

@transaction.atomic
def _ensure_attendance_rows(event: Event) -> None:
    """
    BETA最短：イベントに入った時点でクラブメンバー全員分 Attendance を用意する
    """
    participants = Participant.objects.filter(club=event.club).all()
    for p in participants:
        Attendance.objects.get_or_create(event=event, participant=p)


# -------------------------
# pages (BETA: minimal)
# -------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def portal_index(request):
    """
    / : クラブ作成（クラブ名のみ）
    POST: club_name を受けて作成し、URLを返す（BETA：コピー前提）
    """
    if request.method == "POST":
        club_name = (request.POST.get("club_name") or "").strip()
        if not club_name:
            return HttpResponse("club_name is required", status=400)

        club = Club.objects.create(name=club_name)
        member_url = f"/c/{club.public_token}/"
        admin_url = f"/c/{club.public_token}/admin/{club.admin_token}/settings/"
        return HttpResponse(
            "CLUB CREATED\n"
            f"member_url: {member_url}\n"
            f"admin_url:  {admin_url}\n"
        )

    # GET: 最小表示（後でテンプレ化）
    return HttpResponse(
        "Tennis Portal\n"
        "POST club_name to create a club.\n"
    )


@require_http_methods(["GET"])
def club_main(request, club_public_token: str):
    """
    /c/<public>/ : 当月カレンダー＆イベント一覧（最小表示）
    """
    club = _get_club_by_public(club_public_token)

    now = timezone.localdate()
    first, last = _month_range(now.year, now.month)

    events = (
        Event.objects.filter(club=club, date__range=(first, last))
        .order_by("date")
        .all()
    )

    # 当月サマリー（yes/no/maybe 集計）
    # Attendanceはイベント詳細アクセス時に生成されるが、未生成でも落ちないように left join 的に集計するなら別途要作り込み。
    # ここはBETA最短として「存在するAttendanceのみ集計」。
    summary = (
        Attendance.objects.filter(event__in=events)
        .values("event_id")
        .annotate(
            yes=Count("id", filter=Q(attendance="yes")),
            no=Count("id", filter=Q(attendance="no")),
            maybe=Count("id", filter=Q(attendance="maybe")),
        )
    )
    summary_map = {x["event_id"]: x for x in summary}

    lines = [f"Club: {club.name}", f"Month: {now.year}-{now.month:02d}", ""]
    for e in events:
        s = summary_map.get(e.id, {"yes": 0, "no": 0, "maybe": 0})
        lines.append(f"- {e.date}  (yes={s['yes']}, no={s['no']}, maybe={s['maybe']})  -> /c/{club.public_token}/e/{e.id}/")

    if not events:
        lines.append("(no events this month)")

    return HttpResponse("\n".join(lines))


@require_http_methods(["GET"])
def club_settings(request, club_public_token: str, club_admin_token: str):
    club = _get_club_by_public(club_public_token)
    _require_admin(club, club_admin_token)

    now = timezone.localdate()
    first, last = _month_range(now.year, now.month)

    events = Event.objects.filter(club=club, date__range=(first, last)).order_by("date")
    event_map = {e.date.isoformat(): e.id for e in events}

    # 当月カレンダー行（テンプレで辞書アクセスしないための形）
    calendar_rows = []
    for day in range(1, last.day + 1):
        d = dt_date(now.year, now.month, day).isoformat()
        calendar_rows.append({
            "date": d,
            "day": day,
            "event_id": event_map.get(d),
        })

    flags = ClubFlagDefinition.objects.filter(club=club).order_by("order", "id")
    members = Participant.objects.filter(club=club).order_by("id")

    ctx = {
        "club": club,
        "admin_token": club_admin_token,
        "year": now.year,
        "month": now.month,
        "calendar_rows": calendar_rows,
        "flags": flags,
        "members": members,
    }
    return render(request, "tennis/club_settings.html", ctx)


@require_http_methods(["GET"])
def event_detail(request, club_public_token: str, event_id: int):
    club = get_object_or_404(Club, public_token=club_public_token)
    event = get_object_or_404(Event, id=event_id, club=club)

    members = Participant.objects.filter(club=club).order_by("id")

    # Attendance を足りない分だけ自動作成（最短）
    existing = {a.participant_id: a for a in Attendance.objects.filter(event=event)}
    to_create = []
    for m in members:
        if m.id not in existing:
            to_create.append(Attendance(event=event, participant=m, attendance="maybe"))
    if to_create:
        Attendance.objects.bulk_create(to_create)
        existing = {a.participant_id: a for a in Attendance.objects.filter(event=event)}

    attendances = Attendance.objects.filter(event=event).select_related("participant").order_by("participant__id")

    # フラグ（activeのみ表示。過去保持は DB 側で維持）
    flags = ClubFlagDefinition.objects.filter(club=club, is_active=True).order_by("order", "id")

    # AttendanceFlag 既存チェック
    af_qs = AttendanceFlag.objects.filter(attendance__event=event, flag__in=flags)
    checked = {(af.attendance_id, af.flag_id): af.checked for af in af_qs}

    # 対戦表（ロック優先）
    schedule = event.locked_schedule if event.locked_at else event.draft_schedule
    if not schedule:
        schedule = []

    ctx = {
        "club": club,
        "event": event,
        "members": members,
        "attendances": attendances,
        "flags": flags,
        "checked_map_json": json.dumps({f"{k[0]}_{k[1]}": v for k, v in checked.items()}),
        "schedule_json": json.dumps(schedule),
    }
    return render(request, "tennis/event_detail.html", ctx)


    # スコア
    scores = MatchScore.objects.filter(event=event).order_by("match_key")
    if scores.exists():
        lines.append("")
        lines.append("Scores:")
        for s in scores:
            lines.append(f"  - {s.match_key}: {s.score_text}")

    return HttpResponse("\n".join(lines))


# -------------------------
# APIs
# -------------------------

@csrf_exempt
@require_http_methods(["POST"])
def api_member_add(request, club_public_token: str):
    club = _get_club_by_public(club_public_token)
    name = (request.POST.get("display_name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "display_name is required"}, status=400)

    m = Participant.objects.create(club=club, display_name=name)
    return JsonResponse({"ok": True, "member": {"id": m.id, "display_name": m.display_name}})


@csrf_exempt
@require_http_methods(["POST"])
def api_flag_add(request, club_public_token: str):
    club = _get_club_by_public(club_public_token)
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "name is required"}, status=400)

    # order: 最後尾に追加（BETA最短）
    last = ClubFlagDefinition.objects.filter(club=club).order_by("-order").first()
    next_order = (last.order + 1) if last else 1

    f = ClubFlagDefinition.objects.create(club=club, name=name, order=next_order, is_active=True)
    return JsonResponse({"ok": True, "flag": {"id": f.id, "name": f.name, "order": f.order, "is_active": f.is_active}})


@csrf_exempt
@require_http_methods(["POST"])
def api_flag_rename(request, club_public_token: str, flag_id: int):
    club = _get_club_by_public(club_public_token)
    f = get_object_or_404(ClubFlagDefinition, id=flag_id, club=club)
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "name is required"}, status=400)
    f.name = name
    f.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_flag_toggle_active(request, club_public_token: str, flag_id: int):
    club = _get_club_by_public(club_public_token)
    f = get_object_or_404(ClubFlagDefinition, id=flag_id, club=club)
    f.is_active = not f.is_active
    f.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"ok": True, "is_active": f.is_active})


@csrf_exempt
@require_http_methods(["POST"])
def api_attendance_update(request, event_id: int):
    # POST: participant_id, attendance(yes/no/maybe), participates_match(0/1), comment, flags (comma-separated flag ids)
    event = get_object_or_404(Event, id=event_id)
    pid = request.POST.get("participant_id")
    if not pid:
        return JsonResponse({"ok": False, "error": "participant_id required"}, status=400)

    att = Attendance.objects.select_related("participant").get(event=event, participant_id=int(pid))

    attendance = request.POST.get("attendance")
    if attendance in ("yes", "no", "maybe"):
        att.attendance = attendance

    pm = request.POST.get("participates_match")
    if pm is not None:
        att.participates_match = (pm == "1")

    comment = request.POST.get("comment")
    if comment is not None:
        att.comment = comment

    att.save()

    # flags 更新（activeフラグのみ想定）
    flags_str = request.POST.get("flags", "")
    flag_ids = []
    if flags_str.strip():
        try:
            flag_ids = [int(x) for x in flags_str.split(",") if x.strip()]
        except ValueError:
            return JsonResponse({"ok": False, "error": "invalid flags"}, status=400)

    # 指定フラグだけ checked=True に、指定外は False に（最短）
    club_flags = ClubFlagDefinition.objects.filter(id__in=flag_ids)
    # まず club の active フラグ集合を取得（この attendance の club に限定）
    active_flags = ClubFlagDefinition.objects.filter(club=event.club, is_active=True)
    active_ids = list(active_flags.values_list("id", flat=True))

    # 既存を一括で False
    AttendanceFlag.objects.filter(attendance=att, flag_id__in=active_ids).update(checked=False)

    # 指定分を upsert
    for fid in flag_ids:
        AttendanceFlag.objects.update_or_create(
            attendance=att,
            flag_id=fid,
            defaults={"checked": True},
        )

    return JsonResponse({"ok": True})


def _build_schedule(names: list[str], rounds: int = 1) -> list[dict]:
    rounds = max(1, min(int(rounds), 10))  # 1〜10で制限（BETA安全）

    out = []
    for r in range(1, rounds + 1):
        pool = names[:]
        random.shuffle(pool)

        m = 1
        i = 0
        while i + 4 <= len(pool):
            chunk = pool[i:i+4]
            out.append({
                "match_key": f"R{r}-M{m}",
                "round": r,
                "players": chunk,
                "score": {"a": "", "b": ""},
            })
            m += 1
            i += 4

    return out


@csrf_exempt
@require_http_methods(["POST"])
def api_schedule_generate(request, event_id: int):
    event = get_object_or_404(Event, id=event_id)

    

    force = request.POST.get("force") == "1"
    if event.locked_at and not force:
        return JsonResponse({"ok": False, "error": "locked (score exists). use force=1 to regenerate."}, status=409)

    # 参加者：attendance=yes かつ participates_match=True
    qs = Attendance.objects.filter(event=event, attendance="yes", participates_match=True).select_related("participant")
    names = [a.participant.display_name for a in qs]

    rounds = request.POST.get("rounds") or "1"
    try:
        rounds_i = int(rounds)
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid rounds"}, status=400)

    schedule = _build_schedule(names, rounds=rounds_i)
    event.draft_schedule = schedule
    # force で再生成する場合はロック解除もセットでやる（最短）
    if force:
        event.locked_at = None
        event.has_score = False
        event.locked_schedule = []

    if event.locked_schedule is None:
        event.locked_schedule = []

    event.save(update_fields=["draft_schedule", "locked_at", "has_score", "locked_schedule", "updated_at"])


    return JsonResponse({"ok": True, "schedule": schedule})



@csrf_exempt
@require_http_methods(["POST"])
def api_score_set(request, event_id: int):
    event = get_object_or_404(Event, id=event_id)
    match_key = (request.POST.get("match_key") or "").strip()
    score_a = (request.POST.get("score_a") or "").strip()
    score_b = (request.POST.get("score_b") or "").strip()

    if not match_key:
        return JsonResponse({"ok": False, "error": "match_key required"}, status=400)

    # ロック前なら draft を locked にコピーしてロック開始
    if not event.locked_at:
        base = event.draft_schedule or []
        event.locked_schedule = json.loads(json.dumps(base))  # deep copy
        event.locked_at = timezone.now()

    sched = event.locked_schedule or []
    found = False
    for m in sched:
        if m.get("match_key") == match_key:
            m.setdefault("score", {})
            m["score"]["a"] = score_a
            m["score"]["b"] = score_b
            found = True
            break

    if not found:
        return JsonResponse({"ok": False, "error": "match_key not found"}, status=404)

    # スコアが1つでも入ったら has_score=True
    if score_a or score_b:
        event.has_score = True

    event.locked_schedule = sched
    event.save(update_fields=["locked_schedule", "locked_at", "has_score", "updated_at"])
    return JsonResponse({"ok": True, "locked_at": event.locked_at.isoformat(), "has_score": event.has_score})


@csrf_exempt
@require_http_methods(["POST"])
def api_schedule_reset(request, event_id: int):
    event = get_object_or_404(Event, id=event_id)
    event.locked_at = None
    event.has_score = False

    # NOT NULL 対策（None にしない）
    event.locked_schedule = []
    event.draft_schedule = []

    event.save(update_fields=["locked_at", "has_score", "locked_schedule", "draft_schedule", "updated_at"])
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_event_create(request, club_public_token: str):
    """
    POST:
      date=YYYY-MM-DD  （必須）
      start_time=HH:MM （任意）
      place, note      （任意）
    """
    club = _get_club_by_public(club_public_token)

    date_str = (request.POST.get("date") or "").strip()
    if not date_str:
        return JsonResponse({"ok": False, "error": "date is required (YYYY-MM-DD)"}, status=400)

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid date format. use YYYY-MM-DD"}, status=400)

    start_time = (request.POST.get("start_time") or "").strip() or None
    place = (request.POST.get("place") or "").strip()
    note = (request.POST.get("note") or "").strip()

    # 1日1回固定：unique (club, date)
    event, created = Event.objects.get_or_create(
        club=club,
        date=d,
        defaults={
            "place": place,
            "note": note,
        }
    )

    # 任意項目は created 時のみ入れる（上書きしたいなら別APIで）
    if created and start_time:
        # start_time は TimeField の想定
        try:
            event.start_time = datetime.strptime(start_time, "%H:%M").time()
            event.save(update_fields=["start_time", "updated_at"])
        except ValueError:
            return JsonResponse({"ok": False, "error": "invalid start_time format. use HH:MM"}, status=400)

    return JsonResponse({
        "ok": True,
        "created": created,
        "event": {
            "id": event.id,
            "date": event.date.isoformat(),
            "detail_url": f"/c/{club.public_token}/e/{event.id}/",
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_schedule_swap_player(request, event_id: int):
    event = get_object_or_404(Event, id=event_id)

    old_name = (request.POST.get("old_name") or "").strip()
    new_name = (request.POST.get("new_name") or "").strip()

    if not old_name or not new_name:
        return JsonResponse({"ok": False, "error": "old_name and new_name required"}, status=400)

    # 置換先は「クラブ所属メンバー」の表示名に限定（最短の安全策）
    if not Participant.objects.filter(club=event.club, display_name=new_name).exists():
        return JsonResponse({"ok": False, "error": "new_name not in club members"}, status=400)

    # ロック中は locked_schedule を編集、未ロックは draft_schedule を編集
    target_field = "locked_schedule" if event.locked_at else "draft_schedule"
    sched = getattr(event, target_field) or []

    replaced = 0
    for m in sched:
        players = m.get("players") or []
        new_players = []
        for p in players:
            if p == old_name:
                new_players.append(new_name)
                replaced += 1
            else:
                new_players.append(p)
        m["players"] = new_players

    if replaced == 0:
        return JsonResponse({"ok": False, "error": "old_name not found in schedule"}, status=404)

    setattr(event, target_field, sched)

    # has_score は維持（ロック中の代打でスコアは消さない）
    if event.locked_schedule is None:
        event.locked_schedule = []
    if event.draft_schedule is None:
        event.draft_schedule = []

    event.save(update_fields=[target_field, "updated_at"])
    return JsonResponse({"ok": True, "replaced": replaced, "schedule": sched})
