"""A runaway agent must not be able to fill the database.

Sign-in is throttled by counting recent failures in the audit trail. `/mcp` had
no equivalent: an authenticated agent could call `predict_fuel` in a tight loop,
and every call writes a daily-operation row, a prediction row and an audit row.
A stuck agent — a retry loop, a bad prompt — is a more likely cause than an
attacker, and the effect is the same.

The limit is per client, so one misbehaving agent cannot deny service to the
others, which is the same reason each has its own revocable credential.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from fuel_predictor.delivery.mcp_server import (
    McpRateLimitError,
    McpRequestHandler,
    McpTool,
    McpToolRegistry,
)
from fuel_predictor.domain.identity import AgentClient, AgentScope

_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _Audit:
    """Counts what the handler records, the way the real repository would."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, datetime]] = []

    def add(self, record: object) -> None:  # pragma: no cover - unused here
        raise AssertionError("the handler records through RecordAuditEvent")

    def count_recent_by_actor(self, actor: str, action_prefix: str, since: datetime) -> int:
        return sum(
            1
            for recorded_actor, action, moment in self.records
            if recorded_actor == actor and action.startswith(action_prefix) and moment >= since
        )


class _RecordAudit:
    """Stamps each record with the clock the handler is using.

    Not a fixed instant: a fake that timestamps everything at t=0 lets records
    age out no matter when they were written, which would let the
    "rejections do not extend the block" test pass even with the bug present.
    """

    def __init__(self, audit: _Audit, clock: Callable[[], datetime] | None = None) -> None:
        self.audit_repository = audit
        self._clock = clock or (lambda: _NOW)

    def execute(self, **kwargs: object) -> None:
        self.audit_repository.records.append(
            (str(kwargs["actor"]), str(kwargs["action"]), self._clock())
        )


class _Resolver:
    def __init__(self, client: AgentClient) -> None:
        self._client = client

    def execute(self, token: str | None) -> AgentClient | None:
        return self._client if token else None


def _client(name: str) -> AgentClient:
    return AgentClient(
        client_id=f"AGT-{name}",
        name=name,
        scopes=frozenset({AgentScope.PREDICT}),
        token_hash="x",
        created_at=_NOW,
        is_active=True,
    )


@pytest.fixture
def handler() -> McpRequestHandler:
    registry = McpToolRegistry(
        tools=(
            McpTool(
                name="predict_fuel",
                description="",
                scope=AgentScope.PREDICT,
                input_schema={},
                handler=lambda _arguments: {"ok": True},
            ),
        )
    )
    audit = _Audit()
    return McpRequestHandler(
        registry=registry,
        resolve_credential=_Resolver(_client("Agen Satu")),
        record_audit=_RecordAudit(audit),
        max_calls_per_window=3,
        window_seconds=60,
        now=lambda: _NOW,
    )


def test_calls_within_the_allowance_are_served(handler: McpRequestHandler) -> None:
    caller = _client("Agen Satu")

    for _ in range(3):
        assert handler.call(caller, "predict_fuel", {}) == {"ok": True}


def test_the_call_past_the_allowance_is_refused(handler: McpRequestHandler) -> None:
    caller = _client("Agen Satu")
    for _ in range(3):
        handler.call(caller, "predict_fuel", {})

    with pytest.raises(McpRateLimitError) as refused:
        handler.call(caller, "predict_fuel", {})

    # The agent has to learn it should back off, not that the server broke.
    assert "terlalu banyak" in str(refused.value).lower()


def test_a_refused_call_does_not_reach_the_tool() -> None:
    """The point of the limit: the work must not happen."""
    calls: list[int] = []
    registry = McpToolRegistry(
        tools=(
            McpTool(
                name="predict_fuel",
                description="",
                scope=AgentScope.PREDICT,
                input_schema={},
                handler=lambda _arguments: calls.append(1),
            ),
        )
    )
    audit = _Audit()
    handler = McpRequestHandler(
        registry=registry,
        resolve_credential=_Resolver(_client("Agen Satu")),
        record_audit=_RecordAudit(audit),
        max_calls_per_window=2,
        window_seconds=60,
        now=lambda: _NOW,
    )
    caller = _client("Agen Satu")
    handler.call(caller, "predict_fuel", {})
    handler.call(caller, "predict_fuel", {})

    with pytest.raises(McpRateLimitError):
        handler.call(caller, "predict_fuel", {})

    assert len(calls) == 2, "a throttled call still ran the tool"


