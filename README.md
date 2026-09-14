<img src="assets/barq-logo.svg" alt="BARQ Systems" width="180">

# BARQ DevOps Internship Assessment

Final repaired and validated BARQ assessment environment.

## Final architecture

Client -> 127.0.0.1:8090 -> NGINX -> app-01/app-02/app-03 -> PostgreSQL + Redis.

Networks:
- `frontend`: nginx, app-01, app-02, app-03
- `backend`: app-01, app-02, app-03, postgres, redis
- NGINX is not attached to the backend network.
- Only NGINX publishes a host port.

Persistence:
- PostgreSQL named volume at `/var/lib/postgresql/data`
- Redis named volume at `/data` with AOF enabled

See `docs/ARCHITECTURE.md` and `architecture.png`.

## Setup

    cp .env.example .env
    docker compose config -q

Keep `POSTGRES_PASSWORD` consistent with the password inside `DATABASE_URL`.

## Build and start

    docker compose up --build -d
    docker compose ps

Expected services: nginx, app-01, app-02, app-03, postgres, redis.

Public URL: `http://127.0.0.1:8090`

## Endpoint checks

    curl -sS http://127.0.0.1:8090/
    curl -sS http://127.0.0.1:8090/health
    curl -sS http://127.0.0.1:8090/ready
    curl -sS http://127.0.0.1:8090/instance
    curl -sS http://127.0.0.1:8090/records
    curl -sS http://127.0.0.1:8090/counter

To prove all three application instances serve through NGINX:

    for i in {1..9}; do curl -sS http://127.0.0.1:8090/instance; echo; done

## Validation

Run:

    python3 validate.py

The validator checks Compose syntax, service health, public access, `/health`, `/ready`, PostgreSQL and Redis operations, all configured `app-*` instances, network isolation, NGINX isolation from PostgreSQL/Redis, and prohibited host ports. It dynamically discovers the public port and application services.

## Controlled failure and recovery

Run:

    python3 failure_test.py

The test proves the baseline, stops one backend, measures successes/errors, restores it, waits for health recovery, and proves the recovered backend serves traffic again. It never uses `docker compose down`.

NGINX uses `proxy_next_upstream off`, so some client-visible errors during backend failure are expected and intentionally measured.

## Persistence proof

The record `assessment-persistence-proof-2026-09-14` was created through `/records`.

PostgreSQL and the application containers were force-recreated without deleting the named volume. The record remained present afterward, proving PostgreSQL persistence across container recreation.

## Backup and restore

Create a backup:

    ./backup.sh

Restore-verify a backup:

    ./restore.sh backups/<backup-file>.dump

`restore.sh` restores into a temporary verification database, verifies the `records` table and rows, leaves the live database unchanged, and removes the temporary database afterward.

## Historical log analysis

Run:

    python3 scripts/analyze_logs.py

Key findings:
- 720 distinct client requests
- 95 server-side 5xx responses
- 13.19% 5xx rate
- median latency: 54 ms
- p95 latency: 2001 ms
- 502: backend connectivity failures
- 503: PostgreSQL/Redis dependency failures
- 504: upstream timeout behavior
- 19 observed retries, all successful

See `log_analysis.md`.

## CI

GitHub Actions workflow: `.github/workflows/ci.yml`

It performs checkout, Python/Bash syntax checks, Compose validation, build, startup, bounded readiness polling, `validate.py`, failure diagnostics, and cleanup.

## Security and reliability

Implemented controls include:
- secrets outside tracked runtime files
- non-root application containers
- only NGINX publishes a host port
- frontend/backend network segmentation
- pinned external image digests
- restart policies
- application CPU/memory limits
- dependency-aware readiness
- PostgreSQL and Redis persistence
- tested PostgreSQL restore verification

See `security_review.md`.

## Remaining production limitations

Important remaining single points of failure:
- one NGINX instance
- one PostgreSQL instance
- one Redis instance
- local volumes depend on the Docker host
- local backups do not protect against host loss

Production follow-up should add redundancy, off-host encrypted backups, TLS, centralized observability, alerting, stronger secrets management, and workload-based resource sizing.

## Documentation

- `troubleshooting.md`
- `log_analysis.md`
- `decisions.md`
- `security_review.md`
- `AI_USAGE.md`
- `docs/ARCHITECTURE.md`
- `docs/EVIDENCE_INDEX.md`

## Stop safely

Preserve data:

    docker compose stop

or:

    docker compose down

Only when intentionally deleting persisted lab data:

    docker compose down -v
