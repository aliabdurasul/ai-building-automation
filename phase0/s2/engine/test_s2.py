"""S2 multi-equipment self-test (unittest, offline). Usage: python test_s2.py [--result <json>]"""
from __future__ import annotations

import copy
import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "s6" / "generator"))
import regenerate as rg  # noqa: E402

lt = rg.logic_module()
MODELS = ROOT / "s2" / "model"
TEMPLATES = ROOT / "s2" / "logic" / "templates"
TARGET_BYTES = (MODELS / "target_codesys_softplc.json").read_bytes()
AHU_WORDS = ("FanRunning", "FanCommand", "FanFault", "SupplyTemp", "Setpoint", "HeatingValve", "Mb_Command",
             "Mb_Status", "AHU")
VENDOR_WORDS = ("CODESYS", "codesys", "ScriptEngine", "CDAB", "ABCD", "byte_order", "word_order", "register_order",
                "device_id", ".project", "Modbus_TCP_Server")
P = "PUMP-DEMO/PUMP-01/"


def mbytes(m: dict) -> bytes:
    return (json.dumps(m, indent=2) + "\n").encode("utf-8")


def load(name: str) -> dict:
    return json.loads((MODELS / name).read_text(encoding="utf-8"))


def render(m: dict, parent=None, history=None):
    return rg.render(mbytes(m), TARGET_BYTES, parent, history or [], lt.make_bundle(m))


def chain(models):
    parent, history, outs = None, [], []
    for m in models:
        v, f = render(m, parent, history)
        assert v["status"] == "ACCEPTED", (m["revision"], v["errors"])
        lock = json.loads(f["engineering/allocation.json"])
        history.append({"revision": m["revision"], "active": lock["active"]})
        parent = {"model": m, "lock": lock}
        outs.append((v, f))
    return parent, history, outs


def active(f) -> dict:
    return {e["identity"]: e for e in json.loads(f["engineering/allocation.json"])["active"]}


def diff_of(f) -> dict:
    return {c["identity"]: c for c in json.loads(f["engineering/revision_diff.json"])["changes"]}


class Templates(unittest.TestCase):
    def test_template_files_are_well_formed(self):
        for p in sorted(TEMPLATES.glob("*.json")):
            t = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(t["schema"], lt.SCHEMA)
            self.assertEqual(t["id"], p.stem)
            used = {m for line in t["body"] for m in lt.PLACEHOLDER.findall(line)}
            self.assertLessEqual(used, set(t["slots"]) | set(t.get("parameters") or {}) | {"equipment"}, p.name)
            self.assertFalse(set(t["slots"]) & set(t.get("parameters") or {}), p.name)
            for st in (t.get("behavior_test") or {}).get("steps", []):
                keys = set(st.get("modbus_write", {})) | set(st.get("plc_write", {})) | set(st["expect"])
                self.assertLessEqual(keys, set(t["slots"]), (p.name, st["name"]))

    def test_slot_type_mismatch_rejected(self):
        m = load("pump_v1.json")
        m["variables"]["PumpState"]["type"] = "REAL"
        errs = lt.check(m, json.loads(lt.make_bundle(m)))
        self.assertTrue(any("needs INT" in e["message"] for e in errs), errs)

    def test_unknown_slot_and_free_text_rejected(self):
        m = load("pump_v1.json")
        m["equipment"][0]["logic"]["bind"] = {"NoSuchSlot": "PumpState"}
        self.assertTrue(any("unknown slots" in e["message"] for e in lt.check(m, json.loads(lt.make_bundle(m)))))
        m = load("combined_v1.json")
        m["equipment"][0]["logic"] = "FanRunning := StartCommand;"
        self.assertTrue(any("free-text" in e["message"] for e in lt.check(m, json.loads(lt.make_bundle(m)))))

    def test_bundle_pins_template_content(self):
        m = load("pump_v1.json")
        stored = lt.make_bundle(m)
        with tempfile.TemporaryDirectory() as d:
            t = json.loads((TEMPLATES / "PUMP_BASIC_V1.json").read_text(encoding="utf-8"))
            t["body"] = [line.replace(":= 9;", ":= 8;") for line in t["body"]]
            (Path(d) / "PUMP_BASIC_V1.json").write_text(json.dumps(t), encoding="utf-8")
            changed = lt.make_bundle(m, Path(d))
        self.assertNotEqual(stored, changed)
        a = rg.render(mbytes(m), TARGET_BYTES, None, [], stored)[1]
        b = rg.render(mbytes(m), TARGET_BYTES, None, [], changed)[1]
        self.assertIn(b"PumpState := 9;", a["generated/plc/PLC_PRG_impl.st"])
        self.assertIn(b"PumpState := 8;", b["generated/plc/PLC_PRG_impl.st"])
        self.assertNotEqual(json.loads(a["engineering/validation.json"])["logic_templates_sha256"],
                            json.loads(b["engineering/validation.json"])["logic_templates_sha256"])


