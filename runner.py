from dataclasses import MISSING, fields
import time
import os

from spec import Implementation, Specification
from environments import Environment
from workloads import Workload
from errors import ProgramError
from utils import *
import languages
import workloads


class Runner:
    ENERGY_INSTRUCTIONS = """
# Context & Task
You are an agent who excels in generating programming code for the purpose of doing energy measurements.
Expect the following instructions to involve many possible problems that need to be written in any programming language.

Your main objective is to correctly solve the problem while making the solution **reproducible**:
- A reproducible solution is called a **benchmark**.
- A reproducible solution strictly follows the **reproducibility protocol** shown below.

There are two possible loop structures, depending on whether you have an initialization/cleanup phase:

1) If initialization and cleanup phases are required:

loop do
    <initialization phase putting the benchmark in a consistent state>
    if start_rapl() == 0 then break
    <run solution>
    stop_rapl()
    <cleanup phase>
end

2) If there is no state to initialize or cleanup:

while start_rapl() != 0
    <run solution>
    stop_rapl()
end

- Everything between the call to start_rapl() and stop_rapl() is part of the measurable benchmark.
- Code that is outside this region (such as initialization or cleanup) is never measured.
- If start_rapl() returns 0, do not run the solution. Simply exit the loop.

## Strict requirements:
1. The code must use the "{language}" language.
2. The following dependencies must be used: "{dependencies}".
3. The entire solution must fit in a single file; do not split it across multiple files.
4. DO NOT add any comments whatsoever.
5. DO NOT format the code with Markdown backticks (```) or any other markup. Only output raw code.
6. Do not print anything beyond what is necessary for the solution itself (e.g., no debug statements).
7. If initialization or cleanup is unnecessary, use the simpler loop form.

## Programming problem to solve:
"{description}"

## Example usage of the reproducibility protocol for the "{language}" language:
"{rapl_interface_standard}"

Note:
- The start_rapl() library function reads the RAPL_ITERATIONS environment variable internally and returns an integer denoting how many iterations remain.
    """

    def __init__(
        self, base_dir: str, env: Environment, workload: Workload, timestamp: float
    ) -> None:
        self.base_dir = base_dir
        self.env = env
        self.workload = workload
        self.timestamp = timestamp

    def run_benchmark(
        self, data: dict, warmup: bool, iterations: int, sleep: int, frequency: int, niceness: int
    ) -> bool:
        imp = self._build_language(data, warmup, iterations, frequency, niceness)
        if not imp:
            return False

        try:
            # Reversed order to make building & cleaning more efficient
            with imp, self.workload, self.env:
                splash = self._splash_screen(imp, warmup, iterations, sleep, frequency)
                print(splash)

                if warmup:
                    imp.measure()
                    imp.verify(iterations)
                else:
                    for _ in range(iterations):
                        imp.measure()
                        imp.verify(1)

            imp.move_rapl(self.workload, self.timestamp)
            imp.move_perf(self.workload, self.timestamp)

            print_success("ok")
            if sleep:
                print_info(f"sleeping for {sleep} seconds")
                time.sleep(sleep)
        except ProgramError as ex:
            self._cleanup(imp)
            print_error(str(ex))
            return False
        except KeyboardInterrupt as ex:
            print_warning("manually exited")
            return False
        return True

    def _cleanup(self, imp: Implementation) -> None:
        perf_path = os.path.join(imp.benchmark_path, "perf.json")
        intel_path = os.path.join(imp.benchmark_path, "Intel_[0-9][0-9]*.csv")
        amd_path = os.path.join(imp.benchmark_path, "AMD_[0-9][0-9]*.csv")
        remove_files_if_exist(perf_path)
        remove_files_if_exist(intel_path)
        remove_files_if_exist(amd_path)

    def _get_lang_cls(self, language_str: str) -> type[Implementation] | None:
        lstr = language_str.lower().strip()
        for cls in all_subclasses(Implementation):
            if hasattr(cls, "aliases") and lstr in cls.aliases:
                return cls
        return None

    def _splash_screen(
        self, spec, warmup: bool, iterations: int, sleep: int, frequency: int
    ) -> str:
        estr = self.env.__class__.__name__.lower()
        wstr = self.workload.__class__.__name__.lower()

        if estr == "environment":
            estr = None

        if wstr == "workload":
            wstr = None

        return (
            f"\033[1mbenchmark   :\033[0m {spec.name} | \033[1mlanguage:\033[0m {spec.language} | \033[1mwarmup:\033[0m {'Yes' if warmup else 'No'} | \033[1miterations:\033[0m {iterations} | \033[1mperf freq:\033[0m {frequency}ms | \033[1msleep:\033[0m {sleep}s\n"
            f"\033[1menvironment :\033[0m {estr} | \033[1mworkload:\033[0m {wstr}\n"
            f"{self.env}"
        )

    def _build_language(
        self, yaml: dict, warmup: bool, iterations: int, frequency: int, niceness: int
    ) -> Implementation | None:
        spec_map = {f.name for f in fields(Specification)}
        required_map = {
            f.name
            for f in fields(Specification)
            if f.default is MISSING and f.default_factory is MISSING
        }
        missing = [key for key in required_map if key not in yaml]
        if missing:
            print_error(f"benchmark missing required key(s) - {', '.join(missing)}")
            return None

        filtered = {k: v for k, v in yaml.items() if k in spec_map}
        if "args" in filtered and filtered["args"]:
            filtered["args"] = [str(arg) for arg in filtered["args"]]

        lstr = filtered["language"]
        lcls = self._get_lang_cls(lstr)
        if not lcls:
            print_error(f"{lstr} not available")
            return None

        try:
            return lcls(
                base_dir=self.base_dir,
                warmup=warmup,
                iterations=iterations,
                frequency=frequency,
                niceness=niceness,
                **filtered,
            )
        except TypeError as ex:
            print_error(f"failed initializing specification - {ex}")
            return None
