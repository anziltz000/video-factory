# 🎬 VideoFactory — Full Setup Guide

**What this does:**  
Telegram bot receives a video link → Processor downloads it, burns the campaign logo in, re-encodes → n8n uploads it to YouTube Shorts and/or Instagram Reels → Sends you a Telegram confirmation with the link.

All three services (bot, processor, n8n) run on **one Oracle Cloud VM** using Docker Compose.

---

## 📂 Project Structure

```
videofactory/
├── bot/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── telegram_main.py
├── processor/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── processor_api.py
├── assets/
│   └── campaign-logos/
│       ├── README.txt         ← put your logo .mp4 files here
│       ├── LEONBET-LOGO.mp4   (you upload these manually)
│       ├── Bitz.io-LOGO.mp4
│       ├── ACEBET-LOGO.mp4
│       └── RajBet-LOGO.mp4
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## PART 1 — Create the GitHub Repository

1. Go to **https://github.com/new**
2. Repository name: `videofactory`
3. Set to **Private** (your credentials are in .env but still good practice)
4. Click **Create repository**
5. On your local computer, run:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/videofactory.git
cd videofactory
```

6. Copy all the project files into this folder, then push:

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

> ⚠️ Make sure `.env` is in `.gitignore` (it already is). Never push your tokens.

---

## PART 2 — Create the Oracle Cloud VM

### Step 1 — Sign Up / Log In
Go to **https://cloud.oracle.com** → Sign In or Create Free Account.

### Step 2 — Create a VM Instance

1. In the Oracle Cloud console, go to **Menu → Compute → Instances**
2. Click **Create Instance**
3. Fill in:
   - **Name:** `videofactory`
   - **Image:** Click "Change Image" → Select **Ubuntu 22.04**
   - **Shape:** Click "Change Shape"
     - Select **Ampere** (ARM)
     - Shape: `VM.Standard.A1.Flex`
     - OCPUs: **4**
     - Memory: **24 GB**
     - *(This is FREE — Oracle gives you 4 ARM cores + 24GB for free forever)*
4. **SSH Keys:** 
   - If you have an SSH key: upload your public key
   - If you don't: click "Save Private Key" and save the downloaded `.key` file safely
5. Click **Create**

Wait ~2 minutes for the instance to show as **Running**.

### Step 3 — Note your Public IP
On the instance details page, copy your **Public IP address** (looks like `140.238.12.34`).

### Step 4 — Open the Required Ports (Firewall)

Oracle blocks all ports by default. You need to open 3 ports.

1. On the instance page, click your **VCN** (Virtual Cloud Network) link
2. Click **Security Lists** → **Default Security List**
3. Click **Add Ingress Rules** and add these 3 rules (one at a time):

| Rule | Source CIDR | Protocol | Destination Port |
|------|------------|----------|-----------------|
| n8n  | 0.0.0.0/0  | TCP      | 5678            |
| Processor | 0.0.0.0/0 | TCP | 10000         |
| SSH (already exists) | 0.0.0.0/0 | TCP | 22 |

4. Also run this **on the VM itself** to open the OS firewall (iptables):

```bash
sudo iptables -I INPUT -p tcp --dport 5678 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 10000 -j ACCEPT
sudo netfilter-persistent save
```

---

## PART 3 — Set Up the VM

### Step 1 — SSH into your VM

```bash
ssh -i /path/to/your/saved.key ubuntu@YOUR_ORACLE_VM_PUBLIC_IP
```

*(If you used the Oracle-generated key, the file ends in `.key`. On Mac/Linux run `chmod 400 yourfile.key` first.)*

