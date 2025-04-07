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
        "-i",
        "--iterations",
        type=int,
        default=1,
        help="number of measurement iterations",
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
        "--no-warmup",
        action="store_true",
        help="perform measure iterations around the benchmark",
    )
    measure_parser.add_argument(
        "--warmup",
        action="store_true",
        help="perform measure iterations inside the benchmark",
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
        "--lab",
        action="store_true",
        help="enter the 'lab' environment right before measuring",
    )
    measure_parser.add_argument(
        "--workloads",
        nargs="+",
        help="enter each specified workloads before measuring. Can be combined with an environment",
    )
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

    return parser.parse_args()


def measure_command(base_dir: str, options: argparse.Namespace, yaml_paths: list[str]) -> int:
    errors = 0

    if options.lab:
        env = Lab()
    elif options.light:
        env = Lightweight()
    elif options.prod:
        env = Production()
    else:
        env = Environment()

    workloads = ["workload"]
    if options.workloads:
        workloads = options.workloads

    warmup_modes = []
    if options.warmup:
        warmup_modes.append("warmup")
    if options.no_warmup:
        warmup_modes.append("no-warmup")
    if not warmup_modes:
        warmup_modes = ["warmup", "no-warmup"]

    random.shuffle(yaml_paths)
    random.shuffle(warmup_modes)
    random.shuffle(workloads)

    runner = Runner(base_dir)

    for path in yaml_paths:
        if not os.path.exists(path) or not is_yaml_file(path):
            errors += 1
            print_error(f"'{path}' is not a yaml file or does not exist")
            if options.stop:
                return errors
            continue

        print_info(f"loading file '{path}'")
        print("")

        try:
            with open(path) as file:
                data = yaml.safe_load(file)
        except ParserError as ex:
            errors += 1
            print_error(f"error while parsing benchmark data from {path} - {ex}")
            if options.stop:
                return errors
            continue

        for workload in workloads:
            for mode in warmup_modes:
                status = runner.run_benchmark(
                    data,
                    env,
                    workload,
                    mode == "warmup",
                    options.iterations,
                    options.frequency,
                )
                if not status:
                    errors += 1
                if options.stop:
                    return errors

    return errors


def report_command(base_dir: str, options: argparse.Namespace, results_path: str) -> int:
    if not os.path.exists(results_path) or not os.path.isdir(results_path):
        print_error(f"'{results_path}' is not a directory or does not exist")
        return 1

    reporter = Reporter(base_dir, results_path, options.skip)

    try:
        if options.average_rapl:
            result = reporter.average_rapl_results()
        elif options.average_perf:
            result = reporter.average_perf_results()
        else:
            result = reporter.compile_results()

        print(result)
        return 0
    except ProgramError as ex:
        print_error(str(ex))

    return 1


def main() -> int:
    args = parse_args()

    base_dir = os.path.join(os.path.expanduser("~"), ".energy-bench")
    if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
        print_error("base directory does not exist. Please install first with `make install`")
        return 1

    file_paths = parse_input()
    if not file_paths:
        print_error("no file paths provided via standard input")
        return 1

    if args.command == "measure":
        return measure_command(base_dir, args, list(file_paths))
    elif args.command == "report":
        if len(file_paths) > 1:
            print_error("can only pass one results directory to the report command")
            return 1
        return report_command(base_dir, args, list(file_paths)[0])

    return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code != 0:
        print_warning(f"program finished with {exit_code} error(s)")
    sys.exit(exit_code)
