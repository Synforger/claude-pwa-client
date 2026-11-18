"""A stand-in for the guard's commands, run by the tickets' tests as a subprocess: `fake_guard.py <mode> <rules file> <the
words the backend passed>`. What it answers comes from the rules file (`rules[<mode>]`: `status`, `stdout`, `stderr`,
`refuse_containing` = a text that makes it exit 1, `refuse_sessions` = sessions whose `--to` makes it exit 1). Every
call is logged to `rules["log"]` as one JSON line with the flags it got."""
import json
import sys

mode, rules_path, *words = sys.argv[1:]
with open(rules_path, encoding="utf-8") as file:
    rules = json.load(file)
rule = rules.get(mode, {})
flags, index = {}, 0
while index < len(words):
    if words[index].startswith("--") and index + 1 < len(words) and not words[index + 1].startswith("--"):
        flags[words[index]] = words[index + 1]
        index += 2
    else:
        flags[words[index]] = None
        index += 1
text = ""
if "--text" in flags:
    with open(flags["--text"], encoding="utf-8") as file:
        text = file.read()
with open(rules["log"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"mode": mode, "flags": flags, "text": text}) + "\n")
status = rule.get("status", 0)
if rule.get("refuse_containing") and rule["refuse_containing"] in text:
    status = 1
if flags.get("--to") in rule.get("refuse_sessions", []):
    status = 1
if rule.get("stdout"):
    print(rule["stdout"])
if rule.get("stderr"):
    print(rule["stderr"], file=sys.stderr)
sys.exit(status)
