from dataclasses import dataclass
from typing import ClassVar
import os

from spec import Implementation
from utils import *


def get_impl_cls(impl_str: str) -> type[Implementation]:
    istr = impl_str.lower().strip()
    for cls in all_subclasses(Implementation):
        if hasattr(cls, "aliases") and istr in cls.aliases:
            return cls
    raise ProgramError(f"{impl_str} not a known implementation")


@dataclass
class C(Implementation):
    aliases: ClassVar[list[str]] = ["c"]
    target: str = "main"
    source: str = "main.c"
    rapl_usage: str = """#include <rapl_interface.h>
int main(int argc, char **argv) {
    while (start_rapl()) {
        run_benchmark(argv)
        stop_rapl();
    }
    return 0;
}"""

    @property
    def build_command(self) -> list[str]:
        return ["gcc", self.source_path, "-o", self.target_path, "-w", "-lrapl_interface"]

    @property
    def measure_command(self) -> list[str]:
        return [self.target_path]

    @property
    def clean_command(self) -> list[str]:
        return ["rm", "-f", self.target_path]


@dataclass
class Cpp(C):
    aliases: ClassVar[list[str]] = ["c++", "cpp", "cplus", "cplusplus"]
    source: str = "main.cpp"

    @property
    def build_command(self) -> list[str]:
        return ["g++", self.source_path, "-o", self.target_path, "-w", "-lrapl_interface"]


@dataclass
class CSharp(Implementation):
    aliases: ClassVar[list[str]] = ["c#", "cs", "csharp"]
    target: str = os.path.join("bin", "Release", "net*", "program")
    source: str = "Program.cs"
    rapl_usage: str = """using System.Runtime.InteropServices;
class Program {
    [DllImport("librapl_interface", EntryPoint = "start_rapl")]
    private static extern bool start_rapl();

    [DllImport("librapl_interface", EntryPoint = "stop_rapl")]
    private static extern void stop_rapl();
    public static void Main(string[] args) {
        while (start_rapl()) {
            run_benchmark(args);
            stop_rapl();
        }
    }
}"""

    @property
    def build_command(self) -> list[str]:
        return [
            "dotnet",
            "build",
            self.benchmark_path,
            "--nologo",
            "-v q",
            "-p:WarningLevel=0",
            "-p:UseSharedCompilation=false",
        ]

    @property
    def measure_command(self) -> list[str]:
        return ["env DOTNET_ROOT=$(dirname $(readlink -f $(which dotnet)))", self.target_path]

    @property
    def clean_command(self) -> list[str]:
        bin_path = os.path.join(self.benchmark_path, "bin")
        obj_path = os.path.join(self.benchmark_path, "obj")
        csproj_path = os.path.join(self.benchmark_path, "program.csproj")
        return ["rm", "-rf", bin_path, obj_path, csproj_path]

    def build(self) -> None:
        csproj_path = os.path.join(self.benchmark_path, "program.csproj")
        with open(csproj_path, "w") as file:
            package_references = "".join(
                [
                    f'<PackageReference Include="{pkg.get("name")}" Version="{pkg.get("version")}" />'
                    for pkg in self.packages
                ]
            )
            # Default TargetFramework can be overriden using -p:TargetFramework=net<version>
            file.write(
                f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net9.0</TargetFramework></PropertyGroup><ItemGroup>{package_references}</ItemGroup></Project>'
            )
        super().build()


@dataclass
class Java(Implementation):
    aliases: ClassVar[list[str]] = ["java"]
    target: str = "Program"
    source: str = "Program.java"
    rapl_usage: str = """
    """

    @property
    def _cp_flag(self) -> str:
        return f"-cp {self.base_dir}:{self.benchmark_path}:{':'.join(self.class_paths)}"

    @property
    def build_command(self) -> list[str]:
        return ["javac", "-nowarn", f"-d {self.benchmark_path}", self._cp_flag, self.source_path]

    @property
    def measure_command(self) -> list[str]:
        return [
            "$(which java)",
            "--enable-native-access=ALL-UNNAMED",
            self._cp_flag,
            self.target,
            *self.roptions,
        ]

    @property
    def clean_command(self) -> list[str]:
        classes_path = f"{self.benchmark_path}/*.class"
        return ["rm", "-f", classes_path]


@dataclass
class GraalVm(Java):
    aliases: ClassVar[list[str]] = ["graalvm"]


@dataclass
class OpenJdk(Java):
    aliases: ClassVar[list[str]] = ["openjdk"]


@dataclass
class Semeru(Java):
    aliases: ClassVar[list[str]] = ["semeru"]


@dataclass
class JavaScript(Implementation):
    # Generic
    aliases: ClassVar[list[str]] = ["javascript", "js"]


@dataclass
class Python(Implementation):
    # Generic
    aliases: ClassVar[list[str]] = ["python", "py"]


@dataclass
class Rust(Implementation):
    # Generic
    aliases: ClassVar[list[str]] = ["rust", "rs"]
