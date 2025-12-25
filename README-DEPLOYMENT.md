# Deployment Guide

## Auto CI/CD Setup with GitHub Actions

This bot automatically builds and deploys when you push to the `main` branch.

### How it works:
1. Push code to GitHub → Triggers GitHub Actions
2. GitHub Actions builds Docker image → Pushes to GitHub Container Registry (ghcr.io)
3. Watchtower on your server polls every 5 minutes → Auto-pulls and restarts container

---

## One-Time Server Setup

### 1. Get a VPS
- DigitalOcean, Vultr, Linode, or AWS EC2
- Ubuntu 22.04 LTS
- 1GB RAM minimum ($5-10/month)

### 2. Install Docker on Server

```bash
# SSH into your server
ssh root@your-server-ip

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose-plugin -y

# Verify installation
docker --version
docker compose version
```

### 3. Set Up Bot on Server

```bash
# Create bot directory
mkdir -p ~/meme-arb-bot
cd ~/meme-arb-bot

# Create .env file with your credentials
nano .env
```

**Add your secrets to `.env`:**
```bash
# Binance Futures
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# Solana & Jupiter
SOLANA_PRIVATE_KEY=your_solana_private_key_base58
JUPITER_API_KEY=your_jupiter_api_key

# OKX DEX (optional)
OKX_API_KEY=your_okx_api_key
OKX_SECRET_KEY=your_okx_secret_key
OKX_PASSPHRASE=your_okx_passphrase
BSC_PRIVATE_KEY=your_bsc_private_key
```

**Download docker-compose.yml:**
```bash
# Get the docker-compose file from your repo
curl -o docker-compose.yml https://raw.githubusercontent.com/jerry-curaga/meme-arb-bot/main/docker-compose.yml

# Make container registry public (one-time, on GitHub)
# Go to: https://github.com/jerry-curaga/meme-arb-bot/pkgs/container/meme-arb-bot
# Click "Package settings" → Change visibility to "Public"
```

### 4. Start the Bot

```bash
# Pull and start containers
docker compose up -d

# View logs
docker compose logs -f arb-bot

# Check status
docker ps
```

---

## Usage

### Deploy New Changes
```bash
# On your local machine
git add .
git commit -m "Update bot"
git push origin main

# Bot will auto-update on server within 5 minutes
```

### Server Management Commands

```bash
# View live logs
docker compose logs -f arb-bot

# Restart bot
docker compose restart arb-bot

# Stop bot
docker compose stop arb-bot

# Start bot
docker compose start arb-bot

# Update immediately (don't wait for Watchtower)
docker compose pull && docker compose up -d

# View bot status
docker ps
```

### Monitor from Anywhere

```bash
# SSH and tail logs
ssh user@server "docker logs -f meme-arb-bot"

# Check last 50 log lines
ssh user@server "docker logs --tail 50 meme-arb-bot"

# Check for errors
ssh user@server "docker logs meme-arb-bot 2>&1 | grep ERROR"
```

---

## Configuration

### Change Trading Parameters

Edit `docker-compose.yml` on server:
```yaml
command: python bot.py --mode trade --symbol PIPPINUSDT --usd-amount 100 --no-hedge
```

Then restart:
```bash
docker compose up -d
```

### Run Multiple Bots

Add more services in `docker-compose.yml`:
```yaml
services:
  bot-pippin:
    image: ghcr.io/jerry-curaga/meme-arb-bot:latest
    restart: unless-stopped
    env_file: .env
    command: python bot.py --mode trade --symbol PIPPINUSDT --usd-amount 100

  bot-beat:
    image: ghcr.io/jerry-curaga/meme-arb-bot:latest
    restart: unless-stopped
    env_file: .env
    command: python bot.py --mode trade --symbol BEATUSDT --usd-amount 50 --no-hedge
```

---

## Troubleshooting

### Check GitHub Actions
Visit: https://github.com/jerry-curaga/meme-arb-bot/actions

### Make Container Registry Public
1. Go to: https://github.com/jerry-curaga?tab=packages
2. Click on `meme-arb-bot` package
3. Click "Package settings"
4. Change visibility to "Public"

### Manually Pull Latest Image
```bash
docker compose pull
docker compose up -d
```

### Check Watchtower Logs
```bash
docker logs watchtower
```

### Force Watchtower Update
```bash
docker restart watchtower
```

---

## Security Notes

- ✅ Never commit `.env` file
- ✅ Use API keys with IP restrictions
- ✅ Enable UFW firewall: `ufw allow 22 && ufw enable`
- ✅ Use SSH keys (not passwords)
- ✅ Regular backups of logs
- ✅ Monitor disk space: `df -h`

---

## Cost Estimate

- VPS: $5-10/month (1GB RAM)
- Docker Registry: Free (GitHub Container Registry)
- GitHub Actions: Free (2000 minutes/month)

**Total: $5-10/month** for 24/7 uptime
