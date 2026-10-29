"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_support as _support
from backend.test_support import (
    Cluster,
    Locale,
    Path,
    ROOT,
    Restart,
    asyncio,
    cluster_environment,
    mock,
    offline,
    online,
    os,
    sys,
    unittest,
    without_locale,
)


class Locale(_support.Locale):
# TEST-TIER-BEGIN tests/backend/test_support.py::Locale.test_locale_added_when_the_session_has_none
    def test_locale_added_when_the_session_has_none(self) -> None:
        """backend.cluster-locale-added"""
        plain = without_locale()
        with mock.patch.dict(os.environ, plain, clear=True):
            environment = cluster_environment()
        self.assertEqual(environment, {**plain, "LC_ALL": "C.UTF-8"})
# TEST-TIER-END tests/backend/test_support.py::Locale.test_locale_added_when_the_session_has_none

# TEST-TIER-BEGIN tests/backend/test_support.py::Locale.test_locale_of_the_session_kept
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
# TEST-TIER-END tests/backend/test_support.py::Locale.test_locale_of_the_session_kept

# TEST-TIER-BEGIN tests/backend/test_support.py::Locale.test_lc_ctype_alone_is_no_locale
    def test_lc_ctype_alone_is_no_locale(self) -> None:
        """backend.cluster-locale-ctype"""
        plain = without_locale()
        with mock.patch.dict(os.environ, {**plain, "LC_CTYPE": "C.UTF-8"}, clear=True):
            environment = cluster_environment()
        self.assertEqual(environment, {**plain, "LC_CTYPE": "C.UTF-8", "LC_ALL": "C.UTF-8"})
# TEST-TIER-END tests/backend/test_support.py::Locale.test_lc_ctype_alone_is_no_locale

# TEST-TIER-BEGIN tests/backend/test_support.py::Locale.test_cluster_starts_without_a_locale
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
# TEST-TIER-END tests/backend/test_support.py::Locale.test_cluster_starts_without_a_locale



class Restart(_support.Restart):
# TEST-TIER-BEGIN tests/backend/test_support.py::Restart.test_restart_after_an_outage_drill_starts_without_a_locale
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
# TEST-TIER-END tests/backend/test_support.py::Restart.test_restart_after_an_outage_drill_starts_without_a_locale
