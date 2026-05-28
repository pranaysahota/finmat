# Build Playbook

Use this for new features or intended behavior changes.

## Steps

1. Read `AGENTS.md`, `docs/architecture.md`, and `docs/repo-map.md`.
2. Identify the existing module, route, service, or utility that already owns
   the behavior.
3. Prefer existing services, modules, repositories, utilities, fixtures, and
   patterns before adding new abstractions.
4. Keep controllers/routes thin. In this repo that mainly means keeping
   `ui/app.py` request handling focused on validation, response shape, and
   orchestration.
5. Preserve the portfolio-state contract unless the change explicitly requires
   a contract migration.
6. Add or update tests for new behavior.
7. Update architecture/docs if the design or operational assumptions change.

## Validation

Run at minimum:

```bash
python -m pytest tests/ -q
```

Add focused commands for changed entry points, such as:

```bash
python main.py --once
python ui/app.py
docker build .
```

Only run live integration/API workflows when credentials and side effects are
understood.

