from abc import ABC, abstractmethod
import argparse


class BaseCommand(ABC):
    registry = {}
    name: str | None = None
    help: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.name = cls.name or cls.__name__.lower()
        BaseCommand.registry[cls.name] = cls

    def __init__(self, base_dir) -> None:
        self.base_dir = base_dir

    @abstractmethod
    def add_args(self, parser: argparse.ArgumentParser) -> None:
        ...

    @abstractmethod
    def handle(self, args: argparse.Namespace) -> None:
        ...