### Step 2 — Install Docker

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to the docker group (so you don't need sudo every time)
sudo usermod -aG docker ubuntu

# Install Docker Compose plugin
sudo apt-get install -y docker-compose-plugin

# Log out and back in for group change to take effect
exit
```

SSH back in:
```bash
ssh -i /path/to/your/saved.key ubuntu@YOUR_ORACLE_VM_PUBLIC_IP
```

Verify Docker works:
```bash
docker --version
docker compose version
```

### Step 3 — Install iptables-persistent (to save firewall rules on reboot)

```bash
sudo apt-get install -y iptables-persistent
sudo iptables -I INPUT -p tcp --dport 5678 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 10000 -j ACCEPT
sudo netfilter-persistent save
```

### Step 4 — Clone your repository

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/videofactory.git
cd videofactory
```

---

## PART 4 — Configure Your Environment

### Step 1 — Create your .env file

```bash
cp .env.example .env
nano .env
```

Fill in:
```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
N8N_HOST=YOUR_ORACLE_VM_PUBLIC_IP        # e.g. 140.238.12.34
N8N_USER=admin
N8N_PASSWORD=pick_a_strong_password_here
N8N_WEBHOOK_URL=http://YOUR_IP:5678/webhook/render-receiver
```

Save and close: `Ctrl+O` then `Enter` then `Ctrl+X`

### Step 2 — Upload your logo files

From your **local computer** (not the VM), run:

```bash
scp -i /path/to/your.key LEONBET-LOGO.mp4    ubuntu@YOUR_IP:~/videofactory/assets/campaign-logos/
scp -i /path/to/your.key Bitz.io-LOGO.mp4   ubuntu@YOUR_IP:~/videofactory/assets/campaign-logos/
scp -i /path/to/your.key ACEBET-LOGO.mp4    ubuntu@YOUR_IP:~/videofactory/assets/campaign-logos/
scp -i /path/to/your.key RajBet-LOGO.mp4    ubuntu@YOUR_IP:~/videofactory/assets/campaign-logos/
```

Verify they're there:
```bash
ls -lh ~/videofactory/assets/campaign-logos/
```

---

## PART 5 — Start Everything

```bash
cd ~/videofactory

# Build and start all services in the background
docker compose up -d --build
```

This will take 3–5 minutes the first time (downloading base images, installing packages).

Check everything is running:
```bash
docker compose ps
```

You should see all 3 services as **Up**:
```
NAME           STATUS
vf-bot         Up
vf-processor   Up
vf-n8n         Up
```

Watch live logs:
```bash
docker compose logs -f
```

---

## PART 6 — Set Up n8n Workflow

### Step 1 — Open n8n in your browser

Go to: `http://YOUR_ORACLE_VM_PUBLIC_IP:5678`

Log in with the `N8N_USER` and `N8N_PASSWORD` you set in `.env`.

### Step 2 — Import your workflow

1. Click the **≡ menu** → **Workflows** → **Import from File**
2. Upload `VideoFactory.json` (the n8n workflow file in this repo)
3. Click **Save**

### Step 3 — Reconnect credentials inside n8n

The imported workflow has placeholder credentials. You need to reconnect:

**YouTube:**
1. Click the "Upload a video" node
2. Click the credential → **Create New**
3. Follow OAuth flow to connect your YouTube account

**Instagram:**
1. Click the "Upload an asset from file data" node (Cloudinary) → update or remove
2. Click the "Publish" node → reconnect your Instagram account credential

**Telegram (for notifications):**
1. Click any "Send a text message" node
2. Update the **Chat ID** to your own Telegram user ID
   - To find your ID: message @userinfobot on Telegram
3. Reconnect your Telegram Bot credential

**Cloudinary (for Instagram workflow):**
- The n8n workflow uploads to Cloudinary first, then publishes to Instagram via URL
- Update the Cloudinary node with your Cloudinary account credentials

### Step 4 — Activate the workflow and get the webhook URL

1. Toggle the workflow to **Active** (top right)
2. Click the **Webhook** node
3. Copy the **Production URL** — it looks like:
   `http://YOUR_IP:5678/webhook/render-receiver`

### Step 5 — Update .env with the webhook URL

```bash
cd ~/videofactory
nano .env
```

Update `N8N_WEBHOOK_URL` to the exact URL you copied, then restart:

```bash
docker compose restart bot
```

---

## PART 7 — Test It

1. Open Telegram, find your bot
2. Send a YouTube Shorts or Instagram Reel link
3. Select campaign → position → upload target
4. You should see: `✅ Processing now!`
5. A few minutes later, you'll get a Telegram message with the uploaded video link

---

## Useful Commands

```bash
# View live logs for all services
docker compose logs -f

# View logs for one service only
docker compose logs -f processor
docker compose logs -f bot
docker compose logs -f n8n

# Restart everything
docker compose restart

# Restart one service
docker compose restart processor

# Stop everything
docker compose down

# Pull latest code from GitHub and rebuild
git pull
docker compose up -d --build

# Check disk usage
df -h

# Check how much RAM/CPU is being used
docker stats
```

---

## Troubleshooting

**Bot doesn't respond:**
```bash
docker compose logs bot
```
Check that `TELEGRAM_TOKEN` is correct in `.env`.

**"Logo not found" error:**
```bash
ls ~/videofactory/assets/campaign-logos/
```
Make sure the filenames match exactly (case-sensitive).

**n8n webhook not receiving:**
- Check port 5678 is open in Oracle Security List
- Make sure `N8N_WEBHOOK_URL` in `.env` has the right IP
- Make sure the workflow is **Active** in n8n

**Video processing fails:**
```bash
docker compose logs processor
```
FFmpeg errors will show the exact problem.

**Out of disk space:**
```bash
df -h
docker system prune -f   # removes unused images/containers
```

---

## Architecture Overview

```
User
 │  (sends video link)
 ▼
Telegram Bot  (vf-bot)
 │  POST /process  →  internal Docker network
 ▼
Video Processor  (vf-processor)
 │  1. yt-dlp downloads video
 │  2. FFmpeg: scale + overlay logo + high-quality encode
 │  3. POST video file to n8n webhook
 ▼
n8n  (vf-n8n)
 │  Switch on target (insta / yt / both)
 ├─► YouTube Shorts upload
 └─► Instagram Reels upload (via Cloudinary → Instagram API)
 │  Send Telegram notification with link
 ▼
User gets Telegram message with live video link ✅
```
