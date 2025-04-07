from glob import glob
import subprocess
import os
from datetime import datetime, timezone

from errors import ProgramError


def print_error(msg: str) -> None:
    print(f"\033[31mError:\033[0m {msg}.")


def print_success(msg: str) -> None:
    print(f"\033[32m{msg}\033[0m")


def print_info(msg: str) -> None:
    print(f"\033[34mInfo:\033[0m {msg}.")


def print_warning(msg: str) -> None:
    print(f"\033[33mWarning:\033[0m {msg}.")


def create_splash_screen(
    env, workload, language, warmup: bool, iterations: int, frequency: int, timestamp: float
) -> str:
    env_name = env.__class__.__name__
    workload_name = workload.__class__.__name__
    lang_name = language.__class__.__name__
    bench_name = language.benchmark.name

    formatted_time = datetime.fromtimestamp(timestamp, timezone.utc).strftime(
        "%d-%m-%Y %H:%M:%S UTC"
    )

    return (
        f"\033[1mENERGY-BENCH\033[0m (started {formatted_time})\n\n"
        f"\033[1mbenchmark   :\033[0m {bench_name} | \033[1mlanguage:\033[0m {lang_name} | \033[1mwarmup:\033[0m {'Yes' if warmup else 'No'} | \033[1miterations:\033[0m {iterations}\n"
        f"\033[1menvironment :\033[0m {env_name}\n"
        f"\033[1mworkload    :\033[0m {workload_name}\n{env}"
    )


def remove_files_if_exist(path) -> None:
    files = glob(path)
    for file in files:
        if os.path.exists(file):
            os.remove(file)


def is_yaml_file(file_path: str) -> bool:
    filename = os.path.basename(file_path)
    split = os.path.splitext(filename)
    if len(split) < 2:
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in [".yaml", ".yml"]


def write_file(data: str | bytes, file_path: str) -> None:
    try:
        with open(file_path, "wb") as file:
            if isinstance(data, str):
                file.write(data.encode())
            else:
                file.write(data)
    except IOError as ex:
        raise ProgramError(f"failed while writing to file - {ex}")


def write_file_sudo(data: str | bytes, file_path: str) -> None:
    if isinstance(data, str):
        data = data.encode()
    try:
        subprocess.run(
            ["sudo", "tee", file_path], input=data, check=True, stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as ex:
        raise ProgramError(f"failed while writing to file - {ex}")


def read_file(path: str) -> str:
    try:
        if os.path.exists(path):
            with open(path, "r") as file:
                return file.read().strip()
        raise ProgramError(f"file {path} doesn't exist")
    except OSError:
        raise ProgramError(f"could not read file {path}")
