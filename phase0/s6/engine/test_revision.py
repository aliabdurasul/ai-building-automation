"""S6 revision engine self-test (unittest). Usage: python test_revision.py [--result <json>]"""
from __future__ import annotations

import copy
import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import revision as rv  # noqa: E402

cn = rv.cn
MODELS = Path(__file__).resolve().parents[1] / "model"
TARGET = json.loads((MODELS / "target_codesys_softplc.json").read_text(encoding="utf-8"))
P = "AHU-DEMO/AHU-01/"


def load(name: str) -> dict:
    return json.loads((MODELS / "revisions" / name).read_text(encoding="utf-8"))


def wide_target(ir: int = 16, hr: int = 16) -> dict:
    t = copy.deepcopy(TARGET)
    t["platform"]["register_capacity"] = {"HOLDING_REGISTER": hr, "INPUT_REGISTER": ir}
    return t


def chain(names, target=TARGET):
    """Builds revisions in order; returns (parent record of the last one, history, outputs)."""
    parent, history, outs = None, [], []
    for n in names:
        m = load(n) if isinstance(n, str) else n
        o = rv.build(m, target, parent, history)
        assert o["status"] == "ACCEPTED", (n, o["errors"])
        history.append({"revision": m["revision"], "active": o["lock"]["active"]})
        parent = {"model": m, "lock": o["lock"]}
        outs.append(o)
    return parent, history, outs


def addr(o: dict) -> dict:
    return {e["identity"]: (e["area"], e["address"], e["length"]) for e in o["lock"]["active"]}


def change(o: dict, ident: str) -> dict:
    return next(c for c in o["diff"]["changes"] if c["identity"] == ident)


def next_rev(m: dict, rev: int, parent: int) -> dict:
    m = copy.deepcopy(m)
    m["revision"], m["parent_revision"] = rev, parent
    return m


def sig(m: dict, tag: str, eq: str = "AHU-01") -> dict:
    return next(s for s in m["signals"] if s["tag"] == tag and s["equipment"] == eq)


