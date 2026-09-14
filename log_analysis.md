# Log analysis

The analysis uses all three supplied historical logs:

* `logs/access.log` — NGINX client-facing requests
* `logs/application.log` — application HTTP and dependency events
* `logs/error.log` — NGINX diagnostic events

The original log files were treated as read-only evidence. Analysis is reproducible with:

```bash
python3 scripts/analyze_logs.py
```

## Commands / scripts

The main reproducible analysis is implemented in:

```text
scripts/analyze_logs.py
```

It:

* parses the JSON-line access and application logs
* separately validates NGINX diagnostic text
* excludes malformed records
* detects exact duplicate log lines
* deduplicates client requests using `request_id`
* treats comma-separated upstream values as attempts within one client request
* correlates access, application and NGINX error records using `request_id`
* calculates status counts and error rates
* calculates latency percentiles using the nearest-rank method
* identifies upstream retries
* maps historical upstream addresses to application instances using correlated requests
* produces the incident timeline and failure classification
* prints SHA-256 hashes of all three logs to verify evidence integrity

Initial and final SHA-256 values were:

```text
f8562d6ee86b7e7aa67e8c3474ca16eca8a1e5f521f78f3808d784be62efa754  logs/access.log
483d06cf431faa1d04a7264b015798bcde4bed1ba618f87426e79fb0d5caea05  logs/application.log
940588d00bafd6c5c7cad8a4d8a0c39b665d1fd64928d93a5d1f1810c3c6f175  logs/error.log
```

The hashes were unchanged after analysis.

## Results

### 1. UTC interval, valid lines, malformed lines and duplicates

The combined evidence covers:

```text
2026-08-20T11:00:00.015Z
through
2026-08-20T11:30:00Z
```

Per-file coverage:

```text
access.log:
2026-08-20T11:00:00.015Z -> 2026-08-20T11:29:57.578Z

application.log:
2026-08-20T11:00:00.015Z -> 2026-08-20T11:29:57.578Z

error.log:
2026-08-20T11:05:02Z -> 2026-08-20T11:30:00Z
```

Line counts:

| File              | Total | Valid | Malformed | Exact duplicate extra lines |
| ----------------- | ----: | ----: | --------: | --------------------------: |
| `access.log`      |   726 |   725 |         1 |                           5 |
| `application.log` |   730 |   729 |         1 |                           2 |
| `error.log`       |    68 |    68 |         0 |                           0 |

Excluded malformed records:

```text
access.log line 311:
{"timestamp":"2026-08-20T11:12:48Z","request_id":

application.log line 401:
{"timestamp":"2026-08-20T11:17:00Z","event":
```

The final `[notice]` entry in `error.log` was treated as valid NGINX diagnostic text rather than malformed merely because it does not contain a request ID.

### 2. Distinct client requests and deduplication

`access.log` is the authoritative client-facing request source.

There were:

```text
725 valid access records
720 distinct request_id values
5 repeated request_id values
5 extra duplicate records
0 conflicting repeated request IDs
```

Therefore:

```text
Distinct client requests = 720
```

Deduplication was performed by `request_id`.

Exact duplicate access records were collapsed to one request.

Comma-separated `upstream` and `upstream_status` values were **not** treated as separate client requests. They represent multiple upstream attempts performed while servicing one client request.

For example:

```text
upstream='172.23.0.12:8080, 172.23.0.11:8080'
upstream_status='502, 200'
```

is one client request with two upstream attempts.

### 3. Final client status counts and error rate

After request deduplication:

```text
200 = 615
404 = 10
502 = 40
503 = 47
504 = 8
```

Denominator:

```text
720 distinct client requests
```

Server/proxy failures:

```text
5xx responses = 95
5xx error rate = 95 / 720 = 13.19%
```

Including all non-2xx responses:

```text
non-2xx responses = 105
non-2xx rate = 14.58%
```

The primary incident error rate used here is the **5xx rate of 13.19%**, because the ten `404` responses are client-visible non-success responses but are not evidence of the investigated server/proxy incidents.

### 4. Failure paths, time windows and backends

Correlation between access and application records establishes:

```text
172.23.0.11:8080 -> app-01
172.23.0.12:8080 -> app-02
```

This mapping is based on hundreds of single-upstream records sharing the same `request_id`, not on an assumed IP assignment.

Failure counts by path and final status:

```text
/            502 = 10
/counter     502 = 10
/counter     503 = 16
/health      502 = 10
/ready       503 = 23
/records     502 = 10
/records     503 = 8
/records     504 = 8
```

Failure counts by backend:

```text
app-01:
503 = 23
504 = 4

app-02:
502 = 40
503 = 24
504 = 4
```

All 40 final `502` responses were associated with `app-02`.

The failures form four separate historical incident windows:

```text
11:05:02–11:09:57 UTC
NGINX upstream connection refusals

11:12:09.524–11:15:52.024 UTC
Redis TimeoutError dependency failures

11:20:07.540–11:21:45.040 UTC
PostgreSQL InvalidPassword dependency failures

11:25:14–11:26:47 UTC
NGINX upstream response timeouts
```

### 5. Median and p95 client latency

Latency was calculated from the deduplicated client-facing NGINX `request_time` field.

`request_time` is measured in seconds.

Sample:

```text
720 distinct client requests
```

Percentile method:

```text
nearest-rank
```

Results:

```text
median = 0.054 seconds = 54 ms
p95    = 2.001 seconds = 2001 ms
```

### 6. Upstream retries

A request was classified as retried when its `upstream` or `upstream_status` field contained multiple comma-separated attempts.

Results:

```text
retried client requests = 19
succeeded after retry = 19
failed after retry = 0
```

Every observed retry followed this pattern:

