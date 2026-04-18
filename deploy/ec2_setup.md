# EC2 Deployment Notes

Target EC2 public IP: `3.96.54.81`

SSH key on your machine: `BrainAddOnMBP.pem`

## Current deployment inputs

- Linux username: `ubuntu`
- Access URL for now: `http://3.96.54.81`
- PostgreSQL database: `bridge_crm`
- PostgreSQL user: `bridgecrm`
- First admin email: `fayzeen@bridge-wireless.com`
- ERP integration: deferred until REST API or read-only credentials are available
- SMTP credentials: deferred, but Outlook host/port are configured

## Recommended server layout

- Repo path: `/home/ubuntu/inventory-chatbot`
- CRM virtualenv: `/home/ubuntu/crm-env`
- App service: gunicorn bound to `127.0.0.1:5001`
- Reverse proxy: Nginx on `3.96.54.81` for now
- Database: local PostgreSQL `bridge_crm`

## First-time setup commands

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip postgresql postgresql-contrib nginx

python3 -m venv /home/ubuntu/crm-env
source /home/ubuntu/crm-env/bin/activate
pip install --upgrade pip
pip install -r /home/ubuntu/inventory-chatbot/bridge_crm/requirements.txt
```

Create PostgreSQL database and role:

```bash
sudo -u postgres psql
CREATE ROLE bridgecrm LOGIN PASSWORD 'Feather17!';
CREATE DATABASE bridge_crm OWNER bridgecrm;
\q
```

Create `.env` from the example and fill in real values:

```bash
cp /home/ubuntu/inventory-chatbot/bridge_crm/.env.example /home/ubuntu/inventory-chatbot/bridge_crm/.env
nano /home/ubuntu/inventory-chatbot/bridge_crm/.env
```

Bootstrap the schema and seed the first admin:

```bash
source /home/ubuntu/crm-env/bin/activate
cd /home/ubuntu/inventory-chatbot
python -m bridge_crm.scripts.bootstrap_db
python -m bridge_crm.scripts.seed_admin \
  --email fayzeen@bridge-wireless.com \
  --full-name "Fayzeen Ali" \
  --password "PassFeather_17!"
```

Install the systemd service:

```bash
sudo cp /home/ubuntu/inventory-chatbot/bridge_crm/deploy/bridge-crm.service /etc/systemd/system/bridge-crm.service
sudo systemctl daemon-reload
sudo systemctl enable bridge-crm
sudo systemctl start bridge-crm
sudo systemctl status bridge-crm
```

Install the Nginx site for raw IP access:

```bash
sudo cp /home/ubuntu/inventory-chatbot/bridge_crm/deploy/nginx.crm.ip.conf /etc/nginx/sites-available/bridge-crm
sudo ln -s /etc/nginx/sites-available/bridge-crm /etc/nginx/sites-enabled/bridge-crm
sudo nginx -t
sudo systemctl reload nginx
```

When you later move to a domain/subdomain, switch to `deploy/nginx.crm.conf` and issue SSL:

```bash
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
sudo certbot --nginx -d crm.yourdomain.com
```

## Post-deploy checks

```bash
curl http://127.0.0.1:5001/health
curl http://3.96.54.81/health
sudo journalctl -u bridge-crm -n 100 --no-pager
```