class RevisionEngine(unittest.TestCase):
    def test_metadata_required(self):
        m = load("v1.json")
        for k in ("schema", "project_id", "revision"):
            bad = copy.deepcopy(m)
            del bad[k]
            o = rv.build(bad, TARGET, None, [])
            self.assertEqual(o["status"], "REJECTED", k)
            self.assertIn("SCHEMA", {e["code"] for e in o["errors"]}, k)

    def test_v1_allocation(self):
        _, _, (o,) = chain(["v1.json"])
        a = addr(o)
        self.assertEqual(a[P + "Command"], ("HOLDING_REGISTER", 0, 1))
        self.assertEqual(a[P + "Status"], ("INPUT_REGISTER", 0, 1))
        self.assertEqual(a[P + "FanSpeed"], ("INPUT_REGISTER", 1, 2))
        self.assertEqual(a[P + "SupplyTemp"], ("INPUT_REGISTER", 3, 2))
        self.assertEqual(a[P + "FanRunning"], ("DISCRETE_INPUT", 144, 1))
        self.assertEqual(o["diff"]["summary"], {"ADDED": 7, "EQUIPMENT_ADDED": 1})

    def test_add_signal_preserves_existing(self):
        _, _, (o1, o2) = chain(["v1.json", "v2.json"])
        a1, a2 = addr(o1), addr(o2)
        for i, v in a1.items():
            self.assertEqual(a2[i], v, i)
        self.assertEqual(a2[P + "ReturnTemp"], ("INPUT_REGISTER", 7, 2))
        c = change(o2, P + "ReturnTemp")
        self.assertEqual((c["type"], c["mapping"]["action"]), ("ADDED", "NEW"))
        self.assertEqual(o2["diff"]["summary"], {"ADDED": 1, "UNCHANGED": 7})

    def test_naive_allocation_would_move_signals(self):
        m = load("v2.json")
        naive = cn.allocate(rv.to_s3_model(m, TARGET, [rv.to_s3_signal(s) for s in m["signals"]]), rv.PROFILE)
        by = {e["tag"]: e["address"] for e in naive}
        self.assertNotEqual(by["SupplyTemp"], 3)

    def test_remove_signal_retires_address(self):
        _, _, (_, o2, o3) = chain(["v1.json", "v2.json", "v3.json"])
        self.assertNotIn(P + "FanSpeed", addr(o3))
        for i, v in addr(o3).items():
            self.assertEqual(addr(o2)[i], v, i)
        self.assertEqual([(r["identity"], r["address"]) for r in o3["lock"]["retired"]], [(P + "FanSpeed", 1)])
        self.assertEqual(change(o3, P + "FanSpeed")["mapping"]["action"], "RETIRED")

    def test_retired_address_never_given_to_another_signal(self):
        t = wide_target()
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json"], t)
        m = next_rev(load("v3.json"), 4, 3)
        m["variables"]["OutdoorTemp"] = {"type": "REAL", "initial": 5.0, "role": "process", "equipment": "AHU-01"}
        m["signals"].append({"equipment": "AHU-01", "tag": "OutdoorTemp", "datatype": "REAL32", "direction": "READ",
                             "modbus": {"area": "INPUT_REGISTER", "length": 2}})
        o = rv.build(m, t, parent, hist)
        self.assertEqual(o["status"], "ACCEPTED", o["errors"])
        self.assertNotIn(addr(o)[P + "OutdoorTemp"][1], (1, 2))
        on_real_target = rv.build(m, TARGET, *chain(["v1.json", "v2.json", "v3.json"])[:2])
        self.assertEqual(on_real_target["status"], "REJECTED")
        self.assertIn("ALLOCATION", {e["code"] for e in on_real_target["errors"]})

    def test_same_identity_restored(self):
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json"])
        m = next_rev(load("v2.json"), 4, 3)
        o = rv.build(m, TARGET, parent, hist)
        self.assertEqual(o["status"], "ACCEPTED", o["errors"])
        self.assertEqual(addr(o)[P + "FanSpeed"], ("INPUT_REGISTER", 1, 2))
        self.assertEqual(change(o, P + "FanSpeed")["mapping"]["action"], "RESTORED")

    def test_type_change_blocked_without_approval(self):
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json"])
        o = rv.build(load("v4_type_change.json"), TARGET, parent, hist)
        self.assertEqual(o["status"], "REJECTED")
        self.assertEqual({e["code"] for e in o["errors"]}, {"BREAKING_CHANGE_REQUIRES_APPROVAL"})
        c = change(o, P + "SupplyTemp")
        self.assertEqual((c["type"], c["from"], c["to"], c["breaking"], c["approved"]),
                         ("TYPE_CHANGED", "REAL32", "INT16", True, False))

    def test_approved_type_change_reallocates_and_retires(self):
        t = wide_target()
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json"], t)
        o = rv.build(load("v4_type_change_approved.json"), t, parent, hist)
        self.assertEqual(o["status"], "ACCEPTED", o["errors"])
        area, a, n = addr(o)[P + "SupplyTemp"]
        self.assertEqual(n, 1)
        self.assertNotIn(a, (3, 4))
        self.assertIn((P + "SupplyTemp", 3), [(r["identity"], r["address"]) for r in o["lock"]["retired"]])
        self.assertEqual(change(o, P + "SupplyTemp")["mapping"]["action"], "REALLOCATED")
        blocked = rv.build(load("v4_type_change_approved.json"), TARGET, *chain(["v1.json", "v2.json", "v3.json"])[:2])
        self.assertEqual(blocked["status"], "REJECTED")
        self.assertIn("free register", blocked["errors"][0]["message"])

    def test_direction_change_same_area_preserved(self):
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json", "v5_equipment.json"])
        o = rv.build(load("v6_direction_nonbreaking.json"), TARGET, parent, hist)
        self.assertEqual(o["status"], "ACCEPTED", o["errors"])
        c = change(o, "AHU-DEMO/AHU-02/Setpoint")
        self.assertEqual((c["type"], c["breaking"], c["mapping"]["action"]), ("DIRECTION_CHANGED", False, "PRESERVED"))
        self.assertEqual((c["from"], c["to"]), ("READ_WRITE", "WRITE"))

    def test_direction_change_needing_new_area_blocked(self):
        parent, hist, _ = chain(["v1.json", "v2.json", "v3.json", "v5_equipment.json"])
        o = rv.build(load("v6_direction_breaking.json"), TARGET, parent, hist)
        self.assertEqual(o["status"], "REJECTED")
        c = change(o, P + "SupplyTemp")
        self.assertEqual((c["type"], c["breaking"]), ("DIRECTION_CHANGED", True))
        self.assertIn("area", {f["field"] for f in c["field_changes"]})

    def test_equipment_addition(self):
        _, _, outs = chain(["v1.json", "v2.json", "v3.json", "v5_equipment.json"])
        o3, o4 = outs[2], outs[3]
        for i, v in addr(o3).items():
            self.assertEqual(addr(o4)[i], v, i)
        self.assertEqual(change(o4, "AHU-DEMO/AHU-02")["type"], "EQUIPMENT_ADDED")
        self.assertEqual(addr(o4)["AHU-DEMO/AHU-02/Setpoint"], ("HOLDING_REGISTER", 3, 2))
        self.assertEqual(addr(o4)["AHU-DEMO/AHU-02/Enable"], ("COIL", 144, 1))
        self.assertNotEqual(addr(o4)["AHU-DEMO/AHU-02/Setpoint"], addr(o4)[P + "Setpoint"])

    def test_deterministic_and_order_independent(self):
        parent, hist, _ = chain(["v1.json", "v2.json"])
        ref = rv.build(load("v3.json"), TARGET, parent, hist)
        rnd = random.Random(6)
        for _ in range(20):
            m = load("v3.json")
            rnd.shuffle(m["signals"])
            o = rv.build(m, TARGET, parent, hist)
            self.assertEqual(o["lock"], ref["lock"])
            self.assertEqual(o["diff"], ref["diff"])
            self.assertEqual(o["entries"], ref["entries"])

    def _invalid(self, mutate, code, text):
        parent, hist, _ = chain(["v1.json", "v2.json"])
        m = next_rev(load("v2.json"), 3, 2)
        mutate(m)
        o = rv.build(m, TARGET, parent, hist)
        self.assertEqual(o["status"], "REJECTED")
        msgs = " | ".join(e["message"] for e in o["errors"] if e["code"] == code)
        self.assertIn(text, msgs, o["errors"])

    def test_invalid_duplicate_tag(self):
        self._invalid(lambda m: m["signals"].append(copy.deepcopy(sig(m, "ReturnTemp"))), "DUPLICATE_TAG", "duplicate tag")

    def test_invalid_duplicate_symbol(self):
        def f(m):
            m["equipment"].append({"id": "AHU-02", "type": "AHU"})
            s = copy.deepcopy(sig(m, "ReturnTemp"))
            s["equipment"] = "AHU-02"
            m["signals"].append(s)
        self._invalid(f, "DUPLICATE_SYMBOL", "symbol ReturnTemp")

    def test_invalid_duplicate_address(self):
        def f(m):
            m["variables"]["ExhaustRaw"] = {"type": "WORD", "initial": 0, "role": "process", "equipment": "AHU-01"}
            m["signals"].append({"equipment": "AHU-01", "tag": "ExhaustRaw", "datatype": "WORD", "direction": "READ",
                                 "modbus": {"area": "INPUT_REGISTER", "address": 3}})
        self._invalid(f, "ALLOCATION", "overlaps")

    def test_invalid_real32_length_1(self):
        self._invalid(lambda m: sig(m, "ReturnTemp")["modbus"].update(length=1), "MODEL_RULE", "requires length=2")

    def test_invalid_missing_datatype(self):
        self._invalid(lambda m: sig(m, "ReturnTemp").pop("datatype"), "MODEL_RULE", "missing datatype")

    def test_invalid_missing_area(self):
        self._invalid(lambda m: sig(m, "ReturnTemp")["modbus"].pop("area"), "MODEL_RULE", "missing area")

    def test_invalid_direction(self):
        self._invalid(lambda m: sig(m, "ReturnTemp").update(direction="BIDIRECTIONAL"), "MODEL_RULE", "unsupported direction")

    def test_invalid_overlapping_real32(self):
        def f(m):
            m["variables"]["MixedAirTemp"] = {"type": "REAL", "initial": 15.0, "role": "process", "equipment": "AHU-01"}
            m["signals"].append({"equipment": "AHU-01", "tag": "MixedAirTemp", "datatype": "REAL32", "direction": "READ",
                                 "modbus": {"area": "INPUT_REGISTER", "address": 4, "length": 2}})
        self._invalid(f, "ALLOCATION", "overlaps")

    def test_invalid_capacity_exceeded(self):
        def f(m):
            for t in ("OutdoorTemp", "MixedAirTemp"):
                m["variables"][t] = {"type": "REAL", "initial": 10.0, "role": "process", "equipment": "AHU-01"}
                m["signals"].append({"equipment": "AHU-01", "tag": t, "datatype": "REAL32", "direction": "READ",
                                     "modbus": {"area": "INPUT_REGISTER", "length": 2}})
        self._invalid(f, "ALLOCATION", "free register")

    def test_invalid_unknown_equipment(self):
        self._invalid(lambda m: sig(m, "ReturnTemp").update(equipment="AHU-09"), "EQUIPMENT", "unknown equipment")


def run_to_file(path: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = sorted(t.id().split(".", 1)[1] for t in _iter(suite))
    r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    ok = r.wasSuccessful()
    out = {"step": "revision_engine_selftest", "tests_run": r.testsRun, "failures": len(r.failures),
           "errors": len(r.errors), "tests": names, "operation_status": "PASS" if ok else "FAILED",
           "reason": "%d revision engine tests passed" % r.testsRun if ok else "revision engine tests failed"}
    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0 if ok else 20


def _iter(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _iter(t)
        else:
            yield t


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--result":
        sys.exit(run_to_file(sys.argv[2]))
    unittest.main(verbosity=2)
