# Bridge CRM

Phase 1 foundation for the custom Bridge Wireless CRM described in
`../CRM_Implementation_Plan.md`.

## What is implemented

- Flask app factory with ProxyFix, CSRF protection, secure session defaults, and `/health`
- PostgreSQL database bootstrap using SQLAlchemy Core table metadata
- Login/logout with database-backed users and login rate limiting
- Dashboard shell with summary cards
- Accounts CRUD with search and unique ERP client validation
- Seed scripts for pipeline stages and the first admin user

## Local setup

```bash
python3 -m venv ~/crm-env
source ~/crm-env/bin/activate
pip install -r bridge_crm/requirements.txt
cp bridge_crm/.env.example bridge_crm/.env
```

Create the PostgreSQL database and role first, then bootstrap the schema:

```bash
python -m bridge_crm.scripts.bootstrap_db
python -m bridge_crm.scripts.seed_admin \
  --email admin@bridgewireless.com \
  --full-name "Bridge Admin" \
  --password "replace-with-a-12-char-password"
```

Run locally:

```bash
flask --app bridge_crm.wsgi:app run --debug
```

Run with gunicorn:

```bash
gunicorn --bind 0.0.0.0:5001 bridge_crm.wsgi:app
```

## Deployment

Use the files in [`deploy/`](./deploy):

- [`deploy/ec2_setup.md`](./deploy/ec2_setup.md) for the EC2 rollout sequence
- [`deploy/bridge-crm.service`](./deploy/bridge-crm.service) for systemd
- [`deploy/nginx.crm.ip.conf`](./deploy/nginx.crm.ip.conf) for raw-IP reverse proxy
- [`deploy/nginx.crm.conf`](./deploy/nginx.crm.conf) for the later CRM subdomain reverse proxy
