from django.db import migrations, models


def copy_public_token_to_admin_path(apps, schema_editor):
    Club = apps.get_model("tennis", "Club")
    for club in Club.objects.only("id", "public_token").iterator(chunk_size=500):
        Club.objects.filter(pk=club.pk).update(admin_path_token=club.public_token)


class Migration(migrations.Migration):

    dependencies = [
        ("tennis", "0025_cluborganizer_pending_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="club",
            name="admin_path_token",
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(copy_public_token_to_admin_path, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="club",
            name="admin_path_token",
            field=models.CharField(editable=False, max_length=64, unique=True),
        ),
    ]
