"""Policy seams; see package docstring."""
from apps.core.exceptions import DomainError

DECISIONS = {
    "publication": ("OQ-35", "Evidence-level transitions and publication gates are not yet approved."),
    "manufacturing": ("OQ-36", "Manufacturing authorisation and QA gates are not yet approved."),
    "support_consent": ("OQ-37", "Client consent terms for operator access are not yet approved."),
    "ownership": ("OQ-38", "Ownership and IP licensing rules are not yet approved."),
}


class PolicyNotConfigured(DomainError):
    def __init__(self, seam: str, action: str):
        decision, why = DECISIONS[seam]
        super().__init__("policy_not_configured", f"'{action}' is disabled. {why}",
                         details={"decision": decision, "seam": seam, "action": action})


def require(seam: str, action: str):
    """Guard for an action governed by an open decision. Always refuses in Phase 1."""
    raise PolicyNotConfigured(seam, action)


def status() -> dict:
    """For UIs: which actions are disabled and why."""
    return {seam: {"decision": d, "enabled": False, "reason": why} for seam, (d, why) in DECISIONS.items()}
