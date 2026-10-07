"""S7 behavioural-validation self-test (unittest, offline). Usage: python test_s7.py [--result <json>]"""
from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "s6" / "generator"))
import regenerate as rg  # noqa: E402

lt = rg.logic_module()
MODELS = ROOT / "s7" / "model"
S2_MODELS = ROOT / "s2" / "model"
TEMPLATES = ROOT / "s2" / "logic" / "templates"
TARGET_BYTES = (MODELS / "target_codesys_softplc.json").read_bytes()
VENDOR_WORDS = ("CODESYS", "codesys", "ScriptEngine", "CDAB", "ABCD", "byte_order", "word_order", "register_order",
                "device_id", ".project", "Modbus_TCP_Server")
SEQ_STATES = (0, 1, 2, 3, 4, 5, 6, 9)


def mbytes(m: dict) -> bytes:
    return (json.dumps(m, indent=2) + "\n").encode("utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render(m: dict):
    return rg.render(mbytes(m), TARGET_BYTES, None, [], lt.make_bundle(m))


def active(f) -> dict:
    return {e["identity"]: e for e in json.loads(f["engineering/allocation.json"])["active"]}


class SequenceTemplate(unittest.TestCase):
    def setUp(self):
        self.t = load(TEMPLATES / "AHU_SEQ_V1.json")
        self.body = "\n".join(self.t["body"])

    def test_every_state_has_a_branch_and_unknown_falls_back(self):
        for s in SEQ_STATES:
            self.assertRegex(self.body, r"(?m)^%d: \(\*" % s, s)
        self.assertIn("ELSE (* unknown state value: safe fallback *)", self.body)

    def test_timing_only_from_parameters(self):
        self.assertEqual(self.t["parameters"], {"DamperOpenTime_ms": 2000, "FanStartTime_ms": 1000,
                                                "FanStopTime_ms": 1000, "DamperCloseTime_ms": 2000})
        for line in self.t["body"]:
            if "StateEntryMs}} >=" in line:
                self.assertRegex(line, r">= \{\{\w+_ms\}\} THEN$", line)
        self.assertFalse(re.search(r"\bT#", self.body))

    def test_commands_are_edge_triggered(self):
        self.assertIn("IF {{StartCommand}} AND NOT {{StartPrev}} AND NOT {{StopCommand}} THEN", self.body)
        self.assertEqual(self.body.count("IF {{StopCommand}} AND NOT {{StopPrev}} THEN"), 3)
        self.assertIn("{{StartPrev}} := {{StartCommand}};", self.body)
        self.assertIn("{{StopPrev}} := {{StopCommand}};", self.body)

    def test_fault_forces_safe_state_and_status_contract(self):
        self.assertIn("{{AhuAlarm}} := {{FanFailure}} OR {{DamperFailure}};", self.body)
        self.assertIn("IF {{AhuAlarm}} AND {{AhuState}} <> 9 THEN", self.body)
        self.assertIn("{{FanFault}} := {{FanFailure}};", self.body)
        for slot in ("FanCommand", "FanRunning", "FanFault"):
            self.assertIn(slot, self.t["slots"])


class Parameters(unittest.TestCase):
    def test_default_parameters_rendered(self):
        v, f = render(load(MODELS / "ahu_seq_v1.json"))
        self.assertEqual(v["status"], "ACCEPTED", v["errors"])
        impl = f["generated/plc/PLC_PRG_impl.st"].decode()
        for n in ("2000", "1000"):
            self.assertIn("NowMs - StateEntryMs >= %s THEN" % n, impl)
        self.assertNotIn("{{", impl)
        inst = json.loads(f["engineering/logic_instances.json"])["instances"]
        self.assertEqual(inst[0]["parameters"]["DamperOpenTime_ms"], 2000)
        self.assertEqual(json.loads(f["engineering/codesys_plan.json"])["project_file"], "AI_BMS_S7_AHU_SEQ_r001.project")

    def test_parameter_override(self):
        m = load(MODELS / "ahu_seq_v1.json")
        m["equipment"][0]["logic"]["params"] = {"DamperOpenTime_ms": 3500}
        v, f = render(m)
        self.assertEqual(v["status"], "ACCEPTED", v["errors"])
        impl = f["generated/plc/PLC_PRG_impl.st"].decode()
        self.assertIn("NowMs - StateEntryMs >= 3500 THEN", impl)
        self.assertEqual(json.loads(f["engineering/logic_instances.json"])["instances"][0]["parameters"]["DamperOpenTime_ms"], 3500)

    def test_bad_parameters_rejected(self):
        m = load(MODELS / "ahu_seq_v1.json")
        for params, text in (({"NoSuch_ms": 1}, "unknown parameters"), ({"FanStartTime_ms": -1}, "non-negative integer"),
                             ({"FanStartTime_ms": 1.5}, "non-negative integer"), ({"FanStartTime_ms": True}, "non-negative integer")):
            mm = copy.deepcopy(m)
            mm["equipment"][0]["logic"]["params"] = params
            errs = lt.check(mm, json.loads(lt.make_bundle(mm)))
            self.assertTrue(any(text in e["message"] for e in errs), (params, errs))

    def test_templates_without_parameters_unchanged(self):
        f = rg.render(mbytes(load(S2_MODELS / "pump_v1.json")), (S2_MODELS / "target_codesys_softplc.json").read_bytes(),
                      None, [], lt.make_bundle(load(S2_MODELS / "pump_v1.json")))[1]
        self.assertNotIn("parameters", json.loads(f["engineering/logic_instances.json"])["instances"][0])


class Models(unittest.TestCase):
    def test_models_vendor_neutral_and_unaddressed(self):
        for n in ("ahu_seq_v1.json", "ahu_s1fix_v1.json"):
            text = (MODELS / n).read_text(encoding="utf-8")
            for w in VENDOR_WORDS:
                self.assertNotIn(w, text, (n, w))
            for s in load(MODELS / n)["signals"]:
                if s["tag"] not in ("Command", "Status"):
                    self.assertNotIn("address", s["modbus"], (n, s["tag"]))

    def test_s1_contract_pinned(self):
        for n, proj in (("ahu_seq_v1.json", "AHU-SEQ"), ("ahu_s1fix_v1.json", "AHU-S1")):
            v, f = render(load(MODELS / n))
            self.assertEqual(v["status"], "ACCEPTED", (n, v["errors"]))
            a = active(f)
            self.assertEqual((a[proj + "/AHU-01/Command"]["area"], a[proj + "/AHU-01/Command"]["address"]), ("HOLDING_REGISTER", 0))
            self.assertEqual((a[proj + "/AHU-01/Status"]["area"], a[proj + "/AHU-01/Status"]["address"]), ("INPUT_REGISTER", 0))

    def test_failure_inputs_are_plc_only(self):
        m = load(MODELS / "ahu_seq_v1.json")
        tags = {s["tag"] for s in m["signals"]}
        for v in ("FanFailure", "DamperFailure"):
            self.assertIn(v, m["variables"])
            self.assertNotIn(v, tags)


class Scenarios(unittest.TestCase):
    CASES = (("ahu_seq_behavior.json", MODELS / "ahu_seq_v1.json", TARGET_BYTES),
             ("ahu_s1fix_behavior.json", MODELS / "ahu_s1fix_v1.json", TARGET_BYTES),
             ("pump_behavior.json", S2_MODELS / "pump_v2.json", TARGET_BYTES))

    def test_scenario_keys_resolve(self):
        for scen, model_path, target in self.CASES:
            m = load(model_path)
            f = rg.render(mbytes(m), target, None, [], lt.make_bundle(m))[1]
            mapping = json.loads(f["engineering/modbus_mapping.json"])
            idents = {s["identity"]: s for s in mapping["signals"]}
            inst = {i["equipment"]: i for i in json.loads(f["engineering/logic_instances.json"])["instances"]}
            for st in load(MODELS / scen)["steps"]:
                self.assertIn("expect", st, (scen, st["name"]))
                keys = set(st.get("modbus_write", {})) | set(st.get("plc_write", {})) | set(st["expect"])
                tr = st.get("trace") or {}
                keys |= set(tr.get("signals") or {}) | set(tr.get("until") or {})
                for k in keys:
                    if k.startswith("plc:"):
                        self.assertIn(k[4:], m["variables"], (scen, st["name"], k))
                    else:
                        self.assertIn(k, idents, (scen, st["name"], k))
                for k in st.get("modbus_write", {}):
                    self.assertIn(idents[k]["area"], ("COIL", "HOLDING_REGISTER"), (scen, k))
                for k in set(tr.get("signals") or {}) | set(tr.get("until") or {}):
                    self.assertFalse(k.startswith("plc:"), (scen, k))
                for spec in (tr.get("signals") or {}).values():
                    for ref in (spec.get("durations_ms") or {}).values():
                        eq, p = ref.split(".", 1)
                        self.assertIn(p, inst[eq]["parameters"], (scen, ref))

    def test_unique_step_names(self):
        for scen, _, _ in self.CASES:
            names = [s["name"] for s in load(MODELS / scen)["steps"]]
            self.assertEqual(len(names), len(set(names)), scen)


def run_to_file(path: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = sorted(t.id().split(".", 1)[1] for t in _iter(suite))
    r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    ok = r.wasSuccessful()
    out = {"step": "s7_selftest", "tests_run": r.testsRun, "failures": len(r.failures), "errors": len(r.errors),
           "tests": names, "operation_status": "PASS" if ok else "FAILED",
           "reason": "%d S7 behavioural-validation tests passed" % r.testsRun if ok else "S7 tests failed"}
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
