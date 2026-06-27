"""
デモクラブ（deucenet.app/demo）のシード・毎日リセット処理。

方針:
- is_demo=True のクラブを 1 つだけ持ち、/demo はそこへ誘導する。
- メンバー10名（固定メンバー）を常駐させる。
- 過去90日内にダブルス/シングルスの「公開済み対戦表＋スコア」を仕込み、
  戦績ランキングがそのまま生成される状態にする。
- 「今日」の公開済みイベント（スコア一部空欄）と「直近」の出欠受付イベントを置き、
  訪問者がメンバーモードのまま「名前追加→出欠→スコア入力→ランキング反映」を体験できる。
- 訪問者が増やしたデータは毎日リセットでベースラインへ戻す（クラブ行とトークンは保持）。

シードは固定シードの乱数で決定的（毎日同じ初期状態）に作る。
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

DEMO_CLUB_NAME = "デモテニスサークル"

# 常駐メンバー10名（固定メンバー）。括弧内コメントは想定の強さ（スコア生成のバイアス）。
DEMO_MEMBERS = [
    "佐藤 大輔",
    "鈴木 健一",
    "高橋 翔",
    "田中 由紀",
    "渡辺 彩",
    "伊藤 拓也",
    "山本 真央",
    "中村 蓮",
    "小林 結衣",
    "加藤 涼",
]

# 決定的に作るための固定シード。
_SEED = 20260627


def get_or_create_demo_club() -> Club:
    """is_demo のクラブを返す（無ければ枠だけ作る。データ投入は reseed 側）。"""
    club = Club.objects.filter(is_demo=True, is_active=True).order_by("id").first()
    if club is None:
        club = Club.objects.create(name=DEMO_CLUB_NAME, is_demo=True)
    return club


def ensure_demo_fresh() -> Club:
    """
    /demo アクセス時に呼ぶ。クラブを用意し、シード日が今日でなければ 1 プロセスだけが
    リセットを実行する（同時アクセスでの二重シードを update の原子性で防ぐ）。
    """
    club = get_or_create_demo_club()
    today = timezone.localdate()
    if club.demo_seeded_on == today:
        return club

    # 「今日まだシードしていない」行だけを today に更新できた 1 者がシードを担当。
    claimed = (
        Club.objects.filter(pk=club.pk)
        .exclude(demo_seeded_on=today)
        .update(demo_seeded_on=today)
    )
    if claimed:
        reseed_demo_club(club)
    club.refresh_from_db()
    return club


@transaction.atomic
def reseed_demo_club(club: Club | None = None) -> Club:
    """デモクラブの中身を全消去してベースラインを作り直す。クラブ行とトークンは保持。"""
    if club is None:
        club = get_or_create_demo_club()

    club.name = DEMO_CLUB_NAME
    club.is_demo = True
    club.is_active = True

    # 既存データ全消去（Event 削除で EP/対戦表/スコアもカスケード）。
    Event.objects.filter(club=club).delete()
    Member.objects.filter(club=club).delete()

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

    # 10名の固定メンバーを作成。skill は順位付けが自然になるよう降順割当 → シャッフル。
    members: list[Member] = []
    skills = list(range(len(DEMO_MEMBERS), 0, -1))  # 10,9,...,1
    rng.shuffle(skills)
    for i, name in enumerate(DEMO_MEMBERS, start=1):
        m = Member.objects.create(
            club=club,
            member_no=i,
            display_name=name,
            is_fixed=True,
        )
        m._skill = skills[i - 1]  # type: ignore[attr-defined]  # 一時属性（スコア生成用）
        members.append(m)

    skill_by_member_id = {m.id: m._skill for m in members}  # type: ignore[attr-defined]

    today = timezone.localdate()

    # ---- 過去の実績イベント（公開済み対戦表＋スコア）----
    # ダブルス12回 + シングルス8回を過去85日に散らす。
    doubles_days = _spread_days(today, count=12, span=85, start_offset=3, rng=rng)
    singles_days = _spread_days(today, count=8, span=80, start_offset=6, rng=rng)

    for d in doubles_days:
        _make_scored_event(
            club, members, d, GameType.DOUBLES,
            rng=rng, skill_by_member_id=skill_by_member_id,
            num_rounds=6, num_courts=2, fill_ratio=1.0,
        )
    for d in singles_days:
        _make_scored_event(
            club, members, d, GameType.SINGLES,
            rng=rng, skill_by_member_id=skill_by_member_id,
            num_rounds=6, num_courts=3, fill_ratio=1.0,
        )

    # ---- 「今日」の公開済みイベント（スコア一部空欄＝訪問者が入力して体験）----
    _make_scored_event(
        club, members, today, GameType.DOUBLES,
        rng=rng, skill_by_member_id=skill_by_member_id,
        num_rounds=6, num_courts=2, fill_ratio=0.6,
        title="本日の練習（スコア入力を試せます）",
    )

    # ---- 直近の出欠受付イベント（対戦表なし＝訪問者が名前追加・出欠を試せる）----
    # /demo は当月カレンダーを表示するので、この案内イベントは当月内に収めて見つけやすくする。
    upcoming = Event.objects.create(
        club=club,
        title="次回の練習（名前を追加してみてください）",
        place="市民コート",
        date=_upcoming_date_in_month(today),
        start_time=dt.time(9, 0),
        end_time=dt.time(12, 0),
    )
    # 固定メンバーは「未登録行」として表示されるので EP は作らない（訪問者の追加余地を残す）。
    _ = upcoming

    club.demo_seeded_on = today
    club.save(update_fields=["name", "is_demo", "is_active", "demo_seeded_on", "updated_at"])
    return club


def _upcoming_date_in_month(today: dt.date) -> dt.date:
    """名前追加案内イベントの日付。基本は today+4 だが、当月をはみ出す場合は当月末日に寄せる
    （当月カレンダーで必ず見えるように）。月末当日だけは翌日になる。"""
    target = today + dt.timedelta(days=4)
    if target.month == today.month:
        return target
    # 当月末日を求める
    if today.month == 12:
        first_next = dt.date(today.year + 1, 1, 1)
    else:
        first_next = dt.date(today.year, today.month + 1, 1)
    month_end = first_next - dt.timedelta(days=1)
    if month_end > today:
        return month_end
    return today + dt.timedelta(days=1)


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
    """1イベント分：参加者EP・公開済み対戦表・スコアを作る。"""
    label = "練習（ダブルス）" if game_type == GameType.DOUBLES else "練習（シングルス）"
    ev = Event.objects.create(
        club=club,
        title=title or label,
        place=rng.choice(["市民コート", "中央公園コート", "river side テニスクラブ"]),
        date=date,
        start_time=dt.time(9, 0),
        end_time=dt.time(12, 0),
    )

    # 全メンバーを参加者（出席・対戦参加）として登録。
    eps: list[EventParticipant] = []
    skill_by_ep_id: dict[int, int] = {}
    for m in members:
        ep = EventParticipant.objects.create(
            event=ev,
            member=m,
            display_name=m.display_name,
            attendance="yes",
            participates_match=True,
        )
        eps.append(ep)
        skill_by_ep_id[ep.id] = skill_by_member_id[m.id]

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
    for r in schedule:
        round_no = int(r.get("round") or 0)
        for mt in (r.get("matches") or []):
            court_no = int(mt.get("court") or 0)
            if rng.random() > fill_ratio:
                continue  # 一部空欄（訪問者が入力できる余地）
            t1 = mt.get("team1") or []
            t2 = mt.get("team2") or []
            s1, s2 = _gen_score(t1, t2, skill_by_ep_id, rng)
            MatchScore.objects.create(
                match_schedule=ms,
                round_no=round_no,
                court_no=court_no,
                side_a_score=s1,
                side_b_score=s2,
            )

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
