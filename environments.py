from dataclasses import dataclass
from typing import Any
import os

from errors import ProgramError
from utils import write_file_sudo, read_file

class Cpu:
    def __init__(self, value: int) -> None:
        self.cpu_path = f"/sys/devices/system/cpu/cpu{value}"
        if os.path.isdir(self.cpu_path):
            self.value = value
        else:
            raise ProgramError(f"Cpu {value} doesn't exist.")

    @property
    def enabled(self) -> bool:
        path = f"{self.cpu_path}/online"
        if os.path.exists(path):
            with open(path, "r") as file:
                value = file.read().strip()
                return value == "1"
        return True

    @enabled.setter
    def enabled(self, value: bool) -> None:
        path = f"{self.cpu_path}/online"
        if self.value != 0:
            write_file_sudo("1" if value else "0", path)

    @property
    def hyperthread(self) -> bool:
        path = f"{self.cpu_path}/topology/thread_siblings_list"

        try:
            siblings_str = read_file(path)
        except ProgramError:
            return False

        siblings = []
        for part in siblings_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-")
                siblings.extend([str(i) for i in range(int(start), int(end) + 1)])
            elif part:
                siblings.append(part)

        siblings = sorted(siblings, key=int)
        if len(siblings) < 2:
            return False

        return str(self.value) in siblings[1:]

    @property
    def governor(self) -> str:
        path = f"{self.cpu_path}/cpufreq/scaling_governor"
        return read_file(path)

    @governor.setter
    def governor(self, value: str) -> None:
        path = f"{self.cpu_path}/cpufreq/scaling_governor"
        if value not in self.available_governors:
            raise ProgramError(f"governor '{value}' not available on CPU {self.value}.")
        write_file_sudo(value, path)

    @property
    def available_governors(self) -> list[str]:
        path = f"{self.cpu_path}/cpufreq/scaling_available_governors"
        return read_file(path).split()

    @property
    def min_hw_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/cpuinfo_min_freq"
        return int(read_file(path))

    @property
    def max_hw_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/cpuinfo_max_freq"
        return int(read_file(path))

    @property
    def min_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/scaling_min_freq"
        return int(read_file(path))

    @min_freq.setter
    def min_freq(self, value: int) -> None:
        hw_min = self.min_hw_freq
        hw_max = self.max_hw_freq
        path = f"{self.cpu_path}/cpufreq/scaling_min_freq"
        if not (hw_min <= value <= hw_max):
            raise ProgramError(
                f"frequency {value} cannot be outside hardware limits [{hw_min}, {hw_max}]"
            )
        write_file_sudo(str(value), path)

    @property
    def max_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/scaling_max_freq"
        return int(read_file(path))

    @max_freq.setter
    def max_freq(self, value: int) -> None:
        hw_min = self.min_hw_freq
        hw_max = self.max_hw_freq
        path = f"{self.cpu_path}/cpufreq/scaling_max_freq"
        if not (hw_min <= value <= hw_max):
            raise ProgramError(
                f"frequency {value} cannot be outside hardware limits [{hw_min}, {hw_max}]"
            )
        write_file_sudo(str(value), path)


def get_cpu_vendor() -> str:
    cpuinfo = read_file("/proc/cpuinfo")
    if "GenuineIntel" in cpuinfo:
        return "intel"
    if "AuthenticAMD" in cpuinfo:
        return "amd"
    raise ProgramError("Unknown CPU vendor")


def get_cpus(value: str) -> list[Cpu]:
    available_modes = ["online", "offline", "present", "possible"]
    if not value in available_modes:
        raise ProgramError(f"Can only get {','.join(available_modes)} CPUs")

    cpus: list[Cpu] = []
    content = read_file(f"/sys/devices/system/cpu/{value}")
    if not content:
        return []

    for part in content.split(","):
        rng = part.split("-")
        if len(rng) == 2:
            cpus.extend([Cpu(v) for v in range(int(rng[0]), int(rng[1]) + 1)])
        else:
            cpus.append(Cpu(int(rng[0])))
    return cpus


def get_aslr() -> int:
    val = read_file("/proc/sys/kernel/randomize_va_space")
    return int(val)


def set_aslr(value: int) -> None:
    if value not in [0, 1, 2]:
        raise ProgramError(f"unsupported ASLR mode {value}")
    write_file_sudo(str(value), "/proc/sys/kernel/randomize_va_space")


def get_intel_boost() -> bool:
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    value = read_file(path)
    return not (value == "1")


