"""Seams for business rules that are still open in BRD v0.4.

Until the business owner records a decision, each guarded action is refused with
HTTP 409 and error code `policy_not_configured`. No approval or release rule is invented here.

| Seam | Decision | Guards |
|---|---|---|
| publication | OQ-35 | passport revision submit/approve, evidence-level change, publication |
| manufacturing | OQ-36 | manufacturing eligibility, per-order release |
| support_consent | OQ-37 | consent capture for operator access (assignment itself is decided: OQ-02) |
| ownership | OQ-38 | ownership/licence-based download and export rules |
"""