class Pump(unittest.TestCase):
    def test_pump_model_is_vendor_neutral_and_unaddressed(self):
        for n in ("pump_v1.json", "pump_v2.json", "pump_v3.json", "pump_v4_type_change.json", "combined_v1.json",
                  "ahu_v1.json"):
            text = (MODELS / n).read_text(encoding="utf-8")
            for w in VENDOR_WORDS:
                self.assertNotIn(w, text, (n, w))
        for s in load("pump_v1.json")["signals"]:
            self.assertNotIn("address", s["modbus"], s["tag"])

    def test_pump_v1_generation(self):
        v, f = render(load("pump_v1.json"))
        self.assertEqual(v["status"], "ACCEPTED", v["errors"])
        self.assertEqual(v["stages"].get("logic_template"), "PASS")
        st = f["generated/plc/PLC_PRG.st"].decode()
        for w in AHU_WORDS:
            self.assertIsNone(re.search(r"\b%s\b" % w, st), w)
        self.assertIn("CASE PumpState OF", st)
        self.assertIn("PUMP-DEMO: PUMP-01 (PUMP)", st)
        plan = json.loads(f["engineering/codesys_plan.json"])
        self.assertEqual(plan["project_file"], "AI_BMS_S2_PUMP_DEMO_r001.project")
        a = active(f)
        self.assertEqual(sorted(a), sorted(P + t for t in ("StartCommand", "StopCommand", "PumpRunning", "PumpFault",
                                                          "PumpState", "PumpSpeed", "Pressure")))
        self.assertEqual({a[P + t]["area"] for t in ("StartCommand", "StopCommand")}, {"COIL"})
        self.assertEqual((a[P + "PumpSpeed"]["area"], a[P + "PumpSpeed"]["length"]), ("INPUT_REGISTER", 2))
        inst = json.loads(f["engineering/logic_instances.json"])["instances"]
        self.assertEqual([(i["equipment"], i["template"]) for i in inst], [("PUMP-01", "PUMP_BASIC_V1")])

    def test_revisions_add_remove_preserve(self):
        _, _, outs = chain([load("pump_v1.json"), load("pump_v2.json"), load("pump_v3.json")])
        a1, a2, a3 = (active(f) for _, f in outs)
        d2, d3 = diff_of(outs[1][1]), diff_of(outs[2][1])
        self.assertEqual(d2[P + "FlowRate"]["type"], "ADDED")
        self.assertEqual(d2[P + "FlowRate"]["mapping"]["action"], "NEW")
        for i in a1:
            self.assertEqual(d2[i]["mapping"]["action"], "PRESERVED", i)
            self.assertEqual((a1[i]["area"], a1[i]["address"]), (a2[i]["area"], a2[i]["address"]), i)
        self.assertEqual(d3[P + "Pressure"]["type"], "REMOVED")
        self.assertEqual(d3[P + "Pressure"]["mapping"]["action"], "RETIRED")
        self.assertNotIn(P + "Pressure", a3)
        for i in a3:
            self.assertEqual((a2[i]["area"], a2[i]["address"]), (a3[i]["area"], a3[i]["address"]), i)
        retired = json.loads(outs[2][1]["engineering/allocation.json"])["retired"]
        self.assertIn(P + "Pressure", [r["identity"] for r in retired])

    def test_breaking_type_change_requires_approval(self):
        parent, history, _ = chain([load("pump_v1.json"), load("pump_v2.json"), load("pump_v3.json")])
        m4 = load("pump_v4_type_change.json")
        v, f = render(m4, parent, history)
        self.assertEqual(v["status"], "REJECTED")
        self.assertTrue(any(e["code"] == "BREAKING_CHANGE_REQUIRES_APPROVAL" and "TYPE_CHANGED" in e["message"]
                            for e in v["errors"]), v["errors"])
        ch = diff_of(f)[P + "PumpSpeed"]
        self.assertEqual((ch["type"], ch["breaking"], ch["approved"]), ("TYPE_CHANGED", True, False))
        self.assertNotIn("engineering/codesys_plan.json", f)
        m4a = copy.deepcopy(m4)
        m4a["approvals"] = [{"identity": P + "PumpSpeed", "change": "TYPE_CHANGED", "by": "selftest"}]
        va, fa = render(m4a, parent, history)
        self.assertEqual(va["status"], "ACCEPTED", va["errors"])
        self.assertEqual(diff_of(fa)[P + "PumpSpeed"]["mapping"]["action"], "REALLOCATED")


