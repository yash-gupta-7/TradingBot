"""sync_token.py — Run this on your LAPTOP every morning after kite.login.

It reads the fresh access_token from your local .env and pushes it to
the Azure VM, then restarts the bot service. Takes about 5 seconds.

Usage:
    python deploy/sync_token.py
"""
import os
import sys
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────
# CONFIGURE THESE once after setting up the Azure VM
# ─────────────────────────────────────────────────────
AZURE_VM_IP   = "YOUR_AZURE_VM_IP"   # e.g. "20.123.45.67"
AZURE_VM_USER = "azureuser"          # default Azure username
SSH_KEY_PATH  = str(Path.home() / ".ssh" / "sensexbot_key")  # private key path
REMOTE_DIR    = "/home/azureuser/sensexbot"
# ─────────────────────────────────────────────────────

def read_local_env() -> dict:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print(f"ERROR: .env not found at {env_path}")
        sys.exit(1)
    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values

def run_ssh(command: str, capture: bool = False):
    cmd = [
        "ssh",
        "-i", SSH_KEY_PATH,
        "-o", "StrictHostKeyChecking=no",
        f"{AZURE_VM_USER}@{AZURE_VM_IP}",
        command
    ]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True)
    subprocess.run(cmd, check=True)

def main():
    if AZURE_VM_IP == "YOUR_AZURE_VM_IP":
        print("ERROR: Please set AZURE_VM_IP in deploy/sync_token.py first.")
        sys.exit(1)

    print("Reading local .env...")
    env = read_local_env()
    token = env.get("KITE_ACCESS_TOKEN") or env.get("ACCESS_TOKEN")
    if not token:
        print("ERROR: KITE_ACCESS_TOKEN not found in .env. Did you run kite.login?")
        sys.exit(1)

    print(f"Token found: {token[:8]}...{token[-4:]}")

    # Build the remote sed command to update only the access token line
    print(f"Pushing token to Azure VM ({AZURE_VM_IP})...")
    run_ssh(
        f"sed -i 's/^KITE_ACCESS_TOKEN=.*/KITE_ACCESS_TOKEN={token}/' {REMOTE_DIR}/.env && "
        f"echo 'Token updated on VM.'"
    )

    print("Restarting bot service on Azure VM...")
    run_ssh("sudo systemctl restart sensexbot")

    print("")
    print("✅ Done! Bot is running on Azure with today's fresh token.")
    print(f"   Dashboard: http://{AZURE_VM_IP}:5050")
    print(f"   Logs:      ssh -i {SSH_KEY_PATH} {AZURE_VM_USER}@{AZURE_VM_IP} 'sudo journalctl -u sensexbot -f'")

if __name__ == "__main__":
    main()
