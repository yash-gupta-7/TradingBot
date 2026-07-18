"""Manual kill switch: immediately halts live trading and, if a position
is open, market-exits it.

    python -m live.kill_switch --port 5050
"""
import argparse
import sys
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten and halt the running live bot")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    req = urllib.request.Request(f"http://localhost:{args.port}/api/kill", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.read().decode())
    except Exception as e:
        print(f"Kill switch request failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
