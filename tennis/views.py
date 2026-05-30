# tennis/views.py
import calendar
import json
import datetime as dt
import logging
from collections import defaultdict
from datetime import time

from django.db import transaction, models
from django.db.models import Max
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.template.loader import render_to_string

from .utils import generate_doubles_schedule, generate_singles_schedule
from .models import (
    ActorTokenKind,
    AuditLog,
    Club,
    Event,
    Member,
    EventParticipant,
    ClubFlagDefinition,
    EventFlagDefinition,
    ParticipantFlag,
    MatchSchedule,
    MatchScheduleDraft,
    MatchScore,
    GameType,
    EventDisplaySetting,
    ClubMemberClass,
)

# ============================================================
# Config
# ============================================================

MAX_FLAGS = 3  # V1仕様：クラブごとのフラグ最大数

MAX_EVENT_FLAGS = 2

log = logging.getLogger(__name__)


# ============================================================
# Session Auth (token-based admin access)
#  - eventページの「幹事モード」は、URL token 一致でセッションにフラグを立てる方式
# ============================================================

def _admin_session_key(event_id: int) -> str:
    return f"tennis_event_admin:{event_id}"


def _mark_event_admin_session(request, event_id: int) -> None:
    request.session[_admin_session_key(event_id)] = True
    request.session.modified = True  # セッション保存を確実に


def _is_event_admin_session(request, event_id: int) -> bool:
    return bool(request.session.get(_admin_session_key(event_id), False))


# ============================================================
# Parse / DateTime Helpers
# ============================================================

def _parse_int(value, default=None, min_v=None, max_v=None):
    """int変換＋範囲クランプ。失敗時は default。"""
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
    """YYYY-MM-DD -> date。失敗時は None。"""
    try:
        return dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_hhmm(s: str):
    """HH:MM -> time。空欄は None。失敗時は None。"""
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
    - 過去日 -> 終了
    - 今日 かつ end_time がある -> now > end_time で終了
    - end_time 無し -> 今日分は終了扱いにしない
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


# ============================================================
# Calendar Helpers (club_home/settings 用)
# ============================================================

def _get_month_range(year: int, month: int):
    first_day = dt.date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day = dt.date(year, month, last_day_num)
    return first_day, last_day


def _build_month_calendar(year: int, month: int, events_qs):
    """events_qs を日付キーでまとめて、monthdatescalendar に乗せる。"""
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


# ============================================================
# Member / Participant Helpers
# ============================================================

def _next_member_no(club: Club) -> int:
    """クラブ内の member_no を連番採番。"""
    last = (
        Member.objects
        .filter(club=club)
        .aggregate(m=Max("member_no"))
        .get("m")
    )
    return int(last or 0) + 1


@transaction.atomic
def _get_or_create_member_for_name(club: Club, name: str) -> Member | None:
    """
    同名Memberがいればそれを使う（戦績継承のキー）
    無ければ非固定Memberとして作成（臨時参加）
    """
    name = (name or "").strip()
    if not name:
        return None

    m = (
        Member.objects
        .filter(club=club, display_name=name)
        .order_by("id")  # 最古を採用
        .first()
    )
    if m:
        return m

    return Member.objects.create(
        club=club,
        member_no=_next_member_no(club),
        display_name=name,
        is_fixed=False,
    )


