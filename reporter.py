from glob import glob
import os
import json
import re
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pandas.errors import EmptyDataError
from errors import ProgramError


class Reporter:
    REQUESTED_EVENTS = [
        "cache-misses",
        "branch-misses",
        "LLC-loads-misses",
        "msr/cpu_thermal_margin/",
        "cpu-clock",
        "cycles",
        "cstate_core/c3-residency/",
        "cstate_core/c6-residency/",
        "cstate_core/c7-residency/",
    ]
    _trailing_comma_pattern = re.compile(r",\s*}")
    _number_comma_pattern = re.compile(r"(\d+),(\d+)")

    def __init__(self, base_dir: str, results_path: str, no_trial: bool, skip: int) -> None:
        self.base_dir = base_dir
        self.results_path = results_path
        self.no_trial = no_trial
        self.skip = skip

    def compile_rapl(self) -> str:
        compiled = []
        mode_paths = sorted(glob(os.path.join(self.results_path, "*")))
        for mode_path in mode_paths:
            if not os.path.isdir(mode_path):
                raise ProgramError("provided input doesn't have any warmup dirs")
            mode_str = os.path.basename(mode_path)
            mode_records = []
            imp_paths = sorted(glob(os.path.join(mode_path, "*")))
            for imp_path in imp_paths:
                imp_str = os.path.basename(imp_path)
                if not os.path.isdir(imp_path):
                    raise ProgramError("provided input doesn't have any language dirs")
                bench_paths = sorted(glob(os.path.join(imp_path, "*")))
                for bench_path in bench_paths:
                    bench_str = os.path.basename(bench_path)
                    if bench_str == "trial-run":
                        continue
                    if not os.path.isdir(bench_path):
                        raise ProgramError("provided input doesn't have any benchmark dirs")
                    rapl_file, cpu = self._find_rapl_file(bench_path)
                    try:
                        df = pd.read_csv(rapl_file, header=0, skiprows=self.skip)
                    except EmptyDataError as ex:
                        raise ProgramError(
                            f"rapl measurement file empty or skipped too many rows - {ex}"
                        )
                    power_unit = int(rapl_file.split("_")[-1].split(".")[0])
                    pkg, core, uncore, dram, time = self._calculate_energy(cpu, df, power_unit)
                    df_record = pd.DataFrame(
                        {
                            "Mode": [mode_str] * len(pkg),
                            "Language": [imp_str] * len(pkg),
                            "Benchmark": [bench_str] * len(pkg),
                            "Time (ms)": time,
                            "Pkg (J)": pkg,
                            "Core (J)": core,
                            "Uncore (J)": uncore,
                            "Dram (J)": dram,
                        }
                    )
                    mode_records.append(df_record)
            trial_path = os.path.join(mode_path, "C", "trial-run")
            trial_data_exists = (
                os.path.exists(trial_path) and os.path.isdir(trial_path) and not self.no_trial
            )
            if trial_data_exists:
                tr_pkg, tr_core, tr_uncore, tr_dram, tr_time = self._get_rapl_averages(trial_path)
                if tr_time > 0:
                    for df_record in mode_records:
                        scale = df_record["Time (ms)"] / tr_time
                        df_record["Pkg (J)"] -= tr_pkg * scale
                        df_record["Core (J)"] -= tr_core * scale
                        df_record["Uncore (J)"] -= tr_uncore * scale
                        df_record["Dram (J)"] -= tr_dram * scale
                    trial_record = pd.DataFrame(
                        {
                            "Mode": [mode_str],
                            "Language": ["C"],
                            "Benchmark": ["trial-run"],
                            "Time (ms)": [tr_time],
                            "Pkg (J)": [tr_pkg],
                            "Core (J)": [tr_core],
                            "Uncore (J)": [tr_uncore],
                            "Dram (J)": [tr_dram],
                        }
                    )
                    mode_records.append(trial_record)
            compiled.extend(mode_records)
        df_compiled = pd.concat(compiled, ignore_index=True)
        numeric_cols = ["Time (ms)", "Pkg (J)", "Core (J)", "Uncore (J)", "Dram (J)"]
        df_compiled[numeric_cols] = df_compiled[numeric_cols].round(2)
        return df_compiled.to_csv(index=False)

    def average_rapl(self) -> str:
        rows = []
        mode_paths = sorted(glob(os.path.join(self.results_path, "*")))
        for mode_path in mode_paths:
            if not os.path.isdir(mode_path):
                continue
            mode_str = os.path.basename(mode_path)
            mode_rows = []
            imp_paths = sorted(glob(os.path.join(mode_path, "*")))
            for imp_path in imp_paths:
                if not os.path.isdir(imp_path):
                    continue
                imp_str = os.path.basename(imp_path)
                avg_pkgs = []
                avg_cores = []
                avg_uncores = []
                avg_drams = []
                avg_times = []
                bench_paths = sorted(glob(os.path.join(imp_path, "*")))
                for bench_path in bench_paths:
                    bench_str = os.path.basename(bench_path)
                    if bench_str == "trial-run":
                        continue
                    if not os.path.isdir(bench_path):
                        continue
                    pkg, core, uncore, dram, t = self._get_rapl_averages(bench_path)
                    avg_pkgs.append(pkg)
                    avg_cores.append(core)
                    avg_uncores.append(uncore)
                    avg_drams.append(dram)
                    avg_times.append(t)
                if not avg_times:
                    continue
                mean_time = np.mean(avg_times)
                mean_pkg = np.mean(avg_pkgs)
                mean_core = np.mean(avg_cores)
                mean_uncore = np.mean(avg_uncores)
                mean_dram = np.mean(avg_drams)
                row = {
                    "Mode": mode_str,
                    "Language": imp_str,
                    "Avg. Time (ms)": mean_time,
                    "Avg. Pkg (J)": mean_pkg,
                    "Avg. Core (J)": mean_core,
                    "Avg. Uncore (J)": mean_uncore,
                    "Avg. Dram (J)": mean_dram,
                }
                mode_rows.append(row)
            trial_path = os.path.join(mode_path, "C", "trial-run")
            if os.path.isdir(trial_path) and not self.no_trial:
                tr_pkg, tr_core, tr_uncore, tr_dram, tr_time = self._get_rapl_averages(trial_path)
                if tr_time > 0 and mode_rows:
                    for row in mode_rows:
                        scale = row["Avg. Time (ms)"] / tr_time
                        row["Avg. Pkg (J)"] -= tr_pkg * scale
                        row["Avg. Core (J)"] -= tr_core * scale
                        row["Avg. Uncore (J)"] -= tr_uncore * scale
                        row["Avg. Dram (J)"] -= tr_dram * scale
                trial_row = {
                    "Mode": mode_str,
                    "Language": "C",
                    "Avg. Time (ms)": tr_time,
                    "Avg. Pkg (J)": tr_pkg,
                    "Avg. Core (J)": tr_core,
                    "Avg. Uncore (J)": tr_uncore,
                    "Avg. Dram (J)": tr_dram,
                }
                mode_rows.append(trial_row)
            rows.extend(mode_rows)
        df = pd.DataFrame(rows)
        cols = [
            "Avg. Time (ms)",
            "Avg. Pkg (J)",
            "Avg. Core (J)",
            "Avg. Uncore (J)",
            "Avg. Dram (J)",
        ]
        for col in cols:
            if col in df.columns:
                df[col] = df[col].round(2)
        return df.to_csv(index=False)

    def average_perf(self) -> str:
        rows = []
        mode_paths = sorted(glob(os.path.join(self.results_path, "*")))
        for mode_path in mode_paths:
            if not os.path.isdir(mode_path):
                continue
            mode_str = os.path.basename(mode_path)
            trial_path = os.path.join(mode_path, "C", "trial-run")
            trial_data_exists = os.path.isdir(trial_path) and not self.no_trial
            if trial_data_exists:
                _, _, _, _, tr_time = self._get_rapl_averages(trial_path)
                perf_file = os.path.join(trial_path, "perf.json")
                if not os.path.exists(perf_file):
                    raise ProgramError(f"no perf measurements found in {trial_path}")
                trial_perf_data = self._parse_perf_file(perf_file)
            else:
                tr_time = 0
                trial_perf_data = None
            imp_paths = sorted(glob(os.path.join(mode_path, "*")))
            for imp_path in imp_paths:
                if not os.path.isdir(imp_path):
                    continue
                imp_str = os.path.basename(imp_path)
                event_accum = {ev: [] for ev in self.REQUESTED_EVENTS}
                times = []
                bench_paths = sorted(glob(os.path.join(imp_path, "*")))
                for bench_path in bench_paths:
                    if not os.path.isdir(bench_path):
                        continue
                    bench_str = os.path.basename(bench_path)
                    if bench_str == "trial-run":
                        continue
                    perf_json = os.path.join(bench_path, "perf.json")
                    if not os.path.exists(perf_json):
                        raise ProgramError(f"no perf measurements found in {bench_path}")
                    perf_data = self._parse_perf_file(perf_json)
                    for ev in self.REQUESTED_EVENTS:
                        if perf_data[ev]:
                            vals = [float(e["counter-value"]) for e in perf_data[ev]]
                            event_accum[ev].append(np.mean(vals))
                    _, _, _, _, b_time = self._get_rapl_averages(bench_path)
                    times.append(b_time)
                row_time = np.mean(times) if times else 0
                if not row_time:
                    continue

                row = {"Mode": mode_str, "Language": imp_str, "Avg. Time (ms)": row_time}
                for ev, arr in event_accum.items():
                    row[f"Avg. {ev}"] = np.mean(arr) if arr else 0.0
                if trial_data_exists and trial_perf_data and tr_time > 0 and row_time > 0:
                    for ev in self.REQUESTED_EVENTS:
                        if trial_perf_data[ev]:
                            overhead_vals = [float(e["counter-value"]) for e in trial_perf_data[ev]]
                            overhead = np.mean(overhead_vals) * row_time / tr_time
                            row[f"Avg. {ev}"] -= overhead
                rows.append(row)
            if trial_data_exists:
                trial_row = {"Mode": mode_str, "Language": "C", "Avg. Time (ms)": tr_time}
                for ev in self.REQUESTED_EVENTS:
                    trial_row[f"Avg. {ev}"] = (
                        np.mean([float(e["counter-value"]) for e in trial_perf_data[ev]])
                        if trial_perf_data[ev]
                        else 0.0
                    )
                rows.append(trial_row)
        df = pd.DataFrame(rows)
        numeric_cols = ["Avg. Time (ms)"] + [f"Avg. {ev}" for ev in self.REQUESTED_EVENTS]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = df[c].round(2)
        return df.to_csv(index=False)

    def interactive(self) -> str:
        rapl_file, cpu = self._find_rapl_file(self.results_path)
        perf_file = os.path.join(self.results_path, "perf.json")
        if not os.path.exists(perf_file):
            raise ProgramError(f"no perf measurements found in {self.results_path}")
        try:
            df = pd.read_csv(rapl_file, header=0, skiprows=self.skip)
        except EmptyDataError as ex:
            raise ProgramError(f"rapl measurement file empty {ex}")
        power_unit = int(rapl_file.split("_")[-1].split(".")[0])
        pk, cr, un, dr, tm = self._calculate_energy(cpu, df, power_unit)
        tm = tm / 1000
        umap = {"Pkg": "J", "Core": "J", "Uncore": "J", "Dram": "J", "Time": "s"}
        rapl_m = {"Pkg": pk, "Core": cr, "Uncore": un, "Dram": dr, "Time": tm}
        rapl_n = self._normalize_metrics(rapl_m)
        fig = go.Figure()
        for k, v in rapl_n.items():
            txt = [f"{val} {umap.get(k, '')}" for val in rapl_m[k]]
            htemp = f"Iteration: <b>%{{x}}</b><br>{k}: <b>%{{text}}</b><extra></extra>"
            fig.add_trace(
                go.Scatter(
                    y=v,
                    name=k,
                    mode="markers+lines",
                    marker=dict(symbol="diamond"),
                    text=txt,
                    hovertemplate=htemp,
                )
            )
        p_data = self._parse_perf_file(perf_file)
        p_metrics = {}
        p_ts = {}
        for key, events in p_data.items():
            cvals = [float(ev["counter-value"]) for ev in events]
            unwrapped = self._unwrap_intervals(events)
            p_metrics[key] = cvals
            p_ts[key] = unwrapped
        p_norm = self._normalize_metrics(p_metrics)
        for key, valz in p_norm.items():
            x_val = [x - p_ts[key][0] for x in p_ts[key]]
            txt = [str(x) for x in p_metrics[key]]
            htemp = f"Timestamp: <b>%{{x}}</b> s<br>{key}: <b>%{{text}}</b><extra></extra>"
            fig.add_trace(
                go.Scatter(
                    x=x_val,
                    y=valz,
                    name=key,
                    mode="lines",
                    text=txt,
                    xaxis="x2",
                    hovertemplate=htemp,
                )
            )
        fig.update_layout(
            title="Interactive RAPL & Perf Metrics",
            xaxis=dict(title="Iterations"),
            xaxis2=dict(title="Elapsed Time (s)", overlaying="x", side="top"),
            yaxis_title="Normalized Measurements",
            legend_title="Metrics",
            colorway=[
                "#000000",
                "#E69F00",
                "#56B4E9",
                "#009E73",
                "#F0E442",
                "#0072B2",
                "#D55E00",
                "#CC79A7",
            ],
        )
        fig.show()
        return ""

    def _get_rapl_averages(self, path: str) -> tuple:
        rapl_file, cpu = self._find_rapl_file(path)
        try:
            df = pd.read_csv(rapl_file, header=0, skiprows=self.skip)
        except EmptyDataError:
            raise ProgramError("rapl measurement file empty or skipped too many rows")
        power_unit = int(rapl_file.split("_")[-1].split(".")[0])
        pkg, core, uncore, dram, t_series = self._calculate_energy(cpu, df, power_unit)
        return pkg.mean(), core.mean(), uncore.mean(), dram.mean(), t_series.mean()

    def _find_rapl_file(self, directory: str) -> tuple[str, str]:
        files = sorted(glob(os.path.join(directory, "Intel_[0-9][0-9]*.csv")))
        cpu = "intel"
        if not files:
            files = sorted(glob(os.path.join(directory, "AMD_[0-9][0-9]*.csv")))
            cpu = "amd"
        if not files:
            raise ProgramError(f"no rapl measurement found in {directory}")
        return files[0], cpu

    def _calculate_energy(
        self, cpu: str, df: pd.DataFrame, power_unit: int
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        multiplier = 0.5 ** ((power_unit >> 8) & 0x1F)
        tm = df.iloc[:, 1] - df.iloc[:, 0]
        if cpu == "intel":
            cr = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 2], df.iloc[:, 3])],
                index=df.index,
            )
            un = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 4], df.iloc[:, 5])],
                index=df.index,
            )
            pk = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 6], df.iloc[:, 7])],
                index=df.index,
            )
            dr = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 8], df.iloc[:, 9])],
                index=df.index,
            )
        elif cpu == "amd":
            cr = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 2], df.iloc[:, 3])],
                index=df.index,
            )
            un = pd.Series(0, index=df.index).astype(float)
            pk = pd.Series(
                [self._safe_diff(a, b, multiplier) for b, a in zip(df.iloc[:, 4], df.iloc[:, 5])],
                index=df.index,
            )
            dr = pd.Series(0, index=df.index).astype(float)
        else:
            raise ValueError("Unsupported CPU type")
        return pk, cr, un, dr, tm

    @staticmethod
    def _safe_diff(current, previous, multiplier, bits=32):
        max_val = 2**bits - 1
        if current < previous:
            return (current + max_val + 1 - previous) * multiplier
        return (current - previous) * multiplier

    def _parse_perf_file(self, perf_path: str) -> dict:
        req = {ev: [] for ev in self.REQUESTED_EVENTS}
        with open(perf_path, "r") as f:
            for line in f:
                line = self._trailing_comma_pattern.sub("}", line)
                line = self._number_comma_pattern.sub(r"\1.\2", line)
                data = json.loads(line)
                event_name = data.get("event", "")
                for key in req:
                    if key in event_name:
                        req[key].append(data)
        return req

    def _unwrap_intervals(self, events):
        ts = [float(ev["interval"]) for ev in events]
        unwrapped = []
        offset = 0.0
        last_val = None
        for val in ts:
            if last_val is not None and val < last_val:
                offset += last_val
            unwrapped.append(val + offset)
            last_val = val
        return unwrapped

    def _normalize_metrics(self, metrics: dict) -> dict:
        out = {}
        for k, v in metrics.items():
            if v is not None and len(v) > 0:
                if hasattr(v, "min") and hasattr(v, "max"):
                    mn = v.min()
                    mx = v.max()
                    out[k] = (v - mn) / (mx - mn) if mx > mn else v
                else:
                    mn, mx = min(v), max(v)
                    out[k] = [(x - mn) / (mx - mn) if mx > mn else x for x in v]
            else:
                out[k] = v
        return out