class MultiEquipment(unittest.TestCase):
    def test_combined_identities_isolated(self):
        v, f = render(load("combined_v1.json"))
        self.assertEqual(v["status"], "ACCEPTED", v["errors"])
        a = active(f)
        self.assertIn("BMS-DEMO/AHU-01/Command", a)
        self.assertIn("BMS-DEMO/PUMP-01/StartCommand", a)
        self.assertEqual(len({e["symbol"] for e in a.values()}), len(a))
        mp = json.loads(f["engineering/modbus_mapping.json"])
        self.assertEqual({s["equipment"] for s in mp["signals"]}, {"AHU-01", "PUMP-01"})
        impl = f["generated/plc/PLC_PRG_impl.st"].decode()
        self.assertIn("IF PUMP01_StartCommand = TRUE AND PUMP01_StopCommand = FALSE THEN", impl)
        self.assertIn("IF StartCommand = TRUE AND FanFault = FALSE THEN", impl)
        self.assertLess(impl.index("FanCommand := TRUE"), impl.index("CASE PumpState OF"))
        inst = json.loads(f["engineering/logic_instances.json"])["instances"]
        self.assertEqual([i["equipment"] for i in inst], ["AHU-01", "PUMP-01"])
        self.assertEqual(inst[1]["bind"]["StartCommand"], "PUMP01_StartCommand")

    def test_s1_words_stay_pinned_in_combined(self):
        a = active(render(load("combined_v1.json"))[1])
        self.assertEqual((a["BMS-DEMO/AHU-01/Command"]["area"], a["BMS-DEMO/AHU-01/Command"]["address"]),
                         ("HOLDING_REGISTER", 0))
        self.assertEqual((a["BMS-DEMO/AHU-01/Status"]["area"], a["BMS-DEMO/AHU-01/Status"]["address"]),
                         ("INPUT_REGISTER", 0))

    def test_ahu_template_equivalent_to_builtin(self):
        legacy = rg.render((ROOT / "s6" / "model" / "revisions" / "v1.json").read_bytes(),
                           (ROOT / "s6" / "model" / "target_codesys_softplc.json").read_bytes(), None, [])[1]
        templ = render(load("ahu_v1.json"))[1]
        self.assertEqual(legacy["generated/plc/PLC_PRG_impl.st"], templ["generated/plc/PLC_PRG_impl.st"])
        self.assertEqual(json.loads(legacy["engineering/allocation.json"])["active"],
                         json.loads(templ["engineering/allocation.json"])["active"])


class Determinism(unittest.TestCase):
    def test_render_is_byte_stable(self):
        for n in ("pump_v1.json", "combined_v1.json"):
            self.assertEqual(render(load(n))[1], render(load(n))[1], n)

    def test_signal_and_variable_order_irrelevant_to_allocation(self):
        base = load("combined_v1.json")
        ref = render(base)[1]
        rnd = random.Random(2)
        for _ in range(5):
            m = copy.deepcopy(base)
            rnd.shuffle(m["signals"])
            items = list(m["variables"].items())
            rnd.shuffle(items)
            m["variables"] = dict(items)
            f = render(m)[1]
            self.assertEqual(json.loads(f["engineering/allocation.json"])["active"],
                             json.loads(ref["engineering/allocation.json"])["active"])
            self.assertEqual(json.loads(f["engineering/codesys_plan.json"])["io_mappings"],
                             json.loads(ref["engineering/codesys_plan.json"])["io_mappings"])


def run_to_file(path: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = sorted(t.id().split(".", 1)[1] for t in _iter(suite))
    r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    ok = r.wasSuccessful()
    out = {"step": "s2_selftest", "tests_run": r.testsRun, "failures": len(r.failures), "errors": len(r.errors),
           "tests": names, "operation_status": "PASS" if ok else "FAILED",
           "reason": "%d S2 multi-equipment tests passed" % r.testsRun if ok else "S2 tests failed"}
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
