# Troubleshooting journal

Keep chronological entries. Copy this block for each meaningful investigation.

## Entry / date / time
- Symptom:
- Hypothesis:
- Command or test:
- Actual output:
- Failed attempt and what changed your thinking:
- Root cause:
- Fix:
- Retest evidence:
- Related commit:
- Remaining uncertainty:

Do not fabricate a failed attempt just to fill the template. Record actual attempts.
## Entry 1 / 2026-09-13

* Symptom: `curl -i http://localhost:8080/` failed with `Recv failure: Connection reset by peer`.
* Hypothesis: The public Docker port may be mapped to a different internal NGINX port than the port NGINX is actually listening on.
* Command or test:

  * `docker compose ps`
  * `sed -n '55,90p' docker-compose.yml`
  * `cat nginx/nginx.conf`
  * `docker exec nginx nginx -T | grep -n "listen"`
* Actual output:

  * Compose publishes `127.0.0.1:8080` to container port `81`.
  * The active NGINX configuration contains `listen 80;`.
  * `nginx -T` confirmed that the running NGINX process is listening on port `80`.
* Failed attempt and what changed your thinking: The initial request to `http://localhost:8080/` failed even though the NGINX container was running. This showed that container state alone did not prove the service was reachable and led to checking the host-to-container port mapping.
* Root cause: Docker forwards public traffic from host port `8080` to NGINX container port `81`, but NGINX listens on container port `80`.
* Fix: Changed the NGINX Compose port mapping from container port `81` to `80`, matching the active NGINX `listen 80` configuration.
* Retest evidence: After recreating NGINX, `docker inspect nginx --format '{{json .HostConfig.PortBindings}}' | jq` showed host `127.0.0.1:8080` mapped to container port `80`. A subsequent `curl -i http://localhost:8080/` reached NGINX and returned `502 Bad Gateway` instead of a connection reset, proving the public port mapping was fixed and exposing the next upstream issue.

* Related commit: Pending.
* Remaining uncertainty: After correcting the NGINX port mapping, upstream application connectivity may still fail and must be tested separately.
## Entry 2 / 2026-09-13

* Symptom: `app-01` and `app-02` are running but Docker reports both containers as `unhealthy`.
* Hypothesis: The Docker health check may be calling an endpoint that the Flask application does not expose.
* Command or test:

  * `docker compose ps`
  * `docker inspect app-01 --format '{{json .State.Health}}' | jq`
  * `docker inspect app-02 --format '{{json .State.Health}}' | jq`
  * `grep -n "health" docker-compose.yml`
  * `grep -n "health" app/server.py`
* Actual output:

  * Both app containers reported `unhealthy`.
  * The health-check logs returned `HTTP Error 404: NOT FOUND`.
  * `docker-compose.yml` checks `http://127.0.0.1:8080/healthz`.
  * `app/server.py` defines the liveness endpoint as `/health`.
* Failed attempt and what changed your thinking: Initially the containers appeared to start successfully, but checking their health state showed repeated failures. Inspecting the actual health-check output revealed that the failure was an HTTP 404 rather than a process crash.
* Root cause: The Docker health check calls `/healthz`, while the Flask application exposes `/health`.
* Fix: Changed the application health check in `docker-compose.yml` from `/healthz` to the Flask liveness endpoint `/health`.
* Retest evidence: After recreating `app-01` and `app-02`, `docker compose ps` reported both application containers as `healthy`. A request to `http://localhost:8080/health` returned HTTP `200 OK` with `"status":"alive"`.

* Related commit: Pending.
* Remaining uncertainty: Correcting the health-check path will prove liveness, but it will not by itself prove that NGINX can reach the Flask containers or that PostgreSQL and Redis readiness works.
## Entry 3 / 2026-09-13

* Symptom: NGINX cannot connect to `app-01` over the Docker frontend network.
* Hypothesis: The Flask application may be listening only on its own loopback interface instead of the container network interface.
* Command or test:

  * `grep -n "APP_HOST" app/server.py`
  * `sed -n '1,20p' docker-compose.yml`
  * `docker exec nginx sh -c 'wget -S -O- http://app-01:8080/ 2>&1 || true'`
* Actual output:

  * `app/server.py` uses `APP_HOST` as the Flask bind address and defaults to `0.0.0.0`.
  * Compose overrides `APP_HOST` with `127.0.0.1`.
  * NGINX successfully resolved `app-01` to a Docker network IP address but received `Connection refused`.
