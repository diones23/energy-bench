from glob import glob
from io import BufferedReader
import os

from errors import ProgramError


def print_error(msg: str) -> None:
    print(f"\033[31mError:\033[0m {msg}")


def print_success(msg: str) -> None:
    print(f"\033[32m{msg}\033[0m")


def print_info(msg: str) -> None:
    print(f"\033[34mInfo:\033[0m {msg}")


def print_warning(msg: str) -> None:
    print(f"\033[33mWarning:\033[0m {msg}")


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
        raise ProgramError(f"Failed to store data: {ex}")
