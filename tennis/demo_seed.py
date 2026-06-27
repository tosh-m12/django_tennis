"""
デモクラブ（deucenet.app/demo）のシード処理。

方針:
- /demo は訪問者（セッション）ごとに専用の is_demo クラブを発行する（他人と干渉しない）。
- 各クラブにメンバー10名（歴代プロ選手名）を固定メンバーとして登録。
- 過去90日内にダブルス/シングルスの「公開済み対戦表＋スコア」を仕込み、
  戦績ランキングがそのまま生成される状態にする。
- 「今日」の公開済みイベント（スコア一部空欄）と「直近」の出欠受付イベントを置き、
  訪問者がメンバーモードのまま「名前追加→出欠→スコア入力→ランキング反映」を体験できる。
- 一定時間アクセスが無いデモクラブは離脱とみなし自動削除（sweep）する。

シードは固定シードの乱数で決定的（毎回同じ初期状態）に作る。

性能/堅牢性:
- 本番(Railway)はアプリとPostgresが別サービスで1往復が重いため、INSERTは bulk_create で
  まとめてラウンドトリップ数を抑える（Web リクエスト内で gunicorn timeout に達しないように）。
- クラブ作成〜シードは同一トランザクションで行い、失敗時はクラブごとロールバックする
  （空のクラブが残らない）。
"""
from __future__ import annotations

import datetime as dt
import random

from django.db import transaction
from django.utils import timezone

from .models import (
    Club,
    ClubRankingSetting,
    Event,
    EventParticipant,
    GameType,
    Member,
    MatchSchedule,
    MatchScore,
)
from .utils import generate_doubles_schedule, generate_singles_schedule

DEMO_CLUB_NAME = "デモテニスクラブ"

# 無操作のデモクラブを離脱とみなして削除するまでの時間（分）。
DEMO_TTL_MINUTES = 30

# 常駐メンバー20名（固定メンバー）。実在風の人名は避け、歴代プロテニス選手名（男女混合）を使う。
DEMO_MEMBERS = [
    # 男子
    "フェデラー",
    "ナダル",
    "ジョコビッチ",
    "マレー",
    "サンプラス",
    "アガシ",
    "ボルグ",
    "マッケンロー",
    "ベッカー",
    "エドベリ",
    # 女子
    "グラフ",
    "ナブラチロワ",
    "セレナ",
    "ヴィーナス",
    "ヒンギス",
    "シャラポワ",
    "エナン",
    "クライシュテルス",
    "セレシュ",
    "ウォズニアッキ",
]

# 決定的に作るための固定シード。
_SEED = 20260627


@transaction.atomic
def create_seeded_demo_club(now=None) -> Club:
    """新しいデモクラブを 1 つ作り、ベースライン（メンバー＋ダミー実績）を投入して返す。"""
    if now is None:
        now = timezone.now()
    club = Club.objects.create(
        name=DEMO_CLUB_NAME,
        is_demo=True,
        demo_last_seen=now,
    )
    _seed_demo_club(club)
    return club


def sweep_stale_demo_clubs(now=None, ttl_minutes: int = DEMO_TTL_MINUTES) -> int:
    """無操作が続いたデモクラブを削除（離脱とみなしてリセット）。削除件数を返す。"""
    from django.db.models import Q

    if now is None:
        now = timezone.now()
    cutoff = now - dt.timedelta(minutes=ttl_minutes)
    # demo_last_seen が cutoff より前、または未設定（古い取り残し）を対象。
    stale = Club.objects.filter(is_demo=True).filter(
        Q(demo_last_seen__lt=cutoff) | Q(demo_last_seen__isnull=True)
    )
    count = stale.count()
    if count:
        stale.delete()  # Event/Member 等はカスケード削除
    return count


@transaction.atomic
def reseed_demo_club(club: Club) -> Club:
    """既存デモクラブの中身を全消去してベースラインを作り直す（手動リセット/テスト用）。"""
    Event.objects.filter(club=club).delete()
    Member.objects.filter(club=club).delete()
    _seed_demo_club(club)
    return club


