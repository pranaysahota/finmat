# Cleanup Playbook

Use this for unused files, modules, functions, classes, imports, variables,
assets, dependencies, config, or old patterns.

## Rules

- Identify unused files, modules, functions, classes, imports, variables,
  assets, configuration, and dependencies.
- Use linting, static analysis, dependency analysis, and dead-code detection
  tools where available.
- Verify code is truly unused before removal.
- Preserve externally referenced APIs unless usage has been validated.
- Remove dead code in small, reviewable changes.
- Add or update tests when removal affects behavior assumptions.
- Document removed components in `docs/deprecated.md` when appropriate.
- Run all validation checks after cleanup.

## Current Manual Checks

Until dead-code tools are configured:

```bash
rg "symbol_or_file_name"
rg "from module|import module"
python -m pytest tests/ -q
```

Check these external reference surfaces before deleting:

- `Dockerfile`, `entrypoint.sh`, `docker-compose.yml`, `fly.toml`
- `.github/workflows/*`
- `scripts/*`
- Flask routes and static assets
- env var names
- migration inputs and legacy data paths

## Recommended Tools To Add Later

```bash
ruff check . --select F401,F841
vulture . --min-confidence 80
pip-check-reqs
deptry .
```

