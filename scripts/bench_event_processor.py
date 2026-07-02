#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark kakao-termux-back /events processing.")
    parser.add_argument("--events", type=int, default=1_000)
    parser.add_argument("--duration-seconds", type=float, default=None)
    parser.add_argument("--rate", type=float, default=None)
    parser.add_argument("--rooms", type=int, default=20)
    parser.add_argument("--senders", type=int, default=200)
    parser.add_argument("--message-size", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--client", choices=("http", "testclient", "service"), default="http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--event-process-mode", default="memory_queue")
    parser.add_argument("--event-durability-mode", default="enqueue_backup")
    parser.add_argument("--event-result-log", action="store_true")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--token", default="bench-secret")
    parser.add_argument("--keep-db", action="store_true")
    return parser.parse_args()


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    index = min(int(round((len(values) - 1) * ratio)), len(values) - 1)
    return sorted(values)[index]


def event_payload(index: int, rooms: int, senders: int, message_size: int, token: str) -> dict:
    text_prefix = f"bench message {index} "
    padding = "x" * max(message_size - len(text_prefix), 0)
    return {
        "schemaVersion": 1,
        "eventId": f"bench_evt_{index}",
        "source": "notification",
        "sourcePackage": "pc.kakao-test-app",
        "sourceType": "virtual_phone",
        "roomKey": f"bench_room_{index % max(rooms, 1)}",
        "room": f"벤치방 {index % max(rooms, 1)}",
        "sender": f"sender_{index % max(senders, 1)}",
        "text": text_prefix + padding,
        "messageType": "text",
        "receivedAt": 1_700_000_000_000 + index,
        "notificationKey": f"bench_noti_{index}",
        "replyToken": f"bench_reply_{index}",
        "replyTokenExpiresAt": 1_900_000_000_000,
        "token": token,
    }


def main() -> int:
    args = parse_args()
    db_path = args.db_path
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="kakao-bench-")
        db_path = str(Path(temp_dir.name) / "bench.sqlite3")

    os.environ["BACKEND_DB_PATH"] = db_path
    os.environ["BRIDGE_SHARED_SECRET"] = args.token
    os.environ["ANDROID_BRIDGE_MODE"] = "noop"
    os.environ["EVENT_PROCESS_MODE"] = args.event_process_mode
    os.environ["EVENT_DURABILITY_MODE"] = args.event_durability_mode
    os.environ["EVENT_RESULT_LOG_ENABLED"] = "true" if args.event_result_log else "false"
    os.environ["SETTINGS_AUTO_RELOAD"] = "false"
    os.environ["SEND_DISPATCH_MODE"] = "async_enqueue"
    os.environ["SQLITE_WRITER_FLUSH_INTERVAL_MS"] = "20"

    from app.config import reset_settings_for_test
    from app.infra.runtime_resources import reset_runtime_resources_for_test
    from app import main as main_module

    app = main_module.app

    reset_settings_for_test()
    reset_runtime_resources_for_test()

    latencies_ms: list[float] = []
    actions: dict[str, int] = {}
    benchmark_started = time.perf_counter()
    tracemalloc.start()
    event_count = _event_count(args)
    if args.client == "http":
        health, send_seconds, drain_seconds, drain_complete = _run_http_benchmark(
            args, app, event_count, latencies_ms, actions
        )
    elif args.client == "service":
        health, send_seconds, drain_seconds, drain_complete = _run_service_benchmark(
            args, main_module, event_count, latencies_ms, actions
        )
    else:
        health, send_seconds, drain_seconds, drain_complete = _run_testclient_benchmark(
            args, app, event_count, latencies_ms, actions
        )
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_seconds = time.perf_counter() - benchmark_started
    max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    result = {
        "events": event_count,
        "targetRate": args.rate,
        "durationSeconds": args.duration_seconds,
        "eventProcessMode": args.event_process_mode,
        "eventDurabilityMode": args.event_durability_mode,
        "client": args.client,
        "rooms": max(args.rooms, 1),
        "senders": max(args.senders, 1),
        "messageSize": args.message_size,
        "totalSeconds": round(total_seconds, 4),
        "sendSeconds": round(send_seconds, 4),
        "drainSeconds": round(drain_seconds, 4),
        "drainComplete": drain_complete,
        "eventsPerSecond": round(event_count / send_seconds, 2) if send_seconds else 0,
        "latencyMs": {
            "p50": round(statistics.median(latencies_ms), 4),
            "p95": round(percentile(latencies_ms, 0.95), 4),
            "p99": round(percentile(latencies_ms, 0.99), 4),
            "max": round(max(latencies_ms), 4),
        },
        "memory": {
            "tracemallocCurrentBytes": current_bytes,
            "tracemallocPeakBytes": peak_bytes,
            "maxRssKb": max_rss_kb,
        },
        "actions": actions,
        "runtime": health.get("runtime") if health else None,
        "recovery": health.get("recovery") if health else None,
        "dbPath": db_path if args.keep_db else "<temporary>",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    from app.infra.runtime_resources import shutdown_runtime_resources

    shutdown_runtime_resources(wait=True)
    reset_settings_for_test()
    if temp_dir is not None and not args.keep_db:
        try:
            temp_dir.cleanup()
        except OSError:
            pass
    return 0


def _event_count(args: argparse.Namespace) -> int:
    if args.duration_seconds is not None and args.rate is not None:
        return max(int(args.duration_seconds * args.rate), 1)
    return max(args.events, 1)


def _post_event(client: TestClient, payload: dict) -> tuple[float, str]:
    event_started = time.perf_counter()
    response = client.post("/events", json=payload)
    elapsed_ms = (time.perf_counter() - event_started) * 1000
    response.raise_for_status()
    body = response.json()
    return elapsed_ms, body.get("action", "unknown")


def _run_testclient_benchmark(
    args: argparse.Namespace,
    app,
    event_count: int,
    latencies_ms: list[float],
    actions: dict[str, int],
) -> tuple[dict, float, float, bool]:
    with TestClient(app) as client:
        client.post(
            "/chatbot/modules/ai_chatbot",
            json={"token": args.token, "enabled": False},
        ).raise_for_status()
        send_seconds = _send_events(args, event_count, latencies_ms, actions, lambda payload: _post_event(client, payload))
        drain_started = time.perf_counter()
        drain_complete = _wait_for_runtime_idle(
            lambda: client.get("/health", params={"includeDetails": "true"}).json(),
            event_count,
        )
        drain_seconds = time.perf_counter() - drain_started
        health = client.get("/health", params={"includeDetails": "true"}).json()
    return health, send_seconds, drain_seconds, drain_complete


def _run_http_benchmark(
    args: argparse.Namespace,
    app,
    event_count: int,
    latencies_ms: list[float],
    actions: dict[str, int],
) -> tuple[dict, float, float, bool]:
    import httpx
    import uvicorn

    host = args.host
    port = args.port or _free_port(host)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="bench-uvicorn", daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            _wait_http_ready(client)
            client.post(
                "/chatbot/modules/ai_chatbot",
                json={"token": args.token, "enabled": False},
            ).raise_for_status()
            send_seconds = _send_events(
                args,
                event_count,
                latencies_ms,
                actions,
                lambda payload: _post_event_http(client, payload),
            )
            drain_started = time.perf_counter()
            drain_complete = _wait_for_runtime_idle(
                lambda: client.get("/health", params={"includeDetails": "true"}).json(),
                event_count,
            )
            drain_seconds = time.perf_counter() - drain_started
            health = client.get("/health", params={"includeDetails": "true"}).json()
        return health, send_seconds, drain_seconds, drain_complete
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _run_service_benchmark(
    args: argparse.Namespace,
    main_module,
    event_count: int,
    latencies_ms: list[float],
    actions: dict[str, int],
) -> tuple[dict, float, float, bool]:
    from app.db import init_db
    from app.infra.runtime_resources import get_runtime_resources
    from app.schemas import BridgeEvent

    init_db()
    get_runtime_resources()
    main_module.chatbot_service.startup()
    main_module.recovery_service.recover()
    main_module.recovery_service.start_scheduler()
    try:
        if args.token:
            row = main_module.update_chatbot_module_config_cached(
                "ai_chatbot",
                enabled=False,
                priority=None,
                options={},
            )
            if row is not None:
                get_runtime_resources().config_cache.set_module_row(row)

        def post_service(payload: dict) -> tuple[float, str]:
            event_started = time.perf_counter()
            response = main_module.event_service.handle_event(BridgeEvent.model_validate(payload))
            elapsed_ms = (time.perf_counter() - event_started) * 1000
            return elapsed_ms, response.action.value

        send_seconds = _send_events(args, event_count, latencies_ms, actions, post_service)
        drain_started = time.perf_counter()
        drain_complete = _wait_for_runtime_idle(
            lambda: {
                "runtime": get_runtime_resources().stats(),
                "recovery": main_module.recovery_service.stats(),
            },
            event_count,
        )
        drain_seconds = time.perf_counter() - drain_started
        health = {
            "runtime": get_runtime_resources().stats(),
            "recovery": main_module.recovery_service.stats(),
        }
        return health, send_seconds, drain_seconds, drain_complete
    finally:
        main_module.recovery_service.stop_scheduler()
        main_module.chatbot_service.shutdown()


def _send_events(
    args: argparse.Namespace,
    event_count: int,
    latencies_ms: list[float],
    actions: dict[str, int],
    post_event,
) -> float:
    send_started = time.perf_counter()
    if max(args.workers, 1) <= 1:
        schedule_started = time.perf_counter()
        for index in range(event_count):
            if args.rate and args.rate > 0:
                target = schedule_started + index / args.rate
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            elapsed_ms, action = post_event(
                event_payload(index, args.rooms, args.senders, args.message_size, args.token)
            )
            latencies_ms.append(elapsed_ms)
            actions[action] = actions.get(action, 0) + 1
        return time.perf_counter() - send_started

    with ThreadPoolExecutor(max_workers=max(args.workers, 1)) as executor:
        futures = []
        schedule_started = time.perf_counter()
        for index in range(event_count):
            if args.rate and args.rate > 0:
                target = schedule_started + index / args.rate
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            futures.append(
                executor.submit(
                    post_event,
                    event_payload(index, args.rooms, args.senders, args.message_size, args.token),
                )
            )
        for future in as_completed(futures):
            elapsed_ms, action = future.result()
            latencies_ms.append(elapsed_ms)
            actions[action] = actions.get(action, 0) + 1
    return time.perf_counter() - send_started


def _post_event_http(client, payload: dict) -> tuple[float, str]:
    event_started = time.perf_counter()
    response = client.post("/events", json=payload)
    elapsed_ms = (time.perf_counter() - event_started) * 1000
    response.raise_for_status()
    body = response.json()
    return elapsed_ms, body.get("action", "unknown")


def _wait_for_runtime_idle(health_provider, event_count: int, timeout_seconds: float = 30.0) -> bool:
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        health = health_provider()
        runtime = health.get("runtime") or {}
        memory_pipeline = runtime.get("memoryPipeline") or {}
        pipeline = memory_pipeline.get("pipeline") or {}
        writer = memory_pipeline.get("sqliteWriter") or {}
        processed = int(pipeline.get("processed") or 0)
        queued = int(pipeline.get("queued") or 0)
        active = int(pipeline.get("active") or 0)
        writer_queued = int(writer.get("queued") or 0)
        if processed >= event_count and queued == 0 and active == 0 and writer_queued == 0:
            return True
        time.sleep(0.05)
    return False


def _wait_http_ready(client, timeout_seconds: float = 10.0) -> None:
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.05)
    raise RuntimeError("benchmark HTTP server did not become ready")


def _free_port(host: str) -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
