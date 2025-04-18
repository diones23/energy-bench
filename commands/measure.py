import argparse
import random
import sys
import time
import os

import yaml
from yaml.parser import ParserError

from . import BaseCommand
from languages import get_impl_cls
from spec import Implementation, validate_data
from setups.workloads import Workload
from setups.environments import *
from utils import *


class MeasureCommand(BaseCommand):
    name = "measure"
    help = "Perform measurements on benchmark files"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-i", "--iterations", type=int, default=1, help="Number of measurement iterations"
        )
        parser.add_argument(
            "-f",
            "--frequency",
            type=int,
            default=500,
            help="Perf measurement frequency in milliseconds",
        )
        parser.add_argument(
            "-s",
            "--sleep",
            type=int,
            default=60,
            help="Seconds to sleep between each successful measurement",
        )
        parser.add_argument(
            "--no-warmup",
            action="store_true",
            help="Perform measure iterations around the benchmark",
        )
        parser.add_argument(
            "--warmup", action="store_true", help="Perform measure iterations inside the benchmark"
        )
        parser.add_argument(
            "--prod",
            action="store_true",
            help="Enter the 'production' environment right before measuring",
        )
        parser.add_argument(
            "--light",
            action="store_true",
            help="Enter the 'lightweight' environment right before measuring",
        )
        parser.add_argument(
            "--lab", action="store_true", help="Enter the 'lab' environment right before measuring"
        )
        parser.add_argument(
            "--workloads",
            nargs="*",
            help="Specify workload names to enter before measuring (can be combined with an environment)",
            default=[],
        )
        parser.add_argument("--trial", action="store_true", help="Perform trial run measurement")
        parser.add_argument(
            "files", nargs="+", type=argparse.FileType("r"), default=[sys.stdin], help=""
        )

    def handle(self, args: argparse.Namespace) -> None:
        timestamp = self.welcome()

        if args.lab:
            env = Lab()
        elif args.light:
            env = Lightweight()
        elif args.prod:
            env = Production()
        else:
            env = Environment()

        workloads = [Workload()]
        workload_strs = {wstr.lower() for wstr in args.workloads}

        for wstr in workload_strs:
            wexists = False
            for cls in all_subclasses(Workload):
                if wstr == cls.__name__.lower():
                    workloads.append(cls())
                    wexists = True
            if not wexists:
                raise ProgramError(f"'{wstr}' is not a known workload")

        warmup_modes = []
        if args.warmup:
            warmup_modes.append("warmup")
        if args.no_warmup:
            warmup_modes.append("no-warmup")
        if not warmup_modes:
            warmup_modes = ["warmup", "no-warmup"]

        files = args.files
        if args.trial:
            trial_path = os.path.join(self.base_dir, "trial-run.yml")
            files = [trial_path] + files

        random.shuffle(files)
        random.shuffle(warmup_modes)
        random.shuffle(workloads)

        for file in files:
            name = getattr(file, "name", "<stdin>")
            print_info(f"loading benchmark file '{name}'")

            try:
                data = yaml.safe_load(file)
            except ParserError as ex:
                raise ProgramError(f"failed while parsing benchmark data using {file} - {ex}")
            finally:
                if file is not sys.stdin:
                    file.close()

            validated = validate_data(data)
            istr = validated["language"]
            icls = get_impl_cls(istr)

            for work in workloads:
                for mode in warmup_modes:
                    is_warmup = mode == "warmup"

                    try:
                        imp = icls(
                            base_dir=self.base_dir,
                            warmup=is_warmup,
                            iterations=args.iterations,
                            frequency=args.frequency,
                            niceness=-20 if args.lab else 0,
                            **validated,
                        )
                    except TypeError as ex:
                        raise ProgramError(f"failed while initializing benchmark - {ex}")

                    try:
                        # Reversed order to make building & cleaning more efficient
                        # in case the env and workload are too 'heavy'
                        with imp, work, env:
                            splash = self.splash(imp, env, work, args.sleep)
                            print(splash)

                            if is_warmup:
                                imp.measure()
                                imp.verify(args.iterations)
                            else:
                                for _ in range(args.iterations):
                                    imp.measure()
                                    imp.verify(1)

                        imp.move_rapl(work, env, timestamp)
                        imp.move_perf(work, env, timestamp)

                        print_success("ok!")
                    except KeyboardInterrupt as ex:
                        raise ProgramError("manually exited")
                    finally:
                        remove_files_if_exist(os.path.join(imp.benchmark_path, "perf.json"))
                        remove_files_if_exist(
                            os.path.join(imp.benchmark_path, "Intel_[0-9][0-9]*.csv")
                        )
                        remove_files_if_exist(
                            os.path.join(imp.benchmark_path, "AMD_[0-9][0-9]*.csv")
                        )
                        if args.sleep:
                            print_info(f"sleeping for {args.sleep} seconds")
                            time.sleep(args.sleep)
        self.goodbye(timestamp)

    def welcome(self) -> float:
        start = datetime.now(timezone.utc).timestamp()
        formatted = format_time(start)
        print(f"\033[1mWELCOME to Energy-Bench! Started\033[0m {formatted}\n")
        return start

    def goodbye(self, start: float) -> None:
        end = datetime.now(timezone.utc).timestamp()
        formatted = format_time(end)
        elapsed = elapsed_time(end - start)
        print(f"\033[1mEnded\033[0m {formatted} \033[1mTotal Time\033[0m {elapsed}\n")

    def splash(self, impl: Implementation, env: Environment, work: Workload, sleep: int) -> str:
        estr = env.__class__.__name__.lower()
        wstr = work.__class__.__name__.lower()

        if estr == "environment":
            estr = "none"

        if wstr == "workload":
            wstr = "none"

        return (
            f"\033[1mbenchmark   :\033[0m {impl.name} | \033[1mlanguage:\033[0m {impl.language} | \033[1mwarmup:\033[0m {'Yes' if impl.warmup else 'No'} | "
            f"\033[1miterations:\033[0m {impl.iterations} | \033[1mperf freq:\033[0m {impl.frequency}ms | \033[1msleep:\033[0m {sleep}s\n"
            f"\033[1menvironment :\033[0m {estr} | \033[1mworkload:\033[0m {wstr}\n"
            f"{env}"
        )
