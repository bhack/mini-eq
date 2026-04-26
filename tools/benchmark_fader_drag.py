from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import gi

gi.require_version("Adw", "1")

from demo_runtime import DEMO_PRESET_NAME, DemoController
from gi.repository import Adw, GLib

from mini_eq import core
from mini_eq.core import (
    EQ_FREQUENCY_MAX_HZ,
    EQ_FREQUENCY_MIN_HZ,
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_Q_MAX,
    EQ_Q_MIN,
)
from mini_eq.desktop_integration import APP_ID
from mini_eq.filter_chain import builtin_biquad_band_control_values
from mini_eq.window import MiniEqWindow
from mini_eq.wireplumber_backend import build_spa_params_pod


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    updates_per_second: float


class BenchmarkController(DemoController):
    def __init__(self, engine_profile: str = "none") -> None:
        super().__init__()
        self.engine_profile = engine_profile
        self.engine_apply_count = 0
        self.engine_control_count = 0
        self.engine_pod_count = 0
        self._Wp = self.load_wireplumber_namespace() if engine_profile == "pod" else None

    def load_wireplumber_namespace(self):
        for version in ("0.5", "0.4"):
            try:
                gi.require_version("Wp", version)
                from gi.repository import Wp

                Wp.init(Wp.InitFlags.PIPEWIRE | Wp.InitFlags.SPA_TYPES)
                return Wp
            except (ImportError, ValueError):
                continue

        raise RuntimeError("WirePlumber GI namespace is required for --engine-profile=pod")

    def set_band_gain(self, index: int, gain_db: float, *, apply: bool = True) -> bool:
        gain_db = core.clamp(gain_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB)
        if self.bands[index].gain_db == gain_db:
            return False
        self.bands[index].gain_db = gain_db
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_frequency(self, index: int, frequency: float, *, apply: bool = True) -> bool:
        frequency = core.clamp(frequency, EQ_FREQUENCY_MIN_HZ, EQ_FREQUENCY_MAX_HZ)
        if self.bands[index].frequency == frequency:
            return False
        self.bands[index].frequency = frequency
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_q(self, index: int, q_value: float, *, apply: bool = True) -> bool:
        q_value = core.clamp(q_value, EQ_Q_MIN, EQ_Q_MAX)
        if self.bands[index].q == q_value:
            return False
        self.bands[index].q = q_value
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_type(self, index: int, filter_type: int) -> None:
        self.bands[index].filter_type = filter_type

    def set_band_mute(self, index: int, muted: bool) -> None:
        self.bands[index].mute = bool(muted)

    def set_band_solo(self, index: int, solo: bool) -> None:
        self.bands[index].solo = bool(solo)

    def apply_band_to_engine(self, index: int) -> None:
        self.engine_apply_count += 1
        if self.engine_profile == "none":
            return

        controls = builtin_biquad_band_control_values(
            index,
            self.bands[index],
            self.eq_enabled,
            core.SAMPLE_RATE,
            core.bands_have_solo(self.bands),
        )
        self.engine_control_count += len(controls)

        if self.engine_profile == "pod":
            build_spa_params_pod(self._Wp, controls)
            self.engine_pod_count += 1


def gain_for_iteration(index: int) -> float:
    return round(-6.0 + ((index % 121) * 0.1), 1)


def benchmark_call(
    name: str,
    iterations: int,
    warmup: int,
    callback: Callable[[int], None],
) -> BenchmarkResult:
    for index in range(warmup):
        callback(index)

    durations_ns: list[int] = []
    started_ns = time.perf_counter_ns()
    for index in range(iterations):
        call_started_ns = time.perf_counter_ns()
        callback(index)
        durations_ns.append(time.perf_counter_ns() - call_started_ns)

    elapsed_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000.0
    sorted_durations = sorted(durations_ns)
    p95_index = min(len(sorted_durations) - 1, max(0, math.ceil(len(sorted_durations) * 0.95) - 1))
    mean_ms = statistics.fmean(durations_ns) / 1_000_000.0

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        mean_ms=mean_ms,
        median_ms=statistics.median(durations_ns) / 1_000_000.0,
        p95_ms=sorted_durations[p95_index] / 1_000_000.0,
        max_ms=max(durations_ns) / 1_000_000.0,
        updates_per_second=iterations / elapsed_seconds if elapsed_seconds > 0.0 else 0.0,
    )


