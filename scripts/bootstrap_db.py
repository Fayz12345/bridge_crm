from bridge_crm.db.bootstrap import initialize_database


def main() -> None:
    initialize_database()
    print("Bridge CRM schema initialized and default pipeline stages seeded.")


if __name__ == "__main__":
    main()
