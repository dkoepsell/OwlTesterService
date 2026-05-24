# Deployment Guide

## Run Locally (Development)

```bash
cd /path/to/OwlTesterService

# First time only — copy and fill in secrets
cp .env.example .env
# Edit .env: set SESSION_SECRET (required), OPENAI_API_KEY (optional)

# Start the app
./start.sh
```

App runs at **http://localhost:5000**

To stop: `pkill -f "python main.py"`

---

## Deploy on a VPS

Tested on **Ubuntu 22.04 / 24.04**. You need a domain name pointed at your server's IP before setting up HTTPS.

### 1. Provision the server

Minimum specs: 1 vCPU, 1 GB RAM, 20 GB disk.

Open ports in your hosting provider's firewall (or security group):
- 22 (SSH)
- 80 (HTTP)
- 443 (HTTPS)

### 2. Install Docker

```bash
ssh user@your-server

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker          # apply group without logging out

# Verify
docker --version
docker compose version
```

### 3. Copy the project to the server

Option A — clone from Git:
```bash
git clone https://github.com/youruser/OwlTesterService.git
cd OwlTesterService
```

Option B — rsync from local machine:
```bash
rsync -av --exclude='.venv' --exclude='uploads' --exclude='*.db' \
  /path/to/OwlTesterService/ user@your-server:~/OwlTesterService/
ssh user@your-server
cd OwlTesterService
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in every value:

```
SESSION_SECRET=<run: python3 -c "import secrets; print(secrets.token_hex(32))">
OPENAI_API_KEY=sk-...
POSTGRES_USER=owltester
POSTGRES_PASSWORD=<strong random password>
POSTGRES_DB=owl_tester
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
```

> `DATABASE_URL` uses the variable substitution above — Docker Compose resolves it from the other vars in `.env`.

### 5. Start the stack

```bash
docker compose up -d --build
```

Check everything is healthy:
```bash
docker compose ps
docker compose logs app --tail 50
```

App is now running on **http://your-server-ip**

### 6. Enable HTTPS with Let's Encrypt

```bash
# Install certbot on the host (not inside Docker)
sudo apt install -y certbot

# Stop nginx so certbot can bind port 80
docker compose stop nginx

# Obtain the certificate (replace with your actual domain)
sudo certbot certonly --standalone -d your.domain.com

# Copy certs into the Docker volume
sudo cp /etc/letsencrypt/live/your.domain.com/fullchain.pem \
        /var/lib/docker/volumes/owltesterservice_certbot_certs/_data/
sudo cp /etc/letsencrypt/live/your.domain.com/privkey.pem \
        /var/lib/docker/volumes/owltesterservice_certbot_certs/_data/
```

Edit `nginx/nginx.conf` — uncomment the `server { listen 443 ... }` block and set `server_name your.domain.com`.

Also add an HTTP → HTTPS redirect at the top of the file:
```nginx
server {
    listen 80;
    server_name your.domain.com;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
```

Restart nginx:
```bash
docker compose start nginx
```

### 7. Auto-renew certificates (cron)

```bash
sudo crontab -e
```

Add:
```
0 3 * * * certbot renew --quiet && \
  cp /etc/letsencrypt/live/your.domain.com/fullchain.pem \
     /var/lib/docker/volumes/owltesterservice_certbot_certs/_data/ && \
  cp /etc/letsencrypt/live/your.domain.com/privkey.pem \
     /var/lib/docker/volumes/owltesterservice_certbot_certs/_data/ && \
  docker compose -f /home/user/OwlTesterService/docker-compose.yml restart nginx
```

---

## Ongoing Operations

### Update the app
```bash
git pull
docker compose up -d --build app
```

### Run a database migration
```bash
docker compose exec app python migrate_db.py
```

### View logs
```bash
docker compose logs -f app
docker compose logs -f nginx
```

### Backup the database
```bash
docker compose exec db pg_dump -U owltester owl_tester > backup_$(date +%Y%m%d).sql
```

### Restore from backup
```bash
cat backup_20240101.sql | docker compose exec -T db psql -U owltester owl_tester
```

### Stop / restart
```bash
docker compose down        # stop containers, keep volumes
docker compose restart app # restart just the app
```

> **Never run `docker compose down -v`** in production — it deletes the database and uploads volumes.
