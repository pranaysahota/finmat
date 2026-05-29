# Debug Playbook

Use this for bug reports, failing tests, production anomalies, or suspicious
runtime behavior.

## Steps

1. Reproduce the issue first, preferably with a local test or narrow command.
2. State hypotheses before changing code.
3. Inspect logs, exceptions, failing assertions, response bodies, and runtime
   config.
4. Fix the root cause, not only the symptom.
5. Add a regression test where possible.
6. Remove temporary debug code before finishing.

## Useful Commands

```bash
python -m pytest tests/ -q
python -m pytest tests/test_name.py -q -vv
python main.py --once
./scripts/read_logs.sh --last 7
fly logs --app finmat
```

Use Fly commands only when debugging deployment/runtime behavior and when
credentials are available.

## Notes

Be careful with live notification paths. Telegram/email calls can create real
side effects unless mocked or explicitly intended.

