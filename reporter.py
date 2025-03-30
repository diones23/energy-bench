from glob import glob
import pandas as pd
import numpy as np
import os
import json
import re

from pandas.errors import EmptyDataError
from pandas import Series

from errors import ReportError


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

    def __init__(self, base_dir: str, results_path: str, skip: int) -> None:
        self.base_dir = base_dir
        self.results_path = results_path
        self.skip = skip

    def _calculate_energy(
        self, cpu: str, df: pd.DataFrame, power_unit: int
    ) -> tuple[Series, Series, Series, Series, Series]:
        multiplier = 0.5 ** ((power_unit >> 8) & 0x1F)
        if cpu == "intel":
            time = df.iloc[:, 1] - df.iloc[:, 0]
            core = (df.iloc[:, 3] - df.iloc[:, 2]) * multiplier
            uncore = (df.iloc[:, 5] - df.iloc[:, 4]) * multiplier
            pkg = (df.iloc[:, 7] - df.iloc[:, 6]) * multiplier
            dram = (df.iloc[:, 9] - df.iloc[:, 8]) * multiplier
        elif cpu == "amd":
            time = df.iloc[:, 1] - df.iloc[:, 0]
            core = (df.iloc[:, 3] - df.iloc[:, 2]) * multiplier
            uncore = pd.Series(0, index=df.index)
            pkg = (df.iloc[:, 5] - df.iloc[:, 4]) * multiplier
            dram = pd.Series(0, index=df.index)
        else:
            raise ValueError(f"Unsupported CPU type: {cpu}")

        return pkg, core, uncore, dram, time

    def compile_results(self) -> str:
        compiled = []
        mode_paths = os.path.join(self.results_path, "*")
        for mode_path in glob(mode_paths):
            mode_str = os.path.basename(mode_path)

            lang_paths = os.path.join(mode_path, "*")
            for lang_path in glob(lang_paths):
                lang_str = os.path.basename(lang_path)

                bench_paths = os.path.join(lang_path, "*")
                for bench_path in glob(bench_paths):
                    bench_str = os.path.basename(bench_path)

                    rapls = glob(os.path.join(bench_path, "Intel_[0-9][0-9]*.csv"))
                    cpu = "intel"
                    if not rapls:
                        rapls = glob(os.path.join(bench_path, "AMD_[0-9][0-9]*.csv"))
                        cpu = "amd"

                    if not rapls:
                        raise ReportError(f"No rapl measurement found in {bench_path}")

                    try:
                        df = pd.read_csv(rapls[0], header=0, skiprows=self.skip)
                    except EmptyDataError as ex:
                        raise ReportError(f"Rapl measurement file empty or skipped too many rows")

                    power_unit = int(rapls[0].split("_")[-1].split(".")[0])
                    pkg, core, uncore, dram, time = self._calculate_energy(cpu, df, power_unit)

                    compiled.append(
                        pd.DataFrame(
                            {
                                "Mode": mode_str,
                                "Language": lang_str,
                                "Benchmark": bench_str,
                                "Time (ms)": time.round(2),
                                "Pkg (J)": pkg.round(2),
                                "Core (J)": core.round(2),
                                "Uncore (J)": uncore.round(2),
                                "Dram (J)": dram.round(2),
                            }
                        )
                    )
        compiled = pd.concat(compiled, ignore_index=True)
        return pd.DataFrame(compiled).to_csv(index=False)

    def average_rapl_results(self) -> str:
        averages = []
        mode_paths = os.path.join(self.results_path, "*")
        for mode_path in glob(mode_paths):
            mode_str = os.path.basename(mode_path)

            lang_paths = os.path.join(mode_path, "*")
            for lang_path in glob(lang_paths):
                lang_str = os.path.basename(lang_path)
                avg_times = []
                avg_pkgs = []
                avg_cores = []
                avg_uncores = []
                avg_drams = []

                bench_paths = os.path.join(lang_path, "*")
                for bench_path in glob(bench_paths):
                    rapls = glob(os.path.join(bench_path, "Intel_[0-9][0-9]*.csv"))
                    cpu = "intel"
                    if not rapls:
                        rapls = glob(os.path.join(bench_path, "AMD_[0-9][0-9]*.csv"))
                        cpu = "amd"

                    if not rapls:
                        raise ReportError(f"No rapl measurement found in {bench_path}")

                    try:
                        df = pd.read_csv(rapls[0], header=0, skiprows=self.skip)
                    except EmptyDataError:
                        raise ReportError(f"Rapl measurement file empty or skipped too many rows")
                    power_unit = int(rapls[0].split("_")[-1].split(".")[0])
                    pkg, core, uncore, dram, time = self._calculate_energy(cpu, df, power_unit)

                    avg_times.append(time.mean())
                    avg_pkgs.append(pkg.mean())
                    avg_cores.append(core.mean())
                    avg_uncores.append(uncore.mean())
                    avg_drams.append(dram.mean())

                lang_avg = {
                    "Mode": mode_str,
                    "Language": lang_str,
                    "Avg. Time (ms)": round(np.mean(avg_times), 2),
                    "Avg. Pkg (J)": round(np.mean(avg_pkgs), 2),
                    "Avg. Core (J)": round(np.mean(avg_cores), 2),
                    "Avg. Uncore (J)": round(np.mean(avg_uncores), 2),
                    "Avg. Dram (J)": round(np.mean(avg_drams), 2),
                }

                averages.append(lang_avg)

        return pd.DataFrame(averages).to_csv(index=False)

    def _parse_perf_file(self, perf_path: str) -> dict:
        requested_events = {event: [] for event in self.REQUESTED_EVENTS}

        with open(perf_path, "r") as file:
            for line in file:
                line = self._trailing_comma_pattern.sub("}", line)
                line = self._number_comma_pattern.sub(r"\1.\2", line)
                try:
                    event_data = json.loads(line)
                except json.JSONDecodeError as ex:
                    raise ReportError(f"Error parsing JSON in {perf_path}: {ex}")

                event_name = event_data.get("event", "")
                for key in requested_events:
                    if key in event_name:
                        requested_events[key].append(event_data)
        return requested_events

    def average_perf_results(self) -> str:
        averages = []
        mode_paths = os.path.join(self.results_path, "*")
        for mode_path in glob(mode_paths):
            mode_str = os.path.basename(mode_path)

            lang_paths = os.path.join(mode_path, "*")
            for lang_path in glob(lang_paths):
                lang_str = os.path.basename(lang_path)
                bench_averages = {event: [] for event in self.REQUESTED_EVENTS}

                bench_paths = os.path.join(lang_path, "*")
                for bench_path in glob(bench_paths):
                    perfs = glob(os.path.join(bench_path, "perf.json"))
                    if not perfs:
                        raise ReportError(f"No perf measurements found in {bench_path}")

                    perf_data = self._parse_perf_file(perfs[0])
                    for event in self.REQUESTED_EVENTS:
                        if not perf_data[event]:
                            continue
                        values = [float(ev["counter-value"]) for ev in perf_data[event]]
                        bench_averages[event].append(np.mean(values))

                lang_avg = {}
                for event, values in bench_averages.items():
                    lang_avg[f"Avg. {event}"] = np.round(np.mean(values), 2) if values else 0.0
                lang_avg = {"Mode": f"{mode_str}", "Language": lang_str, **lang_avg}

                averages.append(lang_avg)

        return pd.DataFrame(averages).to_csv(index=False)
