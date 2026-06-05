# tennis/models.py
import uuid

from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver
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
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="events")

    title = models.CharField(max_length=200, blank=True)  # 未入力ならUI側で「練習」等
    place = models.CharField(max_length=200, blank=True, default="")
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    cancelled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["club", "date"])]
        ordering = ["date", "id"]

    def __str__(self) -> str:
        t = self.title or "練習"
        return f"{self.date} {t}"


# ============================================================
# Club member class (optional grouping)
# ============================================================

class ClubMemberClass(models.Model):
    club = models.ForeignKey("Club", on_delete=models.CASCADE, related_name="member_classes")

    name = models.CharField(max_length=40)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "is_active"]),
            models.Index(fields=["club", "display_order"]),
        ]
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"{self.club_id}:{self.name}"


class Member(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="members")
    display_name = models.CharField(max_length=100)

    is_fixed = models.BooleanField(default=False)

    # ★既存行互換：まず nullable で運用 → データが埋まったら NOT NULL に移行できる
    member_no = models.PositiveIntegerField(null=True, blank=True)

    member_class = models.ForeignKey(
        "ClubMemberClass",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "is_fixed"]),
            models.Index(fields=["club", "member_no"]),
        ]
        ordering = ["-is_fixed", "display_name", "id"]
        constraints = [
            # NOTE:
            # - member_no が NULL の間は UniqueConstraint の意味が薄い（DBによりNULLは重複許容）
            # - いずれ member_no を NOT NULL にした段階で “厳密に効く”
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
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="event_participants")

    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_participants",
    )

    # 当該イベントでの表示名（作成時は原則 member.display_name をコピー）
    display_name = models.CharField(max_length=100)

    # yes / no / maybe / NULL（未設定）
    attendance = models.CharField(max_length=10, choices=Attendance.choices, null=True, blank=True)

    event_member_class = models.ForeignKey(
        "ClubMemberClass",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="event_participants",
    )

    class_name = models.CharField(max_length=40, blank=True, default="")

    # 紐づく Member が削除（退会）された EP の印。
    # member は SET_NULL で外れるため「退会者」か「元々ゲスト」かを区別できなくなる。
    # それを判別し、過去イベントの参加表で退会者をグレーアウト表示するためのフラグ。
    member_deleted = models.BooleanField(default=False)

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
# Event display setting (per-event)
# ============================================================

class EventDisplaySetting(models.Model):
    event = models.OneToOneField("Event", on_delete=models.CASCADE, related_name="display_setting")

    # 旧: flags → 新: common_flags
    show_flags = models.BooleanField(default=True)

    # ★追加：イベント固有フラグ列の表示
    show_event_flags = models.BooleanField(default=False)

    show_class = models.BooleanField(default=True)
    show_schedule = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    def as_dict(self):
        # ★サーバが返す形を「正」にする（JS側もこの形を前提にできる）
        return {
            "common_flags": bool(self.show_flags),
            "event_flags": bool(self.show_event_flags),
            "class": bool(self.show_class),
            "schedule": bool(self.show_schedule),
        }


# ============================================================
# Club display setting (per-club default)
# - 行が無いクラブはコード側ハードコードのデフォルトにフォールバック
# ============================================================

class ClubDisplaySetting(models.Model):
    club = models.OneToOneField("Club", on_delete=models.CASCADE, related_name="display_setting")

    show_flags = models.BooleanField(default=True)
    show_event_flags = models.BooleanField(default=False)
    show_class = models.BooleanField(default=True)
    show_schedule = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    def as_dict(self):
        return {
            "common_flags": bool(self.show_flags),
            "event_flags": bool(self.show_event_flags),
            "class": bool(self.show_class),
            "schedule": bool(self.show_schedule),
        }


