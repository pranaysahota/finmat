# Test Playbook

Use this for test-only work, characterization coverage, or test harness changes.

## Rules

- Do not change production behavior unless explicitly required.
- Use existing test patterns, fixtures, monkeypatching style, and naming
  conventions.
- Prefer testing public behavior over implementation details.
- Add regression tests for bugs before or alongside the fix.
- Keep tests deterministic and avoid real network/API calls unless the test is
  explicitly marked and documented as integration.
- Avoid tests that depend on real private portfolio state.

## Current Test Harness

- Test framework: pytest.
- Config: `pytest.ini`.
- Existing command:

```bash
python -m pytest tests/ -q
```

CI also runs:

```bash
python -m pytest tests/ -m "not integration" -q
```

No coverage threshold is configured.

## Validation

For test harness work, run the full test suite and the narrow test file you
changed:

```bash
python -m pytest tests/path_to_changed_test.py -q
python -m pytest tests/ -q
```

