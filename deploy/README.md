# Deployment

The upload server (`verifier.server`) runs in Docker on the VPS, behind nginx (TLS +
HTTP Basic Auth). Pushes to `main` auto-deploy via GitHub Actions.

- **URL:** https://tz-schedule-validation.quickdemo.site
- **Host:** Ubuntu VPS, Docker + Compose, nginx on 80/443
- **Container:** published to `127.0.0.1:8090` → nginx proxies it

## One-time VPS setup

```bash
# 1. Clone (deploy dir must match the CI secret VPS_APP_DIR)
cd /home/ubuntu
git clone https://github.com/canhta/tz-schedule-validation.git
cd tz-schedule-validation
docker compose up -d --build

# 2. nginx vhost
sudo cp deploy/nginx/tz-schedule-validation.conf \
        /etc/nginx/sites-available/tz-schedule-validation.quickdemo.site
sudo ln -s /etc/nginx/sites-available/tz-schedule-validation.quickdemo.site \
           /etc/nginx/sites-enabled/

# 3. Basic auth user
sudo apt-get install -y apache2-utils   # provides htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd-tzsv admin

# 4. TLS (Certbot edits the vhost to add 443 + redirect)
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d tz-schedule-validation.quickdemo.site
```

## CI/CD

`.github/workflows/deploy.yml` runs on push to `main`. Required repo secrets:

| Secret | Value |
|--------|-------|
| `VPS_HOST` | VPS IP / hostname |
| `VPS_USER` | SSH user (e.g. `ubuntu`) |
| `VPS_SSH_KEY` | Private SSH key with access to the VPS |
| `VPS_APP_DIR` | Clone path (default `/home/ubuntu/tz-schedule-validation`) |

Each deploy: `git reset --hard origin/main` → `docker compose up -d --build` → prune.