class ClubRankingSetting(models.Model):
    """
    クラブ単位の戦績ランキング集計ルール。
    プリセット(勝率重視/勝ち点制/勝利数重視)が各値の初期値を決め、
    幹事が引き分けカウント・勝ち点・最低試合数を個別に上書きできる。
    上書き後の具体値をそのまま保持する（プリセット選択時にUIが初期値を流し込む）。
    """
    PRESET_WINRATE = "winrate"
    PRESET_POINTS = "points"
    PRESET_WINS = "wins"
    PRESET_CHOICES = [
        (PRESET_WINRATE, "勝率重視型"),
        (PRESET_POINTS, "勝ち点制"),
        (PRESET_WINS, "勝利数重視型"),
    ]

    club = models.OneToOneField("Club", on_delete=models.CASCADE, related_name="ranking_setting")
    preset = models.CharField(max_length=10, choices=PRESET_CHOICES, default=PRESET_WINRATE)
    count_draws = models.BooleanField(default=False)
    points_win = models.DecimalField(max_digits=4, decimal_places=1, default=3)
    points_draw = models.DecimalField(max_digits=4, decimal_places=1, default=1)
    points_loss = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    min_matches = models.PositiveIntegerField(default=6)
    # 集計対象期間（日）。戦績ページの既定期間＝過去この日数。推移グラフの各日の算出窓もこの日数。
    period_days = models.PositiveIntegerField(default=90)

    updated_at = models.DateTimeField(auto_now=True)

    def as_dict(self):
        return {
            "preset": self.preset,
            "count_draws": bool(self.count_draws),
            "points_win": float(self.points_win),
            "points_draw": float(self.points_draw),
            "points_loss": float(self.points_loss),
            "min_matches": int(self.min_matches),
            "period_days": int(self.period_days),
        }


# ============================================================
# Event-specific flag definitions (per-event)
# ============================================================

class EventFlagDefinition(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="event_flag_definitions")

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
            models.Index(fields=["event", "is_active"]),
            models.Index(fields=["event", "display_order"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "display_order"],
                name="uq_event_flag_definition_event_display_order",
            ),
        ]
        ordering = ["display_order", "id"]

    def __str__(self) -> str:
        return f"{self.event_id}:{self.name}"


# ============================================================
# Club-wide flag definitions & per-participant flag ON/OFF
# （V1：最大3個、クラブ共通）
# ============================================================

class ClubFlagDefinition(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="flag_definitions")

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
    - club_flag_definition / event_flag_definition のどちらか一方だけを持つ
    """
    event_participant = models.ForeignKey(
        EventParticipant, on_delete=models.CASCADE, related_name="flags"
    )

    # ★クラブ共通フラグ
    club_flag_definition = models.ForeignKey(
        ClubFlagDefinition,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="participant_flags",
    )

    # ★イベント固有フラグ
    event_flag_definition = models.ForeignKey(
        EventFlagDefinition,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="participant_flags",
    )

    is_on = models.BooleanField(default=False)

    # digit モードの場合の値
    value = models.SmallIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # club と event の両方を同時に持つのはNG / 両方NULLもNG
            models.CheckConstraint(
                condition=(
                    (models.Q(club_flag_definition__isnull=False) & models.Q(event_flag_definition__isnull=True)) |
                    (models.Q(club_flag_definition__isnull=True) & models.Q(event_flag_definition__isnull=False))
                ),
                name="ck_participant_flag_exactly_one_definition",
            ),


            # clubフラグ：同一参加者×同一クラブフラグは1行
            models.UniqueConstraint(
                fields=["event_participant", "club_flag_definition"],
                condition=models.Q(club_flag_definition__isnull=False),
                name="uq_participant_flag_ep_clubdef",
            ),

            # eventフラグ：同一参加者×同一イベントフラグは1行
            models.UniqueConstraint(
                fields=["event_participant", "event_flag_definition"],
                condition=models.Q(event_flag_definition__isnull=False),
                name="uq_participant_flag_ep_eventdef",
            ),
        ]
        indexes = [
            models.Index(fields=["club_flag_definition", "is_on"]),
            models.Index(fields=["event_flag_definition", "is_on"]),
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
    - イベントにつき1つ（OneToOne）
    - locked は「スコアが1件でも入力されたら true」運用
    """
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="match_schedule")

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
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="match_schedule_draft")

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
        return (
            f"sch={self.match_schedule_id} "
            f"R{self.round_no} C{self.court_no} "
            f"{self.side_a_score}-{self.side_b_score}"
        )


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
        return (
            f"sch={self.match_schedule_id} "
            f"R{self.round_no} "
            f"{self.original_participant_id}->{self.substitute_participant_id}"
        )


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
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

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


# ============================================================
# Signals
# ============================================================

@receiver(pre_delete, sender=Member)
def _mark_event_participants_on_member_delete(sender, instance, **kwargs):
    """
    Member 削除時、その Member に紐づく EventParticipant に退会印を付ける。
    - member は直後に SET_NULL で外れるため、削除“前”にここで印を残す。
    - club_delete_member ビュー / Django admin / QuerySet.delete() のいずれの
      削除経路でも pre_delete が発火するため、経路に依存せず印が付く。
    """
    EventParticipant.objects.filter(member=instance).update(member_deleted=True)

