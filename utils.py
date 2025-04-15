from datetime import datetime, timezone
from glob import glob
import subprocess
import os


class ProgramError(Exception):
    pass


def print_error(msg: str) -> None:
    print(f"\033[31mError:\033[0m {msg}.\n")


def print_success(msg: str) -> None:
    print(f"\033[32m{msg}\033[0m\n")


def print_info(msg: str) -> None:
    print(f"\033[34mInfo:\033[0m {msg}.\n")


def print_warning(msg: str) -> None:
    print(f"\033[33mWarning:\033[0m {msg}.\n")


def remove_files_if_exist(path) -> None:
    files = glob(path)
    for file in files:
        if os.path.exists(file):
            os.remove(file)


def all_subclasses(cls):
    return cls.__subclasses__() + [g for s in cls.__subclasses__() for g in all_subclasses(s)]


def format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC")


def elapsed_time(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}"


def filter_existing_yamls(yaml_paths: list[str]) -> list[str]:
    existing_paths = []
    for path in yaml_paths:
        if os.path.exists(path) and is_yaml_file(path):
            existing_paths.append(path)
    return existing_paths


def is_yaml_file(path: str) -> bool:
    filename = os.path.basename(path)
    split = os.path.splitext(filename)
    if len(split) < 2:
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in [".yaml", ".yml"]


def write_file(data: str | bytes, path: str) -> None:
    try:
        with open(path, "wb") as file:
            if isinstance(data, str):
                file.write(data.encode())
            else:
                file.write(data)
    except IOError as ex:
        raise ProgramError(f"failed while writing to file - {ex}")


def write_file_sudo(data: str | bytes, path: str) -> None:
    if isinstance(data, str):
        data = data.encode()
    try:
        subprocess.run(["sudo", "tee", path], input=data, check=True, stdout=subprocess.DEVNULL)
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


def ensure_dir_exists(path: str) -> None:
    if os.path.isdir(path) and not os.path.exists(path):
        os.makedirs(path)
