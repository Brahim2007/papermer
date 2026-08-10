from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q


class Authors(models.Model):
    """Author model; plural name is retained for migration compatibility."""

    name = models.TextField(unique=True)
    done = models.BooleanField(default=False)

    class Meta:
        verbose_name = "author"
        verbose_name_plural = "authors"

    def __str__(self) -> str:
        return self.name


# Readable import alias without changing the historical database model name.
Author = Authors


class Article(models.Model):
    add_on = models.DateTimeField(auto_now_add=True, db_index=True)
    title = models.TextField()
    type = models.TextField()
    authors = models.ManyToManyField(Authors, blank=True)
    identifiers = models.JSONField(default=dict)
    keywords = ArrayField(
        base_field=models.CharField(max_length=100), null=True, blank=True
    )
    year = models.IntegerField(null=True, blank=True, db_index=True)
    source = models.TextField(blank=True, default="")
    publisher = models.TextField(blank=True, default="")
    id = models.CharField(max_length=100, unique=True, primary_key=True)
    pdf = models.URLField(default=None, null=True, blank=True, max_length=500)
    link = models.URLField(blank=True, default="")
    abstract = models.TextField(blank=True, default="")
    count = models.IntegerField(default=0)
    comm_count = models.IntegerField(default=0)
    score = models.FloatField(blank=True, null=True)
    twitter_data = models.JSONField(default=dict, blank=True)
    normalized_title = models.TextField(blank=True, default="", db_index=True)
    doi = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    arxiv_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    openalex_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    semantic_scholar_id = models.CharField(
        max_length=100, null=True, blank=True, db_index=True
    )
    publication_date = models.DateField(null=True, blank=True, db_index=True)
    venue = models.TextField(blank=True, default="")
    language = models.CharField(max_length=20, blank=True, default="")
    citation_count = models.PositiveIntegerField(default=0)
    reference_count = models.PositiveIntegerField(default=0)
    is_retracted = models.BooleanField(default=False, db_index=True)
    is_open_access = models.BooleanField(default=False)
    topics = models.JSONField(default=list, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["-year"], name="article_year_desc_idx"),
            models.Index(fields=["-add_on"], name="article_added_desc_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["doi"],
                condition=Q(doi__isnull=False),
                name="unique_article_doi",
            ),
            models.UniqueConstraint(
                fields=["arxiv_id"],
                condition=Q(arxiv_id__isnull=False),
                name="unique_article_arxiv_id",
            ),
            models.UniqueConstraint(
                fields=["openalex_id"],
                condition=Q(openalex_id__isnull=False),
                name="unique_article_openalex_id",
            ),
            models.UniqueConstraint(
                fields=["semantic_scholar_id"],
                condition=Q(semantic_scholar_id__isnull=False),
                name="unique_article_s2_id",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def retrieval_text(self) -> str:
        """Canonical input text shared by all retrieval baselines."""
        keywords = " ".join(self.keywords or [])
        return " ".join(
            value.strip()
            for value in (self.title, self.abstract, keywords, self.source, self.type)
            if value and value.strip()
        )

    @property
    def canonical_key(self) -> str:
        for scheme, value in (
            ("doi", self.doi),
            ("arxiv", self.arxiv_id),
            ("openalex", self.openalex_id),
            ("s2", self.semantic_scholar_id),
        ):
            if value:
                return f"{scheme}:{value}"
        return f"legacy:{self.pk}"

    def get_json(self) -> dict:
        return {
            "id": self.pk,
            "title": self.title,
            "type": self.type,
            "authors": list(self.authors.values_list("name", flat=True)),
            "year": self.year,
            "source": self.source,
            "publisher": self.publisher,
            "pdf": self.pdf,
            "link": self.link,
            "abstract": self.abstract,
        }

    def get_pdf_url(self) -> str:
        validator = URLValidator()
        if self.pdf:
            try:
                validator(self.pdf)
                return self.pdf
            except ValidationError:
                pass
        doi = self.identifiers.get("doi")
        return f"https://doi.org/{doi}" if doi else "#"

    def get_issn(self) -> str | None:
        issn = self.identifiers.get("issn")
        if not issn:
            return None
        normalized = str(issn).replace("-", "")
        return (
            "https://portal.issn.org/api/search?"
            f"search[]=MUST=allissnbis={normalized[:4]}-{normalized[4:]}"
        )

    def get_doi(self) -> str | None:
        doi = self.identifiers.get("doi")
        return f"https://doi.org/{doi}" if doi else None

    def get_total(self) -> int:
        return self.review_set.count()

    def get_total_comments(self) -> int:
        return self.comment_set.count()

    def check_up_down(self, user) -> int:
        if not user.is_authenticated:
            return 0
        review = self.review_set.filter(user=user).first()
        return review.rating if review else 0


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(1, "Positive"), (-1, "Negative")])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "article"], name="unique_user_article_review"
            )
        ]


class Tag(models.Model):
    tag = models.CharField(max_length=100)
    article = models.ManyToManyField(Article, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("user", "tag")


class Library(models.Model):
    name = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    articles = models.ManyToManyField(Article, blank=True)

    def __str__(self) -> str:
        return self.name


class Comment(models.Model):
    body = models.TextField()
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_on"]


class WorkIdentifier(models.Model):
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="work_identifiers"
    )
    scheme = models.CharField(max_length=32)
    value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=255)
    source = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "normalized_value"],
                name="unique_normalized_work_identifier",
            )
        ]
        indexes = [
            models.Index(
                fields=["scheme", "normalized_value"], name="work_identifier_lookup_idx"
            )
        ]


class SourceRecord(models.Model):
    article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_records",
    )
    source = models.CharField(max_length=32)
    external_id = models.CharField(max_length=255)
    payload = models.JSONField(default=dict)
    payload_checksum = models.CharField(max_length=64)
    retrieved_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="unique_source_record"
            )
        ]
        indexes = [
            models.Index(
                fields=["source", "external_id"], name="source_record_lookup_idx"
            )
        ]


class WorkVersion(models.Model):
    """A concrete preprint, accepted manuscript, or published work version."""

    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="versions"
    )
    source = models.CharField(max_length=32, db_index=True)
    external_id = models.CharField(max_length=255)
    version_type = models.CharField(max_length=32, default="unknown", db_index=True)
    version_label = models.CharField(max_length=64, blank=True, default="")
    version_number = models.PositiveIntegerField(null=True, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    landing_url = models.URLField(max_length=500, blank=True, default="")
    pdf_url = models.URLField(max_length=500, null=True, blank=True)
    doi = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    arxiv_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    is_open_access = models.BooleanField(default=False)
    license = models.CharField(max_length=100, blank=True, default="")
    host_type = models.CharField(max_length=32, blank=True, default="")
    oa_status = models.CharField(max_length=32, blank=True, default="")
    provenance = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                name="unique_source_work_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["article", "version_type"],
                name="work_version_article_type_idx",
            )
        ]


class Citation(models.Model):
    citing_article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="outgoing_citations"
    )
    cited_article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incoming_citations",
    )
    cited_identifier = models.CharField(max_length=255)
    identifier_scheme = models.CharField(max_length=32)
    source = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["citing_article", "identifier_scheme", "cited_identifier"],
                name="unique_article_citation",
            )
        ]


class MetadataEnrichmentAttempt(models.Model):
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="metadata_enrichment_attempts",
    )
    field_name = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=32, db_index=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    source_identifier = models.CharField(max_length=255, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["field_name", "status"],
                name="metadata_enrichment_status_idx",
            )
        ]


