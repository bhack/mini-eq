# Performance And Profiling

Mini EQ has three maintainer performance tools:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_fader_drag.py --iterations 100 --warmup 20
PYTHONPATH=src .venv/bin/python tools/profile_live_app.py -- --auto-route
.venv/bin/python tools/profile_sysprof.py -- --auto-route
```

Use `benchmark_fader_drag.py` for repeatable GTK callback microbenchmarks. It
uses deterministic demo data and a temporary config directory, so it should not
depend on local devices or presets.

Use `profile_live_app.py` when investigating real interaction lag. It runs the
normal app under `cProfile`, writes the `.prof` file outside the repository by
default, and prints cumulative stats after the app exits.

Use `profile_sysprof.py` when Python profiling does not explain visible lag. It
runs the app or deterministic benchmark under `sysprof-cli`, enables GTK trace
data by default, and writes the `.syscap` file outside the repository by
default.

## Regression Checks

The benchmark supports JSON output and optional budgets:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_fader_drag.py \
  --json \
  --max-p95-ms current-drag-update=10.0 \
  --max-p95-ms graph-response-surface-redraw=30.0
```

For backend parameter-update work, include the local control and SPA pod build
costs:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_fader_drag.py --engine-profile pod
```

To capture the deterministic benchmark with Sysprof:

```bash
.venv/bin/python tools/profile_sysprof.py --target benchmark -- --iterations 80 --warmup 20
```

The benchmark timings cover synchronous Python and GTK callback work. They do
not measure real PipeWire scheduling, audio latency, GPU presentation latency,
or compositor behavior.

Avoid strict timing budgets in generic CI unless the runner and GTK environment
are stable. A better public-project default is to keep these benchmarks as
maintainer checks, archive JSON output in release or PR investigations, and use
generous budgets only on a known runner.

## GTK Diagnostics

When `cProfile` does not explain visible lag, use GTK's own debugging and
profiling controls to inspect frame-clock, layout, renderer, and Sysprof data.
The current GTK reference is:

https://docs.gtk.org/gtk4/running.html

Those environment variables are debugging knobs, not stable application
settings, so do not depend on them from Mini EQ code.
