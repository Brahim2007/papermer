# Security Policy

## Reporting a vulnerability

Please use the repository's private GitHub Security Advisory form. Do not open
a public issue containing an exploit, credential, private paper corpus, or user
data.

Include the affected version, impact, reproduction conditions, and a proposed
fix if available. Maintainers should acknowledge a complete report within
seven days and coordinate disclosure after a fixed release is available.

## Supported versions

Only the current `main` release and the newest production tag receive security
fixes.

## Secrets and data

- Never commit `.env`, `.env.production`, database dumps, API keys, or paper
  artifacts whose distribution rights are unclear.
- Rotate a credential immediately if it appears in a commit, log, issue, or
  chat. Removing the text alone does not revoke it.
- Use repository secrets only for CI values that are actually required.
- Backups and research corpora must have separate access controls from the
  public application source.

TruffleHog's history scan excludes only `scholarly/tests/test_snapshot.py`.
An old pytest function name in that file matched Lob's `test_...` credential
shape and Lob's verifier accepted it, despite the line containing only a Python
identifier. Gitleaks still scans that file and the complete repository history;
TruffleHog continues to scan every production path.