```text
first upstream: app-02
first result: 502

retry upstream: app-01
retry result: 200

final client status: 200
```

Therefore the upstream retry mechanism prevented 19 additional client-visible failures during the connection-refusal incident.

## Timeline and correlated examples

### Incident timeline

#### 11:00 UTC — normal traffic begins

Both the access and application logs begin at approximately:

```text
2026-08-20T11:00:00.015Z
```

Normal successful traffic is present before the first incident.

#### 11:05:02–11:09:57 UTC — app-02 connection-refusal incident

NGINX recorded:

```text
59 connect() failed (111: Connection refused)
```

All attempted connections were directed to the historical upstream corresponding to `app-02`.

Of these 59 connection failures:

```text
19 were recovered through upstream retry -> final 200
40 remained client-visible -> final 502
```

All 40 final `502` requests lack a corresponding application HTTP record, supporting the conclusion that those requests never reached the Flask process.

#### 11:12:09.524–11:15:52.024 UTC — Redis dependency incident

Application logs contain:

```text
31 redis TimeoutError dependency_error events
```

Distribution:

```text
app-01 = 15
app-02 = 16
```

These contribute to final `503` responses.

#### 11:20:07.540–11:21:45.040 UTC — PostgreSQL credential incident

Application logs contain:

```text
16 postgres InvalidPassword dependency_error events
```

Distribution:

```text
app-01 = 8
app-02 = 8
```

These also contribute to final `503` responses.

Across both dependency incidents:

```text
47 final 503 responses
47 matching dependency_error events
0 unmatched final 503 responses
```

#### 11:25:14–11:26:47 UTC — slow-backend / proxy-timeout incident

NGINX recorded:

```text
8 upstream timed out while reading response header
```

All eight affected `/records`.

For all eight requests:

```text
NGINX/client status = 504
NGINX request_time = 2.001 seconds

application status = 200
application duration = 2700 ms
```

The application therefore completed each request after NGINX had already reached its upstream timeout and sent `504` to the client.

### Correlated failed request

Request:

```text
request_id = lab-000292
```

NGINX access evidence:

```text
timestamp = 2026-08-20T11:12:09.525Z
path = /ready
status = 503
upstream = 172.23.0.12:8080
request_time = 2.025 seconds
```

Application dependency evidence:

```text
timestamp = 2026-08-20T11:12:09.524Z
instance_id = app-02
dependency = redis
error_type = TimeoutError
```

Application HTTP evidence:

```text
timestamp = 2026-08-20T11:12:09.525Z
instance_id = app-02
status = 503
duration_ms = 2025
```

There is no matching NGINX proxy diagnostic error for this request.

This supports classification as an application/dependency failure rather than inability by NGINX to reach the backend.

### Correlated successful request

Request:

```text
request_id = lab-000124
```

NGINX initially recorded:

```text
2026/08/20 11:05:07
connect() failed (111: Connection refused)
upstream = 172.23.0.12:8080
```

The access record shows:

```text
upstream =
172.23.0.12:8080, 172.23.0.11:8080

upstream_status =
502, 200

final client status =
200
```

The application record shows:

```text
instance_id = app-01
status = 200
timestamp = 2026-08-20T11:05:07.620Z
```

This provides evidence across all three logs:

```text
error.log:
first upstream connection failed

application.log:
retry reached app-01 successfully

access.log:
client ultimately received HTTP 200
```

## Conclusions and limits

### Proxy/connectivity failures

The `502` failures are best classified as proxy-to-backend connectivity failures.

Evidence:

```text
59 NGINX connection-refused events
19 recovered after retry and returned 200
40 became final 502 responses
40/40 final 502 requests have no application HTTP record
all final 502 responses were associated with app-02
```

The logs therefore support that NGINX could not connect to the historical app-02 upstream during that window.

They do **not** prove why the connection was refused.

Possible causes requiring live-environment investigation include process availability, startup state, bind configuration, container networking or another backend-specific runtime condition.

### Dependency/application failures

The `503` failures are application/dependency failures.

Evidence:

```text
47 final 503 requests
47 matching dependency_error events
0 unmatched 503 requests
```

Breakdown:

```text
Redis TimeoutError:
app-01 = 15
app-02 = 16
total = 31

PostgreSQL InvalidPassword:
app-01 = 8
app-02 = 8
total = 16
```

The logs prove what dependency errors the application observed, but not the deeper reason Redis timed out or how the incorrect PostgreSQL credential entered runtime configuration.

### Proxy timeout / slow-backend failures

The `504` failures are proxy timeout failures caused by slow application responses.

Evidence:

```text
8 NGINX upstream timeout events
8 final client 504 responses
8 matching application requests later returned 200
NGINX timeout occurred at approximately 2.001 seconds
application completion occurred at 2700 ms
```

This proves NGINX stopped waiting before the application completed.

It does not prove why `/records` took 2700 ms.

### What the historical logs do not prove

The logs do not establish:

* why app-02 refused connections
* the internal cause of the Redis timeouts
* how the PostgreSQL credential became incorrect
* why `/records` took 2700 ms
* host-level resource usage during the historical incidents
* whether the historical issues still exist in the current repaired environment

The logs describe historical incidents and should not be treated as evidence that every historical condition remains present now.

### What should be checked next in the running environment

Current-environment investigation should include:

```text
docker compose ps
container health status
current application and NGINX logs
PostgreSQL and Redis runtime logs
container network membership
backend DNS/reachability
runtime configuration and secret injection
PostgreSQL connectivity from an app container
Redis connectivity from an app container
NGINX upstream timeout configuration
container CPU/memory behavior
current endpoint latency
controlled backend failure and recovery behavior
```

These checks should be performed with bounded waits, reproducible commands and controlled failure tests rather than assuming the historical causes remain active.
