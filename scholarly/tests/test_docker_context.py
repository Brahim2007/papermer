from pathlib import Path


def test_production_docker_context_excludes_vps_data_and_local_overrides():
    entries = {
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {"artifacts", "results", "backups", "staging"} <= entries
    assert "compose.vps.yaml*" in entries
    assert "deploy/bootstrap_hostinger_env.sh" in entries
