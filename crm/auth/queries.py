from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, insert, select, update
from werkzeug.security import generate_password_hash

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_login_attempts, crm_users

VALID_USER_ROLES = ("admin", "manager", "rep")


def get_user_by_email(email: str):
    statement = select(crm_users).where(func.lower(crm_users.c.email) == email.lower())
    with get_connection() as connection:
        result = connection.execute(statement).mappings().first()
    return dict(result) if result else None


def get_user_by_id(user_id: int | None):
    if not user_id:
        return None

    statement = select(crm_users).where(crm_users.c.id == user_id)
    with get_connection() as connection:
        result = connection.execute(statement).mappings().first()
    return dict(result) if result else None


def list_users(active_only: bool = False) -> list[dict]:
    statement = select(crm_users).order_by(
        crm_users.c.is_active.desc(),
        func.lower(crm_users.c.full_name),
        crm_users.c.id,
    )
    if active_only:
        statement = statement.where(crm_users.c.is_active.is_(True))
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def list_assignable_users() -> list[dict]:
    return list_users(active_only=True)


def get_users_by_ids(user_ids: list[int]) -> list[dict]:
    if not user_ids:
        return []
    statement = select(crm_users).where(crm_users.c.id.in_(user_ids))
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_users_by_emails(emails: list[str]) -> list[dict]:
    normalized = [email.strip().lower() for email in emails if email and email.strip()]
    if not normalized:
        return []
    statement = select(crm_users).where(func.lower(crm_users.c.email).in_(normalized))
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_user(email: str, password: str, full_name: str, role: str = "rep", is_active: bool = True) -> int:
    normalized_role = (role or "rep").strip().lower()
    if normalized_role not in VALID_USER_ROLES:
        raise ValueError(f"Invalid role: {role}")
    password_hash = generate_password_hash(password)
    statement = (
        insert(crm_users)
        .values(
            email=email.strip().lower(),
            password_hash=password_hash,
            full_name=full_name.strip(),
            role=normalized_role,
            is_active=is_active,
        )
        .returning(crm_users.c.id)
    )
    with get_connection() as connection:
        user_id = connection.execute(statement).scalar_one()
    return int(user_id)


def update_user(user_id: int, full_name: str, role: str, is_active: bool, password: str | None = None) -> None:
    normalized_role = (role or "rep").strip().lower()
    if normalized_role not in VALID_USER_ROLES:
        raise ValueError(f"Invalid role: {role}")

    values = {
        "full_name": full_name.strip(),
        "role": normalized_role,
        "is_active": is_active,
        "updated_at": datetime.now(timezone.utc),
    }
    if password:
        values["password_hash"] = generate_password_hash(password)

    statement = update(crm_users).where(crm_users.c.id == user_id).values(**values)
    with get_connection() as connection:
        connection.execute(statement)


def record_login_attempt(email: str, ip_address: str, successful: bool) -> None:
    statement = insert(crm_login_attempts).values(
        email=email.strip().lower(),
        ip_address=ip_address,
        successful=successful,
    )
    with get_connection() as connection:
        connection.execute(statement)


def count_recent_failed_attempts(ip_address: str, window_seconds: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    statement = select(func.count()).select_from(crm_login_attempts).where(
        crm_login_attempts.c.ip_address == ip_address,
        crm_login_attempts.c.successful.is_(False),
        crm_login_attempts.c.attempted_at >= cutoff,
    )
    with get_connection() as connection:
        return int(connection.execute(statement).scalar_one())


def clear_login_attempts(ip_address: str, email: str) -> None:
    statement = delete(crm_login_attempts).where(
        crm_login_attempts.c.ip_address == ip_address,
        func.lower(crm_login_attempts.c.email) == email.lower(),
    )
    with get_connection() as connection:
        connection.execute(statement)
