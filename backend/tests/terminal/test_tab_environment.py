"""A tab starts without the backend's own Python environment: in the spawned process and in the tmux server.

The tmux calls are stubbed (= which commands are sent is what is checked), as in test_tmux_resilience.py.
"""
import subprocess

from backend.terminal import runner
from backend.terminal.tab_environment import read_environment, tab_environment

ENV = "/home/someone/platform/envs/client"
BACKEND = {
    "HOME": "/home/someone",
    "PATH": f"{ENV}/bin:/opt/homebrew/bin:/usr/bin:/bin",
    "VIRTUAL_ENV": ENV,
    "UV_PROJECT_ENVIRONMENT": ENV,
    "UV_RUN_RECURSION_DEPTH": "1",
    "AGENT_PLATFORM_ROOT": "/home/someone/platform",
}


def test_the_python_environment_of_the_backend_is_left_out():
    tab = tab_environment(BACKEND)
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH"):
        assert name not in tab
    assert tab["PATH"] == "/opt/homebrew/bin:/usr/bin:/bin"


def test_everything_else_is_passed_as_it_is():
    tab = tab_environment(BACKEND)
    assert tab["HOME"] == "/home/someone"
    assert tab["AGENT_PLATFORM_ROOT"] == "/home/someone/platform"


def test_a_folder_on_the_path_that_only_shares_the_start_of_the_name_stays():
    tab = tab_environment({**BACKEND, "PATH": f"{ENV}/bin:{ENV}-other/bin:/usr/bin"})
    assert tab["PATH"] == f"{ENV}-other/bin:/usr/bin"


def test_an_environment_named_only_by_uv_is_taken_off_the_path_too():
    tab = tab_environment({"PATH": f"{ENV}/bin:/usr/bin", "UV_PROJECT_ENVIRONMENT": ENV})
    assert tab == {"PATH": "/usr/bin"}


def test_a_backend_started_outside_any_environment_passes_all_it_has():
    plain = {"HOME": "/home/someone", "PATH": "/usr/bin:/bin"}
    assert tab_environment(plain) == plain


def test_the_listing_of_tmux_is_read_as_names_and_values_and_removed_ones_are_skipped():
    listed = "HOME=/home/someone\n-SSH_AUTH_SOCK\nPATH=/a:/b\nEMPTY=\n"
    assert read_environment(listed) == {"HOME": "/home/someone", "PATH": "/a:/b", "EMPTY": ""}


class _Server:
    """A stand-in for the tmux server: answers `show-environment -g` with `shown`, records the rest."""

    def __init__(self, shown: str, rc: int = 0):
        self.shown, self.rc, self.calls = shown, rc, []

    def __call__(self, args, capture_output=True, timeout=None, text=False):
        verb = args[args.index("show-environment")] if "show-environment" in args else None
        self.calls.append(list(args))
        if verb:
            return subprocess.CompletedProcess(args, self.rc, self.shown, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def sent(self):
        return [call[call.index("set-environment"):] for call in self.calls if "set-environment" in call]


def _listed(environ):
    return "".join(f"{name}={value}\n" for name, value in environ.items())


def test_the_server_loses_the_python_environment_and_gets_the_path_without_it(monkeypatch):
    server = _Server(_listed(BACKEND))
    monkeypatch.setattr(runner.subprocess, "run", server)
    runner.clean_server_environment()
    assert server.sent() == [
        ["set-environment", "-g", "-u", "UV_PROJECT_ENVIRONMENT"],
        ["set-environment", "-g", "-u", "UV_RUN_RECURSION_DEPTH"],
        ["set-environment", "-g", "-u", "VIRTUAL_ENV"],
        ["set-environment", "-g", "PATH", "/opt/homebrew/bin:/usr/bin:/bin"],
    ]


def test_a_clean_server_is_not_touched(monkeypatch):
    server = _Server(_listed(tab_environment(BACKEND)))
    monkeypatch.setattr(runner.subprocess, "run", server)
    runner.clean_server_environment()
    assert server.sent() == []


def test_a_server_that_does_not_answer_is_left_as_it_is(monkeypatch):
    server = _Server("", rc=1)
    monkeypatch.setattr(runner.subprocess, "run", server)
    runner.clean_server_environment()
    assert server.sent() == []
