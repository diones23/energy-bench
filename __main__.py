#!/usr/bin/env python3
from yaml.parser import ParserError
import argparse
import random
import yaml
import sys
import os

from errors import ReportError
from reporter import Reporter
from runner import Runner
from environments import *
from utils import *


def is_yaml_file(file_path: str) -> bool:
    filename = os.path.basename(file_path)
    split = os.path.splitext(filename)
    if len(split) < 2:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in [".yaml", ".yml"]


def parse_input() -> set[str]:
    file_paths = set()
    if not sys.stdin.isatty():
        input_data = sys.stdin.read().strip()
        if input_data:
            file_paths = set(input_data.split())
    return file_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    measure_parser = subparsers.add_parser("measure", help="Perform measurement")
    measure_parser.add_argument(
        "-i", "--iterations", type=int, default=1, help="Number of measurement iterations"
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
        help="Seconds to sleep between each successful measurement",
    )
    measure_parser.add_argument(
        "--no-warmup", action="store_true", help="Perform measure iterations around the benchmark"
    )
    measure_parser.add_argument(
        "--warmup", action="store_true", help="Perform measure iterations inside the benchmark"
    )
    measure_parser.add_argument(
        "--stop", action="store_true", help="Stop after a failed measurement"
    )
    measure_parser.add_argument("--prod", action="store_true", help="")
    measure_parser.add_argument("--light", action="store_true", help="")
    measure_parser.add_argument("--lab", action="store_true", help="")
    measure_parser.add_argument("--workload", type=str, help="")

    report_parser = subparsers.add_parser(
        "report", help="Build different reports from raw measurements"
    )
    report_parser.add_argument(
        "-s",
        "--skip",
        type=int,
        default=0,
        help="Skips the first number of rows for each measurement",
    )
    report_parser.add_argument(
        "-c", "--compile", action="store_true", help="Produce a csv table with compiled results"
    )
    report_parser.add_argument(
        "-ar",
        "--average-rapl",
        action="store_true",
        help="Produce a csv table with averaged rapl results",
    )
    report_parser.add_argument(
        "-ap",
        "--average-perf",
        action="store_true",
        help="Produce a csv table with averaged perf results",
    )
    # report_parser.add_argument("-n", "--normalize", action="store_true", help="")
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
        help="Produces interactive html plots for each measurement",
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

    # workload here too

    runner = Runner(base_dir, env)

    warmup_modes = []
    if options.warmup:
        warmup_modes.append("warmup")
    if options.no_warmup:
        warmup_modes.append("no-warmup")
    if not warmup_modes:
        warmup_modes = ["warmup", "no-warmup"]

    random.shuffle(yaml_paths)
    random.shuffle(warmup_modes)

    for path in yaml_paths:
        if not os.path.exists(path) or not is_yaml_file(path):
            errors += 1
            print_error(f"'{path}' is not a yaml file or does not exist.")
            if options.stop:
                return errors
            continue

        print_info(f"Loading file '{path}'\n")

        try:
            with open(path) as file:
                data = yaml.safe_load(file)
        except ParserError as ex:
            errors += 1
            print_error(f"Error while parsing benchmark data from {path}:\n{ex}")
            if options.stop:
                return errors
            continue

        for mode in warmup_modes:
            status = runner.run_benchmark(
                data, mode == "warmup", options.iterations, options.frequency
            )
            if not status and options.stop:
                errors += 1
                return errors

    return errors


def report_command(base_dir: str, options: argparse.Namespace, results_path: str) -> int:
    if not os.path.exists(results_path) or not os.path.isdir(results_path):
        print_error(f"'{results_path}' is not a directory or does not exist.")
        return 1

    reporter = Reporter(base_dir, results_path, options.skip)

    try:
        if options.compile:
            result = reporter.compile_results()
        elif options.average_rapl:
            result = reporter.average_rapl_results()
        elif options.average_perf:
            result = reporter.average_perf_results()
        else:
            result = ""

        print(result)
        return 0
    except ReportError as ex:
        print_error(str(ex))

    return 1


def main() -> int:
    args = parse_args()

    base_dir = os.path.join(os.path.expanduser("~"), ".energy-bench")
    if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
        print_error("Base directory does not exist. Please install first with `make install`.")
        return 1

    file_paths = parse_input()
    if not file_paths:
        print_error("No file paths provided via standard input.")
        return 1

    if args.command == "measure":
        return measure_command(base_dir, args, list(file_paths))
    elif args.command == "report":
        if len(file_paths) > 1:
            print_error("Can only pass one results directory to the report command.")
            return 1
        return report_command(base_dir, args, list(file_paths)[0])

    return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code != 0:
        print_warning(f"Program finished with {exit_code} error(s).")
    sys.exit(exit_code)
