#!/usr/bin/env python3

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ACCESS_LOG = Path("logs/access.log")
APPLICATION_LOG = Path("logs/application.log")
ERROR_LOG = Path("logs/error.log")


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)

    return h.hexdigest()


def load_json_log(path):
    valid = []
    malformed = []

    with path.open() as f:
        for line_number, line in enumerate(f, 1):
            raw = line.rstrip("\n")

            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                malformed.append(
                    (line_number, raw, exc.msg)
                )
                continue

            valid.append(
                (line_number, raw, record)
            )

    return valid, malformed


def load_error_log(path):
    pattern = re.compile(
        r"^(?P<timestamp>\d{4}/\d{2}/\d{2} "
        r"\d{2}:\d{2}:\d{2}) "
        r"\[(?P<level>[a-z]+)\] "
        r"\d+#\d+: .+$"
    )

    valid = []
    malformed = []

    with path.open() as f:
        for line_number, line in enumerate(f, 1):
            raw = line.rstrip("\n")
            match = pattern.match(raw)

            if not match:
                malformed.append(
                    (line_number, raw, "invalid structure")
                )
                continue

            try:
                timestamp = datetime.strptime(
                    match.group("timestamp"),
                    "%Y/%m/%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                malformed.append(
                    (line_number, raw, "invalid timestamp")
                )
                continue

            valid.append(
                {
                    "line": line_number,
                    "raw": raw,
                    "timestamp": timestamp,
                    "level": match.group("level"),
                }
            )

    return valid, malformed


def exact_duplicate_stats(raw_lines):
    counts = Counter(raw_lines)

    duplicate_unique = sum(
        1 for count in counts.values()
        if count > 1
    )

    duplicate_extra = sum(
        count - 1
        for count in counts.values()
        if count > 1
    )

    return duplicate_unique, duplicate_extra


def split_csv(value):
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    ]


def nearest_rank(values, percentile):
    values = sorted(values)
    rank = math.ceil(
        percentile / 100 * len(values)
    )

    return values[rank - 1]


def request_id_from_error(line):
    match = re.search(
        r"request_id=([^,\s]+)",
        line,
    )

    if match:
        return match.group(1)

    return None


def heading(number, title):
    print()
    print("=" * 72)
    print(f"Q{number}. {title}")
    print("=" * 72)


