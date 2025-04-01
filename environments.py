from dataclasses import dataclass
from abc import ABC, abstractmethod
import subprocess
import os


def _read_file(file_path: str) -> str:
    with open(file_path, "r") as f:
        return f.read().strip()


def _write_file_sudo(file_path: str, value: str) -> None:
    subprocess.run(
        ["sudo", "tee", file_path], input=value.encode(), check=True, stdout=subprocess.DEVNULL
    )


def get_cpu_vendor() -> str:
    cpuinfo = _read_file("/proc/cpuinfo")
    if "GenuineIntel" in cpuinfo:
        return "intel"
    if "AuthenticAMD" in cpuinfo:
        return "amd"
    raise EnvironmentError("Unknown CPU vendor")


def get_cpus(mode: str) -> list[int]:
    if not mode in ["online", "offline"]:
        raise EnvironmentError(f"Cannot get contents of {mode} CPU")

    content = _read_file(f"/sys/devices/system/cpu/{mode}")
    if not content:
        return []
    cpus = []
    for part in content.split(","):
        rng = part.split("-")
        if len(rng) == 2:
            cpus.extend(range(int(rng[0]), int(rng[1]) + 1))
        else:
            cpus.append(int(rng[0]))
    return cpus


def get_all_cpus() -> list[int]:
    content = _read_file("/sys/devices/system/cpu/present")
    if not content:
        return []
    cpus = []
    for part in content.split(","):
        rng = part.split("-")
        if len(rng) == 2:
            cpus.extend(range(int(rng[0]), int(rng[1]) + 1))
        else:
            cpus.append(int(rng[0]))
    return cpus


def get_aslr() -> int:
    val = _read_file("/proc/sys/kernel/randomize_va_space")
    return int(val)


def set_aslr(mode: int) -> None:
    if mode not in [0, 1, 2]:
        raise EnvironmentError(f"Unsupported ASLR mode: {mode}")
    _write_file_sudo("/proc/sys/kernel/randomize_va_space", str(mode))


def get_turbo_boost() -> bool:
    vendor = get_cpu_vendor()
    if vendor == "intel":
        path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
        if os.path.exists(path):
            val = _read_file(path)
            return not (val == "1")
    return False


def set_turbo_boost(enable: bool) -> None:
    if get_cpu_vendor() != "intel":
        raise EnvironmentError("Setting Turbo Boost is only available on intel CPUs")
    value_to_write = "0" if enable == True else "1"
    path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    if os.path.exists(path):
        _write_file_sudo(path, value_to_write)


def get_available_governors() -> dict[int, list[str]]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join(
            "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_available_governors"
        )
        if os.path.exists(path):
            out[cpu] = _read_file(path).split()
        else:
            out[cpu] = []
    return out


def get_governors() -> dict[int, str]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_governor")
        if os.path.exists(path):
            out[cpu] = _read_file(path)
        else:
            out[cpu] = "unknown"
    return out


def set_governor(cpu: int, mode: str) -> None:
    available = get_available_governors().get(cpu, [])
    if mode not in available:
        raise EnvironmentError(f"Governor '{mode}' not available on CPU {cpu}. Found: {available}")
    path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_governor")
    _write_file_sudo(path, mode)


def get_min_frequencies() -> dict[int, int]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_min_freq")
        if os.path.exists(path):
            out[cpu] = int(_read_file(path))
    return out


def get_max_frequencies() -> dict[int, int]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_max_freq")
        if os.path.exists(path):
            out[cpu] = int(_read_file(path))
    return out


def get_hw_min_frequencies() -> dict[int, int]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "cpuinfo_min_freq")
        if os.path.exists(path):
            out[cpu] = int(_read_file(path))
    return out


def get_hw_max_frequencies() -> dict[int, int]:
    out = {}
    for cpu in get_cpus("online"):
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "cpuinfo_max_freq")
        if os.path.exists(path):
            out[cpu] = int(_read_file(path))
    return out


def set_min_frequency(cpu: int, freq: int) -> None:
    hw_min = get_hw_min_frequencies().get(cpu, None)
    hw_max = get_hw_max_frequencies().get(cpu, None)
    if hw_min is None or hw_max is None:
        raise EnvironmentError(f"CPU {cpu} hardware frequency info not found")
    if not (hw_min <= freq <= hw_max):
        raise EnvironmentError(f"Requested min {freq} outside hardware limits [{hw_min}, {hw_max}]")
    path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_min_freq")
    _write_file_sudo(path, str(freq))


def set_max_frequency(cpu: int, freq: int) -> None:
    hw_min = get_hw_min_frequencies().get(cpu, None)
    hw_max = get_hw_max_frequencies().get(cpu, None)
    if hw_min is None or hw_max is None:
        raise EnvironmentError(f"CPU {cpu} hardware frequency info not found")
    if not (hw_min <= freq <= hw_max):
        raise EnvironmentError(f"Requested max {freq} outside hardware limits [{hw_min}, {hw_max}]")
    path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_max_freq")
    _write_file_sudo(path, str(freq))


