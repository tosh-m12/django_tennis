# tennis/migrations/0013_backfill_event_member_class.py
from django.db import migrations


def forwards(apps, schema_editor):
    EventParticipant = apps.get_model("tennis", "EventParticipant")
    ClubMemberClass = apps.get_model("tennis", "ClubMemberClass")
    Event = apps.get_model("tennis", "Event")

    # 対象：まだFKが空で、class_name が入っている EP
    qs = (
        EventParticipant.objects
        .filter(event_member_class__isnull=True)
        .exclude(class_name__isnull=True)
        .exclude(class_name__exact="")
        .select_related("event")
    )

    # club_id -> { class_name: class_id } のキャッシュ（activeのみ）
    cache = {}

    # NOTE: 件数が多くても、クラブごとに辞書作るのでN+1を避けられる
    for ep in qs.iterator():
        # event が取れないケースは通常ないがガード
        if not ep.event_id:
            continue

        # Event から club_id を取る（select_related済み）
        club_id = getattr(ep.event, "club_id", None)
        if not club_id:
            continue

        # クラブごとの辞書を初回だけ構築
        if club_id not in cache:
            mapping = {}
            classes = (
                ClubMemberClass.objects
                .filter(club_id=club_id, is_active=True)
                .order_by("display_order", "id")
                .values("id", "name")
            )
            for c in classes:
                name = (c["name"] or "").strip()
                if name and name not in mapping:
                    mapping[name] = c["id"]
            cache[club_id] = mapping

        key = (ep.class_name or "").strip()
        if not key:
            continue

        class_id = cache[club_id].get(key)
        if not class_id:
            # 一致する active class がない場合は何もしない（空欄のまま）
            continue

        ep.event_member_class_id = class_id
        ep.save(update_fields=["event_member_class"])


def backwards(apps, schema_editor):
    # 巻き戻し時はFKだけ空に戻す（文字列は残る）
    EventParticipant = apps.get_model("tennis", "EventParticipant")
    EventParticipant.objects.update(event_member_class=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tennis", "0012_eventparticipant_event_member_class"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
