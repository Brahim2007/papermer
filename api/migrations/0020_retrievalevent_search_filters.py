from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0019_retrievalevent_expansion_cache_hit_and_more")]

    operations = [
        migrations.AddField(
            model_name="retrievalevent",
            name="search_filters",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
