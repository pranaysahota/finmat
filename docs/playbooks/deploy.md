# Deploy Playbook

Use this for Fly.io, Docker, secrets, runtime config, release, or rollback work.

## Steps

1. Identify the deployment target and runtime assumptions.
2. Confirm whether the work affects Docker, Fly.io, secrets, the persistent
   volume, SQLite, HTTP service config, or scheduled jobs.
3. Check config, environment variables, migrations, secrets handling, and
   rollback path.
4. Do not introduce unrelated code changes during deploy work.
5. Document required deployment steps.

## Current Assumptions

- Target: Fly.io app `finmat`, region `ams`.
- Runtime: Docker image based on Python 3.12 slim.
- Persistence: Fly volume mounted at `/data`.
- Database: `/data/finmat.db`.
- HTTP: Flask dashboard on port 5001.
- Process model: one machine. Multiple machines can duplicate scheduled work.
- CI: GitHub Actions runs tests, Docker build, then deploys on push to `main`.

## Validation

Local:

```bash
python -m pytest tests/ -q
docker build .
docker compose up
```

Production/Fly when authorized:

```bash
fly status --app finmat
fly logs --app finmat
fly secrets list --app finmat
fly volumes list --app finmat
fly deploy --app finmat
```

Document rollback commands or previous image details before risky deploys.

