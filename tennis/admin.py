from django.contrib import admin
from .models import (
    Club,
    Event,
    Member,
    EventParticipant,
    ClubFlagDefinition,
    ParticipantFlag,
    MatchSchedule,
    MatchScheduleDraft,
    MatchScore,
    Substitution,
    AuditLog,
)

# ============================================================
# Club
# ============================================================

@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "public_token",
        "admin_token",
        "is_active",
        "created_at",
    )
    search_fields = ("name", "public_token", "admin_token")
    list_filter = ("is_active",)
    readonly_fields = ("public_token", "admin_token", "created_at", "updated_at")


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
# ParticipantFlag
# ============================================================

@admin.register(ParticipantFlag)
class ParticipantFlagAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_participant",
        "flag_definition",
        "is_on",
        "updated_at",
    )
    list_filter = ("flag_definition", "is_on")
    autocomplete_fields = ("event_participant", "flag_definition")
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
