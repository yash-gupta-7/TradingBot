#!/bin/bash
# setup_azure.sh
# Run this ONCE on your Azure VM after first SSH login.
# It installs Python, copies the bot, and registers it as a system service.

set -e
echo "================================================"
echo " SENSEX Bot - Azure VM Setup"
echo "================================================"

# ── 1. System packages ────────────────────────────────
echo "[1/6] Updating packages..."
sudo apt-get update -qq
sudo apt-get install -y python3.12 python3.12-venv python3-pip git unzip -qq

# ── 2. Project directory ──────────────────────────────
echo "[2/6] Creating project directory..."
mkdir -p ~/sensexbot
cd ~/sensexbot

# ── 3. Python virtual environment ────────────────────
echo "[3/6] Creating Python virtual environment..."
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q

# ── 4. Install dependencies ───────────────────────────
echo "[4/6] Installing Python dependencies..."
pip install -r requirements.txt flask flask-cors paramiko -q

# ── 5. Create log file ────────────────────────────────
touch ~/sensexbot/bot.log
chmod 644 ~/sensexbot/bot.log

# ── 6. Install systemd service ────────────────────────
echo "[5/6] Installing systemd service..."
USERNAME=$(whoami)
VENV_PYTHON="/home/${USERNAME}/sensexbot/.venv/bin/python"

sudo tee /etc/systemd/system/sensexbot.service > /dev/null <<EOF
[Unit]
Description=SENSEX Paper Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USERNAME}
WorkingDirectory=/home/${USERNAME}/sensexbot
ExecStart=${VENV_PYTHON} -m live.run_paper
Restart=on-failure
RestartSec=15
StandardOutput=append:/home/${USERNAME}/sensexbot/bot.log
StandardError=append:/home/${USERNAME}/sensexbot/bot.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sensexbot

echo ""
echo "================================================"
echo " Setup complete!"
echo " - Bot files should be in: ~/sensexbot/"
echo " - Start manually:  sudo systemctl start sensexbot"
echo " - View logs:       sudo journalctl -u sensexbot -f"
echo " - Dashboard:       http://$(curl -s ifconfig.me):5050"
echo "================================================"
