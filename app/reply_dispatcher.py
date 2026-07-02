from __future__ import annotations
from app.bridge_adapters import adb_broadcast, am_broadcast, http_test_backend, noop
from app.schemas import AdapterResult, BridgeMode, ReplyCommand, ReplyJobStatus


def dispatch_reply(command: ReplyCommand, mode: str, http_client=None) -> AdapterResult:
    """bridge mode에 맞는 adapter로 답장 명령을 전달한다."""

    if mode == BridgeMode.noop.value:
        return noop.dispatch(command)
    if mode == BridgeMode.http_test_backend.value:
        return http_test_backend.dispatch(command, http_client=http_client)
    if mode == BridgeMode.am_broadcast.value:
        return am_broadcast.dispatch(command)
    if mode == BridgeMode.adb_broadcast.value:
        return adb_broadcast.dispatch(command)
    return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=f"unsupported mode: {mode}")
