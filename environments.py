from dataclasses import dataclass
from abc import ABC, abstractmethod
import subprocess
import os


@dataclass
class Environment:
    """Controls Linux-specific OS environment"""

    niceness: int | None = None

    def __read_file(self, file_path: str) -> str:
        with open(file_path, "r") as f:
            return f.read().strip()

    def __write_file_sudo(self, file_path: str, value: str) -> None:
        subprocess.run(
            ["sudo", "tee", file_path], input=value.encode(), check=True, stdout=subprocess.DEVNULL
        )

    def _get_cpu_vendor(self) -> str:
        cpuinfo = self.__read_file("/proc/cpuinfo")
        if "GenuineIntel" in cpuinfo:
            return "intel"
        if "AuthenticAMD" in cpuinfo:
            return "amd"
        raise EnvironmentError("Unknown CPU vendor")

    def _get_cpus(self, mode: str) -> list[int]:
        if not mode in ["online", "offline"]:
            raise EnvironmentError(f"Cannot get contents of {mode} CPU")

        content = self.__read_file(f"/sys/devices/system/cpu/{mode}")
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

    def _get_all_cpus(self) -> list[int]:
        content = self.__read_file("/sys/devices/system/cpu/present")
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

    def _get_aslr(self) -> int:
        val = self.__read_file("/proc/sys/kernel/randomize_va_space")
        return int(val)

    def _set_aslr(self, mode: int) -> None:
        if mode not in [0, 1, 2]:
            raise EnvironmentError(f"Unsupported ASLR mode: {mode}")
        self.__write_file_sudo("/proc/sys/kernel/randomize_va_space", str(mode))

    def _get_turbo_boost(self) -> bool:
        vendor = self._get_cpu_vendor()
        if vendor == "intel":
            path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
            if os.path.exists(path):
                val = self.__read_file(path)
                return not (val == "1")
        return False

    def _set_turbo_boost(self, enable: bool) -> None:
        if self._get_cpu_vendor() != "intel":
            raise EnvironmentError("Setting Turbo Boost is only available on intel CPUs")
        value_to_write = "0" if enable == True else "1"
        path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
        if os.path.exists(path):
            self.__write_file_sudo(path, value_to_write)

    def _get_available_governors(self) -> dict[int, list[str]]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_available_governors"
            )
            if os.path.exists(path):
                out[cpu] = self.__read_file(path).split()
            else:
                out[cpu] = []
        return out

    def _get_governors(self) -> dict[int, str]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_governor"
            )
            if os.path.exists(path):
                out[cpu] = self.__read_file(path)
            else:
                out[cpu] = "unknown"
        return out

    def _set_governor(self, cpu: int, mode: str) -> None:
        available = self._get_available_governors().get(cpu, [])
        if mode not in available:
            raise EnvironmentError(
                f"Governor '{mode}' not available on CPU {cpu}. Found: {available}"
            )
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_governor")
        self.__write_file_sudo(path, mode)

    def _get_min_frequencies(self) -> dict[int, int]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_min_freq"
            )
            if os.path.exists(path):
                out[cpu] = int(self.__read_file(path))
        return out

    def _get_max_frequencies(self) -> dict[int, int]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_max_freq"
            )
            if os.path.exists(path):
                out[cpu] = int(self.__read_file(path))
        return out

    def _get_hw_min_frequencies(self) -> dict[int, int]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "cpuinfo_min_freq"
            )
            if os.path.exists(path):
                out[cpu] = int(self.__read_file(path))
        return out

    def _get_hw_max_frequencies(self) -> dict[int, int]:
        out = {}
        for cpu in self._get_cpus("online"):
            path = os.path.join(
                "/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "cpuinfo_max_freq"
            )
            if os.path.exists(path):
                out[cpu] = int(self.__read_file(path))
        return out

    def _set_min_frequency(self, cpu: int, freq: int) -> None:
        hw_min = self._get_hw_min_frequencies().get(cpu, None)
        hw_max = self._get_hw_max_frequencies().get(cpu, None)
        if hw_min is None or hw_max is None:
            raise EnvironmentError(f"CPU {cpu} hardware frequency info not found")
        if not (hw_min <= freq <= hw_max):
            raise EnvironmentError(
                f"Requested min {freq} outside hardware limits [{hw_min}, {hw_max}]"
            )
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_min_freq")
        self.__write_file_sudo(path, str(freq))

    def _set_max_frequency(self, cpu: int, freq: int) -> None:
        hw_min = self._get_hw_min_frequencies().get(cpu, None)
        hw_max = self._get_hw_max_frequencies().get(cpu, None)
        if hw_min is None or hw_max is None:
            raise EnvironmentError(f"CPU {cpu} hardware frequency info not found")
        if not (hw_min <= freq <= hw_max):
            raise EnvironmentError(
                f"Requested max {freq} outside hardware limits [{hw_min}, {hw_max}]"
            )
        path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "cpufreq", "scaling_max_freq")
        self.__write_file_sudo(path, str(freq))

    def _set_hyperthreading(self, enable: bool) -> None:
        vendor = self._get_cpu_vendor()

        if enable:
            for cpu in self._get_cpus("offline"):
                path = os.path.join("/sys/devices/system/cpu", f"cpu{cpu}", "online")
                self.__write_file_sudo(path, "1")
        else:
            cpus_to_disable = set()
            for cpu in self._get_cpus("online"):
                topology_path = os.path.join(
                    "/sys/devices/system/cpu", f"cpu{cpu}", "topology", "thread_siblings_list"
                )
                if not os.path.exists(topology_path):
                    continue

                siblings_str = self.__read_file(topology_path)
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
                self.__write_file_sudo(path, "0")

    def _record_original(self):
        self._orig_aslr = self._get_aslr()
        self._orig_turbo = self._get_turbo_boost()
        self._orig_hyperthreading = self._get_cpus("offline") == []
        self._orig_min_freqs = self._get_min_frequencies()
        self._orig_max_freqs = self._get_max_frequencies()

    def _restore_original(self):
        self._set_aslr(self._orig_aslr)
        self._set_turbo_boost(self._orig_turbo)
        self._set_hyperthreading(self._orig_hyperthreading)
        for cpu, freq in self._orig_min_freqs.items():
            self._set_min_frequency(cpu, freq)
        for cpu, freq in self._orig_max_freqs.items():
            self._set_max_frequency(cpu, freq)

    @abstractmethod
    def __enter__(self):
        return self

    @abstractmethod
    def __exit__(self, exc_type, exc_value, traceback):
        return False


@dataclass
class Production(Environment):
    def __enter__(self):
        self._record_original()

        # Enable ASLR
        self._set_aslr(2)

        # Enable Turbo Boost on Intel
        self._set_turbo_boost(True)

        # Enable Hyperthreading
        self._set_hyperthreading(True)

        # All online CPUs frequencies set to hardware bounds
        hw_min_freqs = self._get_hw_min_frequencies()
        hw_max_freqs = self._get_hw_max_frequencies()
        for cpu in self._get_cpus("online"):
            self._set_min_frequency(cpu, hw_min_freqs[cpu])
            self._set_max_frequency(cpu, hw_max_freqs[cpu])
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
        self._set_aslr(0)

        # Disable Turbo Boost on Intel
        self._set_turbo_boost(False)

        # Disable Hyperthreading
        self._set_hyperthreading(False)

        # All online CPUs pined to their lowest frequencies
        hw_min_freqs = self._get_hw_max_frequencies()
        for cpu in self._get_cpus("online"):
            self._set_min_frequency(cpu, hw_min_freqs[cpu])
            self._set_max_frequency(cpu, hw_min_freqs[cpu])
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_original()
        return False
