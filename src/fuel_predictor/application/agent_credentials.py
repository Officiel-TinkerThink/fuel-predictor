"""Issuing, resolving, and revoking MCP client credentials (ADR 0008, Phase 4)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import uuid4

from fuel_predictor.application.identity import RecordAuditEvent
from fuel_predictor.domain.identity import (
    AgentClient,
    AgentScope,
    AuditOutcome,
    IdentityValidationError,
)

_TOKEN_PREFIX = "fpa_"


class AgentClientRepository(Protocol):
    def add(self, client: AgentClient) -> None: ...

    def get_by_token_hash(self, token_hash: str) -> AgentClient | None: ...

    def get(self, client_id: str) -> AgentClient | None: ...

    def list_clients(self) -> Sequence[AgentClient]: ...

    def replace(self, client: AgentClient) -> None: ...


@dataclass(frozen=True, slots=True)
class IssuedAgentCredential:
    """The one and only time the raw token exists outside the caller's hands."""

    client: AgentClient
    token: str


@dataclass(frozen=True, slots=True)
class IssueAgentCredential:
    repository: AgentClientRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self, name: str, scopes: frozenset[AgentScope], issued_by: str
    ) -> IssuedAgentCredential:
        cleaned = name.strip()
        if not cleaned:
            raise IdentityValidationError("name", "Nama klien agen wajib diisi.")
        if len(cleaned) > 128:
            raise IdentityValidationError("name", "Nama klien agen maksimal 128 karakter.")
        if not scopes:
            raise IdentityValidationError(
                "scopes", "Pilih sedikitnya satu cakupan; klien tanpa cakupan tidak berguna."
            )

        # Prefixed so a leaked token is recognisable in logs and secret
        # scanners, and random enough that guessing is not a threat.
        token = f"{_TOKEN_PREFIX}{token_urlsafe(32)}"
        client = AgentClient(
            client_id=f"AGT-{uuid4().hex[:20]}",
            name=cleaned,
            scopes=frozenset(scopes),
            token_hash=hash_agent_token(token),
            created_at=self.now(),
            is_active=True,
        )
        self.repository.add(client)
        self.record_audit.execute(
            actor=issued_by,
            action="agent_credential_issued",
            outcome=AuditOutcome.SUCCEEDED,
            subject=client.name,
            details={"client_id": client.client_id, "scopes": ",".join(sorted(scopes))},
        )
        # Returned once and never stored in plain form: the hash is all the
        # database keeps, so a lost token is reissued rather than recovered.
        return IssuedAgentCredential(client=client, token=token)


@dataclass(frozen=True, slots=True)
class ResolveAgentCredential:
    repository: AgentClientRepository

    def execute(self, token: str | None) -> AgentClient | None:
        if not token:
            return None
        client = self.repository.get_by_token_hash(hash_agent_token(token))
        if client is None or not client.is_active:
            return None
        return client


@dataclass(frozen=True, slots=True)
class RevokeAgentCredential:
    repository: AgentClientRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, client_id: str, revoked_by: str) -> AgentClient:
        client = self.repository.get(client_id)
        if client is None:
            raise IdentityValidationError("client_id", "Klien agen tidak ditemukan.")

        revoked = AgentClient(
            client_id=client.client_id,
            name=client.name,
            scopes=client.scopes,
            token_hash=client.token_hash,
            created_at=client.created_at,
            is_active=False,
            revoked_at=self.now(),
        )
        self.repository.replace(revoked)
        self.record_audit.execute(
            actor=revoked_by,
            action="agent_credential_revoked",
            outcome=AuditOutcome.SUCCEEDED,
            subject=client.name,
            details={"client_id": client.client_id},
        )
        return revoked


@dataclass(frozen=True, slots=True)
class ListAgentClients:
    repository: AgentClientRepository

    def execute(self) -> tuple[AgentClient, ...]:
        return tuple(self.repository.list_clients())


def hash_agent_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
