from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings

from PaperMetrics.health import liveness, readiness

from .models import Article


class ArticleModelTests(SimpleTestCase):
    def test_retrieval_text_has_canonical_field_order(self):
        article = Article(
            id="paper-1",
            title="Scientific retrieval",
            abstract="A reproducible baseline.",
            keywords=["information retrieval", "evaluation"],
            source="Test Journal",
            type="journal",
        )
        self.assertEqual(
            article.retrieval_text,
            (
                "Scientific retrieval A reproducible baseline. "
                "information retrieval evaluation Test Journal journal"
            ),
        )


class HealthEndpointTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/healthz/")

    def test_liveness_does_not_require_database(self):
        response = liveness(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("PaperMetrics.health.connection")
    def test_readiness_reports_database_success(self, connection):
        connection.cursor.return_value.__enter__.return_value = MagicMock()
        response = readiness(self.request)
        self.assertEqual(response.status_code, 200)

    @patch("PaperMetrics.health.connection")
    def test_readiness_reports_database_failure(self, connection):
        connection.cursor.side_effect = DatabaseError
        response = readiness(self.request)
        self.assertEqual(response.status_code, 503)

    @override_settings(
        SEMANTIC_SEARCH_WARMUP_QUERY="test query",
        SEMANTIC_SEARCH_REQUIRE_WARM_READY=True,
    )
    @patch(
        "frontend.warmup.semantic_warmup_status",
        return_value={"status": "warming", "latency_ms": 0.0},
    )
    @patch("PaperMetrics.health.connection")
    def test_readiness_waits_for_required_semantic_warmup(
        self, connection, warmup_status
    ):
        connection.cursor.return_value.__enter__.return_value = MagicMock()
        response = readiness(self.request)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"semantic_search"', response.content)

    @override_settings(
        SEMANTIC_SEARCH_WARMUP_QUERY="test query",
        SEMANTIC_SEARCH_REQUIRE_WARM_READY=True,
    )
    @patch(
        "frontend.warmup.semantic_warmup_status",
        return_value={"status": "ready", "latency_ms": 12.0},
    )
    @patch("PaperMetrics.health.connection")
    def test_readiness_accepts_completed_semantic_warmup(
        self, connection, warmup_status
    ):
        connection.cursor.return_value.__enter__.return_value = MagicMock()
        response = readiness(self.request)
        self.assertEqual(response.status_code, 200)
