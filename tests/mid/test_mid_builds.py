"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import test_builds as _support
# from test_builds import (
#     ARCHIVE_CACHE,
#     Any,
#     BUILD,
#     BUILDER,
#     Builds,
#     CHECK,
#     CHECKER,
#     Callable,
#     ENTRY,
#     ENV,
#     EXECVE,
#     Fixture,
#     HOLDER,
#     INSTALLER,
#     Install,
#     Launchers,
#     Locking,
#     PROGRAM,
#     PYTHON,
#     Path,
#     PruningRoots,
#     ROOT,
#     Result,
#     RootComponents,
#     Roots,
#     SIGNALS,
#     StartRecords,
#     TOOL,
#     TRUNK_PROGRAM,
#     TrunkLauncher,
#     Trunks,
#     WRITER,
#     alive,
#     ast,
#     document,
#     finish,
#     first_line,
#     json,
#     milliseconds,
#     mode,
#     os,
#     root_record,
#     run_tool,
#     select,
#     shutil,
#     stat,
#     subprocess,
#     sys,
#     tempfile,
#     time,
#     top_level_names,
#     unittest,
#     wait_until,
#     waiting,
#     write_launcher,
#     write_root,
# )


# class Builds(_support.Builds):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_two_builds
#     def test_builds_two_builds(self) -> None:
#         """builds.two-builds runs the newest Build and an explicitly named older Build."""
#         f = Fixture(self)
#         self.assertEqual(f.build()["build"], "1")
#         self.assertEqual(f.build()["build"], "2")
#         self.assertEqual(document(f.launch())["build"], "2")
#         self.assertEqual(document(f.launch("-v", "1"))["build"], "1")
#         self.assertEqual([[r["build"], r["default"]] for r in document(f.call("list", f.component))],
#                          [["2", True], ["1", False]])
#         self.assertEqual(document(f.call("show", f.component))["build"], "2")
#         self.assertEqual(document(f.call("show", f"{f.component}@1"))["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_two_builds

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_numbering
#     def test_builds_numbering(self) -> None:
#         """builds.numbering uses hexadecimal, arbitrary precision, independent components and damaged directories."""
#         f = Fixture(self)
#         for number in range(1, 18):
#             self.assertEqual(reserve(f.registry, f.component)[1], format(number, "x"))
#         self.assertEqual(reserve(f.registry, "other")[1], "1")
#         os.mkdir(f.path("ffffffffffffffff"))
#         self.assertEqual(reserve(f.registry, f.component)[1], "10000000000000000")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_numbering

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_concurrent
#     def test_builds_concurrent(self) -> None:
#         """builds.concurrent invocations never reserve the same number."""
#         f = Fixture(self)
#         children = [f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
#                     for _ in range(4)]
#         numbers = []
#         for child in children:
#             output, errors = child.communicate(timeout=120)
#             self.assertEqual(child.returncode, 0, output + errors)
#             numbers.append(json.loads(output)["build"])
#         self.assertEqual(sorted(numbers), ["1", "2", "3", "4"])
#         self.assertEqual(document(f.launch())["build"], "4")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_concurrent

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_concurrent_mutations
#     def test_builds_concurrent_mutations(self) -> None:
#         """builds.concurrent-mutations serialises record writers and excludes killed reservations from later changes."""
#         f = Fixture(self)
#         f.build()
#         folder = f.path()
#         worker = os.path.join(f.home, "writer.py")
#         Path(worker).write_text(WRITER, encoding="utf-8")
#         Path(folder, "counter.json").write_text("0")
#         writers = [subprocess.Popen([PYTHON, "-I", worker, folder], env=ENV) for _ in range(4)]
#         for writer in writers:
#             self.addCleanup(finish, writer)
#         self.assertTrue(all(writer.wait(timeout=120) == 0 for writer in writers))
#         self.assertEqual(Path(folder, "counter.json").read_text(), "80")
#         Path(worker).write_text(HOLDER, encoding="utf-8")
#         holder = subprocess.Popen([PYTHON, "-I", worker, folder], env=ENV, stdout=subprocess.PIPE)
#         self.addCleanup(finish, holder)
#         self.assertEqual(first_line(holder), b"held\n")
#         holder.kill()
#         holder.wait()
#         self.assertEqual(f.call("withdraw", f"{f.component}@1", "--reason", "after killed writer").returncode, 0)
#         self.assertEqual(f.launch("-v", "1").returncode, 0)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_concurrent_mutations

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_concurrent_prune
#     def test_builds_concurrent_prune(self) -> None:
#         """builds.concurrent-prune and withdrawal preserve a complete serial outcome."""
#         f = Fixture(self)
#         for _ in range(3):
#             f.build()
#         prune = f.spawn("prune", f.component, "--keep", "1", "--registry-dir", f.registry)
#         withdraw = f.spawn("withdraw", f"{f.component}@3", "--reason", "concurrent withdrawal",
#                            "--registry-dir", f.registry)
#         outputs = []
#         for child in (prune, withdraw):
#             output, errors = child.communicate(timeout=120)
#             self.assertEqual(child.returncode, 0, output + errors)
#             outputs.append(json.loads(output))
#         if "2" in outputs[0]["pruned"]:
#             self.assertEqual(f.launch().returncode, 1)
#         else:
#             self.assertEqual(outputs[0]["pruned"], ["1"])
#             self.assertEqual(document(f.launch())["build"], "2")
#         self.assertEqual(f.launch("-v", "3").returncode, 0)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_concurrent_prune

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_source
#     def test_builds_source(self) -> None:
#         """builds.source records package, repository, branch, commit and uncommitted changes."""
#         f = Fixture(self)
#         commit = f.git("rev-parse", "HEAD")
#         first = f.build()
#         self.assertEqual(first["packageVersion"], "1.2.3")
#         self.assertEqual(first["source"], {"repository": f.repo, "branch": "main", "commit": commit,
#                                            "uncommittedChanges": False})
#         Path(f.repo, "uncommitted.txt").write_text("new")
#         self.assertIs(f.build()["source"]["uncommittedChanges"], True)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_source

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_folder_alone
#     def test_builds_folder_alone(self) -> None:
#         """builds.folder-alone launches a relocated Build after its source and the tool are out of reach."""
#         f = Fixture(self)
#         f.build()
#         moved = os.path.join(f.home, "moved")
#         shutil.copytree(f.path("1"), os.path.join(moved, f.component, "1"), symlinks=True)
#         launcher = Path(f.bin, f.component)
#         text = launcher.read_text(encoding="utf-8")
#         # The launcher holds the standard library only; changing its registry is sufficient.
#         self.assertNotIn("from arbol_builds", text)
#         self.assertNotIn("import arbol_builds", text)
#         launcher.write_text(text.replace(repr(f.registry), repr(moved)), encoding="utf-8")
#         shutil.rmtree(f.repo)
#         shutil.rmtree(f.registry)
#         result = f.launch()
#         self.assertEqual(result.returncode, 0, result.stderr)
#         self.assertEqual(document(result)["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_folder_alone

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_failed_check
#     def test_builds_failed_check(self) -> None:
#         """builds.failed-check keeps its record and log, consumes its number, preserves the default, runs only when named."""
#         f = Fixture(self)
#         f.build()
#         f.configure(checks=[{"name": "unavailable-account", "kind": "live",
#                              "command": "echo account-signed-out >&2; exit 1"}])
#         result = f.call("build", f.component, "--repo", f.repo)
#         self.assertEqual(result.returncode, 1)
#         record = document(result)
#         self.assertEqual([record["status"], record["build"], record["failure"]["name"]],
#                          ["failed", "2", "unavailable-account"])
#         self.assertEqual(record["checks"], [{"name": "unavailable-account", "passed": False}])
#         self.assertIn("account-signed-out", Path(f.path("2/build.log")).read_text())
#         self.assertTrue(Path(f.path("2/build.log")).read_text().endswith(
#             "\nFAILED check unavailable-account: Check failed; see build.log.\n"))
#         self.assertEqual(document(f.launch())["build"], "1")
#         named = f.launch("-v", "2", "text")
#         self.assertEqual(named.returncode, 0, named.stdout)
#         self.assertEqual([document(named)["build"], document(named)["args"]], ["2", ["text"]])
#         self.assertEqual(named.stderr,
#                          f"{f.component}@2 is failed: check unavailable-account: Check failed; see build.log.\n".encode())
#         f.configure(checks=[{"name": "sample-check", "command": CHECK}])
#         self.assertEqual(f.build()["build"], "3")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_failed_check

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_failed_command
#     def test_builds_failed_command(self) -> None:
#         """builds.failed-command and missing entry cannot become working."""
#         f = Fixture(self)
#         f.configure(build=["echo compile-failed; exit 7"])
#         command = document(f.call("build", f.component, "--repo", f.repo))
#         self.assertEqual([command["status"], command["failure"]["stage"], command["checks"]], ["failed", "build", []])
#         self.assertRegex(Path(f.path("1/build.log")).read_text(), r"compile-failed[\s\S]*Exit: 7")
#         f.configure(build=["true"])
#         entry = document(f.call("build", f.component, "--repo", f.repo))
#         self.assertEqual([entry["status"], entry["failure"]["stage"]], ["failed", "entry"])
#         f.configure(build=[BUILD], checks=[{"name": "removed-entry", "command": 'rm "$ARBOL_BUILD_DIR/program.py"'}])
#         self.assertEqual(document(f.call("build", f.component, "--repo", f.repo))["status"], "failed")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_failed_command

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_description
#     def test_builds_description(self) -> None:
#         """builds.description passes folder and number to ordered commands and checks against the building entry."""
#         f = Fixture(self)
#         f.configure(build=[BUILD, 'echo second > "$ARBOL_BUILD_DIR/order"'], checks=[
#             {"name": "sample-check", "command": CHECK},
#             {"name": "ordered-check", "command": 'test "$(cat "$ARBOL_BUILD_DIR/order")" = second'},
#         ], contract=1, dataFormat=2)
#         record = f.build()
#         self.assertEqual([record["contract"], record["dataFormat"]], [1, 2])
#         folder = f.path("1")
#         for name in ("build", "check"):
#             self.assertEqual(json.loads(Path(folder, f"{name}-environment.json").read_text()),
#                              {"number": "1", "dir": folder, "cwd": f.repo})
#         self.assertEqual(record["checks"], [{"name": "sample-check", "passed": True},
#                                             {"name": "ordered-check", "passed": True}])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_description

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_driver_checks
#     def test_builds_driver_checks(self) -> None:
#         """builds.driver-checks requires unit, contract and live checks and fails when the live check fails."""
#         f = Fixture(self, "arbol-claude-driver")
#         self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1)
#         self.assertFalse(os.path.exists(f.registry))
#         f.configure(contract=1, dataFormat=1, checks=[
#             {"name": "unit", "kind": "unit", "command": CHECK},
#             {"name": "contract", "kind": "contract", "command": CHECK},
#             {"name": "one-real-message", "kind": "live", "command": "echo synthetic-live-failure; exit 1"},
#         ])
#         result = f.call("build", f.component, "--repo", f.repo)
#         self.assertEqual([result.returncode, document(result)["status"], document(result)["failure"]["name"]],
#                          [1, "failed", "one-real-message"])
#         f.configure(checks=[{"name": "unit", "kind": "unit", "command": CHECK},
#                             {"name": "contract", "kind": "contract", "command": CHECK},
#                             {"name": "live-stand-in", "kind": "live", "command": CHECK}])
#         self.assertEqual(f.build()["status"], "working")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_driver_checks

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_withdraw
#     def test_builds_withdraw(self) -> None:
#         """builds.withdraw changes the computed default and warns only for an explicit withdrawn Build."""
#         f = Fixture(self)
#         f.build()
#         f.build()
#         result = f.call("withdraw", f"{f.component}@2", "--reason", "Bad result on Tuesday")
#         self.assertEqual([result.returncode, document(result)["status"]], [0, "withdrawn"])
#         self.assertEqual(document(f.launch())["build"], "1")
#         named = f.launch("-v", "2")
#         self.assertEqual([named.returncode, document(named)["build"]], [0, "2"])
#         self.assertIn(b"withdrawn: Bad result on Tuesday", named.stderr)
#         self.assertEqual(f.call("withdraw", f"{f.component}@2", "--reason", "again").returncode, 1)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_withdraw

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_launch_refusal
#     def test_builds_launch_refusal(self) -> None:
#         """builds.launch-refusal lists runnable Builds and consumes -v only in first position."""
#         f = Fixture(self)
#         f.build()
#         f.configure(build=["false"])
#         f.call("build", f.component, "--repo", f.repo)
#         for args in (["-v", "2"], ["-v", "3"], ["-v"], ["-v", "01"], ["-v", "A"]):
#             result = f.launch(*args)
#             self.assertEqual([result.returncode, document(result)["error"]["available"]], [1, ["1"]], args)
#             self.assertEqual(document(result)["error"]["code"], "build_unavailable")
#         self.assertEqual(document(f.launch("run", "-v", "2", "", "a b", "a'b"))["args"],
#                          ["run", "-v", "2", "", "a b", "a'b"])
#         self.assertEqual(document(f.launch("a", "b", "-v", "1"))["args"], ["a", "b", "-v", "1"])
#         path = Path(f.path("2/build.json"))
#         building = json.loads(path.read_text())
#         building["status"] = "building"
#         path.write_text(json.dumps(building))
#         self.assertEqual(f.launch("-v", "2").returncode, 1)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_launch_refusal

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_streams
#     def test_builds_streams(self) -> None:
#         """builds.streams preserves standard input, output, errors, working folder, environment and exit status."""
#         f = Fixture(self)
#         f.build()
#         data = "ñ\u0000data\nline two\n".encode()
#         echo = f.launch("--echo", data=data)
#         self.assertEqual([echo.stdout, echo.stderr, echo.returncode], [data, b"diagnostic\n", 0])
#         result = document(f.launch("text", marker="custom"))
#         self.assertEqual([result["cwd"], result["marker"]], [f.home, "custom"])
#         for code in (0, 1, 2, 7, 143):
#             self.assertEqual(f.launch("--exit", str(code)).returncode, code)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_streams

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_signals
#     def test_builds_signals(self) -> None:
#         """builds.signals replaces the launcher process and passes handled and native signals directly."""
#         f = Fixture(self)
#         f.build()
#         for number in (signal.SIGINT, signal.SIGTERM):
#             child = subprocess.Popen([os.path.join(f.bin, f.component), "--wait"], env=f.env(), stdout=subprocess.PIPE)
#             self.addCleanup(finish, child)
#             ready = json.loads(first_line(child))
#             self.assertEqual(ready["pid"], child.pid)
#             child.send_signal(number)
#             code = child.wait(timeout=10)
#             self.assertEqual(code, 2 if number == signal.SIGINT else -signal.SIGTERM)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_signals

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_damaged_record
#     def test_builds_damaged_record(self) -> None:
#         """builds.damaged-record isolates malformed, missing, mismatched and nonexecutable entries."""
#         f = Fixture(self)
#         f.build()
#         f.build()
#         path = Path(f.path("2/build.json"))
#         original = path.read_text()
#         for bad in ("{", "{}", original.replace('"build": "2"', '"build": "9"'),
#                     original.replace('"entry": "program.py"', '"entry": "../../outside"'),
#                     original.replace('"dataFormat": 1', '"dataFormat": NaN'),
#                     original.replace('"dataFormat": 1', '"dataFormat": 1' + "0" * 399),
#                     json.dumps({**json.loads(original), "startedAt": "\uff12\uff10\uff12\uff16-10-15T00:00:00.000Z"}),
#                     json.dumps({**json.loads(original), "startedAt": "2026-10-15T24:00:00.500Z"}),
#                     json.dumps({**json.loads(original), "startedAt": "+275761-01-01T00:00:00.000Z"})):
#             path.write_text(bad)
#             self.assertEqual(document(f.launch())["build"], "1")
#             self.assertEqual(len(document(f.call("list"))), 1)
#         # Valid, as JavaScript reads it: a number longer than Python reads, and the latest time Date.parse accepts.
#         path.write_text(original.rstrip().rstrip("}") + ', "note": 1' + "0" * 5000 + "}")
#         self.assertEqual(document(f.launch("-v", "99"))["error"]["available"], ["2", "1"])
#         path.write_text(json.dumps({**json.loads(original), "startedAt": "+275760-09-13T00:00:00.000Z"}))
#         self.assertEqual(document(f.launch())["build"], "2")
#         path.write_text(original.replace('"entry": "program.py"', '"entry": "program.py\\u0000"'))
#         self.assertEqual(document(f.launch())["build"], "1")
#         self.assertEqual(document(f.launch("-v", "2"))["error"]["available"], ["1"])
#         self.assertEqual([record["default"] for record in document(f.call("list"))], [False, True])
#         path.unlink()
#         self.assertEqual(document(f.launch())["build"], "1")
#         path.write_text(original)
#         os.chmod(f.path("2/program.py"), 0o600)
#         self.assertEqual(document(f.launch())["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_damaged_record

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_prune
#     def test_builds_prune(self) -> None:
#         """builds.prune retains records, logs, default and withdrawn Builds and never reuses a number."""
#         f = Fixture(self)
#         for _ in range(4):
#             f.build()
#         f.call("withdraw", f"{f.component}@2", "--reason", "keep for diagnosis")
#         result = f.call("prune", f.component, "--keep", "1")
#         self.assertEqual([result.returncode, document(result)["pruned"]], [0, ["3", "1"]])
#         for number in ("1", "3"):
#             folder = f.path(number)
#             self.assertTrue(json.loads(Path(folder, "build.json").read_text())["prunedAt"])
#             self.assertTrue(os.path.exists(os.path.join(folder, "build.log")))
#             self.assertFalse(os.path.exists(os.path.join(folder, "program.py")))
#             self.assertEqual(f.launch("-v", number).returncode, 1)
#             self.assertEqual(f.call("show", f"{f.component}@{number}").returncode, 0)
#         self.assertEqual(document(f.launch())["build"], "4")
#         self.assertEqual(f.launch("-v", "2").returncode, 0)
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], [])
#         self.assertEqual(f.build()["build"], "5")
#         for keep in ("0", "-1", "1.5", "two"):
#             self.assertEqual(f.call("prune", f.component, "--keep", keep).returncode, 1)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_prune

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_shared_data_format
#     def test_builds_shared_data_format(self) -> None:
#         """builds.shared-data-format records declarations while the sample component guards its own shared data."""
#         f = Fixture(self)
#         f.build()
#         f.configure(dataFormat=2)
#         f.build()
#         state = os.path.join(f.home, "shared-state.json")
#         contents = '{"format":2,"value":"unchanged"}'
#         Path(state).write_text(contents)
#         older = f.launch("-v", "1", "--state", state)
#         self.assertEqual([older.returncode, document(older)], [1, {"error": "newer data", "found": 2, "supported": 1}])
#         self.assertEqual(f.launch("--state", state).returncode, 0)
#         self.assertEqual(Path(state).read_text(), contents)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_shared_data_format

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_paths
#     def test_builds_paths(self) -> None:
#         """builds.paths uses default repository, registry and bin, or explicit paths with spaces and quotes. The default
#         repository is the clone in ~/repos/sylvan-stack/readonly/, not the repository's own folder (BLD-D18)."""
#         f = Fixture(self)
#         default_repo = os.path.join(f.home, "repos/sylvan-stack/readonly", f.component)
#         os.makedirs(os.path.dirname(default_repo))
#         os.rename(f.repo, default_repo)
#         result = subprocess.run([PYTHON, "-I", "-B", ENTRY, "build", f.component], cwd=f.home, env=f.env(),
#                                 capture_output=True, timeout=120, check=False)
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["source"]["repository"], os.path.realpath(default_repo))
#         self.assertTrue(os.path.exists(os.path.join(f.home, "Library/Application Support/Arbol/builds",
#                                                     f.component, "1/build.json")))
#         launcher = os.path.join(f.home, ".local/bin", f.component)
#         started = subprocess.run([launcher], env=ENV, capture_output=True, timeout=60, check=False)
#         self.assertEqual(document(started)["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_paths

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_invalid_description
#     def test_builds_invalid_description(self) -> None:
#         """builds.invalid-description and CLI input refuse without reserving a number."""
#         f = Fixture(self)
#         for args in ([], ["unknown"], ["build"], ["show", "sample@01"], ["prune", "sample"], ["withdraw", "sample@1"],
#                      ["build", "../outside"], ["list", "sample@1"], ["list", "--repo", f.repo], ["list", "--registry-dir"],
#                      ["list", "--unknown"], ["list", "--bin-dir=a", "--bin-dir=b"], ["show", ""]):
#             result = f.call(*args)
#             self.assertEqual(result.returncode, 1, args)
#             self.assertEqual(document(result)["error"]["code"], "builds_failed", args)
#         patches: list[dict[str, Any]] = [
#             {"entry": "../outside"}, {"build": []}, {"checks": []}, {"dataFormat": 0},
#             {"checks": [{"name": "same", "command": "true"}, {"name": "same", "command": "true"}]}]
#         for patch in patches:
#             f.configure(entry="program.py", build=[BUILD], checks=[{"name": "sample-check", "command": CHECK}],
#                         dataFormat=1)
#             f.configure(**patch)
#             self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1, patch)
#             self.assertFalse(os.path.exists(f.registry), patch)
#         f.configure(entry="program.py", build=[BUILD], checks=[{"name": "sample-check", "command": CHECK}], dataFormat=1)
#         shutil.rmtree(os.path.join(f.repo, ".git"))
#         refused = f.call("build", f.component, "--repo", f.repo)
#         self.assertEqual(refused.returncode, 1)
#         self.assertIn("not a git repository", document(refused)["error"]["message"])
#         self.assertFalse(os.path.exists(f.registry))
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_invalid_description

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_interrupted_build
#     def test_builds_interrupted_build(self) -> None:
#         """builds.interrupted-build keeps a failed record and consumes its reserved number."""
#         f = Fixture(self)
#         f.configure(build=["echo waiting; while true; do sleep 1; done"])
#         child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
#         log = Path(f.path("1/build.log"))
#         wait_until(waiting, log)
#         child.send_signal(signal.SIGTERM)
#         output, _ = child.communicate(timeout=30)
#         self.assertEqual(child.returncode, 1)
#         record = json.loads(output)
#         self.assertEqual(record["status"], "failed")
#         self.assertIn("stopped by the caller", record["failure"]["message"])
#         self.assertIn("(stopped by caller)", log.read_text())
#         f.configure(build=[BUILD])
#         self.assertEqual(f.build()["build"], "2")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_interrupted_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_prune_keeps_default
#     def test_builds_prune_keeps_default(self) -> None:
#         """builds.prune-keeps-default keeps the default when the newest working Build has lost its program."""
#         f = Fixture(self)
#         for _ in range(4):
#             f.build()
#         os.chmod(f.path("4/program.py"), 0o600)
#         self.assertEqual(document(f.launch())["build"], "3")
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["2", "1"])
#         self.assertEqual(document(f.launch())["build"], "3")
#         refused = f.call("withdraw", f"{f.component}@1", "--reason", "already pruned")
#         self.assertEqual([refused.returncode, document(refused)["error"]["code"]], [1, "builds_failed"])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_prune_keeps_default

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_stopped_commands
#     def test_builds_stopped_commands(self) -> None:
#         """builds.stopped-commands: SIGINT or SIGTERM sends SIGTERM to the whole process group of the running command."""
#         f = Fixture(self)
#         # A member of the group other than the shell notes the SIGTERM it receives.
#         f.configure(build=['(trap \'echo term > "$ARBOL_BUILD_DIR/term"; exit 0\' TERM; sleep 300 & wait) & '
#                            'echo $! > "$ARBOL_BUILD_DIR/child"; echo waiting; wait'])
#         for number, build in ((signal.SIGINT, "1"), (signal.SIGTERM, "2")):
#             with self.subTest(signal=number.name):
#                 child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry,
#                                 "--bin-dir", f.bin)
#                 log = Path(f.path(build, "build.log"))
#                 wait_until(waiting, log)
#                 background = int(Path(f.path(build, "child")).read_text())
#                 child.send_signal(number)
#                 output, _ = child.communicate(timeout=30)
#                 self.assertEqual(child.returncode, 1)
#                 record = json.loads(output)
#                 self.assertEqual([record["status"], record["failure"]["stage"]], ["failed", "build"])
#                 self.assertIn("Exit: SIGTERM (stopped by caller)", log.read_text())
#                 wait_until(Path(f.path(build, "term")).exists)
#                 wait_until(lambda pid: not alive(pid), background)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_stopped_commands

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_stop_kills
#     def test_builds_stop_kills(self) -> None:
#         """builds.stop-kills: a command that ignores SIGTERM is killed two seconds after the build is stopped."""
#         f = Fixture(self)
#         f.configure(build=['trap "" TERM; echo waiting; while true; do sleep 1; done'])
#         child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
#         log = Path(f.path("1/build.log"))
#         wait_until(waiting, log)
#         stopped = time.monotonic()
#         child.send_signal(signal.SIGTERM)
#         output, _ = child.communicate(timeout=30)
#         self.assertTrue(1.5 <= time.monotonic() - stopped < 10, time.monotonic() - stopped)
#         self.assertEqual([child.returncode, json.loads(output)["status"]], [1, "failed"])
#         self.assertIn("Exit: SIGKILL (stopped by caller)", log.read_text())
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_stop_kills

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_writer_reservations
#     def test_builds_writer_reservations(self) -> None:
#         """builds.writer-reservations: a live reservation in the earlier tool's form holds back record changes."""
#         f = Fixture(self)
#         f.build()
#         writers = Path(f.path(".writers"))
#         holder = subprocess.Popen(["/bin/sleep", "60"])
#         self.addCleanup(finish, holder)
#         reservation = writers / f"{holder.pid}-{uuid.uuid4()}.json"
#         reservation.write_text(json.dumps({"pid": holder.pid, "choosing": False, "ticket": "1"}, separators=(",", ":")))
#         withdraw = f.spawn("withdraw", f"{f.component}@1", "--reason", "after the writer", "--registry-dir", f.registry)
#         build = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
#         time.sleep(1.5)
#         self.assertEqual([withdraw.poll(), build.poll()], [None, None])
#         self.assertEqual(json.loads(Path(f.path("1/build.json")).read_text())["status"], "working")
#         self.assertFalse(os.path.exists(f.path("2/build.json")))
#         holder.kill()
#         holder.wait()
#         for child in (withdraw, build):
#             output, errors = child.communicate(timeout=120)
#             self.assertEqual(child.returncode, 0, output + errors)
#         # The writer has ended: its reservation was removed.
#         self.assertFalse(reservation.exists())
#         self.assertEqual(document(f.call("show", f"{f.component}@1"))["status"], "withdrawn")
#         self.assertEqual(document(f.launch())["build"], "2")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_writer_reservations

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_busy
#     def test_builds_busy(self) -> None:
#         """builds.busy: a change gives up when a live writer keeps its reservation past the limit."""
#         f = Fixture(self)
#         writers = Path(f.path(".writers"))
#         writers.mkdir(parents=True)
#         held = writers / f"{os.getpid()}-{uuid.uuid4()}.json"
#         held.write_text(json.dumps({"pid": os.getpid(), "choosing": False, "ticket": "1"}))
#         with mock.patch.object(mutation, "WAIT_SECONDS", 0.2), self.assertRaises(mutation.Busy):
#             mutation.with_mutation_lock(f.path(), lambda: None)
#         self.assertEqual(os.listdir(writers), [held.name])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_busy

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_failed_first_build
#     def test_builds_failed_first_build(self) -> None:
#         """builds.failed-first-build writes the launcher, which runs the failed Build only when it is named."""
#         f = Fixture(self)
#         f.configure(checks=[{"name": "always-fails", "command": "exit 1"}])
#         self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1)
#         refused = f.launch()
#         self.assertEqual([refused.returncode, document(refused)["error"]["available"]], [1, ["1"]])
#         named = f.launch("-v", "1")
#         self.assertEqual([named.returncode, document(named)["build"]], [0, "1"])
#         self.assertEqual(named.stderr, f"{f.component}@1 is failed: check always-fails: Check failed; see build.log.\n"
#                          .encode())
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_failed_first_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_entry_outside
#     def test_builds_entry_outside(self) -> None:
#         """builds.entry-outside: an entry that leads out of the Build folder fails at the entry stage."""
#         f = Fixture(self)
#         f.configure(build=[f'ln -s "{PYTHON}" "$ARBOL_BUILD_DIR/program.py"'])
#         record = document(f.call("build", f.component, "--repo", f.repo))
#         self.assertEqual([record["status"], record["failure"]["stage"]], ["failed", "entry"])
#         self.assertEqual(document(f.launch("-v", "1"))["error"]["available"], [])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_entry_outside

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_relative_paths
#     def test_builds_relative_paths(self) -> None:
#         """builds.relative-paths resolves a relative registry, bin folder and repository against the working folder."""
#         f = Fixture(self)
#         result = run_tool(f, "build", f.component, "--repo", "repository", "--registry-dir", "relative registry",
#                           "--bin-dir=relative-bin")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["source"]["repository"], f.repo)
#         launcher = os.path.join(f.home, "relative-bin", f.component)
#         self.assertIn(repr(os.path.join(f.home, "relative registry")), Path(launcher).read_text())
#         started = subprocess.run([launcher], cwd="/", env=ENV, capture_output=True, timeout=60, check=False)
#         self.assertEqual(document(started)["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_relative_paths

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_private_files
#     def test_builds_private_files(self) -> None:
#         """builds.private-files: registry folders are 0700, records and logs 0600, launchers 0755 less the umask."""
#         f = Fixture(self)
#         f.build()
#         for folder in (f.registry, f.path(), f.path("1"), f.path(".writers")):
#             self.assertEqual(mode(folder), 0o700, folder)
#         for file in (f.path("1/build.json"), f.path("1/build.log")):
#             self.assertEqual(mode(file), 0o600, file)
#         umask = os.umask(0)
#         os.umask(umask)
#         self.assertEqual(mode(os.path.join(f.bin, f.component)), 0o755 & ~umask)
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_private_files

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_command_environment
#     def test_builds_command_environment(self) -> None:
#         """builds.command-environment: commands read no input and start with every signal at its default,
#         none blocked, and the raised open-files limit, whatever the caller gave the tool."""
#         f = Fixture(self)
#         Path(f.repo, "signals.py").write_text(SIGNALS)
#         f.configure(build=[BUILD, 'cat > "$ARBOL_BUILD_DIR/input"', 'ulimit -n > "$ARBOL_BUILD_DIR/files"',
#                            f'"{PYTHON}" -I signals.py > "$ARBOL_BUILD_DIR/signals"'])
#
#         hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
#         if hard != resource.RLIM_INFINITY and hard <= 256:
#             self.skipTest("the open-files limit cannot be lowered and raised here")
#
#         def restricted(soft: int) -> Callable[[], None]:
#             def prepare() -> None:
#                 for number in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGUSR1):
#                     signal.signal(number, signal.SIG_IGN)
#                 signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1, signal.SIGTERM})
#                 resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
#             return prepare
#
#         def build(soft: int) -> str:
#             result = subprocess.run([*TOOL, "--registry-dir", f.registry, "--bin-dir", f.bin, "build", f.component,
#                                      "--repo", f.repo], cwd=f.home, env=f.env(), input=b"caller data",
#                                     capture_output=True, timeout=120, check=False, preexec_fn=restricted(soft))
#             self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#             return str(document(result)["build"])
#
#         number = build(256)
#         self.assertEqual(Path(f.path(number, "input")).read_bytes(), b"")
#         files = Path(f.path(number, "files")).read_text().strip()
#         if hard == resource.RLIM_INFINITY:
#             self.assertGreater(int(files), 256)
#             # Above 2**20 the Node.js tool raised the soft limit to the hard one.
#             self.assertEqual(Path(f.path(build(1 << 21), "files")).read_text().strip(), "unlimited")
#         else:
#             self.assertEqual(int(files), hard)
#         self.assertEqual(json.loads(Path(f.path(number, "signals")).read_text()), {"ignored": [], "blocked": []})
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_command_environment

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_record_format
#     def test_builds_record_format(self) -> None:
#         """builds.record-format: records keep the earlier tool's form: key order, times to the millisecond,
#         whole numbers, two-space indentation in build.json and one line on standard output."""
#         f = Fixture(self)
#         f.configure(contract=1.0, dataFormat=2)
#         result = f.call("build", f.component, "--repo", f.repo)
#         self.assertEqual(result.stdout.count(b"\n"), 1)
#         record = document(result)
#         keys = ["component", "build", "packageVersion", "status", "startedAt", "source", "entry", "checks",
#                 "contract", "dataFormat", "finishedAt"]
#         self.assertEqual(list(record), keys)
#         self.assertEqual(list(record["source"]), ["repository", "branch", "commit", "uncommittedChanges"])
#         for key in ("startedAt", "finishedAt"):
#             self.assertRegex(record[key], r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")
#         text = Path(f.path("1/build.json")).read_text()
#         self.assertTrue(text.startswith(f'{{\n  "component": "{f.component}",\n  "build": "1",\n'))
#         self.assertIn('\n  "contract": 1,\n', text)
#         self.assertEqual(list(json.loads(text)), keys)
#         f.call("withdraw", f"{f.component}@1", "--reason", "format")
#         withdrawn = document(f.call("show", f"{f.component}@1"))
#         self.assertEqual(list(json.loads(Path(f.path("1/build.json")).read_text())), [*keys, "withdrawn"])
#         shown_keys = [*keys, "withdrawn", "lastStart", "unusedSince"]
#         self.assertEqual([list(withdrawn), list(withdrawn["withdrawn"])], [shown_keys, ["at", "reason"]])
#         self.assertEqual(list(document(f.call("list"))[0]), [*shown_keys, "default"])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_record_format

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_list_order
#     def test_builds_list_order(self) -> None:
#         """builds.list-order lists components in name order, each newest first."""
#         f = Fixture(self)
#         f.build()
#         f.configure(component="alpha")
#         for _ in range(2):
#             self.assertEqual(f.call("build", "alpha", "--repo", f.repo).returncode, 0)
#         self.assertEqual([[record["component"], record["build"]] for record in document(f.call("list"))],
#                          [["alpha", "2"], ["alpha", "1"], [f.component, "1"]])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_list_order

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_tool_interrupt
#     def test_builds_tool_interrupt(self) -> None:
#         """builds.tool-interrupt: a SIGINT waiting while the caller blocked it ends the tool quietly by SIGINT."""
#         f = Fixture(self)
#
#         def pending() -> None:
#             signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
#             os.kill(os.getpid(), signal.SIGINT)
#
#         result = subprocess.run([*TOOL, "list", "--registry-dir", f.registry], cwd=f.home, env=f.env(),
#                                 capture_output=True, timeout=60, check=False, preexec_fn=pending)
#         self.assertEqual([result.returncode, result.stderr], [-signal.SIGINT, b""])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_tool_interrupt

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_text
#     def test_builds_text(self) -> None:
#         """builds.text: blank means what JavaScript's trim() removes; a reason that is not UTF-8 keeps U+FFFD."""
#         f = Fixture(self)
#         f.configure(checks=[{"name": "\x1c", "command": CHECK}])
#         self.assertEqual(f.build()["checks"], [{"name": "\x1c", "passed": True}])
#         for build in (["\ufeff\u3000"], [BUILD, "\u2028"]):
#             f.configure(build=build)
#             self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1, build)
#         self.assertEqual([name for name in os.listdir(f.path()) if not name.startswith(".")], ["1"])
#         self.assertEqual(f.call("withdraw", f"{f.component}@1", "--reason", "\ufeff\u00a0").returncode, 1)
#         result = run_tool(f, "withdraw", f"{f.component}@1", "--reason", b"caf\xe9 \xff", "--registry-dir", f.registry)
#         self.assertEqual(document(result)["withdrawn"]["reason"], "caf\ufffd \ufffd")
#         self.assertEqual(json.loads(Path(f.path("1/build.json")).read_text())["withdrawn"]["reason"],
#                          "caf\ufffd \ufffd")
#         f.configure(build=[BUILD])
#         Path(f.repo, "package.json").write_bytes(b'{"version":"1.2.3","author":"Jos\xe9"}\n')
#         self.assertEqual(f.build()["packageVersion"], "1.2.3")
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_text

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Builds.test_builds_closed_streams
#     def test_builds_closed_streams(self) -> None:
#         """builds.closed-streams: the tool and the launcher run with standard input and output closed,
#         as if they were /dev/null."""
#         f = Fixture(self)
#         closed = ["/bin/sh", "-c", 'exec "$@" <&- >&-', "sh"]
#         built = subprocess.run([*closed, *TOOL, "--registry-dir", f.registry, "--bin-dir", f.bin, "build", f.component,
#                                 "--repo", f.repo], cwd=f.home, env=f.env(), capture_output=True, timeout=120, check=False)
#         self.assertEqual([built.returncode, built.stdout, built.stderr], [0, b"", b""])
#         self.assertEqual(json.loads(Path(f.path("1/build.json")).read_text())["status"], "working")
#         self.assertNotIn(b'"status"', Path(f.path("1/build.log")).read_bytes())
#         launched = subprocess.run([*closed, os.path.join(f.bin, f.component), "--echo"], env=f.env(),
#                                   capture_output=True, timeout=60, check=False)
#         self.assertEqual([launched.returncode, launched.stderr], [0, b"diagnostic\n"])
# TEST-TIER-DISABLED-END tests/test_builds.py::Builds.test_builds_closed_streams



