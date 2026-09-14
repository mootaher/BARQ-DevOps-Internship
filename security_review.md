# Security and production-readiness review

This review separates controls implemented during the assessment from improvements still required for a real production deployment.

## Finding 1 — Runtime secrets were exposed through tracked/runtime files

- **Risk and evidence:** The starter configuration stored runtime credentials in repository-controlled files and copied an environment file into the application image.
- **Impact:** Repository or image access could expose credentials, and leaked values may remain in Git history or image layers.
- **Implemented fix / commit:** `12aaffe fix: harden secrets and container runtime`
  - Real values moved to an ignored root `.env`.
  - `.env.example` contains safe placeholders only.
  - `config/app.env` was removed from runtime use and ignored.
  - The Dockerfile no longer copies that file into the image.
- **Production follow-up:** Use a dedicated secret manager or platform-native secrets and implement credential rotation.
- **How to verify:** Confirm `.env` is ignored, `.env.example` contains placeholders, and `/srv/app.env` does not exist in the application container.

## Finding 2 — PostgreSQL and Redis must not be host-accessible

- **Risk and evidence:** Publishing database/cache ports unnecessarily increases attack surface.
- **Impact:** Direct access could bypass application controls and expose stateful services to credential attacks or exploitation.
- **Implemented fix / commit:** `494b662 fix: isolate backend services from host and nginx`
  - PostgreSQL and Redis publish no host ports.
  - Application containers publish no host ports.
  - Only NGINX exposes the public service port.
- **Production follow-up:** Add host firewalls or cloud security groups in addition to Docker controls.
- **How to verify:** `docker compose ps` shows only NGINX with a host port. `validate.py` also checks prohibited port exposure.

## Finding 3 — NGINX should not directly reach PostgreSQL or Redis

- **Risk and evidence:** A flat Docker network would give the reverse proxy unnecessary connectivity to backend data services.
- **Impact:** Compromise of NGINX could increase lateral-movement opportunities.
- **Implemented fix / commit:** `494b662 fix: isolate backend services from host and nginx`
  - NGINX is on `frontend`.
  - PostgreSQL and Redis are on `backend`.
  - Application containers connect to both.
- **Production follow-up:** Apply equivalent segmentation using cloud security groups, Kubernetes NetworkPolicies, or service-mesh policies.
- **How to verify:** `validate.py` checks the expected network roles and confirms NGINX has no shared network path to PostgreSQL or Redis.

## Finding 4 — Application containers should not run as root

- **Risk and evidence:** Root runtime privileges give a compromised application more power inside the container.
- **Impact:** Exploitation may have greater effect on the filesystem and runtime environment.
- **Implemented fix / commit:** `12aaffe fix: harden secrets and container runtime`
  - Application containers run as the `app` user.
- **Production follow-up:** Consider read-only filesystems, dropped capabilities, `no-new-privileges`, and stronger seccomp/AppArmor policies.
- **How to verify:** `docker exec app-01 whoami` and `docker exec app-02 whoami` return `app`.

## Finding 5 — External images should be reproducible

- **Risk and evidence:** Floating tags may change without any repository change.
- **Impact:** Builds can unexpectedly gain incompatible or vulnerable software.
- **Implemented fix / commit:** PostgreSQL, Redis, and NGINX images are pinned by SHA-256 digest in Compose.
- **Production follow-up:** Add automated vulnerability scanning and controlled dependency/image update workflows.
- **How to verify:** Inspect `docker-compose.yml` and confirm external images contain `@sha256:` digests.

## Finding 6 — Persistent state must survive container recreation

- **Risk and evidence:** Container-local state is disposable and may be lost on recreation.
- **Impact:** Records and counters can disappear during normal operational changes.
- **Implemented fix / commit:** `8df8cc8 fix: persist postgres and redis data`
  - PostgreSQL uses a named volume mounted at `/var/lib/postgresql/data`.
  - Redis uses a named `/data` volume with AOF enabled.
- **Production follow-up:** Use redundant or managed storage, encryption, replication, and retention policies.
- **How to verify:** PostgreSQL records and Redis counter state were both proven to survive container recreation.

## Finding 7 — Backups must be restored to prove recoverability

