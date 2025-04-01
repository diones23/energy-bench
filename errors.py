# from difflib import unified_diff


class ProgramError(Exception):
    def __init__(self, msg: str | bytes) -> None:
        self.msg = msg

    def __str__(self) -> str:
        if isinstance(self.msg, str):
            return self.msg
        else:
            return self.msg.decode("utf-8")


class ProgramBuildError(ProgramError):
    pass


class ProgramMeasureError(ProgramError):
    pass


class ProgramCleanError(ProgramError):
    pass


class ProgramVerificationError(ProgramError):
    def __init__(self, expected: str | bytes, actual: str | bytes) -> None:
        self.expected = expected
        self.actual = actual

    def __str__(self) -> str:
        # lines1 = self.expected.splitlines(keepends=True)
        # lines2 = self.actual.splitlines(keepends=True)
        # diff = unified_diff(lines1, lines2, fromfile="expected", tofile="actual")
        # return f"Benchmark output didn't match expected output:\n{" ".join(diff)}"
        return f"Benchmark didn't match expected stdout"


class ReportError(Exception):
    pass


class EnvironmentError(Exception):
    pass
