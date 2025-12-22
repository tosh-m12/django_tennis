# tennis/views.py
import calendar
import json
import datetime as dt
from collections import defaultdict
from datetime import time

from django.db import transaction, models
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.template.loader import render_to_string

from .utils import generate_doubles_schedule, generate_singles_schedule
from .models import (
    Club,
    Event,
    Member,
    EventParticipant,
    ClubFlagDefinition,
    ParticipantFlag,
    MatchSchedule,
    MatchScheduleDraft,
    MatchScore,
    GameType,
)

# ============================================================
# Config
# ============================================================

MAX_FLAGS = 3  # V1仕様

# ============================================================
# [AUTH] Admin session flag for token-based admin access
# ============================================================

def _admin_session_key(event_id: int) -> str:
    return f"tennis_event_admin:{event_id}"

def _mark_event_admin_session(request, event_id: int) -> None:
    request.session[_admin_session_key(event_id)] = True
    # セッション保存を確実に
    request.session.modified = True

def _is_event_admin_session(request, event_id: int) -> bool:
    return bool(request.session.get(_admin_session_key(event_id), False))


# ============================================================
# Helpers
# ============================================================

def _parse_int(value, default=None, min_v=None, max_v=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    if v is None:
        return None
    if min_v is not None:
        v = max(min_v, v)
    if max_v is not None:
        v = min(max_v, v)
    return v


def _parse_date_yyyy_mm_dd(date_str: str):
    try:
        return dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_hhmm(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        hh, mm = s.split(":")
        return dt.time(int(hh), int(mm))
    except Exception:
        return None


def _is_event_ended(event) -> bool:
    """
    終了判定：
    - 過去日 → 終了
    - 今日 かつ end_time がある → now > end_time で終了
    - end_time 無し → 今日分は終了扱いにしない
    """
    if not getattr(event, "date", None):
        return False

    today = timezone.localdate()
    if event.date < today:
        return True
    if event.date > today:
        return False

    end_time = getattr(event, "end_time", None)
    if not end_time:
        return False

    tz = timezone.get_current_timezone()
    end_dt = timezone.make_aware(dt.datetime.combine(event.date, end_time), tz)
    now = timezone.localtime()
    return now > end_dt


def _get_month_range(year: int, month: int):
    first_day = dt.date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day = dt.date(year, month, last_day_num)
    return first_day, last_day


def _build_month_calendar(year: int, month: int, events_qs):
    events_by_day = defaultdict(list)
    for ev in events_qs:
        key = ev.date.strftime("%Y-%m-%d")
        events_by_day[key].append(ev)

    cal = calendar.Calendar(firstweekday=0)  # 0=MON
    month_weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            key = d.strftime("%Y-%m-%d")
            week_data.append(
                {
                    "date": d,
                    "key": key,
                    "is_current_month": (d.month == month),
                    "events": events_by_day.get(key, []),
                }
            )
        month_weeks.append(week_data)
    return month_weeks


def _get_or_create_member_for_name(club: Club, name: str) -> Member | None:
    name = (name or "").strip()
    if not name:
        return None

    m = (
        Member.objects.filter(club=club, display_name=name, is_active=True)
        .order_by("-is_fixed", "id")
        .first()
    )
    if m:
        m.touch()
        return m

    # ゲスト運用：Memberは作る（非固定）
    m = Member.objects.create(
        club=club,
        display_name=name,
        is_fixed=False,
        is_active=True,
        last_seen_at=timezone.now(),
    )
    return m


def _get_or_create_ep(event: Event, member: Member | None, display_name: str) -> EventParticipant:
    """
    - memberあり: unique(event, member) を満たすよう get_or_create
    - memberなし: display_name で都度作成（互換用）
    """
    display_name = (display_name or "").strip() or "Guest"

    if member is not None:
        ep, _ = EventParticipant.objects.get_or_create(
            event=event,
            member=member,
            defaults={"display_name": display_name},
        )
        if ep.display_name != display_name:
            ep.display_name = display_name
            ep.save(update_fields=["display_name", "updated_at"])
        return ep

    return EventParticipant.objects.create(event=event, member=None, display_name=display_name)


def _build_score_map(match_schedule: MatchSchedule):
    score_map = {}
    qs = MatchScore.objects.filter(match_schedule=match_schedule)
    for s in qs:
        score_map[(int(s.round_no), int(s.court_no))] = (s.side_a_score, s.side_b_score)
    return score_map


def _merge_scores_into_schedule(schedule_json, score_map):
    if not schedule_json:
        return []

    out = []
    for r in schedule_json:
        round_no = int(r.get("round") or 0)
        matches = []
        for m in (r.get("matches") or []):
            court_no = int(m.get("court") or 0)
            t1 = list(m.get("team1") or [])
            t2 = list(m.get("team2") or [])

            s1, s2 = score_map.get((round_no, court_no), (None, None))
            matches.append(
                {
                    "court": court_no,
                    "team1": t1,
                    "team2": t2,
                    "score1": s1,
                    "score2": s2,
                    "round_no": round_no,
                    "court_no": court_no,
                }
            )
        rests = list(r.get("rests") or [])
        out.append({"round": round_no, "matches": matches, "rests": rests})
    return out


def _build_ep_name_map(event: Event) -> dict:
    """
    template は ep_name_map[get_item:ep_id] を見る。
    今後は ep_id(int) を正とするが、過去互換のため display_name(str) もキーに入れる。
    """
    m = {}
    for ep in EventParticipant.objects.filter(event=event).order_by("id"):
        if ep.id is not None:
            m[int(ep.id)] = ep.display_name
        if ep.display_name:
            m[str(ep.display_name)] = ep.display_name  # 互換（古いscheduleが名前文字列のとき）
    return m


# ============================================================
# publish_state
# ============================================================

def _norm_schedule_json(x):
    return x if x is not None else []


def _compute_publish_state(event, schedule_from_generation=None):
    schedule = _norm_schedule_json(schedule_from_generation)
    if not schedule:
        return "no_schedule"

    ms = MatchSchedule.objects.filter(event=event, published=True).first()
    if not ms:
        return "ready"

    published_schedule = _norm_schedule_json(ms.schedule_json)
    if published_schedule == schedule:
        return "published"
    return "changed"


def _optional_admin_token_check(request, club: Club):
    """
    後方互換のため「送られてきたらチェック」。
    送られてこない場合はスルー。
    """
    token = (request.POST.get("club_admin_token") or "").strip()
    if not token:
        return None
    if token != (club.admin_token or ""):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    return None


# ============================================================
# Ranking（現行踏襲）
# ============================================================
def build_month_ranking(events_qs, game_type: str, min_matches: int = 3):
    events = list(events_qs)
    if not events:
        return {"ranked": [], "others": []}

    ms_by_event = {}
    for ms in MatchSchedule.objects.filter(event__in=events, published=True, game_type=game_type):
        ms_by_event[ms.event_id] = ms

    # 月の対象イベントに出てくるEPをまとめて引く（高速化）
    # ※ schedule_json に入っているのが ep_id 前提
    ep_ids = set()
    for ev in events:
        ms = ms_by_event.get(ev.id)
        if not ms or not ms.schedule_json:
            continue
        for r in (ms.schedule_json or []):
            for m in (r.get("matches") or []):
                for p in (m.get("team1") or []):
                    if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
                        ep_ids.add(int(p))
                for p in (m.get("team2") or []):
                    if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
                        ep_ids.add(int(p))

    ep_map = {
        ep.id: ep
        for ep in EventParticipant.objects.filter(id__in=list(ep_ids)).select_related("member")
    }

    stats = {}

    def ensure(key, name):
        if key not in stats:
            stats[key] = {"name": name, "matches": 0, "wins": 0, "losses": 0, "draws": 0, "gf": 0, "ga": 0}
        return stats[key]

    def resolve_player_key_and_name(p):
        """
        p が:
        - ep_id(int or digit str) → member_id があれば member集計、無ければゲスト名集計
        - 名前文字列（旧形式） → ゲスト名集計
        """
        # ep_id形式
        if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
            ep = ep_map.get(int(p))
            if ep:
                if ep.member_id:
                    # 固定メンバー：member_idで集約
                    name = ep.member.display_name if ep.member else (ep.display_name or f"Member#{ep.member_id}")
                    return (("m", ep.member_id), name)
                # ゲスト：表示名で集計
                gname = (ep.display_name or f"Guest#{ep.id}").strip()
                return (("g", gname), gname)

            # EPが見つからない（保険）
            return (("g", str(p)), str(p))

        # 旧形式：名前が入っている
        name = str(p).strip()
        return (("g", name), name)

    for ev in events:
        ms = ms_by_event.get(ev.id)
        if not ms or not ms.schedule_json:
            continue

        score_map = _build_score_map(ms)

        for r in (ms.schedule_json or []):
            round_no = int(r.get("round") or 0)
            for m in (r.get("matches") or []):
                court_no = int(m.get("court") or 0)
                t1 = list(m.get("team1") or [])
                t2 = list(m.get("team2") or [])

                s1, s2 = score_map.get((round_no, court_no), (None, None))
                if s1 is None or s2 is None:
                    continue

                # team1
                for p in t1:
                    key, name = resolve_player_key_and_name(p)
                    st = ensure(key, name)
                    st["matches"] += 1
                    st["gf"] += int(s1)
                    st["ga"] += int(s2)
                    if s1 > s2:
                        st["wins"] += 1
                    elif s1 < s2:
                        st["losses"] += 1
                    else:
                        st["draws"] += 1

                # team2
                for p in t2:
                    key, name = resolve_player_key_and_name(p)
                    st = ensure(key, name)
                    st["matches"] += 1
                    st["gf"] += int(s2)
                    st["ga"] += int(s1)
                    if s2 > s1:
                        st["wins"] += 1
                    elif s2 < s1:
                        st["losses"] += 1
                    else:
                        st["draws"] += 1

    rows = []
    for st in stats.values():
        m = st["matches"]
        w = st["wins"]
        gf = st["gf"]
        ga = st["ga"]
        st["win_pct"] = round((w / m) * 100, 1) if m else 0.0
        st["gp_pct"] = round((gf / (gf + ga)) * 100, 1) if (gf + ga) else 0.0
        st["diff"] = gf - ga
        rows.append(st)

    ranked = [r for r in rows if r["matches"] >= min_matches]
    others = [r for r in rows if r["matches"] < min_matches]

    ranked.sort(key=lambda r: (-(r["win_pct"]), -(r["gp_pct"]), -(r["wins"]), -(r["diff"]), -(r["matches"]), r["name"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    return {"ranked": ranked, "others": others}


# ============================================================
# Pages
# ============================================================

@require_http_methods(["GET", "POST"])
def index(request):
    """
    トップ = クラブ作成
    ★方針変更：作成後は「幹事ホーム（club_home_admin）」へ
    """
    if request.method == "POST":
        name = (request.POST.get("club_name") or "").strip()
        if not name:
            return HttpResponseBadRequest("クラブ名は必須です。")

        club = Club.objects.create(name=name)
        return redirect("tennis:club_home_admin", club_public_token=club.public_token, club_admin_token=club.admin_token)

    return render(request, "tennis/index.html", {
        "show_topbar": False,
    })


def club_settings(request, club_public_token, club_admin_token):
    club = get_object_or_404(Club, public_token=club_public_token, admin_token=club_admin_token, is_active=True)

    member_url = request.build_absolute_uri(reverse("tennis:club_home", args=[club.public_token]))
    admin_home_url = request.build_absolute_uri(reverse("tennis:club_home_admin", args=[club.public_token, club.admin_token]))
    admin_settings_url = request.build_absolute_uri(reverse("tennis:club_settings", args=[club.public_token, club.admin_token]))

    today = timezone.localdate()
    year = _parse_int(request.GET.get("year"), default=today.year, min_v=2000, max_v=2100) or today.year
    month = _parse_int(request.GET.get("month"), default=today.month, min_v=1, max_v=12) or today.month

    first_day, last_day = _get_month_range(year, month)
    events_qs = (
        Event.objects.filter(club=club, date__gte=first_day, date__lte=last_day)
        .order_by("date", "start_time", "id")
    )

    club_flags = list(ClubFlagDefinition.objects.filter(club=club, is_active=True).order_by("display_order", "id"))
    month_weeks = _build_month_calendar(year, month, events_qs)

    prev_year = year - 1 if month == 1 else year
    prev_month = 12 if month == 1 else month - 1
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1

    return render(
        request,
        "tennis/settings.html",
        {
            "club": club,
            "member_url": member_url,
            "admin_home_url": admin_home_url,
            "admin_settings_url": admin_settings_url,
            "year": year,
            "month": month,
            "month_weeks": month_weeks,
            "today": today,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "flags": club_flags,
            "max_flags": MAX_FLAGS,
            "show_topbar": True,
        },
    )


def club_home(request, club_public_token, club_admin_token=None):
    """
    共通ホーム（メンバー/幹事）
    - /c/<public>/                 -> is_admin=False
    - /c/<public>/admin/<admin>/   -> is_admin=True
    """
    club = get_object_or_404(Club, public_token=club_public_token, is_active=True)

    is_admin = False
    admin_token = ""
    if club_admin_token and club.admin_token == club_admin_token:
        is_admin = True
        admin_token = club.admin_token

    today = timezone.localdate()
    year = _parse_int(request.GET.get("year"), default=today.year, min_v=2000, max_v=2100) or today.year
    month = _parse_int(request.GET.get("month"), default=today.month, min_v=1, max_v=12) or today.month

    first = dt.date(year, month, 1)
    next_month_date = (first + dt.timedelta(days=32)).replace(day=1)

    events_qs = (
        Event.objects.filter(club=club, date__gte=first, date__lt=next_month_date)
        .order_by("date", "start_time", "id")
    )

    month_weeks = _build_month_calendar(year, month, events_qs)

    # ランキング（ダブルス/シングルス）
    ranking_doubles = build_month_ranking(events_qs, GameType.DOUBLES)
    ranking_singles = build_month_ranking(events_qs, GameType.SINGLES)

    prev_month_date = (first - dt.timedelta(days=1)).replace(day=1)
    prev_year, prev_month = prev_month_date.year, prev_month_date.month
    next_year, next_month = next_month_date.year, next_month_date.month

    # settings への導線（幹事だけ）
    settings_url = ""
    if is_admin:
        settings_url = reverse("tennis:club_settings", args=[club.public_token, club.admin_token])

    # ★ URL表示用（base.html / club_home.html が参照）
    member_url = request.build_absolute_uri(
        reverse("tennis:club_home", args=[club.public_token])
    )
    admin_url = request.build_absolute_uri(
        reverse("tennis:club_home_admin", args=[club.public_token, club.admin_token])
    )

    return render(
        request,
        "tennis/club_home.html",
        {
            "club": club,
            "today": today,
            "year": year,
            "month": month,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "month_weeks": month_weeks,
            "ranking_doubles": ranking_doubles,
            "ranking_singles": ranking_singles,
            "is_admin": is_admin,
            "admin_token": admin_token,
            "settings_url": settings_url,
            "member_url": member_url,
            "admin_url": admin_url,
            "show_topbar": True,
        },
    )


# ============================================================
# Event (統合ビュー)
# ============================================================


def event_view(request, club_public_token, event_id, club_admin_token=None):
    club = get_object_or_404(Club, public_token=club_public_token, is_active=True)
    event = get_object_or_404(Event, id=int(event_id), club=club)

    is_admin = False
    if club_admin_token is not None:
        if club.admin_token != club_admin_token:
            return HttpResponseBadRequest("admin token mismatch")
        is_admin = True
        # ✅ このイベントは幹事としてアクセス済み（sessionに記録）
        _mark_event_admin_session(request, event.id)

    flags = list(
        ClubFlagDefinition.objects.filter(club=club, is_active=True).order_by("display_order", "id")
    )

    members = list(Member.objects.filter(club=club, is_active=True).order_by("-is_fixed", "display_name", "id"))
    member_ids = [m.id for m in members]

    eps_by_member = {
        ep.member_id: ep
        for ep in EventParticipant.objects.filter(event=event, member_id__in=member_ids).select_related("member")
    }

    pf_qs = ParticipantFlag.objects.filter(
        event_participant__event=event,
        flag_definition__club=club,
    )
    flag_states = {}
    for pf in pf_qs:
        flag_states[f"{pf.event_participant_id}:{pf.flag_definition_id}"] = bool(pf.is_on)

    # ============================================================
    # A案：Draftは「公開のための一時データ」であり、GET描画では必ず破棄する
    #  - 公開済み(ms)があるときだけ schedule を表示
    #  - 未公開(msなし)のとき schedule は常に空
    # ============================================================
    ms = MatchSchedule.objects.filter(event=event, published=True).first()

    # ★A案（確定）：GETでevent.htmlを描画するたびにDraftを消す
    MatchScheduleDraft.objects.filter(event=event).delete()

    # ====== 出欠リスト（試合参加は常にDB値。Draft participant_ids で上書きしない） ======
    fixed_rows = []
    for m in members:
        ep = eps_by_member.get(m.id)
        fixed_rows.append(
            {
                "member_id": m.id,
                "ep_id": ep.id if ep else None,
                "display_name": ep.display_name if ep else m.display_name,
                "attendance": ep.attendance if ep else None,
                "comment": ep.comment if ep else "",
                # ★A案：常にDB
                "participates_match": bool(ep.participates_match) if ep else False,
            }
        )

    guest_eps = (
        EventParticipant.objects.filter(event=event)
        .exclude(member_id__in=member_ids)
        .select_related("member")
        .order_by("id")
    )

    guest_rows = [
        {
            "ep_id": ep.id,
            "display_name": ep.display_name,
            "attendance": ep.attendance,
            "comment": ep.comment or "",
            # ★A案：常にDB
            "participates_match": bool(ep.participates_match),
        }
        for ep in guest_eps
    ]

    # ====== pill用の値（表示一致の正） ======
    # ここが重要：event.html の上のpill と、_schedule_block.html 側のpill を揃えるため
    # ctxに pill_* を常に入れる（schedule の有無に依存させない）
    if ms:
        game_type = ms.game_type or GameType.DOUBLES
        num_rounds = int(ms.round_count or 8)
        num_courts = int(ms.court_count or 1)

        match_count = EventParticipant.objects.filter(event=event, participates_match=True).count()
        publish_state = "published"

        score_map = _build_score_map(ms)
        schedule_for_view = _merge_scores_into_schedule(ms.schedule_json, score_map)

        # 公開済みページのリロード時に publish 用 schedule_json は出さない（A案）
        schedule_json_for_publish = None
    else:
        game_type = GameType.DOUBLES
        num_rounds = 8
        num_courts = 1
        match_count = EventParticipant.objects.filter(event=event, participates_match=True).count() if is_admin else 0

        publish_state = "no_schedule"
        schedule_for_view = []
        schedule_json_for_publish = None

    ctx = {
        "club": club,
        "event": event,
        "is_admin": is_admin,
        "flags": flags,
        "flag_states": flag_states,
        "fixed_rows": fixed_rows,
        "guest_rows": guest_rows,
        "max_flags": MAX_FLAGS,

        # event.html 側で使う（既存）
        "game_type": game_type,
        "num_rounds": num_rounds,
        "num_courts": num_courts,
        "match_count": match_count,
        "publish_state": publish_state,
        "schedule": schedule_for_view,
        "schedule_json": schedule_json_for_publish,

        # _schedule_block.html 側の pill 表示を一致させる（★ここが肝）
        "show_controls": bool(is_admin),
        "pill_game_type": game_type,
        "pill_num_courts": num_courts,
        "pill_num_rounds": num_rounds,
        "pill_match_count": match_count,

        "ep_name_map": _build_ep_name_map(event),
        "show_topbar": True,
    }
    return render(request, "tennis/event.html", ctx)


# ============================================================
# Club APIs
# ============================================================

@require_POST
def club_add_flag(request):
    club_id = request.POST.get("club_id")
    if not club_id:
        return JsonResponse({"error": "club_id required"}, status=400)
    club = get_object_or_404(Club, id=club_id, is_active=True)

    current = ClubFlagDefinition.objects.filter(club=club, is_active=True).count()
    if current >= MAX_FLAGS:
        return JsonResponse({"error": "max_reached", "max": MAX_FLAGS}, status=400)

    next_order = (
        ClubFlagDefinition.objects.filter(club=club)
        .aggregate(models.Max("display_order"))["display_order__max"]
        or 0
    ) + 1

    flag = ClubFlagDefinition.objects.create(
        club=club,
        name=f"フラグ{next_order}",
        display_order=next_order,
        is_active=True,
    )
    return JsonResponse({"ok": True, "id": flag.id, "name": flag.name, "display_order": flag.display_order})


@require_POST
def club_delete_flag(request):
    club_id = request.POST.get("club_id")
    if not club_id:
        return JsonResponse({"error": "club_id required"}, status=400)
    club = get_object_or_404(Club, id=club_id, is_active=True)

    last_flag = ClubFlagDefinition.objects.filter(club=club, is_active=True).order_by("-display_order", "-id").first()
    if not last_flag:
        return JsonResponse({"error": "no_flag"}, status=400)

    last_flag.is_active = False
    last_flag.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"ok": True})


@require_POST
def club_rename_flag(request):
    flag_id = request.POST.get("flag_id")
    name = (request.POST.get("name") or "").strip()
    if not flag_id:
        return JsonResponse({"error": "flag_id required"}, status=400)
    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    flag = get_object_or_404(ClubFlagDefinition, id=flag_id)
    flag.name = name
    flag.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True, "name": flag.name})


@require_POST
def club_rename_club(request):
    club_id = request.POST.get("club_id")
    name = (request.POST.get("name") or "").strip()
    if not club_id:
        return JsonResponse({"ok": False, "error": "club_id required"}, status=400)
    if not name:
        return JsonResponse({"ok": False, "error": "name required"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    club.name = name
    club.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True, "name": club.name})


@require_POST
def club_create_event(request):
    club_id = request.POST.get("club_id")
    date_str = request.POST.get("date")
    title = (request.POST.get("title") or "").strip()

    place = (request.POST.get("place") or "").strip()  # ★追加

    start_str = (request.POST.get("start_time") or "").strip()
    end_str = (request.POST.get("end_time") or "").strip()

    if not club_id or not date_str:
        return JsonResponse({"error": "required"}, status=400)

    club = get_object_or_404(Club, id=club_id, is_active=True)

    d = _parse_date_yyyy_mm_dd(date_str)
    if not d:
        return JsonResponse({"error": "bad_date"}, status=400)

    start_t = _parse_hhmm(start_str)
    end_t = _parse_hhmm(end_str)
    if start_t and end_t and end_t < start_t:
        return JsonResponse({"error": "time_order"}, status=400)

    ev = Event.objects.create(
        club=club,
        date=d,
        title=title or "練習",
        place=place,  # ★追加
        start_time=start_t,
        end_time=end_t,
        cancelled=False,
    )

    return JsonResponse(
        {
            "ok": True,
            "event": {
                "id": ev.id,
                "date": ev.date.strftime("%Y-%m-%d"),
                "title": ev.title,
                "public_url": reverse("tennis:event_public", args=[club.public_token, ev.id]),
                "admin_url": reverse("tennis:event_admin", args=[club.public_token, club.admin_token, ev.id]),
            },
        }
    )


@require_POST
def club_cancel_event(request):
    event_id = request.POST.get("event_id")
    if not event_id:
        return JsonResponse({"error": "event_id required"}, status=400)

    ev = get_object_or_404(Event, id=event_id)
    ev.cancelled = not bool(ev.cancelled)
    ev.save(update_fields=["cancelled", "updated_at"])
    return JsonResponse({"ok": True, "cancelled": ev.cancelled})


@require_POST
def club_delete_event(request):
    event_id = request.POST.get("event_id")
    if not event_id:
        return JsonResponse({"error": "event_id required"}, status=400)

    ev = get_object_or_404(Event, id=event_id)
    ev.delete()
    return JsonResponse({"ok": True})


def _json_forbidden(message: str, code: str = "forbidden", status: int = 403):
    return JsonResponse({"ok": False, "error": code, "message": message}, status=status)


def _guard_participant_change(request, event, *, require_admin_when_published: bool = True) -> JsonResponse | None:
    """
    出欠/試合参加/出席者追加 など「参加者変更系」APIの共通ガード
    - 公開済み: 一般は変更不可（幹事のみ）
    - 終了イベント: 一般は変更不可（幹事のみ）
    """
    is_admin = _is_event_admin_session(request, event.id)

    # ✅ 公開済み判定は DB で
    is_published = MatchSchedule.objects.filter(event=event, published=True).exists()

    if require_admin_when_published and is_published and not is_admin:
        return _json_forbidden("公開後は幹事のみ変更できます。", code="published_locked")

    if _is_event_ended(event) and not is_admin:
        return _json_forbidden("終了したイベントに対する出席者変更は幹事モードで行ってください。", code="ended_locked")

    return None


def _guard_admin_only(request, event) -> JsonResponse | None:
    if not _is_event_admin_session(request, event.id):
        return _json_forbidden("幹事モードでのみ操作できます。", code="admin_only")
    return None


# ============================================================
# Participant APIs
# ============================================================

@require_POST
def update_attendance(request):
    event_id = request.POST.get("event_id")
    attendance = (request.POST.get("attendance") or "").strip()

    if attendance not in ("yes", "no", "maybe", ""):
        return JsonResponse({"error": "bad_attendance"}, status=400)
    if not event_id:
        return JsonResponse({"error": "missing_event_id"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    blocked = _guard_participant_change(request, event, require_admin_when_published=True)
    if blocked:
        return blocked

    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club, is_active=True)
        member.touch()
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"error": "missing_target"}, status=400)

    old = ep.attendance or ""
    new = attendance or ""

    ep.attendance = new or None

    # =========================
    # A案：出欠が上位
    # =========================
    if new != "yes":
        # no/maybe/空 は強制OFF
        ep.participates_match = False
    else:
        # yes に変わった瞬間はデフォルトON
        if old != "yes":
            ep.participates_match = True
        # old==yes の場合は participates_match を触らない（ユーザーのOFFを尊重）

    ep.save(update_fields=["attendance", "participates_match", "updated_at"])
    return JsonResponse({
        "ok": True,
        "attendance": ep.attendance or "",
        "ep_id": ep.id,
        "participates_match": bool(ep.participates_match),
    })


