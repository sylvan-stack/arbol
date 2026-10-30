
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/c32.py::run
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: Run.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/c32.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# async def run(home: ScenarioHome) -> None:
#     await check_driver_info(home)
#     identifier = await signed(home)
#     info = await home.json(["info"])
#     root = text("State directory", info.result["stateDirectory"])
#     codex = info.result["driver"] == "codex"
#     catalog = await home.json(["subscriptions", "models", identifier])
#     models = [object_("Catalog model", value) for value in array(catalog.result["models"], "map", "catalog.result.models")]
#     model = text("Model with low effort", get(find(models, lambda value: isinstance(value["efforts"], list)
#                                                    and includes(value["efforts"], "low")), "id")) if codex else "sonnet"
#     text_model = text("Text model", get(at(models, -1), "id")) if codex else "haiku"
#     system, request, extra = join(home.home, "system"), join(home.home, "request.json"), join(home.home, "extra")
#     mkdir(extra)
#     write_file(system, "Caller system prompt.")
#     write_file(request, text_of(stringify({"subscriptionId": identifier, "tools": "none", "history": [],
#                                            "input": {"role": "user", "text": "ready"}})))
#     args = ["run", "--state-dir", root, "--request", request, "--subscription", identifier, "--model", model, "--effort",
#             "low", "--system-prompt-file", system, "--cwd", home.home, "--add-dir", extra, "--add-dir=" + home.home,
#             "--tools", "all", "--chat-session", "cli-chat", "--run-id", "cli-run", "--output", "events", "--label",
#             "one=1", "--label=two=2", "ready"]
#     events = stream(await home.call(args))
#     equal("Run build matches info", events[0]["driverBuild"], info.result["build"])
#     equal("Repeated labels", events[0]["labels"], {"one": "1", "two": "2"})
#     received = await home.received()
#     inputs = [entry for entry in received if entry["stage"] == "input"]
#     input_ = at(inputs, -1)
#     if codex:
#         thread = find(await home.received(), lambda entry: entry["stage"] == "request"
#                       and object_("Thread request", entry["request"])["method"] == "thread/start")
#         parameters = object_("Thread params", object_("Thread request", thread["request"])["params"])
#         turn = object_("Turn params", object_("Turn request", input_["request"])["params"])
#         equal("Prompt file delivered", parameters["developerInstructions"], "Caller system prompt.")
#         equal("Model option delivered to thread", parameters["model"], model)
#         equal("Model option delivered to turn", turn["model"], model)
#         equal("Effort option delivered", turn["effort"], "low")
#         equal("Working directory delivered", parameters["cwd"], home.home)
#         equal("Repeated directories accepted in unrestricted run", parameters["sandbox"], "danger-full-access")
#         equal("Run identifier option delivered", events[0]["runId"], "cli-run")
#         equal("Chat session selects durable vendor conversation", parameters["ephemeral"] is True, False)
#         map_directory = join(root, "subscriptions", identifier, "chats")
#         mapped = [read_json(join(map_directory, file)) for file in readdir(map_directory) if file.endswith(".json")]
#         equal("Chat session option is mapped", [prop(entry, "chatSessionId") for entry in mapped], ["cli-chat"])
#     else:
#         arguments = input_["arguments"]
#         equal("Prompt file delivered", item(arguments, index_of(arguments, "--append-system-prompt") + 1),
#               "Caller system prompt.")
#         equal("Model option delivered", item(arguments, index_of(arguments, "--model") + 1), "sonnet")
#         equal("Effort option delivered", item(arguments, index_of(arguments, "--effort") + 1), "low")
#         equal("Repeated directories delivered", len([value for value in arguments if value == "--add-dir"]), 2)
#     stdin = home.start(["run", "--request", "-", "--subscription", identifier])
#     try:
#         stdin.send(parse(read_file(request)))
#         stream(await stdin.done)
#     finally:
#         await stdin.dispose()
#     output = await home.call(["run", "--subscription=" + identifier, "--model=" + text_model, "--tools=none",
#                               "--output=text", "ready"])
#     equal("Text exit", output["status"], 0)
#     equal("Plain text result", output["stdout"], "ready")
#     tier = stream(await home.call(["run", "--subscription", identifier, "--service-tier", "unsupported-tier", "ready"]),
#                   "failed")
#     equal("Unavailable tier is typed", prop(at(tier, -1), "error", "code"), "invalid_input")
#     for bad in (["unknown"], ["info", "--unknown"], ["info", "--state-dir"], ["run", "--unknown", "ready"],
#                 ["subscriptions", "sign-in", identifier, "--secret=fixture-secret"],
#                 ["subscriptions", "sign-in", identifier, "--key-file", request]):
#         reply = await home.call(bad)
#         equal("Invalid input exit", reply["status"], 1)
#         record: Any = parse(reply["stdout"])
#         equal("Invalid input code", prop(record, "error", "code"), "invalid_input")
#         check("Secret option not echoed", "fixture-secret" not in reply["stdout"], "no secret value", reply["stdout"])
#     # All subscription commands are executed in C1-C6/C41; this confirms their command frame here.
#     for command in (["subscriptions", "families"], ["subscriptions", "list"], ["subscriptions", "check", identifier],
#                     ["subscriptions", "usage", identifier], ["subscriptions", "models", identifier], ["runs", "list"],
#                     ["runs", "stop", "unknown"]):
#         equal("Command accepted: " + " ".join(command), (await home.call(command))["status"], 0)
#     imported = await home.json(["subscriptions", "import", "unknown", "--from", request])
#     check("Import frame accepted",
#           includes(["not_found", "invalid_input", *(["unsupported"] if codex else [])], prop(imported.result, "error", "code")),
#           "typed import refusal", imported.result)
#     for name in ("build-check", "live-check"):
#         refused = await home.json(["dev", name])
#         equal("Absent test account refused", refused.process["status"], 1)
#         equal("Absent test account code", prop(refused.result, "error", "code"), "not_found")
#     await home.json(["subscriptions", "create", "--family", identifier, "--label", "Test", "--id", "test-" + identifier])
#     test_id = "test-" + identifier
#     equal("Signed-out build check refuses", (await home.json(["dev", "build-check"])).process["status"], 1)
#     equal("Test sign-in", (await home.call(["subscriptions", "sign-in", test_id]))["status"], 0)
#     before = len([entry for entry in await home.received() if entry["stage"] == "input"])
#     build = await home.json(["dev", "build-check"])
#     equal("Build check passes", build.process["status"], 0)
#     equal("One real message", build.result["inferenceRequests"], 1)
#     equal("Exactly one stand-in prompt", len([entry for entry in await home.received() if entry["stage"] == "input"]),
#           before + 1)
#     record_file = join(root, "subscriptions", test_id, "record.json")
#     account = read_json(record_file)
#     assign(account, "lastUsage", JSObject(outcome="ok", fetchedAt=now_iso(),
#                                           windows=[JSObject(kind="weekly", label="Weekly", usedPercent=100)]))
#     write_file(record_file, text_of(stringify(account)))
#     for name in ("build-check", "live-check"):
#         refused = await home.json(["dev", name])
#         equal("Full account refused", prop(refused.result, "error", "code"), "rate_limited")
#     probe = await home.json(["dev", "probe"])
#     equal("Probe command passes", probe.process["status"], 0)
#     equal("Probe sends no prompt", probe.result["inferenceRequests"], 0)
#     equal("Probe makes no inference", len([entry for entry in await home.received() if entry["stage"] == "input"]),
#           before + 1)
#     active = home.start(["run", "--subscription", identifier, "--control", "ready"])
#     try:
#         active.send({"type": "stop"})
#         stream(await active.done, "cancelled")
#     finally:
#         await active.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END
