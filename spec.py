from subprocess import CalledProcessError
from dataclasses import MISSING, dataclass, field, fields
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from glob import glob
import subprocess
import shutil
import json
import os

from setups.environments import Environment
from setups.workloads import Workload
from utils import *


def validate_data(data: dict) -> dict:
    spec_map = {f.name for f in fields(Specification)}
    required_map = {
        f.name
        for f in fields(Specification)
        if f.default is MISSING and f.default_factory is MISSING
    }
    missing = [key for key in required_map if key not in data]
    if missing:
        raise ProgramError(f"benchmark missing required key(s) - {', '.join(missing)}")

    validated = {k: v for k, v in data.items() if k in spec_map}
    if "args" in validated and validated["args"]:
        validated["args"] = [str(arg) for arg in validated["args"]]

    if "stdin" in validated:
        if isinstance(validated["stdin"], str):
            validated["stdin"] = validated["stdin"].encode("utf-8")
        elif not isinstance(validated["stdin"], bytes):
            raise ProgramError("stdin must be a string or bytes")

    if "expected_stdout" in validated:
        if isinstance(validated["expected_stdout"], str):
            validated["expected_stdout"] = validated["expected_stdout"].encode("utf-8")
        elif not isinstance(validated["expected_stdout"], bytes):
            raise ProgramError("expected_stdout must be a string or bytes")

    return validated


@dataclass
class Specification(ABC):
    name: str
    language: str
    dependencies: list[str]
    target: str = ""
    source: str = ""
    rapl_usage: str = ""
    description: str = ""
    options: list[str] = field(default_factory=list)
    code: str = ""
    args: list[str] = field(default_factory=list)
    stdin: bytes = b""
    expected_stdout: bytes = b""

    # C# Specific
    packages: list[dict] = field(default_factory=list)

    # Java Specific
    class_paths: list[str] = field(default_factory=list)
    roptions: list[str] = field(default_factory=list)


