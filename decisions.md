# Technical decisions

This document records the main technical decisions made while repairing and hardening the BARQ assessment environment.

## Decision 1 — Keep NGINX as the only host-facing service

- **Choice:** Publish only NGINX to the host. PostgreSQL, Redis, and application containers do not publish host ports.
- **Why:** External requests should enter through one controlled reverse-proxy boundary. PostgreSQL and Redis do not require direct host access.
- **Alternative:** Publish PostgreSQL, Redis, and application ports directly for easier debugging.
- **Trade-off:** Debugging from the host is slightly less convenient, but the attack surface is smaller.
- **Evidence / commit:** `494b662 fix: isolate backend services from host and nginx`
- **Production improvement:** Add host/cloud firewall rules and expose administrative access only through authenticated management paths.

## Decision 2 — Separate frontend and backend Docker networks

- **Choice:** Use a `frontend` network for NGINX and applications, and a `backend` network for applications, PostgreSQL, and Redis.
- **Why:** NGINX needs application access but does not need direct database/cache access.
- **Alternative:** Put every service on one Docker network.
- **Trade-off:** Two networks add minor configuration complexity but provide clearer trust boundaries.
- **Evidence / commit:** `494b662 fix: isolate backend services from host and nginx`
- **Production improvement:** Apply equivalent segmentation using cloud security groups, Kubernetes NetworkPolicies, or similar controls.

## Decision 3 — Use health and readiness checks instead of fixed startup delays

- **Choice:** Application startup depends on healthy PostgreSQL and Redis services. `/health` checks the process while `/ready` verifies dependencies.
- **Why:** A running process is not necessarily ready to serve traffic.
- **Alternative:** Start everything together and use arbitrary `sleep` commands.
- **Trade-off:** Health checks add configuration, but they provide deterministic startup behavior.
- **Evidence / commit:** `10491c7 fix: restore app routing health and dependency readiness`
- **Production improvement:** Add dependency latency metrics and alerting while retaining lightweight liveness checks.

## Decision 4 — Persist PostgreSQL and Redis with named volumes

- **Choice:** Persist PostgreSQL at `/var/lib/postgresql/data` and Redis at `/data` with AOF enabled.
- **Why:** Container recreation must not destroy application state.
- **Alternative:** Store state only inside disposable container layers or temporary filesystems.
- **Trade-off:** Persistent volumes require lifecycle and backup management but prevent routine container replacement from deleting state.
- **Evidence / commit:** `8df8cc8 fix: persist postgres and redis data`
- **Verification:** PostgreSQL records and the Redis counter survived container recreation.
- **Production improvement:** Use managed/redundant storage, encryption, retention policies, and off-host backups.

## Decision 5 — Keep runtime secrets outside Git and container images

- **Choice:** Keep real values in an ignored root `.env` file and only safe placeholders in `.env.example`. Remove the tracked runtime environment file from the application image.
- **Why:** Credentials should not be embedded in Git, Compose configuration, or container images.
- **Alternative:** Hardcode credentials or commit a populated environment file.
- **Trade-off:** Developers must create `.env` locally, but secret exposure risk is greatly reduced.
- **Evidence / commit:** `12aaffe fix: harden secrets and container runtime`
- **Production improvement:** Use a dedicated secrets manager or platform-native secret mechanism.

## Decision 6 — Run the application as a non-root user

- **Choice:** Run the application containers as the existing `app` user.
- **Why:** A compromised application should not automatically receive root privileges inside its container.
- **Alternative:** Keep the runtime process as root.
- **Trade-off:** File permissions require more care, but the application requires no privileged runtime actions.
- **Evidence / commit:** `12aaffe fix: harden secrets and container runtime`
- **Verification:** `whoami` returned `app` in both application containers and readiness remained healthy.
- **Production improvement:** Add read-only filesystems where possible, drop unnecessary capabilities, and apply stronger runtime security profiles.

## Decision 7 — Add restart and resource controls

- **Choice:** Configure `restart: unless-stopped` and limit each application instance to 256 MiB memory and 0.50 CPU.
- **Why:** Containers should recover from unexpected exits and application instances should not consume unlimited host resources.
- **Alternative:** Disable restart behavior and leave all resources unrestricted.
- **Trade-off:** Incorrect limits could cause throttling or OOM failures. These limits suit the assessment workload but are not claimed as production sizing.
- **Evidence / commit:** `2876b59 fix: improve container reliability controls`
- **Production improvement:** Set limits using load-test and production telemetry rather than idle measurements.

## Decision 8 — Keep NGINX retry disabled for the assessment failure test

- **Choice:** Keep `proxy_next_upstream off`.
- **Why:** This makes backend loss observable and allows the required failure test to measure real client-visible errors.
- **Alternative:** Automatically retry failed requests against another upstream.
- **Trade-off:** With two round-robin backends, stopping one backend causes some client requests to fail.
- **Evidence / commit:** `d685aa9 test: add backend failure recovery check`
- **Verification:** With `app-02` stopped, 15 of 30 requests succeeded through `app-01`, while 15 returned errors. After restoration, `app-02` became healthy and served requests again.
- **Production improvement:** For a highly available production service, consider carefully scoped retries for safe requests together with health-aware load balancing and monitoring.

## Decision 9 — Verify backups by restoring them

- **Choice:** `backup.sh` creates and validates a PostgreSQL custom-format archive. `restore.sh` restores it into a temporary verification database rather than replacing the live database.
- **Why:** Successful backup creation alone does not prove the backup is recoverable.
- **Alternative:** Treat a successful `pg_dump` command as sufficient evidence.
- **Trade-off:** Restore verification requires temporary database resources but gives much stronger recovery evidence.
- **Evidence / commit:** `5bb3e75 feat: add postgres backup and restore verification`
- **Verification:** The test restored the `records` table with five rows, preserved the live database, and removed the temporary verification database afterward.
- **Production improvement:** Store encrypted backups independently of the Docker host and perform scheduled restore drills.

## Key limitations

The repaired assessment environment still has intentional production limitations:

- NGINX is a single point of failure.
- PostgreSQL is a single instance.
- Redis is a single instance.
- Application resource limits were not derived from production load testing.
- Local named volumes protect against container recreation but not host failure.
- Local backup files do not protect against host loss.
- NGINX currently does not retry another backend after an upstream failure.
- There is no centralized metrics, tracing, alerting, or log aggregation.
- The environment uses synthetic local data and should not be exposed publicly.
