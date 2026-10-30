"""SYL-327 retained selections; this registry is not full DRV-5 qualification."""
from ..harness import Scenario, ScenarioHome
from .c14 import c14
from .errors import c26, c27, c28, c29, c30
from .runs import c18, c33
from .stops import c15, c17, c38
from .subscriptions import c2, c4, c5, c6, c7
from .tools import c36, c37


async def _native_only(home: ScenarioHome) -> None:
    raise ValueError(f"{home.id} is retained only for its named native variant; no generic coverage is claimed.")

SCENARIOS = [
    c2,
    c4,
    c5,
    c6,
    c7,
    c14,
    c15,
    c17,
    c18,
    c26,
    c27,
    c28,
    c29,
    c30,
    c33,
    c36,
    c37,
    c38,
    Scenario("C8", "Retained native variant", "Pi/MiMo only; explicit selection required", [], _native_only),
    Scenario("C12", "Retained native variant", "Pi/MiMo only; explicit selection required", [], _native_only),
    Scenario("C39", "Retained native variant", "Pi/MiMo only; explicit selection required", [], _native_only),
    Scenario("C42", "Retained native variant", "Pi/MiMo only; explicit selection required", [], _native_only),
]
