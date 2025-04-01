from dataclasses import fields
from subprocess import CalledProcessError
from datetime import datetime, timezone
from glob import glob
import os

from base import Benchmark, Language
from errors import ProgramError, EnvironmentError
from environments import Environment
from utils import *
import languages


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

    def __init__(self, base_dir: str, env: Environment) -> None:
        self.base_dir = base_dir
        self.env = env
        self.timestamp = datetime.now(timezone.utc).timestamp()

    def run_benchmark(self, yaml: dict, warmup: bool, iterations: int, frequency: int) -> bool:
        benchmark = self._build_benchmark(yaml)
        if not benchmark:
            return False

        language = self._build_language(yaml, benchmark, warmup, iterations, frequency)
        if not language:
            return False

        try:
            with self.env, language:
                print(self.env)
                print(language)
                if warmup:
                    stdout = language.measure()
                    language.verify(stdout)
                else:
                    for _ in range(iterations):
                        stdout = language.measure()
                        language.verify(stdout)

                language.move_rapl(self.timestamp)
                language.move_perf(self.timestamp)
        except (EnvironmentError, ProgramError, CalledProcessError, KeyboardInterrupt) as ex:
            self._remove_files_if_exist("perf.json")
            self._remove_files_if_exist("Intel_[0-9][0-9]*.csv")
            self._remove_files_if_exist("AMD_[0-9][0-9]*.csv")
            if not isinstance(ex, KeyboardInterrupt):
                print_error(str(ex))
            return False

        print_success("Ok\n")
        return True

    def _remove_files_if_exist(self, path) -> None:
        files = glob(path)
        for file in files:
            if os.path.exists(file):
                os.remove(file)

    def _build_benchmark(self, yaml: dict) -> Benchmark | None:
        required_mappings = ["language", "name"]
        missing_keys = [key for key in required_mappings if key not in yaml]
        if missing_keys:
            print_error(f"Benchmark missing required key(s): {', '.join(missing_keys)}")
            return None

        valid_bkeys = {f.name for f in fields(Benchmark)}
        filtered_bdata = {k: v for k, v in yaml.items() if k in valid_bkeys}

        if "args" in filtered_bdata and filtered_bdata["args"]:
            filtered_bdata["args"] = [str(arg) for arg in filtered_bdata["args"]]

        try:
            return Benchmark(**filtered_bdata)
        except TypeError as ex:
            print_error(f"Error building benchmark: {ex}")
            return None

    def _get_language_class_by_str(self, language_str: str) -> type[Language] | None:
        available_languages = [getattr(languages, name) for name in languages.__all__]
        for lang_cls in available_languages:
            if language_str.lower().strip() in lang_cls.aliases:
                return lang_cls
        return None

    def _build_language(
        self,
        yaml: dict,
        benchmark: Benchmark,
        warmup: bool,
        iterations: int,
        frequency: int,
    ) -> Language | None:
        lang_str = yaml["language"]
        lang_cls = self._get_language_class_by_str(lang_str)
        if not lang_cls:
            print_error(f"{lang_str} not available")
            return None

        valid_lkeys = {f.name for f in fields(lang_cls)}
        filtered_ldata = {k: v for k, v in yaml.items() if k in valid_lkeys}
        try:
            return lang_cls(
                base_dir=self.base_dir,
                benchmark=benchmark,
                warmup=warmup,
                iterations=iterations,
                frequency=frequency,
                niceness=self.env.niceness,
                **filtered_ldata,
            )
        except TypeError as ex:
            print_error(f"Error creating language object: {ex}")
            return None
