"""S2/S7 generic behaviour executor (CPython + pymodbus + S3 PLC online bridge; measurement only).

Runs step lists against the deployed application. Nothing here knows an equipment type:
  --equipment ID   run the behaviour_test of the logic template instance of equipment ID
                   (keys are template slots -> bound PLC variable -> mapped Modbus signal)
  --scenario FILE  run an identity-addressed scenario (keys are project/equipment/tag identities)
Keys: identity (contains "/") or template slot -> Modbus signal + PLC variable; "plc:<var>" -> PLC variable only.
Per step, in this order:
  modbus_write  client-writable mapped signals (BOOL coil, WORD/INT16/UINT16 register, REAL32 FC16)
  plc_write     PLC online write (fault injection / test values)
  trace         Modbus sampling of mapped signals until "until" holds: ordered value runs are compared with the
                expected sequence ("allow" = values that may appear in between, e.g. one-cycle states) and run
                durations with template parameters ("EQUIPMENT.PARAMETER", tolerance -TOL_LOW_MS/+TOL_HIGH_MS)
  wait_ms       hold the inputs unchanged for a while (held-command tests)
  expect        poll until every expectation holds BOTH through Modbus (mapped keys) and PLC online read-back
REAL32 register order: the S3 measured order (--reference typed_verify.json); never discovered here.

Usage: python behavior.py --stage <deploy stage> [--equipment ID ...] [--scenario FILE ...] [--reference FILE]
Writes <stage>/logs/behavior.json. Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "s3" / "probe"))
import typed_verify as tv  # noqa: E402  (Bridge, Modbus client wrapper, PLC literal/parse helpers)

cn = tv.cn
POLL_TIMEOUT_S = 6.0
TOL_LOW_MS, TOL_HIGH_MS = 100, 400


class Codec:
    def __init__(self, ordering: str | None):
        self.ordering = ordering

    def decode(self, s: dict, raw):
        if raw is None:
            return None
        dt = s["datatype"]
        if dt == "BOOL":
            return bool(raw)
        if dt == "REAL32":
            return cn.decode_real32(raw, self.ordering) if self.ordering else None
        v = raw[0]
        return v - 65536 if dt == "INT16" and v >= 32768 else v

    def encode(self, s: dict, v) -> list[int]:
        if s["datatype"] == "REAL32":
            if not self.ordering:
                raise ValueError("REAL32 register order unknown (no --reference)")
            return cn.encode_real32(float(v), self.ordering)
        return [int(v) & 0xFFFF]


def same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and cn.f32_bits(float(a)) == cn.f32_bits(float(b))
    return a == b


class Target:
    """Resolves step keys to (mapping signal or None, PLC variable)."""

    def __init__(self, mapping: dict, model: dict, instance: dict | None, instances: dict):
        self.by_identity = {s["identity"]: s for s in mapping["signals"]}
        self.by_var = {s["plc_var"]: s for s in mapping["signals"]}
        self.variables = model["variables"]
        self.instance = instance
        self.instances = instances

    def resolve(self, key: str):
        if key.startswith("plc:"):
            return None, key[4:]
        if "/" in key:
            s = self.by_identity[key]
            return s, s["plc_var"]
        var = self.instance["bind"][key]
        return self.by_var.get(var), var

    def plc_type(self, key: str) -> str:
        s, var = self.resolve(key)
        return self.variables[var]["type"] if var in self.variables else s["plc_type"]

    def parameter(self, ref: str) -> int:
        eq, name = ref.split(".", 1)
        return self.instances[eq]["parameters"][name]


def runs_of(samples: list) -> list:
    out = []
    for t, v in samples:
        if not out or not same(out[-1][1], v):
            out.append([t, v])
    return out


def do_trace(spec: dict, tgt: Target, mb, codec: Codec) -> dict:
    keys = sorted(set(spec["signals"]) | set(spec.get("until") or {}))
    sig = {k: tgt.resolve(k)[0] for k in keys}
    missing = [k for k in keys if sig[k] is None]
    if missing:
        return {"pass": False, "error": f"trace keys without Modbus signal: {missing}"}
    samples = {k: [] for k in keys}
    t0 = time.perf_counter()
    reached = False
    while time.perf_counter() - t0 < spec.get("timeout_s", 10):
        now = {}
        for k in keys:
            v = codec.decode(sig[k], mb.raw_of(sig[k]))
            samples[k].append((round((time.perf_counter() - t0) * 1000.0, 1), v))
            now[k] = v
        if all(same(now[k], v) for k, v in (spec.get("until") or {}).items()):
            reached = True
            break
        time.sleep(0.005)
    out = {"until_reached": reached, "signals": {}}
    ok = reached
    for k, want in sorted(spec["signals"].items()):
        rs = runs_of(samples[k])
        allow = want.get("allow", [])
        seq = [v for _, v in rs if not any(same(v, a) for a in allow)]
        r = {"observed_runs": [v for _, v in rs], "sequence": seq, "expected_sequence": want["sequence"],
             "sequence_ok": len(seq) == len(want["sequence"]) and all(same(a, b) for a, b in zip(seq, want["sequence"])),
             "timeline": [{"t_ms": t, "value": v} for t, v in rs], "durations": []}
        for val, ref in sorted((want.get("durations_ms") or {}).items()):
            nominal = tgt.parameter(ref)
            idx = next((i for i, (_, v) in enumerate(rs) if same(v, int(val)) and i + 1 < len(rs)), None)
            measured = round(rs[idx + 1][0] - rs[idx][0], 1) if idx is not None else None
            r["durations"].append({"value": int(val), "parameter": ref, "nominal_ms": nominal, "measured_ms": measured,
                                   "tolerance_ms": [-TOL_LOW_MS, TOL_HIGH_MS],
                                   "within_tolerance": measured is not None and
                                   nominal - TOL_LOW_MS <= measured <= nominal + TOL_HIGH_MS})
        r["pass"] = r["sequence_ok"] and all(d["within_tolerance"] for d in r["durations"])
        ok = ok and r["pass"]
        out["signals"][k] = r
    out["samples"] = sum(len(v) for v in samples.values())
    out["pass"] = ok
    return out


def run_steps(name, steps, tgt: Target, mb, bridge, codec: Codec) -> dict:
    out = {"name": name, "steps": []}
    for st in steps:
        rec = {"name": st["name"], "modbus_write": st.get("modbus_write", {}), "plc_write": st.get("plc_write", {}),
               "expect": st["expect"], "errors": []}
        written = {}
        for key, v in st.get("modbus_write", {}).items():
            s, _ = tgt.resolve(key)
            if s is None or s["area"] not in ("COIL", "HOLDING_REGISTER"):
                rec["errors"].append(f"{key}: not mapped to a client-writable signal")
                continue
            if s["area"] == "COIL":
                r = mb.c.write_coil(s["address"], bool(v), device_id=mb.unit)
                written[key] = bool(v)
            else:
                regs = codec.encode(s, v)
                r = (mb.c.write_register(s["address"], regs[0], device_id=mb.unit) if len(regs) == 1
                     else mb.c.write_registers(s["address"], regs, device_id=mb.unit))
                written[key] = regs
            if r.isError():
                rec["errors"].append(f"{key}: Modbus write rejected")
        rec["modbus_written_raw"] = written
        lits = {f"PLC_PRG.{tgt.resolve(k)[1]}": tv.literal(tgt.plc_type(k), v) for k, v in st.get("plc_write", {}).items()}
        if lits:
            bridge.write(lits)
        if st.get("trace"):
            rec["trace"] = do_trace(st["trace"], tgt, mb, codec)
        if st.get("wait_ms"):
            time.sleep(st["wait_ms"] / 1000.0)
            rec["wait_ms"] = st["wait_ms"]
        keys = sorted(st["expect"])
        resolved = {k: tgt.resolve(k) for k in keys}
        t0, attempts = time.time(), 0
        while True:
            attempts += 1
            plc_raw = bridge.read([f"PLC_PRG.{resolved[k][1]}" for k in keys])
            plc = {k: tv.parse_plc(plc_raw[f"PLC_PRG.{resolved[k][1]}"], tgt.plc_type(k)) for k in keys}
            mbv = {k: (codec.decode(resolved[k][0], mb.raw_of(resolved[k][0])) if resolved[k][0] else None) for k in keys}
            ok = all(same(plc[k], st["expect"][k]) and (resolved[k][0] is None or same(mbv[k], st["expect"][k]))
                     for k in keys)
            if ok or time.time() - t0 > POLL_TIMEOUT_S:
                break
            time.sleep(0.1)
        rec["observed_plc"], rec["observed_modbus"] = plc, {k: v for k, v in mbv.items() if resolved[k][0] is not None}
        rec["modbus_checked"] = sorted(k for k in keys if resolved[k][0] is not None)
        rec["plc_only"] = sorted(k for k in keys if resolved[k][0] is None)
        rec["modbus_plc_match"] = all(same(plc[k], mbv[k]) for k in rec["modbus_checked"])
        rec["poll_attempts"] = attempts
        rec["pass"] = ok and not rec["errors"] and rec["modbus_plc_match"] and rec.get("trace", {"pass": True})["pass"]
        out["steps"].append(rec)
    out["pass"] = bool(out["steps"]) and all(s["pass"] for s in out["steps"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--equipment", action="append", default=[])
    ap.add_argument("--scenario", action="append", default=[])
    ap.add_argument("--reference")
    a = ap.parse_args()
    stage = Path(a.stage)
    mapping = json.loads((stage / "engineering" / "modbus_mapping.json").read_text(encoding="utf-8"))
    model = json.loads((stage / "engineering" / "model.json").read_text(encoding="utf-8"))
    li = stage / "engineering" / "logic_instances.json"
    instances = {i["equipment"]: i for i in json.loads(li.read_text(encoding="utf-8"))["instances"]} if li.exists() else {}
    ordering = None
    if a.reference and Path(a.reference).exists():
        ordering = (json.loads(Path(a.reference).read_text(encoding="utf-8")).get("real32_ordering") or {}).get("name")
    res = {"step": "behavior", "project_id": model["project_id"], "revision": model["revision"],
           "real32_ordering_reference": ordering, "tests": [], "checks": {}}
    codec = Codec(ordering)
    bridge = tv.Bridge(stage / "bridge_behavior")
    ready = bridge.wait_ready()
    mb = tv.Modbus(mapping["host"], mapping["port"], mapping["unit_id"])
    res["checks"]["pymodbus_connect"] = mb.ok
    res["checks"]["bridge_logged_in"] = bool(ready.get("ready") and ready.get("logged_in"))
    fatal = None
    if mb.ok and res["checks"]["bridge_logged_in"]:
        try:
            for eq in a.equipment:
                inst = instances.get(eq)
                if not inst or not inst.get("behavior_test"):
                    res["tests"].append({"name": f"template:{eq}", "pass": False,
                                         "error": "equipment has no logic template behaviour test"})
                    continue
                t = run_steps(f"template:{eq}:{inst['template']}", inst["behavior_test"]["steps"],
                              Target(mapping, model, inst, instances), mb, bridge, codec)
                t.update(equipment=eq, template=inst["template"], template_sha256=inst["sha256"])
                res["tests"].append(t)
            for sc in a.scenario:
                spec = json.loads(Path(sc).read_text(encoding="utf-8"))
                t = run_steps(f"scenario:{spec['name']}", spec["steps"], Target(mapping, model, None, instances),
                              mb, bridge, codec)
                t["description"] = spec.get("description")
                res["tests"].append(t)
        except Exception as ex:
            fatal = f"{type(ex).__name__}: {ex}"
    else:
        fatal = "bridge/pymodbus not available: " + str(ready.get("reason", ""))
    try:
        bridge.call({"op": "quit"}, timeout=30)
        res["checks"]["bridge_quit"] = True
    except Exception as ex:
        res["checks"]["bridge_quit"] = False
        res["bridge_quit_error"] = str(ex)
    for t in res["tests"]:
        res["checks"][t["name"]] = t["pass"]
    failed = [k for k, v in res["checks"].items() if not v]
    ok = fatal is None and bool(res["tests"]) and not failed
    res["operation_status"] = "PASS" if ok else "FAILED"
    res["reason"] = fatal or (f"{sum(len(t.get('steps', [])) for t in res['tests'])} behaviour steps passed "
                              f"({', '.join(t['name'] for t in res['tests'])})" if ok else "failed: " + ", ".join(failed))
    (stage / "logs").mkdir(exist_ok=True)
    (stage / "logs" / "behavior.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return 0 if ok else 20


if __name__ == "__main__":
    sys.exit(main())
