class ProgramError(Exception):
    pass


class ProgramBuildError(ProgramError):
    pass


class ProgramMeasureError(ProgramError):
    pass


class ProgramCleanError(ProgramError):
    pass


class ProgramVerificationError(ProgramError):
    pass


class ReportError(Exception):
    pass


class EnvironmentError(Exception):
    pass
