"""sync_token.py — Run this on your LAPTOP every morning after kite.login.

Reads the fresh access_token from kite/.access_token and pushes it to
the Azure VM, then restarts the bot service. Takes about 5 seconds.

Usage:
    python deploy/sync_token.py
"""
import sys
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────
# CONFIGURE THESE once after setting up the Azure VM
# ─────────────────────────────────────────────────────
AZURE_VM_IP   = "20.244.14.89"
AZURE_VM_USER = "azureuser"
SSH_KEY_PATH  = r"C:\Users\Chetan\.ssh\sensexbot_key"
REMOTE_DIR    = "/home/azureuser/sensexbot"
# ─────────────────────────────────────────────────────


def read_local_token() -> str:
    """Read the access token written by kite.login into kite/.access_token."""
    token_path = Path(__file__).parent.parent / "kite" / ".access_token"
    if not token_path.exists():
        print(f"ERROR: No token file found at {token_path}")
        print("       Please run:  python -m kite.login")
        sys.exit(1)
    token = token_path.read_text().strip()
    if not token:
        print("ERROR: Token file is empty. Please run:  python -m kite.login")
        sys.exit(1)
    return token


def run_ssh(command: str):
    cmd = [
        "ssh",
        "-i", SSH_KEY_PATH,
        "-o", "StrictHostKeyChecking=no",
        f"{AZURE_VM_USER}@{AZURE_VM_IP}",
        command
    ]
    subprocess.run(cmd, check=True)


def main():
    print("Reading token from kite/.access_token...")
    token = read_local_token()
    print(f"Token found: {token[:8]}...{token[-4:]}")

    print(f"Pushing token to Azure VM ({AZURE_VM_IP})...")
    # Write token directly to kite/.access_token on the VM (same path auth.py reads from)
    run_ssh(f"echo '{token}' > {REMOTE_DIR}/kite/.access_token")

    print("Restarting bot service on Azure VM...")
    run_ssh("sudo systemctl restart sensexbot")

    print("")
    print("[OK] Done! Bot is running on Azure with today's fresh token.")
    print(f"   Dashboard: http://{AZURE_VM_IP}:5050")
    print(f"   Stop bot:  ssh -i {SSH_KEY_PATH} {AZURE_VM_USER}@{AZURE_VM_IP} 'sudo systemctl stop sensexbot'")


if __name__ == "__main__":
    main()