class RetrievalEvent(models.Model):
    """Privacy-preserving online retrieval trace for reproducible evaluation."""

    request_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retrieval_events",
    )
    query_digest = models.CharField(max_length=64, db_index=True)
    actor_digest = models.CharField(max_length=64, blank=True, default="", db_index=True)
    query_text = models.TextField(null=True, blank=True)
    query_length = models.PositiveIntegerField()
    channel = models.CharField(max_length=32, default="live_search", db_index=True)
    experiment_arm = models.CharField(max_length=32, default="baseline", db_index=True)
    protocol_sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    deployment_version = models.CharField(max_length=100, blank=True, default="")
    method = models.CharField(max_length=100, db_index=True)
    components = models.JSONField(default=list)
    component_latencies_ms = models.JSONField(default=dict)
    total_latency_ms = models.FloatField()
    result_ids = models.JSONField(default=list)
    result_component_ranks = models.JSONField(default=dict)
    search_filters = models.JSONField(default=dict, blank=True)
    semantic_enabled = models.BooleanField(default=False)
    degraded_reason = models.CharField(max_length=100, blank=True, default="")
    cache_hit = models.BooleanField(default=False, db_index=True)
    expansion_status = models.CharField(max_length=32, default="not_selected")
    expansion_model = models.CharField(max_length=255, blank=True, default="")
    expansion_query_digest = models.CharField(max_length=64, blank=True, default="")
    expansion_prompt_version = models.CharField(max_length=100, blank=True, default="")
    expansion_cache_hit = models.BooleanField(default=False)
    expansion_latency_ms = models.FloatField(default=0.0)
    expansion_input_tokens = models.PositiveIntegerField(default=0)
    expansion_output_tokens = models.PositiveIntegerField(default=0)
    expansion_cached_input_tokens = models.PositiveIntegerField(default=0)
    expansion_estimated_cost_usd = models.DecimalField(
        max_digits=12, decimal_places=9, null=True, blank=True
    )
    expansion_provider_response_id = models.CharField(
        max_length=255, blank=True, default=""
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["-created_at", "experiment_arm"],
                name="retrieval_event_arm_idx",
            ),
            models.Index(
                fields=["method", "-created_at"],
                name="retrieval_event_method_idx",
            ),
        ]


class OfflineEvaluationRun(models.Model):
    """Immutable-by-checksum summary of an offline retrieval evaluation artifact."""

    run_key = models.CharField(max_length=255, unique=True)
    label = models.CharField(max_length=255)
    method = models.CharField(max_length=100, db_index=True)
    dataset = models.CharField(max_length=255, blank=True, default="")
    split = models.CharField(max_length=32, blank=True, default="development", db_index=True)
    protocol = models.CharField(max_length=100, blank=True, default="")
    metrics = models.JSONField(default=dict)
    system_metrics = models.JSONField(default=dict)
    configuration = models.JSONField(default=dict)
    query_count = models.PositiveIntegerField(default=0)
    artifact_path = models.CharField(max_length=500)
    artifact_sha256 = models.CharField(max_length=64, db_index=True)
    is_frozen = models.BooleanField(default=False, db_index=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-imported_at", "method"]


class RetrievalInteraction(models.Model):
    """Validated behavioral outcome tied to a server-side retrieval trace."""

    EVENT_TYPES = (
        ("impression", "Impression"),
        ("click", "Click"),
        ("save", "Save"),
        ("relevance", "Relevance feedback"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    retrieval_event = models.ForeignKey(
        RetrievalEvent, on_delete=models.CASCADE, related_name="interactions"
    )
    article = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retrieval_interactions",
    )
    document_id = models.CharField(max_length=100)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retrieval_interactions",
    )
    event_type = models.CharField(max_length=16, choices=EVENT_TYPES, db_index=True)
    rank = models.PositiveSmallIntegerField()
    relevance = models.SmallIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["retrieval_event", "document_id", "event_type"],
                name="unique_retrieval_document_interaction",
            ),
            models.CheckConstraint(
                condition=Q(relevance__isnull=True) | Q(relevance__in=[-1, 1]),
                name="valid_retrieval_relevance_value",
            ),
        ]
        indexes = [
            models.Index(
                fields=["event_type", "-created_at"],
                name="retrieval_interaction_type_idx",
            )
        ]


class ExperimentProtocol(models.Model):
    """Checksum-locked preregistration stored before experimental traffic."""

    name = models.CharField(max_length=100)
    version = models.PositiveSmallIntegerField()
    spec_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    status = models.CharField(max_length=16, default="frozen", db_index=True)
    frozen_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "version"], name="unique_experiment_protocol_version"
            )
        ]


def update_comment_count(sender, instance, **kwargs) -> None:
    Article.objects.filter(pk=instance.article_id).update(
        comm_count=instance.article.comment_set.count()
    )


models.signals.post_save.connect(
    update_comment_count, sender=Comment, dispatch_uid="update_article_comment_count"
)
models.signals.post_delete.connect(
    update_comment_count,
    sender=Comment,
    dispatch_uid="update_article_comment_count_delete",
)
