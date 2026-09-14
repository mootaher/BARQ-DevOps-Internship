# AI usage disclosure

AI was used during this assessment as a technical assistant for investigation guidance, implementation drafting, review, and documentation. All runtime claims and evidence recorded in the repository were independently verified by executing commands against the local environment. AI-generated suggestions were not treated as evidence by themselves.

## Use 1 — Infrastructure investigation and repair

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help investigate the intentionally broken Docker/NGINX/Flask/PostgreSQL/Redis environment, reason about observed failures, and draft focused configuration changes.
- **Files or decisions affected:** `docker-compose.yml`, `Dockerfile`, `nginx/nginx.conf`, `.gitignore`, `.env.example`, removal of `config/app.env`, and related troubleshooting decisions.
- **What you changed or rejected:** Changes were applied incrementally rather than replacing the starter architecture. Arbitrary infrastructure resource limits were rejected because idle measurements were not sufficient evidence for production sizing. Git history containing the original assessment state was intentionally preserved rather than rewritten.
- **How you independently verified it:** Used `docker compose ps`, `docker inspect`, `curl`, direct container connectivity checks, `/health`, `/ready`, `/instance`, persistence tests, non-root checks, network-resolution checks, and repeated full validation.
- **Related commits:** `10491c7`, `8df8cc8`, `494b662`, `12aaffe`, `2876b59`

## Use 2 — Historical log analysis

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help design a reproducible method for parsing the supplied NGINX/application/error logs, deduplicating client requests, calculating status/latency statistics, and correlating incidents by request ID and timestamp.
- **Files or decisions affected:** `scripts/analyze_logs.py`, `log_analysis.md`
- **What you changed or rejected:** Analysis was based only on the supplied historical logs. Duplicate access records were not double-counted as distinct requests. Comma-separated upstream attempts were retained as one client request rather than incorrectly counted as separate requests.
- **How you independently verified it:** Ran the analyzer locally, syntax-checked it with `python3 -m py_compile`, compared generated counts with source-log line counts, confirmed malformed-line handling, and verified SHA-256 hashes showed the original logs were unchanged.
- **Related commit:** `19d2add`

## Use 3 — Environment validation and failure testing

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help design bounded automated checks for the assessment requirements and a controlled backend failure/recovery test.
- **Files or decisions affected:** `validate.py`, `failure_test.py`
- **What you changed or rejected:** Validation was designed to discover the public NGINX port and `app-*` services dynamically so it can remain usable after the recorded challenge. The failure test deliberately avoids `docker compose down`. Cleanup logic was strengthened so the selected backend is always restored even if the stop/test phase fails.
- **How you independently verified it:** Syntax-checked both scripts and executed them against the real Docker stack. `validate.py` passed all endpoint, persistence, network, health, backend, and host-port checks. `failure_test.py` stopped `app-02`, measured 30 requests, observed 15 successes and 15 errors, restored `app-02`, confirmed it became healthy and served traffic again, then a complete validation run passed.
- **Related commits:** `70c7720`, `d685aa9`

## Use 4 — PostgreSQL backup and restore verification

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help implement a safe PostgreSQL backup and restore-verification procedure.
- **Files or decisions affected:** `backup.sh`, `restore.sh`
- **What you changed or rejected:** A destructive restore into the live `barq_tasks` database was rejected. Restore testing instead uses a temporary verification database and removes it afterward.
- **How you independently verified it:** Created a real custom-format PostgreSQL dump, validated it with `pg_restore -l`, restored it into a temporary database, verified the `records` table and five restored rows, confirmed the live database remained intact, and confirmed zero temporary verification databases remained after cleanup.
- **Related commit:** `5bb3e75`

## Use 5 — CI workflow

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help draft a GitHub Actions workflow matching the assessment requirements.
- **Files or decisions affected:** `.github/workflows/ci.yml`
- **What you changed or rejected:** The initial workflow was strengthened to include Python and Bash syntax checks in addition to Docker Compose validation. The workflow uses bounded readiness polling instead of an arbitrary fixed delay.
- **How you independently verified it:** Ran the same Python, Bash, and Compose syntax checks locally, pushed the workflow to GitHub, and confirmed the GitHub Actions CI run completed successfully with a green result.
- **Related commit:** `f7e9e8e`

## Use 6 — Documentation and technical review

- **Tool/model:** OpenAI ChatGPT, GPT-5.6 Sol
- **Purpose:** Help organize verified implementation decisions, security findings, troubleshooting evidence, and assessment documentation.
- **Files or decisions affected:** `troubleshooting.md`, `decisions.md`, `security_review.md`, and this `AI_USAGE.md`.
- **What you changed or rejected:** Documentation was kept tied to observed commands/results and actual commits. Claims without runtime evidence were avoided. Production recommendations were separated from controls actually implemented in the assessment.
- **How you independently verified it:** Compared documentation against Git history, the current Compose/Docker configuration, executed validation/failure/backup tests, and the observed terminal outputs before committing each documentation batch.
- **Related commits:** `307448e`, `50f8044`, `d367412`

## Verification principle

AI suggestions were treated as proposals, not proof. The assessment environment itself was the source of truth. Important changes were verified through executable commands, Docker runtime inspection, HTTP requests, persistence tests, controlled failure/recovery testing, backup restoration, Git diffs, and GitHub Actions.
