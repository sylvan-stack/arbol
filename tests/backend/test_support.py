"""The check frame's own support: the private PostgreSQL starts in a session without a locale."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from backend.recovery_support import offline, online  # noqa: E402
from backend.support import Cluster, cluster_environment  # noqa: E402


def without_locale() -> dict[str, str]:
    """This process's environment with `LANG` and every `LC_*` variable removed, as a session of the app has it."""
    return {name: value for name, value in os.environ.items() if name != "LANG" and not name.startswith("LC_")}


class Locale(unittest.TestCase):
    def test_locale_added_when_the_session_has_none(self) -> None:
        """backend.cluster-locale-added"""
        plain = without_locale()
        with mock.patch.dict(os.environ, plain, clear=True):
            environment = cluster_environment()
        self.assertEqual(environment, {**plain, "LC_ALL": "C.UTF-8"})

    def test_locale_of_the_session_kept(self) -> None:
        """backend.cluster-locale-kept"""
        plain = without_locale()
        for variables in (
            {"LANG": "C.UTF-8"},
            {"LANG": "en_US.UTF-8"},
            {"LC_ALL": "fictional"},
            {"LANG": "C", "LC_ALL": "C"},
        ):
            with self.subTest(variables=variables), mock.patch.dict(os.environ, {**plain, **variables}, clear=True):
                self.assertEqual(cluster_environment(), {**plain, **variables})

    def test_lc_ctype_alone_is_no_locale(self) -> None:
        """backend.cluster-locale-ctype"""
        plain = without_locale()
        with mock.patch.dict(os.environ, {**plain, "LC_CTYPE": "C.UTF-8"}, clear=True):
            environment = cluster_environment()
        self.assertEqual(environment, {**plain, "LC_CTYPE": "C.UTF-8", "LC_ALL": "C.UTF-8"})

    def test_cluster_starts_without_a_locale(self) -> None:
        """backend.cluster-without-locale"""
        with mock.patch.dict(os.environ, without_locale(), clear=True):
            cluster = Cluster()
        try:
            self.assertTrue(cluster.address.startswith("postgresql://bkd@"))
            self.assertIsNotNone(cluster.child)
            self.assertNotIn(b"multithreaded", cluster.log.read_bytes())
        finally:
            cluster.close()


class Restart(unittest.IsolatedAsyncioTestCase):
    async def test_restart_after_an_outage_drill_starts_without_a_locale(self) -> None:
        """backend.cluster-restart-without-locale"""
        with mock.patch.dict(os.environ, without_locale(), clear=True):
            cluster = await asyncio.to_thread(Cluster)
            try:
                await offline(cluster)
                await online(cluster)
                self.assertNotIn(b"multithreaded", cluster.log.read_bytes())
            finally:
                cluster.close()


if __name__ == "__main__":
    unittest.main()
