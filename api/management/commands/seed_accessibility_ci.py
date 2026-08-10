from __future__ import annotations

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.models import Article, Authors, Library
from authorization.models import User


class Command(BaseCommand):
    help = "Create deterministic data for accessibility checks in an isolated CI database."

    def handle(self, *args, **options):
        if os.getenv("ALLOW_CI_SEED") != "1" or not settings.DEBUG:
            raise CommandError(
                "CI accessibility seeding requires ALLOW_CI_SEED=1 and DEBUG=true."
            )
        email = os.getenv("AXE_TEST_EMAIL", "axe-ci@papermetrix.invalid")
        password = os.getenv("AXE_TEST_PASSWORD")
        if not password:
            raise CommandError("AXE_TEST_PASSWORD is required.")

        author, _ = Authors.objects.get_or_create(name="Accessibility Test Author")
        article, _ = Article.objects.update_or_create(
            id="axe-ci-paper",
            defaults={
                "title": "Transparent hybrid retrieval for scientific papers",
                "type": "article",
                "abstract": (
                    "A deterministic record used only to verify accessible research "
                    "discovery interfaces in an isolated continuous integration database."
                ),
                "year": 2026,
                "source": "PaperMetrix CI",
                "venue": "PaperMetrix CI",
                "citation_count": 12,
                "reference_count": 24,
                "is_open_access": True,
                "keywords": ["hybrid retrieval", "accessibility"],
            },
        )
        article.authors.set([author])

        user, _ = User.objects.update_or_create(
            email=email,
            defaults={
                "full_name": "Accessibility CI Researcher",
                "user_roles": "student_phd",
                "tags": ["Information Retrieval"],
                "keywords": ["hybrid retrieval"],
                "authors": [],
                "is_active": True,
                "is_staff": True,
            },
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        library, _ = Library.objects.get_or_create(user=user, name="CI research library")
        library.articles.set([article])
        self.stdout.write(
            self.style.SUCCESS(
                f"Accessibility fixture ready: article={article.pk}, library={library.pk}"
            )
        )
