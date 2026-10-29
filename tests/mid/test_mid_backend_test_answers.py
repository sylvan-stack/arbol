"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_answers as _support
from backend.test_answers import (
    Answering,
    Any,
    CONTROL_BYTES,
    Error,
    PUBLICATION_SECONDS,
    Params,
    Path,
    ROOT,
    Trunk,
    WindowFixture,
    answer_params,
    asyncio,
    chat,
    form,
    json,
    mock,
    os,
    sys,
)


class Answering(_support.Answering):


# TEST-TIER-BEGIN tests/backend/test_answers.py::Answering.test_never_create_or_follow_control_and_reject_replaced_identity
    async def test_never_create_or_follow_control_and_reject_replaced_identity(self) -> None:
        """answers.file-identity; answers.no-create"""
        trunk = await self.make()
        trunk.event("ask_opened", askId="ask", ask=form())
        control = trunk.folder / "control"
        control.unlink()
        await self.refused(trunk, {"type": "decline"}, "no_answer")
        self.assertFalse(control.exists())
        target = self.frame.base / "unrelated"
        target.write_bytes(b"untouched")
        target.chmod(0o600)
        control.symlink_to(target)
        with self.assertRaises(Error):
            await self.answer(trunk, {"type": "decline"})
        self.assertEqual(target.read_bytes(), b"untouched")
        control.unlink()
        os.mkfifo(control, 0o600)
        with self.assertRaises(Error):
            await asyncio.wait_for(self.answer(trunk, {"type": "decline"}), 0.5)
        control.unlink()
        control.touch(mode=0o600)
        verify = self.backend.controls.answers.verify
        def replaced(folder: Any, fd: int) -> None:
            control.rename(trunk.folder / "old-control")
            control.touch(mode=0o600)
            verify(folder, fd)
        with mock.patch.object(self.backend.controls.answers, "verify", side_effect=replaced):
            await self.refused(trunk, {"type": "decline"}, "no_answer")
        self.assertEqual((trunk.folder / "old-control").read_bytes(), b"")
# TEST-TIER-END tests/backend/test_answers.py::Answering.test_never_create_or_follow_control_and_reject_replaced_identity
