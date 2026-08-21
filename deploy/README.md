# Deploying Bridge CRM

Two environments run on one EC2 box (nginx routes by Host header):

| Env | URL | App dir | Service | Port | DB | Runtime (`PYTHONPATH`) |
|-----|-----|---------|---------|------|-----|------------------------|
| Production | https://crm.bridge-renew.net | `/home/ubuntu/bridge_crm` | `bridge-crm` | 5001 | `bridge_crm` | `/opt/crm-runtime` |
| Dev / sandbox | https://dev.crm.bridge-renew.net | `/home/ubuntu/bridge_crm_sandbox` | `bridge-crm-sandbox` | 5002 | `bridge_crm_sandbox` | `/opt/crm-runtime-sandbox` |

## Automated deploys (GitHub Actions + self-hosted runner)

- **Push to `main`** → CI runs → **auto-deploys to dev**.
- **Deploy to production:** GitHub → **Actions → Deploy → Run workflow → target `production`**. Manual on purpose, so pushes to `main` never touch prod.

The deploy job (`.github/workflows/deploy.yml`) runs on a **self-hosted runner installed on the EC2 box**, so there are no SSH secrets, no open ports, and no inbound access required. Each run:

1. Backs up the DB (`pg_dump -Fc`) and code to `/home/ubuntu/backups`.
2. `rsync -a --delete`s the tracked code into the app dir (preserves `.env` and `data/`).
3. `pip install -r requirements.txt`.
4. Runs the idempotent migration: `python -m bridge_crm.scripts.bootstrap_db`.
5. Restarts the service and checks `/health`.

## Self-hosted runner

Installed under `/home/ubuntu/actions-runner`, running as a systemd service as user `ubuntu`:

```bash
sudo ~/actions-runner/svc.sh status
sudo ~/actions-runner/svc.sh start
sudo ~/actions-runner/svc.sh stop
```

If the runner is offline, deploys queue until it comes back online.

## Runtime wiring (why dev and prod don't collide)

Both services import the app package as `bridge_crm`, so each needs its **own** runtime dir on `PYTHONPATH`:

- **prod:** `PYTHONPATH=/opt/crm-runtime`, and `/opt/crm-runtime/bridge_crm` → `/home/ubuntu/bridge_crm`
- **dev:** `PYTHONPATH=/opt/crm-runtime-sandbox`, and `/opt/crm-runtime-sandbox/bridge_crm` → `/home/ubuntu/bridge_crm_sandbox`

⚠️ Never point `/opt/crm-runtime/bridge_crm` at the sandbox — production imports through it.

## Manual fallback

For the full server layout and manual SSH deploy steps, see [`ec2_setup.md`](ec2_setup.md).
