#!/usr/bin/env python3
from yaml.parser import ParserError
from dotenv import load_dotenv
import argparse
import random
import yaml
import sys
import os

from commands.generator import Generator
from commands.reporter import Reporter
from commands.runner import Runner

from setups.environments import *
from setups.workloads import *
from utils import *


ERRORS: int = 0
WARNINGS: int = 0


def errs_or_exit(msg: str, stop: bool) -> None:
    global ERRORS, WARNINGS
    if stop:
        ERRORS += 1
        print_error(msg)
        sys.exit(ERRORS)
    WARNINGS += 1
    print_warning(msg)


def welcome() -> float:
    start = datetime.now(timezone.utc).timestamp()
    formatted = format_time(start)
    print(f"\033[1mWELCOME to Energy-Bench! Started\033[0m {formatted}")
    print(f"")
    return start


def goodbye(start: float) -> None:
    end = datetime.now(timezone.utc).timestamp()
    formatted = format_time(end)
    elapsed = elapsed_time(end - start)
    print(f"\033[1mEnded\033[0m {formatted} \033[1mTotal Time\033[0m {elapsed}\n")


def parse_input() -> set[str]:
    file_paths = set()
    if not sys.stdin.isatty():
        input_data = sys.stdin.read().strip()
        if input_data:
            file_paths = set(input_data.split())
    return file_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="energy-bench",
        description="Energy benchmarking tool for code",
        epilog="Note: File paths should be provided via standard input (pipe or redirect).",
    )
    # Global argument available to all commands
    parser.add_argument("--stop", action="store_true", help="Stop after any failures")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Generate Subcommand ---
    generate_parser = subparsers.add_parser(
        "generate", help="Generate benchmark code from YAML files"
    )
    generate_parser.add_argument("--ollama", nargs="+", help="", default=[])
    generate_parser.add_argument("--openai", nargs="+", help="", default=[])

    # --- Measure Subcommand ---
    measure_parser = subparsers.add_parser(
        "measure", help="Perform measurements on benchmark files provided via stdin"
    )
    measure_parser.add_argument(
        "-i", "--iterations", type=int, default=1, help="Number of measurement iterations"
    )
    measure_parser.add_argument(
        "-f",
        "--frequency",
        type=int,
        default=500,
        help="Perf measurement frequency in milliseconds",
    )
    measure_parser.add_argument(
        "-s",
        "--sleep",
        type=int,
        default=60,
        help="Seconds to sleep between each successful measurement",
    )
    measure_parser.add_argument(
        "--no-warmup", action="store_true", help="Perform measure iterations around the benchmark"
    )
    measure_parser.add_argument(
        "--warmup", action="store_true", help="Perform measure iterations inside the benchmark"
    )
    measure_parser.add_argument(
        "--prod",
        action="store_true",
        help="Enter the 'production' environment right before measuring",
    )
    measure_parser.add_argument(
        "--light",
        action="store_true",
        help="Enter the 'lightweight' environment right before measuring",
    )
    measure_parser.add_argument(
        "--lab", action="store_true", help="Enter the 'lab' environment right before measuring"
    )
    measure_parser.add_argument(
        "--workloads",
        nargs="+",
        help="Specify workload names to enter before measuring (can be combined with an environment)",
        default=[],
    )
    measure_parser.add_argument(
        "--trial", action="store_true", help="Perform trial run measurement"
    )

    # --- Report Subcommand ---
    report_parser = subparsers.add_parser(
        "report",
        help="Build reports from raw measurements in the results directory provided via stdin",
    )
    report_parser.add_argument(
        "-s", "--skip", type=int, default=0, help="Number of rows to skip for each measurement"
    )
    report_parser.add_argument(
        "-ar",
        "--average-rapl",
        action="store_true",
        help="Produce a CSV table with averaged RAPL results",
    )
    report_parser.add_argument(
        "-ap",
        "--average-perf",
        action="store_true",
        help="Produce a CSV table with averaged perf results",
    )
    report_parser.add_argument(
        "-v",
        "--violin",
        action="store_true",
        help="Produce violin and box-plots for each measurement",
    )
    report_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Produce interactive HTML plots for each measurement",
    )
    report_parser.add_argument(
        "--no-trial", action="store_true", help="Exclude trial run measurements in the report"
    )

    return parser.parse_args()


