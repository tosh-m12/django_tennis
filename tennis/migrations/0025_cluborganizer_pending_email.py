from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tennis", "0024_emailthrottle"),
    ]

    operations = [
        migrations.AddField(
            model_name="cluborganizer",
            name="pending_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