@require_POST
def update_comment(request):
    event_id = request.POST.get("event_id")
    if not event_id:
        return JsonResponse({"error": "missing_event_id"}, status=400)
    event = get_object_or_404(Event, id=int(event_id))

    comment = (request.POST.get("comment") or "").strip()
    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club, is_active=True)
        member.touch()
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"error": "missing_target"}, status=400)

    ep.comment = comment
    ep.save(update_fields=["comment", "updated_at"])
    return JsonResponse({"ok": True, "ep_id": ep.id})


@require_POST
def set_participates_match(request):
    event_id = (request.POST.get("event_id") or "").strip()
    checked = request.POST.get("checked")
    if checked is None:
        checked = request.POST.get("value")

    if not event_id or checked not in ("true", "false"):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    blocked = _guard_participant_change(request, event, require_admin_when_published=True)
    if blocked:
        return blocked

    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club, is_active=True)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

    will_on = (checked == "true")

    # =========================
    # A案：attendance が yes 以外なら試合参加は許可しない
    # =========================
    if (ep.attendance or "") != "yes":
        will_on = False

    if ep.participates_match != will_on:
        ep.participates_match = will_on
        ep.save(update_fields=["participates_match", "updated_at"])

    return JsonResponse({"ok": True, "ep_id": ep.id, "participates_match": bool(ep.participates_match)})


