"""KiteConnect client construction from stored credentials/access token."""
import os
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()


def get_kite_client() -> KiteConnect:
    """Build an authenticated KiteConnect client using the access token
    written by kite/login.py. Raises if no token file exists yet."""
    api_key = os.environ["KITE_API_KEY"]
    token_path = Path(os.environ.get("KITE_ACCESS_TOKEN_FILE", "kite/.access_token"))
    if not token_path.exists():
        raise RuntimeError(
            f"No access token at {token_path}. Run `python -m kite.login` first."
        )
    access_token = token_path.read_text().strip()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite
