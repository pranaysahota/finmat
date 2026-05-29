# Refactor Playbook

Use this for internal restructuring that should preserve behavior.

## Rules

- Preserve external behavior.
- Do not mix refactoring with new feature work.
- Add characterization tests first if coverage is weak or behavior is subtle.
- Keep refactors small and reviewable.
- Explain the before/after structure in the PR summary.
- Use linting and static analysis results to identify cleanup opportunities once
  those tools are configured.

## Suggested Flow

1. Document the current behavior and call graph.
2. Add or identify tests that lock the behavior.
3. Move one boundary at a time.
4. Run focused tests after each step.
5. Update `docs/architecture.md`, `docs/repo-map.md`, and ADRs when ownership or
   data flow changes.

## Validation

```bash
python -m pytest tests/ -q
```

If refactoring legacy migration code, run migration checks too:

```bash
python scripts/migrate_to_sqlite.py
```