def _get_or_create_ep(event: Event, member: Member | None, display_name: str) -> EventParticipant:
    """
    EP作成ルール：
    - memberあり : unique(event, member) を満たすよう get_or_create
    - memberなし : display_name で都度作成（互換用）
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


def _build_ep_name_map(event: Event) -> dict:
    """
    schedule_json 内の値が
    - ep_id(int)
    - 旧互換：名前文字列
    の両方を想定して、名前解決用マップを作る。
    """
    m = {}
    for ep in EventParticipant.objects.filter(event=event).select_related("member").order_by("id"):
        name = ep.member.display_name if ep.member_id and ep.member else (ep.display_name or "")
        if ep.id is not None:
            m[int(ep.id)] = name
        if name:
            m[str(name)] = name  # 互換キー
    return m


# ============================================================
# Schedule / Score Helpers
# ============================================================

def _build_score_map(match_schedule: MatchSchedule):
    """(round_no, court_no) -> (a_score, b_score)"""
    score_map = {}
    qs = MatchScore.objects.filter(match_schedule=match_schedule)
    for s in qs:
        score_map[(int(s.round_no), int(s.court_no))] = (s.side_a_score, s.side_b_score)
    return score_map


def _merge_scores_into_schedule(schedule_json, score_map):
    """schedule_json に score_map を合成して、テンプレ表示用構造へ整形。"""
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


# ============================================================
# publish_state
# ============================================================

def _norm_schedule_json(x):
    return x if x is not None else []


def _compute_publish_state(event, schedule_from_generation=None):
    """
    schedule_from_generation を基準に、公開状態を返す。
    - no_schedule : そもそも生成結果なし
    - ready       : 生成はあるが published が無い
    - published   : published と一致
    - changed     : published と差分あり
    """
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


def _require_club_admin_token(request, club):
    """
    幹事トークン認可（club系管理APIの統一実装）。

    POST の admin_token が club.admin_token と一致しなければ
    403 {"ok": False, "error": "forbidden", "message": ...} を返す。OKなら None。

    ※ 旧実装はエンドポイントごとに status(400/403) や error 文字列がバラついていたが、
       本ヘルパで 403 / "forbidden" に統一する（フロントは ok/error の有無で判定しており
       認可エラー値での機能分岐は無いことを確認済み）。
    """
    admin_token = (request.POST.get("admin_token") or "").strip()
    if not admin_token or admin_token != (club.admin_token or ""):
        return JsonResponse(
            {"ok": False, "error": "forbidden", "message": "幹事のみ操作できます。"},
            status=403,
        )
    return None


# ============================================================
# 自動メンバー整理（未使用の非固定メンバーを期限到来で削除）
# ============================================================

INACTIVITY_DAYS = 14   # 警告開始（登録からの日数）
DELETION_DAYS = 21     # 自動削除（登録からの日数）


def _run_member_auto_cleanup(club):
    """
    幹事ページ表示時に呼ぶ。クラブ内の非固定メンバーについて：

    永続セーフ条件：EPのうち1つでも attendance="yes" があるメンバーは削除されない。
    削除対象：上記以外の非固定メンバー（出欠が yes 以外のみ、または EP が無い）。

    「最後の操作タイミング」= max(Member.updated_at, 関連EPのupdated_at, 関連PFのupdated_at)
      - 出欠を「欠席」「未定」にした、フラグON/OFF、コメント編集 等の操作で更新される
      - これら全てが「削除延長」要因（操作なら何でもカウントダウンを延ばす）

    - 最後の操作から DELETION_DAYS 以上経過 → 削除（AuditLog 記録）
    - 最後の操作から INACTIVITY_DAYS 以上 DELETION_DAYS 未満 → 警告

    Returns: List[Dict]
      [{"display_name": str, "days_left": int}, ...]
    """
    today = timezone.localdate()
    cutoff_delete = today - dt.timedelta(days=DELETION_DAYS)
    cutoff_warn = today - dt.timedelta(days=INACTIVITY_DAYS)

    # 候補：非固定 かつ 一度も「出欠=yes」を付けていない（永続セーフから除外）
    candidates = list(
        Member.objects
        .filter(club=club, is_fixed=False)
        .exclude(event_participants__attendance="yes")
        .annotate(
            latest_ep_updated=Max("event_participants__updated_at"),
            latest_pf_updated=Max("event_participants__flags__updated_at"),
        )
        .order_by("created_at", "id")
    )

    warnings = []
    for m in candidates:
        # 最後の操作タイミング（Member自身・EP・PF の updated_at の最大値）
        ts_list = [m.updated_at]
        if m.latest_ep_updated:
            ts_list.append(m.latest_ep_updated)
        if m.latest_pf_updated:
            ts_list.append(m.latest_pf_updated)
        last_activity = max(ts_list)
        last_activity_date = last_activity.date() if last_activity else None
        if last_activity_date is None:
            continue

        if last_activity_date <= cutoff_delete:
            # 削除対象：race対策として直前に yes EP の有無を再確認
            try:
                with transaction.atomic():
                    if EventParticipant.objects.filter(member=m, attendance="yes").exists():
                        continue  # 直前に yes EP が付いたので保護
                    AuditLog.objects.create(
                        club=club,
                        event=None,
                        actor_token_kind=ActorTokenKind.ADMIN,
                        action="auto_cleanup_member",
                        payload_json={
                            "member_id": m.id,
                            "display_name": m.display_name,
                            "last_activity": last_activity.isoformat(),
                            "days_inactive": (today - last_activity_date).days,
                        },
                    )
                    m.delete()
            except Exception as e:
                log.warning("auto_cleanup_member delete failed: member_id=%s err=%s", m.id, e)
            continue

        if last_activity_date <= cutoff_warn:
            days_left = DELETION_DAYS - (today - last_activity_date).days
            if 1 <= days_left <= (DELETION_DAYS - INACTIVITY_DAYS):
                warnings.append({
                    "display_name": m.display_name,
                    "days_left": days_left,
                })

    return warnings


# ============================================================
# Ranking（現行踏襲）
# ============================================================

def _collect_schedule_ep_ids(schedule_json, sink: set) -> None:
    """schedule_json の team1/team2 に含まれる ep_id(int) を sink に集める。"""
    for r in (schedule_json or []):
        for m in (r.get("matches") or []):
            for p in (m.get("team1") or []):
                if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
                    sink.add(int(p))
            for p in (m.get("team2") or []):
                if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
                    sink.add(int(p))


def _compute_ranking_from(events, ms_by_event, ep_map, min_matches):
    """
    1ゲームタイプ分の集計（旧 build_month_ranking 本体）。
    ms_by_event / ep_map は呼び出し側で用意して渡す（クエリ共有のため）。
    """
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
        if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
            ep = ep_map.get(int(p))
            if ep:
                if ep.member_id:
                    name = ep.member.display_name if ep.member else (ep.display_name or f"Member#{ep.member_id}")
                    return (("m", ep.member_id), name)
                gname = (ep.display_name or f"Guest#{ep.id}").strip()
                return (("g", gname), gname)

            return (("g", str(p)), str(p))

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


def build_month_rankings(events_qs, game_types, min_matches: int = 3):
    """
    複数ゲームタイプのランキングを1パスで集計する。
    MatchSchedule / EventParticipant のクエリ・schedule_json パースを
    タイプ間で共有するため、club_home の二重計算を解消する。

    戻り値: {game_type: {"ranked": [...], "others": [...]}}
    各タイプの結果は build_month_ranking(events_qs, game_type) と一致する。
    """
    game_types = list(game_types)
    events = list(events_qs)
    result = {gt: {"ranked": [], "others": []} for gt in game_types}
    if not events:
        return result

    # 公開済み対戦表を1クエリで取得し、game_type 別に振り分け
    ms_by_type = {gt: {} for gt in game_types}
    for ms in MatchSchedule.objects.filter(
        event__in=events, published=True, game_type__in=game_types
    ):
        bucket = ms_by_type.get(ms.game_type)
        if bucket is not None:
            bucket[ms.event_id] = ms

    # 全タイプ横断で ep_id を集め、EP を1クエリでまとめて引く
    ep_ids: set = set()
    for gt in game_types:
        for ms in ms_by_type[gt].values():
            _collect_schedule_ep_ids(ms.schedule_json, ep_ids)

    ep_map = {
        ep.id: ep
        for ep in EventParticipant.objects.filter(id__in=list(ep_ids)).select_related("member")
    }

    for gt in game_types:
        result[gt] = _compute_ranking_from(events, ms_by_type[gt], ep_map, min_matches)
    return result


def build_month_ranking(events_qs, game_type: str, min_matches: int = 3):
    """単一ゲームタイプのランキング（後方互換）。中身は build_month_rankings に委譲。"""
    return build_month_rankings(events_qs, [game_type], min_matches)[game_type]


# ============================================================
# Pages
# ============================================================

@require_http_methods(["GET", "POST"])
def index(request):
    """
    トップ = クラブ作成
    作成後は「幹事ホーム（club_home_admin）」へ遷移
    """
    if request.method == "POST":
        name = (request.POST.get("club_name") or "").strip()
        if not name:
            return HttpResponseBadRequest("クラブ名は必須です。")

        club = Club.objects.create(name=name)
        return redirect(
            "tennis:club_home_admin",
            club_public_token=club.public_token,
            club_admin_token=club.admin_token
        )

    return render(request, "tennis/index.html", {"show_topbar": False})


def club_settings(request, club_public_token, club_admin_token):
    club = get_object_or_404(
        Club,
        public_token=club_public_token,
        admin_token=club_admin_token,
        is_active=True
    )

    member_url = request.build_absolute_uri(reverse("tennis:club_home", args=[club.public_token]))
    admin_home_url = request.build_absolute_uri(reverse("tennis:club_home_admin", args=[club.public_token, club.admin_token]))
    admin_settings_url = request.build_absolute_uri(reverse("tennis:club_settings", args=[club.public_token, club.admin_token]))

    today = timezone.localdate()
    year = _parse_int(request.GET.get("year"), default=today.year, min_v=2000, max_v=2100) or today.year
    month = _parse_int(request.GET.get("month"), default=today.month, min_v=1, max_v=12) or today.month

    first_day, last_day = _get_month_range(year, month)
    events_qs = (
        Event.objects
        .filter(club=club, date__gte=first_day, date__lte=last_day)
        .order_by("date", "start_time", "id")
    )

    club_flags = list(
        ClubFlagDefinition.objects
        .filter(club=club, is_active=True)
        .order_by("display_order", "id")
    )

    month_weeks = _build_month_calendar(year, month, events_qs)

    # 固定/非固定どちらも表示（幹事が固定化できる）
    members = list(
        Member.objects
        .filter(club=club)
        .order_by("member_no", "id")
    )

    classes = list(
        ClubMemberClass.objects.filter(club=club, is_active=True)
        .order_by("display_order", "id")
    )

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
            "members": members,
            "classes": classes,
            "is_admin": True,
            "show_topbar": True,
            "cleanup_warnings": _run_member_auto_cleanup(club),
        },
    )


@require_http_methods(["GET"])
def club_data(request, club_public_token, club_admin_token):
    """
    幹事専用：出欠・共通フラグ・固有フラグのデータ集計表ページ。
    期間内のイベントを対象に、メンバー×イベントの3種のマトリクスを構築する。
    """
    club = get_object_or_404(Club, public_token=club_public_token, is_active=True)
    if club.admin_token != club_admin_token:
        return HttpResponseBadRequest("admin token mismatch")

    # 期間：デフォルトは今月の1日〜末日
    today = timezone.localdate()
    default_start = today.replace(day=1)
    next_month = (default_start + dt.timedelta(days=32)).replace(day=1)
    default_end = next_month - dt.timedelta(days=1)

    start_d = _parse_date_yyyy_mm_dd((request.GET.get("start") or "").strip()) or default_start
    end_d = _parse_date_yyyy_mm_dd((request.GET.get("end") or "").strip()) or default_end
    if end_d < start_d:
        end_d = start_d

    # 期間内イベントとEPを一括取得
    events = list(
        Event.objects.filter(club=club, date__gte=start_d, date__lte=end_d)
        .order_by("date", "start_time", "id")
    )
    eps = list(
        EventParticipant.objects
        .filter(event__in=events)
        .select_related("member")
        .order_by("id")
    )
    ep_ids = [ep.id for ep in eps]

    # 全メンバー（固定→非固定、member_no/displayname順）
    all_members = list(
        Member.objects.filter(club=club).order_by("-is_fixed", "member_no", "id")
    )

    # 行を構築：先に全メンバー、次に期間内に登場した退会者/純ゲスト（display_nameで集約）
    rows = []
    member_key_set = set()
    for m in all_members:
        rows.append({
            "key": f"m{m.id}",
            "display_name": m.display_name,
            "withdrawn": False,
            "is_fixed": m.is_fixed,
        })
        member_key_set.add(("m", m.id))

    seen_guest_names = set()
    guest_rows = []
    for ep in eps:
        if ep.member_id and ("m", ep.member_id) in member_key_set:
            continue
        name = (ep.display_name or "").strip() or f"#{ep.id}"
        if name in seen_guest_names:
            continue
        seen_guest_names.add(name)
        guest_rows.append({
            "key": f"g_{name}",
            "display_name": name,
            "withdrawn": bool(ep.member_deleted),
            "is_fixed": False,
        })
    guest_rows.sort(key=lambda r: r["display_name"])
    rows.extend(guest_rows)

    # EP参照表：row_key -> event_id -> ep
    ep_lookup: dict = {}
    for ep in eps:
        if ep.member_id and ("m", ep.member_id) in member_key_set:
            row_key = f"m{ep.member_id}"
        else:
            name = (ep.display_name or "").strip() or f"#{ep.id}"
            row_key = f"g_{name}"
        ep_lookup.setdefault(row_key, {}).setdefault(ep.event_id, ep)

    # 1) 出欠表
    attendance_table = []
    for row in rows:
        cells = []
        per_ev = ep_lookup.get(row["key"], {})
        for event in events:
            ep = per_ev.get(event.id)
            cells.append({"attendance": (ep.attendance if ep else None)})
        attendance_table.append({"row": row, "cells": cells})

    # 2) 共通フラグ表（フラグごと）
    #    アクティブ ∪ 期間内にデータ有るもの（削除済みでも履歴を表示）
    all_club_flags = list(
        ClubFlagDefinition.objects.filter(club=club).order_by("display_order", "id")
    )
    club_flag_ids_with_data: set = set()
    if ep_ids and all_club_flags:
        club_flag_ids_with_data = set(
            ParticipantFlag.objects
            .filter(
                event_participant_id__in=ep_ids,
                club_flag_definition_id__in=[f.id for f in all_club_flags],
            )
            .values_list("club_flag_definition_id", flat=True)
            .distinct()
        )
    club_flags = [
        f for f in all_club_flags
        if f.is_active or f.id in club_flag_ids_with_data
    ]

    pf_club: dict = {}
    if ep_ids and club_flags:
        for pf in ParticipantFlag.objects.filter(
            event_participant_id__in=ep_ids,
            club_flag_definition_id__in=[f.id for f in club_flags],
        ).values("event_participant_id", "club_flag_definition_id", "is_on", "value"):
            pf_club.setdefault(pf["club_flag_definition_id"], {})[
                pf["event_participant_id"]
            ] = (bool(pf["is_on"]), pf["value"])

    def _cell_text(input_mode, pf_tuple):
        if not pf_tuple:
            return ""
        is_on, value = pf_tuple
        if input_mode == "digit":
            return "" if value is None else str(value)
        return "✓" if is_on else ""

    club_flag_tables = []
    for f in club_flags:
        f_rows = []
        for row in rows:
            cells = []
            per_ev = ep_lookup.get(row["key"], {})
            for event in events:
                ep = per_ev.get(event.id)
                pf_tuple = pf_club.get(f.id, {}).get(ep.id) if ep else None
                cells.append({"text": _cell_text(f.input_mode, pf_tuple)})
            f_rows.append({"row": row, "cells": cells})
        club_flag_tables.append({
            "flag": f,
            "is_active": f.is_active,
            "rows": f_rows,
        })

    # 3) 固有フラグ表（イベントごとに1ブロック）
    event_flag_defs = list(
        EventFlagDefinition.objects
        .filter(event__in=events, is_active=True)
        .order_by("event_id", "display_order", "id")
    )
    efs_by_event: dict = defaultdict(list)
    for f in event_flag_defs:
        efs_by_event[f.event_id].append(f)

    pf_event: dict = {}
    if ep_ids and event_flag_defs:
        for pf in ParticipantFlag.objects.filter(
            event_participant_id__in=ep_ids,
            event_flag_definition_id__in=[f.id for f in event_flag_defs],
        ).values("event_participant_id", "event_flag_definition_id", "is_on", "value"):
            pf_event.setdefault(pf["event_flag_definition_id"], {})[
                pf["event_participant_id"]
            ] = (bool(pf["is_on"]), pf["value"])

    event_flag_blocks = []
    for event in events:
        efs = efs_by_event.get(event.id) or []
        if not efs:
            continue
        block_rows = []
        for row in rows:
            cells = []
            ep = ep_lookup.get(row["key"], {}).get(event.id)
            for f in efs:
                pf_tuple = pf_event.get(f.id, {}).get(ep.id) if ep else None
                cells.append({"text": _cell_text(f.input_mode, pf_tuple)})
            block_rows.append({"row": row, "cells": cells})
        event_flag_blocks.append({
            "event": event,
            "flags": efs,
            "rows": block_rows,
        })

    settings_url = reverse("tennis:club_settings", args=[club.public_token, club.admin_token])

    return render(request, "tennis/club_data.html", {
        "club": club,
        "club_public_token": club_public_token,
        "club_admin_token": club_admin_token,
        "start_date": start_d,
        "end_date": end_d,
        "events": events,
        "rows": rows,
        "attendance_table": attendance_table,
        "club_flag_tables": club_flag_tables,
        "event_flag_blocks": event_flag_blocks,
        "settings_url": settings_url,
        "is_admin": True,
        "show_topbar": True,
        "cleanup_warnings": _run_member_auto_cleanup(club),
    })


def _parse_int_or_none(v):
    try:
        return int(v)
    except Exception:
        return None


@require_http_methods(["GET"])
def member_detail(request, club_public_token, member_id, club_admin_token=None):
    """
    メンバー個人ページ（一般・幹事共通）。
    - 名前編集（一般・幹事とも可。既存の "誰でも編集" 仕様を継承）
    - 削除ボタン（幹事モード・非固定メンバーのみ表示）
    - 戦績集計サマリ（シングルス／ダブルス別、全期間）
    - 試合履歴（公開済み MatchSchedule の schedule_json + MatchScore から構築）
    """
    club = get_object_or_404(Club, public_token=club_public_token, is_active=True)
    is_admin = False
    if club_admin_token is not None:
        if club.admin_token != club_admin_token:
            return HttpResponseBadRequest("admin token mismatch")
        is_admin = True

    member = get_object_or_404(Member, id=int(member_id), club=club)

    # このメンバーの EP id 集合
    my_ep_ids = set(
        EventParticipant.objects.filter(member=member).values_list("id", flat=True)
    )

    # クラブの公開済み MatchSchedule を新しい順に
    schedules = list(
        MatchSchedule.objects
        .filter(event__club=club, published=True)
        .select_related("event")
        .order_by("-event__date", "-event__id")
    )

    # 試合一覧から出てくる全 EP id を収集（対戦相手・パートナー名解決用）
    all_ep_ids = set()
    for ms in schedules:
        for r in (ms.schedule_json or []):
            for m in (r.get("matches") or []):
                for p in (m.get("team1") or []) + (m.get("team2") or []):
                    pi = _parse_int_or_none(p)
                    if pi is not None:
                        all_ep_ids.add(pi)

    ep_map = {
        ep.id: ep for ep in
        EventParticipant.objects.filter(id__in=list(all_ep_ids)).select_related("member")
    }

    def _name_of(p):
        ep = ep_map.get(_parse_int_or_none(p))
        if not ep:
            return str(p)
        if ep.member_id and ep.member:
            return ep.member.display_name
        return ep.display_name or str(p)

    stats = {
        "singles": {"matches": 0, "wins": 0, "losses": 0, "draws": 0, "gf": 0, "ga": 0},
        "doubles": {"matches": 0, "wins": 0, "losses": 0, "draws": 0, "gf": 0, "ga": 0},
    }
    matches_history = []

    for ms in schedules:
        score_map = _build_score_map(ms)
        game_type = ms.game_type or GameType.DOUBLES

        for r in (ms.schedule_json or []):
            round_no = int(r.get("round") or 0)
            for m in (r.get("matches") or []):
                court_no = int(m.get("court") or 0)
                t1_raw = m.get("team1") or []
                t2_raw = m.get("team2") or []
                t1 = [_parse_int_or_none(p) for p in t1_raw]
                t2 = [_parse_int_or_none(p) for p in t2_raw]
                t1 = [p for p in t1 if p is not None]
                t2 = [p for p in t2 if p is not None]

                in_t1 = any(p in my_ep_ids for p in t1)
                in_t2 = any(p in my_ep_ids for p in t2)
                if not (in_t1 or in_t2):
                    continue

                s1, s2 = score_map.get((round_no, court_no), (None, None))

                if in_t1:
                    my_team = t1
                    opp_team = t2
                    my_score, opp_score = s1, s2
                else:
                    my_team = t2
                    opp_team = t1
                    my_score, opp_score = s2, s1

                # スコア両方ある場合のみ集計
                if my_score is not None and opp_score is not None:
                    b = stats.get(game_type)
                    if b is not None:
                        b["matches"] += 1
                        b["gf"] += int(my_score)
                        b["ga"] += int(opp_score)
                        if my_score > opp_score:
                            b["wins"] += 1
                        elif my_score < opp_score:
                            b["losses"] += 1
                        else:
                            b["draws"] += 1

                partners = [_name_of(p) for p in my_team if p not in my_ep_ids]
                opponents = [_name_of(p) for p in opp_team]

                if my_score is None or opp_score is None:
                    result = ""
                elif my_score > opp_score:
                    result = "勝"
                elif my_score < opp_score:
                    result = "負"
                else:
                    result = "分"

                matches_history.append({
                    "date": ms.event.date,
                    "event_title": ms.event.title or "練習",
                    "event_id": ms.event.id,
                    "game_type": game_type,
                    "round_no": round_no,
                    "court_no": court_no,
                    "partners": partners,
                    "opponents": opponents,
                    "my_score": my_score,
                    "opp_score": opp_score,
                    "has_score": my_score is not None and opp_score is not None,
                    "result": result,
                })

    for gt in ("singles", "doubles"):
        s = stats[gt]
        m = s["matches"]
        s["win_pct"] = round((s["wins"] / m) * 100, 1) if m else 0.0
        gf, ga = s["gf"], s["ga"]
        s["gp_pct"] = round((gf / (gf + ga)) * 100, 1) if (gf + ga) else 0.0
        s["diff"] = gf - ga

    # 戻り先（来た元のページ） — referer があればそれ、無ければクラブホーム
    back_url = request.META.get("HTTP_REFERER") or reverse(
        "tennis:club_home_admin" if is_admin else "tennis:club_home",
        args=[club.public_token, club.admin_token] if is_admin else [club.public_token],
    )

    stats_blocks = [
        ("singles", "シングルス", stats["singles"]),
        ("doubles", "ダブルス", stats["doubles"]),
    ]

    return render(request, "tennis/member_detail.html", {
        "club": club,
        "member": member,
        "is_admin": is_admin,
        "stats_blocks": stats_blocks,
        "matches_history": matches_history,
        "back_url": back_url,
        "show_topbar": True,
        "cleanup_warnings": _run_member_auto_cleanup(club) if is_admin else [],
    })


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
        Event.objects
        .filter(club=club, date__gte=first, date__lt=next_month_date)
        .order_by("date", "start_time", "id")
    )

    month_weeks = _build_month_calendar(year, month, events_qs)

    rankings = build_month_rankings(events_qs, [GameType.DOUBLES, GameType.SINGLES])
    ranking_doubles = rankings[GameType.DOUBLES]
    ranking_singles = rankings[GameType.SINGLES]

    prev_month_date = (first - dt.timedelta(days=1)).replace(day=1)
    prev_year, prev_month = prev_month_date.year, prev_month_date.month
    next_year, next_month = next_month_date.year, next_month_date.month

    settings_url = ""
    if is_admin:
        settings_url = reverse("tennis:club_settings", args=[club.public_token, club.admin_token])

    member_url = request.build_absolute_uri(reverse("tennis:club_home", args=[club.public_token]))
    admin_url = request.build_absolute_uri(reverse("tennis:club_home_admin", args=[club.public_token, club.admin_token]))

    save_display_settings_url = reverse("tennis:save_event_display_setting")

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
            "cleanup_warnings": _run_member_auto_cleanup(club) if is_admin else [],
        },
    )


# ============================================================
# Event View（仕様確定版）
# - 既存イベントは event_member_class だけを見る（Member fallback禁止）
# - event_member_class が NULL の行は「このイベントの初回表示」でスナップショット埋め
# ============================================================



def _resolve_event_display_settings(event):
    """
    イベント表示設定を (display_settings: dict, source: str) で返す。
    DB に EventDisplaySetting があれば as_dict()/"db"、無ければデフォルト/"default"。
    """
    default = {
        "common_flags": True,
        "event_flags": False,
        "class": True,
        "schedule": True,
    }
    try:
        return event.display_setting.as_dict(), "db"  # OneToOne 想定
    except EventDisplaySetting.DoesNotExist:
        return default, "default"


def _load_participant_flag_states(event, club, event_flags):
    """
    参加者フラグ状態（クラブ共通 / イベント固有）を1クエリで取得し、メモリ上で振り分ける。
    取得集合は旧実装の「共通フラグクエリ ∪ 固有フラグクエリ」と一致：
      - 共通: event内 かつ club_flag_definition__club=club
      - 固有: event内 かつ event_flag_definition が当該イベントのアクティブフラグ
    （CheckConstraint により1行は共通/固有のどちらか一方のみ → 振り分けは排他）

    Returns: (flag_states_on, flag_states_val, event_flag_states_on, event_flag_states_val)
      いずれも defaultdict(dict): {ep_id: {flag_def_id: 値}}
    """
    event_flag_ids = [f.id for f in event_flags]

    pf_qs = (
        ParticipantFlag.objects
        .filter(event_participant__event=event)
        .filter(
            models.Q(club_flag_definition__club=club)
            | models.Q(event_flag_definition_id__in=event_flag_ids)
        )
        .values(
            "event_participant_id",
            "club_flag_definition_id",
            "event_flag_definition_id",
            "is_on",
            "value",
        )
    )

    flag_states_on = defaultdict(dict)
    flag_states_val = defaultdict(dict)
    event_flag_states_on = defaultdict(dict)
    event_flag_states_val = defaultdict(dict)

    for pf in pf_qs:
        ep_id = pf["event_participant_id"]
        if pf["club_flag_definition_id"] is not None:
            fd_id = pf["club_flag_definition_id"]
            flag_states_on[ep_id][fd_id] = bool(pf["is_on"])
            flag_states_val[ep_id][fd_id] = pf["value"]
        elif pf["event_flag_definition_id"] is not None:
            fd_id = pf["event_flag_definition_id"]
            event_flag_states_on[ep_id][fd_id] = bool(pf["is_on"])
            event_flag_states_val[ep_id][fd_id] = pf["value"]

    return flag_states_on, flag_states_val, event_flag_states_on, event_flag_states_val


def _build_fixed_rows(members, eps_by_member):
    """
    固定メンバーの参加者テーブル行を組み立てる。
    EP が無い固定メンバー（未登録行）も行を作り、ep_id=None・出欠未設定で返す。
    """
    rows = []
    for m in members:
        ep = eps_by_member.get(m.id)

        display_name = (
            ep.member.display_name
            if (ep and ep.member_id and ep.member)
            else (ep.display_name if ep else (m.display_name or ""))
        )

        if ep:
            mc = getattr(ep, "event_member_class", None)
            class_name_compat = (ep.class_name or "")
            attendance = ep.attendance
            comment = ep.comment or ""
            participates_match = bool(ep.participates_match)
            ep_id = ep.id
        else:
            mc = getattr(m, "member_class", None)
            class_name_compat = ""
            attendance = None
            comment = ""
            participates_match = False
            ep_id = None

        rows.append({
            "member_id": m.id,
            "ep_id": ep_id,
            "display_name": display_name,

            "attendance": attendance,
            "comment": comment,
            "participates_match": participates_match,

            "member_class_id": mc.id if mc else None,
            "member_class_name": (mc.name or "") if mc else "",

            # 退会（メンバー削除）済みEPの印
            "withdrawn": bool(ep.member_deleted) if ep else False,

            # 旧互換
            "class_name": class_name_compat,
        })
    return rows


def _build_guest_rows(event, member_ids, is_past_event=False):
    """
    固定メンバー以外（ゲスト/非固定メンバー）の参加者テーブル行を組み立てる。
    - 退会(member削除)済みEPは常にグレーアウト。
    - 過去イベント(is_past_event)では、入会しなかったゲスト＝ゲスト行すべてをグレーアウト。
    """
    guest_eps = (
        EventParticipant.objects
        .filter(event=event)
        .exclude(member_id__in=member_ids)
        .select_related("member", "event_member_class")
        .order_by("id")
    )

    rows = []
    for ep in guest_eps:
        display_name = (
            ep.member.display_name
            if (ep.member_id and ep.member)
            else (ep.display_name or "")
        )
        mc = getattr(ep, "event_member_class", None)

        rows.append({
            "ep_id": ep.id,
            "member_id": ep.member_id,
            "display_name": display_name,

            "attendance": ep.attendance,
            "comment": ep.comment or "",
            "participates_match": bool(ep.participates_match),

            "member_class_id": mc.id if mc else None,
            "member_class_name": (mc.name or "") if mc else "",

            # グレーアウト対象：退会済み、または過去イベントのゲスト全員
            "withdrawn": bool(ep.member_deleted) or is_past_event,

            # 旧互換
            "class_name": ep.class_name or "",
        })
    return rows


@ensure_csrf_cookie
def event_view(request, club_public_token, event_id, club_admin_token=None):
    """
    イベントページ（public/admin 共通）

    - admin URL の場合:
        /c/<public>/e/<event_id>/admin/<admin_token> など
      → token一致なら is_admin=True とし、当該 event の admin セッションを立てる

    - 表示設定:
        EventDisplaySetting があれば DB 値（source="db"）
        無ければデフォルト（source="default"）
      ※ JS は #page-hooks の dataset を正として読む前提（必ず JSON 文字列を供給する）

    - 重要: GET では DB を書かない（踏襲）
    - 重要: MatchScheduleDraft は GET の度に破棄（踏襲）
    """

    # ============================================================
    # 1) 基本取得 & admin 判定
    # ============================================================
    club = get_object_or_404(Club, public_token=club_public_token, is_active=True)
    event = get_object_or_404(Event, id=int(event_id), club=club)

    is_admin = False
    if club_admin_token is not None:
        if club.admin_token != club_admin_token:
            return HttpResponseBadRequest("admin token mismatch")
        is_admin = True
        _mark_event_admin_session(request, event.id)

    # ============================================================
    # 2) 定義系（フラグ / クラス）
    # ============================================================
    flags = list(
        ClubFlagDefinition.objects
        .filter(club=club, is_active=True)
        .order_by("display_order", "id")
    )

    event_flags = list(
        EventFlagDefinition.objects
        .filter(event=event, is_active=True)
        .order_by("display_order", "id")
    )

    member_classes = list(
        ClubMemberClass.objects
        .filter(club=club, is_active=True)
        .order_by("display_order", "id")
    )

    # ============================================================
    # 3) イベント表示設定（DB -> default）
    #    ※ JS が page-hooks の data-display-settings を読む
    # ============================================================
    display_settings, display_settings_source = _resolve_event_display_settings(event)
    # テンプレに必ず JSON 文字列として渡す（escapejs 前提）
    display_settings_json = json.dumps(display_settings, ensure_ascii=False)

    # ============================================================
    # 4) 固定メンバー / EP の下準備（※ DB書き込みなし）
    # ============================================================
    members = list(
        Member.objects
        .filter(club=club, is_fixed=True)
        .select_related("member_class")
        .order_by("member_no", "id")
    )
    member_ids = [m.id for m in members]

    eps_by_member = {
        ep.member_id: ep
        for ep in (
            EventParticipant.objects
            .filter(event=event, member_id__in=member_ids)
            .select_related("member", "event_member_class")
        )
    }

    # ============================================================
    # 5) 参加者フラグ状態（クラブ共通 / イベント固有）
    # ============================================================
    (
        flag_states_on,
        flag_states_val,
        event_flag_states_on,
        event_flag_states_val,
    ) = _load_participant_flag_states(event, club, event_flags)

    # ============================================================
    # 6) 対戦表（published）と Draft 破棄（踏襲）
    # ============================================================
    ms = MatchSchedule.objects.filter(event=event, published=True).first()
    MatchScheduleDraft.objects.filter(event=event).delete()

    # ============================================================
    # 7) 固定行 / 8) ゲスト行の組み立て
    # ============================================================
    is_past_event = bool(event.date and event.date < timezone.localdate())
    fixed_rows = _build_fixed_rows(members, eps_by_member)
    guest_rows = _build_guest_rows(event, member_ids, is_past_event=is_past_event)

    # ============================================================
    # 9) 代打候補（公開済み対戦表がある時だけ）
    # ============================================================
    sub_candidates = []
    if ms:
        sub_candidates_qs = (
            EventParticipant.objects
            .filter(event=event, attendance="yes")
            .select_related("member")
            .order_by("id")
        )
        sub_candidates = [
            {
                "ep_id": ep.id,
                "name": (
                    ep.member.display_name
                    if (ep.member_id and ep.member)
                    else (ep.display_name or str(ep.id))
                ),
            }
            for ep in sub_candidates_qs
        ]

    # ============================================================
    # 10) 対戦表の表示用整形
    # ============================================================
    if ms:
        game_type = ms.game_type or GameType.DOUBLES
        num_rounds = int(ms.round_count or 8)
        num_courts = int(ms.court_count or 1)

        match_count = EventParticipant.objects.filter(event=event, participates_match=True).count()
        publish_state = "published"

        score_map = _build_score_map(ms)
        schedule_for_view = _merge_scores_into_schedule(ms.schedule_json, score_map)
        schedule_json_for_publish = None
    else:
        game_type = GameType.DOUBLES
        num_rounds = 8

        match_count = (
            EventParticipant.objects.filter(event=event, participates_match=True).count()
            if is_admin else 0
        )
        num_courts = 0 if match_count < 4 else 2
        publish_state = "no_schedule"
        schedule_for_view = []
        schedule_json_for_publish = None

    # ============================================================
    # 11) context（JSが読む値は必ず入れる）
    # ============================================================
    ctx = {
        "club": club,
        "event": event,
        "is_admin": is_admin,

        # --- JS(Display Settings) のために必須 ---
        "display_settings_json": display_settings_json,
        "display_settings_source": display_settings_source,
        "save_display_settings_url": reverse("tennis:save_event_display_setting"),

        "member_classes": member_classes,

        # --- Flags ---
        "flags": flags,
        "flag_input_mode": getattr(club, "flag_input_mode", "check"),
        "flag_states_on": {k: dict(v) for k, v in flag_states_on.items()},
        "flag_states_val": {k: dict(v) for k, v in flag_states_val.items()},

        "event_flags": event_flags,
        "max_event_flags": 2,
        "event_flag_states_on": {k: dict(v) for k, v in event_flag_states_on.items()},
        "event_flag_states_val": {k: dict(v) for k, v in event_flag_states_val.items()},

        # --- Participants table rows ---
        "fixed_rows": fixed_rows,
        "guest_rows": guest_rows,
        "max_flags": MAX_FLAGS,

        # --- Schedule ---
        "game_type": game_type,
        "num_rounds": num_rounds,
        "num_courts": num_courts,
        "match_count": match_count,
        "publish_state": publish_state,
        "schedule": schedule_for_view,
        "schedule_json": schedule_json_for_publish,

        # --- UI helpers ---
        "show_controls": bool(is_admin),
        "pill_game_type": game_type,
        "pill_num_courts": num_courts,
        "pill_num_rounds": num_rounds,
        "pill_match_count": match_count,

        "ep_name_map": _build_ep_name_map(event),
        "sub_candidates": sub_candidates,
        "show_topbar": True,
        "cleanup_warnings": _run_member_auto_cleanup(club) if is_admin else [],
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

    club = get_object_or_404(Club, id=int(club_id), is_active=True)

    name = (request.POST.get("name") or "").strip()
    if not name or len(name) > 80:
        return JsonResponse({"error": "bad_name"}, status=400)

    # 認可：admin_token チェック（統一ヘルパ）
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    # input_mode（check / digit）
    input_mode = (request.POST.get("input_mode") or "check").strip()
    if input_mode not in ("check", "digit"):
        return JsonResponse({"error": "bad_input_mode"}, status=400)

    # 重複名チェック
    if ClubFlagDefinition.objects.filter(club=club, is_active=True, name=name).exists():
        return JsonResponse({"error": "duplicate_name"}, status=400)

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
        name=name,
        display_order=next_order,
        input_mode=input_mode,
        is_active=True,
    )

    return JsonResponse({
        "ok": True,
        "id": flag.id,
        "name": flag.name,
        "display_order": flag.display_order,
        "input_mode": flag.input_mode,
    })


@require_POST
def club_delete_flag(request):
    club_id = (request.POST.get("club_id") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()
    flag_id = (request.POST.get("flag_id") or "").strip()

    if not club_id:
        return JsonResponse({"error": "club_id required"}, status=400)
    if not admin_token:
        return JsonResponse({"error": "admin_token required"}, status=400)
    if not flag_id:
        return JsonResponse({"error": "flag_id required"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    flag = get_object_or_404(
        ClubFlagDefinition,
        id=int(flag_id),
        club=club,
        is_active=True,
    )
    flag.is_active = False
    flag.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"ok": True})


@require_POST
def club_rename_flag(request):
    flag_id = (request.POST.get("flag_id") or "").strip()
    name = (request.POST.get("name") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()

    if not flag_id:
        return JsonResponse({"error": "flag_id required"}, status=400)
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    if not admin_token:
        return JsonResponse({"error": "admin_token required"}, status=400)

    flag = get_object_or_404(ClubFlagDefinition, id=int(flag_id), is_active=True)
    blocked = _require_club_admin_token(request, flag.club)
    if blocked:
        return blocked

    flag.name = name
    flag.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True, "name": flag.name})


@require_POST
def club_rename_club(request):
    club_id = (request.POST.get("club_id") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()
    name = (request.POST.get("name") or "").strip()

    if not club_id or not admin_token:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)
    if not name:
        return JsonResponse({"ok": False, "error": "name required"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    club.name = name
    club.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True, "name": club.name})


@require_POST
def club_create_event(request):
    club_id = (request.POST.get("club_id") or "").strip()
    date_str = (request.POST.get("date") or request.POST.get("date_str") or "").strip()

    admin_token = (request.POST.get("admin_token") or "").strip()
    title = (request.POST.get("title") or "").strip()
    place = (request.POST.get("place") or "").strip()
    start_str = (request.POST.get("start_time") or "").strip()
    end_str = (request.POST.get("end_time") or "").strip()

    # --- missing を細かく返す（原因特定用） ---
    if not club_id:
        return JsonResponse({"ok": False, "error": "missing_club_id"}, status=400)
    if not date_str:
        return JsonResponse({"ok": False, "error": "missing_date"}, status=400)

    # --- club ---
    try:
        club_id_i = int(club_id)
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_club_id"}, status=400)

    club = get_object_or_404(Club, id=club_id_i, is_active=True)

    # --- ★幹事認可（統一） ---
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    # --- date / time ---
    d = _parse_date_yyyy_mm_dd(date_str)
    if not d:
        return JsonResponse({"ok": False, "error": "bad_date"}, status=400)

    start_t = _parse_hhmm(start_str)
    end_t = _parse_hhmm(end_str)
    if start_t and end_t and end_t < start_t:
        return JsonResponse({"ok": False, "error": "time_order"}, status=400)

    with transaction.atomic():
        ev = Event.objects.create(
            club=club,
            date=d,
            title=title or "練習",
            place=place,
            start_time=start_t,
            end_time=end_t,
            cancelled=False,
        )

        # 固定メンバーのEPを作っておく（新規イベントでデフォルト表示されるための土台）
        fixed_members = list(
            Member.objects
            .filter(club=club, is_fixed=True)
            .select_related("member_class")
            .order_by("member_no", "id")
        )

        eps = []
        for m in fixed_members:
            eps.append(EventParticipant(
                event=ev,
                member=m,
                display_name=m.display_name,
                attendance=None,
                comment="",
                participates_match=False,
                # ここは「互換」枠：event_view は FK を正とするので、空でOK
                class_name="",
                event_member_class=getattr(m, "member_class", None),  # ★デフォルト表示を確実にする本命
            ))

        if eps:
            EventParticipant.objects.bulk_create(eps)

    return JsonResponse({
        "ok": True,
        "event": {
            "id": ev.id,
            "date": ev.date.strftime("%Y-%m-%d"),
            "title": ev.title,
            "public_url": reverse("tennis:event_public", args=[club.public_token, ev.id]),
            "admin_url": reverse("tennis:event_admin", args=[club.public_token, club.admin_token, ev.id]),
        },
    })


@require_POST
def club_cancel_event(request):
    event_id = (request.POST.get("event_id") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()  # ★追加

    if not event_id:
        return JsonResponse({"error": "event_id required"}, status=400)
    if not admin_token:
        return JsonResponse({"error": "admin_token_required"}, status=400)

    # ★イベント→クラブのtokenで認可
    ev = get_object_or_404(Event.objects.select_related("club"), id=int(event_id))
    blocked = _require_club_admin_token(request, ev.club)
    if blocked:
        return blocked

    ev.cancelled = not bool(ev.cancelled)
    ev.save(update_fields=["cancelled", "updated_at"])
    return JsonResponse({"ok": True, "cancelled": ev.cancelled})

@require_POST
def club_delete_event(request):
    event_id = (request.POST.get("event_id") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()  # ★追加

    if not event_id:
        return JsonResponse({"error": "event_id required"}, status=400)
    if not admin_token:
        return JsonResponse({"error": "admin_token_required"}, status=400)

    # ★イベント→クラブのtokenで認可
    ev = get_object_or_404(Event.objects.select_related("club"), id=int(event_id))
    blocked = _require_club_admin_token(request, ev.club)
    if blocked:
        return blocked

    ev.delete()
    return JsonResponse({"ok": True})


# ============================================================
# API Guards (共通の認可・ロック)
# ============================================================

def _json_forbidden(message: str, code: str = "forbidden", status: int = 403):
    return JsonResponse({"ok": False, "error": code, "message": message}, status=status)


def _guard_participant_change(request, event, *, require_admin_when_published: bool = True) -> JsonResponse | None:
    """
    出欠/試合参加/出席者追加 など「参加者変更系」APIの共通ガード
    - 公開済み: 一般は変更不可（幹事のみ）
    - 終了イベント: 一般は変更不可（幹事のみ）
    """
    is_admin = _is_event_admin_session(request, event.id)
    is_published = MatchSchedule.objects.filter(event=event, published=True).exists()

    if require_admin_when_published and is_published and not is_admin:
        return _json_forbidden("対戦表確定後の出欠変更は幹事へ申請してください", code="published_locked")

    if _is_event_ended(event) and not is_admin:
        return _json_forbidden("終了したイベントに対する出席者変更は幹事へ申請してください", code="ended_locked")

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
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"error": "missing_target"}, status=400)

    old = ep.attendance or ""
    new = attendance or ""

    ep.attendance = new or None

    # A案：出欠が上位
    if new != "yes":
        ep.participates_match = False
    else:
        if old != "yes":
            ep.participates_match = True

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
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"error": "missing_target"}, status=400)

    ep.comment = comment
    ep.save(update_fields=["comment", "updated_at"])
    return JsonResponse({"ok": True, "ep_id": ep.id})


@require_POST
def update_participant_display_name(request):
    """
    イベントページからの表示名編集（一般/幹事どちらも可、公開後/終了後も可）。

    - メンバー紐付き（固定メンバー）: Member.display_name を更新し、当該メンバーの
      全 EventParticipant に伝播する（設定ページの club_rename_member と同じ挙動＝クラブ全体反映）。
    - ゲスト（member 無し）: 当該 EventParticipant.display_name のみ更新。
    - EP が無い固定メンバー（未登録行）: member_id 指定で EP を作ってから更新。

    ※ 出欠/コメント編集と異なり、名前の訂正はいつでも可能としたいので
       _guard_participant_change（公開後/終了後の一般ユーザー制限）は適用しない。
    """
    event_id = (request.POST.get("event_id") or "").strip()
    if not event_id:
        return JsonResponse({"ok": False, "error": "missing_event_id"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    new_name = (request.POST.get("display_name") or "").strip()
    if not new_name:
        return JsonResponse({"ok": False, "error": "empty_name"}, status=400)
    if len(new_name) > 100:
        return JsonResponse({"ok": False, "error": "name_too_long"}, status=400)

    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    member = None
    if ep_id:
        ep = get_object_or_404(
            EventParticipant.objects.select_related("member"), id=int(ep_id), event=event
        )
        member = ep.member
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

    if member is not None:
        # クラブ全体に反映（club_rename_member と同じ伝播）
        member.display_name = new_name
        member.save(update_fields=["display_name", "updated_at"])
        EventParticipant.objects.filter(member=member).update(display_name=new_name)
    else:
        # ゲスト：このイベントの表示名のみ
        ep.display_name = new_name
        ep.save(update_fields=["display_name", "updated_at"])

    return JsonResponse({
        "ok": True,
        "ep_id": ep.id,
        "member_id": ep.member_id,
        "display_name": new_name,
    })


@require_POST
def update_member_display_name(request):
    """
    個人ページからのメンバー名編集（一般/幹事どちらも可）。
    - 対象: Member.display_name
    - 副作用: 当該メンバーの全 EventParticipant.display_name にも伝播
      （クラブ全体に反映する点は update_participant_display_name のメンバー紐付き経路と同じ）
    - event_id を要求しない点が update_participant_display_name と異なる
    """
    club_id = (request.POST.get("club_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()
    new_name = (request.POST.get("display_name") or "").strip()

    if not club_id or not member_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)
    if not new_name:
        return JsonResponse({"ok": False, "error": "empty_name"}, status=400)
    if len(new_name) > 100:
        return JsonResponse({"ok": False, "error": "name_too_long"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    member = get_object_or_404(Member, id=int(member_id), club=club)

    member.display_name = new_name
    member.save(update_fields=["display_name", "updated_at"])
    EventParticipant.objects.filter(member=member).update(display_name=new_name)

    return JsonResponse({
        "ok": True,
        "member_id": member.id,
        "display_name": new_name,
    })


@require_POST
def set_participates_match(request):
    event_id = (request.POST.get("event_id") or "").strip()

    checked = request.POST.get("checked")
    if checked is None:
        checked = request.POST.get("value")
    checked = (checked or "").strip().lower()

    if not event_id:
        return JsonResponse({"ok": False, "error": "missing_event_id"}, status=400)
    if checked not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        return JsonResponse({"ok": False, "error": "bad_checked"}, status=400)

    will_on = checked in ("true", "1", "yes", "on")

    event = get_object_or_404(Event, id=int(event_id))

    blocked = _guard_participant_change(request, event, require_admin_when_published=True)
    if blocked:
        return blocked

    ep_id = (request.POST.get("ep_id") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

    # A案：attendance が yes 以外なら試合参加は強制OFF
    if (ep.attendance or "") != "yes":
        will_on = False

    if ep.participates_match != will_on:
        ep.participates_match = will_on
        ep.save(update_fields=["participates_match", "updated_at"])

    return JsonResponse({
        "ok": True,
        "ep_id": ep.id,
        "participates_match": bool(ep.participates_match),
    })


@require_POST
def toggle_participant_flag(request):
    event_id = (request.POST.get("event_id") or "").strip()
    flag_id = (request.POST.get("flag_id") or "").strip()
    checked = (request.POST.get("checked") or "").strip().lower()

    # ★追加：flag_scope（"club" or "event"）
    flag_scope = (request.POST.get("flag_scope") or "club").strip().lower()
    if flag_scope not in ("club", "event"):
        flag_scope = "club"

    if not event_id or not flag_id:
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    if checked not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    is_on = checked in ("true", "1", "yes", "on")

    event = get_object_or_404(Event, id=int(event_id))

    # ============================================================
    # ① フラグ定義を scope で取得（club/event）
    # ============================================================
    if flag_scope == "event":
        flagdef = get_object_or_404(
            EventFlagDefinition,
            id=int(flag_id),
            event=event,
            is_active=True,
        )
    else:
        flagdef = get_object_or_404(
            ClubFlagDefinition,
            id=int(flag_id),
            club=event.club,
            is_active=True,
        )

    # digit 型は別 API（既存仕様維持）
    if flagdef.input_mode == "digit":
        return JsonResponse({"ok": False, "error": "digit_flag_use_value_api"}, status=400)

    # ============================================================
    # ② 対象参加者（ep）を取得/作成（既存仕様維持）
    # ============================================================
    ep_id = ((request.POST.get("ep_id") or "").strip()
             or (request.POST.get("participant_id") or "").strip())
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

    # ============================================================
    # ③ ParticipantFlag を scope で get_or_create
    #    （あなたのモデル設計に完全一致）
    # ============================================================
    if flag_scope == "event":
        obj, _ = ParticipantFlag.objects.get_or_create(
            event_participant=ep,
            event_flag_definition=flagdef,
            defaults={"club_flag_definition": None},
        )
        # 安全策：過去データ等で両方入ってたら矯正
        if obj.club_flag_definition_id is not None:
            obj.club_flag_definition = None
    else:
        obj, _ = ParticipantFlag.objects.get_or_create(
            event_participant=ep,
            club_flag_definition=flagdef,
            defaults={"event_flag_definition": None},
        )
        if obj.event_flag_definition_id is not None:
            obj.event_flag_definition = None

    if obj.is_on != is_on:
        obj.is_on = is_on
        try:
            obj.save(update_fields=["is_on", "club_flag_definition", "event_flag_definition", "updated_at"])
        except Exception:
            obj.save()

    return JsonResponse({
        "ok": True,
        "ep_id": ep.id,
        "flag_id": flagdef.id,
        "flag_scope": flag_scope,
        "checked": bool(obj.is_on),
    })


@require_POST
def club_set_flag_input_mode(request):
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    mode = (request.POST.get("flag_input_mode") or "").strip()

    if not club_id:
        return JsonResponse({"ok": False, "error": "missing_club_id"}, status=400)
    if mode not in ("check", "digit"):
        return JsonResponse({"ok": False, "error": "bad_mode"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    club.flag_input_mode = mode
    club.save(update_fields=["flag_input_mode"])
    return JsonResponse({"ok": True, "mode": club.flag_input_mode})


@require_POST
def set_participant_flag_value(request):
    event_id = (request.POST.get("event_id") or "").strip()
    flag_id = (request.POST.get("flag_id") or "").strip()
    value_raw = (request.POST.get("value") or "").strip()  # "" でクリア

    # ★flag_scope（"club" or "event"）— toggle_participant_flag と同じ扱い。
    #   固有フラグ(event)の digit 入力にも対応する。
    flag_scope = (request.POST.get("flag_scope") or "club").strip().lower()
    if flag_scope not in ("club", "event"):
        flag_scope = "club"

    if not event_id or not flag_id:
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    # フラグ定義を scope で取得（club=ClubFlagDefinition / event=EventFlagDefinition）
    if flag_scope == "event":
        flagdef = get_object_or_404(
            EventFlagDefinition, id=int(flag_id), event=event, is_active=True
        )
    else:
        flagdef = get_object_or_404(
            ClubFlagDefinition, id=int(flag_id), club=event.club, is_active=True
        )

    ep_id = ((request.POST.get("ep_id") or "").strip()
             or (request.POST.get("participant_id") or "").strip())
    member_id = (request.POST.get("member_id") or "").strip()

    if ep_id:
        ep = get_object_or_404(EventParticipant, id=int(ep_id), event=event)
    elif member_id:
        member = get_object_or_404(Member, id=int(member_id), club=event.club)
        ep = _get_or_create_ep(event, member, member.display_name)
    else:
        return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

    # 空欄はクリア、数字1桁のみ許可
    if value_raw == "":
        next_val = None
    else:
        if not value_raw.isdigit() or len(value_raw) != 1:
            return JsonResponse({"ok": False, "error": "bad_value"}, status=400)
        next_val = int(value_raw)
        if next_val < 0 or next_val > 9:
            return JsonResponse({"ok": False, "error": "bad_value"}, status=400)

    # ParticipantFlag を scope で get_or_create（CheckConstraint: 片側のみ非null）
    if flag_scope == "event":
        obj, _created = ParticipantFlag.objects.get_or_create(
            event_participant=ep,
            event_flag_definition=flagdef,
            defaults={"club_flag_definition": None},
        )
        if obj.club_flag_definition_id is not None:
            obj.club_flag_definition = None
    else:
        obj, _created = ParticipantFlag.objects.get_or_create(
            event_participant=ep,
            club_flag_definition=flagdef,
            defaults={"event_flag_definition": None},
        )
        if obj.event_flag_definition_id is not None:
            obj.event_flag_definition = None

    obj.value = next_val
    obj.is_on = (next_val is not None)  # 数字が入っていればON扱い
    try:
        obj.save(update_fields=["value", "is_on", "club_flag_definition", "event_flag_definition", "updated_at"])
    except Exception:
        obj.save()

    return JsonResponse({
        "ok": True,
        "ep_id": ep.id,
        "flag_id": flagdef.id,
        "flag_scope": flag_scope,
        "value": obj.value,                 # None or int
        "checked": bool(obj.is_on),         # 互換用
    })


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
    if not member:
        return JsonResponse({"ok": False, "error": "invalid_name"}, status=400)

    ep = _get_or_create_ep(event, member, name)
    return JsonResponse({"ok": True, "ep_id": ep.id, "display_name": ep.display_name})


@require_POST
def save_event_display_setting(request):
    event_id = (request.POST.get("event_id") or "").strip()
    if not event_id:
        return JsonResponse({"ok": False, "error": "missing_event_id"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    raw = (request.POST.get("settings_json") or "").strip()
    if not raw:
        return JsonResponse({"ok": False, "error": "missing_settings_json"}, status=400)

    try:
        s = json.loads(raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)

    # ✅ 確定仕様：4キーのみ受付（互換・揺れ吸収はしない）
    required_keys = ("common_flags", "event_flags", "class", "schedule")
    if not isinstance(s, dict) or any(k not in s for k in required_keys):
        return JsonResponse({"ok": False, "error": "bad_settings_keys"}, status=400)

    # ✅ bool に正規化（JSが true/false を送る前提）
    common_flags = bool(s.get("common_flags"))
    event_flags  = bool(s.get("event_flags"))
    show_class   = bool(s.get("class"))
    show_schedule= bool(s.get("schedule"))

    obj, _ = EventDisplaySetting.objects.get_or_create(event=event)
    obj.show_flags = common_flags
    obj.show_event_flags = event_flags
    obj.show_class = show_class
    obj.show_schedule = show_schedule
    obj.save(update_fields=["show_flags", "show_event_flags", "show_class", "show_schedule", "updated_at"])

    return JsonResponse({"ok": True, "settings": obj.as_dict()})


# ============================================================
# Schedule
# ============================================================

@require_POST
def ajax_generate_schedule(request, event_id):
    event = get_object_or_404(Event, id=int(event_id))

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
        match_participants = [p for p in participants if p.participates_match]

    ep_ids = [int(p.id) for p in match_participants]
    match_count = len(ep_ids)

    DEFAULT_ROUNDS = 8
    DEFAULT_COURTS = 1

    game_type = request.POST.get("game_type", GameType.DOUBLES)
    if game_type not in (GameType.DOUBLES, GameType.SINGLES):
        game_type = GameType.DOUBLES

    num_rounds = _parse_int(request.POST.get("num_rounds"), default=DEFAULT_ROUNDS, min_v=1, max_v=20) or DEFAULT_ROUNDS
    num_courts = _parse_int(request.POST.get("num_courts"), default=DEFAULT_COURTS, min_v=1, max_v=12) or DEFAULT_COURTS

    per_court = 4 if game_type == GameType.DOUBLES else 2
    max_courts = max(1, (match_count // per_court)) if match_count >= per_court else 1
    num_courts = max(1, min(num_courts, max_courts))

    if match_count == 0:
        schedule = []
    else:
        schedule = (
            generate_singles_schedule(ep_ids, num_rounds, num_courts)
            if game_type == GameType.SINGLES
            else generate_doubles_schedule(ep_ids, num_rounds, num_courts)
        )

    participant_ids = [int(x) for x in ep_ids]
    params_json = {
        "game_type": game_type,
        "num_courts": int(num_courts),
        "num_rounds": int(num_rounds),
        "participant_ids": participant_ids,
    }

    MatchScheduleDraft.objects.update_or_create(
        event=event,
        defaults={"draft_json": schedule, "params_json": params_json},
    )

    ctx = {
        "event": event,
        "schedule": schedule,
        "schedule_json": schedule,  # publish用（json_script化）
        "stats": None,
        "ep_name_map": _build_ep_name_map(event),

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
            "schedule_json": json.dumps(schedule, ensure_ascii=False),
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

    if (event.club.admin_token or "").strip() != admin_token:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    changed_fields = []

    # cancelled toggle
    if "cancelled" in request.POST:
        v = (request.POST.get("cancelled") or "").strip()
        next_cancelled = v in ("1", "true", "True", "yes", "on")
        if event.cancelled != next_cancelled:
            event.cancelled = next_cancelled
            changed_fields.append("cancelled")

    # normal edit（送られてきたキーだけ更新）
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
        event.save(update_fields=changed_fields + ["updated_at"])

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
                "schedule_json", "game_type", "court_count", "round_count",
                "published", "locked", "updated_at"
            ])

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

    value_raw = request.POST.get("value")
    if value_raw is None:
        value_raw = request.POST.get("score")
    if value_raw is None:
        value_raw = request.POST.get("score_value")

    if not (event_id and round_no and court_no and side in ("a", "b")):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    try:
        round_no_i = int(round_no)
        court_no_i = int(court_no)
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_number"}, status=400)

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

    match_schedule = MatchSchedule.objects.filter(event=event, published=True).first()
    if not match_schedule:
        return JsonResponse({"ok": False, "error": "no_published_schedule"}, status=409)

    with transaction.atomic():
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

        score_obj.save()

        if (not match_schedule.locked) and (v is not None):
            match_schedule.locked = True
            match_schedule.save(update_fields=["locked", "updated_at"])

    return JsonResponse({"ok": True, "side": side, "value": v})


# ============================================================
# Member APIs
# ============================================================

@require_POST
@transaction.atomic
def club_add_member(request):
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    name = (request.POST.get("display_name") or "").strip()

    if not club_id or not admin_token:
        return JsonResponse({"error": "missing"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    if not name:
        return JsonResponse({"error": "empty_name"}, status=400)

    m = Member.objects.create(
        club=club,
        member_no=_next_member_no(club),
        display_name=name,
        is_fixed=False,
    )

    return JsonResponse({"ok": True, "member": {
        "id": m.id,
        "member_no": m.member_no,
        "display_name": m.display_name,
        "is_fixed": m.is_fixed,
    }})


@require_POST
def club_rename_member(request):
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    member_id = request.POST.get("member_id")
    name = (request.POST.get("display_name") or "").strip()

    if not club_id or not admin_token or not member_id:
        return JsonResponse({"error": "missing"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    if not name:
        return JsonResponse({"error": "empty_name"}, status=400)

    m = get_object_or_404(Member, id=int(member_id), club=club)
    m.display_name = name
    m.save(update_fields=["display_name", "updated_at"])
    EventParticipant.objects.filter(member=m).update(display_name=m.display_name)
    return JsonResponse({"ok": True, "member_id": m.id, "display_name": m.display_name})


@require_POST
def club_toggle_member_fixed(request):
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    member_id = request.POST.get("member_id")
    checked = (request.POST.get("checked") or "").lower() in ("1", "true", "yes", "on")

    if not club_id or not admin_token or not member_id:
        return JsonResponse({"error": "missing"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    m = get_object_or_404(Member, id=int(member_id), club=club)
    m.is_fixed = checked
    m.save(update_fields=["is_fixed", "updated_at"])
    return JsonResponse({"ok": True, "member_id": m.id, "is_fixed": m.is_fixed})


@require_POST
def club_delete_member(request):
    """
    メンバー削除（設定ページ・幹事のみ）。
    - 非固定メンバー(is_fixed=False)のみ削除可。固定メンバーは拒否。
    - EventParticipant.member は SET_NULL のため、当該メンバーの出欠/戦績
      （EventParticipant 行・schedule_json 内の ep_id 参照・スコア）はそのまま残る。
      削除されるのは Member 行のみ。
    """
    club_id = request.POST.get("club_id")
    member_id = request.POST.get("member_id")

    if not club_id or not member_id:
        return JsonResponse({"ok": False, "error": "missing"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    m = get_object_or_404(Member, id=int(member_id), club=club)

    # 固定メンバーは削除不可（非固定のみ対象）
    if m.is_fixed:
        return JsonResponse({"ok": False, "error": "fixed_member"}, status=400)

    deleted_id = m.id
    m.delete()  # EP は SET_NULL で残る（履歴・戦績を保持）
    return JsonResponse({"ok": True, "member_id": deleted_id})


# ============================================================
# Substitute (代打) : substitute_slot（仕様コメントは元のまま）
# ============================================================


def _find_target_round(sched, round_no):
    """schedule_json(list) から round 番号一致の round dict を返す。無ければ None。"""
    for r in sched:
        if not isinstance(r, dict):
            continue
        try:
            rr = int(r.get("round", -1))
        except Exception:
            continue
        if rr == round_no:
            return r
    return None


def _find_ep_in_matches(matches, ep_id):
    """matches 内に ep_id が居れば ("match", match_idx, team_key, slot_idx) を返す。無ければ None。"""
    for mi, mm in enumerate(matches):
        if not isinstance(mm, dict):
            continue
        for tk in ("team1", "team2"):
            lst = mm.get(tk) or []
            if not isinstance(lst, list):
                continue
            for si, pid in enumerate(lst):
                try:
                    if int(pid) == ep_id:
                        return ("match", mi, tk, si)
                except Exception:
                    continue
    return None


def _find_ep_in_rests(rests, ep_id):
    """rests 内に ep_id が居れば ("rest", rest_idx) を返す。無ければ None。"""
    for ri, pid in enumerate(rests):
        try:
            if int(pid) == ep_id:
                return ("rest", ri)
        except Exception:
            continue
    return None


def _render_published_schedule_response(event, ms, request):
    """公開済み対戦表のHTMLを描画し、ok レスポンスを返す（substitute_slot 共通の返却処理）。"""
    score_map = _build_score_map(ms)
    schedule_for_view = _merge_scores_into_schedule(ms.schedule_json, score_map)
    ctx = {
        "event": event,
        "schedule": schedule_for_view,
        "schedule_json": None,
        "ep_name_map": _build_ep_name_map(event),
        "show_controls": True,
        "pill_game_type": ms.game_type or GameType.DOUBLES,
        "pill_num_courts": int(ms.court_count or 1),
        "pill_num_rounds": int(ms.round_count or 8),
        "pill_match_count": int(EventParticipant.objects.filter(event=event, participates_match=True).count()),
        "publish_state": "published",
    }
    schedule_html = render_to_string("tennis/_schedule_block.html", ctx, request=request)
    return JsonResponse({"ok": True, "schedule_html": schedule_html, "publish_state": "published"})


@require_POST
def substitute_slot(request):
    event_id = request.POST.get("event_id")
    round_no = request.POST.get("round_no")
    court_no = request.POST.get("court_no")
    team = request.POST.get("team")         # "1" or "2"
    slot_index = request.POST.get("slot_index")
    new_ep_id = request.POST.get("new_ep_id")

    if not (event_id and round_no and court_no and team and slot_index and new_ep_id):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    try:
        event_id_i = int(event_id)
        round_no_i = int(round_no)
        court_no_i = int(court_no)
        team_i = int(team)
        slot_index_i = int(slot_index)
        new_ep_id_i = int(new_ep_id)
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_number"}, status=400)

    if team_i not in (1, 2):
        return JsonResponse({"ok": False, "error": "bad_team"}, status=400)

    event = get_object_or_404(Event, id=event_id_i)

    # ✅ 重要：draft が存在するなら代打は禁止（事故防止）
    if MatchSchedule.objects.filter(event=event, published=False).exists():
        return JsonResponse({"ok": False, "error": "draft_exists"}, status=409)

    new_ep = (
        EventParticipant.objects
        .filter(id=new_ep_id_i, event=event)
        .select_related("member")
        .first()
    )
    if not new_ep:
        return JsonResponse({"ok": False, "error": "no_participant"}, status=404)
    if (new_ep.attendance or "") != "yes":
        return JsonResponse({"ok": False, "error": "not_attendance_yes"}, status=409)

    with transaction.atomic():
        ms = (
            MatchSchedule.objects
            .select_for_update()
            .filter(event=event, published=True)
            .first()
        )
        if not ms:
            return JsonResponse({"ok": False, "error": "no_published_schedule"}, status=409)

        sched = ms.schedule_json or []
        if not isinstance(sched, list):
            return JsonResponse({"ok": False, "error": "bad_schedule"}, status=500)

        # --- 対象 round 取得 ---
        target_round = _find_target_round(sched, round_no_i)
        if not target_round:
            return JsonResponse({"ok": False, "error": "no_round"}, status=404)

        matches = target_round.get("matches") or []
        if not isinstance(matches, list):
            return JsonResponse({"ok": False, "error": "bad_matches"}, status=500)
        if not (1 <= court_no_i <= len(matches)):
            return JsonResponse({"ok": False, "error": "no_court"}, status=404)

        m = matches[court_no_i - 1]
        if not isinstance(m, dict):
            return JsonResponse({"ok": False, "error": "bad_match"}, status=500)

        team_key = "team1" if team_i == 1 else "team2"
        if team_key not in m or not isinstance(m.get(team_key), list):
            return JsonResponse({"ok": False, "error": "bad_team"}, status=500)
        if not (0 <= slot_index_i < len(m[team_key])):
            return JsonResponse({"ok": False, "error": "bad_slot"}, status=400)

        try:
            old_ep_id = int(m[team_key][slot_index_i])
        except Exception:
            return JsonResponse({"ok": False, "error": "bad_old_ep_id"}, status=500)

        # 同じなら何もしない（公開状態維持）
        if old_ep_id == new_ep_id_i:
            return _render_published_schedule_response(event, ms, request)

        # --- new_ep が他に居たら入替（matches を先に、無ければ rests を探す） ---
        found_pos = _find_ep_in_matches(matches, new_ep_id_i)

        rests = target_round.get("rests") or []
        if not isinstance(rests, list):
            rests = []

        if not found_pos:
            found_pos = _find_ep_in_rests(rests, new_ep_id_i)

        if found_pos:
            if found_pos[0] == "match":
                _t, mi, tk, si = found_pos
                matches[mi][tk][si] = old_ep_id
            else:
                _t, ri = found_pos
                rests[ri] = old_ep_id

            m[team_key][slot_index_i] = new_ep_id_i
            rests = [x for x in rests if str(x) != str(new_ep_id_i)]
        else:
            m[team_key][slot_index_i] = new_ep_id_i

            existing_rest_ints = []
            for x in rests:
                try:
                    existing_rest_ints.append(int(x))
                except Exception:
                    continue
            if old_ep_id not in existing_rest_ints:
                rests.append(old_ep_id)
            rests = [x for x in rests if str(x) != str(new_ep_id_i)]

        target_round["matches"] = matches
        target_round["rests"] = rests

        # ✅ 仕様：代打は published を維持（モデル側で落ちる可能性も潰す）
        ms.schedule_json = sched
        ms.published = True
        ms.save(update_fields=["schedule_json", "published", "updated_at"])

        # スコアはその試合だけクリア
        MatchScore.objects.filter(
            match_schedule=ms,
            round_no=round_no_i,
            court_no=court_no_i,
        ).delete()

    # 返却HTML作成（公開状態は published 固定）
    ms2 = MatchSchedule.objects.filter(event=event, published=True).first()
    if not ms2:
        return JsonResponse({"ok": False, "error": "no_published_schedule"}, status=409)

    return _render_published_schedule_response(event, ms2, request)


# ============================================================
# Class APIs
# ============================================================

@require_POST
def club_add_class(request):
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    name = (request.POST.get("name") or "").strip()

    if not club_id or not admin_token:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)
    if not name:
        return JsonResponse({"ok": False, "error": "missing_name"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    last = ClubMemberClass.objects.filter(club=club, is_active=True).order_by("-display_order", "-id").first()
    next_order = (last.display_order + 1) if last else 1

    c = ClubMemberClass.objects.create(club=club, name=name, display_order=next_order, is_active=True)
    return JsonResponse({"ok": True, "class": {"id": c.id, "name": c.name}})


@require_POST
def club_rename_class(request):
    class_id = request.POST.get("class_id")
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()
    name = (request.POST.get("name") or "").strip()

    if not club_id or not class_id or not admin_token:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)
    if not name:
        return JsonResponse({"ok": False, "error": "missing_name"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    c = get_object_or_404(ClubMemberClass, id=int(class_id), club=club)
    c.name = name
    c.save(update_fields=["name", "updated_at"])
    return JsonResponse({"ok": True})


@require_POST
def club_delete_class(request):
    class_id = request.POST.get("class_id")
    club_id = request.POST.get("club_id")
    admin_token = (request.POST.get("admin_token") or "").strip()

    if not club_id or not class_id or not admin_token:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    club = get_object_or_404(Club, id=int(club_id), is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    c = get_object_or_404(ClubMemberClass, id=int(class_id), club=club)
    c.is_active = False
    c.save(update_fields=["is_active", "updated_at"])

    Member.objects.filter(club=club, member_class=c).update(member_class=None)
    return JsonResponse({"ok": True})


@require_POST
def club_set_member_class(request):
    """
    クラブ設定（settings）専用：
    - Member.member_class を更新（クラブデフォルト）
    - 既存イベントのEPには一切触らない
    """
    club_id = (request.POST.get("club_id") or "").strip()
    admin_token = (request.POST.get("admin_token") or "").strip()
    member_id = (request.POST.get("member_id") or "").strip()
    class_id = (request.POST.get("class_id") or "").strip()  # "" なら解除(None)

    if not club_id or not admin_token or not member_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    try:
        club_id_i = int(club_id)
        member_id_i = int(member_id)
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_params"}, status=400)

    club = get_object_or_404(Club, id=club_id_i, is_active=True)
    blocked = _require_club_admin_token(request, club)
    if blocked:
        return blocked

    m = get_object_or_404(Member, id=member_id_i, club=club)

    # class 解決（空欄OK＝None）
    if class_id == "":
        c = None
    else:
        try:
            class_id_i = int(class_id)
        except ValueError:
            return JsonResponse({"ok": False, "error": "bad_params"}, status=400)
        c = get_object_or_404(ClubMemberClass, id=class_id_i, club=club, is_active=True)

    m.member_class = c
    m.save(update_fields=["member_class", "updated_at"])

    return JsonResponse({
        "ok": True,
        "context": "settings",
        "member_id": m.id,
        "class_id": c.id if c else None,
    })


@require_POST
def set_participant_class(request):
    """
    イベントページ専用（FK保存仕様）：
    - EventParticipant.event_member_class を更新（イベント固有：FK）
    - Member.member_class は更新しない（設定ページのデフォルト用は別）
    - EP が無い固定メンバー行は、このイベントに限り EP を作って保存先を確保
    """
    event_id = (request.POST.get("event_id") or "").strip()
    club_id = (request.POST.get("club_id") or "").strip()      # 互換/安全確認用
    member_id = (request.POST.get("member_id") or "").strip()
    ep_id = (request.POST.get("ep_id") or "").strip()          # あれば優先
    class_id = (request.POST.get("class_id") or "").strip()    # "" なら解除（None）

    if not event_id:
        return JsonResponse({"ok": False, "error": "missing_event_id"}, status=400)

    try:
        event_id_i = int(event_id)
        club_id_i = int(club_id) if club_id else None
        member_id_i = int(member_id) if member_id else None
        ep_id_i = int(ep_id) if ep_id else None
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_params"}, status=400)

    event = get_object_or_404(Event.objects.select_related("club"), id=event_id_i)

    # 追加ガード：club_id が送られてきたなら一致確認（壊れたJS対策）
    if club_id_i is not None and int(event.club_id) != int(club_id_i):
        return JsonResponse({"ok": False, "error": "club_mismatch"}, status=400)

    # 認可：イベント幹事セッション必須
    blocked = _guard_admin_only(request, event)
    if blocked:
        return blocked

    # class_id -> FK 解決
    resolved_class = None
    resolved_class_id = None
    resolved_class_name = ""

    if class_id == "":
        resolved_class = None
        resolved_class_id = None
        resolved_class_name = ""
    else:
        try:
            class_id_i = int(class_id)
        except ValueError:
            return JsonResponse({"ok": False, "error": "bad_params"}, status=400)

        resolved_class = get_object_or_404(
            ClubMemberClass,
            id=class_id_i,
            club=event.club,
            is_active=True,
        )
        resolved_class_id = resolved_class.id
        resolved_class_name = (resolved_class.name or "").strip()

    with transaction.atomic():
        # EP を特定
        if ep_id_i is not None:
            ep = get_object_or_404(EventParticipant, id=ep_id_i, event=event)

            # member_id が送られてきた場合だけ整合性チェック
            if member_id_i is not None and ep.member_id != member_id_i:
                return JsonResponse({"ok": False, "error": "member_mismatch"}, status=400)
        else:
            # ep_id が無い場合：member_id 必須（固定行の保存先確保）
            if member_id_i is None:
                return JsonResponse({"ok": False, "error": "missing_target"}, status=400)

            member = get_object_or_404(Member, id=member_id_i, club=event.club)

            # このイベントに限り EP を作る（イベント固有データの保存先）
            ep, _ = EventParticipant.objects.get_or_create(
                event=event,
                member=member,
                defaults={
                    "display_name": member.display_name,
                    "class_name": "",  # 互換
                },
            )

        # ★FK更新（これがステップ3-2の本体）
        ep.event_member_class = resolved_class

        # ★互換・デバッグ用：文字列も追随（残すなら）
        ep.class_name = resolved_class_name

        ep.save(update_fields=["event_member_class", "class_name", "updated_at"])

    return JsonResponse({
        "ok": True,
        "context": "event",
        "event_id": event.id,
        "ep_id": ep.id,
        "member_id": ep.member_id,

        # JS互換のため返す
        "class_id": resolved_class_id,
        "class_name": resolved_class_name,
    })


@require_POST
def add_event_flag(request):
    """
    イベント固有フラグを「1回の呼び出しで1個だけ」追加するAPI
    - 最大2つまで（サーバ側で強制）
    - 名称変更/削除は後回し
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    event_id = str(payload.get("event_id") or "").strip()
    name = str(payload.get("name") or "").strip()

    if not event_id or not name:
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    # 長さ制限（テンプレ側 maxlength=20 と合わせる）
    if len(name) > 20:
        return JsonResponse({"ok": False, "error": "name_too_long"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))

    # ✅ admin ガード（あなたの方式に合わせる）
    # event_view で _mark_event_admin_session(request, event.id) しているので、
    # ここは「そのセッションがあるか」をチェックする想定。
    # ※関数名は既存コードに合わせてください（無ければ下のコメント参照）
    if not _is_event_admin_session(request, event.id):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    # 最大2つ（is_active=True のみカウント）
    existing_qs = (
        EventFlagDefinition.objects
        .filter(event=event, is_active=True)
        .order_by("display_order", "id")
    )

    existing_count = existing_qs.count()

    if existing_count >= MAX_EVENT_FLAGS:
        return JsonResponse({"ok": False, "error": "limit_reached", "count": existing_count}, status=400)

    # 同名は弾く（簡易）
    if existing_qs.filter(name=name).exists():
        return JsonResponse({"ok": False, "error": "duplicate_name"}, status=400)

    # display_order は末尾に追加
    last_order = existing_qs.aggregate(m=Max("display_order")).get("m") or 0
    next_order = int(last_order) + 1

    # input_mode は当面 "check" 固定（要件：名前入力だけ）
    obj = EventFlagDefinition.objects.create(
        event=event,
        name=name,
        display_order=next_order,
        is_active=True,
        input_mode="check",
    )

    return JsonResponse({
        "ok": True,
        "event_id": event.id,
        "flag": {
            "id": obj.id,
            "name": obj.name,
            "input_mode": obj.input_mode,
            "display_order": obj.display_order,
        },
        "count": existing_count + 1,
        "max": MAX_EVENT_FLAGS,
    })


@require_POST
def delete_event_flag(request):
    """
    body: { "event_id": <int>, "event_flag_id": <int> }
    - イベント固有フラグを削除
    - 紐づく参加者フラグ値も一緒に消す（CASCADE でもOK）
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    event_id = str(payload.get("event_id") or "").strip()
    event_flag_id = str(payload.get("event_flag_id") or "").strip()

    if not event_id or not event_flag_id:
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)

    event = get_object_or_404(Event, id=int(event_id))
    event_flag = get_object_or_404(EventFlagDefinition, id=int(event_flag_id), event=event)

    # admin ガード（add と同じ思想で揃えるならここも）
    if not _is_event_admin_session(request, event.id):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    with transaction.atomic():
        # ★正：参加者側の値（ParticipantFlag）を削除
        ParticipantFlag.objects.filter(
            event_participant__event=event,
            event_flag_definition=event_flag,
        ).delete()

        # 定義を削除（CASCADEでも上が消えるが、明示で安全）
        event_flag.delete()

    return JsonResponse({"ok": True})