def test_one_noisy_agent_does_not_throttle_another(handler: McpRequestHandler) -> None:
    """Per client, for the same reason each has its own revocable credential."""
    noisy = _client("Agen Satu")
    for _ in range(3):
        handler.call(noisy, "predict_fuel", {})

    quiet = _client("Agen Dua")

    assert handler.call(quiet, "predict_fuel", {}) == {"ok": True}


def test_the_window_moves_so_a_throttled_agent_recovers() -> None:
    """A limit an agent can never come back from would be an outage, not a limit."""
    audit = _Audit()
    clock = {"now": _NOW}
    handler = McpRequestHandler(
        registry=McpToolRegistry(
            tools=(
                McpTool(
                    name="predict_fuel",
                    description="",
                    scope=AgentScope.PREDICT,
                    input_schema={},
                    handler=lambda _arguments: {"ok": True},
                ),
            )
        ),
        resolve_credential=_Resolver(_client("Agen Satu")),
        record_audit=_RecordAudit(audit, lambda: clock["now"]),
        max_calls_per_window=2,
        window_seconds=60,
        now=lambda: clock["now"],
    )
    caller = _client("Agen Satu")
    handler.call(caller, "predict_fuel", {})
    handler.call(caller, "predict_fuel", {})
    with pytest.raises(McpRateLimitError):
        handler.call(caller, "predict_fuel", {})

    clock["now"] = _NOW + timedelta(seconds=61)

    assert handler.call(caller, "predict_fuel", {}) == {"ok": True}


def test_a_disabled_limit_serves_everything() -> None:
    """Zero means off, for a deployment that would rather not have one."""
    audit = _Audit()
    handler = McpRequestHandler(
        registry=McpToolRegistry(
            tools=(
                McpTool(
                    name="predict_fuel",
                    description="",
                    scope=AgentScope.PREDICT,
                    input_schema={},
                    handler=lambda _arguments: {"ok": True},
                ),
            )
        ),
        resolve_credential=_Resolver(_client("Agen Satu")),
        record_audit=_RecordAudit(audit),
        max_calls_per_window=0,
        window_seconds=60,
        now=lambda: _NOW,
    )
    caller = _client("Agen Satu")

    for _ in range(25):
        assert handler.call(caller, "predict_fuel", {}) == {"ok": True}


def test_a_rejected_call_does_not_extend_the_block() -> None:
    """A polling agent must be able to recover.

    Rate-limit rejections are audited under their own action rather than the
    `mcp_tool:` prefix the counter matches. Counting them would let each
    rejection push the window forward, so an agent that kept polling would
    never get out — and only one that went completely silent could. A polling
    agent is exactly the case this exists to handle.
    """
    audit = _Audit()
    clock = {"now": _NOW}
    handler = McpRequestHandler(
        registry=McpToolRegistry(
            tools=(
                McpTool(
                    name="predict_fuel",
                    description="",
                    scope=AgentScope.PREDICT,
                    input_schema={},
                    handler=lambda _arguments: {"ok": True},
                ),
            )
        ),
        resolve_credential=_Resolver(_client("Agen Satu")),
        record_audit=_RecordAudit(audit, lambda: clock["now"]),
        max_calls_per_window=2,
        window_seconds=60,
        now=lambda: clock["now"],
    )
    caller = _client("Agen Satu")
    handler.call(caller, "predict_fuel", {})
    handler.call(caller, "predict_fuel", {})

    # Keep polling throughout the block, as a stuck agent would.
    for offset in (10, 20, 30, 40, 50):
        clock["now"] = _NOW + timedelta(seconds=offset)
        with pytest.raises(McpRateLimitError):
            handler.call(caller, "predict_fuel", {})

    # Once the two real calls age out, the agent is served again even though it
    # never stopped trying.
    clock["now"] = _NOW + timedelta(seconds=61)

    assert handler.call(caller, "predict_fuel", {}) == {"ok": True}
