# Bridge CRM

Internal CRM for Bridge Wireless, built with Flask, PostgreSQL, and SQLAlchemy.

## Live environments

| Environment | URL |
|-------------|-----|
| Production | https://crm.bridge-renew.net |
| Sandbox | https://dev.crm.bridge-renew.net |

Both run on a shared AWS EC2 instance behind nginx with TLS (Let's Encrypt).
The CRM process runs as an isolated `crm-app` OS user with its own file
permissions and database credentials.

## Features

- User authentication with login rate limiting and CSRF protection
- Dashboard with summary cards
- Accounts, Leads, Opportunities CRUD with search
- Pipeline management with configurable stages
- Quote and Invoice PDF generation
- Email integration (Microsoft 365 Graph OAuth or SMTP)
- Custom fields per entity type
- Activity timeline and notifications
- Role-based access control (admin, manager, rep)
- Public lead capture API with CORS and rate limiting

## Local development setup

```bash
python3 -m venv ~/crm-env
source ~/crm-env/bin/activate
pip install -r requirements.txt
```

Create a local PostgreSQL database:

```bash
sudo -u postgres psql
CREATE ROLE bridge_crm LOGIN PASSWORD 'local-dev-password';
CREATE DATABASE bridge_crm OWNER bridge_crm;
\q
```

Configure environment:

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and CRM_DB_PASSWORD
# For local dev, set SESSION_COOKIE_SECURE=false and SESSION_COOKIE_SAMESITE=Lax
```

Bootstrap the schema and seed an admin user:

```bash
python -m bridge_crm.scripts.bootstrap_db
python -m bridge_crm.scripts.seed_admin \
  --email admin@example.com \
  --full-name "Dev Admin" \
  --password "your-12-char-password"
```

Run the dev server:

```bash
flask --app bridge_crm.wsgi:app run --debug
```

## Configuration

The app requires two environment variables with no defaults — it will crash
on startup if either is missing:

- `SECRET_KEY` — Flask session signing key (generate with `python3 -c "import secrets; print(secrets.token_hex(64))"`)
- `CRM_DB_PASSWORD` — PostgreSQL password

All other settings have sensible defaults. See `.env.example` for the full list.

For Microsoft 365 OAuth, set:

- `EMAIL_PROVIDER=graph`
- `M365_TENANT_ID`
- `M365_CLIENT_ID`
- `M365_CLIENT_SECRET`
- `M365_SENDER`

Production currently uses Microsoft Graph OAuth for outbound mail from
`crm@bridge-wireless.com`. Sandbox is not configured for outbound email.

## Deployment

See [`deploy/ec2_setup.md`](./deploy/ec2_setup.md) for the full server setup
guide covering process isolation, systemd services, nginx, and TLS.

Key deploy files:

| File | Purpose |
|------|---------|
| `deploy/bridge-crm.service` | Production systemd unit |
| `deploy/bridge-crm-sandbox.service` | Sandbox systemd unit |
| `deploy/nginx.crm.conf` | Production nginx (TLS) |
| `deploy/nginx.crm.sandbox.conf` | Sandbox nginx (TLS) |
| `.env.example` | Production env template |
| `.env.sandbox.example` | Sandbox env template |

## Docker (alternative)

```bash
docker compose --profile production up -d    # production on port 5001
docker compose --profile sandbox up -d       # sandbox on port 5002
```

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

- `ci.yml` — Runs linting and tests on push to `main`/`sandbox` and on PRs
- `deploy.yml` — Auto-deploys to the correct environment after CI passes

Required GitHub repository secrets: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`.
