# Test Roles

Mini EQ keeps tests in a flat directory so file paths stay stable, but the
suite has distinct roles:

- `test_mini_eq_*.py`: application behavior, UI seams, models, routing, and
  PipeWire-facing state transitions.
- `test_check_*.py`: tests for smoke-test tools and their non-visual helper
  logic.
- `test_release_*.py`, `test_prepare_release.py`, and `test_version_metadata.py`:
  release metadata, publication dashboards, and release gate behavior.
- `test_github_workflows.py`: workflow contract checks that catch CI/release
  wiring regressions.
- Opt-in runtime tests such as `test_mini_eq_live_ui_runtime.py` are wrappers
  around heavier local smokes and should stay skipped unless their documented
  environment variable is set.

Prefer a small deterministic unit or tool test before adding a heavier runtime
smoke assertion. Runtime smokes should verify behaviors that need PipeWire,
Flatpak, GTK, AT-SPI, or a real session boundary.

For periodic suite hygiene, run:

```bash
.venv/bin/python tools/check_test_hygiene.py
.venv/bin/python -m pytest --dead-fixtures -q
.venv/bin/python -m vulture src tests tools --min-confidence 80
.venv/bin/python -m pytest --cov=mini_eq --cov-report=term-missing:skip-covered -q
```

Treat coverage as a map of risk, not as a release threshold. Low line coverage
in GTK-heavy modules is acceptable when the behavior is covered by focused
widget tests, AT-SPI checks, or runtime smokes that exercise the real session
boundary.
