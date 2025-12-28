# tennis/models.py
import uuid
from django.db import models, transaction
from django.db.models import Q, Max
from django.utils import timezone


# ============================================================
# Core: Club / Event / Member / EventParticipant
# （V1仕様：クラブ単位トークン、未登録行はDBに作らない）
# ============================================================

class Club(models.Model):
    name = models.CharField(max_length=200)

    # V1：クラブ単位トークンのみ
    public_token = models.CharField(max_length=64, unique=True, editable=False)
    admin_token = models.CharField(max_length=64, unique=True, editable=False)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    FLAG_INPUT_MODE_CHOICES = (
        ("check", "チェックボックス"),
        ("digit", "数字(1桁)"),
    )
    flag_input_mode = models.CharField(
        max_length=10,
        choices=FLAG_INPUT_MODE_CHOICES,
        default="check",
    )

    def save(self, *args, **kwargs):
        if not self.public_token:
            self.public_token = uuid.uuid4().hex
        if not self.admin_token:
            self.admin_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    """
    1回分の練習回（イベント）
    - V1：イベント単位トークンは持たない（廃止）
    """
    club = models.ForeignKey(
        Club, on_delete=models.CASCADE, related_name="events"
    )

    title = models.CharField(max_length=200, blank=True)  # 未入力ならUI側で「練習」等
    place = models.CharField(max_length=200, blank=True, default="")
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    cancelled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "date"]),
        ]
        ordering = ["date", "id"]

    def __str__(self) -> str:
        t = self.title or "練習"
        return f"{self.date} {t}"

class Member(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="members")
    display_name = models.CharField(max_length=100)

    is_fixed = models.BooleanField(default=False)

    # ★まずは nullable で追加（既存行があるため）
    member_no = models.PositiveIntegerField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "is_fixed"]),
            models.Index(fields=["club", "member_no"]),
        ]
        ordering = ["-is_fixed", "display_name", "id"]
        constraints = [
            # ★後でNOT NULLにしてから有効化でもOK（まずは付けても動くがNULLがある間は注意）
            models.UniqueConstraint(fields=["club", "member_no"], name="uniq_member_no_per_club"),
        ]

    def __str__(self) -> str:
        return f"{self.club_id}:{self.display_name}"

class Attendance(models.TextChoices):
    YES = "yes", "参加"
    NO = "no", "不参加"
    MAYBE = "maybe", "未定"


class EventParticipant(models.Model):
    """
    イベント参加者（固定/ゲスト混在）
    - V1：固定メンバーはUI上「未登録行」で表示し、初回入力時にだけ作成する
    - member_id は原則付与（ゲストも member を作って付与する運用）
    - 例外的に member=NULL の参加者は過去互換/移行データ等として許容
    """
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="event_participants"
    )

    member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="event_participants"
    )

    # 当該イベントでの表示名（作成時は原則 member.display_name をコピー）
    display_name = models.CharField(max_length=100)

    # yes / no / maybe / NULL（未設定）
    attendance = models.CharField(
        max_length=10, choices=Attendance.choices, null=True, blank=True
    )

    participates_match = models.BooleanField(default=False)  # 幹事のみ操作
    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["event", "member"]),
            models.Index(fields=["event", "attendance"]),
            models.Index(fields=["event", "participates_match"]),
        ]
        constraints = [
            # filtered unique: unique(event, member) WHERE member IS NOT NULL
            models.UniqueConstraint(
                fields=["event", "member"],
                condition=Q(member__isnull=False),
                name="uq_event_participant_event_member_notnull",
            ),
        ]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.event_id}:{self.display_name}"


# ============================================================
# Club-wide flag definitions & per-participant flag ON/OFF
# （V1：最大3個、クラブ共通）
# ============================================================

class ClubFlagDefinition(models.Model):
    club = models.ForeignKey(
        Club, on_delete=models.CASCADE, related_name="flag_definitions"
    )
    name = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField()

    INPUT_MODE_CHECK = "check"
    INPUT_MODE_DIGIT = "digit"
    INPUT_MODE_CHOICES = [
        (INPUT_MODE_CHECK, "チェック"),
        (INPUT_MODE_DIGIT, "数字(1桁)"),
    ]
    input_mode = models.CharField(
        max_length=10,
        choices=INPUT_MODE_CHOICES,
        default=INPUT_MODE_CHECK,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "is_active"]),
            models.Index(fields=["club", "display_order"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["club", "display_order"],
                name="uq_club_flag_definition_club_display_order",
            ),
        ]
        ordering = ["display_order", "id"]

    def __str__(self) -> str:
        return f"{self.club_id}:{self.name}"


