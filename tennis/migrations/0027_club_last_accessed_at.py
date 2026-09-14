from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tennis", "0026_club_admin_path_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="club",
            name="last_accessed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
