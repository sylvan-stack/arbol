"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_backend as _support
from test_backend import (LIMITS ,Lifetime ,Programs ,Refused ,TEST_BUILD ,TEST_ROOT ,asyncio ,json ,os ,signal ,socket ,stat ,subprocess ,sys)


class Process(_support.Process):
# TEST-TIER-BEGIN tests/test_backend.py::Process.test_ready_modes_duplicate_and_stale_socket
    def test_ready_modes_duplicate_and_stale_socket(self) -> None:
        """backend.process-lock"""
        f = self.frame
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(f.root / "backend.sock"))
        stale.close()
        first = f.start()
        ready = f.line(first)
        self.assertEqual(
            {k: ready[k] for k in ("ready", "root", "build", "pid")},
            {"ready": True, "root": TEST_ROOT, "build": TEST_BUILD, "pid": first.pid},
        )
        self.assertEqual(stat.S_IMODE((f.root / "backend.sock").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((f.root / "backend.lock").stat().st_mode), 0o600)
        second = f.start()
        refusal = f.line(second)
        self.assertEqual(refusal["error"]["code"], "already_running")
        self.assertIn(str(first.pid), refusal["error"]["message"])
        self.assertEqual(second.wait(timeout=2), 1)
        first.send_signal(signal.SIGTERM)
        out, err = first.communicate(timeout=2)
        self.assertEqual((first.returncode, out, err), (0, b"", b""))
        self.assertFalse((f.root / "backend.sock").exists())
        third = f.start()
        self.assertTrue(f.line(third)["ready"])
# TEST-TIER-END tests/test_backend.py::Process.test_ready_modes_duplicate_and_stale_socket


# TEST-TIER-BEGIN tests/test_backend.py::Process.test_close_on_exec_and_cleanup_owns_only_its_socket
    def test_close_on_exec_and_cleanup_owns_only_its_socket(self) -> None:
        """backend.descriptor-ownership"""
        f = self.frame
        lifetime = Lifetime(f.root)
        sock = lifetime.acquire()
        self.assertFalse(os.get_inheritable(lifetime.lock))
        self.assertFalse(sock.get_inheritable())
        held = os.fstat(lifetime.lock)
        code = 'import os,json;print(json.dumps([os.fstat(i).st_ino for i in range(3,256) if os.path.exists("/dev/fd/"+str(i))]))'
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        self.assertNotIn(held.st_ino, json.loads(result.stdout))
        lifetime.path.unlink()
        lifetime.path.write_text("replacement")
        lifetime.close()
        self.assertEqual(lifetime.path.read_text(), "replacement")
# TEST-TIER-END tests/test_backend.py::Process.test_close_on_exec_and_cleanup_owns_only_its_socket


class AsyncFoundation(_support.AsyncFoundation):

# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_listing_group_killed_and_mutation_tracked
    async def test_listing_group_killed_and_mutation_tracked(self) -> None:
        """backend.child-deadlines"""
        f = self.frame
        f.behavior = {"arbol-root": {"sleep": 30, "ignoreTerm": True, "fork": True}}
        f.configure()
        p = Programs(self.selected, limits={key: 0.2 for key in LIMITS})
        self.addCleanup(p.close)
        with self.assertRaises(Refused) as caught:
            await p.call("arbol-root", ["list"], kind="list")
        self.assertEqual(caught.exception.code, "no_answer")
        await asyncio.sleep(0.05)
        p.reap()
        self.assertFalse(p.running)
        descendant = int((f.bin / "descendant.pid").read_text())
        # Killed descendants can briefly be zombies before their adopted parent reaps them.
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(descendant)], capture_output=True, text=True
        ).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)
        f.behavior = {"arbol-root": {"sleep": 1}}
        f.configure()
        mutations: list[subprocess.Popen[bytes]] = []
        for kind in ("start", "stop", "settle"):
            with self.assertRaises(Refused):
                await p.call("arbol-root", [kind], kind=kind, key=kind)
            child = p.running[(kind, self.selected.root if kind == "settle" else kind)].process
            mutations.append(child)
            self.assertIsNone(child.poll())
            with self.assertRaises(Refused) as repeated:
                await p.call("arbol-root", [kind], kind=kind, key=kind)
            self.assertEqual(repeated.exception.code, "in_progress")
        p.close()
        for child in mutations:
            self.assertEqual(await asyncio.to_thread(child.wait, timeout=2), 0)
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_listing_group_killed_and_mutation_tracked