# class Roots(_support.Roots):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Roots.test_builds_root_of_build
#     def test_builds_root_of_build(self) -> None:
#         """builds.root-of-build: a Build of arbol or arbol-root names the Root it was made for from the start of its
#         build, numbers count across Roots, and a build without --root, or with it for another component, is refused
#         before a number is reserved (BLD-0.17, ARC-1.12)."""
#         f = Fixture(self, "arbol-root")
#         # What the build commands find in the record while the Build is being made.
#         f.configure(build=[BUILD, 'cp "$ARBOL_BUILD_DIR/build.json" "$ARBOL_BUILD_DIR/record-at-start.json"'])
#         refused = f.call("build", f.component, "--repo", f.repo)
#         self.assertEqual([refused.returncode, document(refused)["error"]["code"]], [1, "builds_failed"])
#         self.assertIn("--root", document(refused)["error"]["message"])
#         self.assertFalse(os.path.exists(f.registry))
#         records = [f.build("--root", root) for root in ("sapling", "sapling", "second", "second")]
#         self.assertEqual([[record["build"], record["root"]] for record in records],
#                          [["1", "sapling"], ["2", "sapling"], ["3", "second"], ["4", "second"]])
#         for record in records:
#             started = json.loads(Path(f.path(record["build"], "record-at-start.json")).read_text())
#             self.assertEqual([started["status"], started["root"]], ["building", record["root"]])
#         self.assertEqual(list(records[0]), ["component", "build", "packageVersion", "status", "startedAt", "source",
#                                             "entry", "checks", "root", "dataFormat", "finishedAt"])
#         self.assertNotIn("root", json.loads(Path(f.repo, "arbol-build.json").read_text()))
#         # list and show print the Root.
#         self.assertEqual([[record["build"], record["root"]] for record in document(f.call("list", f.component))],
#                          [["4", "second"], ["3", "second"], ["2", "sapling"], ["1", "sapling"]])
#         self.assertEqual(document(f.call("show", f"{f.component}@2"))["root"], "sapling")
#         given = run_tool(f, "--root=third", "build", f.component, "--repo", f.repo, "--registry-dir", f.registry,
#                          "--bin-dir", f.bin)
#         self.assertEqual([document(given)["build"], document(given)["root"]], ["5", "third"])
#         for args in (["--root", "Sapling"], ["--root", "sap ling"], ["--root", "../sapling"], ["--root", "sapling/x"],
#                      ["--root", "säpling"], ["--root", "-x"], ["--root="], ["--root", "a", "--root", "b"]):
#             result = f.call("build", f.component, "--repo", f.repo, *args)
#             self.assertEqual([result.returncode, document(result)["error"]["code"]], [1, "builds_failed"], args)
#         for args in (["list", "--root", "sapling"], ["show", f.component, "--root", "sapling"],
#                      ["withdraw", f"{f.component}@1", "--reason", "x", "--root", "sapling"],
#                      ["prune", f.component, "--keep", "1", "--root", "sapling"]):
#             self.assertEqual(f.call(*args).returncode, 1, args)
#         self.assertEqual(sorted(name for name in os.listdir(f.path()) if not name.startswith(".")),
#                          ["1", "2", "3", "4", "5"])
#         # arbol is made for a Root too; every other component belongs to none.
#         f.configure(component="arbol")
#         self.assertEqual(f.call("build", "arbol", "--repo", f.repo).returncode, 1)
#         built = document(f.call("build", "arbol", "--repo", f.repo, "--root", "sapling"))
#         self.assertEqual([built["component"], built["build"], built["root"]], ["arbol", "1", "sapling"])
#         f.configure(component="sample")
#         other = f.call("build", "sample", "--repo", f.repo, "--root", "sapling")
#         self.assertEqual(other.returncode, 1)
#         self.assertIn("belongs to no Root", document(other)["error"]["message"])
#         self.assertFalse(os.path.exists(os.path.join(f.registry, "sample")))
#         # A record of arbol-root without its Root, or with one that is not an identifier, is damaged.
#         path = Path(f.path("4/build.json"))
#         original = json.loads(path.read_text())
#         for bad in ({key: value for key, value in original.items() if key != "root"}, {**original, "root": "Second"},
#                     {**original, "root": 7}, {**original, "root": ""}):
#             path.write_text(json.dumps(bad))
#             self.assertEqual([record["build"] for record in document(f.call("list", f.component))],
#                              ["5", "3", "2", "1"], bad)
#         path.write_text(json.dumps(original))
#         self.assertEqual(document(f.call("show", f"{f.component}@4"))["root"], "second")
# TEST-TIER-DISABLED-END tests/test_builds.py::Roots.test_builds_root_of_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Roots.test_builds_trunk_components
#     def test_builds_trunk_components(self) -> None:
#         """builds.trunk-components: two Trunks, arbol-trunk/alpha and arbol-trunk/beta, are built from their folders
#         in arbol-trunk/trunks/, count separately, lie in folders of their own in the registry, get no launcher of
#         their own but the shared arbol-trunk, and every command takes their names (BLD-0.22, BLD-0.16)."""
#         f = Fixture(self, "arbol-trunk/alpha")
#         trunks = os.path.join(f.home, "repos/sylvan-stack/readonly/arbol-trunk/trunks")
#         os.makedirs(trunks)
#         os.rename(f.repo, os.path.join(trunks, "alpha"))
#         # beef is a code name that also reads as a build number.
#         for code in ("beta", "beef"):
#             shutil.copytree(os.path.join(trunks, "alpha"), os.path.join(trunks, code), symlinks=True)
#             Path(trunks, code, "arbol-build.json").write_text(json.dumps({**f.config, "component": f"arbol-trunk/{code}"}))
#
#         def build(component: str, *args: str) -> dict[str, Any]:
#             result = run_tool(f, "build", component, "--registry-dir", f.registry, "--bin-dir", f.bin, *args)
#             self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#             record: dict[str, Any] = document(result)
#             return record
#
#         order = ["alpha", "beta", "alpha", "beef", "alpha"]
#         records = [build(f"arbol-trunk/{code}") for code in order]
#         self.assertEqual([[record["component"], record["build"]] for record in records],
#                          [["arbol-trunk/alpha", "1"], ["arbol-trunk/beta", "1"], ["arbol-trunk/alpha", "2"],
#                           ["arbol-trunk/beef", "1"], ["arbol-trunk/alpha", "3"]])
#         for code, record in zip(order, records, strict=True):
#             self.assertEqual(record["source"]["repository"], os.path.join(trunks, code))
#         self.assertEqual(os.listdir(f.registry), ["arbol-trunk"])
#         self.assertEqual(sorted(os.listdir(os.path.join(f.registry, "arbol-trunk"))), ["alpha", "beef", "beta"])
#         self.assertEqual(sorted(name for name in os.listdir(f.path()) if not name.startswith(".")), ["1", "2", "3"])
#         self.assertTrue(os.path.isfile(os.path.join(f.registry, "arbol-trunk/beta/1/build.json")))
#         # The Trunks share the launcher arbol-trunk, which the build of any Trunk writes; none has one of its own.
#         self.assertEqual(os.listdir(f.bin), ["arbol-trunk"])
#         text = Path(f.bin, "arbol-trunk").read_text()
#         self.assertTrue(text.rstrip("\n").endswith(f"sys.exit(launch_trunk({f.registry!r}, sys.argv[1:]))"))
#         listed = [[record["component"], record["build"], record["default"]] for record in document(f.call("list"))]
#         self.assertEqual(listed, [["arbol-trunk/alpha", "3", True], ["arbol-trunk/alpha", "2", False],
#                                   ["arbol-trunk/alpha", "1", False], ["arbol-trunk/beef", "1", True],
#                                   ["arbol-trunk/beta", "1", True]])
#         self.assertEqual([record["build"] for record in document(f.call("list", "arbol-trunk/beta"))], ["1"])
#         # A folder in builds/arbol-trunk/ whose name is no code name holds no Trunk.
#         record = json.loads(Path(f.path("1/build.json")).read_text())
#         for stray in ("Stray", "list"):
#             os.makedirs(os.path.join(f.registry, "arbol-trunk", stray, "1"))
#             Path(f.registry, "arbol-trunk", stray, "1/build.json").write_text(
#                 json.dumps({**record, "component": f"arbol-trunk/{stray}"}))
#         self.assertEqual([[record["component"], record["build"], record["default"]]
#                           for record in document(f.call("list"))], listed)
#         for stray in ("Stray", "list"):
#             shutil.rmtree(os.path.join(f.registry, "arbol-trunk", stray))
#         self.assertEqual(document(f.call("show", "arbol-trunk/alpha"))["build"], "3")
#         self.assertEqual(document(f.call("show", "arbol-trunk/alpha@1"))["build"], "1")
#         withdrawn = f.call("withdraw", "arbol-trunk/alpha@3", "--reason", "bad answers")
#         self.assertEqual([withdrawn.returncode, document(withdrawn)["status"]], [0, "withdrawn"])
#         self.assertEqual(document(f.call("show", "arbol-trunk/alpha"))["build"], "2")
#         self.assertEqual(document(f.call("show", "arbol-trunk/beta"))["build"], "1")
#         self.assertEqual(document(f.call("prune", "arbol-trunk/alpha", "--keep", "1")),
#                          {"component": "arbol-trunk/alpha", "pruned": ["1"]})
#         self.assertEqual(document(f.call("show", "arbol-trunk/beef"))["build"], "1")
#         # --repo names another folder for one build.
#         elsewhere = os.path.join(f.home, "beta elsewhere")
#         shutil.copytree(os.path.join(trunks, "beta"), elsewhere, symlinks=True)
#         moved = build("arbol-trunk/beta", "--repo", elsewhere)
#         self.assertEqual([moved["build"], moved["source"]["repository"]], ["2", elsewhere])
#         names = ["arbol-trunk", "arbol-trunk/", "arbol-trunk/run", "arbol-trunk/settle", "arbol-trunk/list",
#                  "arbol-trunk/Alpha", "arbol-trunk/1alpha", "arbol-trunk/al-pha", "arbol-trunk/alpha/x",
#                  "arbol-trunk//alpha", "arbol-trunk/" + "a" * 33, "arbol-trunk/älpha"]
#         for name in names:
#             for args in (["build", name], ["show", name], ["list", name]):
#                 result = f.call(*args)
#                 self.assertEqual([result.returncode, document(result)["error"]["code"]], [1, "builds_failed"], args)
#         self.assertEqual(sorted(os.listdir(os.path.join(f.registry, "arbol-trunk"))), ["alpha", "beef", "beta"])
#         self.assertEqual(component_name("arbol-trunk/" + "a" * 32), "arbol-trunk/" + "a" * 32)
#         self.assertEqual(component_name("arbol-trunk/a1"), "arbol-trunk/a1")
# TEST-TIER-DISABLED-END tests/test_builds.py::Roots.test_builds_trunk_components

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Roots.test_builds_trunk_root_contracts
#     def test_builds_trunk_root_contracts(self) -> None:
#         """builds.trunk-root-contracts: a Trunk's Build lists the Root Contract versions its description names and
#         no Root; a Trunk without rootContracts is refused before a number is reserved, and no other component lists
#         them (BLD-0.21)."""
#         f = Fixture(self, "arbol-trunk/alpha")
#         base = {key: value for key, value in f.config.items() if key != "rootContracts"}
#
#         def refused(config: dict[str, Any], *args: str) -> str:
#             Path(f.repo, "arbol-build.json").write_text(json.dumps(config))
#             result = f.call("build", f.component, "--repo", f.repo, *args)
#             self.assertEqual([result.returncode, document(result)["error"]["code"]], [1, "builds_failed"], config)
#             self.assertFalse(os.path.exists(f.registry), config)
#             return str(document(result)["error"]["message"])
#
#         self.assertIn("rootContracts", refused(base))
#         for value in ([], [0], [-1], [1.5], ["1"], [True], [None], [1, 1], [1, 1.0], 1, "1", True, None, {"1": 1}):
#             refused({**base, "rootContracts": value})
#         self.assertIn("in place of contract", refused({**base, "rootContracts": [1], "contract": 1}))
#         self.assertIn("belongs to no Root", refused({**base, "rootContracts": [1]}, "--root", "sapling"))
#         f.configure(rootContracts=[2, 1.0])
#         record = f.build()
#         self.assertEqual([record["rootContracts"], "root" in record], [[2, 1], False])
#         self.assertEqual(list(record), ["component", "build", "packageVersion", "status", "startedAt", "source",
#                                         "entry", "checks", "rootContracts", "dataFormat", "finishedAt"])
#         self.assertEqual(json.loads(Path(f.path("1/build.json")).read_text())["rootContracts"], [2, 1])
#         self.assertIn('\n  "rootContracts": [\n    2,\n    1\n  ],\n', Path(f.path("1/build.json")).read_text())
#         # list and show print the versions.
#         self.assertEqual(document(f.call("show", f.component))["rootContracts"], [2, 1])
#         self.assertEqual(document(f.call("list"))[0]["rootContracts"], [2, 1])
#         # A record of a Trunk without its versions, or with versions that are not, is damaged.
#         f.build()
#         path = Path(f.path("2/build.json"))
#         original = json.loads(path.read_text())
#         for bad in ({key: value for key, value in original.items() if key != "rootContracts"},
#                     {**original, "rootContracts": []}, {**original, "rootContracts": [0]},
#                     {**original, "rootContracts": "1"}, {**original, "rootContracts": [1, 1]}):
#             path.write_text(json.dumps(bad))
#             self.assertEqual([record["build"] for record in document(f.call("list", f.component))], ["1"], bad)
#         path.write_text(json.dumps(original))
#         self.assertEqual(document(f.call("show", f.component))["build"], "2")
#         # No other component lists them.
#         g = Fixture(self)
#         g.configure(rootContracts=[1])
#         result = g.call("build", g.component, "--repo", g.repo)
#         self.assertEqual([result.returncode, document(result)["error"]["message"]], [1, "Only a Trunk lists rootContracts."])
#         self.assertFalse(os.path.exists(g.registry))
# TEST-TIER-DISABLED-END tests/test_builds.py::Roots.test_builds_trunk_root_contracts

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Roots.test_builds_outside_roots
#     def test_builds_outside_roots(self) -> None:
#         """builds.outside-roots: the registry, the launchers and arbol-builds lie outside every Root and hold no
#         Root's backend, UI code, migration script or table layout; a Build of arbol-root carries its own (BLD-0.23)."""
#         f = Fixture(self, "arbol-root")
#         Path(f.repo, "chat-tables.sql").write_text("CREATE TABLE sample_chats (id integer);\n")
#         f.configure(build=[BUILD, 'mkdir "$ARBOL_BUILD_DIR/layout" && cp chat-tables.sql "$ARBOL_BUILD_DIR/layout/"'])
#         for root in ("sapling", "second"):
#             result = run_tool(f, "build", f.component, "--repo", f.repo, "--root", root)
#             self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         # The default registry, and nothing of a Root: no Root's folder and no settings.
#         state = os.path.join(f.home, "Library/Application Support/Arbol")
#         self.assertEqual(os.listdir(state), ["builds"])
#         self.assertFalse(os.path.exists(os.path.join(f.home, ".arbol")))
#         registry = os.path.join(state, "builds")
#         # One count of Builds for the component, not a folder for each Root.
#         self.assertEqual(os.listdir(registry), ["arbol-root"])
#         self.assertEqual(sorted(name for name in os.listdir(os.path.join(registry, "arbol-root"))
#                                 if not name.startswith(".")), ["1", "2"])
#         # The table layout lies in each Build's own folder, and nowhere else.
#         layouts = sorted(os.path.relpath(os.path.join(folder, name), registry)
#                          for folder, _, names in os.walk(registry) for name in names if name.endswith(".sql"))
#         self.assertEqual(layouts, ["arbol-root/1/layout/chat-tables.sql", "arbol-root/2/layout/chat-tables.sql"])
#         # The one launcher serves every Root and holds nothing of one.
#         launcher = Path(f.home, ".local/bin", f.component).read_text()
#         for word in ("sapling", "'second'", '"second"', "CREATE TABLE", ".sql", "from arbol_builds", "import arbol_builds"):
#             self.assertNotIn(word, launcher)
#         # The tool is Python of the standard library alone, with no SQL.
#         package = ROOT / "src/arbol_builds"
#         modules = sorted(path for path in package.iterdir() if path.name != "__pycache__")
#         self.assertTrue(modules)
#         for path in modules:
#             self.assertEqual(path.suffix, ".py", path)
#             source = path.read_text(encoding="utf-8")
#             self.assertNotIn("create table", source.lower(), path)
#             self.assertNotIn(".sql", source, path)
#             for node in ast.walk(ast.parse(source)):
#                 if isinstance(node, ast.Import):
#                     imported = [alias.name for alias in node.names]
#                 elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
#                     imported = [node.module]
#                 else:
#                     continue
#                 for name in imported:
#                     self.assertIn(name.split(".")[0], sys.stdlib_module_names, path)
# TEST-TIER-DISABLED-END tests/test_builds.py::Roots.test_builds_outside_roots