def generate_command(base_dir: str, options: argparse.Namespace, yamls: list[str]) -> None:
    load_dotenv()

    data = []
    for model in options.ollama:
        data.append({"ollama_model": model})
    for model in options.openai:
        data.append({"openai_model": model})

    if not data:
        errs_or_exit("need to receive at least one model", True)

    existing_yamls = filter_existing_yamls(yamls)
    for path in yamls:
        if path not in existing_yamls:
            errs_or_exit(f"'{path}' is not a yaml file or does not exist", options.stop)

    for path in existing_yamls:
        print_info(f"loading spec file '{path}'")

        try:
            with open(path) as file:
                data = yaml.safe_load(file)
        except ParserError as ex:
            errs_or_exit(f"failed while parsing benchmark data using {path} - {ex}", options.stop)
        else:
            try:
                generator = Generator(base_dir)

                for model in options.ollama:
                    generator.generate_code(data, ollama_model=model)
                for model in options.openai:
                    generator.generate_code(data, openai_model=model)
            except ProgramError as ex:
                errs_or_exit(str(ex), options.stop)


def measure_command(base_dir: str, options: argparse.Namespace, yamls: list[str]):
    start = welcome()

    niceness = 0
    if options.lab:
        env = Lab()
        niceness = -20
    elif options.light:
        env = Lightweight()
    elif options.prod:
        env = Production()
    else:
        env = Environment()

    workloads = [Workload()]
    workload_strs = {wstr.lower() for wstr in options.workloads}

    for wstr in workload_strs:
        wexists = False
        for cls in all_subclasses(Workload):
            if wstr == cls.__name__.lower():
                workloads.append(cls())
                wexists = True
        if not wexists:
            errs_or_exit(f"'{wstr}' is not a known workload", options.stop)

    warmup_modes = []
    if options.warmup:
        warmup_modes.append("warmup")
    if options.no_warmup:
        warmup_modes.append("no-warmup")
    if not warmup_modes:
        warmup_modes = ["warmup", "no-warmup"]

    if options.trial:
        trial_path = os.path.join(base_dir, "trial-run.yml")
        existing_yamls = [trial_path] + yamls

    existing_yamls = filter_existing_yamls(yamls)
    for path in yamls:
        if path not in existing_yamls:
            errs_or_exit(f"'{path}' is not a yaml file or does not exist", options.stop)

    random.shuffle(existing_yamls)
    random.shuffle(warmup_modes)
    random.shuffle(workloads)

    for path in existing_yamls:
        print_info(f"loading file '{path}'")

        try:
            with open(path) as file:
                data = yaml.safe_load(file)
        except ParserError as ex:
            errs_or_exit(f"failed while parsing benchmark data using {path} - {ex}", options.stop)
            continue

        for workload in workloads:
            runner = Runner(base_dir, env, workload, start)
            for mode in warmup_modes:
                try:
                    runner.run_benchmark(
                        data,
                        mode == "warmup",
                        options.iterations,
                        options.sleep,
                        options.frequency,
                        niceness,
                    )
                except ProgramError as ex:
                    errs_or_exit(str(ex), options.stop)
    goodbye(start)


def report_command(base_dir: str, options: argparse.Namespace, results_path: str):
    if not os.path.exists(results_path) or not os.path.isdir(results_path):
        errs_or_exit(f"'{results_path}' is not a directory or does not exist", True)

    reporter = Reporter(base_dir, results_path, options.no_trial, options.skip)

    try:
        if options.average_rapl:
            result = reporter.average_rapl()
        elif options.average_perf:
            result = reporter.average_perf()
        elif options.interactive:
            result = reporter.interactive()
        else:
            result = reporter.compile_rapl()

        print(result)
    except ProgramError as ex:
        errs_or_exit(str(ex), True)


def main():
    args = parse_args()

    base_dir = os.path.join(os.path.expanduser("~"), ".energy-bench")
    if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
        errs_or_exit(
            "base directory does not exist. Please install first with `make install`", True
        )

    file_paths = parse_input()
    if not file_paths:
        errs_or_exit("no file paths provided via standard input", True)

    if args.command == "measure":
        measure_command(base_dir, args, list(file_paths))
    elif args.command == "generate":
        generate_command(base_dir, args, list(file_paths))
    elif args.command == "report":
        if len(file_paths) > 1:
            errs_or_exit("can only pass one results directory to the report command", True)
        return report_command(base_dir, args, list(file_paths)[0])


if __name__ == "__main__":
    main()
    if WARNINGS:
        print_warning(f"program finished with {WARNINGS} warning(s)")
