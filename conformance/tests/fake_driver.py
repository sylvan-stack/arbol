"""A synthetic Driver for testing the runner itself, not a vendor stand-in."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

args = sys.argv[1:]
mode = args.pop(0)[len("--fixture="):] if args and args[0].startswith("--fixture=") else "ok"
home = os.environ["HOME"]
if args[:2] == ["dev", "stand-in"]:
    folder = args[2]
    with open(os.path.join(folder, "scenario"), encoding="utf-8") as stream:
        scenario, part = stream.read().split()
    version = "0.159.1" if part == "old" else "0.159.2"
    with open(os.path.join(folder, "received.jsonl"), "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"scenario": scenario, "part": part, "arguments": args[4:],
                                 "environment": list(os.environ), "workingDirectory": os.getcwd(), "checks": {},
                                 "toolVersion": version}, separators=(",", ":")) + "\n")
    sys.stdout.write(version + "\n")
elif mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(1)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(home, "pids.json"), "w", encoding="utf-8") as stream:
        json.dump([os.getpid(), child.pid], stream)
    while True:
        child.wait()
elif args[:1] == ["subscriptions"]:
    # Synthetic local account protocol, deliberately independent of either Driver.
    file = os.path.join(home, "synthetic-subscriptions.json")
    try:
        with open(file, encoding="utf-8") as stream:
            subscriptions = json.load(stream)
    except FileNotFoundError:
        subscriptions = [{"id": "chatgpt", "family": "chatgpt", "label": "ChatGPT", "auth": "vendor_login",
                          "state": "signed_out", "settings": {}, "createdAt": "2026-10-06T00:00:00Z",
                          "updatedAt": "2026-10-06T00:00:00Z"}]

    def option(key: str) -> str:
        return args[args.index(f"--{key}") + 1] if f"--{key}" in args else args[0]

    def save() -> None:
        with open(file, "w", encoding="utf-8") as stream:
            json.dump(subscriptions, stream)

    status = 0
    result: object = None
    command = args[1]
    if command == "families":
        result = [{"id": "chatgpt", "auth": "vendor_login", "settings": {}}]
    elif command == "list":
        result = subscriptions
    elif command == "create":
        identifier = option("id") if "--id" in args else "chatgpt-2"
        if any(entry["id"] == identifier for entry in subscriptions):
            status, result = 1, {"error": {"code": "in_use", "message": "in_use", "retryable": False}}
        else:
            result = {**subscriptions[0], "id": identifier, "label": option("label")}
            subscriptions.append(result)
            save()
    elif command == "update":
        updated = next(entry for entry in subscriptions if entry["id"] == args[2])
        if "--label" in args:
            updated["label"] = option("label")
        result = updated
        save()
    elif command in ("check", "models"):
        status, result = 1, {"error": {"code": "not_signed_in", "message": "not_signed_in", "retryable": False}}
    elif command == "remove":
        subscriptions = [entry for entry in subscriptions if entry["id"] != args[2]]
        save()
        sys.exit(0)
    elif command == "usage":
        result = {"outcome": "needs_sign_in", "windows": [],
                  "fetchedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    sys.exit(status)
else:
    settings_file = os.path.join(home, ".arbol", "arbol-codex-driver.json")
    with open(settings_file, encoding="utf-8") as stream:
        tool_path = json.load(stream)["toolPath"]
    if "--state-dir" in args:
        index = args.index("--state-dir")
        state_directory = args[index + 1]
        del args[index:index + 2]
    else:
        state_directory = os.path.join(home, "Library", "Application Support", "Arbol", "drivers", "codex")
    os.makedirs(state_directory, exist_ok=True)
    tool: dict[str, object] = {"name": "codex", "supported": False, "oldestSupported": "0.159.2"}
    if os.path.exists(tool_path):
        tool["path"] = tool_path
        tool["version"] = subprocess.run([tool_path, "--version"], capture_output=True, text=True,
                                         check=True).stdout.strip()
        tool["supported"] = tool["version"] == tool["oldestSupported"]
    if args[:1] == ["info"]:
        if mode == "bad-json":
            sys.stdout.write("{broken\n")
            sys.exit(0)
        result = {"driver": "codex", "version": "4.2.1", "build": "a3", "contract": 99 if mode == "wrong" else 1,
                  "stateDirectory": state_directory, "settingsFile": settings_file, "tool": tool}
        status = 1 if mode == "wrong-exit" else 0
    else:
        code = "tool_unsupported" if "path" in tool else "tool_missing"
        detail = {"neededVersion": tool["oldestSupported"], **({"toolVersion": tool["version"]} if "version" in tool else {})}
        result = {"error": {"code": code, "retryable": False,
                            "message": f"codex {tool.get('version', 'not found')}; needed {tool['oldestSupported']}",
                            "detail": detail}}
        status = 1
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    sys.exit(status)