# class Launchers(_support.Launchers):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Launchers.test_builds_launcher_signals
#     def test_builds_launcher_signals(self) -> None:
#         """builds.launcher-signals: the Build gets SIGPIPE and SIGXFSZ at their default, as on a direct start."""
#         f = Fixture(self, "probe")
#         Path(f.repo, "probe.sh").write_text('#!/bin/sh\n(yes; echo "yes ended with $?" >&2) | head -1 > /dev/null\n'
#                                             '(ulimit -f 0; printf x > "$(dirname "$0")/written")\n'
#                                             'echo "write ended with $?" >&2\n')
#         f.configure(build=['cp probe.sh "$ARBOL_BUILD_DIR/probe.sh"; chmod +x "$ARBOL_BUILD_DIR/probe.sh"'],
#                     entry="probe.sh", checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/probe.sh"'}])
#         f.build()
#         direct = subprocess.run([f.path("1/probe.sh")], env=ENV, capture_output=True, timeout=30, check=False)
#         launched = f.launch()
#
#         def ended(result: Result) -> list[bytes]:
#             # The shell also reports the signal, with a process number that differs from run to run.
#             return [line for line in result.stderr.splitlines() if b" ended with " in line]
#
#         self.assertEqual(ended(direct), [b"yes ended with 141", b"write ended with 153"])
#         self.assertEqual(ended(launched), ended(direct))
# TEST-TIER-DISABLED-END tests/test_builds.py::Launchers.test_builds_launcher_signals

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Launchers.test_builds_launcher_bytes
#     def test_builds_launcher_bytes(self) -> None:
#         """builds.launcher-bytes: arguments and environment that are not UTF-8 reach the Build byte for byte."""
#         f = Fixture(self)
#         f.build()
#         arguments = [b"plain", b"caf\xe9", b"\xff\xfe-not-utf8", b"\xe2\x82\xac", b""]
#         result = subprocess.run([os.path.join(f.bin, f.component).encode(), b"--bytes", *arguments],
#                                 env={**{key.encode(): value.encode() for key, value in f.env().items()},
#                                      b"PROBE": b"\xff\x80value"},
#                                 capture_output=True, timeout=60, check=False)
#         self.assertEqual(document(result), {"args": [argument.hex() for argument in arguments],
#                                             "probe": b"\xff\x80value".hex()})
#         helper = os.path.join(f.home, "execve.py")
#         Path(helper).write_text(EXECVE)
#         environment = [b"PATH=/usr/bin:/bin", b"LANG=en_US.UTF-8", b"DUP=first", b"DUP=second", b"NOEQUALS",
#                        b"X=\xff\xfe"]
#
#         def environ(program: str) -> list[bytes]:
#             words = [program.encode(), b"--environ", b"--", *environment]
#             started = subprocess.run([PYTHON, "-I", helper, *(word.hex() for word in words)], capture_output=True,
#                                      timeout=60, check=False)
#             self.assertEqual(started.returncode, 0, started.stderr)
#             # macOS adds this one when it is missing, on a direct start too.
#             return [bytes.fromhex(entry) for entry in document(started)
#                     if not bytes.fromhex(entry).startswith(b"__CF_USER_TEXT_ENCODING=")]
#
#         self.assertEqual(environ(os.path.join(f.bin, f.component)), environment)
#         self.assertEqual(environ(f.path("1/program.py")), environment)
# TEST-TIER-DISABLED-END tests/test_builds.py::Launchers.test_builds_launcher_bytes

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Launchers.test_builds_launcher_start_interrupt
#     def test_builds_launcher_start_interrupt(self) -> None:
#         """builds.launcher-start-interrupt: a SIGINT at any moment of the launcher's start ends it by SIGINT, or
#         reaches the Build; it is never lost, so the Build never runs on after it."""
#         f = Fixture(self, "pause")
#         Path(f.repo, "pause.sh").write_text("#!/bin/sh\nexec sleep 5\n")
#         f.configure(build=['cp pause.sh "$ARBOL_BUILD_DIR/pause.sh"; chmod +x "$ARBOL_BUILD_DIR/pause.sh"'],
#                     entry="pause.sh", checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/pause.sh"'}])
#         f.build()
#         outcomes: dict[object, int] = {}
#         for attempt in range(200):
#             child = subprocess.Popen([os.path.join(f.bin, f.component)], env=f.env(), stdin=subprocess.DEVNULL,
#                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#             self.addCleanup(finish, child)
#             time.sleep((attempt % 25) / 1000)
#             child.send_signal(signal.SIGINT)
#             try:
#                 code: object = child.wait(timeout=4)
#             except subprocess.TimeoutExpired:
#                 code = "lost"
#             outcomes[code] = outcomes.get(code, 0) + 1
#         # Exit status 1: Python failed to start at all, a case BLD-0 names; the Build never ran.
#         self.assertLessEqual(set(outcomes), {-signal.SIGINT, 1}, outcomes)
# TEST-TIER-DISABLED-END tests/test_builds.py::Launchers.test_builds_launcher_start_interrupt

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Launchers.test_builds_launch_failed
#     def test_builds_launch_failed(self) -> None:
#         """builds.launch-failed: a hand-over the system refuses prints launch_failed and ends with 1."""
#         f = Fixture(self)
#         f.configure(build=['printf "not a program" > "$ARBOL_BUILD_DIR/program.py"; chmod +x "$ARBOL_BUILD_DIR/program.py"'],
#                     checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/program.py"'}])
#         f.build()
#         result = f.launch()
#         self.assertEqual(result.returncode, 1)
#         self.assertEqual(document(result)["error"]["code"], "launch_failed")
#         self.assertIn("Exec format error", document(result)["error"]["message"])
# TEST-TIER-DISABLED-END tests/test_builds.py::Launchers.test_builds_launch_failed

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Launchers.test_builds_nonblocking_output
#     def test_builds_nonblocking_output(self) -> None:
#         """builds.nonblocking-output: output reaches a pipe the caller left non-blocking in full."""
#         f = Fixture(self)
#         f.build()
#         record = json.loads(Path(f.path("1/build.json")).read_text())
#         for number in range(2, 302):
#             os.mkdir(f.path(format(number, "x")))
#             Path(f.path(format(number, "x"), "build.json")).write_text(json.dumps({**record, "build": format(number, "x")}))
#         reading, writing = os.pipe()
#         os.set_blocking(writing, False)
#         lister = subprocess.Popen([*TOOL, "list", "--registry-dir", f.registry], cwd=f.home, env=f.env(),
#                                   stdout=writing, stderr=subprocess.PIPE)
#         self.addCleanup(finish, lister)
#         os.close(writing)
#         time.sleep(0.5)  # the caller reads late: the pipe fills
#         with os.fdopen(reading, "rb") as stream:
#             listed = stream.read()
#         self.assertEqual(lister.wait(timeout=60), 0)
#         self.assertGreater(len(listed), 1 << 17)
#         self.assertEqual(len(json.loads(listed)), 301)
#         read_end, write_end = os.pipe()
#         os.set_blocking(write_end, False)
#         data = os.urandom(1 << 20)
#         received = bytearray()
#
#         def drain() -> None:
#             while chunk := os.read(read_end, 65536):
#                 received.extend(chunk)
#                 time.sleep(0.001)
#
#         reader = threading.Thread(target=drain)
#         reader.start()
#         try:
#             write_all(write_end, data)
#         finally:
#             os.close(write_end)
#             reader.join(timeout=60)
#             os.close(read_end)
#         self.assertEqual(bytes(received), data)
# TEST-TIER-DISABLED-END tests/test_builds.py::Launchers.test_builds_nonblocking_output