* Failed attempt and what changed your thinking: The failed request from NGINX showed that service-name resolution was working, so the problem was not Docker DNS. The refusal suggested the application was not listening on the interface reachable from other containers.
* Root cause: Compose forces Flask to bind to `127.0.0.1`, making it reachable only from inside its own container. NGINX therefore cannot connect to the Flask service over the Docker network.
* Fix: Changed `APP_HOST` in `docker-compose.yml` from `127.0.0.1` to `0.0.0.0` so Flask listens on the container network interface and is reachable from NGINX.
* Retest evidence: After recreating both application containers, their logs showed `Running on all addresses (0.0.0.0)` and container network addresses such as `172.19.0.x:8080`. A subsequent request through NGINX reached the Flask backend successfully and returned HTTP `200 OK`.

* Related commit: Pending.
* Remaining uncertainty: After changing the Flask bind address, NGINX upstream port configuration must still be verified separately.
## Entry 4 / 2026-09-14

* Symptom: The Flask application is configured to connect to PostgreSQL and Redis using ports that are not accepting connections.
* Hypothesis: `config/app.env` may contain incorrect internal Docker service ports.
* Command or test:

  * `cat config/app.env`
  * `docker exec app-01 python -c "import socket; socket.create_connection(('postgres', 5433), timeout=2); print('CONNECTED')"`
  * `docker exec app-01 python -c "import socket; socket.create_connection(('postgres', 5432), timeout=2); print('CONNECTED')"`
  * `docker exec app-01 python -c "import socket; socket.create_connection(('redis', 6380), timeout=2); print('CONNECTED')"`
  * `docker exec app-01 python -c "import socket; socket.create_connection(('redis', 6379), timeout=2); print('CONNECTED')"`
* Actual output:

  * `postgres:5433` returned `Connection refused`.
  * `postgres:5432` returned `CONNECTED`.
  * `redis:6380` returned `Connection refused`.
  * `redis:6379` returned `CONNECTED`.
* Failed attempt and what changed your thinking: The configured ports failed even though both PostgreSQL and Redis containers were running and healthy. Testing the standard internal service ports showed that Docker networking worked and that the problem was specifically the configured ports.
* Root cause: The application configuration uses PostgreSQL port `5433` instead of `5432`, and Redis port `6380` instead of `6379`.
* Fix: Updated `config/app.env` so PostgreSQL uses `postgres:5432` and Redis uses `redis:6379`, matching the actual internal service ports.
* Retest evidence: After recreating the application containers, `/ready` changed from reporting both dependencies unavailable to reporting PostgreSQL as `ready` while Redis remained `unavailable`. After correcting Redis as well, `/ready` returned HTTP `200 OK` with both `"postgres":"ready"` and `"redis":"ready"`.

* Related commit: Pending.
* Remaining uncertainty: PostgreSQL authentication may still fail after correcting the port because the configured application password must be verified separately.
## Entry 5 / 2026-09-14

* Symptom: After testing PostgreSQL on the correct internal port, the application still could not establish a database connection.
* Hypothesis: The password in the application's `DATABASE_URL` may not match the PostgreSQL container password.
* Command or test:

  * `grep -Ei "psycopg|postgres" requirements.txt`
  * `docker exec app-01 python -c "import os, psycopg; u=os.environ['DATABASE_URL'].replace(':5433/', ':5432/'); psycopg.connect(u, connect_timeout=2).close(); print('CONNECTED')"`
* Actual output:

  * `psycopg[binary]` is installed and available to the application.
  * Connecting with the corrected port returned `FATAL: password authentication failed for user "barq_app"`.
* Failed attempt and what changed your thinking: Correcting only the PostgreSQL port in the test changed the failure from `Connection refused` to an authentication failure. This showed that the network path was now correct and exposed a second independent configuration problem.
* Root cause: The password in the application's `DATABASE_URL` does not match the password configured for the PostgreSQL container.
* Fix: Updated the PostgreSQL password in `config/app.env` so the application's `DATABASE_URL` matches the password configured for the PostgreSQL service.
* Retest evidence: After recreating the application containers with the corrected PostgreSQL port and password, `/ready` reported `"postgres":"ready"`. After the Redis port was corrected as well, `/ready` returned HTTP `200 OK` with overall `"status":"ready"`.

* Related commit: Pending.
* Remaining uncertainty: After correcting the port and password, the application's `/ready` endpoint must still be tested to confirm real PostgreSQL and Redis operations succeed.
## Entry 6 / 2026-09-14