class ParticipantFlag(models.Model):
    """
    イベント参加者に対するフラグON/OFF
    - フラグ操作時、対象が「未登録行」なら先に EventParticipant を作ってから保存（view側）
    """
    event_participant = models.ForeignKey(
        EventParticipant, on_delete=models.CASCADE, related_name="flags"
    )
    flag_definition = models.ForeignKey(
        ClubFlagDefinition, on_delete=models.CASCADE, related_name="participant_flags"
    )
    is_on = models.BooleanField(default=False)

    value = models.SmallIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_participant", "flag_definition"],
                name="uq_participant_flag_ep_flagdef",
            ),
        ]
        indexes = [
            models.Index(fields=["flag_definition", "is_on"]),
        ]


# ============================================================
# Match Schedule (published) / Draft / Score / Substitution
# （V1仕様：schedule_json を正として保持）
# ============================================================

class GameType(models.TextChoices):
    DOUBLES = "doubles", "Doubles"
    SINGLES = "singles", "Singles"


class MatchSchedule(models.Model):
    """
    対戦表（公開版）
    - イベントにつき1つ（unique(event)）
    - locked は「スコアが1件でも入力されたら true」
    """
    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="match_schedule"
    )

    schedule_json = models.JSONField()  # 対戦表本体（UI/集計の正）
    game_type = models.CharField(max_length=10, choices=GameType.choices)
    court_count = models.PositiveIntegerField()
    round_count = models.PositiveIntegerField()

    published = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["published"]),
            models.Index(fields=["locked"]),
        ]

    def __str__(self) -> str:
        return f"event={self.event_id} published={self.published} locked={self.locked}"


class MatchScheduleDraft(models.Model):
    """
    生成中ドラフト（イベントにつき1つ）
    """
    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="match_schedule_draft"
    )

    draft_json = models.JSONField(null=True, blank=True)
    params_json = models.JSONField(null=True, blank=True)  # game_type/court_count/round_count 等

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"event={self.event_id} draft"


class MatchScore(models.Model):
    """
    スコア（round/court 単位）
    - どちらか片方でも入ったら「入力あり」とみなして locked 判定に使ってよい
    """
    match_schedule = models.ForeignKey(
        MatchSchedule, on_delete=models.CASCADE, related_name="scores"
    )

    round_no = models.PositiveIntegerField()
    court_no = models.PositiveIntegerField()

    side_a_score = models.PositiveIntegerField(null=True, blank=True)
    side_b_score = models.PositiveIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match_schedule", "round_no", "court_no"],
                name="uq_match_score_schedule_round_court",
            ),
        ]
        indexes = [
            models.Index(fields=["match_schedule", "round_no"]),
        ]
        ordering = ["round_no", "court_no", "id"]

    def __str__(self) -> str:
        return f"sch={self.match_schedule_id} R{self.round_no} C{self.court_no} {self.side_a_score}-{self.side_b_score}"


class Substitution(models.Model):
    """
    代打（現状態のみ）
    """
    match_schedule = models.ForeignKey(
        MatchSchedule, on_delete=models.CASCADE, related_name="substitutions"
    )

    round_no = models.PositiveIntegerField()

    original_participant = models.ForeignKey(
        EventParticipant, on_delete=models.CASCADE, related_name="substituted_from"
    )
    substitute_participant = models.ForeignKey(
        EventParticipant, on_delete=models.CASCADE, related_name="substituted_to"
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match_schedule", "round_no", "original_participant"],
                name="uq_substitution_schedule_round_original",
            ),
        ]
        indexes = [
            models.Index(fields=["match_schedule", "round_no"]),
        ]

    def __str__(self) -> str:
        return f"sch={self.match_schedule_id} R{self.round_no} {self.original_participant_id}->{self.substitute_participant_id}"


# ============================================================
# Optional: Audit Log (V1は任意)
# ============================================================

class ActorTokenKind(models.TextChoices):
    PUBLIC = "public", "public"
    ADMIN = "admin", "admin"


class AuditLog(models.Model):
    """
    V1必須ではないが、「全員編集可」のため将来トラブル対応に有効
    - 個人特定はしない（token種別のみ）
    """
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="audit_logs")
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")

    actor_token_kind = models.CharField(max_length=10, choices=ActorTokenKind.choices)
    action = models.CharField(max_length=100)
    payload_json = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "created_at"]),
            models.Index(fields=["event", "created_at"]),
            models.Index(fields=["action"]),
        ]
        ordering = ["-created_at", "id"]

    def __str__(self) -> str:
        return f"{self.created_at} {self.actor_token_kind} {self.action}"