# class PruningRoots(_support.PruningRoots):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_versions_keeps_each_retained_contract_version_with_independent_trunk_counts
#     def test_builds_prune_versions_keeps_each_retained_contract_version_with_independent_trunk_counts(self) -> None:
#         """builds.prune-versions: overlapping version lists and all Root states protect compatible Builds."""
#         f = Fixture(self, "arbol-trunk/alpha")
#         roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#         for name, state, version in (("sapling", "working", 1), ("second", "preparing", 2), ("third", "failed", 1)):
#             write_root(roots, root_record(name, state, contract=version))
#         for versions in ([3], [1], [1, 2], [2], [4]):
#             f.configure(rootContracts=versions)
#             f.build()
#         f.configure(component="arbol-trunk/beta", rootContracts=[1, 2])
#         beta = f.call("build", "arbol-trunk/beta", "--repo", f.repo)
#         self.assertEqual(beta.returncode, 0, beta.stdout + beta.stderr)
#         other = Path(f.registry, "arbol-trunk/beta")
#         before = {path: path.read_bytes() for path in other.rglob("*") if path.is_file()}
#         result = f.call("prune", f.component, "--keep", "1")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["pruned"], ["2", "1"])
#         self.assertEqual({path: path.read_bytes() for path in other.rglob("*") if path.is_file()}, before)
#         for name, expected in (("sapling", "3"), ("second", "4"), ("third", "3")):
#             launched = subprocess.run([os.path.join(f.bin, "arbol-trunk"), "--root", name, "alpha", "run"],
#                                       cwd=f.home, env=f.env(), capture_output=True, timeout=30, check=False)
#             self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
#             self.assertEqual(document(launched)["build"], expected)
#         for name in ("sapling", "third"):
#             Path(roots, name, "root.json").unlink()
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["3"])
#         Path(roots, "second/root.json").unlink()
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["4"])
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], [])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_versions_keeps_each_retained_contract_version_with_independent_trunk_counts

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds
#     def test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds(self) -> None:
#         """builds.prune-version-fallback: missing newer executables do not expose the last runnable fit."""
#         f = Trunks(self)
#         f.root("sapling", 1, "2026-10-16T09:00:00.000Z")
#         f.root("second", 2, "2026-10-16T10:00:00.000Z")
#         for number, versions in (("1", [1]), ("2", [1, 2]), ("3", [2]), ("4", [3])):
#             f.build("alpha", number, versions)
#         Path(f.registry, "arbol-trunk/alpha/3/program.py").unlink()
#         self.assertEqual(self.trunk_command(f, "lock", "arbol-trunk/alpha@1").returncode, 0)
#         result = self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["pruned"], ["3"])
#         self.assertEqual(f.started("--root", "second", "alpha", "run")[0], "2")
#         self.assertEqual(f.started("--root", "sapling", "alpha", "run")[0], "2")
#         self.assertEqual(self.trunk_command(f, "unlock", "arbol-trunk/alpha@1").returncode, 0)
#         self.assertEqual(document(self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1"))["pruned"],
#                          ["1"])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation
#     def test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation(self) -> None:
#         """builds.prune-version-refusal: an unknown retained version refuses the whole prune without changes."""
#         f = Trunks(self)
#         f.root("sapling", 1, "2026-10-16T09:00:00.000Z")
#         for number in ("1", "2", "3"):
#             f.build("alpha", number, [1])
#         write_root(f.roots, "{", "damaged")
#         Path(f.roots, "pipe").mkdir()
#         os.mkfifo(Path(f.roots, "pipe/root.json"))
#         before = {path: path.read_bytes() for path in Path(f.registry).rglob("*") if path.is_file()}
#         result = self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1")
#         self.assertEqual(result.returncode, 1)
#         error = document(result)["error"]
#         self.assertEqual(error["code"], "builds_failed")
#         self.assertIn("damaged, pipe", error["message"])
#         self.assertIn("versions are unknown", error["message"])
#         self.assertEqual({path: path.read_bytes() for path in Path(f.registry).rglob("*") if path.is_file()}, before)
#         write_root(f.roots, root_record("damaged", "failed"))
#         Path(f.roots, "pipe/root.json").unlink()
#         self.assertEqual(document(self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1"))["pruned"],
#                          ["2", "1"])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_outside_roots_stays_count_based_without_reading_the_catalogue
#     def test_builds_prune_outside_roots_stays_count_based_without_reading_the_catalogue(self) -> None:
#         """builds.prune-outside-roots: Drivers and other components need locks, never per-Root counts."""
#         for component in ("sample", "arbol-claude-driver"):
#             with self.subTest(component=component):
#                 f = Fixture(self, component)
#                 if component == "arbol-claude-driver":
#                     f.configure(contract=1, checks=[{"name": kind, "kind": kind, "command": CHECK}
#                                                    for kind in ("unit", "contract", "live")])
#                 for _ in range(3):
#                     f.build()
#                 roots = Path(f.home, "Library/Application Support/Arbol/roots")
#                 roots.parent.mkdir(parents=True)
#                 roots.write_text("an inaccessible catalogue must not affect this component")
#                 self.assertEqual(f.call("lock", component + "@1").returncode, 0)
#                 result = f.call("prune", component, "--keep", "1")
#                 self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#                 self.assertEqual(document(result)["pruned"], ["2"])
#                 self.assertEqual(f.call("unlock", component + "@1").returncode, 0)
#                 self.assertEqual(document(f.call("prune", component, "--keep", "1"))["pruned"], ["1"])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_outside_roots_stays_count_based_without_reading_the_catalogue

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_roots_preserves_one_runnable_build_of_every_retained_root_in_any_state
#     def test_builds_prune_roots_preserves_one_runnable_build_of_every_retained_root_in_any_state(self) -> None:
#         """builds.prune-roots: three retained Roots keep three working Builds despite --keep 1."""
#         for component in ("arbol", "arbol-root"):
#             with self.subTest(component=component):
#                 f = Fixture(self, component)
#                 roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#                 for name, state in (("sapling", "working"), ("second", "preparing"), ("third", "failed")):
#                     write_root(roots, root_record(name, state))
#                     f.build("--root", name)
#                     f.build("--root", name)
#                 self.assertEqual(f.launch("-v", "1").returncode, 0)
#                 activity = Path(f.path("1/last-start")).read_bytes()
#                 log = Path(f.path("1/build.log")).read_bytes()
#                 result = f.call("prune", component, "--keep", "1")
#                 self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#                 self.assertEqual(document(result)["pruned"], ["5", "3", "1"])
#                 for name, number in (("sapling", "2"), ("second", "4"), ("third", "6")):
#                     self.assertEqual(document(f.launch("--root", name))["build"], number)
#                 self.assertEqual(Path(f.path("1/last-start")).read_bytes(), activity)
#                 self.assertEqual(Path(f.path("1/build.log")).read_bytes(), log)
#                 self.assertIn("prunedAt", json.loads(Path(f.path("1/build.json")).read_text()))
#                 self.assertFalse(Path(f.path("1/program.py")).exists())
#                 self.assertEqual(document(f.call("prune", component, "--keep", "1"))["pruned"], [])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_roots_preserves_one_runnable_build_of_every_retained_root_in_any_state

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds
#     def test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds(self) -> None:
#         """builds.prune-root-retention: missing records protect nothing; damaged records and locks still do."""
#         f = Fixture(self, "arbol-root")
#         roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#         for name in ("removed", "sapling", "sapling", "second", "third"):
#             f.build("--root", name)
#         write_root(roots, "{", "sapling")
#         write_root(roots, root_record("another"), "second")
#         write_root(roots, root_record("third"))
#         Path(roots, "removed").mkdir()  # a folder without root.json is no longer retained
#         Path(f.path("3/program.py")).unlink()
#         result = f.call("prune", f.component, "--keep", "1")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["pruned"], ["3", "1"])
#         for number in ("2", "4", "5"):
#             self.assertTrue(Path(f.path(number, "program.py")).is_file())
#         self.assertEqual(f.call("lock", "arbol-root@2").returncode, 0)
#         for name in ("sapling", "second"):
#             Path(roots, name, "root.json").unlink()
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["4"])
#         self.assertTrue(Path(f.path("2/program.py")).is_file())
#         self.assertEqual(f.call("unlock", "arbol-root@2").returncode, 0)
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["2"])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_roots_refuses_an_unlistable_catalogue_before_changing_builds
#     def test_builds_prune_roots_refuses_an_unlistable_catalogue_before_changing_builds(self) -> None:
#         """builds.prune-root-catalogue-refusal: a listing failure is not an empty Root catalogue."""
#         f = Fixture(self, "arbol-root")
#         for _ in range(3):
#             f.build("--root", "sapling")
#         roots = Path(f.home, "Library/Application Support/Arbol/roots")
#         roots.parent.mkdir(parents=True)
#         roots.write_text("not a catalogue")
#         before = {path: path.read_bytes() for path in Path(f.path()).rglob("*") if path.is_file()}
#         result = f.call("prune", f.component, "--keep", "1")
#         self.assertEqual(result.returncode, 1)
#         self.assertEqual(document(result)["error"]["code"], "builds_failed")
#         self.assertIn("Cannot list the retained Roots", document(result)["error"]["message"])
#         self.assertEqual({path: path.read_bytes() for path in Path(f.path()).rglob("*") if path.is_file()}, before)
#         roots.unlink()
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["2", "1"])
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_roots_refuses_an_unlistable_catalogue_before_changing_builds

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_catalogue_keeps_retained_identities_even_when_records_cannot_be_used
#     def test_builds_prune_catalogue_keeps_retained_identities_even_when_records_cannot_be_used(self) -> None:
#         """builds.prune-catalogue: every state and damaged/unreadable/nonregular entry retains its folder."""
#         with tempfile.TemporaryDirectory() as home:
#             for name, state in (("sapling", "working"), ("preparing", "preparing"), ("failed", "failed")):
#                 write_root(home, root_record(name, state))
#             write_root(home, "{", "damaged")
#             write_root(home, root_record("another"), "mismatch")
#             write_root(home, root_record("invalid", contract=0))
#             write_root(home, root_record("BadName"))
#             Path(home, "missing").mkdir()
#             for name in ("directory", "pipe", "dangling", "unreadable"):
#                 Path(home, name).mkdir()
#             Path(home, "directory/root.json").mkdir()
#             os.mkfifo(Path(home, "pipe/root.json"))
#             Path(home, "dangling/root.json").symlink_to("absent")
#             Path(home, "unreadable/root.json").write_text("{}")
#             opened = os.open
#
#             def open_record(path: str, flags: int) -> int:
#                 if path == str(Path(home, "unreadable/root.json")):
#                     raise PermissionError("private unreadable record")
#                 return opened(path, flags)
#
#             with mock.patch("arbol_builds.pruning.os.open", side_effect=open_record):
#                 records = pruning.retained_roots(home)
#             self.assertEqual(set(records), {"sapling", "preparing", "failed", "damaged", "mismatch", "invalid",
#                                             "directory", "pipe", "dangling", "unreadable"})
#             for name in ("sapling", "preparing", "failed"):
#                 self.assertEqual(records[name], root_record(name, "working" if name == "sapling" else name))
#             for name in set(records) - {"sapling", "preparing", "failed"}:
#                 self.assertIsNone(records[name], name)
#             self.assertIsNone(read_root(home, "damaged"))
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_catalogue_keeps_retained_identities_even_when_records_cannot_be_used

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_catalogue_distinguishes_absence_from_listing_or_record_access_failures
#     def test_builds_prune_catalogue_distinguishes_absence_from_listing_or_record_access_failures(self) -> None:
#         """builds.prune-catalogue-failure: absence is empty; an unlistable catalogue cannot authorize pruning."""
#         with tempfile.TemporaryDirectory() as home:
#             self.assertEqual(pruning.retained_roots(str(Path(home, "absent"))), {})
#             Path(home, "file").write_text("not a catalogue")
#             with self.assertRaisesRegex(ValueError, "Cannot list the retained Roots"):
#                 pruning.retained_roots(str(Path(home, "file")))
#             with mock.patch("arbol_builds.pruning.os.scandir", side_effect=PermissionError("private denial")):
#                 with self.assertRaisesRegex(ValueError, "private denial"):
#                     pruning.retained_roots(home)
#             write_root(home, root_record("sapling"))
#             with mock.patch("arbol_builds.pruning.os.lstat", side_effect=PermissionError("record inaccessible")):
#                 self.assertEqual(pruning.retained_roots(home), {"file": None, "sapling": None})
# TEST-TIER-DISABLED-END tests/test_builds.py::PruningRoots.test_builds_prune_catalogue_distinguishes_absence_from_listing_or_record_access_failures



