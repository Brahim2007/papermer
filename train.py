"""Fit and persist the reproducible TF-IDF retrieval baseline.

Dense and hybrid systems should be introduced through separate experiment
configurations so that paper results remain comparable to this baseline.
"""

from __future__ import annotations

import argparse
import json
import pickle
import platform
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import sklearn

from retrieval import TfidfRetriever


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("artifacts/corpus.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/tfidf"))
    args = parser.parse_args()

    frame = pd.read_csv(args.corpus).fillna("")
    required = {"id", "retrieval_text"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"corpus is missing required columns: {sorted(missing)}")

    retriever = TfidfRetriever().fit(
        frame["id"].astype(str).tolist(),
        frame["retrieval_text"].astype(str).tolist(),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "retriever.pkl").open("wb") as handle:
        pickle.dump(retriever, handle, protocol=pickle.HIGHEST_PROTOCOL)

    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "method": "tfidf",
        "corpus": str(args.corpus.resolve()),
        "corpus_size": retriever.corpus_size,
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "parameters": {
            "ngram_range": [1, 2],
            "min_df": 1,
            "sublinear_tf": True,
            "stop_words": "english",
        },
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
