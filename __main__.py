#!/usr/bin/env python3
from yaml.parser import ParserError
import argparse
import random
import yaml
import sys
import os

from reporter import Reporter
from runner import Runner
from environments import *
from workloads import *
from utils import *


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
    subparsers = parser.add_subparsers(dest="command", required=True)

    measure_parser = subparsers.add_parser(
        "measure", help="perform measurement on benchmark files provided via stdin"
    )
    measure_parser.add_argument(
        "-i", "--iterations", type=int, default=1, help="number of measurement iterations"
    )
    measure_parser.add_argument(
        "-f",
        "--frequency",
        type=int,
        default=500,
        help="`perf` measurement frequency in milliseconds",
    )
    measure_parser.add_argument(
        "-s",
        "--sleep",
        type=int,
        default=60,
        help="seconds to sleep between each successful measurement",
    )
    measure_parser.add_argument(
        "--no-warmup", action="store_true", help="perform measure iterations around the benchmark"
    )
    measure_parser.add_argument(
        "--warmup", action="store_true", help="perform measure iterations inside the benchmark"
    )
    measure_parser.add_argument("--stop", action="store_true", help="stop after any failures")
    measure_parser.add_argument(
        "--prod",
        action="store_true",
        help="enter the 'production' environment right before measuring",
    )
    measure_parser.add_argument(
        "--light",
        action="store_true",
        help="enter the 'lightweight' environment right before measuring",
    )
    measure_parser.add_argument(
        "--lab", action="store_true", help="enter the 'lab' environment right before measuring"
    )
    measure_parser.add_argument(
        "--workloads",
        nargs="+",
        help="enter each specified workloads before measuring. Can be combined with an environment",
    )
    measure_parser.add_argument("--trial", action="store_true", help="")

    report_parser = subparsers.add_parser(
        "report",
        help="build different reports from raw measurements in the results directory provided via stdin",
    )
    report_parser.add_argument(
        "-s",
        "--skip",
        type=int,
        default=0,
        help="skips the first number of rows for each measurement",
    )
    report_parser.add_argument(
        "-ar",
        "--average-rapl",
        action="store_true",
        help="produce a csv table with averaged rapl results",
    )
    report_parser.add_argument(
        "-ap",
        "--average-perf",
        action="store_true",
        help="produce a csv table with averaged perf results",
    )
    # report_parser.add_argument("-n", "--normalize", action="store_true", help="")
    report_parser.add_argument(
        "-v",
        "--violin",
        action="store_true",
        help="produce violin and box-plots for each measurement",
    )
    report_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="produces interactive html plots for each measurement",
    )
    report_parser.add_argument("--no-trial", action="store_true", help="")

    return parser.parse_args()


def measure_command(
    base_dir: str, options: argparse.Namespace, yaml_paths: list[str]
) -> tuple[int, int]:
    start = datetime.now(timezone.utc).timestamp()
    formatted = format_time(start)
    print(f"\033[1mWELCOME to Energy-Bench! Started\033[0m {formatted}")
    print(f"")

    errors = 0
    warnings = 0
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
    workload_strs = set()
    if options.workloads:
        workload_strs: set[str] = set(options.workloads)
        workload_strs = {wstr.lower() for wstr in workload_strs}

    for wstr in workload_strs:
        wexists = False
        for cls in all_subclasses(Workload):
            if wstr == cls.__name__.lower():
                workloads.append(cls())
                wexists = True
        if not wexists:
            print_warning(f"'{wstr}' is not a known workload")

    warmup_modes = []
    if options.warmup:
        warmup_modes.append("warmup")
    if options.no_warmup:
        warmup_modes.append("no-warmup")
    if not warmup_modes:
        warmup_modes = ["warmup", "no-warmup"]

    existing_yaml_paths = []
    for path in yaml_paths:
        if not os.path.exists(path) or not is_yaml_file(path):
            msg = f"'{path}' is not a yaml file or does not exist"
            if options.stop:
                errors += 1
                print_error(msg)
                return errors, warnings
            warnings += 1
            print_warning(msg)
        else:
            existing_yaml_paths.append(path)

    random.shuffle(existing_yaml_paths)
    random.shuffle(warmup_modes)
    random.shuffle(workloads)

    if options.trial:
        trial_path = os.path.join(base_dir, "trial-run.yml")
        existing_yaml_paths = [trial_path] + existing_yaml_paths

    for path in existing_yaml_paths:
        print_info(f"loading file '{path}'")

        try:
            with open(path) as file:
                data = yaml.safe_load(file)
        except ParserError as ex:
            msg = f"error while parsing benchmark data from {path} - {ex}"
            if options.stop:
                errors += 1
                print_error(msg)
                return errors, warnings
            warnings += 1
            print_warning(msg)
            continue

        for workload in workloads:
            runner = Runner(base_dir, env, workload, start)
            for mode in warmup_modes:
                mode = mode == "warmup"
                status = runner.run_benchmark(
                    data, mode, options.iterations, options.sleep, options.frequency, niceness
                )
                if not status:
                    if options.stop:
                        errors += 1
                        return errors, warnings
                    warnings += 1

    end = datetime.now(timezone.utc).timestamp()
    formatted = format_time(end)
    elapsed = elapsed_time(end - start)
    print(f"\033[1mEnded\033[0m {formatted} \033[1mTotal Time\033[0m {elapsed}\n")
    return errors, warnings


def report_command(
    base_dir: str, options: argparse.Namespace, results_path: str
) -> tuple[int, int]:
    if not os.path.exists(results_path) or not os.path.isdir(results_path):
        print_error(f"'{results_path}' is not a directory or does not exist")
        return (1, 0)

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
        print_error(str(ex))
        return (1, 0)

    return (0, 0)


def main() -> tuple[int, int]:
    args = parse_args()

    base_dir = os.path.join(os.path.expanduser("~"), ".energy-bench")
    if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
        print_error("base directory does not exist. Please install first with `make install`")
        return (1, 0)

    file_paths = parse_input()
    if not file_paths:
        print_error("no file paths provided via standard input")
        return (1, 0)

    if args.command == "measure":
        return measure_command(base_dir, args, list(file_paths))
    elif args.command == "report":
        if len(file_paths) > 1:
            print_error("can only pass one results directory to the report command")
            return (1, 0)
        return report_command(base_dir, args, list(file_paths)[0])

    return (0, 0)


if __name__ == "__main__":
    errors, warnings = main()
    if errors or warnings:
        print_warning(f"program finished with {errors} error(s) and {warnings} warning(s)")
    sys.exit(errors)
