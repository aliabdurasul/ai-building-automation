"""S7 test matrix (measurement only): derives the S7 behavioural test matrix from the result files of a run.

Every row names the evidence it needs: a result file whose operation_status must be PASS, a named check inside a
result file, or behaviour steps (Modbus write, PLC write, Modbus + PLC observation, trace). A row is
  PASS            every requirement present and passing
  FAIL            a requirement present and failing
  NOT VERIFIED    a requirement missing (the test did not run)
  NOT APPLICABLE  the behaviour does not exist in that logic (stated reason, no evidence claimed)
Usage: python test_matrix.py --run-root <stage root> --result <file>   Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SEQ, S1, PUMP, COMB = "ahu_seq_r001", "ahu_s1_r001", "pump_r002", "combined_r001"
SEQ_T = "scenario:AHU-01 AHU_SEQ_V1 behaviour"
S1_T = "scenario:AHU-01 AHU_S1FIX_V1 existing behaviour"
PUMP_T = "template:PUMP-01:PUMP_BASIC_V1"
PUMP_S = "scenario:PUMP-01 PUMP_BASIC_V1 S7 regression"
ISO_T = "scenario:BMS-DEMO equipment isolation"


def op(path):
    return ("op", path)


def chk(path, name):
    return ("check", path, name)


def steps(chain, test, *names):
    return ("steps", chain, test, names)


def all_steps(chain, test):
    return ("steps", chain, test, None)


def build(chain):
    return [op(f"deploy/{chain}/logs/create_result.json"), op(f"deploy/{chain}/logs/verify_result.json")]


def typed(chain):
    return [op(f"deploy/{chain}/logs/typed_verify.json"), chk(f"deploy/{chain}/logs/typed_verify.json", "real32_ordering_matches_reference")]


ROWS = [
    ("AHU", "AHU build (AHU_SEQ_V1, AHU_S1FIX_V1)", build(SEQ) + build(S1)),
    ("AHU", "AHU deploy", [op(f"deploy/{SEQ}/logs/deployment_result.json"), op(f"deploy/{S1}/logs/deployment_result.json")]),
    ("AHU", "AHU START (HR0=1 -> IR0=3, FanCommand/FanRunning TRUE, FanFault FALSE, intermediate states)",
     [steps(SEQ, SEQ_T, "AHU_START_start_edge"), steps(S1, S1_T, "AHU_START_hr0_1")]),
    ("AHU", "AHU STOP (HR0=2 -> IR0=0)", [steps(SEQ, SEQ_T, "AHU_STOP_stop_edge"), steps(S1, S1_T, "AHU_STOP_hr0_2")]),
    ("AHU", "AHU sequence STOPPED-STARTING-DAMPER OPENING-FAN STARTING-RUNNING-STOPPING-DAMPER CLOSING-STOPPED, template timing",
     [("trace", SEQ, SEQ_T, ("AHU_START_start_edge", "AHU_STOP_stop_edge"))]),
    ("AHU", "AHU start edge", [steps(SEQ, SEQ_T, "AHU_START_start_edge", "start_edge_while_running_ignored")]),
    ("AHU", "AHU stop edge", [steps(SEQ, SEQ_T, "AHU_STOP_stop_edge", "stop_edge_while_stopped_ignored")]),
    ("AHU", "AHU start held / released", [steps(SEQ, SEQ_T, "start_held", "start_released"),
                                         steps(S1, S1_T, "start_held", "start_released_stays_running")]),
    ("AHU", "AHU stop held / released", [steps(SEQ, SEQ_T, "stop_held", "stop_released"),
                                        steps(S1, S1_T, "stop_held", "stop_released_stays_stopped")]),
    ("AHU", "AHU fault (FanFailure in RUNNING, DamperFailure in DAMPER OPENING; S1 FanFault)",
     [steps(SEQ, SEQ_T, "AHU_FAULT_fan_failure_during_running", "negative_damper_failure_during_starting"),
      steps(S1, S1_T, "AHU_FAULT_fan_fault_while_running", "fault_while_stopped")]),
    ("AHU", "AHU fault recovery",
     [steps(SEQ, SEQ_T, "AHU_FAULT_RECOVERY_fan_failure_cleared_start_held_stays_stopped", "damper_failure_cleared"),
      steps(S1, S1_T, "AHU_FAULT_RECOVERY_fault_cleared_level_start_restarts", "fault_cleared_after_start_released_stays_stopped")]),
    ("AHU", "AHU setpoint / heating (SupplyTemp < Setpoint -> 100, >= -> 0)",
     [steps(SEQ, SEQ_T, "AHU_HEATING_supply_below_setpoint", "heating_supply_equal_setpoint", "heating_supply_above_setpoint",
            "heating_setpoint_raised_over_modbus"),
      steps(S1, S1_T, "AHU_HEATING_supply_below_setpoint", "heating_supply_equal_setpoint", "heating_supply_above_setpoint",
            "heating_setpoint_raised_over_modbus"),
      chk(f"deploy/{SEQ}/logs/typed_verify.json", "ahu_heating_logic_over_modbus"),
      chk(f"deploy/{S1}/logs/typed_verify.json", "ahu_heating_logic_over_modbus")]),
    ("AHU", "AHU negative: invalid command, conflicting START/STOP, unknown state, STOP during sequence, start in FAULT",
     [steps(SEQ, SEQ_T, "negative_invalid_command_bit2", "negative_invalid_command_bit3",
            "negative_conflicting_start_stop_from_stopped", "negative_unknown_state_falls_back_to_stopped",
            "stop_edge_during_fan_starting_aborts", "negative_start_edge_in_fault_ignored"),
      steps(S1, S1_T, "negative_invalid_command_bit2_while_running", "negative_invalid_command_bit3_while_stopped",
            "negative_conflicting_start_stop_stop_wins", "negative_start_held_during_fault_blocked",
            "negative_start_during_fault_blocked")]),
    ("AHU", "AHU_SEQ_V1 complete scenario", [all_steps(SEQ, SEQ_T)]),
    ("AHU", "AHU_S1FIX_V1 existing behaviour complete scenario", [all_steps(S1, S1_T)]),
    ("PUMP", "PUMP regression (PUMP_BASIC_V1 template behaviour, start while stop held)", [all_steps(PUMP, PUMP_T)]),
    ("PUMP", "PUMP state machine 0/1/2/3/9 (traces, forced STARTING/STOPPING branches, unknown state)",
     [steps(PUMP, PUMP_S, "PUMP_start_trace", "PUMP_stop_trace", "state1_starting_branch_forced",
            "state3_stopping_branch_forced", "negative_unknown_state_falls_back_to_stopped")]),
    ("PUMP", "PUMP fault", [steps(PUMP, PUMP_T, "fault_while_running_start_held"),
                            steps(PUMP, PUMP_S, "PUMP_fault_while_stopped", "negative_start_during_fault_blocked")]),
    ("PUMP", "PUMP fault recovery", [steps(PUMP, PUMP_T, "fault_cleared_stopped"), steps(PUMP, PUMP_S, "PUMP_fault_recovery_stopped")]),
    ("PUMP", "PUMP REAL32 PumpSpeed / Pressure / FlowRate 50.0, 3.75, 21.5, 123.456 (reference word order)",
     [steps(PUMP, PUMP_S, "PUMP_REAL32_50_0", "PUMP_REAL32_3_75", "PUMP_REAL32_21_5", "PUMP_REAL32_123_456",
            "PUMP_REAL32_distinct_per_signal"), ("ordering", PUMP)] + typed(PUMP)),
    ("MODBUS", "AHU HR0/IR0 (S1 contract on every AHU application)",
     [op(f"deploy/{c}/logs/s1_regression.json") for c in (SEQ, S1, COMB)]),
    ("MODBUS", "PUMP Modbus (BOOL coil/DI, INT16, REAL32)", typed(PUMP) + typed(COMB)),
    ("MODBUS", "PLC online readback (every behaviour step: Modbus value == PLC online value)",
     [("match", c) for c in (SEQ, S1, PUMP, COMB)] + [op(f"deploy/{c}/logs/typed_verify.json") for c in (SEQ, S1)]),
    ("REGRESSION", "S1 regression (HR0/IR0, AHU template equivalence with S6 V1)",
     [op(f"deploy/{c}/logs/s1_regression.json") for c in (SEQ, S1, COMB)] + [op("logs/template_equivalence.json")]),
    ("REGRESSION", "S2 regression (combined AHU + PUMP application, isolation, S2 store reproduction, S2 self-test)",
     build(COMB) + [op(f"deploy/{COMB}/logs/behavior.json"), all_steps(COMB, ISO_T)] + typed(COMB)
     + [op("logs/s2_selftest.json"), op("logs/s2_store_reproduction_pump.json"),
        op("logs/s2_store_reproduction_combined.json"), op("logs/s2_store_reproduction_ahu.json")]),
    ("REGRESSION", "S3 typed regression (typed verification on every deployed application, reference word order)",
     typed(SEQ) + typed(S1) + typed(PUMP) + typed(COMB) + [op("logs/s3_engine_selftest.json")]),
    ("REGRESSION", "S6 revision regression (self-test, S6 store reproduction)",
     [op("logs/s6_revision_selftest.json"), op("logs/s6_store_reproduction.json")]),
    ("REGRESSION", "Adapter generic (no equipment-specific logic in the CODESYS adapter)", [op("logs/adapter_generic.json")]),
]

NOT_APPLICABLE = [
    ("AHU", "AHU_S1FIX_V1 sequence / damper / timing", "AHU_S1FIX_V1 has no sequence states, damper or timers (level logic); covered by AHU_SEQ_V1"),
    ("AHU", "AHU_S1FIX_V1 start / stop edge detection", "AHU_S1FIX_V1 acts on command levels; held-command behaviour is tested instead"),
    ("AHU", "AHU_S1FIX_V1 DamperFailure", "no damper in AHU_S1FIX_V1"),
]


class Run:
    def __init__(self, root: Path):
        self.root = root
        self.cache = {}

    def load(self, rel):
        if rel not in self.cache:
            p = self.root / rel
            self.cache[rel] = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else None
        return self.cache[rel]

    def test(self, chain, name):
        b = self.load(f"deploy/{chain}/logs/behavior.json")
        if b is None:
            return None
        return next((t for t in b.get("tests", []) if t["name"] == name), None)


def step_evidence(s):
    e = {"step": s["name"], "command": {"modbus_write": s.get("modbus_write") or {}, "plc_write": s.get("plc_write") or {}},
         "expect": s.get("expect"), "modbus": s.get("observed_modbus"), "plc": s.get("observed_plc"),
         "modbus_plc_match": s.get("modbus_plc_match"), "result": "PASS" if s.get("pass") else "FAIL"}
    if s.get("trace"):
        e["trace"] = {k: {"sequence": v.get("sequence"), "expected_sequence": v.get("expected_sequence"),
                          "durations": v.get("durations")} for k, v in (s["trace"].get("signals") or {}).items()}
    if s.get("errors"):
        e["errors"] = s["errors"]
    return e


def evaluate(run: Run, req):
    kind = req[0]
    if kind == "op":
        r = run.load(req[1])
        if r is None:
            return None, {"file": req[1], "present": False}
        return r.get("operation_status") == "PASS", {"file": req[1], "operation_status": r.get("operation_status"),
                                                     "reason": r.get("reason")}
    if kind == "check":
        r = run.load(req[1])
        if r is None or req[2] not in (r.get("checks") or {}):
            return None, {"file": req[1], "check": req[2], "present": False}
        return bool(r["checks"][req[2]]), {"file": req[1], "check": req[2], "value": r["checks"][req[2]]}
    if kind in ("steps", "trace"):
        chain, name, names = req[1], req[2], req[3]
        t = run.test(chain, name)
        if t is None:
            return None, {"chain": chain, "test": name, "present": False}
        by = {s["name"]: s for s in t.get("steps", [])}
        wanted = list(names) if names else list(by)
        missing = [n for n in wanted if n not in by]
        ev = {"chain": chain, "test": name, "steps": [step_evidence(by[n]) for n in wanted if n in by]}
        if missing:
            ev["missing_steps"] = missing
            return None, ev
        if kind == "trace":
            traces = [by[n].get("trace") for n in wanted]
            ok = all(tr and tr.get("pass") and any(sig.get("durations") for sig in tr["signals"].values()) for tr in traces)
            return ok, ev
        return all(by[n].get("pass") for n in wanted) and (names is not None or t.get("pass")), ev
    if kind == "match":
        b = run.load(f"deploy/{req[1]}/logs/behavior.json")
        if b is None:
            return None, {"chain": req[1], "present": False}
        sts = [s for t in b.get("tests", []) for s in t.get("steps", [])]
        bad = [s["name"] for s in sts if not s.get("modbus_plc_match")]
        return bool(sts) and not bad, {"chain": req[1], "behaviour_steps": len(sts),
                                       "modbus_checked_values": sum(len(s.get("modbus_checked") or []) for s in sts),
                                       "plc_only_values": sum(len(s.get("plc_only") or []) for s in sts),
                                       "mismatched_steps": bad}
    if kind == "ordering":
        b = run.load(f"deploy/{req[1]}/logs/behavior.json")
        if b is None:
            return None, {"chain": req[1], "present": False}
        o = b.get("real32_ordering_reference")
        return o == "CDAB", {"chain": req[1], "behaviour_real32_ordering": o, "expected": "CDAB"}
    raise ValueError(kind)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--result", required=True)
    a = ap.parse_args()
    run = Run(Path(a.run_root))
    rows = []
    for group, name, reqs in ROWS:
        results = [evaluate(run, r) for r in reqs]
        if any(ok is False for ok, _ in results):
            status = "FAIL"
        elif any(ok is None for ok, _ in results):
            status = "NOT VERIFIED"
        else:
            status = "PASS"
        rows.append({"group": group, "test": name, "result": status, "evidence": [ev for _, ev in results]})
    for group, name, why in NOT_APPLICABLE:
        rows.append({"group": group, "test": name, "result": "NOT APPLICABLE", "reason": why})
    counted = [r for r in rows if r["result"] != "NOT APPLICABLE"]
    summary = {k: sum(1 for r in rows if r["result"] == k) for k in ("PASS", "FAIL", "NOT VERIFIED", "NOT APPLICABLE")}
    behaviour_steps = {}
    for c in (SEQ, S1, PUMP, COMB):
        b = run.load(f"deploy/{c}/logs/behavior.json")
        if b:
            behaviour_steps[c] = {"steps": sum(len(t.get("steps", [])) for t in b.get("tests", [])),
                                  "passed": sum(1 for t in b.get("tests", []) for s in t.get("steps", []) if s.get("pass"))}
    ok = bool(counted) and all(r["result"] == "PASS" for r in counted)
    res = {"step": "s7_test_matrix", "rows": rows, "summary": summary, "matrix_tests": len(counted),
           "behaviour_steps": behaviour_steps, "operation_status": "PASS" if ok else "FAILED",
           "reason": (f"{len(counted)} matrix tests PASS ({summary['NOT APPLICABLE']} NOT APPLICABLE)" if ok else
                      "not PASS: " + ", ".join(f"{r['test']} [{r['result']}]" for r in counted if r["result"] != "PASS"))}
    Path(a.result).parent.mkdir(parents=True, exist_ok=True)
    Path(a.result).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return 0 if ok else 20


if __name__ == "__main__":
    raise SystemExit(main())
