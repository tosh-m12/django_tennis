# tennis/models.py
import uuid
from django.db import models

class Event(models.Model):
    title = models.CharField(max_length=200)
    date = models.DateField()
    place = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)

    public_token = models.CharField(max_length=32, unique=True, editable=False)
    admin_token = models.CharField(max_length=32, unique=True, editable=False)

    # JSONで保存（draft / published）
    draft_schedule = models.JSONField(null=True, blank=True)
    published_schedule = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["date"], name="uniq_event_per_day"),
        ]

    def save(self, *args, **kwargs):
        if not self.public_token:
            self.public_token = uuid.uuid4().hex
        if not self.admin_token:
            self.admin_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} {self.title}"


class Participant(models.Model):
    ATTENDANCE_CHOICES = [
        ("yes", "参加"),
        ("no", "不参加"),
        ("maybe", "未定"),
    ]

    event = models.ForeignKey(Event, related_name="participants", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    attendance = models.CharField(max_length=10, choices=ATTENDANCE_CHOICES, default="yes")
    level = models.CharField(max_length=50, blank=True)
    comment = models.CharField(max_length=200, blank=True)

    # 幹事が「対戦に入れる人」をチェックする
    participates_match = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("event", "name")]

    def __str__(self):
        return f"{self.event_id} {self.name}"
