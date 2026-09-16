import datetime

from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Club, Event, Member, EventParticipant, ClubFlagDefinition, EventFlagDefinition, ParticipantFlag, \
    MatchSchedule, MatchScheduleDraft, MatchScore, Substitution, AuditLog, ClubOrganizer, EmailThrottle


# ============================================================
# Club
# ============================================================


class ClubActivityFilter(admin.SimpleListFilter):
    title = "利用状況"
    parameter_name = "activity"

    def lookups(self, request, model_admin):
        return (
            ("recent", "30日以内"),
            ("inactive", "30日超"),
            ("never", "未アクセス"),
        )

    def queryset(self, request, queryset):
        threshold = timezone.now() - datetime.timedelta(days=30)
        if self.value() == "recent":
            return queryset.filter(last_accessed_at__gte=threshold)
        if self.value() == "inactive":
            return queryset.filter(last_accessed_at__lt=threshold)
        if self.value() == "never":
            return queryset.filter(last_accessed_at__isnull=True)
        return queryset


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "registration_email",
        "usage_summary",
        "last_accessed_datetime",
        "created_date",
        "club_home_urls",
        "is_active",
    )
    list_display_links = ("id", "name")
    search_fields = ("name", "registered_by_email", "public_token", "admin_token")
    list_filter = ("is_active", ClubActivityFilter)
    readonly_fields = (
        "public_token",
        "admin_token",
        "registration_email",
        "last_accessed_at",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _member_count=Count("members", distinct=True),
            _event_count=Count("events", distinct=True),
            _match_result_count=Count(
                "events__match_schedule__scores",
                filter=(
                    Q(events__match_schedule__scores__side_a_score__isnull=False)
                    | Q(events__match_schedule__scores__side_b_score__isnull=False)
                ),
                distinct=True,
            ),
        )

    @admin.display(description="利用実績")
    def usage_summary(self, obj: Club):
        return format_html(
            '<span style="white-space:nowrap">'
            "メンバー {}<br>イベント {}<br>試合結果 {}"
            "</span>",
            obj._member_count,
            obj._event_count,
            obj._match_result_count,
        )

    @admin.display(description="作成日", ordering="created_at")
    def created_date(self, obj: Club):
        return timezone.localtime(obj.created_at).strftime("%Y/%m/%d")

    @admin.display(description="登録者メールアドレス", ordering="registered_by_email", empty_value="—")
    def registration_email(self, obj: Club):
        return obj.registered_by_email or None

    @admin.display(description="最終アクセス日時", ordering="last_accessed_at", empty_value="—")
    def last_accessed_datetime(self, obj: Club):
        if obj.last_accessed_at is None:
            return None
        return timezone.localtime(obj.last_accessed_at).strftime("%Y/%m/%d %H:%M")

    @admin.display(description="URL")
    def club_home_urls(self, obj: Club):
        public_url = reverse("tennis:club_home", args=[obj.public_token])
        admin_url = reverse("tennis:club_home_admin", args=[obj.public_token, obj.admin_token])

        return format_html(
            '<a href="{}" target="_blank" rel="noopener">一般</a>'
            ' ｜ '
            '<a href="{}" target="_blank" rel="noopener">幹事</a>',
            public_url,
            admin_url,
        )

# ============================================================
# Event
# ============================================================

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "club",
        "title",
        "date",
        "start_time",
        "end_time",
        "place",
        "cancelled",
    )
    list_filter = ("club", "date", "cancelled")
    search_fields = ("title", "place")
    autocomplete_fields = ("club",)
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# Member
# ============================================================


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        "id",          # DB用ID（内部）
        "club",
        "member_no",   # ★クラブ内連番（表示・運用用）
        "display_name",
        "is_fixed",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "club",
        "is_fixed",
    )

    search_fields = (
        "display_name",
    )

    autocomplete_fields = (
        "club",
    )

    readonly_fields = (
        "member_no",
        "created_at",
        "updated_at",
    )

    ordering = (
        "club",
        "member_no",
        "id",
    )


# ============================================================
# EventParticipant
# ============================================================

@admin.register(EventParticipant)
class EventParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "member",
        "display_name",
        "attendance",
        "participates_match",
    )
    list_filter = ("event", "attendance", "participates_match")
    search_fields = ("display_name",)
    autocomplete_fields = ("event", "member")
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# ClubFlagDefinition
# ============================================================

@admin.register(ClubFlagDefinition)
class ClubFlagDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "club",
        "name",
        "display_order",
        "is_active",
    )
    list_filter = ("club", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("club",)
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# EventFlagDefinition
# ============================================================

@admin.register(EventFlagDefinition)
class EventFlagDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "name",
        "display_order",
        "is_active",
        "input_mode",
    )
    list_filter = ("event", "is_active", "input_mode")
    search_fields = ("name",)
    autocomplete_fields = ("event",)
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# ParticipantFlag
# ============================================================

@admin.register(ParticipantFlag)
class ParticipantFlagAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_participant",
        "club_flag_definition",
        "event_flag_definition",
        "is_on",
        "value",
        "updated_at",
    )
    list_filter = ("club_flag_definition", "event_flag_definition", "is_on")
    autocomplete_fields = ("event_participant", "club_flag_definition", "event_flag_definition")
    readonly_fields = ("updated_at",)


# ============================================================
# MatchSchedule（公開版）
# ============================================================

@admin.register(MatchSchedule)
class MatchScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "published",
        "locked",
        "game_type",
        "court_count",
        "round_count",
    )
    list_filter = ("published", "locked", "game_type")
    autocomplete_fields = ("event",)
    search_fields = (
        "event__title",
        "event__id",
    )
    readonly_fields = ("created_at", "updated_at")



# ============================================================
# MatchScheduleDraft
# ============================================================

@admin.register(MatchScheduleDraft)
class MatchScheduleDraftAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "updated_at",
    )
    autocomplete_fields = ("event",)
    readonly_fields = ("updated_at",)


# ============================================================
# MatchScore
# ============================================================

@admin.register(MatchScore)
class MatchScoreAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "match_schedule",
        "round_no",
        "court_no",
        "side_a_score",
        "side_b_score",
    )
    list_filter = ("match_schedule", "round_no", "court_no")
    autocomplete_fields = ("match_schedule",)
    readonly_fields = ("updated_at",)


# ============================================================
# Substitution
# ============================================================

@admin.register(Substitution)
class SubstitutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "match_schedule",
        "round_no",
        "original_participant",
        "substitute_participant",
    )
    list_filter = ("match_schedule", "round_no")
    autocomplete_fields = (
        "match_schedule",
        "original_participant",
        "substitute_participant",
    )
    readonly_fields = ("updated_at",)


# ============================================================
# AuditLog（参照専用推奨）
# ============================================================

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "club",
        "event",
        "actor_token_kind",
        "action",
        "created_at",
    )
    list_filter = ("actor_token_kind", "action", "club")
    readonly_fields = (
        "club",
        "event",
        "actor_token_kind",
        "action",
        "payload_json",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClubOrganizer)
class ClubOrganizerAdmin(admin.ModelAdmin):
    list_display = ("id", "club", "member", "email", "confirmed_at", "created_at")
    list_filter = ("club",)
    search_fields = ("email", "club__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailThrottle)
class EmailThrottleAdmin(admin.ModelAdmin):
    list_display = ("id", "scope", "key", "created_at")
    list_filter = ("scope",)
    search_fields = ("key",)
