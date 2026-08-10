"""Django-independent retrieval components used by PaperMetrix experiments."""

from .bm25 import BM25Retriever
from .baselines import StaticMetadataRetriever
from .citation_graph import (
    CitationEdge,
    CitationGraphArtifact,
    CitationHybridRetriever,
    CitationGraphRetriever,
    GraphExpansionRetriever,
    load_citation_graph,
)
from .hybrid import HybridRetriever, HybridSearchResult, reciprocal_rank_fusion
from .metrics import average_precision, evaluate_ranking
from .recommendation_metrics import (
    catalog_coverage_at_k,
    citation_novelty_at_k,
    long_tail_share_at_k,
    mean_age_days_at_k,
    topic_diversity_at_k,
)
from .reranker import (
    BGE_RERANKER_MODEL,
    BGE_RERANKER_REVISION,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    MMARCO_RERANKER_MODEL,
    MMARCO_RERANKER_REVISION,
    CrossEncoderReranker,
    CrossEncoderRetriever,
)
from .specter2 import Specter2Encoder, Specter2Retriever
from .specter_cache import (
    Specter2CorpusCache,
    load_specter2_cache,
    save_specter2_cache,
)
from .tfidf import SearchResult, TfidfRetriever

__all__ = [
    "BM25Retriever",
    "StaticMetadataRetriever",
    "BGE_RERANKER_MODEL",
    "BGE_RERANKER_REVISION",
    "DEFAULT_RERANKER_MODEL",
    "DEFAULT_RERANKER_REVISION",
    "MMARCO_RERANKER_MODEL",
    "MMARCO_RERANKER_REVISION",
    "CitationEdge",
    "CitationGraphArtifact",
    "CitationGraphRetriever",
    "CitationHybridRetriever",
    "CrossEncoderReranker",
    "CrossEncoderRetriever",
    "GraphExpansionRetriever",
    "HybridRetriever",
    "HybridSearchResult",
    "SearchResult",
    "Specter2Encoder",
    "Specter2CorpusCache",
    "Specter2Retriever",
    "TfidfRetriever",
    "evaluate_ranking",
    "average_precision",
    "catalog_coverage_at_k",
    "citation_novelty_at_k",
    "long_tail_share_at_k",
    "mean_age_days_at_k",
    "topic_diversity_at_k",
    "load_specter2_cache",
    "load_citation_graph",
    "reciprocal_rank_fusion",
    "save_specter2_cache",
]
