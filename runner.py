from dataclasses import fields, MISSING
from datetime import datetime, timezone
import os

from spec import Benchmark, Language
from errors import ProgramError
from environments import Environment
from utils import *
from workloads import Workload
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

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.timestamp = datetime.now(timezone.utc).timestamp()

    def run_benchmark(
        self,
        yaml: dict,
        env: Environment,
        workload_str: str,
        warmup: bool,
        iterations: int,
        frequency: int,
    ) -> bool:
        language = self._setup(yaml, env, warmup, iterations, frequency)
        if not language:
            return False

        workload = self._get_workload_instance(workload_str)
        if not workload:
            print_error(f"{workload_str} not available")
            return False

        try:
            with language, workload, env:  # Reversed order to make building more efficient
                splash = create_splash_screen(
                    env, workload, language, warmup, iterations, frequency, timestamp=self.timestamp
                )
                print(splash)
                print("")

                if warmup:
                    language.measure()
                    language.verify(iterations)
                else:
                    for _ in range(iterations):
                        language.measure()
                        language.verify(1)

                language.move_rapl(workload, self.timestamp)
                language.move_perf(workload, self.timestamp)
        except ProgramError as ex:
            perf_path = os.path.join(language.benchmark_path, "perf.json")
            intel_path = os.path.join(language.benchmark_path, "Intel_[0-9][0-9]*.csv")
            amd_path = os.path.join(language.benchmark_path, "AMD_[0-9][0-9]*.csv")
            remove_files_if_exist(perf_path)
            remove_files_if_exist(intel_path)
            remove_files_if_exist(amd_path)
            print_error(str(ex))
            return False
        except KeyboardInterrupt as ex:
            print_error("Manually exited")
            return False
        print_success("Ok")
        print("")
        return True

    def _all_subclasses(self, cls):
        return cls.__subclasses__() + [
            g for s in cls.__subclasses__() for g in self._all_subclasses(s)
        ]

    def _get_language_class_by_str(self, language_str: str) -> type[Language] | None:
        language_str = language_str.lower().strip()
        for subclass in self._all_subclasses(Language):
            if hasattr(subclass, "aliases") and language_str in subclass.aliases:
                return subclass
        return None

    def _get_workload_instance(self, workload_str: str) -> Workload | None:
        workload_str = workload_str.lower().strip()
        if workload_str == "workload":
            return Workload()

        for subclass in self._all_subclasses(Workload):
            if subclass.__name__.lower() == workload_str:
                return subclass()
        return None

    def _setup(
        self,
        yaml: dict,
        env: Environment,
        warmup: bool,
        iterations: int,
        frequency: int,
    ) -> Language | None:
        # Build Benchmark
        all_mappings = {f.name for f in fields(Benchmark)}
        required_mappings = {
            f.name
            for f in fields(Benchmark)
            if f.default is MISSING and f.default_factory is MISSING
        }
        required_mappings.add("language")
        missing_keys = [key for key in required_mappings if key not in yaml]
        if missing_keys:
            print_error(f"benchmark missing required key(s) - {', '.join(missing_keys)}")
            return None

        filtered = {k: v for k, v in yaml.items() if k in all_mappings}
        if "args" in filtered and filtered["args"]:
            filtered["args"] = [str(arg) for arg in filtered["args"]]

        try:
            benchmark = Benchmark(**filtered)
        except TypeError as ex:
            print_error(f"failed initializing benchmark - {ex}")
            return None

        # Build Language
        lang_str = yaml["language"]
        lang_cls = self._get_language_class_by_str(lang_str)
        if not lang_cls:
            print_error(f"{lang_str} not available")
            return None

        all_mappings = {f.name for f in fields(lang_cls)}
        filtered = {k: v for k, v in yaml.items() if k in all_mappings}

        try:
            language = lang_cls(
                base_dir=self.base_dir,
                benchmark=benchmark,
                warmup=warmup,
                iterations=iterations,
                frequency=frequency,
                niceness=env.niceness,
                **filtered,
            )
            return language
        except TypeError as ex:
            print_error(f"failed initializing language - {ex}")
            return None