* Symptom: The second Flask container is expected to have a distinct backend identity, but its configuration appears to reuse the first backend's identity.
* Hypothesis: `app-02` may be receiving the wrong `INSTANCE_ID` environment variable.
* Command or test:

  * `docker exec app-02 printenv INSTANCE_ID`
* Actual output:

  * The running `app-02` container returned `app-01`.
* Failed attempt and what changed your thinking: No failed attempt was needed for this issue. Inspecting the live container environment directly confirmed the configuration mismatch.
* Root cause: `app-02` is configured with `INSTANCE_ID: "app-01"` instead of its own distinct identity.
* Fix: Changed `app-02` in `docker-compose.yml` from `INSTANCE_ID: "app-01"` to `INSTANCE_ID: "app-02"`.
* Retest evidence: After recreating only `app-02`, `docker exec app-02 printenv INSTANCE_ID` returned `app-02`. Repeated requests to `http://localhost:8080/instance` then returned responses from both `app-01` and `app-02`, proving that both backends serve traffic with distinct identities through NGINX.

* Related commit: Pending.
* Remaining uncertainty: After correcting the identity value, `/instance` still needs to be tested through NGINX repeatedly to prove both backends are serving traffic.
## Entry 7 / 2026-09-14

* Symptom: PostgreSQL is expected to preserve records across container recreation, but the current storage configuration does not attach the named volume to the live PostgreSQL data directory.
* Hypothesis: The PostgreSQL data directory may be using temporary storage instead of the named Docker volume.
* Command or test:

  * `docker inspect postgres --format '{{json .Mounts}}' | jq`
  * `docker inspect postgres --format '{{json .HostConfig.Tmpfs}}' | jq`
* Actual output:

  * The named volume `barq-assessment_postgres-data` is mounted at `/var/lib/postgresql/backup`.
  * `/var/lib/postgresql/data` is configured as a `tmpfs`.
* Failed attempt and what changed your thinking: No failed attempt was required. Inspecting the live container mounts showed that the named volume exists, but it protects the backup directory instead of PostgreSQL's active data directory.
* Root cause: PostgreSQL's live data directory `/var/lib/postgresql/data` is stored on temporary `tmpfs` storage, while the persistent named volume is mounted to `/var/lib/postgresql/backup`.
* Fix: Changed the PostgreSQL named volume mount from `/var/lib/postgresql/backup` to the actual PostgreSQL data directory `/var/lib/postgresql/data` and removed the `tmpfs` mount from `/var/lib/postgresql/data`.
* Retest evidence: `docker inspect postgres` showed the named volume `barq-assessment_postgres-data` mounted read-write at `/var/lib/postgresql/data`. A test record titled `postgres-persistence-test-2026-09-14` was created through `POST /records` and returned HTTP `201 Created` with record ID `3`. After recreating the PostgreSQL container with `docker compose up -d --force-recreate postgres`, PostgreSQL returned to healthy state and `GET /records` still returned the same record, proving that the database persisted across container recreation.

* Related commit: Pending.
* Remaining uncertainty: Basic persistence across PostgreSQL container recreation is confirmed. Backup and restore behavior will be validated separately in the dedicated persistence test.
## Entry 8 / 2026-09-14

* Symptom: Redis-backed state is expected to support persistent application behavior, but the current Redis configuration does not appear to preserve data across container recreation.
* Hypothesis: Redis persistence may be disabled in the running configuration.
* Command or test:

  * `docker exec redis redis-cli CONFIG GET save appendonly`
* Actual output:

  * `save` returned an empty value.
  * `appendonly` returned `no`.
* Failed attempt and what changed your thinking: No failed attempt was required. Inspecting the live Redis configuration directly confirmed that both RDB snapshot persistence and AOF persistence are disabled.
* Root cause: Redis is started with persistence disabled, so Redis-backed counter state may be lost when the container is recreated.
* Fix: Enabled Redis AOF persistence with `--appendonly yes`, added a named volume `redis-data`, and mounted it at Redis's `/data` directory.
* Retest evidence: `docker inspect redis` showed the named volume `barq-assessment_redis-data` mounted read-write at `/data`, and `redis-cli CONFIG GET appendonly` returned `yes`. A request to `/counter` returned `1`; after recreating the Redis container with `docker compose up -d --force-recreate redis`, Redis returned to healthy state and the next `/counter` request returned `2`, proving that the previous counter value persisted across container recreation.

