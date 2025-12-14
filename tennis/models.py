# tennis/models.py
from __future__ import annotations

import secrets
from django.db import models
from django.utils import timezone


def _gen_token(nbytes: int = 16) -> str:
    # URLに載せる前提なので、推測困難なランダム値（hex文字列）にする
    # 16bytes -> 32hex chars
    return secrets.token_hex(nbytes)


class Club(models.Model):
    """
    BETA: ログインなし。public_token / admin_token を知っている人がアクセス可能。
      - /c/<club_public_token>/
      - /c/<club_public_token>/admin/<club_admin_token>/settings/
    """
    name = models.CharField("クラブ名", max_length=100)

    public_token = models.CharField("公開トークン", max_length=64, unique=True, db_index=True)
    admin_token = models.CharField("幹事トークン", max_length=64, unique=True, db_index=True)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name}"

    def save(self, *args, **kwargs):
        # 初回作成時にトークンを自動発行
        if not self.public_token:
            self.public_token = _gen_token(16)
        if not self.admin_token:
            self.admin_token = _gen_token(16)
        super().save(*args, **kwargs)


class Event(models.Model):
    """
    Club配下の練習日（1日1回固定）
    - unique_together (club, date)
    - 公開/非公開 概念は廃止
    - スコアが1つでも入ったら確定（ロック）: locked_at / has_score
    """
    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="events",
        null=True,   # ★一時対応
        blank=True,  # ★一時対応
    )
    date = models.DateField("練習日")

    start_time = models.TimeField("開始時刻", null=True, blank=True)
    place = models.CharField("場所", max_length=255, blank=True)
    note = models.TextField("メモ", blank=True)

    # 対戦表（案）と（確定版）を保持
    # 生成ロジックは utils.py 側で JSON を作り、ここに保存する想定
    draft_schedule = models.JSONField("対戦表（下書き）", default=dict, blank=True)
    locked_schedule = models.JSONField("対戦表（確定版）", default=dict, blank=True)

    # ロック状態（スコアが入ったら確定）
    has_score = models.BooleanField("スコアあり", default=False)
    locked_at = models.DateTimeField("ロック日時", null=True, blank=True)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["club", "date"], name="uniq_event_club_date"),
        ]
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.club.name} {self.date}"

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_at) or self.has_score

    def lock(self):
        """
        スコア入力が1つでも入ったら呼ぶ想定。
        """
        self.has_score = True
        if not self.locked_at:
            self.locked_at = timezone.now()


class Participant(models.Model):
    """
    クラブ所属メンバー（表示名は重複OK、内部IDで管理）
    """
    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="participants",
        null=True,   # ★一時対応
        blank=True,  # ★一時対応
    )
    display_name = models.CharField("表示名", max_length=50)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.club.name})"


class Attendance(models.Model):
    class AttendanceChoice(models.TextChoices):
        YES = "yes", "〇"
        NO = "no", "×"
        MAYBE = "maybe", "？"

    event = models.ForeignKey("Event", on_delete=models.CASCADE, related_name="attendances", null=True, blank=True)
    participant = models.ForeignKey("Participant", on_delete=models.CASCADE, related_name="attendances", null=True, blank=True)

    attendance = models.CharField("出欠", max_length=10, choices=AttendanceChoice.choices, default=AttendanceChoice.MAYBE)
    participates_match = models.BooleanField("試合参加", default=False)
    comment = models.CharField("コメント", max_length=255, blank=True)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)


class ClubFlagDefinition(models.Model):
    """
    クラブ共通フラグ定義
    - 追加/名称変更/非表示(=inactive)/復活
    - 削除はしない
    """
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="flag_definitions")
    name = models.CharField("フラグ名", max_length=50)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("有効（表示）", default=True)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["club", "order"], name="uniq_flag_club_order"),
        ]
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.club.name} / {self.order}: {self.name}"


class AttendanceFlag(models.Model):
    attendance = models.ForeignKey("Attendance", on_delete=models.CASCADE, related_name="flags", null=True, blank=True)
    flag = models.ForeignKey("ClubFlagDefinition", on_delete=models.CASCADE, related_name="attendance_flags", null=True, blank=True)
    checked = models.BooleanField("チェック", default=False)


class MatchScore(models.Model):
    """
    BETA用：スコア入力（最短ルート）
    - 「スコアが1つでも入ったら Event をロック」の判定用に存在
    - 対戦表の詳細構造は locked_schedule(JSON) に持たせても良いが、
      スコアの永続化は別テーブルにした方が「消す/再生成」が安全。
    - 再生成時はこのテーブルを event単位で削除する運用でOK。
    """
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="scores", null=True, blank=True)

    # どの試合/どのコート/何番目…などをJSON側と対応させるキー
    # 例: "m1", "m2" / "court1_game3" など（utils側で決める）
    match_key = models.CharField("試合キー", max_length=50)

    # スコアは最短でテキスト（例: "6-4" "7-5" "6-2 3-6 10-8" など自由）
    score_text = models.CharField("スコア", max_length=50, blank=True)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "match_key"], name="uniq_score_event_matchkey"),
        ]
        ordering = ["match_key", "id"]

    def __str__(self) -> str:
        return f"{self.event.date} {self.match_key}: {self.score_text}"