def _seed_demo_club(club: Club) -> Club:
    """club にベースライン（ルール・固定メンバー10名・過去実績・体験用イベント）を投入。"""
    club.name = DEMO_CLUB_NAME
    club.is_demo = True
    club.is_active = True

    rng = random.Random(_SEED)

    # ランキングルール（既定の勝率重視型・最低6試合・90日窓）を明示設定。
    ClubRankingSetting.objects.update_or_create(
        club=club,
        defaults={
            "preset": ClubRankingSetting.PRESET_WINRATE,
            "count_draws": False,
            "points_win": 3,
            "points_draw": 1,
            "points_loss": 0,
            "min_matches": 6,
            "period_days": 90,
        },
    )

    # 10名の固定メンバーを一括作成。skill は順位付けが自然になるよう降順割当 → シャッフル。
    skills = list(range(len(DEMO_MEMBERS), 0, -1))  # 10,9,...,1
    rng.shuffle(skills)
    members = [
        Member(club=club, member_no=i, display_name=name, is_fixed=True)
        for i, name in enumerate(DEMO_MEMBERS, start=1)
    ]
    Member.objects.bulk_create(members)  # pk が各 member にセットされる(PG/SQLite3.35+)
    skill_by_member_id = {m.id: skills[idx] for idx, m in enumerate(members)}

    today = timezone.localdate()

    # ---- 過去の実績イベント（公開済み対戦表＋スコア）----
    # ダブルス12回 + シングルス8回を過去85日に散らす。
    doubles_days = _spread_days(today, count=12, span=85, start_offset=3, rng=rng)
    singles_days = _spread_days(today, count=8, span=80, start_offset=6, rng=rng)

    for d in doubles_days:
        _make_scored_event(
            club, members, d, GameType.DOUBLES,
            rng=rng, skill_by_member_id=skill_by_member_id,
            num_rounds=6, num_courts=4, fill_ratio=1.0,
        )
    for d in singles_days:
        _make_scored_event(
            club, members, d, GameType.SINGLES,
            rng=rng, skill_by_member_id=skill_by_member_id,
            num_rounds=6, num_courts=5, fill_ratio=1.0,
        )

    # ---- 「今日」の公開済みイベント（スコア一部空欄＝訪問者が入力して体験）----
    _make_scored_event(
        club, members, today, GameType.DOUBLES,
        rng=rng, skill_by_member_id=skill_by_member_id,
        num_rounds=6, num_courts=4, fill_ratio=0.6,
        title="本日の練習（スコア入力を試せます）",
    )

    # ---- 直近の出欠受付イベント（対戦表なし＝訪問者が名前追加・出欠を試せる）----
    # /demo は当月カレンダーを表示するので、この案内イベントは当月内に収めて見つけやすくする。
    upcoming_date = _upcoming_date_in_month(today)
    Event.objects.create(
        club=club,
        title="次回の練習（名前を追加してみてください）",
        place="市民コート",
        date=upcoming_date,
        start_time=dt.time(9, 0),
        end_time=dt.time(12, 0),
    )
    # 固定メンバーは「未登録行」として表示されるので EP は作らない（訪問者の追加余地を残す）。

    # ---- 当月残り〜翌月の予定（対戦表なしのダミースケジュール）----
    # カレンダーを次月に進めても予定が並ぶように、将来日に練習予定を散らす。
    for d in _future_practice_days(today, rng, exclude={upcoming_date}):
        gt = rng.choice([GameType.DOUBLES, GameType.SINGLES])
        label = "練習（ダブルス）" if gt == GameType.DOUBLES else "練習（シングルス）"
        Event.objects.create(
            club=club,
            title=label,
            place=rng.choice(["市民コート", "中央公園コート", "river side テニスクラブ"]),
            date=d,
            start_time=dt.time(9, 0),
            end_time=dt.time(12, 0),
        )

    club.save(update_fields=["name", "is_demo", "is_active", "updated_at"])
    return club


def _upcoming_date_in_month(today: dt.date) -> dt.date:
    """名前追加案内イベントの日付。基本は today+4 だが、当月をはみ出す場合は当月末日に寄せる
    （当月カレンダーで必ず見えるように）。月末当日だけは翌日になる。"""
    target = today + dt.timedelta(days=4)
    if target.month == today.month:
        return target
    if today.month == 12:
        first_next = dt.date(today.year + 1, 1, 1)
    else:
        first_next = dt.date(today.year, today.month + 1, 1)
    month_end = first_next - dt.timedelta(days=1)
    if month_end > today:
        return month_end
    return today + dt.timedelta(days=1)


def _month_end(d: dt.date) -> dt.date:
    """d が属する月の末日。"""
    if d.month == 12:
        first_next = dt.date(d.year + 1, 1, 1)
    else:
        first_next = dt.date(d.year, d.month + 1, 1)
    return first_next - dt.timedelta(days=1)