# class RootComponents(_support.RootComponents):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_default_selects_only_that_root_in_the_arc_example
#     def test_builds_root_default_selects_only_that_root_in_the_arc_example(self) -> None:
#         """builds.root-default: Builds 5/6 for sapling and 7/8 for second choose 6 and 8, for both components."""
#         for component in ("arbol", "arbol-root"):
#             with self.subTest(component=component):
#                 f = self.fixture(component)
#                 os.makedirs(f.path("4"))  # consume the earlier numbers of ARC-1's example
#                 records = [f.build("--root", root) for root in ("sapling", "sapling", "second", "second")]
#                 self.assertEqual([r["build"] for r in records], ["5", "6", "7", "8"])
#                 self.assertEqual(document(f.launch("--root", "sapling", "command"))["build"], "6")
#                 self.assertEqual(document(f.launch("--root", "second", "command"))["build"], "8")
#                 current = document(f.launch("command"))
#                 self.assertEqual((current["build"], current["args"]), ("8", ["command"]))
#                 self.assertEqual(document(f.launch())["args"], [])
#                 Path(f.path("6/program.py")).unlink()
#                 self.assertEqual(document(f.launch("--root", "sapling"))["build"], "5")
#                 Path(f.path("5/program.py")).unlink()
#                 refused = f.launch("--root", "sapling")
#                 self.assertEqual(refused.returncode, 1)
#                 self.assertEqual(document(refused)["error"]["code"], "build_unavailable")
#                 self.assertIn(component, document(refused)["error"]["message"])
#                 self.assertIn("sapling", document(refused)["error"]["message"])
#                 self.assertEqual(document(refused)["error"]["available"], [])
#                 self.assertEqual(document(f.launch())["build"], "8")
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_default_selects_only_that_root_in_the_arc_example

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_records_are_reread_and_only_working_roots_can_be_current
#     def test_builds_root_records_are_reread_and_only_working_roots_can_be_current(self) -> None:
#         """builds.root-refusals isolates damaged records and never substitutes another Root for an explicit one."""
#         f = self.fixture()
#         f.build("--root", "sapling")
#         f.build("--root", "second")
#         roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#         write_root(roots, "{", "second")
#         self.assertEqual(document(f.launch())["build"], "1")
#         for args in (["--root", "second"], ["--root", "missing"], ["--root", "../sapling"], ["--root"]):
#             result = f.launch(*args)
#             self.assertEqual(result.returncode, 1)
#             self.assertEqual(document(result)["error"]["code"], "unknown_root")
#             self.assertEqual(document(result)["error"]["available"], [])
#         write_root(roots, root_record("sapling", "failed", "2026-10-16T09:00:00.000Z"))
#         result = f.launch()
#         self.assertEqual(result.returncode, 1)
#         self.assertIn("none is working", document(result)["error"]["message"])
#         self.assertEqual(document(f.launch("--root", "sapling"))["build"], "1")
#         write_root(roots, root_record("second", "preparing", "2026-10-16T11:00:00.000Z"))
#         self.assertEqual(document(f.launch("--root", "second"))["build"], "2")
#         self.assertEqual(f.launch().returncode, 1)
#         write_root(roots, root_record("second", "working", "2026-10-16T11:00:00.000Z"))
#         self.assertEqual(document(f.launch())["build"], "2")
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_records_are_reread_and_only_working_roots_can_be_current

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_named_selection_uses_its_own_root_and_refuses_conflicting_selectors
#     def test_builds_root_named_selection_uses_its_own_root_and_refuses_conflicting_selectors(self) -> None:
#         """builds.root-named covers independent current Root, explicit agreement, warnings and unavailable Builds."""
#         f = self.fixture()
#         f.build("--root", "sapling")
#         f.build("--root", "second")
#         self.assertEqual(document(f.launch("-v", "1", "run"))["build"], "1")
#         self.assertEqual(document(f.launch("--root", "sapling", "-v", "1", "run"))["build"], "1")
#         conflict = f.launch("--root", "second", "-v", "1", "run")
#         self.assertEqual(conflict.returncode, 1)
#         self.assertEqual(document(conflict)["error"]["code"], "invalid_input")
#         for root in ("sapling", "second"):
#             self.assertIn(root, document(conflict)["error"]["message"])
#         for number in ("0", "01", "A", "missing", "3"):
#             result = f.launch("--root", "sapling", "-v", number, "run")
#             self.assertEqual(result.returncode, 1)
#             self.assertEqual(document(result)["error"]["code"], "build_unavailable")
#             self.assertEqual(document(result)["error"]["available"], ["1"])
#         self.assertEqual(f.call("withdraw", f"{f.component}@1", "--reason", "private defect").returncode, 0)
#         result = f.launch("-v", "1", "run")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertIn(b"withdrawn: private defect", result.stderr)
#         self.assertEqual(f.launch("--root", "sapling", "run").returncode, 1)
#         path = Path(f.path("1/build.json"))
#         record = json.loads(path.read_text())
#         record.update(status="failed", checks=[{"name": "private", "passed": False}],
#                       failure={"stage": "check", "name": "private", "message": "synthetic failure"})
#         path.write_text(json.dumps(record))
#         result = f.launch("-v", "1", "run")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertIn(b"failed: check private", result.stderr)
#         record["status"] = "building"
#         path.write_text(json.dumps(record))
#         self.assertEqual(f.launch("-v", "1", "run").returncode, 1)
#         record["status"] = "failed"
#         path.write_text(json.dumps(record))
#         Path(f.path("1/program.py")).unlink()
#         self.assertEqual(f.launch("-v", "1", "run").returncode, 1)
#         self.assertEqual(document(f.launch())["build"], "2")
#         Path(f.home, "Library/Application Support/Arbol/roots/second/root.json").unlink()
#         missing = f.launch("-v", "2", "run")
#         self.assertEqual(document(missing)["error"]["code"], "unknown_root")
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_named_selection_uses_its_own_root_and_refuses_conflicting_selectors

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status
#     def test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status(self) -> None:
#         """builds.root-pass-through adds no Root argument and preserves the caller's process contract."""
#         f = self.fixture()
#         f.build("--root", "sapling")
#         args = ["command", "two words", "", "--root", "second", "-v", "999"]
#         result = f.launch("--root", "sapling", "-v", "1", *args, marker="root caller")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         value = document(result)
#         self.assertEqual((value["build"], value["args"], value["cwd"], value["marker"]),
#                          ("1", args, f.home, "root caller"))
#         raw = b"bytes\x00\xff\nsecond line\n"
#         echo = f.launch("--root", "sapling", "--echo", data=raw)
#         self.assertEqual((echo.returncode, echo.stdout, echo.stderr), (0, raw, b"diagnostic\n"))
#         self.assertEqual(f.launch("--root", "sapling", "--exit", "23").returncode, 23)
#         child = subprocess.Popen([os.path.join(f.bin, f.component), "--root", "sapling", "--wait"],
#                                  cwd=f.home, env=f.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#         self.addCleanup(finish, child)
#         self.assertEqual(json.loads(first_line(child))["pid"], child.pid)
#         child.send_signal(signal.SIGINT)
#         output, errors = child.communicate(timeout=10)
#         self.assertEqual((child.returncode, output, errors), (2, b"interrupted\n", b""))
#         stamp = Path(f.path("1/last-start")).read_text().strip()
#         self.assertIsNotNone(milliseconds(stamp))
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_launcher_is_standalone_and_keeps_shared_top_level_names_distinct
#     def test_builds_root_launcher_is_standalone_and_keeps_shared_top_level_names_distinct(self) -> None:
#         """builds.root-launcher-text carries no Root implementation and can start without source imports."""
#         f = self.fixture()
#         f.build("--root", "sapling")
#         text = Path(f.bin, f.component).read_text()
#         tree = ast.parse(text)
#         self.assertFalse(any(isinstance(node, ast.ImportFrom) and (node.level or
#                          node.module is not None and node.module.startswith("arbol_builds"))
#                          for node in ast.walk(tree)))
#         self.assertTrue(text.rstrip().endswith(f"sys.exit(launch_root({f.registry!r}, {f.component!r}, sys.argv[1:]))"))
#         names: dict[str, str] = {}
#         for module in ("launcher.py", "roots.py", "root_launcher.py"):
#             bound, relative = top_level_names(ROOT / "src/arbol_builds" / module)
#             self.assertTrue(all(name in names for name in relative), (module, relative, names))
#             for name, kind in bound.items():
#                 self.assertTrue(name not in names or kind.startswith("import ") and kind == names[name],
#                                 (module, name, kind, names.get(name)))
#             names.update(bound)
#         with mock.patch.dict(os.environ, f.env(), clear=True):
#             from arbol_builds.service import launcher_source
#             plain = launcher_source(f.registry, "arbol-app", PYTHON).decode()
#             trunk = launcher_source(f.registry, "arbol-trunk", PYTHON).decode()
#         self.assertNotIn("def select_root_build(", plain)
#         self.assertNotIn("def select_root_build(", trunk)
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_launcher_is_standalone_and_keeps_shared_top_level_names_distinct

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::RootComponents.test_builds_root_inventory_agrees_with_launchers_and_keeps_other_defaults_global
#     def test_builds_root_inventory_agrees_with_launchers_and_keeps_other_defaults_global(self) -> None:
#         """builds.root-inventory: explicit/current defaults agree; named introspection outlives a Root record."""
#         f = self.fixture()
#         for root in ("sapling", "sapling", "second", "second"):
#             f.build("--root", root)
#         for root, expected in (("sapling", "2"), ("second", "4")):
#             listed = f.call("list", f.component, "--root", root)
#             self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
#             self.assertEqual([r["build"] for r in document(listed) if r["default"]], [expected])
#             shown = f.call("show", f.component, "--root", root)
#             self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
#             self.assertEqual(document(shown)["build"], expected)
#             self.assertEqual(document(f.launch("--root", root))["build"], expected)
#         self.assertEqual(document(f.call("show", f.component))["build"], "4")
#         self.assertEqual([r["build"] for r in document(f.call("list", f.component)) if r["default"]], ["4"])
#         self.assertEqual(document(f.call("show", f"{f.component}@1", "--root", "sapling"))["build"], "1")
#         mismatch = f.call("show", f"{f.component}@1", "--root", "second")
#         self.assertEqual(mismatch.returncode, 1)
#         self.assertIn("belongs to Root sapling", document(mismatch)["error"]["message"])
#         f.configure(component="sample")
#         built = f.call("build", "sample", "--repo", f.repo)
#         self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
#         listed = f.call("list", "--root", "sapling")
#         defaults = {(r["component"], r["build"]) for r in document(listed) if r["default"]}
#         self.assertEqual(defaults, {("arbol-root", "2"), ("sample", "1")})
#         for command in ("list", "show"):
#             self.assertEqual(f.call(command, "sample", "--root", "sapling").returncode, 1)
#         roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#         Path(roots, "sapling/root.json").unlink()
#         # Named record introspection stays available after a Root is removed; a default selection does not.
#         self.assertEqual(document(f.call("show", f"{f.component}@1"))["build"], "1")
#         self.assertEqual(document(f.call("show", f"{f.component}@1", "--root", "sapling"))["build"], "1")
#         self.assertEqual(f.call("show", f.component, "--root", "sapling").returncode, 1)
#         self.assertEqual(f.call("list", "--root", "sapling").returncode, 1)
#         write_root(roots, root_record("second", "failed", "2026-10-16T10:00:00.000Z"))
#         listed = f.call("list")
#         self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
#         self.assertEqual([(r["component"], r["build"]) for r in document(listed) if r["default"]], [("sample", "1")])
#         no_current = f.call("show", f.component)
#         self.assertEqual(no_current.returncode, 1)
#         self.assertIn("none is working", document(no_current)["error"]["message"])
#         self.assertEqual(document(f.call("show", "sample"))["build"], "1")
# TEST-TIER-DISABLED-END tests/test_builds.py::RootComponents.test_builds_root_inventory_agrees_with_launchers_and_keeps_other_defaults_global



