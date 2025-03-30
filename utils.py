def print_error(msg: str) -> None:
    print(f"\033[31mError:\033[0m {msg}")


def print_success(msg: str) -> None:
    print(f"\033[32m{msg}\033[0m")


def print_info(msg: str) -> None:
    print(f"\033[34mInfo:\033[0m {msg}")


def print_warning(msg: str) -> None:
    print(f"\033[33mWarning:\033[0m {msg}")
