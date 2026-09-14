# Evidence and submission index

- Repository URL: https://github.com/mootaher/BARQ-DevOps-Internship
- Final implementation commit shown in video: `75a6fba` — `feat: complete live challenge architecture`
- Matching CI run: PENDING final documentation push
- Continuous 12-18 minute video URL: PENDING video upload
- Challenge receipt ID: `ac9dcb02bb4c4b058fb63f2deaf8f5c8`
- Starting video commit: `edda7db` — `docs: disclose AI-assisted work and verification`
- Post-video finalization commits: documentation/diagram updates plus CI port alignment to `8090`; no runtime architecture change after `75a6fba`

## Video evidence

The continuous recording demonstrates:

1. Clean starting Git state at `edda7db`.
2. Environment build and startup.
3. Public endpoints through NGINX.
4. Traffic served by multiple Flask backends.
5. Controlled backend failure and recovery.
6. PostgreSQL persistence across container recreation.
7. `validate.py`.
8. Historical log analysis.
9. Challenge preflight diagnosis: NGINX lacked a Docker healthcheck.
10. Successful challenge application after repairing preflight health.
11. Runtime challenge diagnosis: `app-02` disconnected from the frontend network.
12. Live repair without `docker compose down`.
13. Final public port changed to `8090`.
14. Addition of `app-03`.
15. All three application instances serving traffic.
16. Final validation, Git diff/status, commit, and push.

## Final architecture consistency

The final repository documentation, Compose configuration, NGINX configuration,
architecture diagram, and implementation commit describe:

- three Flask instances: `app-01`, `app-02`, `app-03`
- NGINX as the only host-facing service
- public port `8090`
- PostgreSQL and Redis isolated on the backend network
- persistent PostgreSQL and Redis storage
- Docker healthchecks and readiness behavior

The exact final GitHub Actions run URL and continuous video URL are added after
the final documentation push and video upload.
