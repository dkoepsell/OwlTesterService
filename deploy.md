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

There are **two supported topologies**. Pick the one that matches your server:

- **Topology A — self-contained (bundled nginx).** The server runs nothing but this app. The Docker Compose stack's own `nginx` container terminates TLS and owns ports 80/443. Simplest for a dedicated single-app box. This is what the repo's `docker-compose.yml` and `nginx/nginx.conf` are wired for out of the box.
- **Topology B — behind an existing host nginx.** The server already runs a host-level (Ubuntu-packaged) nginx that owns ports 80/443 — typically because it also hosts other apps. The bundled nginx container **cannot** be used here (it would collide on 80/443). Instead the host nginx reverse-proxies the domain to the app, which is published on `127.0.0.1:5000`.

> ⚠️ **The production instance at https://ontology.davidkoepsell.com runs Topology B.** That Hetzner host also serves a separate app (Everdice / realmofeverdice.com), so a host-level nginx fronts both domains and the bundled `nginx` service has been removed from its `docker-compose.yml`. If you redeploy that box straight from the repo defaults (Topology A), the bundled nginx will try to bind 80/443 and crash-loop. See **Topology B** below.

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
docker compose version   # v2 plugin; some older hosts only have `docker-compose` v1 (see gotcha below)
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

---

## Topology A — self-contained (bundled nginx)

Use this only on a dedicated box where this app owns ports 80/443.

### A.5. Start the stack

```bash
docker compose up -d --build
```

Check everything is healthy:
```bash
docker compose ps
docker compose logs app --tail 50
```

App is now running on **http://your-server-ip**

### A.6. Enable HTTPS with Let's Encrypt

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

Edit `nginx/nginx.conf` so the `server { listen 443 ... }` block uses `server_name your.domain.com` and a matching HTTP→HTTPS redirect block exists for it. Then:

```bash
docker compose start nginx
```

### A.7. Auto-renew certificates (cron)

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

## Topology B — behind an existing host nginx (production setup)

This is how **ontology.davidkoepsell.com** runs on Hetzner. The host's Ubuntu nginx owns 80/443 and reverse-proxies the domain to the app container, which is published only on localhost. The bundled `nginx` service is **not used**.

### B.5. Adjust the compose file: drop the bundled nginx, publish the app on localhost

Remove the entire `nginx:` service from `docker-compose.yml`, and change the `app` service so it publishes a host port instead of only `expose`-ing one:

```yaml
  app:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-owltester}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-owl_tester}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      SESSION_SECRET: ${SESSION_SECRET}
    volumes:
      - uploads:/app/uploads
    ports:
      - "127.0.0.1:5000:5000"      # host nginx proxies here; not exposed to the internet
```

You can also drop the now-unused `certbot_www` / `certbot_certs` volumes — TLS is handled by the host's certbot, not inside Docker.

Bring the stack up (only `db` and `app` should run):
```bash
docker compose up -d
docker compose ps
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/   # expect 200
```

### B.6. Add a host nginx vhost for the domain

Create `/etc/nginx/sites-available/ontology` (substitute your domain), mirroring the long timeouts the OWL reasoners need:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name ontology.davidkoepsell.com;

    # Large buffers + long timeouts for slow OWL reasoners / AI calls
    proxy_buffers 16 64k;
    proxy_buffer_size 128k;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    send_timeout 600s;
    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it and reload:
```bash
ln -sf /etc/nginx/sites-available/ontology /etc/nginx/sites-enabled/ontology
nginx -t && systemctl reload nginx
```

### B.7. Issue the certificate with the certbot nginx plugin

The host's nginx already owns port 80, so use the `--nginx` plugin (it handles the ACME challenge and rewrites the vhost to add the 443 block + HTTP→HTTPS redirect automatically):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ontology.davidkoepsell.com --redirect \
  --non-interactive --agree-tos -m you@example.com
nginx -t && systemctl reload nginx
```

Certbot installs a systemd timer for auto-renewal — no manual cron needed.

### B.8. Gotcha: `docker-compose` v1 + newer Docker Engine

The production host only has **`docker-compose` v1 (1.29.2)**, not the `docker compose` v2 plugin. v1 throws `KeyError: 'ContainerConfig'` when it tries to **recreate** an existing container against a newer Docker Engine. Workaround — remove the container first so it does a clean create:

```bash
docker rm -f owltesterservice_app_1   # or the current container name from `docker ps -a`
docker-compose up -d
```

(All `docker compose ...` commands below should be run as `docker-compose ...` on that host.)

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
docker compose logs -f nginx        # Topology A only — no nginx container under Topology B
```

> Under **Topology B**, the web server logs live on the host: `/var/log/nginx/access.log` and `/var/log/nginx/error.log` (or `journalctl -u nginx`).

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
