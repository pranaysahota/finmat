# Finmat — Operations Guide

## App Overview

Finmat is a **background worker** deployed on Fly.io (region: `ams`). It runs a Python scheduler — no HTTP server, no public endpoints. One machine, one volume.

- **Scheduler:** price check every hour, daily briefing at 08:00 Dublin time, weekly digest Sundays 09:00
- **Persistent volume:** `finmat_data` mounted at `/app/data` — stores `portfolio_history.json` and `trades.json`
- **Holdings:** `portfolio/local.py` reconstructed on every startup from the `PORTFOLIO_LOCAL_PY` Fly secret (base64-encoded)

---

## Fly.io — Common Commands

### Status and monitoring

```bash
# Check machine state, region, health
fly machines list --app finmat

# Tail live logs
fly logs --app finmat

# Check deployed secrets (names only, not values)
fly secrets list --app finmat

# Check volume
fly volumes list --app finmat
```

### SSH and file access

```bash
# Interactive shell into the running machine
fly ssh console --app finmat

# Run a single command without interactive shell
fly ssh console --app finmat --command "python main.py --once"

# Upload a local file to the machine (overwrites)
fly ssh console --app finmat --command "cat > /app/data/trades.json" < data/trades.json

# Download a file from the machine
fly ssh console --app finmat --command "cat /app/data/portfolio_history.json" > data/portfolio_history.json
```

### Scaling

```bash
# Scale to 1 machine (finmat should always run as a single instance)
fly scale count 1 --app finmat

# Check current scale
fly status --app finmat
```

### Deployment

```bash
# Deploy latest release branch image
fly deploy --app finmat

# Deploy a specific image (e.g. from a CI run)
fly deploy --app finmat --image registry.fly.io/finmat:<tag>

# Force restart the running machine
fly machines restart --app finmat
```

### Secrets management

```bash
# Set all required secrets
fly secrets set \
  ANTHROPIC_API_KEY="..." \
  TELEGRAM_BOT_TOKEN="..." \
  TELEGRAM_CHAT_ID="..." \
  PORTFOLIO_LOCAL_PY="$(base64 < portfolio/local.py)" \
  --app finmat

# Update holdings secret after a trade
fly secrets set PORTFOLIO_LOCAL_PY="$(base64 < portfolio/local.py)" --app finmat

# Unset a secret
fly secrets unset SECRET_NAME --app finmat
```

### Volume management

```bash
# List volumes and see which machine they are attached to
fly volumes list --app finmat

# Create a new volume (only needed if starting fresh or changing region)
fly volumes create finmat_data --region ams --size 1 --app finmat

# Extend volume size
fly volumes extend <volume-id> --size 2 --app finmat
```

---

## Maintenance Guide

### After every Revolut purchase

Run `trade.py` locally to log the trade and update `portfolio/local.py`:

```bash
python trade.py
```

Then push the updated holdings to Fly as a secret:

```bash
fly secrets set PORTFOLIO_LOCAL_PY="$(base64 < portfolio/local.py)" --app finmat
```

The running machine will pick up the new secret on next restart/redeploy. To apply immediately:

```bash
fly machines restart --app finmat
```

### Deploying a code change

Follow the branch flow: `dev` -> `main` -> `release`.

1. Merge your PR into `main`
2. Cherry-pick the commit onto a branch off `release`, raise a PR to `release`
3. CI (`release.yml`) triggers `fly deploy` automatically on merge to `release`

Never push directly to `main` or `release` — both have branch protection rules requiring PRs.

### Checking the daily briefing ran

```bash
fly logs --app finmat | grep "Daily Briefing"
```

### App is not sending Telegram messages

1. Check secrets are set: `fly secrets list --app finmat`
2. Tail logs for errors: `fly logs --app finmat`
3. Run a one-off briefing manually:
   ```bash
   fly ssh console --app finmat --command "python main.py --once"
   ```

### Restoring data after a fresh volume

If the volume is wiped or replaced:

```bash
# Push local data files to the machine
fly ssh console --app finmat --command "cat > /app/data/trades.json" < data/trades.json
fly ssh console --app finmat --command "cat > /app/data/portfolio_history.json" < data/portfolio_history.json
```

### Changing region

1. Update `primary_region` in `fly.toml`
2. Create a new volume in the new region:
   ```bash
   fly volumes create finmat_data --region <new-region> --size 1 --app finmat
   ```
3. Deploy — Fly will migrate the machine to the new region

### Machine scaling

Finmat must run as **exactly one machine**. Two machines means duplicate briefings and duplicate Telegram messages.

```bash
# Verify only one machine is running
fly machines list --app finmat

# Scale down if needed
fly scale count 1 --app finmat
```

---

## Key File Locations (on the machine)

| Path | Description |
|------|-------------|
| `/app/data/trades.json` | Permanent trade log — on persistent volume |
| `/app/data/portfolio_history.json` | Daily snapshots — on persistent volume |
| `/app/portfolio/local.py` | Holdings — rebuilt from secret on startup |
| `/app/fly.toml` | Fly config — baked into image |
| `/app/.env` | Not present — all secrets via Fly secrets |
