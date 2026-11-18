"""Running a command of the guard: the words filled in, an empty place left out with its flag, what the run answered."""
from __future__ import annotations

import sys
from pathlib import Path

from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import guard_command


def test_every_place_is_replaced_by_its_value():
    assert guard_command.argv_for(["peers", "--to", "{session}", "--covers-place", "{place}"],
                                  {"session": "s1", "place": "/x"}) == ["peers", "--to", "s1", "--covers-place", "/x"]


def test_a_place_with_no_value_is_left_out_with_the_flag_before_it():
    command = ["peers", "--place-for", "{session}", "--typed-in", "{typed_in}"]
    assert guard_command.argv_for(command, {"session": "s1", "typed_in": ""}) == ["peers", "--place-for", "s1"]
    assert guard_command.argv_for(command, {"session": "s1", "typed_in": "s2"}) == [
        "peers", "--place-for", "s1", "--typed-in", "s2"]


def test_a_word_that_is_not_a_flag_is_kept_when_the_place_after_it_is_empty():
    assert guard_command.argv_for(["peers", "plain", "{typed_in}"], {"typed_in": ""}) == ["peers", "plain"]


def test_a_tilde_is_the_home_folder():
    assert guard_command.argv_for(["~/bin/peers"], {}) == [str(Path.home() / "bin/peers")]


def test_a_run_answers_with_its_exit_code_what_it_printed_and_the_last_line_it_said_on_stderr(ticket_env):
    script = "import sys; print('out'); print('first', file=sys.stderr); print('  last  ', file=sys.stderr); sys.exit(3)"
    result = run(guard_command.run_command([sys.executable, "-c", script], {}))
    assert (result.status, result.stdout, result.reason) == (3, "out\n", "last")


def test_the_text_is_given_in_a_private_file_that_is_gone_after_the_run(ticket_env):
    script = "import sys, os; print(open(sys.argv[1]).read() + '|' + oct(os.stat(sys.argv[1]).st_mode & 0o777) + '|' + sys.argv[1])"
    result = run(guard_command.run_command([sys.executable, "-c", script, "{text_file}"], {}, "the text"))
    said, mode, path = result.stdout.strip().split("|")
    assert (said, mode) == ("the text", "0o600") and not Path(path).exists()


def test_a_command_that_cannot_run_answers_with_no_exit_code(ticket_env):
    result = run(guard_command.run_command([str(ticket_env.root / "missing-program")], {}))
    assert result.status is None and result.reason