@require_POST
def toggle_participant_flag(request):
    event_id = request.POST.get("event_id")
    flag_id = request.POST.get("flag_id")
    checked = request.POST.get("checked")

    if not event_id or not flag_id or checked not in ("true", "false"):
        return JsonResponse({"error": "bad_request"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))
    flagdef = get_object_or_404(ClubFlagDefinition, id=int(flag_id), club=event.club, is_active=True)

    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club, is_active=True)
        member.touch()
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"error": "missing_target"}, status=400)

    is_on = (checked == "true")

    obj, created = ParticipantFlag.objects.get_or_create(
        event_participant=ep,
        flag_definition=flagdef,
        defaults={"is_on": is_on},
    )
    if not created and obj.is_on != is_on:
        obj.is_on = is_on
        obj.save(update_fields=["is_on", "updated_at"])

    return JsonResponse({"ok": True, "ep_id": ep.id, "flag_id": flagdef.id, "checked": obj.is_on})


@require_POST
def add_guest_participant(request):
    event_id = request.POST.get("event_id")
    name = (request.POST.get("display_name") or request.POST.get("name") or "").strip()

    if not event_id or not name:
        return JsonResponse({"ok": False, "error": "required"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    blocked = _guard_participant_change(request, event, require_admin_when_published=True)
    if blocked:
        return blocked

    member = _get_or_create_member_for_name(event.club, name)
    if member:
        member.touch()
        ep = _get_or_create_ep(event, member, name)
    else:
        ep = EventParticipant.objects.create(event=event, member=None, display_name=name)

    return JsonResponse({"ok": True, "ep_id": ep.id, "display_name": ep.display_name})


# ============================================================
# Schedule
# ============================================================

@require_POST
def ajax_generate_schedule(request, event_id):
    event = get_object_or_404(Event, id=int(event_id))

    # ✅ 幹事のみ
    blocked = _guard_admin_only(request, event)
    if blocked:
        return blocked

    deny = _optional_admin_token_check(request, event.club)
    if deny:
        return deny

    participants = list(EventParticipant.objects.filter(event=event).order_by("id"))

    ids_str = (request.POST.get("participant_ids") or "").strip()
    if ids_str:
        try:
            selected_ids = {int(x) for x in ids_str.split(",") if x}
        except ValueError:
            return JsonResponse({"ok": False, "error": "bad_participant_ids"}, status=400)
        match_participants = [p for p in participants if p.id in selected_ids]
    else:
        # ✅ POSTが無い場合は Draftではなく「公開済み(=DB確定値)」を使う
        match_participants = [p for p in participants if p.participates_match]

    # ✅ generate_* は ep_id(int) 専用（名前文字列は渡さない）
    ep_ids = [int(p.id) for p in match_participants]
    match_count = len(ep_ids)

    DEFAULT_ROUNDS = 8
    DEFAULT_COURTS = 1

    game_type = request.POST.get("game_type", GameType.DOUBLES)
    if game_type not in (GameType.DOUBLES, GameType.SINGLES):
        game_type = GameType.DOUBLES

    num_rounds = _parse_int(
        request.POST.get("num_rounds"),
        default=DEFAULT_ROUNDS,
        min_v=1,
        max_v=20,
    ) or DEFAULT_ROUNDS

    num_courts = _parse_int(
        request.POST.get("num_courts"),
        default=DEFAULT_COURTS,
        min_v=1,
        max_v=12,
    ) or DEFAULT_COURTS

    # 面数上限（人数に対して不可能な組み合わせを潰す）
    per_court = 4 if game_type == GameType.DOUBLES else 2
    max_courts = max(1, (match_count // per_court)) if match_count >= per_court else 1
    num_courts = max(1, min(num_courts, max_courts))

    # 生成
    if match_count == 0:
        schedule = []
    else:
        schedule = (
            generate_singles_schedule(ep_ids, num_rounds, num_courts)
            if game_type == GameType.SINGLES
            else generate_doubles_schedule(ep_ids, num_rounds, num_courts)
        )

    # ============================================================
    # A案：Draft を公開元にするため「生成したら Draft を必ず保存」する
    #  - publish_schedule は Draft が無いと no_draft で落ちる仕様
    #  - GET(event_view)では Draft を消すので「生成→公開」は同一画面内で完結させる
    # ============================================================
    # participant_ids を「公開時に participates_match を確定反映」するため params_json に入れる
    participant_ids = [int(x) for x in ep_ids]

    params_json = {
        "game_type": game_type,
        "num_courts": int(num_courts),
        "num_rounds": int(num_rounds),
        "participant_ids": participant_ids,
    }

    MatchScheduleDraft.objects.update_or_create(
        event=event,
        defaults={
            "draft_json": schedule,
            "params_json": params_json,
        },
    )

    # 表示用ctx（_schedule_block.html 側で pill を一致させる）
    ctx = {
        "event": event,
        "schedule": schedule,
        "schedule_json": schedule,  # publish 用（json_script化）
        "stats": None,
        "ep_name_map": _build_ep_name_map(event),

        # ★pill一致
        "show_controls": True,
        "pill_game_type": game_type,
        "pill_num_courts": int(num_courts),
        "pill_num_rounds": int(num_rounds),
        "pill_match_count": int(match_count),
        "publish_state": _compute_publish_state(event, schedule_from_generation=schedule),
    }

    schedule_html = render_to_string("tennis/_schedule_block.html", ctx, request=request)
    stats_html = render_to_string("tennis/_stats_block.html", ctx, request=request)

    return JsonResponse(
        {
            "ok": True,
            "schedule_html": schedule_html,
            "stats_html": stats_html,
            "publish_state": ctx["publish_state"],
            "game_type": game_type,
            "num_courts": int(num_courts),
            "num_rounds": int(num_rounds),
            "match_count": int(match_count),
        }
    )


@require_POST
def ajax_update_event(request):
    """
    幹事：イベント編集（eventメタ更新 + cancelled toggle）
    - cancelled=1/0 だけでも更新できる
    - title/place/start_time/end_time は送信されてきたキーだけ更新
    """
    event_id = request.POST.get("event_id")
    admin_token = (request.POST.get("admin_token") or "").strip()

    if not event_id or not admin_token:
        return HttpResponseBadRequest("missing event_id/admin_token")

    try:
        event = Event.objects.select_related("club").get(id=event_id)
    except Event.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    # 認可：クラブのadmin_token一致
    if (event.club.admin_token or "").strip() != admin_token:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    changed_fields = []

    # ---- cancelled toggle ----
    if "cancelled" in request.POST:
        v = (request.POST.get("cancelled") or "").strip()
        next_cancelled = v in ("1", "true", "True", "yes", "on")
        if event.cancelled != next_cancelled:
            event.cancelled = next_cancelled
            changed_fields.append("cancelled")

    # ---- normal edit ----
    if "title" in request.POST:
        title = (request.POST.get("title") or "").strip()
        if (event.title or "") != title:
            event.title = title
            changed_fields.append("title")

    if "place" in request.POST:
        place = (request.POST.get("place") or "").strip()
        if (event.place or "") != place:
            event.place = place
            changed_fields.append("place")

    def _parse_hhmm(s: str):
        s = (s or "").strip()
        if not s:
            return None
        hh, mm = s.split(":")
        return time(int(hh), int(mm))

    if "start_time" in request.POST:
        next_start = _parse_hhmm(request.POST.get("start_time"))
        if event.start_time != next_start:
            event.start_time = next_start
            changed_fields.append("start_time")

    if "end_time" in request.POST:
        next_end = _parse_hhmm(request.POST.get("end_time"))
        if event.end_time != next_end:
            event.end_time = next_end
            changed_fields.append("end_time")

    if changed_fields:
        # updated_at は auto_now=True なので save() で更新される
        event.save(update_fields=changed_fields + ["updated_at"])

    # meta_text（event.html の表示用）
    meta_text = event.date.strftime("%Y-%m-%d")
    if event.start_time and event.end_time:
        meta_text += f" {event.start_time.strftime('%H:%M')}〜{event.end_time.strftime('%H:%M')}"
    elif event.start_time:
        meta_text += f" {event.start_time.strftime('%H:%M')}〜"
    elif event.end_time:
        meta_text += f" 〜{event.end_time.strftime('%H:%M')}"
    if event.place:
        meta_text += f" @ {event.place}"

    return JsonResponse({
        "ok": True,
        "event": {
            "id": event.id,
            "club_id": event.club_id,
            "title": event.title or "",
            "place": event.place or "",
            "date": event.date.strftime("%Y-%m-%d"),
            "start_time": event.start_time.strftime("%H:%M") if event.start_time else "",
            "end_time": event.end_time.strftime("%H:%M") if event.end_time else "",
            "cancelled": bool(event.cancelled),
            "meta_text": meta_text,
        }
    })


@require_POST
def publish_schedule(request):
    event_id = request.POST.get("event_id")
    if not event_id:
        return JsonResponse({"ok": False, "error": "bad_event_id"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    blocked = _guard_admin_only(request, event)
    if blocked:
        return blocked

    deny = _optional_admin_token_check(request, event.club)
    if deny:
        return deny

    force = request.POST.get("force") == "1"

    # ============================================================
    # A案：基本は Draft を公開元にする
    # ただし Draft が無い場合だけ POST schedule_json をフォールバック採用
    # （リロードで Draft が破棄されても公開できるようにする）
    # ============================================================
    schedule = None
    params = {}

    draft = MatchScheduleDraft.objects.filter(event=event).first()
    if draft and draft.draft_json:
        schedule = draft.draft_json
        params = (draft.params_json or {}) if isinstance(draft.params_json, dict) else {}
    else:
        raw = (request.POST.get("schedule_json") or "").strip()
        if not raw:
            return JsonResponse({"ok": False, "error": "no_draft"}, status=400)
        try:
            schedule = json.loads(raw)
        except Exception:
            return JsonResponse({"ok": False, "error": "bad_schedule_json"}, status=400)

        if not isinstance(schedule, list):
            return JsonResponse({"ok": False, "error": "bad_schedule_json"}, status=400)

        # フォールバック時は params が無いので最低限だけ推定（必要なら後で強化）
        params = {}

    game_type = (params.get("game_type") or GameType.DOUBLES)
    court_count = params.get("num_courts", params.get("court_count", 1))
    round_count = params.get("num_rounds", params.get("round_count", (len(schedule) or 1)))

    existing = MatchSchedule.objects.filter(event=event, published=True).first()
    if existing:
        has_any_score = MatchScore.objects.filter(match_schedule=existing).exclude(
            side_a_score__isnull=True,
            side_b_score__isnull=True,
        ).exists()
        if has_any_score and not force:
            return JsonResponse(
                {"ok": False, "error": "score_exists",
                 "message": "入力済みのスコアはすべて破棄されます。よろしいですか？"},
                status=409,
            )

    with transaction.atomic():
        ms, created = MatchSchedule.objects.get_or_create(
            event=event,
            published=True,
            defaults={
                "schedule_json": schedule,
                "game_type": game_type,
                "court_count": int(court_count),
                "round_count": int(round_count),
                "locked": False,
            },
        )

        if not created:
            if force:
                MatchScore.objects.filter(match_schedule=ms).delete()
                ms.locked = False

            ms.schedule_json = schedule
            ms.game_type = game_type
            ms.court_count = int(court_count)
            ms.round_count = int(round_count)
            ms.published = True
            ms.save(update_fields=[
                "schedule_json","game_type","court_count","round_count",
                "published","locked","updated_at"
            ])

        # Draft participant_ids がある時だけ participates_match を反映
        pids = params.get("participant_ids") or []
        fixed_pids = []
        for x in pids:
            try:
                fixed_pids.append(int(x))
            except Exception:
                pass

        if fixed_pids:
            EventParticipant.objects.filter(event=event).update(participates_match=False)
            EventParticipant.objects.filter(event=event, id__in=fixed_pids).update(participates_match=True)

        # 公開したら Draft 破棄（A案維持）
        MatchScheduleDraft.objects.filter(event=event).delete()

    return JsonResponse({"ok": True, "published": True, "locked": ms.locked})


# ============================================================
# Score
# ============================================================


@require_POST
def save_match_score(request):
    """
    1試合 = (match_schedule, round_no, court_no) をキーに1レコードで保持し、
    side(a/b) に応じて side_a_score / side_b_score を更新する。
    """
    event_id = request.POST.get("event_id")
    round_no = request.POST.get("round_no")
    court_no = request.POST.get("court_no")
    side = (request.POST.get("side") or "").strip().lower()  # "a" or "b"

    # value / score / score_value どれでも受ける（JS互換）
    value_raw = request.POST.get("value")
    if value_raw is None:
        value_raw = request.POST.get("score")
    if value_raw is None:
        value_raw = request.POST.get("score_value")

    # validate
    if not (event_id and round_no and court_no and side in ("a", "b")):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    try:
        round_no_i = int(round_no)
        court_no_i = int(court_no)
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_number"}, status=400)

    # 空欄は None（クリア）扱い
    v = None
    if value_raw is not None:
        s = str(value_raw).strip()
        if s != "":
            try:
                v = int(s)
            except ValueError:
                return JsonResponse({"ok": False, "error": "bad_score"}, status=400)
            if v < 0 or v > 99:
                return JsonResponse({"ok": False, "error": "out_of_range"}, status=400)

    event = get_object_or_404(Event, pk=int(event_id))

    # 公開済みの対戦表が前提（なければ保存できない）
    match_schedule = MatchSchedule.objects.filter(event=event, published=True).first()
    if not match_schedule:
        return JsonResponse({"ok": False, "error": "no_published_schedule"}, status=409)

    with transaction.atomic():
        # 対戦表行をロック（並行更新対策）
        match_schedule = MatchSchedule.objects.select_for_update().get(pk=match_schedule.pk)

        score_obj, _created = MatchScore.objects.select_for_update().get_or_create(
            match_schedule=match_schedule,
            round_no=round_no_i,
            court_no=court_no_i,
            defaults={"side_a_score": None, "side_b_score": None},
        )

        if side == "a":
            score_obj.side_a_score = v
        else:
            score_obj.side_b_score = v

        score_obj.save()  # updated_at 更新

        # 1件でも入力されたら locked=True（以後 publish の挙動に使える）
        if (not match_schedule.locked) and (v is not None):
            match_schedule.locked = True
            match_schedule.save(update_fields=["locked", "updated_at"])

    return JsonResponse({"ok": True, "side": side, "value": v})
