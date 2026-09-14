#!/usr/bin/env python3
"""
BARQ controlled backend failure/recovery test.

The test:
1. Discovers the configured app services and NGINX public port.
2. Proves all configured backends are serving before the test.
3. Stops exactly one backend.
4. Sends bounded traffic through NGINX and measures successes/errors.
5. Proves the remaining backend(s) still provide availability.
6. Always restores the selected backend.
7. Waits for health recovery.
8. Proves the recovered backend serves traffic again.

It never uses `docker compose down`.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent

HTTP_TIMEOUT = 3
BASELINE_ATTEMPTS = 30
FAILURE_REQUESTS = 30
RECOVERY_ATTEMPTS = 60
RECOVERY_TIMEOUT = 45
REQUEST_INTERVAL = 0.10


def passed(message):
    print(f"PASS: {message}")


def failed(message):
    print(f"FAIL: {message}")


def run(command, timeout=20):
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


def compose(*args, timeout=20):
    return run(
        ["docker", "compose", *args],
        timeout=timeout,
    )


def discover_services():
    result = compose("config", "--services")

    if result is None or result.returncode != 0:
        return None

    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def discover_public_url():
    result = compose("port", "nginx", "80")

    if result is None or result.returncode != 0:
        return None

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if not lines:
        return None

    try:
        port = int(lines[0].rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return None

    return f"http://127.0.0.1:{port}"


def http_get(base_url, path):
    request = urllib.request.Request(
        base_url + path,
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=HTTP_TIMEOUT,
        ) as response:
            raw = response.read().decode(
                "utf-8",
                errors="replace",
            )

            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = None

            return response.status, body

    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            body = json.loads(raw)
        except Exception:
            body = None

        return exc.code, body

    except (
        urllib.error.URLError,
        TimeoutError,
    ):
        return None, None


def container_id(service):
    result = compose(
        "ps",
        "-q",
        "--all",
        service,
    )

    if result is None or result.returncode != 0:
        return None

    value = result.stdout.strip()
    return value or None


def container_state(service):
    cid = container_id(service)

    if not cid:
        return None

    result = run(
        ["docker", "inspect", cid],
    )

    if result is None or result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return None

    state = data.get("State", {})

    return {
        "status": state.get("Status"),
        "health": (
            state
            .get("Health", {})
            .get("Status")
        ),
    }


def wait_for_healthy(service):
    deadline = time.monotonic() + RECOVERY_TIMEOUT

    while time.monotonic() < deadline:
        state = container_state(service)

        if state:
            running = state.get("status") == "running"
            health = state.get("health")

            if running and (
                health is None
                or health == "healthy"
            ):
                return True

        time.sleep(1)

    return False


def collect_instances(
    base_url,
    attempts,
    stop_when=None,
):
    seen = set()
    status_counts = Counter()

    for _ in range(attempts):
        status, body = http_get(
            base_url,
            "/instance",
        )

        status_key = (
            str(status)
            if status is not None
            else "connection_error"
        )

        status_counts[status_key] += 1

        if (
            status == 200
            and isinstance(body, dict)
        ):
            instance = body.get("instance_id")

            if instance:
                seen.add(instance)

        if (
            stop_when
            and stop_when.issubset(seen)
        ):
            break

        time.sleep(REQUEST_INTERVAL)

    return seen, status_counts


def main():
    print("BARQ backend failure/recovery test")
    print("=" * 72)

    services = discover_services()

    if services is None:
        failed("could not discover Compose services")
        return 1

    app_services = sorted(
        service
        for service in services
        if service.startswith("app-")
    )

    if len(app_services) < 2:
        failed(
            "at least two app services are required"
        )
        return 1

    passed(
        "configured app services: "
        + ", ".join(app_services)
    )

    base_url = discover_public_url()

    if base_url is None:
        failed(
            "could not discover NGINX public endpoint"
        )
        return 1

    passed(
        f"NGINX public endpoint: {base_url}"
    )

    # ---------------------------------------------------------
    # Baseline
    # ---------------------------------------------------------

    expected_instances = set(app_services)

    baseline_seen, baseline_statuses = collect_instances(
        base_url,
        BASELINE_ATTEMPTS,
        stop_when=expected_instances,
    )

    print()
    print("Baseline traffic:")
    print(
        "  statuses="
        + json.dumps(
            dict(baseline_statuses),
            sort_keys=True,
        )
    )
    print(
        "  instances="
        + (
            ", ".join(sorted(baseline_seen))
            if baseline_seen
            else "<none>"
        )
    )

    missing = expected_instances - baseline_seen

    if missing:
        failed(
            "baseline did not observe all backends: "
            + ", ".join(sorted(missing))
        )
        return 1

    passed(
        "all configured backends served "
        "before failure injection"
    )

    # Deterministic target:
    # - with app-01/app-02 => app-02
    # - after app-03 is added => app-03
    target = app_services[-1]

    survivors = expected_instances - {target}

    state = container_state(target)

    if (
        state is None
        or state.get("status") != "running"
    ):
        failed(
            f"{target} is not running before test"
        )
        return 1

    print()
    print(f"Failure target: {target}")

    test_failed = False

    try:
        # -----------------------------------------------------
        # Inject failure
        # -----------------------------------------------------

        result = compose(
            "stop",
            "-t",
            "5",
            target,
        )

        if (
            result is None
            or result.returncode != 0
        ):
            failed(
                f"could not stop {target}"
            )
            test_failed = True
        else:
            state = container_state(target)

            if (
                state is None
                or state.get("status") == "running"
            ):
                failed(
                    f"{target} did not stop"
                )
                test_failed = True
            else:
                passed(
                    f"{target} stopped successfully"
                )

        # -----------------------------------------------------
        # Measure traffic while backend is down
        # -----------------------------------------------------

        if not test_failed:
            seen_during_failure = set()
            status_counts = Counter()

            for _ in range(FAILURE_REQUESTS):
                status, body = http_get(
                    base_url,
                    "/instance",
                )

                status_key = (
                    str(status)
                    if status is not None
                    else "connection_error"
                )

                status_counts[
                    status_key
                ] += 1

                if (
                    status == 200
                    and isinstance(body, dict)
                ):
                    instance = body.get(
                        "instance_id"
                    )

                    if instance:
                        seen_during_failure.add(
                            instance
                        )

                time.sleep(REQUEST_INTERVAL)

            successful_requests = (
                status_counts.get("200", 0)
            )

            error_requests = (
                sum(status_counts.values())
                - successful_requests
            )

            print()
            print(
                "Traffic while backend is stopped:"
            )
            print(
                "  total_requests="
                f"{sum(status_counts.values())}"
            )
            print(
                "  successful_requests="
                f"{successful_requests}"
            )
            print(
                "  error_requests="
                f"{error_requests}"
            )
            print(
                "  status_counts="
                + json.dumps(
                    dict(status_counts),
                    sort_keys=True,
                )
            )
            print(
                "  successful_instances="
                + (
                    ", ".join(
                        sorted(
                            seen_during_failure
                        )
                    )
                    if seen_during_failure
                    else "<none>"
                )
            )

            if successful_requests == 0:
                failed(
                    "service lost all availability "
                    "while one backend was stopped"
                )
                test_failed = True
            else:
                passed(
                    "service remained available "
                    "through surviving backend(s)"
                )

            unexpected_instances = (
                seen_during_failure
                - survivors
            )

            if unexpected_instances:
                failed(
                    "stopped backend unexpectedly "
                    "served successful traffic: "
                    + ", ".join(
                        sorted(
                            unexpected_instances
                        )
                    )
                )
                test_failed = True
            else:
                passed(
                    "successful outage traffic came "
                    "only from surviving backend(s)"
                )

            print(
                "INFO: measured client errors during "
                f"backend failure = {error_requests}"
            )

    finally:
        # -----------------------------------------------------
        # Guaranteed restoration
        # -----------------------------------------------------

        print()
        print(
            f"Ensuring {target} is restored..."
        )

        result = compose(
            "start",
            target,
        )

        if (
            result is None
            or result.returncode != 0
        ):
            failed(
                f"could not restart {target}"
            )
            test_failed = True

        elif not wait_for_healthy(
            target
        ):
            failed(
                f"{target} did not become "
                f"healthy within "
                f"{RECOVERY_TIMEOUT}s"
            )
            test_failed = True

        else:
            passed(
                f"{target} returned healthy"
            )

    # ---------------------------------------------------------
    # Prove recovered backend serves again
    # ---------------------------------------------------------

    recovery_seen = set()
    recovery_statuses = Counter()

    for _ in range(RECOVERY_ATTEMPTS):
        status, body = http_get(
            base_url,
            "/instance",
        )

        status_key = (
            str(status)
            if status is not None
            else "connection_error"
        )

        recovery_statuses[
            status_key
        ] += 1

        if (
            status == 200
            and isinstance(body, dict)
        ):
            instance = body.get(
                "instance_id"
            )

            if instance:
                recovery_seen.add(
                    instance
                )

        if target in recovery_seen:
            break

        time.sleep(REQUEST_INTERVAL)

    print()
    print("Recovery traffic:")
    print(
        "  statuses="
        + json.dumps(
            dict(recovery_statuses),
            sort_keys=True,
        )
    )
    print(
        "  instances="
        + (
            ", ".join(
                sorted(recovery_seen)
            )
            if recovery_seen
            else "<none>"
        )
    )

    if target not in recovery_seen:
        failed(
            f"recovered backend {target} "
            "did not serve traffic again"
        )
        test_failed = True
    else:
        passed(
            f"recovered backend {target} "
            "served traffic again"
        )

    # ---------------------------------------------------------
    # Final readiness proof
    # ---------------------------------------------------------

    status, body = http_get(
        base_url,
        "/ready",
    )

    if (
        status == 200
        and isinstance(body, dict)
        and body.get(
            "dependencies",
            {},
        ).get("postgres") == "ready"
        and body.get(
            "dependencies",
            {},
        ).get("redis") == "ready"
    ):
        passed(
            "final /ready confirms "
            "PostgreSQL and Redis ready"
        )
    else:
        failed(
            "final /ready check failed"
        )
        test_failed = True

    print()
    print("=" * 72)

    if test_failed:
        print(
            "FAILURE TEST FAILED"
        )
        return 1

    print(
        "FAILURE TEST PASSED"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except KeyboardInterrupt:
        print()
        print(
            "Interrupted. Backend restoration "
            "is attempted by the finally block."
        )
        sys.exit(130)
