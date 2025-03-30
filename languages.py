from dataclasses import dataclass, field
from typing import ClassVar
import os

from base import Language

"""
All supported languages. Can be extended
"""
__all__ = ["C", "Cpp", "CSharp", "Java", "JavaScript", "Python", "Rust"]


@dataclass
class C(Language):
    aliases: ClassVar[list[str]] = ["c"]
    target: str = "main"
    source: str = "main.c"
    rapl_usage: str = """
        #include <rapl_interface.h> // brings start_rapl and stop_rapl in scope
        int main() {
            while (1) {
                char *str = (char *)malloc(16 * sizeof(char)); // initialization code
                if (start_rapl() == 0) break;
                printf("%s\n", str); // code to be measured
                stop_rapl();
                free(str) // cleanup code
            }
            return 0;
        }
    """

    @property
    def build_command(self) -> list[str]:
        return ["gcc", self.source_path, "-o", self.target_path, "-w", "-lrapl_interface"]

    @property
    def measure_command(self) -> list[str]:
        return [self.target_path]

    @property
    def clean_command(self) -> list[str]:
        return ["rm", "-f", self.target_path, self.source_path]


@dataclass
class Cpp(C):
    aliases: ClassVar[list[str]] = ["c++", "cpp", "cplus", "cplusplus"]
    source: str = "main.cpp"

    @property
    def build_command(self) -> list[str]:
        return ["g++", self.source_path, "-o", self.target_path, "-w", "-lrapl_interface"]


@dataclass
class CSharp(Language):
    # C# specific
    packages: list[dict] = field(default_factory=list)

    # Generic
    aliases: ClassVar[list[str]] = ["c#", "cs", "csharp"]
    target: str = os.path.join("bin", "Release", "net*", "program")
    source: str = "Program.cs"
    rapl_usage: str = """
    """

    @property
    def build_command(self) -> list[str]:
        return ["dotnet", "build", self.benchmark_path, "--nologo", "-v q", "-p:WarningLevel=0"]

    @property
    def measure_command(self) -> list[str]:
        return ["envDOTNET_ROOT=$(dirname $(readlink -f $(which dotnet)))", self.target_path]

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
class Java(Language):
    aliases: ClassVar[list[str]] = ["java"]
    target: str = "main"
    source: str = "main.c"
    rapl_usage: str = """
        #include <rapl_interface.h> // brings start_rapl and stop_rapl in scope
        int main() {
            while (1) {
                char *str = (char *)malloc(16 * sizeof(char)); // initialization code
                if (start_rapl() == 0) break;
                printf("%s\n", str); // code to be measured
                stop_rapl();
                free(str) // cleanup code
            }
            return 0;
        }
    """

    @property
    def build_command(self) -> list[str]:
        return ["gcc", self.source_path, "-o", self.target_path, "-lrapl_interface"]

    @property
    def measure_command(self) -> list[str]:
        return [self.target_path]

    @property
    def clean_command(self) -> list[str]:
        return ["rm", "-f", self.target_path, self.source_path]


@dataclass
class JavaScript(Language):
    pass


@dataclass
class Python(Language):
    pass


@dataclass
class Rust(Language):
    pass
