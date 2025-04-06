from dataclasses import dataclass, field
from ollama import chat, ChatResponse
from abc import ABC, abstractmethod
from subprocess import CalledProcessError
from typing import ClassVar, Any
from glob import glob
import shutil
import json
import subprocess
import os

from errors import *
from utils import *


@dataclass
class Benchmark:
    """
    Represents a benchmark with its configuration and expected outputs.
    """

    name: str
    description: str | None = None
    options: list[str] = field(default_factory=list)
    code: str | None = None
    args: list[str] = field(default_factory=list)
    stdin: str | bytes = ""
    expected_stdout: str | bytes = ""


@dataclass
class Language(ABC):
    """
    Generic data class responsible for building, measuring and cleaning
    benchmarks implemented in a specific language.
    """

    # Base Dependencies
    base_dir: str
    benchmark: Benchmark

    # Language Specifics
    aliases: ClassVar[list[str]]
    target: str
    source: str

    # Nix Environment
    nix_deps: list[str] = field(default_factory=list)
    nix_commit: str = (
        "https://github.com/NixOS/nixpkgs/archive/52e3095f6d812b91b22fb7ad0bfc1ab416453634.tar.gz"
    )

    # RAPL Interface
    rapl_usage: str = ""

    # Configuration with Defaults
    warmup: bool = False
    iterations: int = 1
    frequency: int = 500
    niceness: int | None = None

    def __post_init__(self):
        if self.iterations < 1:
            raise ProgramError("Iterations can't be lower than 1")

        if not os.path.exists(self.benchmark_path):
            os.makedirs(self.benchmark_path)

        # Offload large data to disk and discard the in-memory copy.
        write_file(self.benchmark.stdin, os.path.join(self.benchmark_path, "input"))
        write_file(self.benchmark.expected_stdout, os.path.join(self.benchmark_path, "expected"))
        self.benchmark.stdin = ""
        self.benchmark.expected_stdout = ""

    def __str__(self) -> str:
        warmup_str = "warmup" if self.warmup else "no-warmup"
        lang_str = self.__class__.__name__
        return (
            f"Benchmark : [{lang_str} {self.benchmark.name}] [{warmup_str}] [{self.iterations} iters]\n"
            f"            [nice {self.niceness}] [perf {self.frequency}/s]\n"
        )

    def __enter__(self):
        self.build()
        return self

    def __exit__(
        self, exc_type: type | None, exc_value: Exception | None, traceback: Any | None
    ) -> bool:
        self.clean()
        return False

    def _ensure_results_dir(self, timestamp: float) -> str:
        warmup_dir = "warmup" if self.warmup else "no-warmup"
        results_dir = f"results_{timestamp}"
        language_name = self.__class__.__name__
        results_dir = os.path.join(
            self.base_dir, results_dir, warmup_dir, language_name, self.benchmark.name
        )
        os.makedirs(results_dir, exist_ok=True)
        return results_dir

    def _rapl_wrapper(self, command: str) -> str:
        rapl_env = " ".join(
            [
                f"LIBRARY_PATH={self.base_dir}:$(echo $NIX_LDFLAGS | sed 's/-rpath //g; s/-L//g' | tr ' ' ':'):$LIBRARY_PATH",
                f"LD_LIBRARY_PATH={self.base_dir}:$(echo $NIX_LDFLAGS | sed 's/-rpath //g; s/-L//g' | tr ' ' ':'):$LD_LIBRARY_PATH",
                f"CPATH={self.base_dir}:$(echo $NIX_CFLAGS_COMPILE | sed -e 's/-frandom-seed=[^ ]*//g' -e 's/-isystem/ /g' | tr -s ' ' | sed 's/ /:/g'):$CPATH",
                f"RAPL_ITERATIONS={self.iterations if self.warmup else 1}",
                f"RAPL_OUTPUT={self.benchmark_path}",
            ]
        )
        return f"{rapl_env} {command}"

    def _get_available_perf_events(self) -> list[str]:
        requested_events = [
            "cache-misses",
            "branch-misses",
            "LLC-loads-misses",
            "msr/cpu_thermal_margin/",
            "cpu-clock",
            "cycles",
            "cstate_core/c3-residency/",
            "cstate_core/c6-residency/",
            "cstate_core/c7-residency/",
        ]
        captured_events = []

        try:
            result = subprocess.run(
                args=["perf", "list", "--json", "--no-desc"],
                check=True,
                capture_output=True,
            )
            available_events = iter(json.loads(result.stdout))

            while captured_events != requested_events:
                available_event = next(available_events, None)
                if not available_event:
                    break
                available_event_name = available_event.get("EventName")
                if available_event_name in requested_events:
                    captured_events.append(available_event_name)

            if not captured_events:
                return ["cpu-clock", "cycles"]

            return captured_events
        except (subprocess.SubprocessError, json.JSONDecodeError):
            return ["cpu-clock", "cycles"]

    def _perf_wrapper(self, command: str) -> str:
        events = self._get_available_perf_events()
        perf_path = os.path.join(self.benchmark_path, "perf.json")
        perf_command = f"perf stat --all-cpus -I {self.frequency} --json --output {perf_path} -e {','.join(events)}"
        return f"{perf_command} {command}"

    def _nice_wrapper(self, command: str) -> str:
        if self.niceness:
            return f"nice -n {self.niceness} {command}"
        return command

    def _nix_wrapper(self, command: str) -> list[str]:
        return (
            ["nix-shell", "--no-build-output", "--quiet", "--packages"]
            + self.nix_deps
            + ["-I", f"nixpkgs={self.nix_commit}", "--run", command]
        )

    def _wrap_command(self, command: str, measuring: bool = False) -> list[str]:
        if not self.nix_deps:
            raise ProgramError("Benchmark must specify at least one nix dependency")

        if measuring:
            command = self._perf_wrapper(command)
            command = self._nice_wrapper(command)
            command = self._rapl_wrapper(command)
            command = f"sudo -E {command}"  # Measuring requires sudo because of rapl and perf
        else:
            command = self._rapl_wrapper(command)

        return self._nix_wrapper(command)

    @property
    def benchmark_path(self) -> str:
        lang_name = self.__class__.__name__
        return os.path.join(self.base_dir, lang_name, self.benchmark.name)

    @property
    def target_path(self) -> str:
        return os.path.join(self.benchmark_path, self.target)

    @property
    def source_path(self) -> str:
        return os.path.join(self.benchmark_path, self.source)

    def build(self) -> None:
        if not self.benchmark.code:
            raise ProgramError("Benchmark doesn't have any source code")

        if not self.nix_deps:
            raise ProgramError("Benchmark must specify at least one nix dependency")

        write_file(self.benchmark.code, self.source_path)
        cmd = " ".join(self.build_command + self.benchmark.options)
        wrapped = self._wrap_command(cmd)

        try:
            result = subprocess.run(args=wrapped, check=True, capture_output=True)
        except CalledProcessError as ex:
            raise ProgramError(f"failed while building - {ex}")

        if result.stderr:
            raise ProgramError(result.stderr.decode())

    def measure(self) -> None:
        cmd = " ".join(self.measure_command + self.benchmark.args)
        wrapped = self._wrap_command(cmd, measuring=True)

        input_path = os.path.join(self.benchmark_path, "input")
        output_path = os.path.join(self.benchmark_path, "output")

        try:
            with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
                result = subprocess.run(
                    args=wrapped, check=True, stdout=outfile, stderr=subprocess.PIPE, stdin=infile
                )
        except IOError as ex:
            raise ProgramError(f"failed while performing IO on measurement - {ex}")

        if result.stderr:
            raise ProgramError(result.stderr.decode())

    def verify(self, iterations: int) -> None:
        expected_path = os.path.join(self.benchmark_path, "expected")
        output_path = os.path.join(self.benchmark_path, "output")

        try:
            with open(expected_path, "rb") as expfile, open(output_path, "rb") as outfile:
                expected = expfile.read()

                for i in range(iterations):
                    chunk = outfile.read(len(expected))
                    if len(chunk) != len(expected):
                        raise ProgramError(
                            f"iteration {i + 1} didn't match expected stdout - lengths not matching"
                        )
                    if chunk != expected:
                        raise ProgramError(
                            f"iteration {i + 1} didn't match expected stdout - unequal"
                        )

                remaining = outfile.read(1)
                if remaining:
                    raise ProgramError(f"benchmark has more output than expected")
        except IOError as ex:
            raise ProgramError(f"failed to verify - {ex}")

    def clean(self) -> None:
        try:
            cmd = " ".join(self.clean_command)
            wrapped = self._wrap_command(cmd)
            result = subprocess.run(args=wrapped, check=True, capture_output=True)

            remove_files_if_exist(os.path.join(self.benchmark_path, "input"))
            remove_files_if_exist(os.path.join(self.benchmark_path, "expected"))

            if result.stderr:
                raise ProgramError(result.stderr.decode())
        except IOError as ex:
            raise ProgramError(f"failed to clean benchmark: {ex}")

    def move_rapl(self, timestamp: float) -> None:
        intel_rapls = glob(os.path.join(self.benchmark_path, "Intel_[0-9][0-9]*.csv"))
        amd_rapls = glob(os.path.join(self.benchmark_path, "AMD_[0-9][0-9]*.csv"))
        rapls = intel_rapls + amd_rapls
        if not rapls:
            raise ProgramError("benchmark didn't generate a valid rapl measurement")
        if len(rapls) > 1:
            raise ProgramError("found more than one rapl measurements")

        results_dir = self._ensure_results_dir(timestamp)
        try:
            shutil.move(rapls[0], results_dir)
        except IOError as ex:
            raise ProgramError(f"failed to move RAPL files - {ex}")

    def move_perf(self, timestamp: float) -> None:
        perfs = glob(os.path.join(self.benchmark_path, "perf.json"))
        if not perfs:
            raise ProgramError("benchmark didn't generate a valid perf measurement")
        if len(perfs) > 1:
            raise ProgramError("found more than one perf measurements")

        results_dir = self._ensure_results_dir(timestamp)
        try:
            shutil.move(perfs[0], results_dir)
        except IOError as ex:
            raise ProgramError(f"failed to move perf files - {ex}")

    @property
    @abstractmethod
    def build_command(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def measure_command(self) -> list[str]:
        raise NotImplementedError

    @property
    @abstractmethod
    def clean_command(self) -> list[str]:
        raise NotImplementedError
