# SENSEX Bot — Azure Deployment Guide

Follow these steps **once** to get the bot permanently running on Azure.

---

## Step 1: Generate SSH Keys (on your laptop)

Open PowerShell and run:

```powershell
ssh-keygen -t rsa -b 4096 -f "$HOME\.ssh\sensexbot_key" -N ""
```

This creates two files:
- `C:\Users\Chetan\.ssh\sensexbot_key` → **Private key** (stays on your laptop, never share)
- `C:\Users\Chetan\.ssh\sensexbot_key.pub` → **Public key** (uploaded to Azure)

Print the public key — you'll need it in Step 2:
```powershell
type "$HOME\.ssh\sensexbot_key.pub"
```
Copy the entire output line.

---

## Step 2: Create the Azure VM

1. Go to [portal.azure.com](https://portal.azure.com)
2. Click **Create a resource** → **Virtual Machine**
3. Fill in the form:

| Field | Value |
|---|---|
| **Resource Group** | Create new → `sensexbot-rg` |
| **VM Name** | `sensexbot-vm` |
| **Region** | Central India (lowest latency) |
| **Image** | Ubuntu Server 22.04 LTS |
| **Size** | **B1s** (1 vCPU, 1 GB RAM) — Free tier eligible |
| **Authentication type** | SSH public key |
| **Username** | `azureuser` |
| **SSH public key source** | Paste your key from Step 1 |

4. Click **Next: Networking**
5. Under **Inbound port rules**, add:
   - Port **22** (SSH) — already there
   - Click **Add inbound port rule** → Port **5050** → Protocol TCP → Name `dashboard`
6. Click **Review + create** → **Create**
7. **Note down the Public IP address** once the VM is created

---

## Step 3: Copy Bot Files to Azure

In PowerShell (from your TradingBot folder):

```powershell
# Copy all bot files to the VM
scp -i "$HOME\.ssh\sensexbot_key" -r . "azureuser@YOUR_VM_IP:~/sensexbot"
```

Replace `YOUR_VM_IP` with your actual Azure VM public IP.

---

## Step 4: SSH into the VM and Run Setup

```powershell
ssh -i "$HOME\.ssh\sensexbot_key" azureuser@YOUR_VM_IP
```

Once logged in, run the setup script:

```bash
cd ~/sensexbot
chmod +x deploy/setup_azure.sh
./deploy/setup_azure.sh
```

This installs Python, creates the venv, installs all packages, and registers the bot as a system service.

---

## Step 5: Configure sync_token.py on Your Laptop

Open `deploy/sync_token.py` and update the top 3 lines:

```python
AZURE_VM_IP   = "20.123.45.67"     # ← your actual VM IP
AZURE_VM_USER = "azureuser"        # ← leave as-is
SSH_KEY_PATH  = r"C:\Users\Chetan\.ssh\sensexbot_key"  # ← your private key
```

---

## Step 6: Test Everything

Do a test run on your laptop:

```bash
# Login to Kite
python -m kite.login

# Push token to Azure and start the bot
python deploy/sync_token.py
```

Then open your browser and go to `http://YOUR_VM_IP:5050` — you should see the dashboard!

---

## Your Daily Routine (Every Morning)

```bash
# Takes about 60 seconds total:
python -m kite.login
python deploy/sync_token.py
```

Done. The bot runs on Azure until 15:20. Open `http://YOUR_VM_IP:5050` from any device anywhere.

---

## Useful Commands

```bash
# View live bot logs
ssh -i "$HOME\.ssh\sensexbot_key" azureuser@YOUR_VM_IP "sudo journalctl -u sensexbot -f"

# Check bot status
ssh -i "$HOME\.ssh\sensexbot_key" azureuser@YOUR_VM_IP "sudo systemctl status sensexbot"

# Manually stop/start bot
ssh -i "$HOME\.ssh\sensexbot_key" azureuser@YOUR_VM_IP "sudo systemctl stop sensexbot"
ssh -i "$HOME\.ssh\sensexbot_key" azureuser@YOUR_VM_IP "sudo systemctl start sensexbot"
```

---

> **Note:** The B1s VM is free for 12 months on Azure's free tier. After that, it costs approximately ₹600-700/month. You can stop the VM on weekends to save cost (the bot doesn't need to run on weekends since markets are closed).
