"""One-off daily login: exchange a request_token for an access_token.

Kite Connect access tokens expire every day. Run this once per trading day:
    python -m kite.login
It prints a login URL, you log in in the browser, paste the redirected
request_token back here, and it saves the access token to disk.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()


def main() -> None:
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    token_path = Path(os.environ.get("KITE_ACCESS_TOKEN_FILE", "kite/.access_token"))

    kite = KiteConnect(api_key=api_key)
    print("Login URL:", kite.login_url())
    request_token = input("Paste the request_token from the redirect URL: ").strip()

    session = kite.generate_session(request_token, api_secret=api_secret)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(session["access_token"])
    print(f"Access token saved to {token_path}")


if __name__ == "__main__":
    main()
