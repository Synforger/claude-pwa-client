"""The event loop waits on no command and no walk of the process table.

One slow tmux call made from a coroutine stops every screen, terminal and message at once. So a coroutine hands such a
function to a thread (`asyncio.to_thread(function, ...)`) instead of calling it. This reads the source: it follows the
plain functions a coroutine calls, through imports, to the calls that start a command or walk the process table. A
function that is only handed over is not a call, and a call inside a lambda or a nested function is the thread's.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

WAITS = frozenset({
    "subprocess.run", "subprocess.check_output", "subprocess.call", "subprocess.check_call",
    "os.system", "os.popen",
    "psutil.process_iter", "psutil.pids", "psutil.net_connections",
    "backend.terminal.pty_discover._find_claude_descendant_info",
    "backend.terminal.pty_discover.runs_inside_another_claude",
    "backend.sleep.sleep_sensors.process_tree",
})
# The coroutines that may wait, and why.
MAY_WAIT = {
    "backend.main.lifespan": "runs before the backend takes its first request",
}

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := _dotted(node.value)):
        return f"{base}.{node.attr}"
    return None


def _own_nodes(function: _Function) -> Iterator[ast.AST]:
    waiting = list(function.body)
    while waiting:
        node = waiting.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        waiting.extend(ast.iter_child_nodes(node))


def _read_source() -> tuple[dict[str, tuple[str, _Function]], dict[str, dict[str, str]]]:
    functions: dict[str, tuple[str, _Function]] = {}
    imported: dict[str, dict[str, str]] = {}

    def visit(node: ast.AST, module: str, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{prefix}.{child.name}"
                if not isinstance(child, ast.ClassDef):
                    functions[inner] = (module, child)
            visit(child, module, inner)

    for path in BACKEND_ROOT.rglob("*.py"):
        parts = path.relative_to(BACKEND_ROOT.parent).with_suffix("").parts
        if "tests" in parts:
            continue
        module = ".".join(parts).removesuffix(".__init__")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = imported.setdefault(module, {})
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    names[alias.asname or head] = alias.name if alias.asname else head
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        visit(tree, module, module)
    return functions, imported


def _calls_of(name: str, functions: dict[str, tuple[str, _Function]],
              imported: dict[str, dict[str, str]]) -> list[str]:
    module, function = functions[name]
    called = []
    for node in _own_nodes(function):
        if not isinstance(node, ast.Call) or not (written := _dotted(node.func)):
            continue
        head, _, rest = written.partition(".")
        here = [f"{name}.{written}", f"{module}.{written}"]
        if head == "self":
            here.append(f"{name.rsplit('.', 1)[0]}.{rest}")
        target = next((known for known in here if known in functions), None)
        if target is None:
            target = written
            if head in imported[module]:
                target = imported[module][head] + (f".{rest}" if rest else "")
            # a name that a module passes on from where it is defined
            while target not in functions and target not in WAITS and "." in target:
                owner, last = target.rsplit(".", 1)
                passed_on = imported.get(owner, {}).get(last)
                if passed_on is None or passed_on == target:
                    break
                target = passed_on
        called.append(target)
    return called


def test_no_coroutine_waits_on_a_command_or_the_process_table():
    functions, imported = _read_source()
    assert WAITS - functions.keys() <= {wait for wait in WAITS if not wait.startswith("backend.")}, "a name moved"
    called = {name: _calls_of(name, functions, imported) for name in functions}
    is_plain = {name: isinstance(node, ast.FunctionDef) for name, (_, node) in functions.items()}
    waiting = set(WAITS)
    grew = True
    while grew:
        grew = False
        for name, targets in called.items():
            if is_plain[name] and name not in waiting and waiting.intersection(targets):
                waiting.add(name)
                grew = True
    found = sorted(f"{name} calls {target}" for name, targets in called.items()
                   if not is_plain[name] and name not in MAY_WAIT
                   for target in waiting.intersection(targets))
    assert found == [], "hand these to a thread (asyncio.to_thread):\n" + "\n".join(found)
