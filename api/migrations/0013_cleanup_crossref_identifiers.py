from django.db import migrations


def cleanup_crossref_identifiers(apps, schema_editor):
    Article = apps.get_model("api", "Article")
    WorkIdentifier = apps.get_model("api", "WorkIdentifier")
    WorkIdentifier.objects.filter(scheme="crossref").delete()
    updates = []
    for article in Article.objects.iterator():
        identifiers = dict(article.identifiers or {})
        if "crossref" in identifiers:
            identifiers.pop("crossref", None)
            article.identifiers = identifiers
            updates.append(article)
    if updates:
        Article.objects.bulk_update(updates, ["identifiers"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("api", "0012_citation_sourcerecord_workidentifier_and_more")]

    operations = [migrations.RunPython(cleanup_crossref_identifiers, migrations.RunPython.noop)]