def _future_practice_days(today: dt.date, rng: random.Random, *, exclude: set) -> list[dt.date]:
    """当月残り（翌日〜月末）から数件、翌月から多めに、練習予定日を散らして返す。"""
    days: list[dt.date] = []

    # 当月の残り（翌日〜当月末）から最大3件。
    cur_pool = [d for d in _date_range(today + dt.timedelta(days=1), _month_end(today)) if d not in exclude]
    rng.shuffle(cur_pool)
    days.extend(cur_pool[:3])

    # 翌月から7件。
    if today.month == 12:
        nm_first = dt.date(today.year + 1, 1, 1)
    else:
        nm_first = dt.date(today.year, today.month + 1, 1)
    next_pool = [d for d in _date_range(nm_first, _month_end(nm_first)) if d not in exclude]
    rng.shuffle(next_pool)
    days.extend(next_pool[:7])

    return sorted(days)


def _date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """start〜end（両端含む）の日付リスト。"""
    if end < start:
        return []
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _spread_days(today: dt.date, *, count: int, span: int, start_offset: int, rng: random.Random) -> list[dt.date]:
    """today から過去 span 日内に count 個の日付を、ほどよくばらして返す（重複なし・新しい順）。"""
    earliest = start_offset
    latest = min(span, 89)  # 90日窓に確実に収める
    pool = list(range(earliest, latest + 1))
    rng.shuffle(pool)
    offsets = sorted(pool[:count])
    return [today - dt.timedelta(days=o) for o in offsets]


def _make_scored_event(
    club: Club,
    members: list[Member],
    date: dt.date,
    game_type: str,
    *,
    rng: random.Random,
    skill_by_member_id: dict[int, int],
    num_rounds: int,
    num_courts: int,
    fill_ratio: float,
    title: str | None = None,
) -> Event:
    """1イベント分：参加者EP・公開済み対戦表・スコアを作る（INSERTは bulk_create でまとめる）。"""
    label = "練習（ダブルス）" if game_type == GameType.DOUBLES else "練習（シングルス）"
    ev = Event.objects.create(
        club=club,
        title=title or label,
        place=rng.choice(["市民コート", "中央公園コート", "river side テニスクラブ"]),
        date=date,
        start_time=dt.time(9, 0),
        end_time=dt.time(12, 0),
    )

    # 全メンバーを参加者（出席・対戦参加）として一括登録。
    eps = [
        EventParticipant(
            event=ev,
            member=m,
            display_name=m.display_name,
            attendance="yes",
            participates_match=True,
        )
        for m in members
    ]
    EventParticipant.objects.bulk_create(eps)  # pk が各 ep にセットされる
    skill_by_ep_id = {ep.id: skill_by_member_id[ep.member_id] for ep in eps}

    ep_ids = [ep.id for ep in eps]
    if game_type == GameType.SINGLES:
        schedule = generate_singles_schedule(ep_ids, num_rounds, num_courts)
    else:
        schedule = generate_doubles_schedule(ep_ids, num_rounds, num_courts)

    ms = MatchSchedule.objects.create(
        event=ev,
        schedule_json=schedule,
        game_type=game_type,
        court_count=num_courts,
        round_count=num_rounds,
        published=True,
        locked=True,
    )

    # スコア生成：チームの強さ差で勝敗を決め、テニスらしい 6-x / x-6 を入れる。
    scores = []
    for r in schedule:
        round_no = int(r.get("round") or 0)
        for mt in (r.get("matches") or []):
            court_no = int(mt.get("court") or 0)
            if rng.random() > fill_ratio:
                continue  # 一部空欄（訪問者が入力できる余地）
            s1, s2 = _gen_score(mt.get("team1") or [], mt.get("team2") or [], skill_by_ep_id, rng)
            scores.append(MatchScore(
                match_schedule=ms,
                round_no=round_no,
                court_no=court_no,
                side_a_score=s1,
                side_b_score=s2,
            ))
    if scores:
        MatchScore.objects.bulk_create(scores)

    return ev


def _gen_score(team1, team2, skill_by_ep_id: dict[int, int], rng: random.Random) -> tuple[int, int]:
    """チームの平均skill差で勝者を確率的に決め、6ゲーム先取のセットスコアを返す。"""
    def avg(team):
        vals = [skill_by_ep_id.get(int(p), 5) for p in team]
        return sum(vals) / len(vals) if vals else 5.0

    a = avg(team1)
    b = avg(team2)
    # skill 差を勝率へ（差が大きいほど強い側が勝ちやすい）。
    p_a = 1.0 / (1.0 + 10 ** (-(a - b) / 6.0))
    a_wins = rng.random() < p_a
    loser = rng.choice([3, 4, 4, 5, 2])  # 競り具合のばらつき
    if a_wins:
        return (6, loser)
    return (loser, 6)