def main():
    access_valid, access_malformed = load_json_log(
        ACCESS_LOG
    )

    app_valid, app_malformed = load_json_log(
        APPLICATION_LOG
    )

    error_valid, error_malformed = load_error_log(
        ERROR_LOG
    )

    access_records = [
        record
        for _, _, record in access_valid
    ]

    app_records = [
        record
        for _, _, record in app_valid
    ]

    # ---------------------------------------------------------
    # Indexes
    # ---------------------------------------------------------

    access_by_id = {}

    repeated_ids = Counter()
    conflicting_ids = []

    for record in access_records:
        request_id = record.get("request_id")

        if request_id is None:
            continue

        if request_id in access_by_id:
            repeated_ids[request_id] += 1

            if record != access_by_id[request_id]:
                conflicting_ids.append(request_id)

            continue

        access_by_id[request_id] = record

    app_http_by_id = {}
    dependency_by_id = {}
    app_events_by_id = defaultdict(list)

    for record in app_records:
        request_id = record.get("request_id")

        if request_id:
            app_events_by_id[request_id].append(
                record
            )

        if (
            record.get("event") == "http_request"
            and request_id
        ):
            app_http_by_id.setdefault(
                request_id,
                record,
            )

        if (
            record.get("event") == "dependency_error"
            and request_id
        ):
            dependency_by_id[request_id] = record

    errors_by_id = defaultdict(list)

    for item in error_valid:
        request_id = request_id_from_error(
            item["raw"]
        )

        if request_id:
            errors_by_id[request_id].append(
                item
            )

    # ---------------------------------------------------------
    # Q1
    # ---------------------------------------------------------

    heading(
        1,
        "UTC interval and log-line validity",
    )

    access_dup_unique, access_dup_extra = (
        exact_duplicate_stats(
            raw
            for _, raw, _ in access_valid
        )
    )

    app_dup_unique, app_dup_extra = (
        exact_duplicate_stats(
            raw
            for _, raw, _ in app_valid
        )
    )

    error_dup_unique, error_dup_extra = (
        exact_duplicate_stats(
            item["raw"]
            for item in error_valid
        )
    )

    print(
        f"access.log total="
        f"{len(access_valid) + len(access_malformed)} "
        f"valid={len(access_valid)} "
        f"malformed={len(access_malformed)} "
        f"duplicate_unique={access_dup_unique} "
        f"duplicate_extra={access_dup_extra}"
    )

    print(
        f"application.log total="
        f"{len(app_valid) + len(app_malformed)} "
        f"valid={len(app_valid)} "
        f"malformed={len(app_malformed)} "
        f"duplicate_unique={app_dup_unique} "
        f"duplicate_extra={app_dup_extra}"
    )

    print(
        f"error.log total="
        f"{len(error_valid) + len(error_malformed)} "
        f"valid={len(error_valid)} "
        f"malformed={len(error_malformed)} "
        f"duplicate_unique={error_dup_unique} "
        f"duplicate_extra={error_dup_extra}"
    )

    print()
    print("Malformed/excluded lines:")

    for line, raw, reason in access_malformed:
        print(
            f"access.log line {line}: "
            f"{reason}: {raw}"
        )

    for line, raw, reason in app_malformed:
        print(
            f"application.log line {line}: "
            f"{reason}: {raw}"
        )

    for line, raw, reason in error_malformed:
        print(
            f"error.log line {line}: "
            f"{reason}: {raw}"
        )

    access_times = [
        parse_iso(record["timestamp"])
        for record in access_records
    ]

    app_times = [
        parse_iso(record["timestamp"])
        for record in app_records
    ]

    error_times = [
        item["timestamp"]
        for item in error_valid
    ]

    print()
    print(
        "access.log UTC: "
        f"{min(access_times).isoformat()} -> "
        f"{max(access_times).isoformat()}"
    )

    print(
        "application.log UTC: "
        f"{min(app_times).isoformat()} -> "
        f"{max(app_times).isoformat()}"
    )

    print(
        "error.log UTC: "
        f"{min(error_times).isoformat()} -> "
        f"{max(error_times).isoformat()}"
    )

    print(
        "overall UTC: "
        f"{min(access_times + app_times + error_times).isoformat()} "
        "-> "
        f"{max(access_times + app_times + error_times).isoformat()}"
    )

    # ---------------------------------------------------------
    # Q2
    # ---------------------------------------------------------

    heading(
        2,
        "Distinct client requests",
    )

    print(
        f"valid access records="
        f"{len(access_records)}"
    )

    print(
        f"distinct request_ids="
        f"{len(access_by_id)}"
    )

    print(
        f"repeated request_ids="
        f"{len(repeated_ids)}"
    )

    print(
        "extra duplicate records="
        f"{sum(repeated_ids.values())}"
    )

    print(
        "conflicting repeated request_ids="
        f"{len(set(conflicting_ids))}"
    )

    print(
        "Deduplication method: "
        "access.log is the client-facing source; "
        "one client request is counted per request_id. "
        "Comma-separated upstream values are retry "
        "attempts within that one request."
    )

    # ---------------------------------------------------------
    # Q3
    # ---------------------------------------------------------

    heading(
        3,
        "Final client status counts and error rate",
    )

    status_counts = Counter(
        int(record["status"])
        for record in access_by_id.values()
    )

    total_requests = len(access_by_id)

    for status, count in sorted(
        status_counts.items()
    ):
        print(
            f"status {status}: {count}"
        )

    errors_5xx = sum(
        count
        for status, count
        in status_counts.items()
        if 500 <= status < 600
    )

    non_2xx = sum(
        count
        for status, count
        in status_counts.items()
        if not 200 <= status < 300
    )

    print(
        f"denominator={total_requests} "
        "distinct client requests"
    )

    print(
        f"5xx errors={errors_5xx}"
    )

    print(
        "5xx error rate="
        f"{errors_5xx / total_requests * 100:.2f}%"
    )

    print(
        f"non-2xx responses={non_2xx}"
    )

    print(
        "non-2xx rate="
        f"{non_2xx / total_requests * 100:.2f}%"
    )

    # ---------------------------------------------------------
    # Map upstream -> instance
    # ---------------------------------------------------------

    mapping = Counter()

    for request_id, access in access_by_id.items():
        app = app_http_by_id.get(request_id)

        if not app:
            continue

        upstreams = split_csv(
            access.get("upstream")
        )

        if len(upstreams) == 1:
            mapping[
                (
                    upstreams[0],
                    app.get("instance_id"),
                )
            ] += 1

    backend_map = {}

    for (
        upstream,
        instance,
    ), count in mapping.items():

        existing = [
            (
                existing_count,
                existing_instance,
            )
            for (
                existing_upstream,
                existing_instance,
            ), existing_count
            in mapping.items()
            if existing_upstream == upstream
        ]

        backend_map[upstream] = max(
            existing
        )[1]

    # ---------------------------------------------------------
    # Q4
    # ---------------------------------------------------------

    heading(
        4,
        "Failure paths, windows and backends",
    )

    print("Upstream mapping:")

    for (
        upstream,
        instance,
    ), count in sorted(mapping.items()):
        print(
            f"{upstream} -> "
            f"{instance}: "
            f"{count} correlated requests"
        )

    failures = [
        record
        for record in access_by_id.values()
        if 500 <= int(record["status"]) < 600
    ]

    print()
    print("Failures by path/status:")

    path_counts = Counter(
        (
            record["path"],
            int(record["status"]),
        )
        for record in failures
    )

    for (
        path,
        status,
    ), count in sorted(
        path_counts.items()
    ):
        print(
            f"{path:12} "
            f"status={status} "
            f"count={count}"
        )

    print()
    print("Failures by backend/status:")

    backend_counts = Counter()

    for record in failures:
        upstreams = split_csv(
            record.get("upstream")
        )

        final_upstream = (
            upstreams[-1]
            if upstreams
            else "<missing>"
        )

        backend = backend_map.get(
            final_upstream,
            final_upstream,
        )

        backend_counts[
            (
                backend,
                int(record["status"]),
            )
        ] += 1

    for (
        backend,
        status,
    ), count in sorted(
        backend_counts.items()
    ):
        print(
            f"{backend:12} "
            f"status={status} "
            f"count={count}"
        )

    failure_minutes = Counter(
        (
            record["timestamp"][:16],
            int(record["status"]),
        )
        for record in failures
    )

    print()
    print("Failures by UTC minute/status:")

    for (
        minute,
        status,
    ), count in sorted(
        failure_minutes.items()
    ):
        print(
            f"{minute}Z "
            f"status={status} "
            f"count={count}"
        )

    # ---------------------------------------------------------
    # Q5
    # ---------------------------------------------------------

    heading(
        5,
        "Client latency",
    )

    latencies = [
        float(record["request_time"])
        for record in access_by_id.values()
    ]

    median = nearest_rank(
        latencies,
        50,
    )

    p95 = nearest_rank(
        latencies,
        95,
    )

    print(
        f"sample_count={len(latencies)}"
    )

    print(
        "source=access.log request_time"
    )

    print(
        "percentile_method=nearest-rank"
    )

    print(
        f"median={median:.3f}s "
        f"({median * 1000:.1f}ms)"
    )

    print(
        f"p95={p95:.3f}s "
        f"({p95 * 1000:.1f}ms)"
    )

    # ---------------------------------------------------------
    # Q6
    # ---------------------------------------------------------

    heading(
        6,
        "Upstream retries",
    )

    retried = []

    for record in access_by_id.values():

        upstreams = split_csv(
            record.get("upstream")
        )

        upstream_statuses = split_csv(
            record.get("upstream_status")
        )

        if (
            len(upstreams) > 1
            or len(upstream_statuses) > 1
        ):
            retried.append(record)

    retried.sort(
        key=lambda record:
        parse_iso(record["timestamp"])
    )

    succeeded_after_retry = [
        record
        for record in retried
        if 200 <= int(record["status"]) < 300
    ]

    print(
        f"retried_client_requests="
        f"{len(retried)}"
    )

    print(
        f"succeeded_after_retry="
        f"{len(succeeded_after_retry)}"
    )

    print(
        "failed_after_retry="
        f"{len(retried) - len(succeeded_after_retry)}"
    )

    for record in retried:
        print(
            f"{record['request_id']} "
            f"{record['timestamp']} "
            f"path={record['path']} "
            f"upstream={record['upstream']!r} "
            f"upstream_status="
            f"{record['upstream_status']!r} "
            f"final_status={record['status']}"
        )

    # ---------------------------------------------------------
    # Q7
    # ---------------------------------------------------------

    heading(
        7,
        "Incident timeline",
    )

    connect_refused = [
        item
        for item in error_valid
        if "connect() failed" in item["raw"]
    ]

    upstream_timeouts = [
        item
        for item in error_valid
        if "upstream timed out" in item["raw"]
    ]

    redis_errors = [
        record
        for record in app_records
        if (
            record.get("event")
            == "dependency_error"
            and record.get("dependency")
            == "redis"
            and record.get("error_type")
            == "TimeoutError"
        )
    ]

    postgres_errors = [
        record
        for record in app_records
        if (
            record.get("event")
            == "dependency_error"
            and record.get("dependency")
            == "postgres"
            and record.get("error_type")
            == "InvalidPassword"
        )
    ]

    def error_window(name, items):
        timestamps = [
            item["timestamp"]
            for item in items
        ]

        print(
            f"{name}: "
            f"count={len(items)} "
            f"first={min(timestamps).isoformat()} "
            f"last={max(timestamps).isoformat()}"
        )

    def app_window(name, records):
        timestamps = [
            parse_iso(record["timestamp"])
            for record in records
        ]

        print(
            f"{name}: "
            f"count={len(records)} "
            f"first={min(timestamps).isoformat()} "
            f"last={max(timestamps).isoformat()}"
        )

    error_window(
        "NGINX connection refused",
        connect_refused,
    )

    app_window(
        "Redis TimeoutError",
        redis_errors,
    )

    app_window(
        "PostgreSQL InvalidPassword",
        postgres_errors,
    )

    error_window(
        "NGINX upstream timeout",
        upstream_timeouts,
    )

    # ---------------------------------------------------------
    # Q8
    # ---------------------------------------------------------

    heading(
        8,
        "Correlated failed and successful requests",
    )

    failed_example = None

    for record in sorted(
        access_by_id.values(),
        key=lambda item:
        parse_iso(item["timestamp"]),
    ):
        request_id = record["request_id"]

        if (
            int(record["status"]) == 503
            and request_id in dependency_by_id
            and request_id in app_http_by_id
        ):
            failed_example = record
            break

    print("FAILED EXAMPLE")

    if failed_example:
        request_id = failed_example[
            "request_id"
        ]

        print(
            "access:",
            json.dumps(
                failed_example,
                sort_keys=True,
            ),
        )

        for event in app_events_by_id[
            request_id
        ]:
            print(
                "application:",
                json.dumps(
                    event,
                    sort_keys=True,
                ),
            )

        print(
            "nginx error records:",
            len(
                errors_by_id.get(
                    request_id,
                    [],
                )
            ),
        )

    successful_example = None

    for record in retried:
        request_id = record["request_id"]

        if (
            200 <= int(record["status"]) < 300
            and request_id in app_http_by_id
            and request_id in errors_by_id
        ):
            successful_example = record
            break

    print()
    print("SUCCESSFUL RETRY EXAMPLE")

    if successful_example:
        request_id = successful_example[
            "request_id"
        ]

        print(
            "access:",
            json.dumps(
                successful_example,
                sort_keys=True,
            ),
        )

        for event in app_events_by_id[
            request_id
        ]:
            print(
                "application:",
                json.dumps(
                    event,
                    sort_keys=True,
                ),
            )

        for event in errors_by_id[
            request_id
        ]:
            print(
                "nginx error:",
                event["raw"],
            )

    # ---------------------------------------------------------
    # Q9
    # ---------------------------------------------------------

    heading(
        9,
        "Failure classification",
    )

    connect_ids = {
        request_id_from_error(
            item["raw"]
        )
        for item in connect_refused
    }

    connect_ids.discard(None)

    connect_final_statuses = Counter(
        int(
            access_by_id[request_id][
                "status"
            ]
        )
        for request_id in connect_ids
        if request_id in access_by_id
    )

    print(
        "NGINX connection-refused events="
        f"{len(connect_refused)}"
    )

    for status, count in sorted(
        connect_final_statuses.items()
    ):
        print(
            f"connection-refused final "
            f"status {status}: {count}"
        )

    final_502 = [
        record
        for record in access_by_id.values()
        if int(record["status"]) == 502
    ]

    final_502_without_app = sum(
        1
        for record in final_502
        if record["request_id"]
        not in app_http_by_id
    )

    print(
        f"final 502 requests="
        f"{len(final_502)}"
    )

    print(
        "final 502 without app HTTP record="
        f"{final_502_without_app}"
    )

    final_503 = [
        record
        for record in access_by_id.values()
        if int(record["status"]) == 503
    ]

    matched_503 = sum(
        1
        for record in final_503
        if record["request_id"]
        in dependency_by_id
    )

    print()
    print(
        f"final 503 requests="
        f"{len(final_503)}"
    )

    print(
        "503 with matching dependency_error="
        f"{matched_503}"
    )

    print(
        "503 without matching dependency_error="
        f"{len(final_503) - matched_503}"
    )

    dependency_breakdown = Counter(
        (
            record.get("dependency"),
            record.get("error_type"),
            record.get("instance_id"),
        )
        for record
        in dependency_by_id.values()
    )

    for (
        dependency,
        error_type,
        instance,
    ), count in sorted(
        dependency_breakdown.items()
    ):
        print(
            f"{dependency} "
            f"{error_type} "
            f"{instance}: "
            f"{count}"
        )

    timeout_ids = {
        request_id_from_error(
            item["raw"]
        )
        for item in upstream_timeouts
    }

    timeout_ids.discard(None)

    late_200 = 0

    for request_id in timeout_ids:

        access = access_by_id.get(
            request_id
        )

        app = app_http_by_id.get(
            request_id
        )

        if not access or not app:
            continue

        if (
            int(access["status"]) == 504
            and int(app["status"]) == 200
            and float(app["duration_ms"])
            > float(
                access["request_time"]
            ) * 1000
        ):
            late_200 += 1

    print()
    print(
        "NGINX upstream timeout events="
        f"{len(upstream_timeouts)}"
    )

    print(
        "504 requests followed by late "
        f"application 200={late_200}"
    )

    print()
    print(
        "Classification:"
    )

    print(
        "- 502 = proxy/backend connectivity: "
        "NGINX connection refused and no app "
        "HTTP record for the final failures."
    )

    print(
        "- 503 = application/dependency: "
        "every final 503 has a matching "
        "dependency_error."
    )

    print(
        "- 504 = proxy timeout caused by slow "
        "backend response: NGINX times out "
        "before the app later returns 200."
    )

    # ---------------------------------------------------------
    # Q10
    # ---------------------------------------------------------

    heading(
        10,
        "Limits of the historical evidence",
    )

    print(
        "The logs do NOT prove:"
    )

    print(
        "- the root cause of app-02 refusing "
        "connections"
    )

    print(
        "- the internal reason Redis timed out"
    )

    print(
        "- how the PostgreSQL password became "
        "incorrect"
    )

    print(
        "- why /records took 2700 ms during "
        "the timeout incident"
    )

    print(
        "- whether these historical failures "
        "still exist in the current environment"
    )

    print()
    print(
        "Next checks in a running environment:"
    )

    print(
        "- docker compose ps and health status"
    )

    print(
        "- application, NGINX, PostgreSQL and "
        "Redis runtime logs"
    )

    print(
        "- network membership and backend "
        "reachability"
    )

    print(
        "- runtime secret/config injection "
        "without printing secrets"
    )

    print(
        "- PostgreSQL and Redis connectivity "
        "from app containers"
    )

    print(
        "- NGINX upstream timeout settings"
    )

    print(
        "- CPU/memory pressure and application "
        "latency"
    )

    print(
        "- bounded validation and controlled "
        "failure testing"
    )

    # ---------------------------------------------------------
    # Integrity
    # ---------------------------------------------------------

    print()
    print("=" * 72)
    print("LOG SHA-256")
    print("=" * 72)

    for path in (
        ACCESS_LOG,
        APPLICATION_LOG,
        ERROR_LOG,
    ):
        print(
            f"{sha256(path)}  {path}"
        )


if __name__ == "__main__":
    main()
