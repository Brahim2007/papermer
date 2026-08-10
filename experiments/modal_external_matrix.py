"""Modal L4 launcher for the frozen external B0-B7 matrix."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import modal


APP_NAME = "papermetrix-external-matrix-v1"
VOLUME_NAME = "papermetrix-external-matrix-v1"
GPU = "L4"
TIMEOUT_SECONDS = 2 * 60 * 60

DATASETS = {
    "beir-scifact": "beir-v1.0.0",
    "beir-scidocs": "beir-v1.0.0",
    "litsearch": "9573fb284a1026c998df47024b888a163f0f0e25",
}


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.6.0",
        "numpy==2.2.6",
        "pandas==2.2.3",
        "scipy==1.15.3",
        "scikit-learn==1.5.2",
        "transformers==4.57.6",
        "adapters==1.3.0",
        "sentence-transformers==3.4.1",
    )
    .add_local_dir("retrieval", "/workspace/retrieval", copy=True)
    .add_local_dir("experiments", "/workspace/experiments", copy=True)
)

app = modal.App(APP_NAME, image=image)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _run(command: list[str]) -> None:
    print("RUN", " ".join(command), flush=True)
    subprocess.run(command, cwd="/workspace", check=True)


@app.function(gpu=GPU, timeout=5 * 60)
def preflight() -> dict:
    """Confirm the pinned image and allocated GPU before the full paid run."""
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Modal allocated no CUDA GPU")
    probe = torch.ones((1024, 1024), device="cuda")
    checksum = float((probe @ probe).mean().cpu())
    return {
        "cuda": True,
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "checksum": checksum,
    }


@app.function(
    gpu=GPU,
    cpu=8,
    memory=32768,
    timeout=TIMEOUT_SECONDS,
    volumes={"/data": volume},
)
def build_caches_and_run_matrix() -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Modal allocated no CUDA GPU")
    device = torch.cuda.get_device_name(0)
    summaries = {}
    for dataset, revision in DATASETS.items():
        benchmark_dir = Path("/data/input") / dataset / revision
        output_dir = Path("/data/output") / dataset
        output_dir.mkdir(parents=True, exist_ok=True)
        cache = output_dir / "specter2.npz"
        if not cache.exists() or not cache.with_suffix(".json").exists():
            _run(
                [
                    "python",
                    "-m",
                    "experiments.build_specter2_cache",
                    "--corpus",
                    str(benchmark_dir / "corpus.csv"),
                    "--output",
                    str(cache),
                    "--device",
                    "cuda",
                    "--batch-size",
                    "64",
                ]
            )
            volume.commit()
        matrix_manifest = output_dir / "matrix" / "matrix_manifest.json"
        manifest = None
        if matrix_manifest.exists():
            manifest = json.loads(matrix_manifest.read_text(encoding="utf-8"))
        if not manifest or manifest.get("status") != "completed":
            _run(
                [
                    "python",
                    "-m",
                    "experiments.run_external_matrix",
                    "--benchmark-dir",
                    str(benchmark_dir),
                    "--output-dir",
                    str(output_dir / "matrix"),
                    "--specter-cache",
                    str(cache),
                    "--top-k",
                    "100",
                    "--candidate-k",
                    "100",
                    "--reranker-batch-size",
                    "64",
                    "--resume",
                ]
            )
            volume.commit()
            manifest = json.loads(matrix_manifest.read_text(encoding="utf-8"))
        summaries[dataset] = {
            "status": manifest["status"],
            "runs": {
                item["run_id"]: item["status"] for item in manifest["runs"]
            },
        }
    return {
        "gpu": device,
        "torch": torch.__version__,
        "datasets": summaries,
        "volume": VOLUME_NAME,
    }


@app.local_entrypoint()
def main(preflight_only: bool = False) -> None:
    target = preflight if preflight_only else build_caches_and_run_matrix
    result = target.remote()
    print(json.dumps(result, indent=2, sort_keys=True))
