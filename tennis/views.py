# tennis/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import HttpResponseBadRequest, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
import json
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt



from .models import Event, Participant
from .utils import generate_doubles_schedule, generate_singles_schedule




def index(request):
    """
    とりあえず最近のイベント一覧と「新規作成」リンクだけ出す簡易トップ
    """
    events = Event.objects.order_by("-date")[:10]
    return render(request, "tennis/index.html", {"events": events})

@login_required
def club_settings(request):
    """
    クラブ設定ページ：
      - ① 練習日の設定（カレンダー）
      - ② 出席表フォーマット（フラグなど）の設定
    新規クラブ登録後、まずここに来て設定してもらう想定。
    """
    today = timezone.localdate()

    # ?year= / ?month= 指定があればその月、なければ今月
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year = today.year
        month = today.month

    # 当月の範囲
    first_day = date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day = date(year, month, last_day_num)

    # この月のイベント（練習日）を取得
    events_qs = (
        Event.objects
        .filter(date__gte=first_day, date__lte=last_day)
        .order_by("date", "title")
    )

    # 日付文字列 "YYYY-MM-DD" → [Event,...]
    events_by_day = {}
    for ev in events_qs:
        key = ev.date.strftime("%Y-%m-%d")
        events_by_day.setdefault(key, []).append(ev)

    # イベントごとのフラグ
    flags_qs = Flag.objects.filter(event__in=events_qs).order_by("id")
    flags_by_event = {}
    for f in flags_qs:
        flags_by_event.setdefault(f.event_id, []).append(f)

    # カレンダー用 2次元配列
    cal = calendar.Calendar(firstweekday=0)  # 月曜始まりなら 0
    month_weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            key = d.strftime("%Y-%m-%d")
            week_data.append({
                "date": d,
                "key": key,
                "is_current_month": (d.month == month),
                "events": events_by_day.get(key, []),
            })
        month_weeks.append(week_data)

    context = {
        "year": year,
        "month": month,
        "month_weeks": month_weeks,
        "flags_by_event": flags_by_event,
        "today": today,
        "prev_year": (month == 1 and year - 1) or year,
        "prev_month": (month == 1 and 12) or (month - 1),
        "next_year": (month == 12 and year + 1) or year,
        "next_month": (month == 12 and 1) or (month + 1),
    }
    return render(request, "tennis/settings.html", context)

def create_event(request):
    """
    幹事用：1回分のテニス会を作成
    """
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        date = request.POST.get("date", "")
        start_time = request.POST.get("start_time", "")
        place = request.POST.get("place", "").strip()
        note = request.POST.get("note", "").strip()

        if not title or not date:
            return HttpResponseBadRequest("タイトルと日付は必須です。")

        event = Event(
            title=title,
            date=date,
            start_time=start_time or None,
            place=place,
            note=note,
        )
        event.save()

        public_url = request.build_absolute_uri(
            reverse("tennis:event_public", args=[event.public_token])
        )
        admin_url = request.build_absolute_uri(
            reverse("tennis:event_admin", args=[event.public_token, event.admin_token])
        )

        return render(
            request,
            "tennis/create_done.html",
            {
                "event": event,
                "public_url": public_url,
                "admin_url": admin_url,
            },
        )

    return render(request, "tennis/create_event.html")


