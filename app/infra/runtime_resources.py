from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock

import httpx

from app.config import Settings, get_settings
from app.infra.dispatch_queue import DispatchQueue
from app.infra.external_runner import ExternalTaskRunner, ExternalTaskResult
from app.infra.memory_caches import ConfigCache, ReplyTokenCache
from app.infra.memory_pipeline import MemoryPipeline


@dataclass
class RuntimeResources:
    """프로세스 lifecycle 동안 공유하는 외부 I/O 리소스다."""

    bot_external_runner: ExternalTaskRunner
    adapter_external_runner: ExternalTaskRunner
    http_client: httpx.Client
    memory_pipeline: MemoryPipeline
    dispatch_queue: DispatchQueue
    reply_token_cache: ReplyTokenCache
    config_cache: ConfigCache

    @classmethod
    def from_settings(cls, settings: Settings) -> "RuntimeResources":
        http_client = httpx.Client(
            limits=httpx.Limits(
                max_connections=max(settings.http_client_max_connections, 1),
                max_keepalive_connections=max(settings.http_client_max_keepalive, 0),
            )
        )
        return cls(
            bot_external_runner=ExternalTaskRunner(
                max_workers=settings.chatbot_external_workers,
                queue_size=settings.chatbot_external_queue_size,
                name="bot_external",
            ),
            adapter_external_runner=ExternalTaskRunner(
                max_workers=settings.adapter_external_workers,
                queue_size=settings.adapter_external_queue_size,
                name="adapter_external",
            ),
            http_client=http_client,
            memory_pipeline=MemoryPipeline(settings),
            dispatch_queue=DispatchQueue(settings, http_client),
            reply_token_cache=ReplyTokenCache(),
            config_cache=ConfigCache(),
        )

    def stats(self) -> dict[str, dict]:
        """health API에서 노출할 runner 통계를 반환한다."""

        return {
            "botExternal": asdict(self.bot_external_runner.stats()),
            "adapterExternal": asdict(self.adapter_external_runner.stats()),
            "memoryPipeline": self.memory_pipeline.stats(),
            "dispatchQueue": self.dispatch_queue.stats(),
            "configCache": self.config_cache.stats(),
        }

    def shutdown(self, wait: bool = False) -> None:
        self.bot_external_runner.shutdown(wait=wait)
        self.adapter_external_runner.shutdown(wait=wait)
        self.dispatch_queue.shutdown(wait=wait)
        self.memory_pipeline.shutdown(wait=wait)
        self.http_client.close()


class BotExternalRunnerProxy:
    """봇 runtime에 주입되는 lazy runner proxy다.

    봇 모듈이 오래 살아 있어도 매 호출 시 현재 RuntimeResources의 runner를 사용한다.
    """

    def submit(self, fn):
        return get_runtime_resources().bot_external_runner.submit(fn)

    def run(self, fn, timeout_seconds: float | None = None) -> ExternalTaskResult:
        return get_runtime_resources().bot_external_runner.run(fn, timeout_seconds=timeout_seconds)

    def stats(self):
        return get_runtime_resources().bot_external_runner.stats()


class HttpClientProxy:
    """봇 runtime에 주입되는 lazy HTTP client proxy다."""

    def post(self, *args, **kwargs):
        return get_runtime_resources().http_client.post(*args, **kwargs)


_resources_lock = RLock()
_resources: RuntimeResources | None = None
_resources_signature: tuple[int, ...] | None = None
_bot_external_runner_proxy = BotExternalRunnerProxy()
_http_client_proxy = HttpClientProxy()


def _signature(settings: Settings) -> tuple[int, ...]:
    return (
        settings.chatbot_external_workers,
        settings.chatbot_external_queue_size,
        settings.adapter_external_workers,
        settings.adapter_external_queue_size,
        settings.http_client_max_connections,
        settings.http_client_max_keepalive,
        settings.event_queue_size,
        settings.event_dedupe_ttl_ms,
        settings.room_workers,
        settings.room_max_pending_per_room,
        settings.room_max_active_partitions,
        settings.sqlite_writer_batch_size,
        settings.sqlite_writer_flush_interval_ms,
        settings.sqlite_writer_queue_size,
        settings.dispatch_queue_size,
        settings.dispatch_workers,
        settings.dispatch_max_attempts,
        settings.dispatch_retry_backoff_ms,
        settings.dispatch_lease_ms,
    )


def get_runtime_resources() -> RuntimeResources:
    """현재 설정 기준 runtime resource singleton을 반환한다."""

    global _resources, _resources_signature
    settings = get_settings()
    signature = _signature(settings)
    with _resources_lock:
        if _resources is not None and _resources_signature == signature:
            return _resources
        if _resources is not None:
            _resources.shutdown(wait=False)
        _resources = RuntimeResources.from_settings(settings)
        _resources_signature = signature
        return _resources


def get_existing_runtime_resources() -> RuntimeResources | None:
    """이미 시작된 runtime resource를 반환한다.

    로그/실행 기록 같은 low priority writer facade에서 사용한다. 이 함수는 호출만으로
    worker thread를 새로 만들지 않으므로 단위 테스트와 초기화 전 fallback 경로를 유지한다.
    """

    with _resources_lock:
        return _resources


def shutdown_runtime_resources(wait: bool = False) -> None:
    """프로세스 종료 또는 테스트 reset에서 runtime resource를 정리한다."""

    global _resources, _resources_signature
    with _resources_lock:
        if _resources is not None:
            _resources.shutdown(wait=wait)
        _resources = None
        _resources_signature = None


def reset_runtime_resources_for_test() -> None:
    """테스트가 env 설정을 바꿀 때 runner singleton을 초기화한다."""

    shutdown_runtime_resources(wait=True)


def get_bot_external_runner_proxy() -> BotExternalRunnerProxy:
    return _bot_external_runner_proxy


def get_http_client_proxy() -> HttpClientProxy:
    return _http_client_proxy
