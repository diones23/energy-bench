#!/usr/bin/env python3
import argparse
import sys
import os

from commands import *
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


def main():
    base_dir = os.path.join(os.path.expanduser("~"), ".energy-bench")
    if not os.path.exists(base_dir) or not os.path.isdir(base_dir):
        errs_or_exit("base dir does not exist. Please install first with `make install`", True)

    parser = argparse.ArgumentParser(
        prog="energy-bench", description="Measure and analyze the energy consumption of your code."
    )
    parser.add_argument("--stop", action="store_true", help="Stop after any failures")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    for name, cls in BaseCommand.registry.items():
        sub = subparsers.add_parser(name, help=cls.help)
        cmd = cls(base_dir)
        cmd.add_args(sub)
        sub.set_defaults(instance=cmd)

    args = parser.parse_args()

    try:
        args.instance.handle(args)
    except ProgramError as ex:
        errs_or_exit(str(ex), args.stop)


if __name__ == "__main__":
    main()
    if WARNINGS:
        print_warning(f"program finished with {WARNINGS} warning(s)")