@dataclass
class Implementation(Specification):
    aliases: ClassVar[list[str]] = []
    base_dir: str = ""
    warmup: bool = False
    iterations: int = 1
    frequency: int = 500
    niceness: int = 0
    commit: str = (
        "https://github.com/NixOS/nixpkgs/archive/52e3095f6d812b91b22fb7ad0bfc1ab416453634.tar.gz"
    )

    def __post_init__(self) -> None:
        if " " in self.name:
            raise ProgramError("benchmark name must not have any spaces")

        if self.iterations < 1:
            raise ProgramError("iterations can't be lower than 1")

        if self.frequency < 500:
            raise ProgramError("frequency can't be lower than 500")

        if self.niceness and not self.niceness in range(-20, 20):
            raise ProgramError("niceness must be within this range [-20, 19]")

    def __enter__(self):
        # Offload large data to disk and discard the in-memory copy.
        os.makedirs(self.benchmark_path, exist_ok=True)
        write_file(self.stdin, os.path.join(self.benchmark_path, "input"))
        write_file(self.expected_stdout, os.path.join(self.benchmark_path, "expected"))
        self.stdin = b""
        self.expected_stdout = b""
        self.build()
        return self

    def __exit__(
        self, exc_type: type | None, exc_value: Exception | None, traceback: Any | None
    ) -> bool:
        self.clean()
        return False

    def _ensure_results_dir(self, workload: Workload, env: Environment, timestamp: float) -> str:
        estr = env.__class__.__name__.lower()
        wstr = workload.__class__.__name__.lower()

        results_dir = timestamp
        if wstr == "workload":
            results_dir = f"none_{results_dir}"
        else:
            results_dir = f"{wstr}_{results_dir}"

        if estr == "environment":
            results_dir = f"none_{results_dir}"
        else:
            results_dir = f"{estr}_{results_dir}"

        warmup_dir = "warmup" if self.warmup else "no-warmup"
        istr = self.__class__.__name__
        results_dir = os.path.join(self.base_dir, results_dir, warmup_dir, istr, self.name)
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
                args=["perf", "list", "--json", "--no-desc"], check=True, capture_output=True
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
        perf_command = f"perf stat --all-cpus --append -I {self.frequency} --json --output {perf_path} -e {','.join(events)}"
        return f"{perf_command} {command}"

    def _nice_wrapper(self, command: str) -> str:
        return f"nice -n {self.niceness} {command}"

    def _nix_wrapper(self, command: str) -> list[str]:
        return (
            ["nix-shell", "--no-build-output", "--quiet", "--packages"]
            + self.dependencies
            + ["-I", f"nixpkgs={self.commit}", "--run", command]
        )

    def _wrap_command(self, command: str, measuring: bool = False) -> list[str]:
        if not self.dependencies:
            raise ProgramError("benchmark must specify at least one nix dependency")

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
        return os.path.join(self.base_dir, lang_name, self.name)

    @property
    def target_path(self) -> str:
        return os.path.join(self.benchmark_path, self.target)

    @property
    def source_path(self) -> str:
        return os.path.join(self.benchmark_path, self.source)

    def build(self) -> None:
        if not self.code:
            raise ProgramError("benchmark doesn't have any source code")

        if not self.dependencies:
            raise ProgramError("benchmark must specify at least one nix dependency")

        write_file(self.code, self.source_path)
        cmd = " ".join(self.build_command + self.options)
        wrapped = self._wrap_command(cmd)

        try:
            subprocess.run(args=wrapped, check=True, capture_output=True)
        except CalledProcessError as ex:
            raise ProgramError(
                f"returned non-zero exit status {ex.returncode} while building - {ex.stderr}"
            )

    def measure(self) -> None:
        cmd = " ".join(self.measure_command + self.args)
        wrapped = self._wrap_command(cmd, measuring=True)

        input_path = os.path.join(self.benchmark_path, "input")
        output_path = os.path.join(self.benchmark_path, "output")

        try:
            with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
                subprocess.run(
                    args=wrapped, check=True, stdout=outfile, stderr=subprocess.PIPE, stdin=infile
                )
        except CalledProcessError as ex:
            raise ProgramError(f"failed while measuring - {ex.stderr}")
        except IOError as ex:
            raise ProgramError(f"failed while performing IO on measurement - {ex}")

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
            subprocess.run(args=wrapped, check=True, capture_output=True)
        except CalledProcessError as ex:
            raise ProgramError(f"failed to clean benchmark: {ex.stderr}")
        except IOError as ex:
            raise ProgramError(f"failed to clean benchmark: {ex}")
        finally:
            remove_files_if_exist(os.path.join(self.benchmark_path, "input"))
            remove_files_if_exist(os.path.join(self.benchmark_path, "expected"))

    def move_rapl(self, workload: Workload, env: Environment, timestamp: float) -> None:
        intel_rapls = glob(os.path.join(self.benchmark_path, "Intel_[0-9][0-9]*.csv"))
        amd_rapls = glob(os.path.join(self.benchmark_path, "AMD_[0-9][0-9]*.csv"))
        rapls = intel_rapls + amd_rapls
        if not rapls:
            raise ProgramError("benchmark didn't generate a valid rapl measurement")
        if len(rapls) > 1:
            raise ProgramError("found more than one rapl measurements")

        results_dir = self._ensure_results_dir(workload, env, timestamp)
        try:
            shutil.move(rapls[0], results_dir)
        except IOError as ex:
            raise ProgramError(f"failed to move RAPL files - {ex}")

    def move_perf(self, workload: Workload, env: Environment, timestamp: float) -> None:
        perfs = glob(os.path.join(self.benchmark_path, "perf.json"))
        if not perfs:
            raise ProgramError("benchmark didn't generate a valid perf measurement")
        if len(perfs) > 1:
            raise ProgramError("found more than one perf measurements")

        results_dir = self._ensure_results_dir(workload, env, timestamp)
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
