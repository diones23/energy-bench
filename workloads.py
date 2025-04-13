from subprocess import CalledProcessError
import subprocess
import signal
import time
import os


from errors import ProgramError


class Workload:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def __str__(self) -> str:
        return self.__class__.__name__.lower()


class Librewolf(Workload):
    def __enter__(self):
        command = f"{self._start_virtual_display_command()} & {self._start_librewolf_command()} ; {self._open_sites_command()}"
        command = self._nix_wrapper(command)
        try:
            self._result = subprocess.Popen(
                args=command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, process_group=0
            )
            time.sleep(2)
        except CalledProcessError as ex:
            raise ProgramError(f"failed while starting workload - {ex}")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.killpg(os.getpgid(self._result.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        return False

    def _start_virtual_display_command(self, display: int = 99) -> str:
        return f"Xvfb :{display}"

    def _start_librewolf_command(self, display: int = 99) -> str:
        return f"librewolf --display=:{display} & sleep 5"

    def _open_sites_command(self, display: int = 99) -> str:
        urls = [
            "https://www.youtube.com/watch?v=xm3YgoEiEDc",
            "https://www.google.com/",
            "https://open.spotify.com/",
            "https://www.amazon.com/",
        ]

        return "& ".join([f"librewolf --new-tab --display=:{display} '{url}'" for url in urls])

    def _nix_wrapper(self, command: str) -> list[str]:
        dependencies = ["librewolf", "xorg.xvfb"]
        nix_commit = "https://github.com/NixOS/nixpkgs/archive/52e3095f6d812b91b22fb7ad0bfc1ab416453634.tar.gz"

        return (
            ["nix-shell", "--no-build-output", "--quiet", "--packages"]
            + dependencies
            + ["-I", f"nixpkgs={nix_commit}", "--run", command]
        )