* Related commit: Pending.
* Remaining uncertainty: Basic Redis persistence across container recreation is confirmed. Broader application validation will be handled in the final validation phase.
## Entry 9 / 2026-09-14

* Symptom: PostgreSQL and Redis should be internal-only services, but the runtime configuration exposes both services to host ports.
* Hypothesis: The Compose configuration may be publishing database and cache ports even though the task requires only NGINX to be externally published.
* Command or test:

  * `docker inspect postgres --format '{{json .HostConfig.PortBindings}}' | jq`
  * `docker inspect redis --format '{{json .HostConfig.PortBindings}}' | jq`
* Actual output:

  * PostgreSQL container port `5432` is bound to host `127.0.0.1:15432`.
  * Redis container port `6379` is bound to host `127.0.0.1:16379`.
* Failed attempt and what changed your thinking: `docker compose ps` did not clearly display the host mappings, so the runtime configuration was inspected directly with `docker inspect`.
* Root cause: The Compose configuration publishes PostgreSQL and Redis ports to the host instead of keeping those services accessible only through the Docker backend network.
* Fix: Removed the PostgreSQL and Redis `ports` mappings from `docker-compose.yml`, leaving only NGINX with a published host port.
* Retest evidence: After recreating PostgreSQL, Redis, and NGINX, `docker compose ps` showed NGINX published on `127.0.0.1:8080->80/tcp`, while PostgreSQL showed only `5432/tcp` and Redis only `6379/tcp`, confirming that the database and cache were no longer exposed on host ports.
* Related commit: Pending.
* Remaining uncertainty: Host-port exposure is resolved. Network-level isolation between NGINX and the backend services is verified separately in Entry 10.

## Entry 10 / 2026-09-14

* Symptom: NGINX should be isolated from PostgreSQL and Redis, but the running container appears to share the backend network.
* Hypothesis: NGINX may be attached to both the frontend and backend Docker networks.
* Command or test:

  * `docker inspect nginx --format '{{json .NetworkSettings.Networks}}' | jq`
* Actual output:

  * NGINX is attached to `barq-assessment_frontend`.
  * NGINX is also attached to `barq-assessment_backend`.
* Failed attempt and what changed your thinking: No failed attempt was required. Inspecting the running container network membership directly confirmed that NGINX has backend-network access.
* Root cause: The Compose configuration attaches NGINX to both `frontend` and `backend`, allowing direct network access to PostgreSQL and Redis.
* Fix: Changed the NGINX service network configuration in `docker-compose.yml` from `[frontend, backend]` to `[frontend]`, preventing NGINX from directly joining the backend network.
* Retest evidence: After recreating NGINX, `docker inspect nginx` showed only `barq-assessment_frontend` and no backend network. From inside the NGINX container, `getent hosts postgres` failed and printed `postgres not reachable from nginx`, confirming that NGINX could no longer resolve PostgreSQL directly. A request to `/ready` through NGINX still returned HTTP `200 OK` with both PostgreSQL and Redis reported as `ready`, proving that the Flask application containers still bridge the frontend and backend networks correctly.
* Related commit: Pending.
* Remaining uncertainty: Network isolation is confirmed. The full topology will be rechecked during final validation.

## Entry 11 / 2026-09-14

* Symptom: NGINX is configured with different upstream ports for the two Flask backends even though both applications run on the same internal port.
* Hypothesis: `app-01` may be configured with an incorrect upstream port in the active NGINX configuration.
* Command or test:

  * `docker exec nginx nginx -T 2>&1 | grep -A4 "upstream application_pool"`
* Actual output:

  * The active NGINX configuration contains `server app-01:8081`.
  * The active NGINX configuration contains `server app-02:8080`.
* Failed attempt and what changed your thinking: No additional failed attempt was required. Inspecting the active NGINX configuration directly confirmed that one upstream uses a different port from the Flask application port.
* Root cause: NGINX points `app-01` to port `8081` even though the Flask application listens on port `8080`.
* Fix: Changed the `app-01` NGINX upstream from port `8081` to port `8080` so both Flask backends use their actual application port.
* Retest evidence: `nginx -t` reported the configuration syntax as valid. After reloading NGINX, the upstream error changed from `app-01:8081` to `app-01:8080`, proving the new port was active. After the Flask bind-address fix was also applied, `curl -i http://localhost:8080/` returned HTTP `200 OK`.

* Related commit: Pending.
* Remaining uncertainty: After correcting the upstream port and Flask bind address, repeated requests through NGINX must prove that both backends serve traffic.
