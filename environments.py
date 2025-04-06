from dataclasses import dataclass
import subprocess
import os


class Cpu:
    def __init__(self, value: int) -> None:
        self.cpu_path = f"/sys/devices/system/cpu/cpu{value}"
        if os.path.isdir(self.cpu_path):
            self.value = value
        else:
            raise EnvironmentError(f"Cpu {value} doesn't exist.")

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
            _write_file_sudo(path, "1" if value else "0")

    @property
    def hyperthread(self) -> bool:
        path = f"{self.cpu_path}/topology/thread_siblings_list"

        try:
            siblings_str = _read_file_safe(path)
        except EnvironmentError:
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
        return _read_file_safe(path)

    @governor.setter
    def governor(self, value: str) -> None:
        path = f"{self.cpu_path}/cpufreq/scaling_governor"
        if value not in self.available_governors:
            raise EnvironmentError(f"Governor '{value}' not available on CPU {self.value}.")
        _write_file_sudo(path, value)

    @property
    def available_governors(self) -> list[str]:
        path = f"{self.cpu_path}/cpufreq/scaling_available_governors"
        return _read_file_safe(path).split()

    @property
    def min_hw_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/cpuinfo_min_freq"
        return int(_read_file_safe(path))

    @property
    def max_hw_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/cpuinfo_max_freq"
        return int(_read_file_safe(path))

    @property
    def min_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/scaling_min_freq"
        return int(_read_file_safe(path))

    @min_freq.setter
    def min_freq(self, value: int) -> None:
        hw_min = self.min_hw_freq
        hw_max = self.max_hw_freq
        path = f"{self.cpu_path}/cpufreq/scaling_min_freq"
        if not (hw_min <= value <= hw_max):
            raise EnvironmentError(
                f"Frequency {value} cannot be outside hardware limits [{hw_min}, {hw_max}]"
            )
        _write_file_sudo(path, str(value))

    @property
    def max_freq(self) -> int:
        path = f"{self.cpu_path}/cpufreq/scaling_max_freq"
        return int(_read_file_safe(path))

    @max_freq.setter
    def max_freq(self, value: int) -> None:
        hw_min = self.min_hw_freq
        hw_max = self.max_hw_freq
        path = f"{self.cpu_path}/cpufreq/scaling_max_freq"
        if not (hw_min <= value <= hw_max):
            raise EnvironmentError(
                f"Frequency {value} cannot be outside hardware limits [{hw_min}, {hw_max}]"
            )
        _write_file_sudo(path, str(value))


def _read_file_safe(path: str) -> str:
    try:
        if os.path.exists(path):
            with open(path, "r") as file:
                return file.read().strip()
        raise EnvironmentError(f"File {path} doesn't exist.")
    except OSError:
        raise EnvironmentError(f"Could not read file {path}.")


def _write_file_sudo(path: str, value: str) -> None:
    subprocess.run(
        ["sudo", "tee", path], input=value.encode(), check=True, stdout=subprocess.DEVNULL
    )


def get_cpu_vendor() -> str:
    cpuinfo = _read_file_safe("/proc/cpuinfo")
    if "GenuineIntel" in cpuinfo:
        return "intel"
    if "AuthenticAMD" in cpuinfo:
        return "amd"
    raise EnvironmentError("Unknown CPU vendor")


def get_cpus(value: str) -> list[Cpu]:
    available_modes = ["online", "offline", "present", "possible"]
    if not value in available_modes:
        raise EnvironmentError(f"Can only get {','.join(available_modes)} CPUs")

    cpus: list[Cpu] = []
    content = _read_file_safe(f"/sys/devices/system/cpu/{value}")
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
    val = _read_file_safe("/proc/sys/kernel/randomize_va_space")
    return int(val)


def set_aslr(value: int) -> None:
    if value not in [0, 1, 2]:
        raise EnvironmentError(f"Unsupported ASLR mode: {value}")
    _write_file_sudo("/proc/sys/kernel/randomize_va_space", str(value))


def get_intel_boost() -> bool:
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    value = _read_file_safe(path)
    return not (value == "1")


def set_intel_boost(enable: bool) -> None:
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    _read_file_safe(path)
    _write_file_sudo(path, "0" if enable == True else "1")


@dataclass
class Environment:
    """Controls Linux-specific OS environment"""

    niceness: int | None = None

    def _record_original(self):
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

    def _restore_original(self):
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
            f"Platform  : {vendor} CPUs [{len(get_cpus("online"))} on] [{len(get_cpus("offline"))} off] [{min_freq_str}GHz-{max_freq_str}Ghz]\n"
            f"Features  : Turbo [{boost_str}] Governor [{gov_str}]\n"
            f"OS        : ASLR  [{aslr_str}]"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


@dataclass
class Production(Environment):
    def __enter__(self):
        self._record_original()

        set_aslr(2) # Enable ASLR

        set_intel_boost(True) # Enable Turbo Boost on Intel

        for cpu in get_cpus("present"):
            cpu.enabled = True # Enable all CPUs
            cpu.governor = "performance" # Peformance Governor on all CPUs
            cpu.max_freq = cpu.max_hw_freq # Max Hardware Frequency on all CPUs
            cpu.min_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_original()
        return False


@dataclass
class Lightweight(Environment):
    def __enter__(self):
        self._record_original()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_original()
        return False


@dataclass
class Lab(Environment):
    niceness: int | None = -20

    def __enter__(self):
        self._record_original()

        set_aslr(0) # Enable ASLR

        set_intel_boost(False) # Enable Turbo Boost on Intel

        for cpu in get_cpus("online"):
            if cpu.hyperthread:
                cpu.enabled = False # Disable all Hyperthreads

        for cpu in get_cpus("online")[4:]:
            cpu.enabled = False # Disable all but Cores 0, 1, 2, 3

        for cpu in get_cpus("online"):
            cpu.governor = "powersave" # Peformance Governor on all CPUs
            cpu.max_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs
            cpu.min_freq = cpu.min_hw_freq # Min Hardware Frequency on all CPUs

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_original()
        return False
