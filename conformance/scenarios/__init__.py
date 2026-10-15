"""The registry: every scenario of DRV-5, in the order the report lists them."""

from __future__ import annotations

from ..harness import Scenario
from .c1 import c1
from .c14 import c14
from .c31 import c31
from .c32 import c32
from .c40 import c40
from .errors import c26, c27, c28, c29, c30
from .runs import c10, c11, c12, c13, c18, c19, c20, c33, c42, c43
from .stops import c15, c16, c17, c38
from .subscriptions import c2, c3, c4, c5, c6, c7, c8, c39, c41
from .tools import c9, c25, c35, c36, c37

SCENARIOS: list[Scenario] = [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14, c15, c16, c17, c18, c19, c20,
                             c25, c26, c27, c28, c29, c30, c31, c32, c33, c35, c36, c37, c38, c39, c40, c41, c42, c43]
