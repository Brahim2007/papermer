# Public release checklist

The infrastructure is deployable, but a public research service also needs
the following release decisions. Do not mark the launch complete until every
blocking item has an owner and evidence.

## Blocking

- [ ] Rotate every database, Semantic Scholar, SMTP, and provider credential
      that has appeared outside a secret manager.
- [ ] Choose a source-code license. No license has been assumed automatically.
- [ ] Audit the redistribution rights of every corpus snapshot, abstract,
      generated embedding, model, frontend asset, and benchmark judgment.
- [ ] Publish privacy and terms documents reviewed for the operator's
      jurisdiction, including retention and account-deletion procedures.
- [ ] Configure a real domain, ACME email, sender domain, SPF, DKIM, and DMARC.
- [ ] Run the container build in CI or with a running Docker engine.
- [ ] Test database backup restoration against a separate database.
- [ ] Run a staging smoke test and a small authenticated load test.

## Operations

- [ ] Protect the GitHub default branch and require CI and Security checks.
- [ ] Require pull-request review and prohibit direct production changes.
- [ ] Enable GitHub private vulnerability reporting.
- [ ] Configure uptime, 5xx, memory, disk, and certificate-expiry alerts.
- [ ] Store backups outside the VPS with encryption and retention controls.
- [ ] Document incident response, credential rotation, and rollback ownership.
- [ ] Set a maintenance window for migrations and research cache rebuilding.

## Research integrity

- [ ] Keep the frozen benchmark and publication artifacts immutable.
- [ ] Record commit, corpus checksum, model revision, seed, and configuration
      for every reported run.
- [ ] Separate public application telemetry from experimental judgments.
- [ ] Obtain consent and ethics approval where user behavior is research data.
- [ ] Do not evaluate on private interaction logs without an approved protocol.