# class TrunkLauncher(_support.TrunkLauncher):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_launch
#     def test_builds_trunk_launch(self) -> None:
#         """builds.trunk-launch: arbol-trunk run takes the current Root and trivial, starts the newest working Build
#         whose rootContracts hold the Root's rootContract, and hands it --root <root> before the command, in RCT-0's
#         example: First Sapling and the second Root on version 1, a third Root on version 2, and Builds 3, 4 and 5 of
#         trivial with [1], [1, 2] and [2] (RCT-0.7, 0.8)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.root("second", 1, "2026-10-15T09:00:00.000Z")
#         t.root("third", 2, "2026-10-16T09:00:00.000Z", "preparing")
#         for number, contracts in (("3", [1]), ("4", [1, 2]), ("5", [2])):
#             t.build("trivial", number, contracts)
#         message = "What does build.sh do?"
#         # The second Root is current: Build 4 is the newest that fits version 1.
#         self.assertEqual(t.started("run", message), ["4", ["--root", "second", "run", message]])
#         # Once the third Root is working, it is current, and Build 5 is the newest that fits version 2.
#         t.root("third", 2, "2026-10-16T09:00:00.000Z")
#         self.assertEqual(t.started("run", message), ["5", ["--root", "third", "run", message]])
#         # Build numbers of the Trunk alone decide: a newer Build that fits nothing of the Root is passed over.
#         t.build("trivial", "6", [3])
#         self.assertEqual(t.started("run", message)[0], "5")
#         # Only a working Build that has its program is chosen; withdrawn and failed ones only when named.
#         t.build("trivial", "7", [2], "withdrawn")
#         t.build("trivial", "8", [2], "failed")
#         t.build("trivial", "9", [2], "building")
#         t.build("trivial", "a", [2], prunedAt="2026-10-16T11:00:00.000Z")
#         os.remove(os.path.join(t.registry, "arbol-trunk/trivial/a/program.py"))
#         t.build("trivial", "b", [2])
#         os.chmod(os.path.join(t.registry, "arbol-trunk/trivial/b/program.py"), 0o600)
#         self.assertEqual(t.started("run", message)[0], "5")
#         # settle and any other command go to the Build with everything after them.
#         self.assertEqual(t.started("settle", "--exchange", "7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b"),
#                          ["5", ["--root", "third", "settle", "--exchange", "7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b"]])
#         self.assertEqual(t.started("--help"), ["5", ["--root", "third", "--help"]])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_launch

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_selection
#     def test_builds_trunk_selection(self) -> None:
#         """builds.trunk-selection: --root counts only as the first argument and names the Root, a preparing or failed
#         one too; a code name names the Trunk; a second --root after the code name goes to the Build unchanged, for
#         the Build to refuse (RCT-0.7, 0.8)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.root("second", 1, "2026-10-15T09:00:00.000Z")
#         t.root("third", 2, "2026-10-16T09:00:00.000Z")
#         t.root("fourth", 1, "2026-10-17T09:00:00.000Z", "preparing")
#         t.root("fifth", 2, "2026-10-13T09:00:00.000Z", "failed")
#         for number, contracts in (("3", [1]), ("4", [1, 2]), ("5", [2])):
#             t.build("trivial", number, contracts)
#         # A Trunk of its own, whose build numbers are higher: they are never compared with those of trivial.
#         t.build("advanced", "8e", [2])
#         t.build("advanced", "8f", [1])
#         m = "What does build.sh do?"
#         self.assertEqual(t.started("run", m), ["5", ["--root", "third", "run", m]])
#         self.assertEqual(t.started("--root", "sapling", "run", m), ["4", ["--root", "sapling", "run", m]])
#         self.assertEqual(t.started("--root", "second", "run", m), ["4", ["--root", "second", "run", m]])
#         self.assertEqual(t.started("--root", "sapling", "trivial", "run", m), ["4", ["--root", "sapling", "run", m]])
#         self.assertEqual(t.started("advanced", "run", m), ["8e", ["--root", "third", "run", m]])
#         self.assertEqual(t.started("--root", "sapling", "advanced", "run", m), ["8f", ["--root", "sapling", "run", m]])
#         # A Root that is not current is started when it is named, a preparing or a failed one too.
#         self.assertEqual(t.started("--root", "fourth", "run", m), ["4", ["--root", "fourth", "run", m]])
#         self.assertEqual(t.started("--root", "fifth", "advanced", "run", m), ["8e", ["--root", "fifth", "run", m]])
#         # --root anywhere else is the Build's: after the code name, after a first --root, after the command.
#         self.assertEqual(t.started("trivial", "--root", "sapling", "run", m),
#                          ["5", ["--root", "third", "--root", "sapling", "run", m]])
#         self.assertEqual(t.started("--root", "sapling", "--root", "third", "run", m),
#                          ["4", ["--root", "sapling", "--root", "third", "run", m]])
#         self.assertEqual(t.started("run", "--root", "sapling", m), ["5", ["--root", "third", "run", "--root", "sapling", m]])
#         self.assertEqual(t.started("--root=sapling", "run"), ["5", ["--root", "third", "--root=sapling", "run"]])
#         # Options of run reach the Build after the command, unchanged.
#         self.assertEqual(t.started("run", "--detach", "--cwd", t.home, "--request", "a b'c.json", m),
#                          ["5", ["--root", "third", "run", "--detach", "--cwd", t.home, "--request", "a b'c.json", m]])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_selection

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_named_build
#     def test_builds_trunk_named_build(self) -> None:
#         """builds.trunk-named-build: -v names a Build of the Trunk, started only when it fits the Root; a withdrawn
#         one, and a failed one that has its program, start with a line on standard error; one still building,
#         pruned, failed without its program or unknown is refused (RCT-0.7, BLD-0 "Running a Build", BLD-D13)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.build("trivial", "3", [1])
#         t.build("trivial", "4", [1, 2], "withdrawn")
#         failure = {"stage": "check", "name": "unit", "message": "Check failed; see build.log."}
#         t.build("trivial", "5", [1], "failed", failure=failure)
#         t.build("trivial", "6", [1], "failed", failure=failure)
#         os.remove(os.path.join(t.registry, "arbol-trunk/trivial/6/program.py"))
#         t.build("trivial", "7", [1], "building")
#         t.build("trivial", "8", [1], prunedAt="2026-10-16T11:00:00.000Z")
#         os.remove(os.path.join(t.registry, "arbol-trunk/trivial/8/program.py"))
#         t.build("trivial", "9", [2])
#         m = "What does build.sh do?"
#         self.assertEqual(t.started("run", m), ["3", ["--root", "sapling", "run", m]])
#         self.assertEqual(t.started("-v", "3", "run", m), ["3", ["--root", "sapling", "run", m]])
#         self.assertEqual(t.started("--root", "sapling", "trivial", "-v", "3", "run", m),
#                          ["3", ["--root", "sapling", "run", m]])
#         self.assertEqual(t.run("-v", "3", "run").stderr, b"")
#         withdrawn = t.run("-v", "4", "run", m)
#         self.assertEqual([document(withdrawn)["build"], withdrawn.stderr],
#                          ["4", b"arbol-trunk/trivial@4 is withdrawn: bad answers\n"])
#         failed = t.run("trivial", "-v", "5", "run", m)
#         self.assertEqual([document(failed)["build"], failed.stderr],
#                          ["5", b"arbol-trunk/trivial@5 is failed: check unit: Check failed; see build.log.\n"])
#         # Refused, with the Builds that can be run and fit: still building, pruned, without its program, unknown,
#         # not a build number, or not fitting the Root.
#         for number, why in (("7", "is still building"), ("8", "is pruned"), ("6", "has no program to run"),
#                             ("99", "is unknown"), ("01", "is not a build number"), ("A", "is not a build number"),
#                             ("", "is not a build number"), ("9", "does not fit the Root sapling")):
#             result = t.run("-v", number, "run", m)
#             self.assertEqual([result.returncode, result.stderr], [1, b""], number)
#             refusal = document(result)
#             self.assertEqual([refusal["error"]["code"], refusal["available"]], ["no_fit", ["5", "4", "3"]], number)
#             self.assertIn(why, refusal["error"]["message"], number)
#         # -v counts only right after the code name or in its place; anywhere else it is the Build's.
#         self.assertEqual(t.started("run", "-v", "9", m), ["3", ["--root", "sapling", "run", "-v", "9", m]])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_named_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_pass_through
#     def test_builds_trunk_pass_through(self) -> None:
#         """builds.trunk-pass-through: through arbol-trunk the Build gets its arguments and environment byte for
#         byte, the standard streams, the working folder, the process, the signals and the exit status unchanged, and
#         SIGPIPE and SIGXFSZ at their default; closed standard streams reach it as /dev/null, and a Ctrl-C during the
#         start is never lost, as through a component's launcher (RCT-0.8, BLD-0.9)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.build("trivial", "1", [1])
#         # Standard streams, working folder, environment and exit status.
#         data = "ñ\u0000data\nline two\n".encode()
#         echo = t.run("--echo", data=data)
#         self.assertEqual([echo.stdout, echo.stderr, echo.returncode], [data, b"diagnostic\n", 0])
#         result = document(t.run("run", "text", marker="custom"))
#         self.assertEqual([result["args"], result["cwd"], result["marker"]],
#                          [["--root", "sapling", "run", "text"], t.home, "custom"])
#         for code in (0, 1, 2, 7, 143):
#             self.assertEqual(t.run("--exit", str(code)).returncode, code)
#         # Arguments and environment that are not UTF-8, byte for byte.
#         arguments = [b"plain", b"caf\xe9", b"\xff\xfe-not-utf8", b"\xe2\x82\xac", b""]
#         raw = subprocess.run([t.launcher.encode(), b"--bytes", *arguments],
#                              env={**{key.encode(): value.encode() for key, value in t.env().items()},
#                                   b"PROBE": b"\xff\x80value"}, capture_output=True, timeout=60, check=False)
#         self.assertEqual(document(raw), {"args": [argument.hex() for argument in arguments],
#                                          "probe": b"\xff\x80value".hex()})
#         helper = os.path.join(t.home, "execve.py")
#         Path(helper).write_text(EXECVE)
#         environment = [b"PATH=/usr/bin:/bin", b"LANG=en_US.UTF-8", b"HOME=" + t.home.encode(), b"DUP=first",
#                        b"DUP=second", b"NOEQUALS", b"X=\xff\xfe"]
#
#         def environ(*words: bytes) -> list[bytes]:
#             started = subprocess.run([PYTHON, "-I", helper, *(word.hex() for word in [*words, b"--", *environment])],
#                                      capture_output=True, timeout=60, check=False)
#             self.assertEqual(started.returncode, 0, started.stderr)
#             return [bytes.fromhex(entry) for entry in document(started)
#                     if not bytes.fromhex(entry).startswith(b"__CF_USER_TEXT_ENCODING=")]
#
#         program = os.path.join(t.registry, "arbol-trunk/trivial/1/program.py").encode()
#         self.assertEqual(environ(t.launcher.encode(), b"--environ"), environment)
#         self.assertEqual(environ(program, b"--environ"), environment)
#         # The Build is the launcher's own process, and receives its signals.
#         for number in (signal.SIGINT, signal.SIGTERM):
#             child = subprocess.Popen([t.launcher, "--wait"], env=t.env(), stdout=subprocess.PIPE)
#             self.addCleanup(finish, child)
#             self.assertEqual(json.loads(first_line(child))["pid"], child.pid)
#             child.send_signal(number)
#             self.assertEqual(child.wait(timeout=10), 2 if number == signal.SIGINT else -signal.SIGTERM)
#         # SIGPIPE and SIGXFSZ at their default, as on a direct start.
#         probe = t.build("probe", "1", [1], entry="probe.sh")
#         script = os.path.join(t.registry, "arbol-trunk/probe/1", probe["entry"])
#         Path(script).write_text('#!/bin/sh\n(yes; echo "yes ended with $?" >&2) | head -1 > /dev/null\n'
#                                 '(ulimit -f 0; printf x > "$(dirname "$0")/written")\n'
#                                 'echo "write ended with $?" >&2\n')
#         os.chmod(script, 0o755)
#
#         def ended(result: Result) -> list[bytes]:
#             return [line for line in result.stderr.splitlines() if b" ended with " in line]
#
#         direct = subprocess.run([script], env=ENV, capture_output=True, timeout=30, check=False)
#         self.assertEqual(ended(direct), [b"yes ended with 141", b"write ended with 153"])
#         self.assertEqual(ended(t.run("probe", "run")), ended(direct))
#         # Standard input and output that the caller closed reach the Build as /dev/null, and a refusal ends quietly.
#         closed = ["/bin/sh", "-c", 'exec "$@" <&- >&-', "sh"]
#         launched = subprocess.run([*closed, t.launcher, "--echo"], env=t.env(), capture_output=True, timeout=60,
#                                   check=False)
#         self.assertEqual([launched.returncode, launched.stderr], [0, b"diagnostic\n"])
#         refused = subprocess.run([*closed, t.launcher, "unknown", "run"], env=t.env(), capture_output=True,
#                                  timeout=60, check=False)
#         self.assertEqual([refused.returncode, refused.stdout, refused.stderr], [1, b"", b""])
#         # A Ctrl-C at any moment of the start ends the launcher by SIGINT, or reaches the Build; it is never lost,
#         # and no traceback points into the launcher's own lines. One while Python itself starts can print one at
#         # line 0, or stop Python with status 1, as BLD-0 says.
#         inside = re.compile(rb'File "' + re.escape(t.launcher.encode()) + rb'", line [1-9]')
#         pause = t.build("pause", "1", [1], entry="pause.sh")
#         script = os.path.join(t.registry, "arbol-trunk/pause/1", pause["entry"])
#         Path(script).write_text("#!/bin/sh\nexec sleep 5\n")
#         os.chmod(script, 0o755)
#         outcomes: dict[object, int] = {}
#         for attempt in range(100):
#             child = subprocess.Popen([t.launcher, "pause", "run"], env=t.env(), stdin=subprocess.DEVNULL,
#                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
#             self.addCleanup(finish, child)
#             time.sleep((attempt % 25) / 1000)
#             child.send_signal(signal.SIGINT)
#             try:
#                 outcome: object = child.wait(timeout=4)
#             except subprocess.TimeoutExpired:
#                 outcome = "lost"
#             assert child.stderr is not None
#             if inside.search(child.stderr.read()):
#                 outcome = "traceback"
#             outcomes[outcome] = outcomes.get(outcome, 0) + 1
#         self.assertLessEqual(set(outcomes), {-signal.SIGINT, 1}, outcomes)
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_pass_through

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_refusals
#     def test_builds_trunk_refusals(self) -> None:
#         """builds.trunk-refusals: arbol-trunk checks the call, then the Root, then the Trunk, and refuses in one
#         line with exit status 1: invalid_input without a command and for list after -v or with more after it;
#         unknown_root for a Root identifier that is not one, a Root without a readable record, and no Root named
#         while none is working, with a message that says which; unknown_trunk for a code name that is not one or
#         that the registry does not know (RCT-0.9, BLD-D17)."""
#         t = Trunks(self)
#         t.build("trivial", "1", [1])
#
#         def refused(*args: str) -> tuple[str, str]:
#             result = t.run(*args)
#             self.assertEqual([result.returncode, result.stderr, result.stdout.count(b"\n")], [1, b"", 1], args)
#             refusal = document(result)
#             self.assertEqual([sorted(refusal), sorted(refusal["error"]), refusal["available"]],
#                              [["available", "error"], ["code", "message"], []], args)
#             return str(refusal["error"]["code"]), str(refusal["error"]["message"])
#
#         # No Root at all, then only one in preparation and one that failed: there is no current Root.
#         self.assertEqual(refused("run", "m")[0], "unknown_root")
#         self.assertIn("none is working", refused("run", "m")[1])
#         t.root("fourth", 1, "2026-10-17T09:00:00.000Z", "preparing")
#         t.root("fifth", 1, "2026-10-13T09:00:00.000Z", "failed")
#         self.assertIn("none is working", refused("list")[1])
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         write_root(t.roots, "{", "broken")
#         # The call first: no command, and list after -v or with more after it.
#         for args in ([], ["--root"], ["--root", "sapling"], ["trivial"], ["-v", "1"], ["-v"],
#                      ["--root", "sapling", "trivial", "-v", "1"], ["--root", "Sapling"], ["unknown"]):
#             self.assertEqual(refused(*args), ("invalid_input", "No command: arbol-trunk [--root <root>] [<code name>] "
#                                                                "[-v <build>] <command> …, where the command is run, "
#                                                                "settle or list."), args)
#         for args in (["-v", "1", "list"], ["trivial", "-v", "1", "list"], ["list", "trivial"], ["list", "--root", "x"],
#                      ["--root", "nowhere", "list", "x"]):
#             code, message = refused(*args)
#             self.assertEqual(code, "invalid_input", args)
#             self.assertIn("list takes no -v and nothing after it", message, args)
#         # Then the Root.
#         for value in ("", "Sapling", "../sapling", "sap ling", "säpling", "-x", "sapling/", "sapling\n"):
#             code, message = refused("--root", value, "run", "m")
#             self.assertEqual(code, "unknown_root", value)
#             self.assertIn("is not a Root identifier", message, value)
#         for name in ("nowhere", "broken"):
#             code, message = refused("--root", name, "run", "m")
#             self.assertEqual(code, "unknown_root", name)
#             self.assertIn(f"There is no Root {name}: ", message)
#             self.assertIn(os.path.join(t.roots, name, "root.json"), message)
#         self.assertEqual(refused("--root", "nowhere", "unknown", "run", "m")[0], "unknown_root")
#         # Then the Trunk: a code name that is not one, or one with no folder in builds/arbol-trunk/.
#         os.makedirs(os.path.join(t.home, "elsewhere/1"))
#         os.symlink(os.path.join(t.home, "elsewhere"), os.path.join(t.registry, "arbol-trunk/linked"))
#         Path(t.registry, "arbol-trunk/plain").write_text("not a folder")
#         for code_name in ("unknown", "Trivial", "tri-vial", "a" * 33, "1trivial", "linked", "plain", "trïvial"):
#             code, message = refused(code_name, "run", "m")
#             self.assertEqual(code, "unknown_trunk", code_name)
#             self.assertIn("There is no Trunk", message, code_name)
#             self.assertEqual(refused("--root", "sapling", code_name, "list")[0], "unknown_trunk", code_name)
#         # Text that is not UTF-8 is shown as U+FFFD, and the refusal is still one line of JSON.
#         result = subprocess.run([t.launcher.encode(), b"--root", b"\xff", b"run"], env=t.env(), capture_output=True,
#                                 timeout=60, check=False)
#         self.assertEqual([result.returncode, document(result)["error"]["code"]], [1, "unknown_root"])
#         self.assertIn("�", document(result)["error"]["message"])
#         self.assertEqual(t.started("run", "m"), ["1", ["--root", "sapling", "run", "m"]])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_refusals

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_no_fit
#     def test_builds_trunk_no_fit(self) -> None:
#         """builds.trunk-no-fit: with no working Build of the Trunk that fits the Root, or a named one that does not
#         fit, arbol-trunk refuses with no_fit, and available lists the runnable Builds of that Trunk that fit, newest
#         first; it never takes a Build of another Trunk, whatever its number (RCT-0.9, BLD-0.22)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.root("third", 2, "2026-10-13T09:00:00.000Z")
#
#         def no_fit(*args: str) -> tuple[list[str], str]:
#             result = t.run(*args)
#             self.assertEqual([result.returncode, result.stderr, result.stdout.count(b"\n")], [1, b"", 1], args)
#             refusal = document(result)
#             self.assertEqual([sorted(refusal), sorted(refusal["error"]), refusal["error"]["code"]],
#                              [["available", "error"], ["code", "message"], "no_fit"], args)
#             return list(refusal["available"]), str(refusal["error"]["message"])
#
#         # A Trunk the registry knows, whose folder holds no Build that can be read.
#         os.makedirs(os.path.join(t.registry, "arbol-trunk/trivial/1"))
#         Path(t.registry, "arbol-trunk/trivial/1/build.json").write_text("{")
#         self.assertEqual(no_fit("run", "m")[0], [])
#         t.build("trivial", "3", [2])
#         t.build("trivial", "4", [2, 3])
#         available, message = no_fit("run", "m")
#         self.assertEqual(available, [])
#         self.assertIn("No working Build of arbol-trunk/trivial fits the Root sapling", message)
#         self.assertIn("Root Contract version 1", message)
#         # Builds that fit and can be run when named, but none working: run refuses, and lists them.
#         t.build("trivial", "5", [1], "failed")
#         t.build("trivial", "6", [1, 3], "withdrawn")
#         t.build("trivial", "7", [1], "building")
#         t.build("trivial", "8", [1], prunedAt="2026-10-16T11:00:00.000Z")
#         os.remove(os.path.join(t.registry, "arbol-trunk/trivial/8/program.py"))
#         self.assertEqual(no_fit("run", "m")[0], ["6", "5"])
#         available, message = no_fit("-v", "3", "run", "m")
#         self.assertEqual(available, ["6", "5"])
#         self.assertIn("arbol-trunk/trivial@3 does not fit the Root sapling: it implements Root Contract versions 2, "
#                       "and the Root uses 1", message)
#         self.assertEqual(no_fit("--root", "third", "-v", "5", "run", "m")[0], ["4", "3"])
#         # Another Trunk with far higher numbers that fits: never a fallback for trivial, and the reverse.
#         t.build("advanced", "ff", [1])
#         self.assertEqual(no_fit("run", "m")[0], ["6", "5"])
#         self.assertEqual(no_fit("-v", "ff", "run", "m")[0], ["6", "5"])
#         self.assertEqual(no_fit("advanced", "-v", "6", "run", "m")[0], ["ff"])
#         self.assertEqual(t.started("advanced", "run", "m"), ["ff", ["--root", "sapling", "run", "m"]])
#         self.assertEqual(no_fit("--root", "third", "advanced", "run", "m")[0], [])
#         # A working Build that fits ends the refusal; the newest of them is started.
#         t.build("trivial", "2", [1])
#         self.assertEqual(t.started("run", "m"), ["2", ["--root", "sapling", "run", "m"]])
#         self.assertEqual(t.started("--root", "third", "run", "m"), ["4", ["--root", "third", "run", "m"]])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_no_fit

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_list
#     def test_builds_trunk_list(self) -> None:
#         """builds.trunk-list: arbol-trunk list prints, from the Root's record and the Build records alone, the Root,
#         its rootContract and every Trunk with default and its Builds, each with status, rootContracts, fits and
#         runnable, in RCT-0's example (RCT-0.10)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.build("trivial", "3", [1])
#         t.build("trivial", "4", [1, 2])
#         t.build("advanced", "8f", [2])
#
#         def listed(*args: str) -> Any:
#             result = t.run(*args)
#             self.assertEqual([result.returncode, result.stderr, result.stdout.count(b"\n")], [0, b"", 1], args)
#             return document(result)
#
#         example = {"root": "sapling", "rootContract": 1, "trunks": [
#             {"trunk": "trivial", "default": True,
#              "builds": [{"build": "4", "status": "working", "rootContracts": [1, 2], "fits": True, "runnable": True,
#                          "chosen": True},
#                         {"build": "3", "status": "working", "rootContracts": [1], "fits": True, "runnable": True,
#                          "chosen": False}]},
#             {"trunk": "advanced", "default": False,
#              "builds": [{"build": "8f", "status": "working", "rootContracts": [2], "fits": False, "runnable": True,
#                          "chosen": False}]}]}
#         self.assertEqual(listed("list"), example)
#         self.assertEqual(listed("--root", "sapling", "list"), example)
#         # The same in the order of the keys of TrunkList, as one line.
#         self.assertTrue(t.run("list").stdout.startswith(b'{"root":"sapling","rootContract":1,"trunks":[{"trunk":'
#                                                         b'"trivial","default":true,"builds":[{"build":"4","status":'
#                                                         b'"working","rootContracts":[1,2],"fits":true,"runnable":true,'
#                                                         b'"chosen":true}'))
#         # Every status, and runnable as the launcher would judge a named Build; damaged records are left out.
#         t.root("third", 2, "2026-10-13T09:00:00.000Z", "failed")
#         t.build("beta", "1", [1], "failed")
#         t.build("beta", "2", [2], "withdrawn")
#         t.build("beta", "3", [2], "building")
#         t.build("beta", "4", [2.0], prunedAt="2026-10-16T11:00:00.000Z")  # type: ignore[list-item]
#         t.build("beta", "5", [1, 2])
#         os.chmod(os.path.join(t.registry, "arbol-trunk/beta/5/program.py"), 0o600)
#         os.makedirs(os.path.join(t.registry, "arbol-trunk/beta/6"))
#         Path(t.registry, "arbol-trunk/beta/6/build.json").write_text("{")
#         os.makedirs(os.path.join(t.registry, "arbol-trunk/empty"))
#         for stray in ("Stray", "list", ".hidden"):
#             os.makedirs(os.path.join(t.registry, "arbol-trunk", stray))
#         os.symlink(os.path.join(t.registry, "arbol-trunk/beta"), os.path.join(t.registry, "arbol-trunk/linked"))
#         third = listed("--root", "third", "list")
#         self.assertEqual([third["root"], third["rootContract"]], ["third", 2])
#         self.assertEqual([trunk["trunk"] for trunk in third["trunks"]], ["trivial", "advanced", "beta", "empty"])
#         self.assertEqual([trunk["default"] for trunk in third["trunks"]], [True, False, False, False])
#         beta = third["trunks"][2]["builds"]
#         self.assertEqual([[build["build"], build["status"], build["rootContracts"], build["fits"], build["runnable"]]
#                           for build in beta],
#                          [["5", "working", [1, 2], True, False], ["4", "working", [2], True, False],
#                           ["3", "building", [2], True, False], ["2", "withdrawn", [2], True, True],
#                           ["1", "failed", [1], False, True]])
#         self.assertEqual(third["trunks"][3], {"trunk": "empty", "default": False, "builds": []})
#         # A registry without Trunks lists none.
#         shutil.rmtree(os.path.join(t.registry, "arbol-trunk"))
#         self.assertEqual(listed("list"), {"root": "sapling", "rootContract": 1, "trunks": []})
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_list

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_list_chosen
#     def test_builds_trunk_list_chosen(self) -> None:
#         """builds.trunk-list-chosen: list marks as chosen the Build that run would start, for the current Root or the
#         one named; after a code name it lists that Trunk alone; it starts no Build (RCT-0.10)."""
#         t = Trunks(self)
#         t.root("sapling", 1, "2026-10-14T09:00:00.000Z")
#         t.root("second", 1, "2026-10-15T09:00:00.000Z")
#         t.root("third", 2, "2026-10-16T09:00:00.000Z", "preparing")
#         for number, contracts in (("3", [1]), ("4", [1, 2]), ("5", [2])):
#             t.build("trivial", number, contracts)
#         t.build("advanced", "8e", [2])
#         t.build("advanced", "8f", [1])
#         # Each Build's program would leave a mark if it were started.
#         for folder, _, names in os.walk(os.path.join(t.registry, "arbol-trunk")):
#             if "program.py" in names:
#                 Path(folder, "program.py").write_text(f"#!/bin/sh\ntouch {json.dumps(os.path.join(folder, 'started'))}\n"
#                                                       'exec "$(dirname "$0")/real.py" "$@"\n')
#                 Path(folder, "real.py").write_text(TRUNK_PROGRAM)
#                 os.chmod(os.path.join(folder, "real.py"), 0o755)
#
#         def chosen(*args: str) -> dict[str, list[str]]:
#             result = t.run(*args)
#             self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#             return {trunk["trunk"]: [build["build"] for build in trunk["builds"] if build["chosen"]]
#                     for trunk in document(result)["trunks"]}
#
#         def run_starts(*args: str) -> str:
#             return str(t.started(*args)[0])
#
#         for root in (None, "sapling", "second", "third"):
#             prefix = [] if root is None else ["--root", root]
#             marked = chosen(*prefix, "list")
#             self.assertEqual(marked, {"trivial": ["5" if root == "third" else "4"],
#                                       "advanced": ["8e" if root == "third" else "8f"]}, root)
#             self.assertEqual(marked["trivial"], [run_starts(*prefix, "run", "m")])
#             self.assertEqual(marked["advanced"], [run_starts(*prefix, "advanced", "run", "m")])
#             # After a code name, that Trunk alone.
#             self.assertEqual(chosen(*prefix, "advanced", "list"), {"advanced": marked["advanced"]})
#             self.assertEqual(chosen(*prefix, "trivial", "list"), {"trivial": marked["trivial"]})
#         # When the newest is withdrawn, the one before it is chosen; when none fits, none is.
#         Path(t.registry, "arbol-trunk/trivial/4/build.json").write_text(json.dumps(
#             {**json.loads(Path(t.registry, "arbol-trunk/trivial/4/build.json").read_text()), "status": "withdrawn",
#              "withdrawn": {"at": "2026-10-16T12:00:00.000Z", "reason": "bad answers"}}))
#         self.assertEqual(chosen("--root", "sapling", "list"), {"trivial": ["3"], "advanced": ["8f"]})
#         self.assertEqual(chosen("--root", "third", "list"), {"trivial": ["5"], "advanced": ["8e"]})
#         shutil.rmtree(os.path.join(t.registry, "arbol-trunk/advanced/8e"))
#         self.assertEqual(chosen("--root", "third", "advanced", "list"), {"advanced": []})
#         # list started nothing: the only marks are those of the Builds run started above.
#         started = sorted(os.path.relpath(folder, t.registry) for folder, _, names
#                          in os.walk(os.path.join(t.registry, "arbol-trunk")) if "started" in names)
#         self.assertEqual(started, ["arbol-trunk/advanced/8f", "arbol-trunk/trivial/4", "arbol-trunk/trivial/5"])
#         for name in started:
#             os.remove(os.path.join(t.registry, name, "started"))
#         chosen("list")
#         chosen("trivial", "list")
#         self.assertFalse([folder for folder, _, names in os.walk(t.registry) if "started" in names])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_list_chosen

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_first_build
#     def test_builds_trunk_first_build(self) -> None:
#         """builds.trunk-first-build: the first build of a Trunk with arbol-builds writes arbol-trunk, which then
#         starts the Build that fits the Root, handing it --root, in a home of the test's own; a withdrawal made with
#         the tool counts at the next start (BLD-0.16, RCT-0.7, 0.8, 0.10)."""
#         f = Fixture(self, "arbol-trunk/sample")
#         launcher = os.path.join(f.bin, "arbol-trunk")
#         self.assertFalse(os.path.exists(launcher))
#         records = [f.build()]
#         self.assertTrue(os.access(launcher, os.X_OK))
#         for contracts in ([1, 2], [2]):
#             f.configure(rootContracts=contracts)
#             records.append(f.build())
#         self.assertEqual([[record["build"], record["rootContracts"]] for record in records],
#                          [["1", [1]], ["2", [1, 2]], ["3", [2]]])
#         self.assertEqual(os.listdir(f.bin), ["arbol-trunk"])
#         roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
#         write_root(roots, root_record("sapling", contract=1))
#         write_root(roots, root_record("third", "preparing", "2026-10-16T09:00:00.000Z", 2))
#
#         def trunk(*args: str) -> Result:
#             return subprocess.run([launcher, *args], cwd=f.home, env=f.env(MARKER="caller"), capture_output=True,
#                                   timeout=60, check=False)
#
#         m = "What does build.sh do?"
#         started = document(trunk("sample", "run", m))
#         self.assertEqual([started["build"], started["args"], started["cwd"], started["marker"]],
#                          ["2", ["--root", "sapling", "run", m], f.home, "caller"])
#         self.assertEqual(document(trunk("--root", "third", "sample", "run", m))["build"], "3")
#         listed = document(trunk("sample", "list"))
#         self.assertEqual([[build["build"], build["fits"], build["chosen"]] for build in listed["trunks"][0]["builds"]],
#                          [["3", False, False], ["2", True, True], ["1", True, False]])
#         # The Trivial Trunk is not built here, so a call that names no Trunk finds none.
#         self.assertEqual(document(trunk("run", m))["error"]["code"], "unknown_trunk")
#         # A Build withdrawn with the tool is passed over at the next start, and runs when named.
#         self.assertEqual(f.call("withdraw", "arbol-trunk/sample@2", "--reason", "bad answers").returncode, 0)
#         self.assertEqual(document(trunk("sample", "run", m))["build"], "1")
#         named = trunk("sample", "-v", "2", "run", m)
#         self.assertEqual([document(named)["build"], named.stderr],
#                          ["2", b"arbol-trunk/sample@2 is withdrawn: bad answers\n"])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_first_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_trunk_launcher_text
#     def test_builds_trunk_launcher_text(self) -> None:
#         """builds.trunk-launcher-text: arbol-trunk is the text of launcher.py, roots.py and trunk_launcher.py
#         without their imports from the package; no module redefines a name of one before it, and each finds
#         there every name it imports (BLD-D17)."""
#         package = ROOT / "src/arbol_builds"
#         seen: dict[str, str] = {}
#         for name in ("launcher.py", "roots.py", "trunk_launcher.py"):
#             bound, relative = top_level_names(package / name)
#             for imported in relative:
#                 self.assertEqual(seen.get(imported), "definition", f"{name} imports {imported}")
#             for item, kind in bound.items():
#                 if item in seen:
#                     self.assertTrue(kind == seen[item] and kind.startswith(("import ", "from ")),
#                                     f"{name} binds {item} again: {kind}, before {seen[item]}")
#                 seen[item] = kind
#         t = Trunks(self)
#         text = Path(t.launcher).read_text(encoding="utf-8")
#         self.assertEqual(text.split("\n")[:2], [f"#!{PYTHON} -ISB", LAUNCHER_MARK])
#         self.assertTrue(text.rstrip("\n").endswith(f"sys.exit(launch_trunk({t.registry!r}, sys.argv[1:]))"))
#         imports = [line for line in text.split("\n") if line.lstrip().startswith(("from .", "import arbol_builds",
#                                                                                 "from arbol_builds"))]
#         self.assertEqual(imports, [])
#         self.assertFalse("sapling" in text)
#         self.assertEqual(stat.S_IMODE(os.stat(t.launcher).st_mode), 0o755)
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_trunk_launcher_text

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_root_records
#     def test_builds_root_records(self) -> None:
#         """builds.root-records: the record of every Root is read from the home folder at each call, and a record
#         that is missing or damaged takes only its own Root out of use (BLD-D17)."""
#         home = os.path.realpath(tempfile.mkdtemp(prefix="Arbol's roots "))
#         self.addCleanup(shutil.rmtree, home, True)
#         with mock.patch.dict(os.environ, {"HOME": home}):
#             roots = roots_folder()
#         self.assertEqual(roots, os.path.join(home, "Library/Application Support/Arbol/roots"))
#         self.assertEqual(read_roots(roots), [])
#         sapling = root_record("sapling")
#         second = root_record("second", "preparing", contract=1.0)
#         third = root_record("third", "failed", contract=2, failed={"at": "2026-10-16T08:00:00.000Z", "reason": "x"})
#         for record in (sapling, second, third):
#             write_root(roots, record)
#         # Only the four fields BLD-D17 names are read.
#         bare = {key: sapling[key] for key in ("root", "status", "createdAt", "rootContract")}
#         write_root(roots, {**bare, "root": "bare"})
#         damaged: list[tuple[str, object]] = [
#             ("broken", "{"), ("empty", "{}"), ("array", "[]"), ("nan", '{"root": "nan", "rootContract": NaN}'),
#             ("other", root_record("sapling")), ("state", root_record("state", "ready")),
#             ("unstated", {key: value for key, value in root_record("unstated").items() if key != "status"}),
#             ("time", root_record("time", created="16 October 2026")),
#             ("wide", root_record("wide", created="２０２６-10-15T00:00:00.000Z")),
#             ("zero", root_record("zero", contract=0)), ("true", root_record("true", contract=True)),
#             ("text", root_record("text", contract="1")), ("half", root_record("half", contract=1.5)),
#             ("none", {key: value for key, value in root_record("none").items() if key != "rootContract"}),
#         ]
#         for folder, given in damaged:
#             write_root(roots, given, folder)
#         # No record, a record that is a folder, and folders whose names are no Root identifier.
#         os.makedirs(os.path.join(roots, "missing"))
#         os.makedirs(os.path.join(roots, "folder/root.json"))
#         for name in ("Upper", "with-dash", "säpling", ".hidden"):
#             write_root(roots, root_record(name), name)
#         Path(roots, "file").write_text(json.dumps(root_record("file")))
#         self.assertEqual([record["root"] for record in read_roots(roots)], ["bare", "sapling", "second", "third"])
#         self.assertEqual(read_root(roots, "sapling"), sapling)
#         self.assertEqual(read_root(roots, "second"), second)
#         for name in ("broken", "other", "missing", "folder", "file", "Upper", "säpling", "../roots/sapling",
#                      "sapling/", "", "unknown"):
#             self.assertIsNone(read_root(roots, name), name)
#         # Bytes that are not UTF-8 read as U+FFFD, as in the Build records; the record stays in use.
#         Path(roots, "bytes").mkdir()
#         Path(roots, "bytes", "root.json").write_bytes(json.dumps(root_record("bytes")).encode().replace(b"Bytes", b"B\xffytes"))
#         self.assertEqual(read_root(roots, "bytes"), root_record("bytes", name="B\ufffdytes"))
#         shutil.rmtree(os.path.join(roots, "bytes"))
#         # Read again at each call: a record that is mended or damaged counts at once.
#         write_root(roots, root_record("broken"))
#         write_root(roots, "{", "sapling")
#         self.assertEqual([record["root"] for record in read_roots(roots)], ["bare", "broken", "second", "third"])
#         self.assertEqual(read_roots(os.path.join(home, "nowhere")), [])
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_root_records

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::TrunkLauncher.test_builds_current_root
#     def test_builds_current_root(self) -> None:
#         """builds.current-root: the current Root is the one created last among those in the state working, worked
#         out from the records at every call; a Root that is preparing or failed is never current (ARC-1, BLD-D17)."""
#         home = os.path.realpath(tempfile.mkdtemp(prefix="Arbol's roots "))
#         self.addCleanup(shutil.rmtree, home, True)
#         roots = os.path.join(home, "roots")
#
#         def current() -> str | None:
#             record = current_root(read_roots(roots))
#             return None if record is None else str(record["root"])
#
#         self.assertIsNone(current())
#         write_root(roots, root_record("sapling", created="2026-10-15T09:30:00.000Z"))
#         self.assertEqual(current(), "sapling")
#         # A newer Root in preparation changes nothing; once it is working, it is current.
#         write_root(roots, root_record("second", "preparing", created="2026-10-16T09:30:00.000Z"))
#         self.assertEqual(current(), "sapling")
#         write_root(roots, root_record("second", created="2026-10-16T09:30:00.000Z"))
#         self.assertEqual(current(), "second")
#         # Marking the newest failed makes the one before it current again.
#         write_root(roots, root_record("second", "failed", created="2026-10-16T09:30:00.000Z"))
#         self.assertEqual(current(), "sapling")
#         # Newest by the time itself, not by its text: 11:00 in UTC is later than 12:00 two hours east.
#         write_root(roots, root_record("east", created="2026-10-16T12:00:00.000+02:00"))
#         write_root(roots, root_record("utc", created="2026-10-16T11:00:00Z"))
#         self.assertEqual(current(), "utc")
#         # Of two created at the same millisecond, the one whose identifier sorts last.
#         write_root(roots, root_record("alpha", created="2026-10-16T13:00:00.000+02:00"))
#         self.assertEqual(current(), "utc")
#         write_root(roots, root_record("zulu", created="2026-10-16T11:00:00.000Z"))
#         self.assertEqual(current(), "zulu")
#         # A damaged record takes only its own Root out of use.
#         write_root(roots, "{", "zulu")
#         self.assertEqual(current(), "utc")
#         for name in ("utc", "alpha", "east", "sapling"):
#             write_root(roots, root_record(name, "preparing"))
#         self.assertIsNone(current())
# TEST-TIER-DISABLED-END tests/test_builds.py::TrunkLauncher.test_builds_current_root



