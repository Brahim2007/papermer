import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0013_cleanup_crossref_identifiers"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetadataEnrichmentAttempt",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("field_name", models.CharField(db_index=True, max_length=64)),
                ("provider", models.CharField(db_index=True, max_length=32)),
                ("status", models.CharField(db_index=True, max_length=32)),
                ("reason", models.CharField(blank=True, default="", max_length=255)),
                (
                    "source_identifier",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("attempted_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metadata_enrichment_attempts",
                        to="api.article",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["field_name", "status"],
                        name="metadata_enrichment_status_idx",
                    )
                ],
            },
        ),
    ]
