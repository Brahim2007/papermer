"""Modal L4 launcher for the frozen Scope v3.1.1 SPECTER2 cache."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import modal


APP_NAME = "papermetrix-scope-v3-1-1-specter2"
VOLUME_NAME = "papermetrix-scope-v3-1-1"
GPU = "L4"
CORPUS_SHA256 = "2d80460bd329c2c5401478320f3dbd1e6d35806631ce4df1e5d96fa280af765f"
DOCUMENT_COUNT = 52493
INPUT = Path("/data/input/corpus.csv")
OUTPUT = Path("/data/output/specter2.npz")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.6.0",
        "numpy==2.2.6",
        "pandas==2.2.3",
        "transformers==4.57.6",
        "adapters==1.3.0",
    )
    .add_local_dir("retrieval", "/workspace/retrieval", copy=True)
    .add_local_dir("experiments", "/workspace/experiments", copy=True)
)

app = modal.App(APP_NAME, image=image)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@app.function(gpu=GPU, timeout=5 * 60, volumes={"/data": volume})
def preflight() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Modal allocated no CUDA GPU")
    return {
        "cuda": True,
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "corpus_present": INPUT.exists(),
        "corpus_sha256": _sha256(INPUT) if INPUT.exists() else None,
    }


@app.function(
    gpu=GPU,
    cpu=4,
    memory=16384,
    timeout=2 * 60 * 60,
    volumes={"/data": volume},
)
def build_cache() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Modal allocated no CUDA GPU")
    observed = _sha256(INPUT)
    if observed != CORPUS_SHA256:
        raise ValueError(f"corpus checksum mismatch: {observed}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = OUTPUT.with_suffix(".json")
    if OUTPUT.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("corpus_sha256") == CORPUS_SHA256
            and int(metadata.get("document_count") or 0) == DOCUMENT_COUNT
        ):
            return {
                "status": "cache_hit",
                "gpu": torch.cuda.get_device_name(0),
                "cache_sha256": _sha256(OUTPUT),
                "metadata_sha256": _sha256(metadata_path),
                "metadata": metadata,
            }
    os.environ["HF_HOME"] = "/data/huggingface"
    started = time.perf_counter()
    subprocess.run(
        [
            "python",
            "-m",
            "experiments.build_specter2_cache",
            "--corpus",
            str(INPUT),
            "--output",
            str(OUTPUT),
            "--device",
            "cuda",
            "--batch-size",
            "64",
        ],
        cwd="/workspace",
        check=True,
    )
    volume.commit()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "status": "completed",
        "gpu": torch.cuda.get_device_name(0),
        "elapsed_seconds": time.perf_counter() - started,
        "cache_sha256": _sha256(OUTPUT),
        "metadata_sha256": _sha256(metadata_path),
        "metadata": metadata,
    }


@app.local_entrypoint()
def main(preflight_only: bool = False) -> None:
    result = (preflight if preflight_only else build_cache).remote()
    print(json.dumps(result, indent=2, sort_keys=True))