def set_hyperthreading(enable: bool) -> None:
    vendor = get_cpu_vendor()

    if enable:
        for cpu in get_cpus("offline"):
            path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "online")
            _write_file_sudo(path, "1")
    else:
        cpus_to_disable = set()
        for cpu in get_cpus("online"):
            topology_path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "topology", "thread_siblings_list"
            )
            if not os.path.exists(topology_path):
                continue

            siblings_str = _read_file(topology_path)
            if vendor == "amd":
                siblings = siblings_str.split("-")
            else:
                siblings = siblings_str.split(",")

            if len(siblings) < 2:
                continue

            for sibling in siblings[1:]:
                try:
                    cpus_to_disable.add(int(sibling.strip()))
                except ValueError:
                    continue

        for cpu in cpus_to_disable:
            path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "online")
            _write_file_sudo(path, "0")


@dataclass
class Environment:
    """Controls Linux-specific OS environment"""

    niceness: int | None = None

    def _record_original(self):
        self._orig_aslr = get_aslr()
        self._orig_turbo = get_turbo_boost()
        self._orig_hyperthreading = get_cpus("offline") == []
        self._orig_governors = get_governors()
        self._orig_min_freqs = get_min_frequencies()
        self._orig_max_freqs = get_max_frequencies()

    def _restore_original(self):
        set_aslr(self._orig_aslr)
        set_turbo_boost(self._orig_turbo)
        set_hyperthreading(self._orig_hyperthreading)
        for cpu, governor in self._orig_governors.items():
            set_governor(cpu, governor)
        for cpu, freq in self._orig_min_freqs.items():
            set_min_frequency(cpu, freq)
        for cpu, freq in self._orig_max_freqs.items():
            set_max_frequency(cpu, freq)

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

        turbo = get_turbo_boost()
        if turbo:
            turbo_str = f"on"
        else:
            turbo_str = f"off"

        gov = set()
        for cpu, applied_gov in get_governors().items():
            gov.add(applied_gov)

        if len(gov) == 1:
            gov_str = gov.pop()
        elif len(gov) > 1:
            gov_str = "mixed"
        else:
            gov_str = "unknown"

        max_freq = set()
        for cpu, applied_max_freq in get_max_frequencies().items():
            max_freq.add(applied_max_freq)

        if len(max_freq) == 1:
            max_freq_str = round(max_freq.pop() * 1e-6, 2)
        elif len(max_freq) > 1:
            max_freq_str = "mixed"
        else:
            max_freq_str = "unknown"

        min_freq = set()
        for cpu, applied_min_freq in get_min_frequencies().items():
            min_freq.add(applied_min_freq)

        if len(min_freq) == 1:
            min_freq_str = round(min_freq.pop() * 1e-6, 2)
        elif len(min_freq) > 1:
            min_freq_str = "mixed"
        else:
            min_freq_str = "unknown"

        return (
            f"Platform  : {get_cpu_vendor()} CPUs [{len(get_cpus("online"))} on] [{len(get_cpus("offline"))} off] [{min_freq_str}GHz-{max_freq_str}Ghz]\n"
            f"Features  : Turbo [{turbo_str}] Governor [{gov_str}]\n"
            f"OS        : ASLR [{aslr_str}]"
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


@dataclass
class Production(Environment):
    def __enter__(self):
        self._record_original()

        # Enable ASLR
        set_aslr(2)

        # Enable Turbo Boost on Intel
        set_turbo_boost(True)

        # Enable Hyperthreading
        set_hyperthreading(True)

        hw_min_freqs = get_hw_min_frequencies()
        hw_max_freqs = get_hw_max_frequencies()
        for cpu in get_cpus("online"):
            # All online CPUs frequencies set to hardware bounds
            set_min_frequency(cpu, hw_min_freqs[cpu])
            set_max_frequency(cpu, hw_max_freqs[cpu])

            # All online CPUs get the 'performance' governor
            set_governor(cpu, "performance")
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

        # Disable ASLR
        set_aslr(0)

        # Disable Turbo Boost on Intel
        set_turbo_boost(False)

        # Disable Hyperthreading
        set_hyperthreading(False)

        hw_min_freqs = get_hw_min_frequencies()
        for cpu in get_cpus("online"):
            # All online CPUs pined to their lowest frequencies
            set_min_frequency(cpu, hw_min_freqs[cpu])
            set_max_frequency(cpu, hw_min_freqs[cpu])

            # All online CPUs get the 'powersave' governor
            set_governor(cpu, "powersave")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_original()
        return False
