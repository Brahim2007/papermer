from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.contrib.staticfiles import finders
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import translation
from django.utils.translation import gettext
from retrieval.tfidf import SearchResult
from retrieval.hybrid import HybridSearchResult
from api.models import Article, Library, RetrievalEvent, RetrievalInteraction
from authorization.models import User

from .interactions import record_impressions, record_interaction
from .recom import LiveSearchResponse, live_search
from .query_expansion import _daily_budget_key, expand_query, should_expand
from .retrieval_telemetry import query_digest, record_retrieval_event
from .search_filters import apply_search_filters, canonical_filter_key, parse_search_filters
from .views import _paired_query_comparisons


class UrlConfigurationTests(SimpleTestCase):
    def test_public_routes_resolve(self):
        names = (
            "home",
            "search",
            "api_get_articles",
            "api_new_articles",
            "api_top_articles",
            "api_hot_articles",
            "api_live_search",
        )
        for name in names:
            path = reverse(name)
            self.assertIsNotNone(resolve(path).func)

    def test_article_aliases_are_available(self):
        self.assertEqual(reverse("article", args=["paper-1"]), "/article/paper-1/")
        self.assertEqual(
            reverse("article_detail", args=["paper-1"]), "/articles/paper-1/"
        )


class InterfaceFoundationTests(SimpleTestCase):
    def test_new_public_templates_compile(self):
        for template_name in (
            "base.html",
            "frontend/index.html",
            "frontend/search.html",
            "frontend/about.html",
            "frontend/detail.html",
            "frontend/author.html",
            "frontend/library_list.html",
            "frontend/library_detail.html",
            "frontend/topics.html",
            "frontend/your_rec.html",
            "frontend/evaluation_dashboard.html",
            "auth/login.html",
            "auth/signup.html",
            "auth/questions.html",
            "auth/password_reset_form.html",
        ):
            self.assertIsNotNone(get_template(template_name))

    def test_design_system_assets_are_discoverable(self):
        self.assertIsNotNone(finders.find("css/app.css"))
        self.assertIsNotNone(finders.find("js/app.js"))
        self.assertIsNotNone(finders.find("js/onboarding.js"))
        for asset in (
            "js/paper-detail.js",
            "js/libraries.js",
            "js/library-detail.js",
            "js/topics.js",
            "js/recommendations.js",
            "js/semantic-search.js",
        ):
            self.assertIsNotNone(finders.find(asset))

    def test_arabic_catalog_is_compiled(self):
        with translation.override("ar"):
            self.assertEqual(gettext("Welcome back"), "مرحبًا بعودتك")
            self.assertEqual(gettext("Evidence-aware discovery"), "اكتشاف قائم على الأدلة")
            rendered = get_template("base.html").render({})
        self.assertIn('<html lang="ar" dir="rtl">', rendered)
        self.assertIn("انتقل إلى المحتوى", rendered)

    def test_shared_chrome_has_accessible_navigation_contract(self):
        root = Path(__file__).resolve().parents[1] / "templates"
        navigation = (root / "nav.html").read_text(encoding="utf-8")
        footer = (root / "footer.html").read_text(encoding="utf-8")
        self.assertIn('aria-controls="primary-navigation"', navigation)
        self.assertIn("data-site-navigation", navigation)
        self.assertIn('method="post" action="{% url \'logout\' %}"', navigation)
        self.assertNotIn("onclick=", navigation.lower())
        self.assertGreaterEqual(footer.count("<nav"), 3)
        self.assertIn('aria-label="{% trans \'Retrieval methods\' %}"', footer)


class AccessibilityGuardTests(SimpleTestCase):
    """Fast structural guards for common accessibility regressions."""

    template_dir = Path(__file__).resolve().parents[1] / "templates" / "frontend"
    redesigned_templates = (
        "about.html",
        "search.html",
        "detail.html",
        "author.html",
        "library_list.html",
        "library_detail.html",
        "topics.html",
        "your_rec.html",
    )

    def _source(self, name):
        return (self.template_dir / name).read_text(encoding="utf-8")

    def test_child_templates_do_not_duplicate_document_landmarks(self):
        for name in self.redesigned_templates:
            source = self._source(name).lower()
            with self.subTest(template=name):
                self.assertNotIn("<html", source)
                self.assertNotIn("<body", source)
                self.assertNotIn("<main", source)
                self.assertNotIn("include 'nav.html'", source)
                self.assertNotIn('include "nav.html"', source)

    def test_pages_have_one_source_level_h1_and_labelled_sections(self):
        for name in self.redesigned_templates:
            source = self._source(name)
            with self.subTest(template=name):
                self.assertEqual(source.count("<h1"), 1)
                self.assertTrue(
                    'aria-label="' in source or 'aria-labelledby="' in source
                )

    def test_interactions_avoid_inline_handlers_and_unsafe_html_sinks(self):
        for name in self.redesigned_templates:
            source = self._source(name).lower()
            with self.subTest(template=name):
                self.assertNotIn("onclick=", source)
                self.assertNotIn("onchange=", source)
                self.assertNotIn(".innerhtml", source)
        for asset in (
            "paper-detail.js",
            "libraries.js",
            "library-detail.js",
            "topics.js",
            "recommendations.js",
            "semantic-search.js",
        ):
            source = (
                Path(__file__).resolve().parents[1] / "static" / "js" / asset
            ).read_text(encoding="utf-8")
            with self.subTest(asset=asset):
                self.assertNotIn(".innerHTML", source)

    def test_form_controls_have_programmatic_names(self):
        detail = self._source("detail.html")
        libraries = self._source("library_list.html")
        self.assertIn('label for="comment-body"', detail)
        self.assertIn('label for="library-select"', detail)
        self.assertIn('label for="library-name"', libraries)
        self.assertIn('aria-label=', libraries)

    def test_paper_detail_progressive_disclosure_is_accessible(self):
        detail = self._source("detail.html")
        self.assertIn('data-authors-toggle', detail)
        self.assertIn('aria-controls="paper-authors"', detail)
        self.assertIn('role="status" aria-live="polite" data-copy-status', detail)
        self.assertIn('aria-label="{% trans \'On this page\' %}"', detail)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AboutPageTests(TestCase):
    def test_about_renders_dedicated_research_story(self):
        response = self.client.get(reverse("about"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A research system, not a black box")
        self.assertContains(response, "What PaperMetrix does—and does not do")
        self.assertContains(response, 'class="about-stats"')


class LiveRetrievalTests(SimpleTestCase):
    class FakeRetriever:
        def __init__(self, ids):
            self.ids = ids

        def search(self, query, *, top_k, exclude_ids=()):
            return [
                SearchResult(document_id, 1.0 / rank, rank)
                for rank, document_id in enumerate(self.ids[:top_k], start=1)
            ]

    @patch("frontend.recom._get_live_retrievers")
    def test_dense_hybrid_reports_components_and_component_ranks(self, get_retrievers):
        get_retrievers.return_value = (
            self.FakeRetriever(["paper-a", "paper-b"]),
            self.FakeRetriever(["paper-b", "paper-a"]),
            self.FakeRetriever(["paper-a", "paper-b"]),
        )
        response = live_search("hybrid retrieval", top_k=2)
        self.assertTrue(response.semantic_enabled)
        self.assertEqual(response.method, "hybrid_specter2_bm25_rrf")
        self.assertEqual(response.components, ("bm25", "tfidf", "specter2"))
        self.assertGreaterEqual(response.total_latency_ms, 0)
        self.assertEqual(
            set(response.component_latencies_ms),
            {"setup", "bm25", "tfidf", "specter2", "rrf"},
        )
        self.assertEqual(
            set(response.results[0].component_ranks),
            {"bm25", "tfidf", "specter2"},
        )

    @patch("frontend.recom._dense_failure", "cache_unavailable")
    @patch("frontend.recom._get_live_retrievers")
    def test_sparse_fallback_is_explicit(self, get_retrievers):
        get_retrievers.return_value = (
            self.FakeRetriever(["paper-a"]),
            self.FakeRetriever(["paper-a"]),
            None,
        )
        response = live_search("hybrid retrieval", top_k=1)
        self.assertFalse(response.semantic_enabled)
        self.assertEqual(response.method, "hybrid_bm25_tfidf_rrf")
        self.assertEqual(response.degraded_reason, "cache_unavailable")


class SearchFilterUnitTests(SimpleTestCase):
    def test_filters_are_validated_and_canonicalized(self):
        filters = parse_search_filters(
            {
                "year_from": "2020",
                "year_to": "2025",
                "paper_type": "article",
                "source": "Nature",
                "open_access": "1",
                "min_citations": "10",
            }
        )
        self.assertEqual(filters["year_from"], 2020)
        self.assertTrue(filters["open_access"])
        self.assertEqual(
            canonical_filter_key(filters),
            '{"min_citations":10,"open_access":true,"paper_type":"article","source":"Nature","year_from":2020,"year_to":2025}',
        )

    def test_invalid_year_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_search_filters({"year_from": "2025", "year_to": "2020"})


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    LLM_QUERY_EXPANSION_ENABLED=False,
    RETRIEVAL_TELEMETRY_ENABLED=True,
    RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT=False,
    RETRIEVAL_TELEMETRY_HMAC_KEY="filter-test-key",
)
class SearchFilterEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.eligible = Article.objects.create(
            id="filter-eligible",
            title="Explainable retrieval in medicine",
            type="article",
            year=2023,
            source="Nature",
            citation_count=25,
            is_open_access=True,
        )
        self.excluded = Article.objects.create(
            id="filter-excluded",
            title="Explainable retrieval survey",
            type="review",
            year=2018,
            source="Elsevier",
            citation_count=2,
            is_open_access=False,
        )

    @patch("frontend.views.live_search")
    def test_live_filters_are_applied_and_recorded_with_request(self, search):
        search.return_value = LiveSearchResponse(
            results=(
                HybridSearchResult(self.excluded.pk, 0.9, 1, {"bm25": 1}),
                HybridSearchResult(self.eligible.pk, 0.8, 2, {"bm25": 2}),
            ),
            method="hybrid_bm25_tfidf_rrf",
            components=("bm25", "tfidf"),
            semantic_enabled=False,
            degraded_reason="test",
            component_latencies_ms={"bm25": 1.0, "tfidf": 1.0, "rrf": 0.2},
            total_latency_ms=2.2,
        )
        response = self.client.get(
            reverse("api_live_search"),
            {
                "q": "explainable retrieval",
                "year_from": 2020,
                "paper_type": "article",
                "open_access": 1,
                "min_citations": 10,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([row["id"] for row in payload["results"]], [self.eligible.pk])
        self.assertEqual(payload["results"][0]["rank"], 1)
        self.assertEqual(payload["results"][0]["retrieval_rank"], 2)
        event = RetrievalEvent.objects.get(request_id=payload["request_id"])
        self.assertEqual(event.search_filters, payload["filters"])
        self.assertEqual(event.search_filters["year_from"], 2020)


@override_settings(ALLOWED_HOSTS=["testserver"])
class SearchQuickSaveTests(TestCase):
    def test_search_save_uses_selected_library_and_request_attribution(self):
        user = User.objects.create_user(
            email="search-save@example.test",
            password="test-password",
            full_name="Search Saver",
            user_roles="researcher",
        )
        article = Article.objects.create(
            id="search-save-paper", title="Saved from search", type="article"
        )
        library = Library.objects.create(user=user, name="Evidence")
        event = RetrievalEvent.objects.create(
            user=user,
            query_digest="a" * 64,
            actor_digest="b" * 64,
            query_length=10,
            method="bm25",
            components=["bm25"],
            component_latencies_ms={"bm25": 1.0},
            total_latency_ms=1.0,
            result_ids=[article.pk],
            result_component_ranks={article.pk: {"bm25": 1}},
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("add_to_library"),
            {
                "library_id": library.pk,
                "article_id": article.pk,
                "request_id": event.pk,
                "source": "search_results",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(library.articles.filter(pk=article.pk).exists())
        interaction = RetrievalInteraction.objects.get(
            retrieval_event=event, document_id=article.pk, event_type="save"
        )
        self.assertEqual(interaction.metadata["source"], "search_results")


@override_settings(ALLOWED_HOSTS=["testserver"])
class PairedEvaluationDashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email="paired-staff@example.org",
            password="test-password",
            full_name="Paired Evaluation Staff",
            user_roles="researcher",
            is_staff=True,
        )
        self.reader = User.objects.create_user(
            email="paired-reader@example.org",
            password="test-password",
            full_name="Paired Evaluation Reader",
            user_roles="researcher",
        )
        self.first = Article.objects.create(
            id="paired-paper-one", title="Baseline and expansion comparison", type="article"
        )
        self.second = Article.objects.create(
            id="paired-paper-two", title="Auditable query expansion", type="article"
        )
        common = {
            "user": self.staff,
            "query_digest": "c" * 64,
            "actor_digest": "d" * 64,
            "query_text": "transparent scholarly retrieval",
            "query_length": 32,
            "protocol_sha256": "e" * 64,
            "search_filters": {"year_from": 2020, "open_access": True},
            "components": ["bm25", "specter2", "rrf"],
            "component_latencies_ms": {"bm25": 2.0, "specter2": 4.0},
            "semantic_enabled": True,
        }
        self.baseline = RetrievalEvent.objects.create(
            **common,
            experiment_arm="baseline",
            expansion_status="not_selected",
            method="hybrid_rrf",
            total_latency_ms=20.0,
            result_ids=[self.first.pk, self.second.pk],
            result_component_ranks={},
        )
        self.llm = RetrievalEvent.objects.create(
            **common,
            experiment_arm="llm_expansion",
            expansion_status="expanded",
            expansion_model="test-model",
            expansion_prompt_version="prompt-v2",
            expansion_latency_ms=11.0,
            expansion_input_tokens=20,
            expansion_output_tokens=8,
            expansion_estimated_cost_usd="0.000120000",
            method="llm_expanded_hybrid_rrf",
            total_latency_ms=35.0,
            result_ids=[self.second.pk],
            result_component_ranks={},
        )
        RetrievalInteraction.objects.create(
            retrieval_event=self.baseline,
            article=self.first,
            document_id=self.first.pk,
            user=self.staff,
            event_type="relevance",
            rank=1,
            relevance=-1,
        )
        RetrievalInteraction.objects.create(
            retrieval_event=self.llm,
            article=self.second,
            document_id=self.second.pk,
            user=self.staff,
            event_type="relevance",
            rank=1,
            relevance=1,
        )

    def test_pair_metrics_preserve_conditions_and_judgments(self):
        paired = _paired_query_comparisons()
        pair = next(
            item for item in paired["pairs"] if item["query_digest"] == "c" * 64
        )
        self.assertTrue(pair["effectiveness_ready"])
        self.assertEqual(pair["delta"]["latency_ms"], 15.0)
        self.assertEqual(pair["delta"]["positive"], 1)
        self.assertEqual(pair["overlap"]["common_at_10"], 1)
        self.assertEqual(pair["search_filters"]["year_from"], 2020)
        self.assertEqual(pair["llm"]["results"][0]["title"], self.second.title)

    def test_dashboard_and_export_are_staff_only(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("evaluation_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("evaluation_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Baseline vs LLM-expanded by query")
        exported = self.client.get(reverse("evaluation_export"))
        self.assertEqual(exported.status_code, 200)
        payload = exported.json()
        pair = next(
            item
            for item in payload["paired"]["pairs"]
            if item["query_digest"] == "c" * 64
        )
        self.assertEqual(pair["query"], "")

    def test_different_filters_are_not_paired(self):
        self.llm.search_filters = {"year_from": 2021, "open_access": True}
        self.llm.save(update_fields=["search_filters"])
        matching = [
            item
            for item in _paired_query_comparisons()["pairs"]
            if item["query_digest"] == "c" * 64
        ]
        self.assertEqual(matching, [])


class QueryExpansionTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=False,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=100,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    def test_disabled_expansion_never_selects_query(self):
        self.assertFalse(
            should_expand(query="graph retrieval", client_key="reader", mode="auto", is_staff=False)
        )

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=100,
        LLM_QUERY_EXPANSION_ENDPOINT="https://llm.invalid/v1/chat/completions",
        LLM_QUERY_EXPANSION_API_KEY="test-token",
        LLM_QUERY_EXPANSION_MODEL="test-model",
        LLM_QUERY_EXPANSION_STAFF_ONLY=False,
        LLM_QUERY_EXPANSION_TIMEOUT_SECONDS=2,
        LLM_QUERY_EXPANSION_MAX_CHARS=1000,
        LLM_QUERY_EXPANSION_MAX_OUTPUT_TOKENS=120,
        LLM_QUERY_EXPANSION_CACHE_SECONDS=3600,
        LLM_QUERY_EXPANSION_INPUT_USD_PER_MILLION=1.0,
        LLM_QUERY_EXPANSION_CACHED_INPUT_USD_PER_MILLION=0.25,
        LLM_QUERY_EXPANSION_OUTPUT_USD_PER_MILLION=4.0,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    @patch("frontend.query_expansion.requests.post")
    def test_provider_expansion_is_an_independent_selected_arm(self, post):
        response = Mock()
        response.json.return_value = {
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": "graph neural retrieval citation networks"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        }
        post.return_value = response
        result = expand_query(
            query="graph retrieval", client_key="reader", mode="auto", is_staff=False
        )
        self.assertTrue(result.selected)
        self.assertEqual(result.status, "expanded")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.prompt_version, "scholarly-query-expansion-v1")
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 20)
        self.assertEqual(result.cached_input_tokens, 40)
        self.assertEqual(result.estimated_cost_usd, 0.00015)
        self.assertEqual(result.provider_response_id, "chatcmpl-test")
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["reasoning_effort"], "none")
        self.assertEqual(request_body["max_completion_tokens"], 120)

        cached = expand_query(
            query="graph retrieval", client_key="reader", mode="auto", is_staff=False
        )
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.query, result.query)
        self.assertEqual(cached.input_tokens, 0)
        self.assertIsNone(cached.estimated_cost_usd)
        post.assert_called_once()

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=100,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    def test_non_staff_cannot_force_experimental_arm(self):
        self.assertFalse(
            should_expand(query="graph retrieval", client_key="reader", mode="on", is_staff=False)
        )

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        LLM_QUERY_EXPANSION_STAFF_ONLY=True,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=100,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    def test_staff_only_mode_blocks_public_auto_traffic(self):
        self.assertFalse(
            should_expand(
                query="graph retrieval",
                client_key="reader",
                mode="auto",
                is_staff=False,
            )
        )
        self.assertTrue(
            should_expand(
                query="graph retrieval",
                client_key="staff",
                mode="on",
                is_staff=True,
            )
        )

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        LLM_QUERY_EXPANSION_STAFF_ONLY=True,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=0,
        LLM_QUERY_EXPANSION_ENDPOINT="https://llm.invalid/v1/chat/completions",
        LLM_QUERY_EXPANSION_API_KEY="test-token",
        LLM_QUERY_EXPANSION_MODEL="test-model",
        LLM_QUERY_EXPANSION_TIMEOUT_SECONDS=2,
        LLM_QUERY_EXPANSION_MAX_CHARS=1000,
        LLM_QUERY_EXPANSION_MAX_OUTPUT_TOKENS=120,
        LLM_QUERY_EXPANSION_CACHE_SECONDS=3600,
        LLM_QUERY_EXPANSION_DAILY_BUDGET_USD=1.0,
        LLM_QUERY_EXPANSION_FAILURE_THRESHOLD=2,
        LLM_QUERY_EXPANSION_FAILURE_WINDOW_SECONDS=300,
        LLM_QUERY_EXPANSION_CIRCUIT_COOLDOWN_SECONDS=300,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    def test_circuit_breaker_stops_calls_after_consecutive_failures(self):
        with patch(
            "frontend.query_expansion.requests.post",
            side_effect=requests.Timeout("timeout"),
        ) as failing_post:
            first = expand_query(
                query="failure one", client_key="staff", mode="on", is_staff=True
            )
            second = expand_query(
                query="failure two", client_key="staff", mode="on", is_staff=True
            )
            blocked = expand_query(
                query="failure three", client_key="staff", mode="on", is_staff=True
            )
        self.assertEqual(first.status, "provider_failed")
        self.assertEqual(second.status, "provider_failed")
        self.assertEqual(blocked.status, "circuit_open")
        self.assertEqual(failing_post.call_count, 2)

    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        LLM_QUERY_EXPANSION_STAFF_ONLY=True,
        LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=0,
        LLM_QUERY_EXPANSION_ENDPOINT="https://llm.invalid/v1/chat/completions",
        LLM_QUERY_EXPANSION_API_KEY="test-token",
        LLM_QUERY_EXPANSION_MODEL="test-model",
        LLM_QUERY_EXPANSION_DAILY_BUDGET_USD=0.5,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    @patch("frontend.query_expansion.requests.post")
    def test_daily_budget_blocks_new_provider_calls(self, post):
        cache.set(_daily_budget_key(), 500_000_000, 60)
        result = expand_query(
            query="budget guard", client_key="staff", mode="on", is_staff=True
        )
        self.assertEqual(result.status, "budget_exhausted")
        post.assert_not_called()


class StaffExpansionInterfaceTests(TestCase):
    @override_settings(
        LLM_QUERY_EXPANSION_ENABLED=True,
        ALLOWED_HOSTS=["testserver"],
    )
    def test_staff_search_page_exposes_internal_toggle_only_to_staff(self):
        staff = User.objects.create_user(
            email="staff-expansion@example.org",
            password="test-password",
            full_name="Staff Researcher",
            user_roles="researcher",
            is_staff=True,
        )
        self.client.force_login(staff)
        staff_response = self.client.get(reverse("search"))
        self.assertContains(staff_response, "data-expansion-toggle")
        self.client.logout()
        public_response = self.client.get(reverse("search"))
        self.assertNotContains(public_response, "data-expansion-toggle")


class RetrievalTelemetryTests(SimpleTestCase):
    @override_settings(RETRIEVAL_TELEMETRY_HMAC_KEY="test-key")
    def test_query_digest_is_keyed_and_deterministic(self):
        digest = query_digest("  Private Research Direction  ")
        self.assertEqual(digest, query_digest("private research direction"))
        self.assertNotIn("private", digest)
        self.assertEqual(len(digest), 64)

    @override_settings(
        RETRIEVAL_TELEMETRY_ENABLED=True,
        RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT=False,
        RETRIEVAL_TELEMETRY_HMAC_KEY="test-key",
    )
    @patch("frontend.retrieval_telemetry.current_protocol_sha256", return_value="c" * 64)
    @patch("frontend.retrieval_telemetry.RetrievalEvent.objects.create")
    def test_raw_query_is_not_stored_by_default(self, create, protocol):
        request = RequestFactory().get("/api/search/live/")
        request.user = AnonymousUser()
        record_retrieval_event(
            request=request,
            query="unpublished hypothesis",
            actor_key="anonymous-test-actor",
            method="bm25",
            components=["bm25"],
            component_latencies_ms={"bm25": 1.2},
            total_latency_ms=2.0,
            results=[{"id": "paper-1", "explanation": {"component_ranks": {"bm25": 1}}}],
            semantic_enabled=False,
            degraded_reason=None,
            cache_hit=False,
            experiment_arm="baseline",
        )
        self.assertIsNone(create.call_args.kwargs["query_text"])
        self.assertNotEqual(create.call_args.kwargs["query_digest"], "unpublished hypothesis")
        self.assertEqual(create.call_args.kwargs["search_filters"], {})


class RetrievalInteractionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email="interaction@example.org",
            password="test-password",
            full_name="Interaction Researcher",
            user_roles="researcher",
        )
        self.other_user = User.objects.create_user(
            email="other@example.org",
            password="test-password",
            full_name="Other Researcher",
            user_roles="researcher",
        )
        self.article = Article.objects.create(
            id="interaction-paper",
            title="Interaction-aware retrieval",
            type="article",
        )
        self.event = RetrievalEvent.objects.create(
            user=self.user,
            query_digest="a" * 64,
            actor_digest="b" * 64,
            query_length=12,
            method="bm25",
            components=["bm25"],
            component_latencies_ms={"bm25": 1.0},
            total_latency_ms=2.0,
            result_ids=[self.article.pk],
            result_component_ranks={self.article.pk: {"bm25": 1}},
        )

    def _request(self, user):
        request = self.factory.post("/api/search/interactions/")
        request.user = user
        return request

    def test_impressions_are_idempotent_and_server_ranked(self):
        request = self._request(self.user)
        self.assertEqual(
            record_impressions(
                request=request,
                request_id=str(self.event.pk),
                document_ids=[self.article.pk],
            ),
            (1, 1),
        )
        self.assertEqual(
            record_impressions(
                request=request,
                request_id=str(self.event.pk),
                document_ids=[self.article.pk],
            ),
            (0, 1),
        )
        interaction = RetrievalInteraction.objects.get(
            retrieval_event=self.event, event_type="impression"
        )
        self.assertEqual(interaction.rank, 1)

    def test_document_not_in_exposure_is_rejected(self):
        with self.assertRaises(ValidationError):
            record_interaction(
                request=self._request(self.user),
                request_id=str(self.event.pk),
                document_id="unexposed-paper",
                event_type="click",
            )

    def test_relevance_requires_authentication(self):
        with self.assertRaises(PermissionDenied):
            record_interaction(
                request=self._request(AnonymousUser()),
                request_id=str(self.event.pk),
                document_id=self.article.pk,
                event_type="relevance",
                relevance=1,
            )

    def test_another_user_cannot_attribute_to_owned_request(self):
        with self.assertRaises(PermissionDenied):
            record_interaction(
                request=self._request(self.other_user),
                request_id=str(self.event.pk),
                document_id=self.article.pk,
                event_type="click",
            )
