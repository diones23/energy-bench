import plotly.graph_objects as go
from pandas.errors import EmptyDataError
from glob import glob
from typing import Any
import pandas as pd
import numpy as np
import argparse
import os
import json
import re
import sys

from commands.base import BaseCommand
from utils import *


class ReportCommand(BaseCommand):
    name = "report"
    help = "Build reports from raw measurements"

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
    _UNIT_MAP = {"Pkg": "J", "Core": "J", "Uncore": "J", "Dram": "J", "Time": "s"}
    _COLORWAY = [
        "#000000",
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#0072B2",
        "#D55E00",
        "#CC79A7",
    ]

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-s", "--skip", type=int, default=0, help="Number of rows to skip for each measurement"
        )
        parser.add_argument(
            "-ar",
            "--average-rapl",
            action="store_true",
            help="Produce a CSV table with averaged RAPL results",
        )
        parser.add_argument(
            "-ap",
            "--average-perf",
            action="store_true",
            help="Produce a CSV table with averaged perf results",
        )
        parser.add_argument(
            "-v",
            "--violin",
            action="store_true",
            help="Produce violin and box-plots for each measurement",
        )
        parser.add_argument(
            "-i",
            "--interactive",
            action="store_true",
            help="Produce interactive HTML plots for each measurement",
        )
        parser.add_argument(
            "-f",
            "--format",
            choices=["csv", "json"],
            default="csv",
            help="Output format for results",
        )
        parser.add_argument("results", nargs="+", type=self.dir_path, default=[sys.stdin], help="")

    def handle(self, args: argparse.Namespace) -> None:
        result = None

        if args.average_rapl:
            result = self.average_rapl(args)
        elif args.average_perf:
            result = self.average_perf(args)
        elif args.interactive:
            self.interactive(args)
            return
        else:
            result = self.compile_rapl(args)

        self.output_result(result, args)

    def output_result(self, result: str | pd.DataFrame, args: argparse.Namespace) -> None:
        if isinstance(result, pd.DataFrame):
            if args.format == "csv":
                output = result.to_csv(index=False)
            elif args.format == "json":
                output = result.to_json(orient="records")
            else:
                output = result.to_csv(index=False)
        else:
            output = result

        print(output)

    def split_energy_path(self, result: str) -> tuple[str, str, str, str, str, str]:
        path = os.path.abspath(os.path.expanduser(result)).rstrip(os.sep)

        if os.path.isfile(path):
            path = os.path.dirname(path)

        parts = path.split(os.sep)
        if len(parts) < 4:
            raise ProgramError(f"Run directory {result!r} doesn't have the expected structure")

        bench = parts[-1]
        lang = parts[-2]
        warmup = parts[-3]
        run_dir = parts[-4]

        if run_dir.count("_") < 2:
            raise ProgramError(f"Run directory {run_dir!r} does not match <env>_<work>_<time>")

        env, work, time = run_dir.split("_", 2)

        return env, work, time, warmup, lang, bench

    def read_rapl_file(self, file_path: str, skip_rows: int) -> tuple[pd.DataFrame, str, int]:
        try:
            df = pd.read_csv(file_path, header=0, skiprows=skip_rows)
            if df.empty:
                raise ProgramError(
                    f"RAPL measurement file {file_path} is empty after skipping {skip_rows} rows"
                )

            if len(df.columns) < 10:
                raise ProgramError(
                    f"RAPL file {file_path} has insufficient columns: {len(df.columns)}"
                )

            cpu_type = "intel" if "Intel" in os.path.basename(file_path) else "amd"
            power_unit = int(file_path.split("_")[-1].split(".")[0])

            return df, cpu_type, power_unit
        except EmptyDataError:
            raise ProgramError(
                f"RAPL measurement file {file_path} is empty or formatted incorrectly"
            )
        except Exception as e:
            raise ProgramError(f"Error reading RAPL file {file_path}: {str(e)}")

    def compile_rapl(self, args: argparse.Namespace) -> pd.DataFrame:
        compiled = []
        trial_averages = []

        for result in args.results:
            _, _, _, mode, lang, bench = self.split_energy_path(result)

            if bench == "trial-run":
                tp, tc, tu, td, tt = self.get_rapl_averages(result, args.skip)
                trial_averages.append(
                    {
                        "Mode": mode,
                        "Language": lang,
                        "Benchmark": bench,
                        "Time (ms)": tt,
                        "Pkg (J)": tp,
                        "Core (J)": tc,
                        "Uncore (J)": tu,
                        "Dram (J)": td,
                    }
                )
            else:
                rapl_path, cpu_type = self.find_rapl_file(result)
                df, cpu_type, power_unit = self.read_rapl_file(rapl_path, args.skip)
                p, c, u, d, t = self.calculate_energy(cpu_type, df, power_unit)

                compiled.append(
                    pd.DataFrame(
                        {
                            "Mode": mode,
                            "Language": lang,
                            "Benchmark": bench,
                            "Time (ms)": t,
                            "Pkg (J)": p,
                            "Core (J)": c,
                            "Uncore (J)": u,
                            "Dram (J)": d,
                        }
                    )
                )

        self.apply_trial_correction(compiled, trial_averages)

        for average in trial_averages:
            compiled.append(pd.DataFrame([average]))

        df_compiled = pd.concat(compiled, ignore_index=True) if compiled else pd.DataFrame()

        if not df_compiled.empty:
            numeric_cols = ["Time (ms)", "Pkg (J)", "Core (J)", "Uncore (J)", "Dram (J)"]
            df_compiled[numeric_cols] = df_compiled[numeric_cols].round(2)

        return df_compiled

    def apply_trial_correction(self, compiled_dfs: list[pd.DataFrame], trials: list[dict]) -> None:
        for average in trials:
            for df in compiled_dfs:
                df_mode = df["Mode"].iloc[0]
                df_time = df["Time (ms)"].iloc[0]
                avg_time = average["Time (ms)"]

                if df_mode == average["Mode"]:
                    scale = df_time / avg_time
                    df["Pkg (J)"] -= average["Pkg (J)"] * scale
                    df["Core (J)"] -= average["Core (J)"] * scale
                    df["Uncore (J)"] -= average["Uncore (J)"] * scale
                    df["Dram (J)"] -= average["Dram (J)"] * scale

    def average_rapl(self, args: argparse.Namespace) -> pd.DataFrame:
        compiled = []
        trial_averages = []

        for result in args.results:
            _, _, _, mode, lang, bench = self.split_energy_path(result)
            p, c, u, d, t = self.get_rapl_averages(result, args.skip)
            row = {
                "Mode": mode,
                "Language": lang,
                "Time (ms)": t,
                "Pkg (J)": p,
                "Core (J)": c,
                "Uncore (J)": u,
                "Dram (J)": d,
            }
            if bench == "trial-run":
                trial_averages.append(row)
            else:
                compiled.append(pd.DataFrame([row]))

        self.apply_trial_correction(compiled, trial_averages)

        metric_cols = ["Time (ms)", "Pkg (J)", "Core (J)", "Uncore (J)", "Dram (J)"]
        summary_parts = []

        if compiled:
            df_norm_summary = (
                pd.concat(compiled, ignore_index=True)
                .groupby(["Language", "Mode"], as_index=False)[metric_cols]
                .mean()
                .round(2)
            )
            summary_parts.append(df_norm_summary)

        if trial_averages:
            df_trial = pd.DataFrame(trial_averages).assign(Language="trial-run")
            df_trial_summary = (
                df_trial[["Language", "Mode"] + metric_cols]
                .groupby(["Language", "Mode"], as_index=False)[metric_cols]
                .mean()
                .round(2)
            )
            summary_parts.append(df_trial_summary)

        if summary_parts:
            return pd.concat(summary_parts, ignore_index=True)

        return pd.DataFrame(columns=["Language", "Mode"] + metric_cols)

    def average_perf(self, args: argparse.Namespace) -> pd.DataFrame:
        compiled = []
        trials = []

        for result in args.results:
            _, _, _, mode, lang, bench = self.split_energy_path(result)

            perf_path = os.path.join(result, "perf.json")
            if not os.path.exists(perf_path):
                raise ProgramError(f"No perf measurements found in {result!r}")

            perf_data = self.parse_perf_file(perf_path)
            avg_counters = {}
            for ev in self.REQUESTED_EVENTS:
                vals = [float(e["counter-value"]) for e in perf_data.get(ev, [])]
                avg_counters[ev] = float(np.mean(vals)) if vals else 0.0

            _, _, _, _, t = self.get_rapl_averages(result, args.skip)

            row = {
                "Mode": mode,
                "Language": "trial-run" if bench == "trial-run" else lang,
                "Avg. Time (ms)": t,
                **{f"Avg. {ev}": avg_counters[ev] for ev in self.REQUESTED_EVENTS},
            }

            if bench == "trial-run":
                trials.append(row)
            else:
                compiled.append(row)

        trial_map = self.process_perf_trials(trials)
        adjusted = self.adjust_perf_measurements(compiled, trial_map)

        metric_cols = ["Avg. Time (ms)"] + [f"Avg. {ev}" for ev in self.REQUESTED_EVENTS]
        parts = []

        if adjusted:
            df_adj = pd.DataFrame(adjusted)
            df_norm = (
                df_adj.groupby(["Language", "Mode"], as_index=False)[metric_cols].mean().round(2)
            )
            parts.append(df_norm)

        if trials:
            trial_summary = []
            for mode, (_, _) in trial_map.items():
                mode_trials = [t for t in trials if t["Mode"] == mode]
                if mode_trials:
                    trial_df = pd.DataFrame(mode_trials)
                    agg = trial_df[metric_cols].mean().to_dict()
                    agg["Mode"] = mode
                    agg["Language"] = "trial-run"
                    trial_summary.append(agg)

            if trial_summary:
                df_tr = pd.DataFrame(trial_summary)
                df_trial = (
                    df_tr.groupby(["Language", "Mode"], as_index=False)[metric_cols].mean().round(2)
                )
                parts.append(df_trial)

        if parts:
            return pd.concat(parts, ignore_index=True)

        return pd.DataFrame(columns=["Language", "Mode"] + metric_cols)

    def process_perf_trials(self, trials: list[dict]) -> dict:
        if not trials:
            return {}

        trial_map = {}
        for tr in trials:
            trial_map.setdefault(tr["Mode"], []).append(tr)

        result = {}
        for mode, rows in trial_map.items():
            ts = pd.DataFrame(rows)
            cols = ["Avg. Time (ms)"] + [f"Avg. {ev}" for ev in self.REQUESTED_EVENTS]
            agg = ts[cols].mean(numeric_only=True).to_dict()
            result[mode] = (
                agg["Avg. Time (ms)"],
                {ev: agg[f"Avg. {ev}"] for ev in self.REQUESTED_EVENTS},
            )

        return result

    def adjust_perf_measurements(self, compiled: list[dict], trial_map: dict) -> list[dict]:
        adjusted = []
        for row in compiled:
            mode = row["Mode"]
            time_ms = row["Avg. Time (ms)"]
            r = row.copy()
            if mode in trial_map:
                tr_time, tr_counters = trial_map[mode]
                if tr_time > 0 and time_ms > 0:
                    scale_factor = time_ms / tr_time
                    for ev in self.REQUESTED_EVENTS:
                        key = f"Avg. {ev}"
                        r[key] = round(r[key] - tr_counters[ev] * scale_factor, 2)
            adjusted.append(r)
        return adjusted

    def interactive(self, args: argparse.Namespace):
        first_result = args.results[0]
        rapl_path, cpu_type = self.find_rapl_file(first_result)
        perf_path = os.path.join(first_result, "perf.json")
        _, _, _, mode, lang, bench = self.split_energy_path(first_result)

        if not os.path.exists(perf_path):
            raise ProgramError(f"No perf measurements found in {first_result}")

        df, cpu_type, power_unit = self.read_rapl_file(rapl_path, args.skip)

        pk, cr, un, dr, tm = self.calculate_energy(cpu_type, df, power_unit)
        tm = tm / 1000

        rapl_m = {"Pkg": pk, "Core": cr, "Uncore": un, "Dram": dr, "Time": tm}
        rapl_n = self.normalize_metrics(rapl_m)

        fig = go.Figure()

        for k, v in rapl_n.items():
            txt = [f"{val} {self._UNIT_MAP.get(k, '')}" for val in rapl_m[k]]
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

        p_data = self.parse_perf_file(perf_path)
        p_metrics = {}
        p_ts = {}

        for key, events in p_data.items():
            cvals = [float(ev["counter-value"]) for ev in events]
            unwrapped = self.unwrap_intervals(events)
            p_metrics[key] = cvals
            p_ts[key] = unwrapped

        p_norm = self.normalize_metrics(p_metrics)

        for key, valz in p_norm.items():
            if p_ts[key]:
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
            title=f"Interactive RAPL & Perf Metrics<br>{mode} {lang} {bench}",
            xaxis=dict(title="Iterations"),
            xaxis2=dict(title="Elapsed Time (s)", overlaying="x", side="top"),
            yaxis_title="Normalized Measurements",
            legend_title="Metrics",
            colorway=self._COLORWAY,
        )

        fig.show()

    def dir_path(self, value: str) -> str:
        if not os.path.exists(value) or not os.path.isdir(value):
            raise argparse.ArgumentTypeError(f"{value!r} is not a directory")
        return os.path.abspath(value)

    def get_rapl_averages(self, path: str, skip: int) -> tuple[float, float, float, float, float]:
        rapl_path, cpu_type = self.find_rapl_file(path)
        df, cpu_type, power_unit = self.read_rapl_file(rapl_path, skip)
        pkg, core, uncore, dram, t_series = self.calculate_energy(cpu_type, df, power_unit)
        return (
            float(pkg.mean()),
            float(core.mean()),
            float(uncore.mean()),
            float(dram.mean()),
            float(t_series.mean()),
        )

    def find_rapl_file(self, directory: str) -> tuple[str, str]:
        files = sorted(glob(os.path.join(directory, "Intel_[0-9][0-9]*.csv")))
        cpu = "intel"
        if not files:
            files = sorted(glob(os.path.join(directory, "AMD_[0-9][0-9]*.csv")))
            cpu = "amd"
        if not files:
            raise ProgramError(f"No RAPL measurement found in {directory}")
        return files[0], cpu

    def calculate_energy(
        self, cpu: str, df: pd.DataFrame, power_unit: int
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        if len(df.columns) < 10:
            raise ProgramError(f"RAPL dataframe has insufficient columns: {len(df.columns)}")

        tm = df.iloc[:, 1] - df.iloc[:, 0]

        multiplier = 0.5 ** ((power_unit >> 8) & 0x1F)

        if cpu == "intel":
            cr = self._calculate_diff_series(df.iloc[:, 3], df.iloc[:, 2], multiplier)
            un = self._calculate_diff_series(df.iloc[:, 5], df.iloc[:, 4], multiplier)
            pk = self._calculate_diff_series(df.iloc[:, 7], df.iloc[:, 6], multiplier)
            dr = self._calculate_diff_series(df.iloc[:, 9], df.iloc[:, 8], multiplier)
        elif cpu == "amd":
            cr = self._calculate_diff_series(df.iloc[:, 3], df.iloc[:, 2], multiplier)
            un = pd.Series(0, index=df.index).astype(float)
            pk = self._calculate_diff_series(df.iloc[:, 5], df.iloc[:, 4], multiplier)

            if len(df.columns) >= 8:
                dr = self._calculate_diff_series(df.iloc[:, 7], df.iloc[:, 6], multiplier)
            else:
                dr = pd.Series(0, index=df.index).astype(float)
        else:
            raise ValueError(f"Unsupported CPU type: {cpu}")

        return pk, cr, un, dr, tm

    def _calculate_diff_series(
        self, current: pd.Series, previous: pd.Series, multiplier: float, bits: int = 32
    ) -> pd.Series:
        max_val = 2**bits - 1

        mask = current < previous
        result = pd.Series(index=current.index, dtype=float)

        result[mask] = (current[mask] + max_val + 1 - previous[mask]) * multiplier

        result[~mask] = (current[~mask] - previous[~mask]) * multiplier

        return result

    def parse_perf_file(self, perf_path: str) -> dict[str, list[dict[str, Any]]]:
        req = {ev: [] for ev in self.REQUESTED_EVENTS}

        try:
            with open(perf_path, "r") as f:
                for line in f:
                    line = self._trailing_comma_pattern.sub("}", line)
                    line = self._number_comma_pattern.sub(r"\1.\2", line)

                    try:
                        data = json.loads(line)
                        event_name = data.get("event", "")

                        for key in req:
                            if key in event_name:
                                req[key].append(data)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            raise ProgramError(f"Error reading perf file {perf_path}: {str(e)}")

        return req

    def unwrap_intervals(self, events: list[dict[str, Any]]) -> list[float]:
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

    def normalize_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        out = {}

        for k, v in metrics.items():
            if v is not None and len(v) > 0:
                if hasattr(v, "min") and hasattr(v, "max"):
                    mn, mx = v.min(), v.max()
                    out[k] = (v - mn) / (mx - mn) if mx > mn else v
                else:
                    mn, mx = min(v), max(v)
                    if mx > mn:
                        out[k] = [(x - mn) / (mx - mn) for x in v]
                    else:
                        out[k] = v
            else:
                out[k] = v

        return out