- **Risk and evidence:** A generated backup file may still be corrupt or operationally unusable.
- **Impact:** Backup failure may only be discovered during a real incident.
- **Implemented fix / commit:** `5bb3e75 feat: add postgres backup and restore verification`
  - `backup.sh` creates a PostgreSQL custom-format dump.
  - The archive is validated.
  - `restore.sh` restores into a temporary verification database.
  - The restored table and row count are checked.
  - Temporary verification databases are removed afterward.
- **Production follow-up:** Encrypt backups, store copies off-host, define RPO/RTO targets, and schedule automated restore drills.
- **How to verify:** Restore verification recovered five rows from `records`, preserved the live database, and left zero temporary verification databases.

## Finding 8 — Liveness and readiness must remain separate

- **Risk and evidence:** A running process may still be unable to serve requests because PostgreSQL or Redis is unavailable.
- **Impact:** Traffic can be routed to unhealthy application instances.
- **Implemented fix / commit:** `10491c7 fix: restore app routing health and dependency readiness`
  - `/health` checks process health.
  - `/ready` verifies PostgreSQL and Redis.
  - Applications depend on healthy backend services.
- **Production follow-up:** Add latency/error metrics and dependency-specific alerting.
- **How to verify:** `validate.py` checks `/health`, `/ready`, and both dependency statuses.

## Finding 9 — Backend loss still creates client-visible errors

- **Risk and evidence:** NGINX currently has `proxy_next_upstream off`.
- **Impact:** Requests routed to a failed backend are not retried against a surviving instance.
- **Implemented fix / commit:** `d685aa9 test: add backend failure recovery check`
  - The behavior is intentionally measured instead of hidden.
- **Observed evidence:** With `app-02` stopped, 30 requests produced:
  - 15 HTTP 200 responses through `app-01`
  - 15 client-visible errors
  - no successful traffic from the stopped backend
  - successful recovery and later traffic from `app-02`
- **Production follow-up:** Consider health-aware load balancing and carefully scoped retry behavior for safe/idempotent requests.
- **How to verify:** Run `python3 failure_test.py`.

## Finding 10 — Centralized observability is missing

- **Risk and evidence:** The environment has logs but no centralized metrics, tracing, dashboards, or alerting.
- **Impact:** Failures may be detected late and diagnosis may take longer.
- **Implemented fix / commit:** `19d2add docs: add reproducible historical log analysis`
  - Historical NGINX and application logs can be correlated reproducibly.
- **Production follow-up:** Add centralized log aggregation, metrics, tracing, uptime checks, and alerts for 5xx rate, latency, dependency health, restarts, and backup failures.
- **How to verify:** Run `python3 scripts/analyze_logs.py` and inspect `log_analysis.md`.

## Finding 11 — Infrastructure still contains single points of failure

- **Risk and evidence:** NGINX, PostgreSQL, and Redis each run as a single instance.
- **Impact:** Failure of any of these services can reduce or remove availability.
- **Implemented fix / commit:** `2876b59 fix: improve container reliability controls`
  - Restart behavior was improved, but redundancy was intentionally not added to this assessment environment.
- **Production follow-up:** Use redundant edge instances, PostgreSQL failover/replication, and an appropriate Redis HA design.
- **How to verify:** Inspect `docker compose ps` and `docker-compose.yml`.

## Finding 12 — Resource limits must be based on workload evidence

- **Risk and evidence:** Unlimited containers can exhaust the host, while arbitrary limits can cause throttling or OOM termination.
- **Impact:** Either condition can create availability problems.
- **Implemented fix / commit:** `2876b59 fix: improve container reliability controls`
  - Application containers are limited to 256 MiB memory and 0.50 CPU.
  - Services use `restart: unless-stopped`.
  - Database/cache limits were not guessed from idle usage.
- **Production follow-up:** Use load testing and real production telemetry to size CPU/memory requests and limits.
- **How to verify:** Inspect container memory/CPU settings and restart policies with `docker inspect`.

## Overall production-readiness limitations

The repaired environment is substantially safer than the starter system but is still a lab environment. Important future improvements include:

- TLS termination and certificate management.
- Authentication and authorization for externally exposed APIs.
- Redundant NGINX, PostgreSQL, and Redis infrastructure.
- Encrypted off-host backups.
- Centralized logs, metrics, traces, dashboards, and alerting.
- Automated dependency and container vulnerability scanning.
- Load testing before production resource sizing.
- Stronger container runtime restrictions.
- Network firewall controls in addition to Docker networking.
- Formal credential rotation and secrets management.
