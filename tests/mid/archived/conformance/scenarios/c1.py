# Mid-tier source from conformance/scenarios/c1.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/c1.py::run
# async def run(home: ScenarioHome) -> None:
#     family_reply = await home.call(["subscriptions", "families"])
#     equal("Families exit status", family_reply["status"], 0)
#     families = parse(family_reply["stdout"])
#     check("Families array", isinstance(families, list) and len(families) > 0, "a nonempty Family array", families)
#
#     async def listed() -> JSArray:
#         reply = await home.call(["subscriptions", "list"])
#         equal("List exit status", reply["status"], 0)
#         parsed = parse(reply["stdout"])
#         check("Subscription array", isinstance(parsed, list), "a Subscription array", parsed)
#         return JSArray(object_("Subscription", value) for value in parsed)
#
#     initial = await listed()
#     equal("One default Subscription per family", len(initial), len(families))
#     for value in families:
#         family = object_("Family", value)
#         identifier = text("Family identifier", family["id"])
#         object_("Family settings schema", family["settings"])
#         builtin = find_by(initial, "id", identifier)
#         check("Default Subscription is named after its family", isinstance(builtin, dict), identifier, initial)
#         equal("Default family", builtin["family"], identifier)
#         equal("Default auth", builtin["auth"], family["auth"])
#         equal("Default state", builtin["state"], "signed_out")
#         object_("Subscription settings", builtin["settings"])
#         created = await home.json(["subscriptions", "create", "--family", identifier, "--label", "Another account"])
#         equal("Create exit status", created.process["status"], 0)
#         equal("Automatic name", created.result["id"], f"{identifier}-2")
#         equal("New account family", created.result["family"], identifier)
#         equal("New account auth", created.result["auth"], family["auth"])
#         equal("New account state", created.result["state"], "signed_out")
#         equal("New account label", created.result["label"], "Another account")
#         text("Creation date", created.result["createdAt"])
#         equal("Create is stored", find_by(await listed(), "id", created.result["id"]),
#               created.result)
#         changed = await home.json(["subscriptions", "update", f"{identifier}-2", "--label", "Renamed account"])
#         equal("Update exit status", changed.process["status"], 0)
#         equal("Relabel changes only label and update date",
#               JSObject({**changed.result, "label": created.result["label"], "updatedAt": created.result["updatedAt"]}),
#               created.result)
#         equal("Update is stored", find_by(await listed(), "id", changed.result["id"]),
#               changed.result)
#         unchanged = await home.json(["subscriptions", "update", f"{identifier}-2"])
#         equal("Omitted fields are preserved", unchanged.result, changed.result)
#         duplicate = await home.json(["subscriptions", "create", "--family", identifier, "--label", "Duplicate", "--id",
#                                      f"{identifier}-2"])
#         equal("Duplicate fails", duplicate.process["status"], 1)
#         equal("Duplicate typed error", object_("Duplicate error", duplicate.result["error"])["code"], "in_use")
#         explicit = await home.json(["subscriptions", "create", "--family", identifier, "--label", "Named account", "--id",
#                                     f"{identifier}-work"])
#         equal("Explicit creation succeeds", explicit.process["status"], 0)
#         equal("Explicit identifier", explicit.result["id"], f"{identifier}-work")
#         removed = await home.call(["subscriptions", "remove", f"{identifier}-work"])
#         equal("Removal exit status", removed["status"], 0)
#         equal("Removal returns no document", removed["stdout"], "")
#         equal("Removed account is absent", any(entry["id"] == f"{identifier}-work" for entry in await listed()), False)
#     equal("Local commands never start the vendor tool", await home.received(), [])
# TEST-TIER-DISABLED-END conformance/scenarios/c1.py::run

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c1.py:5
# from ..check import check, equal, object_, text
# TEST-TIER-IMPORTS-END conformance/scenarios/c1.py:5

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c1.py:7
# from ..js import JSArray, JSObject, parse
# TEST-TIER-IMPORTS-END conformance/scenarios/c1.py:7

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c1.py:8
# from .support import find_by
# TEST-TIER-IMPORTS-END conformance/scenarios/c1.py:8

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
