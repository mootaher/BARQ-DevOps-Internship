# Final architecture

Client -> 127.0.0.1:8090 -> NGINX -> app-01/app-02/app-03

## Networks

frontend:
- nginx
- app-01
- app-02
- app-03

backend:
- app-01
- app-02
- app-03
- postgres
- redis

NGINX is intentionally not attached to the backend network.

## Internal services

- app-01:8080
- app-02:8080
- app-03:8080
- postgres:5432
- redis:6379

Only NGINX publishes a host port.

## Health and readiness

- PostgreSQL: pg_isready
- Redis: redis-cli ping
- Flask apps: /health
- NGINX: local /health request through the proxy
- /ready verifies PostgreSQL and Redis
- apps wait for healthy PostgreSQL and Redis
- NGINX waits for healthy app instances

## Persistence

- PostgreSQL named volume -> /var/lib/postgresql/data
- Redis named volume -> /data
- Redis AOF persistence enabled

## Remaining single points of failure

- one NGINX instance
- one PostgreSQL instance
- one Redis instance
- local volumes depend on the Docker host
- local backups do not protect against host failure
