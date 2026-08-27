from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, func, select

from fuel_predictor.domain.identity import (
    AgentClient,
    AgentScope,
    AuditOutcome,
    AuditRecord,
    AuthenticatedSession,
    User,
    UserRole,
)
from fuel_predictor.infrastructure.database import (
    AgentClientRow,
    AuditRecordRow,
    SessionFactory,
    UserRow,
    UserSessionRow,
)


class SqlAlchemyUserRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, user: User) -> None:
        with self._session_factory.begin() as session:
            session.add(
                UserRow(
                    user_id=user.user_id,
                    username=user.username,
                    full_name=user.full_name,
                    role=str(user.role),
                    password_hash=user.password_hash,
                    is_active=user.is_active,
                    created_at=user.created_at,
                )
            )

    def get(self, user_id: str) -> User | None:
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
            return _user(row) if row is not None else None

    def get_by_username(self, username: str) -> User | None:
        with self._session_factory() as session:
            row = session.execute(
                select(UserRow).where(UserRow.username == username)
            ).scalar_one_or_none()
            return _user(row) if row is not None else None

    def list_users(self) -> tuple[User, ...]:
        with self._session_factory() as session:
            rows = session.execute(select(UserRow).order_by(UserRow.username)).scalars().all()
        return tuple(_user(row) for row in rows)

    def replace(self, user: User) -> None:
        with self._session_factory.begin() as session:
            row = session.get(UserRow, user.user_id)
            if row is None:
                return
            row.full_name = user.full_name
            row.role = str(user.role)
            row.password_hash = user.password_hash
            row.is_active = user.is_active


class SqlAlchemySessionRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, session_record: AuthenticatedSession) -> None:
        with self._session_factory.begin() as session:
            session.add(
                UserSessionRow(
                    token_hash=session_record.token_hash,
                    user_id=session_record.user_id,
                    created_at=session_record.created_at,
                    expires_at=session_record.expires_at,
                    last_seen_at=session_record.last_seen_at,
                    csrf_token=session_record.csrf_token,
                )
            )

    def get(self, token_hash: str) -> AuthenticatedSession | None:
        with self._session_factory() as session:
            row = session.get(UserSessionRow, token_hash)
            if row is None:
                return None
            return AuthenticatedSession(
                token_hash=row.token_hash,
                user_id=row.user_id,
                created_at=_aware(row.created_at),
                expires_at=_aware(row.expires_at),
                last_seen_at=_aware(row.last_seen_at),
                csrf_token=row.csrf_token,
            )

    def touch(self, token_hash: str, last_seen_at: datetime) -> None:
        with self._session_factory.begin() as session:
            row = session.get(UserSessionRow, token_hash)
            if row is not None:
                row.last_seen_at = last_seen_at

    def delete(self, token_hash: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(UserSessionRow).where(UserSessionRow.token_hash == token_hash))

    def delete_for_user(self, user_id: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(UserSessionRow).where(UserSessionRow.user_id == user_id))

    def delete_expired(self, moment: datetime) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(UserSessionRow).where(UserSessionRow.expires_at <= moment))


class SqlAlchemyAuditRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, record: AuditRecord) -> None:
        with self._session_factory.begin() as session:
            session.add(
                AuditRecordRow(
                    audit_id=record.audit_id,
                    occurred_at=record.occurred_at,
                    actor=record.actor,
                    actor_kind=record.actor_kind,
                    action=record.action,
                    outcome=str(record.outcome),
                    subject=record.subject,
                    details=dict(record.details),
                )
            )

    def list_recent(self, limit: int) -> tuple[AuditRecord, ...]:
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(AuditRecordRow)
                    .order_by(AuditRecordRow.occurred_at.desc(), AuditRecordRow.audit_id.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        return tuple(
            AuditRecord(
                audit_id=row.audit_id,
                occurred_at=_aware(row.occurred_at),
                actor=row.actor,
                actor_kind=row.actor_kind,
                action=row.action,
                outcome=AuditOutcome(row.outcome),
                subject=row.subject,
                details=cast("dict[str, str | int | float | bool | None]", row.details),
            )
            for row in rows
        )

    def count_recent_by_actor(self, actor: str, action_prefix: str, since: datetime) -> int:
        with self._session_factory() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(AuditRecordRow)
                    .where(
                        AuditRecordRow.actor == actor,
                        AuditRecordRow.action.startswith(action_prefix),
                        AuditRecordRow.occurred_at >= since,
                    )
                ).scalar_one()
            )

    def count_recent(self, action: str, subject: str, since: datetime) -> int:
        with self._session_factory() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(AuditRecordRow)
                    .where(
                        AuditRecordRow.action == action,
                        AuditRecordRow.subject == subject,
                        AuditRecordRow.occurred_at >= since,
                    )
                ).scalar_one()
            )


def _user(row: UserRow) -> User:
    return User(
        user_id=row.user_id,
        username=row.username,
        full_name=row.full_name,
        role=UserRole(row.role),
        password_hash=row.password_hash,
        is_active=row.is_active,
        created_at=_aware(row.created_at),
    )


def _aware(moment: datetime) -> datetime:
    """SQLite loses the timezone that PostgreSQL preserves; normalise to UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class SqlAlchemyAgentClientRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, client: AgentClient) -> None:
        with self._session_factory.begin() as session:
            session.add(
                AgentClientRow(
                    client_id=client.client_id,
                    name=client.name,
                    scopes=sorted(str(scope) for scope in client.scopes),
                    token_hash=client.token_hash,
                    created_at=client.created_at,
                    is_active=client.is_active,
                    revoked_at=client.revoked_at,
                )
            )

    def get_by_token_hash(self, token_hash: str) -> AgentClient | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AgentClientRow).where(AgentClientRow.token_hash == token_hash)
            ).scalar_one_or_none()
            return _agent(row) if row is not None else None

    def get(self, client_id: str) -> AgentClient | None:
        with self._session_factory() as session:
            row = session.get(AgentClientRow, client_id)
            return _agent(row) if row is not None else None

    def list_clients(self) -> tuple[AgentClient, ...]:
        with self._session_factory() as session:
            rows = session.execute(
                select(AgentClientRow).order_by(AgentClientRow.created_at.desc())
            ).scalars().all()
        return tuple(_agent(row) for row in rows)

    def replace(self, client: AgentClient) -> None:
        with self._session_factory.begin() as session:
            row = session.get(AgentClientRow, client.client_id)
            if row is None:
                return
            row.name = client.name
            row.scopes = sorted(str(scope) for scope in client.scopes)
            row.is_active = client.is_active
            row.revoked_at = client.revoked_at


def _agent(row: AgentClientRow) -> AgentClient:
    return AgentClient(
        client_id=row.client_id,
        name=row.name,
        scopes=frozenset(AgentScope(scope) for scope in row.scopes),
        token_hash=row.token_hash,
        created_at=_aware(row.created_at),
        is_active=row.is_active,
        revoked_at=_aware(row.revoked_at) if row.revoked_at is not None else None,
    )
