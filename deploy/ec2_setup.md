# EC2 Deployment Notes

## Live environments

| Environment | URL | Port | Database |
|-------------|-----|------|----------|
| Production | https://crm.bridge-renew.net | 127.0.0.1:5001 | bridge_crm |
| Sandbox | https://dev.crm.bridge-renew.net | 127.0.0.1:5002 | bridge_crm_sandbox |

DNS: Both domains are A records on GoDaddy pointing to the EC2 public IP.

## Server layout

```
/home/ubuntu/bridge_crm/              # Production code
/home/ubuntu/bridge_crm_sandbox/      # Sandbox code
/home/ubuntu/crm-env/                 # Shared Python virtualenv
/home/ubuntu/inventory-chatbot/       # Chatbot app (separate)
/opt/crm-runtime/                     # Symlinks for Python imports
  bridge_crm -> /home/ubuntu/bridge_crm
  bridge_crm_sandbox -> /home/ubuntu/bridge_crm_sandbox
```

## Process isolation

| Component | OS User | Group |
|-----------|---------|-------|
| CRM (prod + sandbox) | `crm-app` | `crm-shared` |
| Chatbot | `ubuntu` | `ubuntu` |

- `.env` files are `chmod 600` owned by `crm-app` — only the CRM process can read them
- Code directories are `chmod 750` with group `crm-shared` — the chatbot (ubuntu) can read code via group membership but not secrets
- `/opt/crm-runtime` provides a listable directory for Python imports since `/home/ubuntu` is `711`

## Systemd services

| Service | Config |
|---------|--------|
| `bridge-crm` | Production — 3 workers on 127.0.0.1:5001 |
| `bridge-crm-sandbox` | Sandbox — 2 workers on 127.0.0.1:5002 |
| `inventory-chatbot-public` | Chatbot — 3 workers on 0.0.0.0:5000 |

Common service commands:

```bash
sudo systemctl restart bridge-crm
sudo systemctl restart bridge-crm-sandbox
sudo journalctl -u bridge-crm -n 100 --no-pager
sudo journalctl -u bridge-crm-sandbox -n 100 --no-pager
```

## TLS

Certificates are managed by Let's Encrypt via certbot. Both domains share one
certificate at `/etc/letsencrypt/live/crm.bridge-renew.net/`. Certbot auto-renews
via a snap timer — no manual renewal needed.

To check cert expiry:

```bash
sudo certbot certificates
```

## Nginx

Nginx serves as the TLS-terminating reverse proxy. Config files:

- `/etc/nginx/sites-available/crm-prod` → https://crm.bridge-renew.net → 127.0.0.1:5001
- `/etc/nginx/sites-available/crm-sandbox` → https://dev.crm.bridge-renew.net → 127.0.0.1:5002

Both configs enforce:
- HTTP → HTTPS redirect (301)
- HSTS (1 year, includeSubDomains)
- Security headers (X-Frame-Options, CSP, etc.)

To reload after config changes:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## AWS Security Group

Required inbound rules:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP only | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP → HTTPS redirect + certbot challenges |
| 443 | TCP | 0.0.0.0/0 | HTTPS |

## First-time setup from scratch

### 1. Install system packages

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql postgresql-contrib nginx
```

### 2. Create OS users for isolation

```bash
sudo useradd -r -s /sbin/nologin crm-app
sudo groupadd crm-shared
sudo usermod -aG crm-shared ubuntu
sudo usermod -aG crm-shared crm-app
sudo chmod 711 /home/ubuntu/
```

### 3. Set up Python virtualenv

```bash
python3 -m venv /home/ubuntu/crm-env
source /home/ubuntu/crm-env/bin/activate
pip install --upgrade pip
pip install -r /home/ubuntu/bridge_crm/requirements.txt
```

### 4. Create databases

```bash
sudo -u postgres psql
CREATE ROLE bridgecrm LOGIN PASSWORD '<GENERATE_STRONG_PASSWORD>';
CREATE DATABASE bridge_crm OWNER bridgecrm;
CREATE ROLE bridgecrm_sandbox LOGIN PASSWORD '<GENERATE_STRONG_PASSWORD>';
CREATE DATABASE bridge_crm_sandbox OWNER bridgecrm_sandbox;
\q
```

### 5. Configure .env files

```bash
cp /home/ubuntu/bridge_crm/.env.example /home/ubuntu/bridge_crm/.env
nano /home/ubuntu/bridge_crm/.env
# Set SECRET_KEY (python3 -c "import secrets; print(secrets.token_hex(64))")
# Set CRM_DB_PASSWORD to the password from step 4
# For Microsoft 365 Graph OAuth set EMAIL_PROVIDER=graph plus
# M365_TENANT_ID, M365_CLIENT_ID, M365_CLIENT_SECRET, and M365_SENDER
# Production currently uses Graph OAuth from crm@bridge-wireless.com

cp /home/ubuntu/bridge_crm/.env.sandbox.example /home/ubuntu/bridge_crm_sandbox/.env
nano /home/ubuntu/bridge_crm_sandbox/.env
# Set a DIFFERENT SECRET_KEY
# Set CRM_DB_PASSWORD to the sandbox password from step 4
# Leave EMAIL_PROVIDER=smtp unless sandbox mail is intentionally configured
```

Lock down permissions:

```bash
sudo chown -R crm-app:crm-shared /home/ubuntu/bridge_crm
sudo chown -R crm-app:crm-shared /home/ubuntu/bridge_crm_sandbox
sudo chmod 750 /home/ubuntu/bridge_crm /home/ubuntu/bridge_crm_sandbox
sudo chmod 600 /home/ubuntu/bridge_crm/.env /home/ubuntu/bridge_crm_sandbox/.env
```

### 6. Create runtime symlinks

```bash
sudo mkdir -p /opt/crm-runtime
sudo ln -sf /home/ubuntu/bridge_crm /opt/crm-runtime/bridge_crm
sudo ln -sf /home/ubuntu/bridge_crm_sandbox /opt/crm-runtime/bridge_crm_sandbox
sudo chown crm-app:crm-shared /opt/crm-runtime
```

### 7. Bootstrap schemas and seed admins

```bash
sudo -u crm-app PYTHONPATH=/opt/crm-runtime \
  /home/ubuntu/crm-env/bin/python3 -m bridge_crm.scripts.bootstrap_db

sudo -u crm-app PYTHONPATH=/opt/crm-runtime \
  /home/ubuntu/crm-env/bin/python3 -m bridge_crm.scripts.seed_admin \
  --email <ADMIN_EMAIL> \
  --full-name "<ADMIN_FULL_NAME>" \
  --password "<GENERATE_STRONG_PASSWORD>"
```

Repeat for sandbox with its .env sourced.

### 8. Install systemd services

```bash
sudo cp deploy/bridge-crm.service /etc/systemd/system/
sudo cp deploy/bridge-crm-sandbox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bridge-crm bridge-crm-sandbox
sudo systemctl start bridge-crm bridge-crm-sandbox
```

### 9. Set up nginx and TLS

```bash
# Copy nginx configs, enable sites, issue certs
sudo certbot --nginx \
  -d crm.bridge-renew.net \
  -d dev.crm.bridge-renew.net \
  --non-interactive --agree-tos --email <YOUR_EMAIL> --redirect
```

## Post-deploy checks

```bash
curl -sf https://crm.bridge-renew.net/health
curl -sf https://dev.crm.bridge-renew.net/health
curl -sI https://crm.bridge-renew.net/ | grep Strict-Transport
sudo systemctl is-active bridge-crm bridge-crm-sandbox nginx
```