# class Locking(_support.Locking):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_prune_keeps_locked_builds_in_addition_to_the_newest_working_count
#     def test_builds_prune_keeps_locked_builds_in_addition_to_the_newest_working_count(self) -> None:
#         """builds.locked-prune retains older marks and resumes ordinary pruning after unlock."""
#         f = Fixture(self)
#         for _ in range(4):
#             f.build()
#         for number in ("1", "3"):
#             self.assertEqual(f.call("lock", f"{f.component}@{number}").returncode, 0)
#         mark = json.loads(Path(f.path("1/build.json")).read_text())["lockedAt"]
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "2"))["pruned"], ["2"])
#         for number in ("1", "3", "4"):
#             self.assertTrue(Path(f.path(number, "program.py")).is_file())
#             self.assertNotIn("prunedAt", json.loads(Path(f.path(number, "build.json")).read_text()))
#         self.assertEqual(json.loads(Path(f.path("1/build.json")).read_text())["lockedAt"], mark)
#         self.assertEqual(f.call("unlock", f"{f.component}@1").returncode, 0)
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "2"))["pruned"], ["1"])
#         self.assertFalse(Path(f.path("1/program.py")).exists())
#         self.assertTrue(Path(f.path("1/build.json")).is_file())
#         self.assertTrue(Path(f.path("1/build.log")).is_file())
#         self.assertEqual(document(f.launch())["build"], "4")
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_prune_keeps_locked_builds_in_addition_to_the_newest_working_count

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders
#     def test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders(self) -> None:
#         """builds.lock-prune-race: holding each first mutation proves both serialized outcomes."""
#         for first_operation in ("lock", "prune"):
#             with self.subTest(first=first_operation):
#                 f = Fixture(self)
#                 for _ in range(3):
#                     f.build()
#                 worker = Path(f.home, "mutation.py")
#                 worker.write_text("import json,sys\n"
#                                   f"sys.path.insert(0,{str(ROOT / 'src')!r})\n"
#                                   "from arbol_builds import service\n"
#                                   "registry,component,operation=sys.argv[1:]\n"
#                                   "original=service.save_unlocked\n"
#                                   "def held(folder,record):\n"
#                                   " if record['build']=='1':\n"
#                                   "  print('held',flush=True);sys.stdin.readline()\n"
#                                   " original(folder,record)\n"
#                                   "service.save_unlocked=held\n"
#                                   "result=(service.lock_build(registry,component,'1',True) if operation=='lock'"
#                                   " else service.prune_builds(registry,component,1))\n"
#                                   "print(json.dumps(result))\n")
#                 first = subprocess.Popen([PYTHON, "-I", "-B", str(worker), f.registry, f.component, first_operation],
#                                          env=f.env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
#                                          stderr=subprocess.PIPE)
#                 self.addCleanup(finish, first)
#                 self.assertEqual(first_line(first), b"held\n")
#                 args = (["prune", f.component, "--keep", "1"] if first_operation == "lock"
#                         else ["lock", f"{f.component}@1"])
#                 second = f.spawn(*args, "--registry-dir", f.registry)
#                 deadline = time.monotonic() + 10
#                 writers = Path(f.path(".writers"))
#                 while not list(writers.glob(f"{second.pid}-*.json")) and time.monotonic() < deadline:
#                     time.sleep(0.01)
#                 self.assertTrue(list(writers.glob(f"{second.pid}-*.json")))
#                 self.assertIsNone(second.poll())
#                 assert first.stdin is not None
#                 first.stdin.write(b"go\n")
#                 first.stdin.flush()
#                 output, errors = first.communicate(timeout=30)
#                 self.assertEqual(first.returncode, 0, output + errors)
#                 output, errors = second.communicate(timeout=30)
#                 record = json.loads(Path(f.path("1/build.json")).read_text())
#                 if first_operation == "lock":
#                     self.assertEqual(second.returncode, 0, output + errors)
#                     self.assertEqual(json.loads(output)["pruned"], ["2"])
#                     self.assertIn("lockedAt", record)
#                     self.assertNotIn("prunedAt", record)
#                     self.assertTrue(Path(f.path("1/program.py")).is_file())
#                 else:
#                     self.assertEqual(second.returncode, 1, output + errors)
#                     self.assertIn("pruned", json.loads(output)["error"]["message"])
#                     self.assertIn("prunedAt", record)
#                     self.assertNotIn("lockedAt", record)
#                     self.assertFalse(Path(f.path("1/program.py")).exists())
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock
#     def test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock(self) -> None:
#         """builds.lock-building: stale lifecycle writes cannot undo a concurrent mark or its removal."""
#         f = Fixture(self)
#         gate = Path(f.repo, "gate.py")
#         gate.write_text("from pathlib import Path\nimport sys,time\n"
#                         f"home=Path({f.home!r}); phase=sys.argv[1]\n"
#                         "(home/(phase+'-ready')).touch()\n"
#                         "while not (home/(phase+'-go')).exists():time.sleep(.01)\n")
#         command = f"{shlex.quote(PYTHON)} -I -B {shlex.quote(str(gate))}"
#         f.configure(build=[BUILD, command + " build"], checks=[
#             {"name": "sample-check", "command": CHECK}, {"name": "later-check", "command": command + " check"}])
#         child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
#
#         def ready(phase: str) -> None:
#             path = Path(f.home, phase + "-ready")
#             deadline = time.monotonic() + 15
#             while not path.exists() and child.poll() is None and time.monotonic() < deadline:
#                 time.sleep(0.01)
#             self.assertTrue(path.exists(), f"Build did not reach {phase}: {child.poll()}")
#
#         ready("build")
#         result = f.call("lock", f"{f.component}@1")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         mark = document(result)["lockedAt"]
#         self.assertEqual(document(result)["status"], "building")
#         Path(f.home, "build-go").touch()
#         ready("check")
#         after_first_write = json.loads(Path(f.path("1/build.json")).read_text())
#         self.assertEqual(after_first_write["lockedAt"], mark)
#         self.assertEqual(after_first_write["checks"], [{"name": "sample-check", "passed": True}])
#         self.assertEqual(f.call("unlock", f"{f.component}@1").returncode, 0)
#         Path(f.home, "check-go").touch()
#         output, errors = child.communicate(timeout=30)
#         self.assertEqual(child.returncode, 0, output + errors)
#         finished = json.loads(output)
#         self.assertEqual(finished["status"], "working")
#         self.assertNotIn("lockedAt", finished)
#         self.assertEqual(finished, json.loads(Path(f.path("1/build.json")).read_text()))
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_lock_and_unlock_are_idempotent_and_print_the_stored_record
#     def test_builds_lock_and_unlock_are_idempotent_and_print_the_stored_record(self) -> None:
#         """builds.lock-unlock keeps the first timestamp and makes repeated operations successful no-ops."""
#         f = Fixture(self)
#         f.build()
#         path = Path(f.path("1/build.json"))
#         first = f.call("lock", f"{f.component}@1")
#         self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
#         self.assertEqual(document(first), json.loads(path.read_text()))
#         stamp = document(first)["lockedAt"]
#         self.assertRegex(stamp, r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")
#         locked = path.read_bytes()
#         self.assertEqual(document(f.call("lock", f"{f.component}@1"))["lockedAt"], stamp)
#         self.assertEqual(path.read_bytes(), locked)
#         unlocked = f.call("unlock", f"{f.component}@1")
#         self.assertEqual(unlocked.returncode, 0, unlocked.stdout + unlocked.stderr)
#         self.assertEqual(document(unlocked), json.loads(path.read_text()))
#         self.assertNotIn("lockedAt", document(unlocked))
#         plain = path.read_bytes()
#         self.assertEqual(f.call("unlock", f"{f.component}@1").returncode, 0)
#         self.assertEqual(path.read_bytes(), plain)
#         usage = document(run_tool(f, "--help"))["usage"]
#         self.assertIn("lock <component>@<build>", usage)
#         self.assertIn("unlock <component>@<build>", usage)
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_lock_and_unlock_are_idempotent_and_print_the_stored_record

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_lock_accepts_every_unpruned_status
#     def test_builds_lock_accepts_every_unpruned_status(self) -> None:
#         """builds.lock-states allows building, failed, working and withdrawn records."""
#         f = Fixture(self)
#         original = f.build()
#         path = Path(f.path("1/build.json"))
#         for state in ("building", "failed", "working", "withdrawn"):
#             with self.subTest(state=state):
#                 record = {**original, "status": state}
#                 if state == "building":
#                     record.pop("finishedAt")
#                     record["checks"] = []
#                 if state == "failed":
#                     record["checks"] = [{"name": "sample-check", "passed": False}]
#                 if state == "withdrawn":
#                     record["withdrawn"] = {"at": original["finishedAt"], "reason": "qualification failure"}
#                 path.write_text(json.dumps(record))
#                 result = f.call("lock", f"{f.component}@1")
#                 self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#                 self.assertEqual(document(result)["status"], state)
#                 self.assertIn("lockedAt", document(result))
#                 self.assertEqual(f.call("unlock", f"{f.component}@1").returncode, 0)
#                 self.assertEqual(json.loads(path.read_text()), record)
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_lock_accepts_every_unpruned_status

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_lock_requires_an_explicit_known_unpruned_build
#     def test_builds_lock_requires_an_explicit_known_unpruned_build(self) -> None:
#         """builds.lock-refusal rejects missing, malformed, unknown and pruned targets and irrelevant options."""
#         f = Fixture(self)
#         f.build()
#         for command in ("lock", "unlock"):
#             for target in (f.component, f"{f.component}@", f"{f.component}@0", f"{f.component}@01",
#                            f"{f.component}@A", f"{f.component}@1@2", f"{f.component}@2"):
#                 with self.subTest(command=command, target=target):
#                     self.assertEqual(f.call(command, target).returncode, 1)
#             self.assertEqual(f.call(command, f"{f.component}@1", "--keep", "1").returncode, 1)
#         f.build()
#         self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["1"])
#         for command in ("lock", "unlock"):
#             result = f.call(command, f"{f.component}@1")
#             self.assertEqual(result.returncode, 1)
#             self.assertIn("pruned", document(result)["error"]["message"])
#         self.assertNotIn("lockedAt", json.loads(Path(f.path("1/build.json")).read_text()))
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_lock_requires_an_explicit_known_unpruned_build

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Locking.test_builds_locked_record
#     def test_builds_locked_record(self) -> None:
#         """builds.locked-record: a valid mark survives inventory; a damaged one cannot select a Build."""
#         f = Fixture(self)
#         record = f.build()
#         path = Path(f.path("1/build.json"))
#         stamp = "2026-10-26T14:00:00.123Z"
#         path.write_text(json.dumps({**record, "lockedAt": stamp}))
#         self.assertEqual(document(f.call("show", f"{f.component}@1"))["lockedAt"], stamp)
#         self.assertEqual(document(f.call("list", f.component))[0]["lockedAt"], stamp)
#         self.assertEqual(document(f.launch())["build"], "1")
#         for damaged in (None, True, 0, "bad", "2026-13-26T14:00:00.123Z"):
#             with self.subTest(mark=damaged):
#                 path.write_text(json.dumps({**record, "lockedAt": damaged}))
#                 self.assertEqual(f.call("show", f"{f.component}@1").returncode, 1)
#                 self.assertEqual(document(f.call("list", f.component)), [])
#                 self.assertEqual(f.launch().returncode, 1)
# TEST-TIER-DISABLED-END tests/test_builds.py::Locking.test_builds_locked_record



