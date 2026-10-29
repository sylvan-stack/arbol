# Mid-tier source from conformance/scenarios/subscriptions.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c2
# async def run_c2(home: ScenarioHome) -> None:
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     vendor = find(await families(home), lambda value: value["auth"] == "vendor_login")
#     check("Vendor login family", vendor is not UNDEFINED, "a vendor-login family", vendor)
#     identifier = text("Family identifier", vendor["id"])
#     await home.part("success")
#     direct = await sign_in(home, identifier)
#     open_ = object_("Open URL", find(direct.lines, lambda value: object_("Step", value)["step"] == "open_url"))
#     check("Host list", isinstance(open_["allowedHosts"], list)
#           and includes(open_["allowedHosts"], hostname(text("URL", open_["url"]))), "URL hostname on allowedHosts", open_)
#     await home.part("by-code")
#     await sign_in(home, identifier, True)
#     await home.part("waiting")
#     first = home.start(["subscriptions", "sign-in", identifier])
#     try:
#         await first.step("open_url")
#         equal("Pending state", (await subscription(home, identifier))["state"], "signing_in")
#         changed = await home.json(["subscriptions", "update", identifier, "--label", "Changed while waiting"])
#         equal("No lock across sign-in", changed.process["status"], 0)
#         await home.part("success")
#         await sign_in(home, identifier)
#         replaced = await first.step("failed")
#         equal("Replacement error", object_("Error", replaced["error"])["code"], "in_use")
#         equal("Replaced exit", (await first.done)["status"], 1)
#     finally:
#         await first.dispose()
#     if identifier == "chatgpt":
#         created = await home.json(["subscriptions", "create", "--family", identifier, "--label", "Other login", "--id",
#                                    "login-other"])
#         equal("Create another login home", created.process["status"], 0)
#         await home.part("waiting")
#         machine = home.start(["subscriptions", "sign-in", identifier])
#         try:
#             await machine.step("open_url")
#             await home.part("success")
#             await sign_in(home, "login-other")
#             replaced = await machine.step("failed")
#             equal("Machine-wide replacement error", object_("Error", replaced["error"])["code"], "in_use")
#             equal("Machine-wide replaced exit", (await machine.done)["status"], 1)
#             equal("Replaced home signed out", (await subscription(home, identifier))["state"], "signed_out")
#         finally:
#             await machine.dispose()
#         await home.part("waiting")
#         device = home.start(["subscriptions", "sign-in", identifier, "--by-code"])
#         try:
#             step = await device.step("open_url")
#             text("Device code", step["userCode"])
#             await home.part("success")
#             await sign_in(home, "login-other")
#             equal("Device login is independent of machine login", (await subscription(home, identifier))["state"],
#                   "signing_in")
#             device.stop()
#             equal("Device cancellation exit", (await device.done)["status"], 2)
#         finally:
#             await device.dispose()
#     await home.part("waiting")
#     home.env["ARBOL_TEST_TIME_SCALE"] = "100"
#     pending = home.start(["subscriptions", "sign-in", identifier])
#     try:
#         await pending.step("open_url")
#         expired = await pending.step("failed", 6000)
#         equal("Timeout code", object_("Error", expired["error"])["code"], "limit_reached")
#         equal("Timeout exit", (await pending.done)["status"], 1)
#         equal("Timeout signed out", (await subscription(home, identifier))["state"], "signed_out")
#     finally:
#         await pending.dispose()
#     if any(family["id"] == "zai" for family in await families(home)):
#         await home.part("success")
#         gateway = await gateway_fixture(home)
#         service: str | None = None
#         try:
#             signed = await sign_in(home, "zai")
#             check("Command key needs no store step", not has_step(signed.lines, "store_secret"), "no store_secret",
#                   signed.lines)
#             settings: Any = parse(text_of(stringify(gateway.settings)))
#             del settings["subscriptions"]["zai"]["secret"]
#             await home.settings(settings)
#             prompted = home.start(["subscriptions", "sign-in", "zai"])
#             try:
#                 step = await prompted.step("store_secret")
#                 service = text("Service", object_("Keychain item", step["keychain"])["service"])
#                 check("Isolated Keychain service", test(r"\.[a-f0-9]{12}\Z", service), "hashed test-directory service",
#                       service)
#                 await store(service, "zai", KEY)
#                 await prompted.step("done")
#                 equal("Keychain sign-in exit", (await prompted.done)["status"], 0)
#             finally:
#                 await prompted.dispose()
#             out = await home.json(["subscriptions", "sign-out", "zai"])
#             equal("Key sign-out state", out.result["state"], "signed_out")
#             equal("Sign-out removes Keychain item",
#                   (await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["status"], 44)
#             await store(service, "zai", KEY)
#             prefilled = await sign_in(home, "zai")
#             check("Prefilled item skips prompt", not has_step(prefilled.lines, "store_secret"), "no store_secret",
#                   prefilled.lines)
#             gateway.mode = "rejected"
#             rejected = home.start(["subscriptions", "sign-in", "zai"])
#             try:
#                 failed = await rejected.step("failed")
#                 equal("Vendor rejects key", object_("Error", failed["error"])["code"], "credential_rejected")
#                 await rejected.done
#             finally:
#                 await rejected.dispose()
#             equal("Vendor-rejected key removed",
#                   (await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["status"], 44)
#             gateway.mode = "unavailable"
#             await store(service, "zai", KEY)
#             unreachable = await sign_in(home, "zai")
#             equal("Unchecked key has no checkedAt", object_("Subscription", unreachable.done["subscription"])["checkedAt"],
#                   UNDEFINED)
#             equal("Unreachable vendor keeps key",
#                   trim((await keychain(["find-generic-password", "-s", service, "-a", "zai", "-w"]))["stdout"]), KEY)
#         finally:
#             if service:
#                 await keychain(["delete-generic-password", "-s", service, "-a", "zai"])
#             await gateway.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c2

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c3
# async def run_c3(home: ScenarioHome) -> None:
#     family = find(await families(home), lambda value: value["auth"] == "key")
#     if family is UNDEFINED:
#         before = len(await home.received())
#         refused = await home.json(["subscriptions", "create", "--family", "openai", "--label", "Unsupported key", "--id",
#                                    "key-not-offered"])
#         equal("Unavailable key family exit", refused.process["status"], 1)
#         equal("Unavailable key family refusal",
#               object_("Unavailable key family error", refused.result["error"])["code"], "invalid_input")
#         equal("Unavailable key family starts no vendor", len(await home.received()), before)
#         return
#     identifier = text("Family id", family["id"])
#     pending = home.start(["subscriptions", "sign-in", identifier])
#     service: str | None = None
#     try:
#         step = await pending.step("store_secret")
#         entry = object_("Keychain item", step["keychain"])
#         service = text("Service", entry["service"])
#         check("Test service is isolated", test(r"\.[a-f0-9]{12}\Z", service), "hashed test-directory service", service)
#         equal("Item account", entry["account"], identifier)
#         await store(service, identifier, "fixture-key“ ”—")
#         failed = await pending.step("failed")
#         error = object_("Error", failed["error"])
#         equal("Validation error", error["code"], "invalid_input")
#         message = error["message"]
#         check("Offending characters named", isinstance(message, str) and "U+201C" in message and "U+00A0" in message
#               and "U+2014" not in message, "up to three invalid code points", error)
#         equal("Failed sign-in exit", (await pending.done)["status"], 1)
#         equal("Rejected key removed",
#               (await keychain(["find-generic-password", "-s", service, "-a", identifier, "-w"]))["status"], 44)
#         equal("Failed state", (await subscription(home, identifier))["state"], "signed_out")
#     finally:
#         await pending.dispose()
#         if service:
#             await keychain(["delete-generic-password", "-s", service, "-a", identifier])
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c3

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c4
# async def run_c4(home: ScenarioHome) -> None:
#     await check_subscription_rejection(home, True)
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c4

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c5
# async def run_c5(home: ScenarioHome) -> None:
#     root = await state(home)
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     identifier = await vendor_family(home)
#     for operation in ("sign-out", "remove"):
#         await home.part("success")
#         await sign_in(home, identifier)
#         await home.part("hold")
#         active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
#                              "answer"])
#         try:
#             deadline = now_monotonic() + 5000
#             while not any(prop(event, "type") == "started" for event in active.lines):
#                 check("Run starts", now_monotonic() < deadline, "within five seconds", active.lines)
#                 await delay(10)
#             refused = await home.json(["subscriptions", operation, identifier])
#             equal("Busy refusal", object_("Error", refused.result["error"])["code"], "in_use")
#             equal("Busy exit", refused.process["status"], 1)
#             equal("Refusal retains login", (await subscription(home, identifier))["state"], "signed_in")
#             forced = await home.call(["subscriptions", operation, identifier, "--force"])
#             equal("Forced exit", forced["status"], 0)
#             stream(await active.done, "cancelled")
#             equal("Run record removed", listing(join(root, "runs")), [])
#             equal("Run folder removed", listing(join(root, "tmp")), [])
#             seen = at([entry for entry in await home.received() if entry["stage"] == "input"], -1)
#             for pid in (prop(seen, "checks", "toolPid"), prop(seen, "checks", "backgroundPid")):
#                 if is_number(pid):
#                     equal("Tool and shell leftovers ended", await running(pid), False)
#             equal("Credential removed", (await subscription(home, identifier))["state"], "signed_out")
#             if operation == "remove":
#                 equal("Home removed", not exists(join(root, "subscriptions", identifier, "home")), True)
#         finally:
#             await active.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c5

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c6
# async def run_c6(home: ScenarioHome) -> None:
#     root = await state(home)
#     await home.part("waiting")
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     identifier = await vendor_family(home)
#     for signal in ("SIGTERM", "SIGKILL"):
#         pending = home.start(["subscriptions", "sign-in", identifier])
#         try:
#             await pending.step("open_url")
#             progress = read_json(join(root, "subscriptions", identifier, "sign-in.json"))
#             pending.stop(signal)
#             result = await pending.done
#             if signal == "SIGTERM":
#                 equal("Cancelled exit", result["status"], 2)
#                 check("Failed final step", has_step(pending.lines, "failed"), "failed step", pending.lines)
#             equal("Dead sign-in is signed out", (await subscription(home, identifier))["state"], "signed_out")
#             await home.json(["subscriptions", "update", identifier, "--label", "After cancellation"])
#             equal("Progress removed", not exists(join(root, "subscriptions", identifier, "sign-in.json")), True)
#             alive = await running(prop(progress, "tool", "pid"))
#             equal("Login child is gone", alive, False)
#         finally:
#             await pending.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c6

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c7
# async def run_c7(home: ScenarioHome) -> None:
#     await check_subscription_credentials(home, True)
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c7

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c8
# async def run_c8(home: ScenarioHome) -> None:
#     await check_subscription_environments(home, True)
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c8

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c39
# async def run_c39(home: ScenarioHome) -> None:
#     await home.part("success")
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     family = await vendor_family(home)
#     created = await home.json(["subscriptions", "create", "--family", family, "--label", "Second", "--id", "second"])
#     equal("Creation exit", created.process["status"], 0)
#     await sign_in(home, family)
#     await sign_in(home, "second")
#     homes = set_size(entry["checks"]["home"] for entry in await home.received() if entry["arguments"][0] != "--version")
#     equal("Distinct vendor homes", homes, 2)
#     await home.call(["subscriptions", "sign-out", family])
#     equal("First is out", (await subscription(home, family))["state"], "signed_out")
#     equal("Second still works", (await home.json(["subscriptions", "check", "second"])).result["state"], "signed_in")
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c39

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/subscriptions.py::run_c41
# async def run_c41(home: ScenarioHome) -> None:
#     offered = await families(home)
#     if any(value["id"] == "chatgpt" for value in offered):
#         await check_chatgpt_usage(home)
#         return
#     if [value["id"] for value in offered] == ["anthropic"]:
#         await home.part("success")
#         equal("Unsigned usage", (await home.json(["subscriptions", "usage", "anthropic"])).result["outcome"],
#               "needs_sign_in")
#         await sign_in(home, "anthropic")
#         account = object_("Vendor account", (await subscription(home, "anthropic"))["account"])
#         equal("Vendor plan", account["plan"], "fixture")
#         before = len(await home.received())
#         await home.call(["subscriptions", "list"])
#         equal("List does not poll", len(await home.received()), before)
#         unsupported = await home.json(["subscriptions", "usage", "anthropic"])
#         equal("Usage unsupported before run", unsupported.result["outcome"], "unsupported")
#         check_resources("unsupported.result.windows", unsupported.result["windows"])
#         equal("Tool catalog source", (await home.json(["subscriptions", "models", "anthropic"])).result["source"],
#               "tool")
#         await home.part("unavailable")
#         fallback = await home.json(["subscriptions", "models", "anthropic"])
#         equal("Unavailable catalog marked builtin", fallback.result["source"], "builtin")
#         check("Fallback is nonempty", isinstance(fallback.result["models"], list) and bool(fallback.result["models"]),
#               "Anthropic models", fallback.result)
#         for model in array(fallback.result["models"], "map", "models"):
#             check("No retired model", not text("Model id", object_("Model", model)["id"]).startswith("glm"),
#                   "Anthropic model", model)
#         await home.part("success")
#         out = await home.json(["subscriptions", "sign-out", "anthropic"])
#         equal("Account gone", out.result["account"], UNDEFINED)
#         equal("Cached usage gone", out.result["lastUsage"], UNDEFINED)
#         before = len(await home.received())
#         for command in ("check", "usage", "models", "sign-in"):
#             stale = await home.json(["subscriptions", command, "zai"])
#             equal("Retired route refused", stale.result["error"]["code"], "invalid_input")
#         equal("Retired requests never reach native tool", len(await home.received()), before)
#         return
#     await home.part("success")
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     gateway = await gateway_fixture(home)
#     try:
#         equal("Unsigned usage", (await home.json(["subscriptions", "usage", "zai"])).result["outcome"], "needs_sign_in")
#         await sign_in(home, "zai")
#         gateway.paths.clear()
#         await home.call(["subscriptions", "list"])
#         equal("List does not poll", gateway.paths, [])
#         catalog = await home.json(["subscriptions", "models", "zai"])
#         equal("Vendor source", catalog.result["source"], "vendor")
#         equal("Only models request", gateway.paths, ["/api/paas/v4/models"])
#         gateway.paths.clear()
#         usage = await home.json(["subscriptions", "usage", "zai"])
#         equal("Usage outcome", usage.result["outcome"], "ok")
#         equal("Only requested usage", gateway.paths, ["/api/monitor/usage/quota/limit"])
#         windows = usage.result["windows"]
#         check_resources("usage.result.windows", windows)
#         equal("Computed percentage", get(prop(windows, 0), "usedPercent"), 25)
#         equal("Unknown reset absent", get(prop(windows, 1), "resetsAt"), UNDEFINED)
#         equal("Unknown length absent", get(prop(windows, 2), "windowMinutes"), UNDEFINED)
#         equal("Good usage cached", (await subscription(home, "zai"))["lastUsage"], usage.result)
#         gateway.mode = "unavailable"
#         unavailable = await home.json(["subscriptions", "usage", "zai"])
#         equal("Unavailable usage", unavailable.result["outcome"], "unavailable")
#         check("Error redacted", KEY not in unavailable.process["stdout"], "no key", "output checked")
#         equal("Last good report preserved", (await subscription(home, "zai"))["lastUsage"], usage.result)
#         fallback = await home.json(["subscriptions", "models", "zai"])
#         equal("Fallback source", fallback.result["source"], "builtin")
#         equal("Own family only", fallback.result["models"], [record(id="fixture-fallback", label="fixture-fallback")])
#         await sign_in(home, "anthropic")
#         account = object_("Vendor account", (await subscription(home, "anthropic"))["account"])
#         equal("Vendor plan", account["plan"], "fixture")
#         equal("Anthropic usage unsupported before run",
#               (await home.json(["subscriptions", "usage", "anthropic"])).result["outcome"], "unsupported")
#         equal("Tool catalog source", (await home.json(["subscriptions", "models", "anthropic"])).result["source"], "tool")
#         await home.part("unavailable")
#         await home.settings(gateway.settings)
#         tool_fallback = await home.json(["subscriptions", "models", "anthropic"])
#         equal("Tool fallback marked builtin", tool_fallback.result["source"], "builtin")
#         tool_models = tool_fallback.result["models"]
#         check("Tool fallback is its own family", isinstance(tool_models, list) and all(
#             not text("Model", object_("Model entry", value)["id"]).startswith("fixture-") for value in tool_models),
#             "Anthropic names", tool_models)
#         await home.part("success")
#         await home.settings(gateway.settings)
#         out = await home.json(["subscriptions", "sign-out", "anthropic"])
#         equal("Account gone", out.result["account"], UNDEFINED)
#         equal("Cached usage gone", out.result["lastUsage"], UNDEFINED)
#         gateway.mode = "rejected"
#         equal("Rejected usage", (await home.json(["subscriptions", "usage", "zai"])).result["outcome"], "needs_sign_in")
#         equal("Rejected key needs attention", (await subscription(home, "zai"))["state"], "needs_attention")
#     finally:
#         await gateway.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/subscriptions.py::run_c41

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/subscriptions.py:26
# from ..js import (
#     UNDEFINED,
#     JSArray,
#     JSObject,
#     get,
#     is_number,
#     join,
#     loose_includes,
#     parse,
#     stringify,
#     text_of,
#     trim,
#     well_formed,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/subscriptions.py:26

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/subscriptions.py:41
# from .support import (
#     at,
#     delay,
#     exists,
#     find,
#     includes,
#     item,
#     mkdir,
#     now_monotonic,
#     now_ms,
#     null_check,
#     read_file,
#     read_json,
#     readdir,
#     record,
#     test,
#     write_file,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/subscriptions.py:41

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