def set_intel_boost(enable: bool) -> None:
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    if not os.path.exists(path):
        raise ProgramError(f"file {path} doesn't exist")
    write_file_sudo("0" if enable == True else "1", path)


@dataclass
class Environment:
    """Controls Linux-specific OS environment"""

    def record_original(self):
        self._orig_aslr = get_aslr()
        if get_cpu_vendor() == "intel":
            self._orig_intel_boost = get_intel_boost()

        self._orig_cpus = {}
        for cpu in get_cpus("present"):
            if cpu.enabled:
                self._orig_cpus[cpu.value] = {
                    "enabled": True,
                    "governor": cpu.governor,
                    "max_freq": cpu.max_freq,
                    "min_freq": cpu.min_freq
                }
            else:
                self._orig_cpus[cpu.value] = {
                    "enabled": False
                }

    def restore_original(self):
        set_aslr(self._orig_aslr)
        if get_cpu_vendor() == "intel":
            set_intel_boost(self._orig_intel_boost)

        for cpu in get_cpus("present"):
            orig_cpu = self._orig_cpus[cpu.value]
            if orig_cpu["enabled"]:
                cpu.enabled = True
                cpu.governor = orig_cpu["governor"]
                cpu.max_freq = orig_cpu["max_freq"]
                cpu.min_freq = orig_cpu["min_freq"]
            else:
                cpu.enabled = False

    def __str__(self) -> str:
        aslr = get_aslr()
        if aslr == 0:
            aslr_str = "off"
        elif aslr == 1:
            aslr_str = "partial"
        elif aslr == 2:
            aslr_str = "on"
        else:
            aslr_str = "unknown"

        vendor = get_cpu_vendor()
        boost_str = "unknown"
        if vendor == "intel":
            boost = get_intel_boost()
            if boost:
                boost_str = f"on"
            else:
                boost_str = f"off"

        gov = set()
        max_freq = set()
        min_freq = set()
        for cpu in get_cpus("online"):
            gov.add(cpu.governor)
            max_freq.add(cpu.max_freq)
            min_freq.add(cpu.min_freq)

        if len(gov) == 1:
            gov_str = gov.pop()
        elif len(gov) > 1:
            gov_str = "mixed"
        else:
            gov_str = "unknown"

        if len(max_freq) == 1:
            max_freq_str = round(max_freq.pop() * 1e-6, 2)
        elif len(max_freq) > 1:
            max_freq_str = "mixed"
        else:
            max_freq_str = "unknown"

        if len(min_freq) == 1:
            min_freq_str = round(min_freq.pop() * 1e-6, 2)
        elif len(min_freq) > 1:
            min_freq_str = "mixed"
        else:
            min_freq_str = "unknown"

        return (
            f"\033[1mplatform    :\033[0m {vendor} | \033[1mcpus on/off:\033[0m {len(get_cpus("online"))}/{len(get_cpus("offline"))} | \033[1mcpus freq:\033[0m {min_freq_str}GHz-{max_freq_str}Ghz\n"
            f"\033[1mturbo       :\033[0m {boost_str} | \033[1mgovernor:\033[0m {gov_str} | \033[1maslr:\033[0m {aslr_str}\n"
        )

    def __enter__(self):
        self.record_original()
        self.enter()
        return self

    def __exit__(self, exc_type: type | None, exc_value: Exception | None, traceback: Any | None) -> bool:
        self.restore_original()
        return False

    def enter(self) -> None:
        pass


@dataclass
class Production(Environment):
    def enter(self) -> None:
        set_aslr(2) # Enable ASLR

        set_intel_boost(True) # Enable Turbo Boost on Intel

        for cpu in get_cpus("present"):
            cpu.enabled = True # Enable all CPUs
            cpu.governor = "performance" # Peformance Governor on all CPUs
            cpu.max_freq = cpu.max_hw_freq # Max Hardware Frequency on all CPUs
            cpu.min_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs


@dataclass
class Lightweight(Environment):
    pass

@dataclass
class Lab(Environment):
    def enter(self) -> None:
        set_aslr(0) # Enable ASLR

        set_intel_boost(False) # Enable Turbo Boost on Intel

        for cpu in get_cpus("online"):
            if cpu.hyperthread:
                cpu.enabled = False # Disable all Hyperthreads

        for cpu in get_cpus("online")[4:]:
            cpu.enabled = False # Disable all but Cores 0, 1, 2, 3

        for cpu in get_cpus("online"):
            cpu.governor = "powersave" # Powersave Governor on all CPUs
            cpu.max_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs
            cpu.min_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs
