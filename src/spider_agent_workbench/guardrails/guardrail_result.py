
from dataclasses import dataclass

@dataclass(frozen=True)
class GuardrailResult:
    ok: bool
    reason: str | None = None