"""PySide6 graphical user interface for myFlowNet."""


def run(argv=None):
    from .main_window import run as _run
    return _run(argv)
