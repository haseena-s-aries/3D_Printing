"""Manufacturing specification: the 3D-printing settings are required only for additive manufacturing (decision of
17 Nov 2026). A cast or machined part can be marked complete without layer thickness, supports, orientation, inert gas
or printing hours."""
import copy

from apps.passports.content import SPEC_AM_ONLY, completeness

from .test_w1_passport_workspace import RL2_FULL


def _rl2(process, drop_am=True):
    rl2 = copy.deepcopy(RL2_FULL)
    rl2["manufacturing_process"] = process
    if drop_am:
        for k in SPEC_AM_ONLY:
            rl2["manufacturing_spec"].pop(k, None)
    return rl2


def test_casting_and_machining_need_no_3d_printing_settings():
    for process in ("Casting", "CNC machining", "Reverse-engineered conventional manufacture", " casting "):
        c = completeness({"rl2": _rl2(process)})["rl2"]
        assert c["complete"], (process, c["missing"])
        assert c["total"] == completeness({"rl2": copy.deepcopy(RL2_FULL)})["rl2"]["total"] - len(SPEC_AM_ONLY)


def test_additive_or_unknown_process_still_needs_them():
    for process in ("L-PBF (laser powder bed fusion)", "Hybrid: AM + CNC machining", ""):
        c = completeness({"rl2": _rl2(process)})["rl2"]
        assert not c["complete"]
        assert set(c["missing"]) == {f"manufacturing_spec.{k}" for k in SPEC_AM_ONLY}
    assert completeness({"rl2": _rl2("L-PBF (laser powder bed fusion)", drop_am=False)})["rl2"]["complete"]
