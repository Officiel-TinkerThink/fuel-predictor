"""PostgreSQL/SQLite persistence for OAuth agent grants (ADR 0014)."""

from datetime import UTC, datetime

from sqlalchemy import delete, or_, select

from fuel_predictor.domain.agent_authorization import (
    AgentGrant,
    AuthorizationCode,
    RegisteredAgentClient,
)
from fuel_predictor.domain.identity import AgentScope
from fuel_predictor.infrastructure.database import (
    AgentGrantRow,
    AgentRegistrationRow,
    AuthorizationCodeRow,
    SessionFactory,
)


class SqlAlchemyAgentRegistrationRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, registration: RegisteredAgentClient) -> None:
        with self._session_factory.begin() as session:
            session.add(
                AgentRegistrationRow(
                    registration_id=registration.registration_id,
                    client_name=registration.client_name,
                    redirect_uris=sorted(registration.redirect_uris),
                    registered_at=registration.registered_at,
                )
            )

    def get(self, registration_id: str) -> RegisteredAgentClient | None:
        with self._session_factory() as session:
            row = session.get(AgentRegistrationRow, registration_id)
            return _registration(row) if row is not None else None


class SqlAlchemyAuthorizationCodeRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, code: AuthorizationCode) -> None:
        with self._session_factory.begin() as session:
            session.add(
                AuthorizationCodeRow(
                    code_hash=code.code_hash,
                    registration_id=code.registration_id,
                    user_id=code.user_id,
                    scopes=sorted(str(scope) for scope in code.scopes),
                    redirect_uri=code.redirect_uri,
                    code_challenge=code.code_challenge,
                    issued_at=code.issued_at,
                    expires_at=code.expires_at,
                    redeemed_at=code.redeemed_at,
                )
            )

    def get(self, code_hash: str) -> AuthorizationCode | None:
        with self._session_factory() as session:
            row = session.get(AuthorizationCodeRow, code_hash)
            return _code(row) if row is not None else None

    def replace(self, code: AuthorizationCode) -> None:
        with self._session_factory.begin() as session:
            row = session.get(AuthorizationCodeRow, code.code_hash)
            if row is None:
                return
            row.redeemed_at = code.redeemed_at

    def delete_expired(self, moment: datetime) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                delete(AuthorizationCodeRow).where(AuthorizationCodeRow.expires_at <= moment)
            )


class SqlAlchemyAgentGrantRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, grant: AgentGrant) -> None:
        with self._session_factory.begin() as session:
            session.add(
                AgentGrantRow(
                    grant_id=grant.grant_id,
                    registration_id=grant.registration_id,
                    user_id=grant.user_id,
                    scopes=sorted(str(scope) for scope in grant.scopes),
                    access_token_hash=grant.access_token_hash,
                    access_token_expires_at=grant.access_token_expires_at,
                    refresh_token_hash=grant.refresh_token_hash,
                    refresh_token_expires_at=grant.refresh_token_expires_at,
                    granted_at=grant.granted_at,
                    refreshed_at=grant.refreshed_at,
                    revoked_at=grant.revoked_at,
                    label=grant.label,
                    previous_refresh_token_hash=grant.previous_refresh_token_hash,
                )
            )

    def get(self, grant_id: str) -> AgentGrant | None:
        with self._session_factory() as session:
            row = session.get(AgentGrantRow, grant_id)
            return _grant(row) if row is not None else None

    def get_by_access_token_hash(self, token_hash: str) -> AgentGrant | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AgentGrantRow).where(AgentGrantRow.access_token_hash == token_hash)
            ).scalar_one_or_none()
            return _grant(row) if row is not None else None

    def get_by_refresh_token_hash(self, token_hash: str) -> AgentGrant | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AgentGrantRow).where(
                    or_(
                        AgentGrantRow.refresh_token_hash == token_hash,
                        AgentGrantRow.previous_refresh_token_hash == token_hash,
                    )
                )
            ).scalar_one_or_none()
            return _grant(row) if row is not None else None

    def list_grants(self, user_id: str | None = None) -> tuple[AgentGrant, ...]:
        with self._session_factory() as session:
            query = select(AgentGrantRow).order_by(AgentGrantRow.granted_at.desc())
            if user_id is not None:
                query = query.where(AgentGrantRow.user_id == user_id)
            rows = session.execute(query).scalars().all()
        return tuple(_grant(row) for row in rows)

    def delete(self, grant_id: str) -> None:
        with self._session_factory.begin() as session:
            row = session.get(AgentGrantRow, grant_id)
            if row is not None:
                session.delete(row)

    def replace(self, grant: AgentGrant) -> None:
        with self._session_factory.begin() as session:
            row = session.get(AgentGrantRow, grant.grant_id)
            if row is None:
                return
            row.access_token_hash = grant.access_token_hash
            row.access_token_expires_at = grant.access_token_expires_at
            row.refresh_token_hash = grant.refresh_token_hash
            row.refresh_token_expires_at = grant.refresh_token_expires_at
            row.refreshed_at = grant.refreshed_at
            row.revoked_at = grant.revoked_at
            row.label = grant.label
            row.previous_refresh_token_hash = grant.previous_refresh_token_hash


def _registration(row: AgentRegistrationRow) -> RegisteredAgentClient:
    return RegisteredAgentClient(
        registration_id=row.registration_id,
        client_name=row.client_name,
        redirect_uris=frozenset(row.redirect_uris),
        registered_at=_aware(row.registered_at),
    )


def _code(row: AuthorizationCodeRow) -> AuthorizationCode:
    return AuthorizationCode(
        code_hash=row.code_hash,
        registration_id=row.registration_id,
        user_id=row.user_id,
        scopes=frozenset(AgentScope(scope) for scope in row.scopes),
        redirect_uri=row.redirect_uri,
        code_challenge=row.code_challenge,
        issued_at=_aware(row.issued_at),
        expires_at=_aware(row.expires_at),
        redeemed_at=_optional_aware(row.redeemed_at),
    )


def _grant(row: AgentGrantRow) -> AgentGrant:
    return AgentGrant(
        grant_id=row.grant_id,
        registration_id=row.registration_id,
        user_id=row.user_id,
        scopes=frozenset(AgentScope(scope) for scope in row.scopes),
        access_token_hash=row.access_token_hash,
        access_token_expires_at=_aware(row.access_token_expires_at),
        refresh_token_hash=row.refresh_token_hash,
        refresh_token_expires_at=_aware(row.refresh_token_expires_at),
        granted_at=_aware(row.granted_at),
        refreshed_at=_optional_aware(row.refreshed_at),
        revoked_at=_optional_aware(row.revoked_at),
        label=row.label,
        previous_refresh_token_hash=row.previous_refresh_token_hash,
    )


def _aware(moment: datetime) -> datetime:
    """SQLite loses the timezone that PostgreSQL preserves; normalise to UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _optional_aware(moment: datetime | None) -> datetime | None:
    return _aware(moment) if moment is not None else None
