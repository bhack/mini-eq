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

For release candidates that changed UI responsiveness, graph drawing, filter
parameter updates, analyzer work, routing callbacks, or PipeWire event
handling, run a deterministic benchmark before publishing:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_fader_drag.py \
  --iterations 300 \
  --warmup 50 \
  --json \
  --max-p95-ms current-drag-update=10.0 \
  --max-p95-ms graph-response-surface-redraw=30.0 \
  > /tmp/mini-eq-release-benchmark.json
```

Archive or summarize the JSON output in the release or PR notes when it was
part of the decision to ship. If this benchmark fails, rerun it without
`--json` to inspect the terminal table before changing budgets; the intended
fix is usually the performance regression, not looser thresholds.

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

Compare runtime CPU separately from profiler captures. Use a private
PipeWire/WirePlumber graph, synthetic playback, and temporary application
settings so the measurements do not change desktop audio or presets. Compare
Monitor off, live, frozen, and hidden-window states at both 48 and 192 kHz.
Warm up first, repeat the baseline after the changed build, and record the
runtime versions and CPU frequency/power policy. Express process CPU as a
percentage of one logical core; include native audio threads in that total.

Use Sysprof's GTK trace to distinguish frame updates, layout, snapshots, and
rendering, and its native samples to distinguish PipeWire DSP from Python
callbacks. Profile startup separately from steady playback: shader compilation
and font loading can dominate the first frame. `cProfile` is useful for Python
call attribution, but its elapsed waiting time is not CPU consumption and its
instrumentation overhead must not be used as a benchmark result. The official
references are GTK's [drawing model](https://docs.gtk.org/gtk4/drawing-model.html)
and Python's [profiler guidance](https://docs.python.org/3/library/profile.html).
