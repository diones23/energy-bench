import time
import os

from languages import get_impl_cls
from spec import Implementation, validate_data
from setups.environments import Environment
from setups.workloads import Workload
from utils import *


class Runner:
    def __init__(
        self, base_dir: str, env: Environment, workload: Workload, timestamp: float
    ) -> None:
        self.base_dir = base_dir
        self.env = env
        self.workload = workload
        self.timestamp = timestamp

    def run_benchmark(
        self, data: dict, warmup: bool, iterations: int, sleep: int, frequency: int, niceness: int
    ) -> None:
        validated = validate_data(data)
        istr = validated["language"]
        icls = get_impl_cls(istr)

        try:
            imp = icls(
                base_dir=self.base_dir,
                warmup=warmup,
                iterations=iterations,
                frequency=frequency,
                niceness=niceness,
                **validated,
            )
        except TypeError as ex:
            raise ProgramError(f"failed while initializing benchmark - {ex}")

        try:
            # Reversed order to make building & cleaning more efficient
            # in case the env and workload are too 'heavy'
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

            imp.move_rapl(self.workload, self.env, self.timestamp)
            imp.move_perf(self.workload, self.env, self.timestamp)

            print_success("ok!")
        except KeyboardInterrupt as ex:
            raise ProgramError("manually exited")
        finally:
            remove_files_if_exist(os.path.join(imp.benchmark_path, "perf.json"))
            remove_files_if_exist(os.path.join(imp.benchmark_path, "Intel_[0-9][0-9]*.csv"))
            remove_files_if_exist(os.path.join(imp.benchmark_path, "AMD_[0-9][0-9]*.csv"))
            if sleep:
                print_info(f"sleeping for {sleep} seconds")
                time.sleep(sleep)

    def _splash_screen(
        self, spec, warmup: bool, iterations: int, sleep: int, frequency: int
    ) -> str:
        estr = self.env.__class__.__name__.lower()
        wstr = self.workload.__class__.__name__.lower()

        if estr == "environment":
            estr = "none"

        if wstr == "workload":
            wstr = "none"

        return (
            f"\033[1mbenchmark   :\033[0m {spec.name} | \033[1mlanguage:\033[0m {spec.language} | \033[1mwarmup:\033[0m {'Yes' if warmup else 'No'} | \033[1miterations:\033[0m {iterations} | \033[1mperf freq:\033[0m {frequency}ms | \033[1msleep:\033[0m {sleep}s\n"
            f"\033[1menvironment :\033[0m {estr} | \033[1mworkload:\033[0m {wstr}\n"
            f"{self.env}"
        )
