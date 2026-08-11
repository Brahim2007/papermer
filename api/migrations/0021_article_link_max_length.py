from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0020_retrievalevent_search_filters")]

    operations = [
        migrations.AlterField(
            model_name="article",
            name="link",
            field=models.URLField(blank=True, default="", max_length=500),
        )
    ]
