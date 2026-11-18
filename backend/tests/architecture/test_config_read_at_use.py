"""Gate: a name that `backend/_common/config.py` serves from the configuration is read where it is used.

`config.py` builds `AGENTS`, `CLAUDE_PATH` and the other served names in a module `__getattr__`, on every read.
`from backend._common.config import AGENTS` at the top of a module reads it once, at import, and keeps that value:
a configuration read again later, or a test that points the configuration elsewhere, is not seen by that module.
The form to write is `from backend._common import config as _config` at the top and `_config.AGENTS` where the value
is used.

The served names are taken from the `__getattr__` of config.py itself, so a name added there is covered without a
change here. Three shapes bind a copy at import and fail this test: a `from backend._common.config import <name>`
(or `import *`) that runs when the module is imported, and a module-level assignment from `<alias>.<name>`. An import
inside a function reads the value at call time and is not one of them.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = BACKEND_ROOT / "_common" / "config.py"
CONFIG_MODULE = "backend._common.config"

# A function body (and a lambda) runs when it is called, not when the module is imported.
_DEFERRED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def served_names(config_source: str) -> frozenset[str]:
    """The names `__getattr__` of config.py answers: every string it compares `name` with (`==` or `in`)."""
    tree = ast.parse(config_source)
    getter = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "__getattr__"), None
    )
    if getter is None:
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(getter):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                names.add(comparator.value)
            elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                names.update(
                    item.value for item in comparator.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    return frozenset(names)


def _statements_run_at_import(body: list[ast.stmt]):
    """Every statement that runs when the module is imported: the module's own, those nested in `if` / `try` /
    `with` / `for` / `while`, and a class body. A function body is left out (it runs when called)."""
    for statement in body:
        yield statement
        if isinstance(statement, _DEFERRED):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _statements_run_at_import(getattr(statement, field, []))
        for handler in getattr(statement, "handlers", []):
            yield from _statements_run_at_import(handler.body)


def _expression_nodes_run_at_import(expression: ast.AST):
    """The nodes of an expression that are evaluated at once (= a lambda's body is not)."""
    pending = [expression]
    while pending:
        node = pending.pop()
        if isinstance(node, _DEFERRED):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def import_time_copies(source: str, served: frozenset[str]) -> list[tuple[int, str]]:
    """(line, what) for each place of `source` that binds a served name of config.py when the module is imported."""
    found: list[tuple[int, str]] = []
    aliases: set[str] = set()
    statements = list(_statements_run_at_import(ast.parse(source).body))
    for statement in statements:
        if isinstance(statement, ast.ImportFrom) and statement.module == CONFIG_MODULE and statement.level == 0:
            for imported in statement.names:
                if imported.name == "*":
                    found.append((statement.lineno, "from backend._common.config import *"))
                elif imported.name in served:
                    found.append((statement.lineno, f"from backend._common.config import {imported.name}"))
        elif isinstance(statement, ast.ImportFrom) and statement.module == "backend._common" and statement.level == 0:
            aliases.update(imported.asname or imported.name for imported in statement.names if imported.name == "config")
        elif isinstance(statement, ast.Import):
            aliases.update(imported.asname for imported in statement.names if imported.name == CONFIG_MODULE and imported.asname)
    for statement in statements:
        value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
        if value is None:
            continue
        for node in _expression_nodes_run_at_import(value):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in served
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                found.append((node.lineno, f"a module-level assignment from {node.value.id}.{node.attr}"))
    return found


def _backend_sources():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        if path.relative_to(BACKEND_ROOT).parts[0] in ("tests", "__pycache__"):
            continue
        yield path


def test_the_names_config_serves_are_found():
    """If the parse of `__getattr__` found nothing, the gate below would pass on every module."""
    served = served_names(CONFIG_FILE.read_text(encoding="utf-8"))
    assert {"AGENTS", "ACCOUNTS", "CLAUDE_PATH", "UPLOADS_TMP", "CLAUDE_PROJECTS_DIRS", "AGENT_MESSAGE_PEERS"} <= served
    assert "get_config" not in served and "HOME" not in served


def test_no_module_binds_a_served_config_name_at_import():
    served = served_names(CONFIG_FILE.read_text(encoding="utf-8"))
    violations = [
        f"{path.relative_to(BACKEND_ROOT.parent)}:{line}: {what}"
        for path in _backend_sources()
        for line, what in import_time_copies(path.read_text(encoding="utf-8"), served)
    ]
    assert not violations, (
        "a name config.py serves from the configuration is bound once at import; "
        "write `from backend._common import config as _config` and read `_config.<NAME>` where it is used:\n  "
        + "\n  ".join(violations)
    )


# What the gate must catch, and what it must let through: the detector run on small sources.
_SERVED = frozenset({"AGENTS", "CLAUDE_PATH"})


def test_the_detector_catches_each_shape_that_binds_a_copy():
    assert import_time_copies("from backend._common.config import AGENTS\n", _SERVED) == [
        (1, "from backend._common.config import AGENTS")
    ]
    assert import_time_copies("from backend._common.config import CLAUDE_PATH as _path, get_config\n", _SERVED) == [
        (1, "from backend._common.config import CLAUDE_PATH")
    ]
    assert import_time_copies("from backend._common.config import *\n", _SERVED) == [
        (1, "from backend._common.config import *")
    ]
    assert import_time_copies("try:\n    from backend._common.config import AGENTS\nexcept ImportError:\n    AGENTS = {}\n", _SERVED) == [
        (2, "from backend._common.config import AGENTS")
    ]
    assert import_time_copies("class Holder:\n    from backend._common.config import AGENTS\n", _SERVED) == [
        (2, "from backend._common.config import AGENTS")
    ]
    assert import_time_copies("from backend._common import config as _config\nHELD = _config.AGENTS\n", _SERVED) == [
        (2, "a module-level assignment from _config.AGENTS")
    ]
    assert import_time_copies("import backend._common.config as cfg\nHELD: dict = dict(cfg.AGENTS)\n", _SERVED) == [
        (2, "a module-level assignment from cfg.AGENTS")
    ]


def test_the_detector_lets_through_what_reads_at_use():
    for source in (
        "from backend._common import config as _config\n\n\ndef agents():\n    return _config.AGENTS\n",
        "from backend._common.config import get_config, HOME\n",
        "def agents():\n    from backend._common.config import AGENTS\n    return AGENTS\n",
        "from backend._common import config as _config\nREADER = lambda: _config.AGENTS\n",
        "from backend._common import config as _config\nif _config.AGENTS:\n    pass\n",
        "from backend.other import AGENTS\n",
    ):
        assert import_time_copies(source, _SERVED) == [], source