def legacy_drag_update(window: MiniEqWindow, index: int, gain_db: float) -> None:
    window.controller.set_band_gain(index, gain_db)
    window.selected_band_index = index
    window.updating_ui = True
    try:
        window.update_quick_fader_strip()
        window.update_focus_summary()
    finally:
        window.updating_ui = False

    window.update_status_summary()
    window.invalidate_graph_response_cache()
    window.queue_response_draw()
    window.update_preset_state()


def immediate_engine_drag_update(window: MiniEqWindow, index: int, gain_db: float) -> None:
    window.controller.set_band_gain(index, gain_db)
    window.selected_band_index = index
    window.updating_ui = True
    try:
        window.update_band_fader(index)
        window.update_focus_summary()
    finally:
        window.updating_ui = False

    window.invalidate_graph_response_cache()
    window.queue_response_draw()
    window.schedule_curve_metadata_refresh()


def run_benchmarks(window: MiniEqWindow, iterations: int, warmup: int) -> list[BenchmarkResult]:
    band_index = 0
    window.select_band(band_index)
    graph_width, graph_height, left, right, top, bottom = window.graph_plot_bounds(900, 240)

    results = [
        benchmark_call(
            "current-drag-update",
            iterations,
            warmup,
            lambda index: window.on_custom_band_fader_changed(band_index, gain_for_iteration(index)),
        ),
        benchmark_call(
            "legacy-full-refresh-drag-update",
            iterations,
            warmup,
            lambda index: legacy_drag_update(window, band_index, gain_for_iteration(index)),
        ),
        benchmark_call(
            "full-fader-strip-refresh",
            iterations,
            warmup,
            lambda _index: window.update_quick_fader_strip(),
        ),
        benchmark_call(
            "headroom-system-summary",
            iterations,
            warmup,
            lambda _index: window.update_status_summary(),
        ),
        benchmark_call(
            "graph-response-surface-redraw",
            iterations,
            warmup,
            lambda _index: (
                window.invalidate_graph_response_cache(),
                window.graph_cached_response_surface(900, 240, graph_width, graph_height, left, right, top, bottom),
            ),
        ),
        benchmark_call(
            "preset-state-signature",
            iterations,
            warmup,
            lambda _index: window.update_preset_state(),
        ),
    ]

    if getattr(window.controller, "engine_profile", "none") != "none":
        results.insert(
            1,
            benchmark_call(
                f"immediate-engine-drag-update-{window.controller.engine_profile}",
                iterations,
                warmup,
                lambda index: immediate_engine_drag_update(window, band_index, gain_for_iteration(index)),
            ),
        )

    return results


class BenchmarkApplication(Adw.Application):
    def __init__(self, iterations: int, warmup: int, config_dir: Path, engine_profile: str) -> None:
        super().__init__(application_id=f"{APP_ID}.BenchmarkFaderDrag.{engine_profile}.Pid{os.getpid()}")
        self.iterations = iterations
        self.warmup = warmup
        self.config_dir = config_dir
        self.controller = BenchmarkController(engine_profile)
        self.window: MiniEqWindow | None = None
        self.results: list[BenchmarkResult] = []

    def do_activate(self) -> None:
        core.PRESET_STORAGE_DIR = self.config_dir / "mini-eq" / "output"
        core.write_mini_eq_preset_file(
            core.preset_path_for_name(DEMO_PRESET_NAME),
            self.controller.build_preset_payload(DEMO_PRESET_NAME),
        )

        self.window = MiniEqWindow(self, self.controller, auto_route=True)
        self.window.current_preset_name = DEMO_PRESET_NAME
        self.window.saved_preset_signature = self.controller.state_signature()
        self.window.refresh_preset_list()
        self.window.set_visible(True)
        self.window.present()
        GLib.idle_add(self.on_benchmark_idle)

    def on_benchmark_idle(self) -> bool:
        if self.window is None:
            raise RuntimeError("window is not available")

        try:
            self.results = run_benchmarks(self.window, self.iterations, self.warmup)
        finally:
            self.window.prepare_for_shutdown()
            self.quit()
        return False


