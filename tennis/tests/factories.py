"""
テスト用のオブジェクト生成ヘルパ。

特性テスト（characterization test）の土台。
「あるべき仕様」ではなく「現状こう動く」を固定するためのデータを最小限で組む。
"""
from __future__ import annotations

from tennis.models import (
    Club,
    ClubFlagDefinition,
    Event,
    EventFlagDefinition,
    EventParticipant,
    MatchSchedule,
    MatchScore,
    Member,
    ParticipantFlag,
)


def make_club(name: str = "テストクラブ") -> Club:
    # public_token / admin_token は save() で自動採番される
    return Club.objects.create(name=name)


def make_event(club: Club, *, date, title: str = "", **kwargs) -> Event:
    return Event.objects.create(club=club, date=date, title=title, **kwargs)


def make_member(club: Club, display_name: str, *, is_fixed: bool = True, **kwargs) -> Member:
    return Member.objects.create(
        club=club, display_name=display_name, is_fixed=is_fixed, **kwargs
    )


def make_ep(
    event: Event,
    *,
    member: Member | None = None,
    display_name: str | None = None,
    attendance: str | None = None,
    participates_match: bool = False,
) -> EventParticipant:
    if display_name is None:
        display_name = member.display_name if member else "ゲスト"
    return EventParticipant.objects.create(
        event=event,
        member=member,
        display_name=display_name,
        attendance=attendance,
        participates_match=participates_match,
    )


def make_published_schedule(
    event: Event,
    schedule_json,
    *,
    game_type: str = "doubles",
    court_count: int = 1,
    round_count: int = 1,
) -> MatchSchedule:
    return MatchSchedule.objects.create(
        event=event,
        schedule_json=schedule_json,
        game_type=game_type,
        court_count=court_count,
        round_count=round_count,
        published=True,
    )


def make_score(ms: MatchSchedule, round_no: int, court_no: int, a: int, b: int) -> MatchScore:
    return MatchScore.objects.create(
        match_schedule=ms,
        round_no=round_no,
        court_no=court_no,
        side_a_score=a,
        side_b_score=b,
    )


def make_club_flag(club: Club, name: str, display_order: int, *, input_mode: str = "check") -> ClubFlagDefinition:
    return ClubFlagDefinition.objects.create(
        club=club, name=name, display_order=display_order, input_mode=input_mode
    )


def make_event_flag(event: Event, name: str, display_order: int, *, input_mode: str = "check") -> EventFlagDefinition:
    return EventFlagDefinition.objects.create(
        event=event, name=name, display_order=display_order, input_mode=input_mode
    )


def make_participant_flag(
    ep: EventParticipant,
    *,
    club_flag: ClubFlagDefinition | None = None,
    event_flag: EventFlagDefinition | None = None,
    is_on: bool = False,
    value: int | None = None,
) -> ParticipantFlag:
    # CheckConstraint: club_flag / event_flag のどちらか一方のみ
    return ParticipantFlag.objects.create(
        event_participant=ep,
        club_flag_definition=club_flag,
        event_flag_definition=event_flag,
        is_on=is_on,
        value=value,
    )


def set_admin_session(client, event_id: int) -> None:
    """テストクライアントに幹事セッションを立てる（views._admin_session_key と同じキー）。"""
    session = client.session
    session[f"tennis_event_admin:{event_id}"] = True
    session.save()
