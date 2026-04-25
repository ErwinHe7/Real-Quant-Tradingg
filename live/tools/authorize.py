"""
Authorization tool — hash and register a live_authorization.yaml file.

Usage:
    python -m live.tools.authorize

The operator must have manually edited live/state/live_authorization.yaml
before running this command.  This command only records the hash; it does
not validate the content or grant any permissions.

The agent is NEVER authorized to run this command autonomously.
"""
import sys
from pathlib import Path


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Hash and register a live authorization file")
    parser.add_argument("--auth-file", default="live/state/live_authorization.yaml")
    args = parser.parse_args(argv)

    auth_file = Path(args.auth_file)
    from live.auth import register_authorization
    try:
        file_hash = register_authorization(auth_file)
        print(f"Authorization registered. SHA256: {file_hash}")
        print(f"Hash appended to live/state/auth_hashes.jsonl")
        return 0
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