def print_results(results: list[BenchmarkResult], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps([asdict(result) for result in results], indent=2))
        return

    print("Mini EQ fader drag benchmark")
    print("Lower latency is better. Timings cover synchronous GTK callback work, not PipeWire audio latency.")
    print()
    print(f"{'benchmark':32} {'mean':>10} {'median':>10} {'p95':>10} {'max':>10} {'updates/s':>12}")
    for result in results:
        print(
            f"{result.name:32} "
            f"{result.mean_ms:9.3f}ms "
            f"{result.median_ms:9.3f}ms "
            f"{result.p95_ms:9.3f}ms "
            f"{result.max_ms:9.3f}ms "
            f"{result.updates_per_second:12.0f}"
        )


def parse_budgets(raw_budgets: list[str]) -> dict[str, float]:
    budgets: dict[str, float] = {}
    for raw_budget in raw_budgets:
        name, separator, value = raw_budget.partition("=")
        if not separator or not name:
            raise ValueError(f"invalid budget {raw_budget!r}; expected BENCHMARK=MS")
        try:
            budget_ms = float(value)
        except ValueError as exc:
            raise ValueError(f"invalid budget {raw_budget!r}; MS must be a number") from exc
        if budget_ms <= 0.0:
            raise ValueError(f"invalid budget {raw_budget!r}; MS must be positive")
        budgets[name] = budget_ms
    return budgets


def evaluate_budgets(
    results: list[BenchmarkResult],
    *,
    max_mean_ms: dict[str, float],
    max_p95_ms: dict[str, float],
) -> list[str]:
    result_by_name = {result.name: result for result in results}
    failures: list[str] = []

    for name, budget_ms in max_mean_ms.items():
        result = result_by_name.get(name)
        if result is None:
            failures.append(f"unknown benchmark in --max-mean-ms: {name}")
        elif result.mean_ms > budget_ms:
            failures.append(f"{name} mean {result.mean_ms:.3f}ms exceeded {budget_ms:.3f}ms")

    for name, budget_ms in max_p95_ms.items():
        result = result_by_name.get(name)
        if result is None:
            failures.append(f"unknown benchmark in --max-p95-ms: {name}")
        elif result.p95_ms > budget_ms:
            failures.append(f"{name} p95 {result.p95_ms:.3f}ms exceeded {budget_ms:.3f}ms")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Mini EQ fader drag update paths.")
    parser.add_argument("--iterations", type=int, default=100, help="measured iterations per benchmark")
    parser.add_argument("--warmup", type=int, default=20, help="warmup iterations per benchmark")
    parser.add_argument(
        "--engine-profile",
        choices=("none", "controls", "pod"),
        default="none",
        help="include an immediate engine-apply drag path; pod also builds a WirePlumber SPA pod",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--max-mean-ms",
        action="append",
        default=[],
        metavar="BENCHMARK=MS",
        help="fail if the named benchmark mean exceeds the given milliseconds; repeatable",
    )
    parser.add_argument(
        "--max-p95-ms",
        action="append",
        default=[],
        metavar="BENCHMARK=MS",
        help="fail if the named benchmark p95 exceeds the given milliseconds; repeatable",
    )
    args = parser.parse_args(argv)

    try:
        max_mean_ms = parse_budgets(args.max_mean_ms)
        max_p95_ms = parse_budgets(args.max_p95_ms)
    except ValueError as exc:
        parser.error(str(exc))

    iterations = max(1, args.iterations)
    warmup = max(0, args.warmup)

    Adw.init()
    with tempfile.TemporaryDirectory(prefix="mini-eq-benchmark-") as config_dir:
        app = BenchmarkApplication(iterations, warmup, Path(config_dir), args.engine_profile)
        exit_code = app.run([])
        if exit_code != 0:
            return exit_code
        print_results(app.results, json_output=args.json)
        if args.engine_profile != "none" and not args.json:
            print()
            print(
                "engine apply calls: "
                f"{app.controller.engine_apply_count}, "
                f"control values built: {app.controller.engine_control_count}, "
                f"SPA pods built: {app.controller.engine_pod_count}"
            )

        budget_failures = evaluate_budgets(app.results, max_mean_ms=max_mean_ms, max_p95_ms=max_p95_ms)
        if budget_failures:
            print("benchmark budget failures:", file=sys.stderr)
            for failure in budget_failures:
                print(f"  {failure}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
