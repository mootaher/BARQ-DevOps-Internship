#!/usr/bin/env python3
"""
BARQ environment validator.

Validates:
- Docker Compose syntax and required services
- bounded public readiness
- required HTTP endpoints
- real PostgreSQL create/list behavior
- real Redis counter behavior
- all configured app backends through NGINX
- container health
- frontend/backend network isolation
- prohibited host port exposure

The validator discovers the NGINX public port and app-* services dynamically,
so it remains usable after the video challenge changes the stack.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent

HTTP_TIMEOUT = 3
READY_TIMEOUT = 45
READY_INTERVAL = 1
INSTANCE_ATTEMPTS = 30

failures = 0


def passed(message):
    print(f"PASS: {message}")


def failed(message):
    global failures
    failures += 1
    print(f"FAIL: {message}")


def run(command, timeout=15):
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return result
    except subprocess.TimeoutExpired:
        return None


def compose(*args, timeout=15):
    return run(
        ["docker", "compose", *args],
        timeout=timeout,
    )


def http_request(
    base_url,
    path,
    method="GET",
    json_body=None,
):
    data = None
    headers = {}

    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=HTTP_TIMEOUT,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None

            return (
                response.status,
                parsed,
                dict(response.headers),
                body,
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None

        return (
            exc.code,
            parsed,
            dict(exc.headers),
            body,
        )

    except (
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        return (
            None,
            None,
            {},
            str(exc),
        )


def get_service_container_id(service):
    result = compose(
        "ps",
        "-q",
        service,
    )

    if (
        result is None
        or result.returncode != 0
    ):
        return None

    container_id = result.stdout.strip()

    return container_id or None


def inspect_container(container_id):
    result = run(
        [
            "docker",
            "inspect",
            container_id,
        ]
    )

    if (
        result is None
        or result.returncode != 0
    ):
        return None

    try:
        data = json.loads(result.stdout)
        return data[0]
    except (
        json.JSONDecodeError,
        IndexError,
    ):
        return None


def network_roles(inspect_data):
    networks = (
        inspect_data
        .get("NetworkSettings", {})
        .get("Networks", {})
    )

    roles = set()

    for name in networks:
        if name == "frontend" or name.endswith("_frontend"):
            roles.add("frontend")

        if name == "backend" or name.endswith("_backend"):
            roles.add("backend")

    return roles


def discover_public_url():
    result = compose(
        "port",
        "nginx",
        "80",
    )

    if (
        result is None
        or result.returncode != 0
    ):
        return None

    line = result.stdout.strip().splitlines()

    if not line:
        return None

    address = line[0].strip()

    try:
        port = int(
            address.rsplit(":", 1)[1]
        )
    except (
        ValueError,
        IndexError,
    ):
        return None

    return f"http://127.0.0.1:{port}"


def wait_for_ready(base_url):
    deadline = time.monotonic() + READY_TIMEOUT
    last_status = None

    while time.monotonic() < deadline:
        status, body, _, _ = http_request(
            base_url,
            "/ready",
        )

        last_status = status

        if (
            status == 200
            and isinstance(body, dict)
        ):
            dependencies = body.get(
                "dependencies",
                {},
            )

            if (
                dependencies.get("postgres")
                == "ready"
                and dependencies.get("redis")
                == "ready"
            ):
                return True

        time.sleep(READY_INTERVAL)

    failed(
        "readiness did not become healthy "
        f"within {READY_TIMEOUT}s "
        f"(last HTTP status={last_status})"
    )

    return False


def check_endpoint(
    base_url,
    path,
    expected_status=200,
):
    status, body, headers, _ = http_request(
        base_url,
        path,
    )

    if status != expected_status:
        failed(
            f"{path} returned {status}; "
            f"expected {expected_status}"
        )
        return None, headers

    passed(
        f"{path} returned HTTP {expected_status}"
    )

    return body, headers


def main():
    print("BARQ environment validation")
    print("=" * 72)

    # ---------------------------------------------------------
    # Compose syntax
    # ---------------------------------------------------------

    result = compose(
        "config",
        "-q",
    )

    if (
        result is not None
        and result.returncode == 0
    ):
        passed("Docker Compose configuration is valid")
    else:
        failed("Docker Compose configuration is invalid")

    # ---------------------------------------------------------
    # Discover services
    # ---------------------------------------------------------

    result = compose(
        "config",
        "--services",
    )

    if (
        result is None
        or result.returncode != 0
    ):
        failed("could not discover Compose services")
        print()
        print(f"Validation finished: {failures} failure(s)")
        sys.exit(1)

    services = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    required_services = {
        "nginx",
        "postgres",
        "redis",
    }

    missing_services = sorted(
        required_services - set(services)
    )

    if missing_services:
        failed(
            "missing required services: "
            + ", ".join(missing_services)
        )
    else:
        passed(
            "required infrastructure services exist"
        )

    app_services = sorted(
        service
        for service in services
        if service.startswith("app-")
    )

    if len(app_services) < 2:
        failed(
            "fewer than two app services configured"
        )
    else:
        passed(
            "configured app services: "
            + ", ".join(app_services)
        )

    all_services = [
        "nginx",
        *app_services,
        "postgres",
        "redis",
    ]

    # ---------------------------------------------------------
    # Running state / health
    # ---------------------------------------------------------

    inspected = {}

    for service in all_services:
        container_id = get_service_container_id(
            service
        )

        if not container_id:
            failed(
                f"{service} has no running container"
            )
            continue

        data = inspect_container(
            container_id
        )

        if data is None:
            failed(
                f"could not inspect {service}"
            )
            continue

        inspected[service] = data

        state = data.get(
            "State",
            {},
        )

        if state.get("Status") != "running":
            failed(
                f"{service} is not running "
                f"(state={state.get('Status')})"
            )
            continue

        health = state.get(
            "Health",
            {},
        ).get("Status")

        if health is not None:
            if health == "healthy":
                passed(
                    f"{service} is running and healthy"
                )
            else:
                failed(
                    f"{service} health={health}"
                )
        else:
            passed(
                f"{service} is running"
            )

    # ---------------------------------------------------------
    # Public NGINX address
    # ---------------------------------------------------------

    base_url = discover_public_url()

    if base_url is None:
        failed(
            "could not discover NGINX public port"
        )
        print()
        print(
            f"Validation finished: "
            f"{failures} failure(s)"
        )
        sys.exit(1)

    passed(
        f"NGINX public endpoint discovered at "
        f"{base_url}"
    )

    # ---------------------------------------------------------
    # Bounded readiness wait
    # ---------------------------------------------------------

    if wait_for_ready(base_url):
        passed(
            "PostgreSQL and Redis readiness confirmed"
        )

    # ---------------------------------------------------------
    # Required public endpoints
    # ---------------------------------------------------------

    root_body, _ = check_endpoint(
        base_url,
        "/",
    )

    if isinstance(root_body, dict):
        if root_body.get("instance_id"):
            passed(
                "/ includes backend instance identity"
            )
        else:
            failed(
                "/ response lacks instance_id"
            )
    else:
        failed(
            "/ did not return a JSON object"
        )

    check_endpoint(
        base_url,
        "/health",
    )

    ready_body, _ = check_endpoint(
        base_url,
        "/ready",
    )

    if isinstance(ready_body, dict):
        dependencies = ready_body.get(
            "dependencies",
            {},
        )

        if (
            dependencies.get("postgres")
            == "ready"
            and dependencies.get("redis")
            == "ready"
        ):
            passed(
                "/ready reports PostgreSQL "
                "and Redis ready"
            )
        else:
            failed(
                "/ready dependency state is incorrect"
            )

    # ---------------------------------------------------------
    # PostgreSQL real operation
    # ---------------------------------------------------------

    validation_title = (
        "validator-"
        + str(int(time.time()))
    )

    status, body, _, _ = http_request(
        base_url,
        "/records",
        method="POST",
        json_body={
            "title": validation_title,
        },
    )

    if status == 201:
        passed(
            "POST /records stored a PostgreSQL record"
        )
    else:
        failed(
            "POST /records returned "
            f"{status}; expected 201"
        )

    records_body, _ = check_endpoint(
        base_url,
        "/records",
    )

    if isinstance(records_body, dict):
        records = records_body.get(
            "records",
            [],
        )

        if any(
            record.get("title")
            == validation_title
            for record in records
            if isinstance(record, dict)
        ):
            passed(
                "created PostgreSQL record is "
                "visible through GET /records"
            )
        else:
            failed(
                "created PostgreSQL record was not "
                "found in GET /records"
            )
    else:
        failed(
            "GET /records did not return JSON"
        )

    # ---------------------------------------------------------
    # Redis real operation
    # ---------------------------------------------------------

    first_counter, _ = check_endpoint(
        base_url,
        "/counter",
    )

    second_counter, _ = check_endpoint(
        base_url,
        "/counter",
    )

    try:
        first_value = int(
            first_counter["counter"]
        )

        second_value = int(
            second_counter["counter"]
        )

        if second_value == first_value + 1:
            passed(
                "Redis counter incremented atomically"
            )
        else:
            failed(
                "Redis counter did not increment "
                "by exactly one"
            )

    except (
        TypeError,
        KeyError,
        ValueError,
    ):
        failed(
            "/counter responses did not contain "
            "valid integer counter values"
        )

    # ---------------------------------------------------------
    # Prove every configured backend serves via NGINX
    # ---------------------------------------------------------

    expected_instances = set(
        app_services
    )

    seen_instances = set()

    for _ in range(INSTANCE_ATTEMPTS):
        status, body, headers, _ = http_request(
            base_url,
            "/instance",
        )

        if (
            status == 200
            and isinstance(body, dict)
        ):
            instance = body.get(
                "instance_id"
            )

            if instance:
                seen_instances.add(
                    instance
                )

                header_instance = (
                    headers.get("X-Instance-ID")
                    or headers.get("X-Instance-Id")
                )

                if (
                    header_instance
                    and header_instance != instance
                ):
                    failed(
                        "/instance body/header "
                        "identity mismatch"
                    )
                    break

        if expected_instances.issubset(
            seen_instances
        ):
            break

    missing_instances = sorted(
        expected_instances - seen_instances
    )

    if missing_instances:
        failed(
            "did not observe all backends through "
            "NGINX; missing: "
            + ", ".join(missing_instances)
        )
    else:
        passed(
            "all configured backends served "
            "through NGINX: "
            + ", ".join(sorted(seen_instances))
        )

    # ---------------------------------------------------------
    # Network isolation
    # ---------------------------------------------------------

    expected_networks = {
        "nginx": {"frontend"},
        "postgres": {"backend"},
        "redis": {"backend"},
    }

    for app_service in app_services:
        expected_networks[
            app_service
        ] = {
            "frontend",
            "backend",
        }

    for service, expected in expected_networks.items():
        data = inspected.get(service)

        if data is None:
            continue

        actual = network_roles(
            data
        )

        if actual == expected:
            passed(
                f"{service} network roles="
                + ",".join(sorted(actual))
            )
        else:
            failed(
                f"{service} network roles="
                f"{sorted(actual)}; "
                f"expected={sorted(expected)}"
            )

    # Explicitly prove NGINX shares no network
    # with PostgreSQL or Redis.
    nginx_data = inspected.get(
        "nginx"
    )

    if nginx_data:
        nginx_networks = set(
            nginx_data
            .get("NetworkSettings", {})
            .get("Networks", {})
            .keys()
        )

        for dependency in (
            "postgres",
            "redis",
        ):
            dependency_data = inspected.get(
                dependency
            )

            if not dependency_data:
                continue

            dependency_networks = set(
                dependency_data
                .get("NetworkSettings", {})
                .get("Networks", {})
                .keys()
            )

            shared = (
                nginx_networks
                & dependency_networks
            )

            if shared:
                failed(
                    f"nginx shares network with "
                    f"{dependency}: "
                    + ", ".join(sorted(shared))
                )
            else:
                passed(
                    f"nginx has no direct network "
                    f"path to {dependency}"
                )

    # ---------------------------------------------------------
    # Host port exposure
    # ---------------------------------------------------------

    for service in all_services:
        data = inspected.get(service)

        if data is None:
            continue

        bindings = (
            data
            .get("HostConfig", {})
            .get("PortBindings", {})
            or {}
        )

        active_bindings = {
            port: value
            for port, value in bindings.items()
            if value
        }

        if service == "nginx":
            if set(active_bindings) != {
                "80/tcp"
            }:
                failed(
                    "nginx exposes unexpected "
                    f"container ports: "
                    f"{sorted(active_bindings)}"
                )
                continue

            entries = active_bindings[
                "80/tcp"
            ]

            if len(entries) != 1:
                failed(
                    "nginx does not have exactly "
                    "one host binding"
                )
                continue

            host_ip = entries[0].get(
                "HostIp",
                "",
            )

            host_port = entries[0].get(
                "HostPort",
                "",
            )

            if host_ip != "127.0.0.1":
                failed(
                    "nginx is not bound only to "
                    f"127.0.0.1 "
                    f"(HostIp={host_ip!r})"
                )
            else:
                passed(
                    f"only nginx publishes "
                    f"127.0.0.1:{host_port}->80"
                )

        else:
            if active_bindings:
                failed(
                    f"{service} publishes prohibited "
                    f"host ports: "
                    f"{sorted(active_bindings)}"
                )
            else:
                passed(
                    f"{service} publishes no host ports"
                )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print()
    print("=" * 72)

    if failures:
        print(
            f"VALIDATION FAILED: "
            f"{failures} check(s) failed"
        )
        sys.exit(1)

    print(
        "VALIDATION PASSED: all checks succeeded"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
