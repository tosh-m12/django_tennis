# tennis/models.py
import uuid
from django.db import models
from django.db.models import JSONField   # ← 正しい JSONField import


class Event(models.Model):
    """
    1回分のテニス会
    """
    title = models.CharField("タイトル", max_length=200)
    date = models.DateField("日付")
    start_time = models.TimeField("開始時間", null=True, blank=True)
    place = models.CharField("場所", max_length=200, blank=True)
    note = models.TextField("メモ", blank=True)

    # URL 用トークン
    public_token = models.CharField(max_length=64, unique=True, editable=False)
    admin_token = models.CharField(max_length=64, unique=True, editable=False)

    # ★ 公開済みの公式対戦表（確定）
    published_schedule = JSONField(null=True, blank=True)

    # ★ 幹事が作った下書きの対戦表（公開前のプレビュー）
    draft_schedule = JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.public_token:
            self.public_token = uuid.uuid4().hex
        if not self.admin_token:
            self.admin_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} {self.title}"


class Participant(models.Model):
    ATTEND_CHOICES = [
        ("yes", "参加"),
        ("no", "不参加"),
        ("maybe", "未定"),
    ]

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="participants"
    )
    name = models.CharField("名前 / ニックネーム", max_length=100)
    level = models.CharField("レベル", max_length=50, blank=True)

    attendance = models.CharField(
        "出欠", max_length=10, choices=ATTEND_CHOICES, default="yes"
    )

    # ★ 試合に出るかどうか
    participates_match = models.BooleanField("試合に参加する", default=True)

    comment = models.CharField("コメント", max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class FlagDefinition(models.Model):
    """イベントごとのフラグ列定義"""
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="flag_definitions"
    )
    name = models.CharField("フラグ名", max_length=50)
    order = models.PositiveSmallIntegerField("表示順", default=1)

    class Meta:
        ordering = ["order"]
        unique_together = ("event", "order")

    def __str__(self):
        return f"{self.event.title} / {self.name}"


class ParticipantFlag(models.Model):
    """参加者×フラグの ON/OFF"""
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="participant_flags"
    )
    flag = models.ForeignKey(
        FlagDefinition, on_delete=models.CASCADE, related_name="participant_flags"
    )
    checked = models.BooleanField("フラグON", default=False)

    class Meta:
        unique_together = ("participant", "flag")

    def __str__(self):
        return f"{self.participant.name} - {self.flag.name}: {self.checked}"
