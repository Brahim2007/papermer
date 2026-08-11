from datetime import date

import numpy as np
import pandas as pd

from experiments.retrievers import build_retriever
from retrieval import Specter2CorpusCache


class FakeSharedEncoder:
    def identity(self):
        return {"model": "fake-shared"}

    def encode_queries(self, queries, *, batch_size=16):
        return np.asarray([[1.0, 0.0] for _ in queries], dtype=np.float32)


def test_build_retriever_reuses_supplied_specter2_encoder():
    corpus = pd.DataFrame(
        {
            "id": ["a", "b"],
            "title": ["alpha", "beta"],
            "abstract": ["", ""],
            "retrieval_text": ["alpha", "beta"],
            "_publication_date": [date(2020, 1, 1), date(2020, 1, 2)],
        }
    )
    encoder = FakeSharedEncoder()
    cache = Specter2CorpusCache(
        ("a", "b"),
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        {"encoder": encoder.identity()},
    )

    retriever = build_retriever(
        "hybrid",
        corpus,
        specter_cache=cache,
        specter2_encoder=encoder,
    )

    assert retriever.retrievers["specter2"].encoder is encoder
    assert retriever.search("alpha", top_k=1)[0].document_id == "a"
