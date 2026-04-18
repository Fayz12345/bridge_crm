import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge CRM ERP sync placeholder.")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    mode = "full" if args.full else "incremental"
    print(f"ERP sync scaffold is in place, but remote API/database credentials are not configured yet. Requested mode: {mode}.")


if __name__ == "__main__":
    main()
