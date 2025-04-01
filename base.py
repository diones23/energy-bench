from dataclasses import dataclass, field
from ollama import chat, ChatResponse
from abc import ABC, abstractmethod
from typing import ClassVar
from glob import glob
import shutil
import json
import subprocess
import os

from errors import *


@dataclass
class Benchmark:
    name: str

    description: str | None = None
    options: list[str] = field(default_factory=list)
    code: str | None = None
    args: list[str] = field(default_factory=list)
    stdin: str | bytes | None = None
    expected_stdout: str | bytes | None = None


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

    # More Configurations with Defaults
    warmup: bool = False
    iterations: int = 1
    frequency: int = 500
    niceness: int | None = None

    def __str__(self) -> str:
        warmup_str = "Warmup" if self.warmup else "No-Warmup"
        lang_str = self.__class__.__name__
        return (
            f"Benchmark : [{lang_str} {self.benchmark.name}] [{warmup_str}] [{self.iterations} iters]\n"
            f"            [nice {self.niceness}] [perf {self.frequency}]\n"
        )

    def __enter__(self):
        if not os.path.exists(self.benchmark_path):
            os.makedirs(self.benchmark_path)
        self.build()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
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

    def _rapl_wrapper(self, command) -> str:
        rapl_env = " ".join(
            [
                f"LIBRARY_PATH={self.base_dir}:$(echo $NIX_LDFLAGS | sed 's/-rpath //g; s/-L//g' | tr ' ' ':'):$LIBRARY_PATH",
                f"LD_LIBRARY_PATH={self.base_dir}:$(echo $NIX_LDFLAGS | sed 's/-rpath //g; s/-L//g' | tr ' ' ':'):$LD_LIBRARY_PATH",
                f"CPATH={self.base_dir}:$(echo $NIX_CFLAGS_COMPILE | sed -e 's/-frandom-seed=[^ ]*//g' -e 's/-isystem/ /g' | tr -s ' ' | sed 's/ /:/g'):$CPATH",
                f"RAPL_ITERATIONS={self.iterations}",
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

        return captured_events

    def _perf_wrapper(self, command: str) -> str:
        events = self._get_available_perf_events()
        perf_command = (
            f"perf stat --all-cpus -I {self.frequency} --json --output perf.json -e "
            + ",".join(events)
        )
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
            raise ProgramBuildError("Benchmark must specify at least one nix dependency")

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

    # def generate_and_update_code(self, model: str, prompt: str):
    #     """
    #     Uses the LLM to generate the code and also updates the benchmark
    #     code in place.
    #     """
    #     prompt_formatted = prompt.format(
    #         language=self.name,
    #         dependencies=",".join(self.benchmark.nix_deps),
    #         description=self.benchmark.description.strip(),
    #         rapl_usage=self.rapl_usage.strip(),
    #     ).strip()

    #     response: ChatResponse = chat(
    #         model=model, messages=[{"role": "user", "content": prompt_formatted}]
    #     )
    #     code = response.message.content
    #     self.benchmark.code = code
    #     return code

    def build(self) -> None:
        if not self.benchmark.code:
            raise ProgramBuildError("Benchmark doesn't have any source code")

        with open(self.source_path, "w") as file:
            file.write(self.benchmark.code)

        cmd = " ".join(self.build_command + self.benchmark.options)
        wrapped = self._wrap_command(cmd)
        result = subprocess.run(args=wrapped, check=True, capture_output=True)

        if result.stderr:
            raise ProgramBuildError(result.stderr)

    def measure(self) -> bytes:
        cmd = " ".join(self.measure_command + self.benchmark.args)
        wrapped = self._wrap_command(cmd, measuring=True)

        if self.benchmark.stdin:
            stdin = self.benchmark.stdin
            if isinstance(stdin, str):
                stdin = stdin.encode()
            result = subprocess.run(args=wrapped, check=True, capture_output=True, input=stdin)
        else:
            result = subprocess.run(args=wrapped, check=True, capture_output=True)

        if result.stderr:
            raise ProgramMeasureError(result.stderr)
        return result.stdout

    def verify(self, stdout: bytes) -> None:
        expected = self.benchmark.expected_stdout
        if not expected:
            return

        if isinstance(expected, str):
            expected = expected.encode()

        if self.warmup:
            expected = expected * self.iterations

        if stdout != expected:
            raise ProgramVerificationError(expected, stdout)

    def clean(self) -> None:
        cmd = " ".join(self.clean_command)
        wrapped = self._wrap_command(cmd)
        result = subprocess.run(args=wrapped, check=True, capture_output=True)

        if result.stderr:
            raise ProgramCleanError(result.stderr)

    def move_rapl(self, timestamp: float) -> None:
        intel_rapls = glob("Intel_[0-9][0-9]*.csv")
        amd_rapls = glob("AMD_[0-9][0-9]*.csv")
        rapls = intel_rapls + amd_rapls
        if not rapls:
            raise ProgramMeasureError("Benchmark didn't generate a valid rapl measurement")
        if len(rapls) > 1:
            raise ProgramMeasureError("Found more than one rapl measurements")

        results_dir = self._ensure_results_dir(timestamp)
        shutil.move(rapls[0], results_dir)

    def move_perf(self, timestamp: float) -> None:
        perfs = glob("perf.json")
        if not perfs:
            raise ProgramMeasureError("Benchmark didn't generate a valid perf measurement")
        if len(perfs) > 1:
            raise ProgramMeasureError("Found more than one perf measurements")

        results_dir = self._ensure_results_dir(timestamp)
        shutil.move(perfs[0], results_dir)

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