# class StartRecords(_support.StartRecords):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start
#     def test_builds_last_start(self) -> None:
#         """builds.last-start records default and named working, withdrawn and failed launches."""
#         f = Fixture(self)
#         for _ in range(3):
#             f.build()
#         f.call("withdraw", "sample@2", "--reason", "test withdrawal")
#         failed_path = Path(f.path("3/build.json"))
#         failed = json.loads(failed_path.read_text())
#         failed["status"] = "failed"
#         failed_path.write_text(json.dumps(failed))
#         for args, number in [((), "1"), (("-v", "1"), "1"), (("-v", "2"), "2"), (("-v", "3"), "3")]:
#             record = Path(f.path(number, "build.json"))
#             original = record.read_bytes()
#             before = time.time_ns() // 1_000_000
#             result = f.launch(*args)
#             self.assertEqual([result.returncode, document(result)["build"]], [0, number])
#             self.timestamp(Path(f.path(number, "last-start")), before)
#             self.assertEqual(record.read_bytes(), original)
#         self.assertEqual(list(Path(f.path("1")).glob("last-start.*.tmp")), [])
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_write_failure
#     def test_builds_last_start_write_failure(self) -> None:
#         """builds.last-start-write-failure: read-only folder, directory target and file-size limit never stop a Build."""
#         f = Fixture(self)
#         f.build()
#         folder = Path(f.path("1"))
#         saved = folder / "last-start"
#         previous = b"2026-01-01T00:00:00.000Z\n"
#         saved.write_bytes(previous)
#         os.chmod(folder, 0o500)
#         try:
#             self.assertEqual(document(f.launch())["build"], "1")
#             self.assertEqual(saved.read_bytes(), previous)
#         finally:
#             os.chmod(folder, 0o700)
#
#         def no_file_bytes() -> None:
#             resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
#
#         result = subprocess.run([str(Path(f.bin, f.component))], env=f.env(), capture_output=True,
#                                 preexec_fn=no_file_bytes, timeout=10, check=False)
#         self.assertEqual([result.returncode, document(result)["build"]], [0, "1"], result.stderr)
#         self.assertEqual(saved.read_bytes(), previous)
#         saved.unlink()
#         saved.mkdir()
#         self.assertEqual(document(f.launch())["build"], "1")
#         self.assertTrue(saved.is_dir())
#         self.assertEqual(list(folder.glob("last-start.*.tmp")), [])
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start_write_failure

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_disk_full
#     def test_builds_last_start_disk_full(self) -> None:
#         """builds.last-start-disk-full keeps the prior time after an ENOSPC error or a failed replacement."""
#         with tempfile.TemporaryDirectory() as folder:
#             saved = Path(folder, "last-start")
#             saved.write_bytes(b"2026-01-01T00:00:00.000Z\n")
#             original = saved.read_bytes()
#             for call in ("os.open", "os.replace"):
#                 with self.subTest(call=call), mock.patch("arbol_builds.launcher." + call,
#                                                        side_effect=OSError(errno.ENOSPC, "disk full")):
#                     record_start(folder)
#                 self.assertEqual(saved.read_bytes(), original)
#                 self.assertEqual(list(Path(folder).glob("last-start.*.tmp")), [])
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start_disk_full

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_refusal
#     def test_builds_last_start_refusal(self) -> None:
#         """builds.last-start-refusal leaves pruned/building Builds and inventory calls untouched."""
#         f = Fixture(self)
#         f.build()
#         path = Path(f.path("1/build.json"))
#         original = json.loads(path.read_text())
#         for patch in ({"status": "building"}, {"prunedAt": "2026-01-01T00:00:00.000Z"}):
#             path.write_text(json.dumps({**original, **patch}))
#             self.assertEqual(f.launch("-v", "1").returncode, 1)
#             self.assertFalse(Path(f.path("1/last-start")).exists())
#         f.call("list")
#         f.call("show", "sample@1")
#         self.assertFalse(Path(f.path("1/last-start")).exists())
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start_refusal

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_trunk_last_start
#     def test_builds_trunk_last_start(self) -> None:
#         """builds.trunk-last-start records selected Trunk Builds; list and refused selections record nothing."""
#         f = Trunks(self)
#         f.root("sapling", 1, "2026-01-01T00:00:00.000Z")
#         for number, status in [("1", "working"), ("2", "withdrawn"), ("3", "failed"), ("4", "building")]:
#             f.build("trivial", number, [1], status)
#         self.assertEqual(f.run("list").returncode, 0)
#         self.assertEqual(f.run("trivial", "list").returncode, 0)
#         self.assertEqual(f.run("-v", "4", "run").returncode, 1)
#         self.assertEqual(list(Path(f.registry).rglob("last-start")), [])
#         for args, number in [(("run",), "1"), (("-v", "2", "run"), "2"), (("-v", "3", "settle", "x"), "3")]:
#             before = time.time_ns() // 1_000_000
#             self.assertEqual(f.started(*args)[0], number)
#             self.timestamp(Path(f.registry, "arbol-trunk/trivial", number, "last-start"), before)
#         self.assertFalse(Path(f.registry, "arbol-trunk/trivial/4/last-start").exists())
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_trunk_last_start

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_inventory
#     def test_builds_last_start_inventory(self) -> None:
#         """builds.last-start-inventory derives activity for old, started, withdrawn, pruned and building Builds."""
#         f = Fixture(self)
#         first = f.build()
#         folder = Path(f.path("1"))
#         original = (folder / "build.json").read_bytes()
#         for args in [("list",), ("show", "sample"), ("show", "sample@1")]:
#             value = document(f.call(*args))
#             row = value[0] if isinstance(value, list) else value
#             self.assertEqual([row["lastStart"], row["unusedSince"]], [None, first["finishedAt"]])
#         self.assertFalse((folder / "last-start").exists())
#         self.assertEqual((folder / "build.json").read_bytes(), original)
#         f.launch()
#         stamp = (folder / "last-start").read_text().strip()
#         for args in [("list", "sample"), ("show", "sample@1")]:
#             value = document(f.call(*args))
#             row = value[0] if isinstance(value, list) else value
#             self.assertEqual([row["lastStart"], row["unusedSince"]], [stamp, stamp])
#         f.build()
#         f.call("prune", "sample", "--keep", "1")
#         self.assertEqual(sorted(p.name for p in folder.iterdir()), ["build.json", "build.log", "last-start"])
#         self.assertEqual(document(f.call("show", "sample@1"))["lastStart"], stamp)
#         f.call("withdraw", "sample@2", "--reason", "test")
#         second_path = Path(f.path("2/build.json"))
#         second = json.loads(second_path.read_text())
#         for field in ("lastStart", "unusedSince"):
#             self.assertNotIn(field, second)
#         second["status"] = "building"
#         second.pop("finishedAt")
#         second_path.write_text(json.dumps(second))
#         self.assertEqual(document(f.call("show", "sample@2"))["unusedSince"], second["startedAt"])
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start_inventory

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_fallback
#     def test_builds_last_start_fallback(self) -> None:
#         """builds.last-start-fallback handles unreadable/damaged files and ignores nonregular files without waiting."""
#         f = Fixture(self)
#         record = f.build()
#         path = Path(f.path("1/last-start"))
#         fallback = "2026-01-01T00:00:00.123Z"
#         timestamp = 1767225600.123
#         for content in (b"broken", b"\xff\xfe", b"2026-01-01T00:00:00.000Z\nextra",
#                         b"2026-02-30T00:00:00.000Z\n", b"2026-1-1T0:0:0.0Z\n"):
#             path.write_bytes(content)
#             os.utime(path, (timestamp, timestamp))
#             self.assertEqual(document(f.call("show", "sample@1"))["lastStart"], fallback)
#         path.write_text("2025-01-01T00:00:00.000Z\n")
#         os.utime(path, (timestamp, timestamp))
#         path.chmod(0)
#         try:
#             self.assertEqual(document(f.call("list"))[0]["lastStart"], fallback)
#         finally:
#             path.chmod(0o600)
#         path.unlink()
#         for kind in ("directory", "fifo", "symlink"):
#             if kind == "directory":
#                 path.mkdir()
#             elif kind == "fifo":
#                 os.mkfifo(path)
#             else:
#                 path.symlink_to(path.parent / "build.json")
#             row = document(f.call("show", "sample@1"))
#             self.assertEqual([row["lastStart"], row["unusedSince"]], [None, record["finishedAt"]])
#             if kind == "directory":
#                 path.rmdir()
#             else:
#                 path.unlink()
#         with mock.patch("arbol_builds.service.os.lstat", side_effect=PermissionError):
#             self.assertIsNone(last_start(str(path.parent)))
# TEST-TIER-DISABLED-END tests/test_builds.py::StartRecords.test_builds_last_start_fallback



# class Install(_support.Install):
# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Install.test_builds_install
#     def test_builds_install(self) -> None:
#         """builds.install installs an independent tool, with its own Python, that can create a standalone launcher."""
#         f = self.f
#         result = self.install(f"--bin-dir={self.folder}")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         installed = os.path.join(self.folder, "arbol-builds")
#         installed_roots = os.path.join(self.folder, "arbol-roots")
#         python = document(result)["python"]
#         self.assertEqual(document(result)["rootsProgram"], installed_roots)
#         self.assertEqual(Path(installed_roots).read_text().split("\n", 1)[0], f"#!{python} -ISB")
#         self.assertTrue(python.startswith(os.path.join(self.folder, ".arbol-builds/runtime/")))
#         os.chmod(installed, 0o600)
#         os.chmod(installed_roots, 0o600)
#         self.assertEqual(self.install(f"--bin-dir={self.folder}", home=False).returncode, 0)
#         self.assertEqual(stat.S_IMODE(os.stat(installed).st_mode) & 0o111, 0o111)
#         self.assertEqual(stat.S_IMODE(os.stat(installed_roots).st_mode) & 0o111, 0o111)
#         build = subprocess.run([installed, "--registry-dir", f.registry, "build", f.component, "--repo", f.repo,
#                                 "--bin-dir", f.bin], env=ENV, capture_output=True, timeout=120, check=False)
#         self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
#         self.assertEqual(Path(f.bin, f.component).read_text().split("\n", 1)[0], f"#!{python} -ISB")
#         self.assertEqual(document(f.launch())["build"], "1")
#         listed = subprocess.run([installed, "list", f"--registry-dir={f.registry}"], env=ENV, capture_output=True,
#                                 timeout=60, check=False)
#         self.assertEqual(listed.returncode, 0)
#         from test_roots import database_fixture
#
#         paths = database_fixture(self)
#         made_root = subprocess.run([installed_roots, "create", "sapling", "--name", "Private installed Root",
#                                     "--roots-dir", str(paths.roots), "--settings-dir", str(paths.settings),
#                                     "--registry-dir", str(paths.registry), "--database-config", str(paths.database_config),
#                                     "--psql", paths.psql, "--security", paths.security],
#                                    env={**ENV, "HOME": str(paths.home)}, capture_output=True, timeout=60, check=False)
#         self.assertEqual(made_root.returncode, 0, made_root.stdout + made_root.stderr)
#         self.assertEqual((document(made_root)["status"], document(made_root)["app"]), ("preparing", "0"))
#         self.assertTrue((paths.roots / "sapling/root.json").is_file())
#         self.assertEqual(self.install("--unknown").returncode, 1)
#         self.assertEqual(self.install("word").returncode, 1)
# TEST-TIER-DISABLED-END tests/test_builds.py::Install.test_builds_install

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Install.test_builds_install_refreshes_launchers
#     def test_builds_install_refreshes_launchers(self) -> None:
#         """builds.install-refreshes-launchers rewrites Node.js and Python launchers, arbol-trunk among them, leaves
#         other files alone, and removes the earlier Node.js tool and the leftovers of a stopped install."""
#         f = self.f
#         f.build()
#         registry = json.dumps(os.path.abspath(f.registry))
#         node = (f"#!/usr/bin/env node\nfunction launch(registry, component, args) {{ process.stdout.write('old\\n'); }}\n"
#                 f"launch({registry}, \"{f.component}\", process.argv.slice(2));\n")
#         Path(self.folder, f.component).write_text(node)
#         os.chmod(os.path.join(self.folder, f.component), 0o755)
#         written = Path(f.bin, f.component).read_text()
#         others = {
#             "other-tool": "#!/bin/sh\necho other\n",
#             "renamed": node,
#             "notes.txt": f"launch({registry}, \"notes.txt\", process.argv.slice(2));\n",
#             "python-renamed": written,
#             # Marked like a launcher, but its last line does not parse as one.
#             "arbol-a": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch({{[]: 1}}, \"arbol-a\", sys.argv[1:]))\n",
#             "arbol-b": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(start({registry}, \"arbol-b\", sys.argv[1:]))\n",
#             "arbol-c": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_trunk({registry}, \"arbol-c\", []))\n",
#             "arbol-d": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_root({registry}, \"arbol-d\", []))\n",
#             # The Trunks' launcher under another name.
#             "trunks-renamed": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_trunk({registry}, sys.argv[1:]))\n",
#         }
#         # The launcher arbol-trunk of an earlier install: only its last line, which names the registry, is kept.
#         Path(self.folder, "arbol-trunk").write_text(f"#!/x/python -ISB\n{LAUNCHER_MARK}\nprint('old')\n"
#                                                     f"sys.exit(launch_trunk({registry}, sys.argv[1:]))\n")
#         for name, text in others.items():
#             Path(self.folder, name).write_text(text)
#         os.symlink(os.path.join(self.folder, "other-tool"), os.path.join(self.folder, "linked"))
#         os.mkdir(os.path.join(self.folder, "folder"))
#         # A Python launcher written by this tool is refreshed as well.
#         shutil.copy2(os.path.join(f.bin, f.component), os.path.join(self.folder, "second"))
#         Path(self.folder, "second").write_text(written.replace(repr(f.component), repr("second")))
#         # A link named after the component it serves is left as a link, and its target as it is.
#         outside = Path(f.home, "outside-third")
#         outside.write_text(written.replace(repr(f.component), repr("third")))
#         os.symlink(outside, os.path.join(self.folder, "third"))
#         library = Path(self.folder, ".arbol-builds")
#         library.mkdir()
#         old = ["cli.js", "service.js", "package.json"]
#         for name in old:
#             Path(library, name).write_text("// the earlier tool\n")
#         leftovers = [Path(library, f".arbol_builds-{uuid.uuid4()}"), Path(library, f".arbol_roots-{uuid.uuid4()}"),
#                      Path(library, "runtime", f".unpacking-{uuid.uuid4()}")]
#         for leftover in leftovers:
#             leftover.mkdir(parents=True)
#         ended = subprocess.Popen(["/usr/bin/true"])
#         ended.wait()
#         leftovers += [Path(self.folder, f"arbol-builds.1.{uuid.uuid4()}.tmp"),
#                       Path(self.folder, f"arbol-roots.1.{uuid.uuid4()}.tmp"),
#                       Path(self.folder, f"{f.component}.{ended.pid}.{uuid.uuid4()}.tmp")]
#         for leftover in leftovers[-3:]:
#             leftover.write_text("unfinished")
#         # A launcher that a running build is writing stays.
#         writing = Path(self.folder, f"{f.component}.{os.getpid()}.{uuid.uuid4()}.tmp")
#         writing.write_text("being written")
#         root_fixtures = [Fixture(self, component) for component in ("arbol", "arbol-root")]
#         for fixture in root_fixtures:
#             fixture.build("--root", "sapling")
#             write_root(os.path.join(fixture.home, "Library/Application Support/Arbol/roots"), root_record("sapling"))
#             text = Path(fixture.bin, fixture.component).read_text()
#             if fixture.component == "arbol":
#                 # An older generic launcher upgrades; the other exercises future recognition of launch_root.
#                 text = text.replace("sys.exit(launch_root(", "sys.exit(launch(")
#             Path(self.folder, fixture.component).write_text(text)
#         result = self.install(f"--bin-dir={self.folder}")
#         self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
#         self.assertEqual(document(result)["launchers"], ["arbol", "arbol-root", "arbol-trunk", "sample", "second"])
#         python = document(result)["python"]
#         for name in ("sample", "second"):
#             text = Path(self.folder, name).read_text()
#             self.assertEqual(text.split("\n", 1)[0], f"#!{python} -ISB")
#             self.assertTrue(text.rstrip().endswith(f"launch({os.path.abspath(f.registry)!r}, {name!r}, sys.argv[1:]))"))
#         for fixture in root_fixtures:
#             text = Path(self.folder, fixture.component).read_text()
#             self.assertEqual(text.split("\n", 1)[0], f"#!{python} -ISB")
#             self.assertTrue(text.rstrip().endswith(
#                 f"launch_root({fixture.registry!r}, {fixture.component!r}, sys.argv[1:]))"))
#             started_root = subprocess.run([os.path.join(self.folder, fixture.component), "--root", "sapling", "probe"],
#                                           env=fixture.env(), capture_output=True, timeout=60, check=False)
#             self.assertEqual(started_root.returncode, 0, started_root.stdout + started_root.stderr)
#             self.assertEqual((document(started_root)["build"], document(started_root)["args"]), ("1", ["probe"]))
#         # arbol-trunk holds the current code for the same registry, and runs with the installed Python.
#         trunks = Path(self.folder, "arbol-trunk").read_text()
#         self.assertEqual(trunks.split("\n", 1)[0], f"#!{python} -ISB")
#         self.assertTrue(trunks.rstrip().endswith(f"launch_trunk({os.path.abspath(f.registry)!r}, sys.argv[1:]))"))
#         self.assertNotIn("print('old')", trunks)
#         self.assertIn("def launch_trunk(", trunks)
#         write_root(os.path.join(f.home, "Library/Application Support/Arbol/roots"), root_record("sapling"))
#         listed = subprocess.run([os.path.join(self.folder, "arbol-trunk"), "list"], env={**ENV, "HOME": f.home},
#                                 capture_output=True, timeout=60, check=False)
#         self.assertEqual([listed.returncode, document(listed)], [0, {"root": "sapling", "rootContract": 1, "trunks": []}])
#         started = subprocess.run([os.path.join(self.folder, f.component)], env=ENV, capture_output=True, timeout=60,
#                                  check=False)
#         self.assertEqual(document(started)["build"], "1")
#         self.assertTrue(Path(f.path("1/last-start")).is_file())
#         t = Trunks(self)
#         t.build("trivial", "1", [1])
#         shutil.copytree(Path(t.registry, "arbol-trunk"), Path(f.registry, "arbol-trunk"))
#         started_trunk = subprocess.run([os.path.join(self.folder, "arbol-trunk"), "run"],
#                                        env={**ENV, "HOME": f.home}, capture_output=True, timeout=60, check=False)
#         self.assertEqual([started_trunk.returncode, document(started_trunk)["build"]], [0, "1"])
#         self.assertTrue(Path(f.registry, "arbol-trunk/trivial/1/last-start").is_file())
#         inventory = subprocess.run([os.path.join(self.folder, "arbol-builds"), "show", "arbol-trunk/trivial@1",
#                                     "--registry-dir", f.registry], env=ENV, capture_output=True, timeout=60, check=False)
#         self.assertEqual(document(inventory)["lastStart"],
#                          Path(f.registry, "arbol-trunk/trivial/1/last-start").read_text().strip())
#         for name, text in others.items():
#             self.assertEqual(Path(self.folder, name).read_text(), text, name)
#         self.assertTrue(os.path.islink(os.path.join(self.folder, "linked")))
#         self.assertTrue(os.path.islink(os.path.join(self.folder, "third")))
#         self.assertEqual(outside.read_text(), written.replace(repr(f.component), repr("third")))
#         for path in [*(library / name for name in old), *leftovers]:
#             self.assertFalse(path.exists(), path)
#         self.assertEqual(writing.read_text(), "being written")
# TEST-TIER-DISABLED-END tests/test_builds.py::Install.test_builds_install_refreshes_launchers

# TEST-TIER-DISABLED-BEGIN tests/test_builds.py::Install.test_builds_install_refuses_spaces
#     def test_builds_install_refuses_spaces(self) -> None:
#         """builds.install-refuses-spaces: a folder whose path holds a space or a '#', or is too long, cannot name
#         the Python in a first line; nothing is created."""
#         for name in ("with space", "with#hash", "with\ttab", "a" * 200 + "/" + "b" * 200):
#             target = os.path.join(self.folder, name)
#             result = self.install(f"--bin-dir={target}")
#             self.assertEqual([result.returncode, document(result)["error"]["code"]], [1, "install_failed"], name)
#             self.assertEqual(os.listdir(self.folder), [], name)
# TEST-TIER-DISABLED-END tests/test_builds.py::Install.test_builds_install_refuses_spaces


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:13
# import errno
# TEST-TIER-IMPORTS-END tests/test_builds.py:13

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:16
# import re
# TEST-TIER-IMPORTS-END tests/test_builds.py:16

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:17
# import resource
# TEST-TIER-IMPORTS-END tests/test_builds.py:17

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:19
# import shlex
# TEST-TIER-IMPORTS-END tests/test_builds.py:19

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:21
# import signal
# TEST-TIER-IMPORTS-END tests/test_builds.py:21

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:26
# import threading
# TEST-TIER-IMPORTS-END tests/test_builds.py:26

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:29
# import uuid
# TEST-TIER-IMPORTS-END tests/test_builds.py:29

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:33
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/test_builds.py:33

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:37
# from arbol_builds import mutation, pruning  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_builds.py:37

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:38
# from arbol_builds.config import component_name  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_builds.py:38

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:39
# from arbol_builds.launcher import milliseconds, record_start, write_all  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_builds.py:39

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:40
# from arbol_builds.roots import current_root, read_root, read_roots, roots_folder  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_builds.py:40

# TEST-TIER-IMPORTS-BEGIN tests/test_builds.py:41
# from arbol_builds.service import LAUNCHER_MARK, last_start, reserve, write_launcher  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_builds.py:41

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