def update_participation_flag(request):
    """
    AJAX 用：試合参加フラグを即時更新する
    POST: participant_id, value(true/false)

    ★ ここでは DB を書き換えず、イベントごとの「作業用フラグ」を
       セッションにだけ保存する。
       → リロードすれば破棄される。
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=400)

    try:
        pid = int(request.POST.get("participant_id"))
        val = request.POST.get("value") == "true"
    except Exception:
        return JsonResponse({"error": "bad request"}, status=400)

    p = Participant.objects.select_related("event").filter(id=pid).first()
    if not p:
        return JsonResponse({"error": "participant not found"}, status=404)

    event_id = p.event_id
    session_key = f"event_{event_id}_working_participates"

    # 作業用フラグをセッションに保持
    flags = request.session.get(session_key, {})
    flags[str(pid)] = val
    request.session[session_key] = flags
    request.session.modified = True

    return JsonResponse({"status": "ok", "participant": p.id, "value": val})


def event_public(request, public_token):
    """
    参加者用ページ
    - 出欠フォーム
    - 出欠一覧
    """
    event = get_object_or_404(Event, public_token=public_token)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        attendance = request.POST.get("attendance", "yes")
        level = request.POST.get("level", "").strip()
        comment = request.POST.get("comment", "").strip()

        if name:
            participant, created = Participant.objects.get_or_create(
                event=event,
                name=name,
                defaults={
                    "attendance": attendance,
                    "level": level,
                    "comment": comment,
                },
            )
            if not created:
                participant.attendance = attendance
                participant.level = level
                participant.comment = comment
                participant.save()

        return redirect("tennis:event_public", public_token=event.public_token)

    participants = event.participants.order_by("created_at")
    return render(
        request,
        "tennis/event_public.html",
        {
            "event": event,
            "participants": participants,
        },
    )


def event_admin(request, public_token, admin_token):
    """
    幹事用ページ：
      - POST(generate_schedule) のときだけ乱数表を生成して draft 保存 → PRG
      - 直後の GET 1回だけ draft を表示
      - それ以外の GET では「最後に公開された対戦表」を表示
      - 試合参加フラグの変更はセッションにだけ保持し、リロードしたら破棄
    """
    event = get_object_or_404(Event, public_token=public_token, admin_token=admin_token)

    # 出席者（attendance="yes" のみ）
    participants = event.participants.filter(attendance="yes").order_by("created_at")

    DEFAULT_ROUNDS = 10
    DEFAULT_COURTS = 1

    # 作業用フラグのセッションキー
    session_flags_key = f"event_{event.id}_working_participates"

    # ============ 共通：stats 作成関数 ============（ここはそのまま）
    def build_stats_from_schedule(names_list, schedule_list):
        if not schedule_list:
            return None, None

        all_names = names_list[:]
        round_seq = {n: [] for n in all_names}

        for round_info in schedule_list:
            playing = set()
            for m in round_info.get("matches", []):
                playing.update(m.get("team1", []))
                playing.update(m.get("team2", []))

            rests = [n for n in all_names if n not in playing]
            round_info["rests"] = rests

            for n in all_names:
                round_seq[n].append("P" if n in playing else "R")

        def max_streak(seq, target):
            cur = max_s = 0
            for x in seq:
                if x == target:
                    cur += 1
                    max_s = max(max_s, cur)
                else:
                    cur = 0
            return max_s

        # ★ サマリーは match_participants のみを対象にする
        stats_list = []
        for p in match_participants:
            seq = round_seq.get(p.name, [])
            stats_list.append({
                "name": p.name,
                "matches": seq.count("P"),
                "rests": seq.count("R"),
                "max_play_streak": max_streak(seq, "P"),
                "max_rest_streak": max_streak(seq, "R"),
            })

        return schedule_list, stats_list


    # ★ schedule からゲーム種別・ラウンド数・面数を推論するヘルパー
    def infer_meta_from_schedule(schedule_list):
        """
        schedule_list: [{"round": n, "matches": [...]}] のリスト から
        - game_type: "singles" or "doubles"
        - num_rounds: ラウンド数
        - num_courts: 最大コート番号（≒ 面数）
        を推論して返す。
        """
        if not schedule_list:
            return None, None, None

        num_rounds = len(schedule_list)
        game_type = "doubles"  # デフォルト
        num_courts = 1

        # 最初に「試合があるラウンド」を1つ見て、その中の最初の試合から判定
        for round_info in schedule_list:
            matches = round_info.get("matches") or []
            if not matches:
                continue

            first_match = matches[0]
            team1 = first_match.get("team1") or []

            # チーム人数でシングルス/ダブルスを判定
            if len(team1) == 1:
                game_type = "singles"
            else:
                game_type = "doubles"

            # 面数は「court の最大値」か、なければ試合数
            courts = [
                m.get("court")
                for m in matches
                if isinstance(m.get("court"), int)
            ]
            if courts:
                num_courts = max(courts)
            else:
                num_courts = len(matches)

            break  # 1ラウンド分見られれば十分

        return game_type, num_rounds, num_courts


    # ★ 有効な「試合参加メンバー」を求めるヘルパー
    def get_match_participants(use_working_flags: bool):
        """
        use_working_flags=True のとき：
            セッション上の作業用フラグを優先（なければ DB の participates_match）
        use_working_flags=False のとき：
            DB の participates_match のみを信じる（公式状態）
        """
        if use_working_flags:
            flags = request.session.get(session_flags_key, {})
        else:
            flags = {}

        result = []
        for p in participants:
            if use_working_flags:
                f = flags.get(str(p.id))
                if f is None:
                    f = p.participates_match
            else:
                f = p.participates_match

            if f:
                result.append(p)
        return result

    # ============================================================
    # ① POST: 乱数表生成 → draft に保存して PRG（このリクエストでは render しない）
    # ============================================================
    if request.method == "POST" and "generate_schedule" in request.POST:
        # 今の「試合参加チェック状態」（作業用＋DB）を反映したメンバー
        match_participants = get_match_participants(use_working_flags=True)
        match_count = len(match_participants)
        names = [p.name for p in match_participants]

        # ゲーム種別
        game_type = request.POST.get("game_type", "doubles")
        per_court = 4 if game_type == "doubles" else 2
        max_courts = max(1, match_count // per_court) if match_count >= per_court else 1

        # ラウンド数
        try:
            num_rounds = int(request.POST.get("num_rounds", DEFAULT_ROUNDS))
        except (TypeError, ValueError):
            num_rounds = DEFAULT_ROUNDS
        num_rounds = max(1, min(num_rounds, 20))

        # 面数
        try:
            num_courts = int(request.POST.get("num_courts", DEFAULT_COURTS))
        except (TypeError, ValueError):
            num_courts = DEFAULT_COURTS
        num_courts = max(1, min(num_courts, max_courts))

        # 乱数表生成
        if match_count == 0:
            schedule = []
        else:
            if game_type == "singles":
                schedule = generate_singles_schedule(names, num_rounds, num_courts)
            else:
                schedule = generate_doubles_schedule(names, num_rounds, num_courts)

        # draft に保存（未公開の案）
        event.draft_schedule = schedule
        event.save()

        # pill 表示用の条件をセッションに保存
        request.session[f"event_{event.id}_game_type"] = game_type
        request.session[f"event_{event.id}_num_rounds"] = num_rounds
        request.session[f"event_{event.id}_num_courts"] = num_courts

        # ★ 直後の GET 1 回だけ draft を表示するためのフラグ
        request.session[f"event_{event.id}_show_draft_once"] = True

        # PRG
        return redirect("tennis:event_admin", public_token=public_token, admin_token=admin_token)

    # ============================================================
    # ② GET: 表示用ロジック
    #     - show_draft_once が True なら draft を 1 回だけ表示
    #     - それ以外は「公開版」を最優先（ドラフトは無視 / 作業フラグも破棄）
    # ============================================================
    draft = event.draft_schedule
    published = event.published_schedule

    show_draft_once_key = f"event_{event.id}_show_draft_once"
    show_draft_once = request.session.pop(show_draft_once_key, False)

    if show_draft_once and draft:
        # 乱数生成直後の 1 回だけは draft を表示
        schedule_source = "draft_once"
        schedule_raw = draft

        # この 1 回だけは作業用フラグを生かして人数を数える
        match_participants = get_match_participants(use_working_flags=True)
        # テンプレート用に表示だけ上書き（DB は書き換えない）
        working_flags = request.session.get(session_flags_key, {})
        for p in participants:
            f = working_flags.get(str(p.id))
            if f is None:
                f = p.participates_match
            p.participates_match = f

    else:
        # ★ リロード or 通常アクセス：
        #    公開済みの対戦表だけを表示し、ドラフト＆作業フラグは破棄
        if published:
            schedule_source = "published"
            schedule_raw = published
        else:
            schedule_source = None
            schedule_raw = None

        # 未公開ドラフト＆作業フラグは破棄
        request.session.pop(session_flags_key, None)
        # 必要なら DB 上の draft も物理的に消してしまうことも可能
        # event.draft_schedule = None
        # event.save(update_fields=["draft_schedule"])

        # 人数は「公式状態」（DB）の participates_match から
        match_participants = get_match_participants(use_working_flags=False)

    match_count = len(match_participants)
    names = [p.name for p in match_participants]

    # 対戦表 & サマリー
    if schedule_raw:
        schedule, stats = build_stats_from_schedule(names, schedule_raw)
    else:
        schedule = None
        stats = None

    # ===== pill 表示用の値を決める =====
    # 基本方針：
    #   - 今表示している schedule_raw があれば、そこから逆算した値を優先
    #   - schedule が無ければ、これまでどおりセッション or デフォルト
    derived_game_type = None
    derived_num_rounds = None
    derived_num_courts = None

    if schedule_raw:
        derived_game_type, derived_num_rounds, derived_num_courts = infer_meta_from_schedule(schedule_raw)

    if derived_game_type is not None:
        game_type = derived_game_type
        num_rounds = derived_num_rounds or DEFAULT_ROUNDS
        num_courts = derived_num_courts or DEFAULT_COURTS

        # セッションにも反映しておくと、次回以降も一貫した挙動になる
        request.session[f"event_{event.id}_game_type"] = game_type
        request.session[f"event_{event.id}_num_rounds"] = num_rounds
        request.session[f"event_{event.id}_num_courts"] = num_courts
    else:
        # まだ対戦表が一度も作られていないケースなどは従来動作
        game_type = request.session.get(f"event_{event.id}_game_type", "doubles")
        num_rounds = request.session.get(f"event_{event.id}_num_rounds", DEFAULT_ROUNDS)
        num_courts = request.session.get(f"event_{event.id}_num_courts", DEFAULT_COURTS)


    # 公開状態の判定
    if not schedule_raw:
        publish_state = "no_schedule"
    else:
        if schedule_source == "published":
            publish_state = "published"
        else:
            # draft_once を表示している（公開前 or 公開済みと別物）
            if published and schedule_raw != published:
                publish_state = "changed"  # 公開済みと異なる → 再公開可能
            elif published and schedule_raw == published:
                publish_state = "published"
            else:
                publish_state = "ready"    # まだ一度も公開していない

    schedule_json = json.dumps(schedule, ensure_ascii=False) if schedule else None

    # ============================================================
    # フラグ情報（ここはそのまま）
    # ============================================================
    flags = list(event.flag_definitions.all())
    MAX_FLAGS = 5

    pf_qs = ParticipantFlag.objects.filter(
        participant__event=event,
        flag__event=event,
    )
    flag_states = {(pf.participant_id, pf.flag_id): pf.checked for pf in pf_qs}

    # ============================================================
    # レンダリング
    # ============================================================
    return render(
        request,
        "tennis/event_admin.html",
        {
            "event": event,
            "participants": participants,
            "schedule": schedule,
            "num_rounds": num_rounds,
            "num_courts": num_courts,
            "stats": stats,
            "match_count": match_count,
            "game_type": game_type,
            "publish_state": publish_state,
            "schedule_json": schedule_json,
            "flags": flags,
            "flag_states": flag_states,
            "max_flags": MAX_FLAGS,
        },
    )


@csrf_exempt
def publish_schedule(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=400)

    event_id = request.POST.get("event_id")
    event = Event.objects.filter(id=event_id).first()
    if not event:
        return JsonResponse({"error": "Event not found"}, status=404)

    schedule_json = request.POST.get("schedule_json")
    if not schedule_json:
        return JsonResponse({"error": "No schedule provided"}, status=400)

    try:
        schedule = json.loads(schedule_json)

        # 公開＆ドラフトをこの schedule に揃える
        event.published_schedule = schedule
        event.draft_schedule = schedule

        # ★ 公開時点の「公式試合参加フラグ」を schedule に合わせて更新
        player_names = set()
        for round_info in schedule:
            for m in round_info.get("matches", []):
                player_names.update(m.get("team1", []))
                player_names.update(m.get("team2", []))

        for p in event.participants.filter(attendance="yes"):
            p.participates_match = (p.name in player_names)
            p.save(update_fields=["participates_match"])

        event.save()

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"status": "ok"})


@require_POST
def add_flag(request):
    """フラグを 1 つ追加（上限 5）。名前はデフォルト 'フラグN'。"""
    event_id = request.POST.get("event_id")
    event = get_object_or_404(Event, id=event_id)

    MAX_FLAGS = 5
    current = event.flag_definitions.count()
    if current >= MAX_FLAGS:
        return JsonResponse({"error": "max_reached", "max": MAX_FLAGS}, status=400)

    order = current + 1
    flag = FlagDefinition.objects.create(
        event=event,
        name=f"フラグ{order}",
        order=order,
    )
    return JsonResponse(
        {"id": flag.id, "name": flag.name, "order": flag.order}
    )


@require_POST
def delete_flag(request):
    """最後に作られたフラグを削除する"""
    event_id = request.POST.get("event_id")
    event = get_object_or_404(Event, id=event_id)

    # 最新（order の最大）を削除
    last_flag = event.flag_definitions.order_by("-order").first()
    if not last_flag:
        return JsonResponse({"error": "no_flag"}, status=400)

    last_flag.delete()
    return JsonResponse({"status": "ok"})



@require_POST
def rename_flag(request):
    """フラグ名の変更（ヘッダクリックで使う想定）"""
    flag_id = request.POST.get("flag_id")
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "empty_name"}, status=400)

    flag = get_object_or_404(FlagDefinition, id=flag_id)
    flag.name = name
    flag.save()
    return JsonResponse({"id": flag.id, "name": flag.name})


@require_POST
def toggle_flag(request):
    """参加者×フラグの ON/OFF 切り替え"""
    participant_id = request.POST.get("participant_id")
    flag_id = request.POST.get("flag_id")
    checked = request.POST.get("checked") == "true"

    participant = get_object_or_404(Participant, id=participant_id)
    flag = get_object_or_404(FlagDefinition, id=flag_id)

    pf, _ = ParticipantFlag.objects.get_or_create(
        participant=participant,
        flag=flag,
    )
    pf.checked = checked
    pf.save()

    return JsonResponse({"status": "ok"})


# 参加者リストと条件を受け取って対戦表＋サマリーだけ返すAPI
@require_POST
def ajax_generate_schedule(request, event_id):
    """
    対戦条件＆試合参加メンバーを受け取り、
    対戦表＋サマリーを HTML にして返す（ページはリロードしない）
    """
    event = get_object_or_404(Event, id=event_id)

    # 出席者（出欠 yes のみ）
    participants = list(
        event.participants.filter(attendance="yes").order_by("created_at")
    )

    # ===== チェックボックスで選ばれた「試合参加メンバー」 =====
    ids_str = request.POST.get("participant_ids", "").strip()
    if ids_str:
        try:
            selected_ids = {int(x) for x in ids_str.split(",") if x}
        except ValueError:
            return JsonResponse({"error": "bad participant_ids"}, status=400)
        match_participants = [p for p in participants if p.id in selected_ids]
    else:
        # 何も来なかった場合は DB 上の participates_match=True を採用
        match_participants = [
            p for p in participants if p.participates_match
        ]

    match_count = len(match_participants)
    names = [p.name for p in match_participants]

    # ===== 条件の取得 =====
    DEFAULT_ROUNDS = 10
    DEFAULT_COURTS = 1

    game_type = request.POST.get("game_type", "doubles")
    try:
        num_rounds = int(request.POST.get("num_rounds", DEFAULT_ROUNDS))
    except (TypeError, ValueError):
        num_rounds = DEFAULT_ROUNDS
    num_rounds = max(1, min(num_rounds, 20))

    try:
        num_courts = int(request.POST.get("num_courts", DEFAULT_COURTS))
    except (TypeError, ValueError):
        num_courts = DEFAULT_COURTS

    per_court = 4 if game_type == "doubles" else 2
    max_courts = (
        max(1, match_count // per_court) if match_count >= per_court else 1
    )
    num_courts = max(1, min(num_courts, max_courts))

    # ===== 対戦表生成 =====
    if match_count == 0:
        schedule = []
    else:
        if game_type == "singles":
            schedule = generate_singles_schedule(names, num_rounds, num_courts)
        else:
            schedule = generate_doubles_schedule(names, num_rounds, num_courts)

    # ===== stats 用の共通処理 =====
    def build_stats_from_schedule(names_list, schedule_list):
        if not schedule_list:
            return None, None

        all_names = names_list[:]
        round_seq = {n: [] for n in all_names}

        for round_info in schedule_list:
            playing = set()
            for m in round_info.get("matches", []):
                playing.update(m.get("team1", []))
                playing.update(m.get("team2", []))

            rests = [n for n in all_names if n not in playing]
            round_info["rests"] = rests

            for n in all_names:
                round_seq[n].append("P" if n in playing else "R")

        def max_streak(seq, target):
            cur = max_s = 0
            for x in seq:
                if x == target:
                    cur += 1
                    max_s = max(max_s, cur)
                else:
                    cur = 0
            return max_s

        stats_list = []
        # ★ 試合参加しない人はここに含めない
        for p in match_participants:
            seq = round_seq.get(p.name, [])
            stats_list.append(
                {
                    "name": p.name,
                    "matches": seq.count("P"),
                    "rests": seq.count("R"),
                    "max_play_streak": max_streak(seq, "P"),
                    "max_rest_streak": max_streak(seq, "R"),
                }
            )

        return schedule_list, stats_list


    if schedule:
        schedule, stats = build_stats_from_schedule(names, schedule)
    else:
        stats = None

    # ===== 公開状態の判定（publish_state） =====
    published = event.published_schedule
    if not schedule:
        publish_state = "no_schedule"
    else:
        if published and schedule == published:
            publish_state = "published"
        elif published and schedule != published:
            publish_state = "changed"
        else:
            publish_state = "ready"

    schedule_json = json.dumps(schedule, ensure_ascii=False) if schedule else None

    ctx = {
        "event": event,
        "schedule": schedule,
        "schedule_json": schedule_json,
        "stats": stats,
    }

    schedule_html = render_to_string("tennis/_schedule_block.html", ctx, request=request)
    stats_html = render_to_string("tennis/_stats_block.html", ctx, request=request)

    return JsonResponse(
        {
            "schedule_html": schedule_html,
            "stats_html": stats_html,
            "publish_state": publish_state,
            "game_type": game_type,
            "num_courts": num_courts,
            "num_rounds": num_rounds,
            "match_count": match_count,
        }
    )