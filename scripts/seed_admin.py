import argparse
import sys

from sqlalchemy import select

from bridge_crm.crm.auth.queries import create_user
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_users


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the first Bridge CRM admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=["admin", "manager", "rep"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if len(args.password) < 12:
        raise SystemExit("Password must be at least 12 characters.")

    with get_connection() as connection:
        existing = connection.execute(
            select(crm_users.c.id).where(crm_users.c.email == args.email.lower())
        ).first()

    if existing:
        raise SystemExit(f"User already exists for {args.email.lower()}.")

    user_id = create_user(
        email=args.email,
        password=args.password,
        full_name=args.full_name,
        role=args.role,
    )
    print(f"Created user {args.email.lower()} with id={user_id}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
