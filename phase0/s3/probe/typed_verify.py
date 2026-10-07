"""S3 F07: typed Modbus mapping verification against the real runtime (CPython + pymodbus).

READ  path: PLC value (injected for s3_test signals, observed for production signals)
            -> PLC online read-back (bridge) -> Modbus read (pymodbus) -> decode -> compare.
WRITE path: Modbus write (pymodbus) -> Modbus read-back -> PLC online read-back (bridge) -> compare.
REAL32 register order is measured: every REAL read sample is decoded with all four candidate
orderings; exactly one ordering must reproduce the PLC value bit-exactly for all samples.
Only fully passing signals become verified=true in engineering/modbus_mapping.json.

Usage: python typed_verify.py --stage <dir> [--reference <other stage>/logs/typed_verify.json]
Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import canonical as cn  # noqa: E402

SETTLE_S = 0.4
PLC_SETTLE_TIMEOUT_S = 6.0
READY_TIMEOUT_S = 300
READ_TABLE = {   # index 0 = generated initial value (not injected)
    "INT16": [None, 1234, -32768, 32767],
    "UINT16": [None, 65535, 0, 40000],
    "WORD": [None, 0x0001, 0xFFFF, 0x8000],
    "REAL32": [None, 22.0, 18.25, 123.456],
    "BOOL": [None, False, True, False],
}
WRITE_TABLE = {
    "BOOL": [True, False, True, False],
    "INT16": [-1234, 1234, -32768, 0],
    "UINT16": [1234, 54321, 65535, 0],
    "WORD": [0xBEEF, 0x0F0F, 0xFFFF, 0x0000],
    "REAL32": [21.5, 18.25, 123.456, 22.0],
}
TOLERANCE = "bit-exact: Modbus-decoded float32 == PLC REAL (float32) and == float32(intended decimal)"


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, d: Path):
        self.d, self.n = d, 0

    def wait_ready(self) -> dict:
        t0 = time.time()
        f = self.d / "ready.json"
        while time.time() - t0 < READY_TIMEOUT_S:
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
            time.sleep(0.25)
        return {"ready": False, "reason": f"bridge not ready within {READY_TIMEOUT_S} s"}

    def call(self, req: dict, timeout: float = 60) -> dict:
        self.n += 1
        cmd, res = self.d / f"cmd_{self.n:04d}.json", self.d / f"res_{self.n:04d}.json"
        tmp = self.d / f"tmp_{self.n:04d}.json"
        tmp.write_text(json.dumps(req), encoding="utf-8")
        tmp.rename(cmd)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if res.exists():
                try:
                    return json.loads(res.read_text(encoding="utf-8"))
                except (PermissionError, json.JSONDecodeError):
                    pass  # just-renamed file can be briefly locked on Windows (e.g. by a scanner); retry
            time.sleep(0.05)
        raise BridgeError(f"no bridge response for {cmd.name} within {timeout} s")

    def read(self, exprs: list[str]) -> dict:
        r = self.call({"op": "read", "exprs": exprs})
        if not r.get("ok"):
            raise BridgeError("PLC read failed: " + str(r.get("error")))
        return r["values"]

    def write(self, values: dict) -> None:
        r = self.call({"op": "write", "values": values})
        if not r.get("ok"):
            raise BridgeError("PLC write failed: " + str(r.get("error")))


def expr(s: dict) -> str:
    return "PLC_PRG." + s["plc_var"]


def parse_plc(raw: str, plc_type: str):
    s = raw.strip()
    if "#" in s and s.split("#", 1)[0].isalpha():
        s = s.split("#", 1)[1]
    if plc_type == "BOOL":
        return s.upper() == "TRUE"
    if plc_type == "REAL":
        return cn.f32(float(s))
    base = 10
    for pre, b in (("16#", 16), ("2#", 2), ("8#", 8)):
        if s.startswith(pre):
            s, base = s[len(pre):], b
    return int(s.replace("_", ""), base)


def literal(plc_type: str, v) -> str:
    if plc_type == "BOOL":
        return "TRUE" if v else "FALSE"
    if plc_type == "REAL":
        return repr(float(v))
    if plc_type == "WORD":
        return f"16#{int(v):04X}"
    return str(int(v))


def same(dt: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if dt == "REAL32":
        return cn.f32_bits(a) == cn.f32_bits(b)
    return a == b


class Modbus:
    def __init__(self, host, port, unit):
        self.c = ModbusTcpClient(host, port=port, timeout=3)
        self.unit = unit
        self.ok = bool(self.c.connect())

    def regs(self, area: str, addr: int, n: int):
        fn = self.c.read_holding_registers if area == "HOLDING_REGISTER" else self.c.read_input_registers
        r = fn(addr, count=n, device_id=self.unit)
        return None if r.isError() else list(r.registers[:n])

    def bit(self, area: str, addr: int):
        fn = self.c.read_coils if area == "COIL" else self.c.read_discrete_inputs
        r = fn(addr, count=1, device_id=self.unit)
        return None if r.isError() else bool(r.bits[0])

    def raw_of(self, s: dict):
        if s["area"] in cn.BIT_AREAS:
            return self.bit(s["area"], s["address"])
        return self.regs(s["area"], s["address"], s["length"])


def decode(s: dict, raw, ordering):
    dt = s["datatype"]
    if raw is None:
        return None
    if dt == "BOOL":
        return raw
    if dt == "INT16":
        return cn.decode_int16(raw[0])
    if dt in ("UINT16", "WORD"):
        return raw[0]
    return cn.decode_real32(raw, ordering) if ordering else None


def encode(s: dict, v, ordering):
    dt = s["datatype"]
    if dt == "INT16":
        return [cn.encode_int16(int(v))]
    if dt in ("UINT16", "WORD"):
        if not 0 <= int(v) <= 0xFFFF:
            raise ValueError(f"{dt} out of range: {v}")
        return [int(v)]
    return cn.encode_real32(v, ordering)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--reference")
    a = ap.parse_args()
    stage = Path(a.stage)
    mpath = stage / "engineering" / "modbus_mapping.json"
    mapping = json.loads(mpath.read_text(encoding="utf-8"))
    sigs = mapping["signals"]
    res = {"step": "typed_verify", "profile": mapping["profile"], "tolerance": TOLERANCE, "cases": [],
           "real32_samples": [], "behavior": [], "checks": {}}
    ref_order = None
    if a.reference and Path(a.reference).exists():
        ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))
        ref_order = (ref.get("real32_ordering") or {}).get("name")
        res["reference_ordering"] = ref_order

    bridge = Bridge(stage / "bridge")
    ready = bridge.wait_ready()
    res["bridge_ready"] = ready
    mb = Modbus(mapping["host"], mapping["port"], mapping["unit_id"])
    res["checks"]["pymodbus_connect"] = mb.ok
    res["checks"]["bridge_logged_in"] = bool(ready.get("ready") and ready.get("logged_in"))
    if not (mb.ok and res["checks"]["bridge_logged_in"]):
        return finish(stage, res, mapping, mpath, bridge, "bridge/pymodbus not available: " + str(ready.get("reason", "")))

    typed = [s for s in sigs if not s.get("bits")]
    reads = [s for s in typed if s["direction"] == "READ"]
    writes = [s for s in typed if s["direction"] in ("WRITE", "READ_WRITE")]
    # s3_test signals use READ_TABLE; a READ signal with explicit verification_values gets exactly those values.
    injectable = [s for s in reads if s.get("role") == "s3_test" or s.get("verification_values")]

    def read_values(s: dict) -> list:
        return READ_TABLE[s["datatype"]] if s.get("role") == "s3_test" else [None] + list(s["verification_values"])
    ordering = {"value": None}

    def plc_poll(group: list[dict], want: dict):
        """Online values are refreshed asynchronously: poll until every value in `want` is reached,
        or (without `want`) until two consecutive reads agree. Returns (raw, parsed, attempts, settled)."""
        t0, last, n = time.time(), None, 0
        while True:
            raw = bridge.read([expr(s) for s in group])
            vals = {s["tag"]: parse_plc(raw[expr(s)], s["plc_type"]) for s in group}
            n += 1
            if want:
                settled = all(same(s["datatype"], vals[s["tag"]], want[s["tag"]]) for s in group if s["tag"] in want)
            else:
                settled = last is not None and vals == last
            if settled or time.time() - t0 > PLC_SETTLE_TIMEOUT_S:
                return raw, vals, n, settled
            last = vals
            time.sleep(0.25)

    def observe(phase: str, intended: dict):
        plc, vals, attempts, settled = plc_poll(reads, intended)
        time.sleep(SETTLE_S)
        raws = {s["tag"]: mb.raw_of(s) for s in reads}
        _, after, _, _ = plc_poll(reads, {})
        for s in reads:
            raw = raws[s["tag"]]
            pv = vals[s["tag"]]
            case = {"phase": phase, "tag": s["tag"], "path": "READ", "datatype": s["datatype"],
                    "intended": intended.get(s["tag"]), "plc_raw": plc[expr(s)], "plc_value": pv, "modbus_raw": raw,
                    "plc_poll_attempts": attempts, "plc_settled": settled,
                    "plc_stable_across_modbus_read": same(s["datatype"], after[s["tag"]], pv)}
            if s["datatype"] == "REAL32" and raw is not None:
                cands = cn.matching_orderings(raw, pv)
                res["real32_samples"].append({"phase": phase, "tag": s["tag"], "registers": raw,
                                              "plc_value": pv, "plc_bits": f"{cn.f32_bits(pv):08X}",
                                              "matching_orderings": cands})
            res["cases"].append(case)

    phases = max((len(read_values(s)) for s in injectable), default=1)
    for i in range(phases):
        intended = {}
        if i > 0:
            lits = {}
            for s in injectable:
                if i >= len(read_values(s)):
                    continue
                v = read_values(s)[i]
                intended[s["tag"]] = cn.f32(v) if s["datatype"] == "REAL32" else v
                lits[expr(s)] = literal(s["plc_type"], v)
            bridge.write(lits)
        else:
            for s in injectable:
                v = s.get("plc_initial")
                intended[s["tag"]] = cn.f32(v) if s["datatype"] == "REAL32" else v
        time.sleep(SETTLE_S)
        observe(f"R{i}" if injectable else "R0_observe", intended)

    informative = [x for x in res["real32_samples"] if 0 < len(x["matching_orderings"]) < len(cn.ORDERINGS)]
    cands = set(cn.ORDERINGS)
    for x in res["real32_samples"]:
        cands &= set(x["matching_orderings"])
    res["real32_candidates_after_reads"] = sorted(cands)
    if res["real32_samples"]:
        if len(cands) == 1 and informative:
            ordering["value"] = cands.pop()
        elif ref_order and ref_order in cands:
            ordering["value"] = ref_order
            res["real32_ordering_source"] = "reference (consistent with this profile's samples)"
        res["checks"]["real32_ordering_determined"] = ordering["value"] is not None
        if ref_order and ordering["value"]:
            res["checks"]["real32_ordering_matches_reference"] = ordering["value"] == ref_order
    elif ref_order:
        ordering["value"] = ref_order
    res["real32_ordering"] = cn.describe_ordering(ordering["value"]) if ordering["value"] else None

    nwrites = max((len(s.get("verification_values") or WRITE_TABLE[s["datatype"]]) for s in writes), default=0)
    for j in range(nwrites):
        intended = {}
        for s in writes:
            vals = s.get("verification_values") or WRITE_TABLE[s["datatype"]]
            if j >= len(vals):
                continue
            v = vals[j]
            case = {"phase": f"W{j + 1}", "tag": s["tag"], "path": "WRITE", "datatype": s["datatype"],
                    "intended": cn.f32(v) if s["datatype"] == "REAL32" else v}
            try:
                if s["area"] == "COIL":
                    r = mb.c.write_coil(s["address"], bool(v), device_id=mb.unit)
                    case["written_raw"] = bool(v)
                else:
                    if s["datatype"] == "REAL32" and not ordering["value"]:
                        raise ValueError("REAL32 register order not determined; write not attempted")
                    regs = encode(s, v, ordering["value"])
                    case["written_raw"] = regs
                    r = (mb.c.write_register(s["address"], regs[0], device_id=mb.unit) if len(regs) == 1
                         else mb.c.write_registers(s["address"], regs, device_id=mb.unit))
                case["write_accepted"] = not r.isError()
                case["function"] = {"COIL": "FC5"}.get(s["area"], "FC6" if s["length"] == 1 else "FC16")
            except Exception as ex:
                case["write_accepted"] = False
                case["error"] = str(ex)
            case["modbus_readback"] = mb.raw_of(s)
            if s["area"] == "COIL":
                case["overlay_register_raw"] = mb.regs(s["overlay"]["register_area"], s["overlay"]["register"], 1)
            intended[s["tag"]] = case["intended"]
            res["cases"].append(case)
        time.sleep(SETTLE_S)
        plc, vals, attempts, settled = plc_poll(writes, intended)
        for case in (c for c in res["cases"] if c["phase"] == f"W{j + 1}"):
            s = next(x for x in writes if x["tag"] == case["tag"])
            case["plc_raw"] = plc[expr(s)]
            case["plc_value"] = vals[s["tag"]]
            case["plc_poll_attempts"], case["plc_settled"] = attempts, settled
        observe(f"after_W{j + 1}", {})

    for c in res["cases"]:
        dt = c["datatype"]
        s = next(x for x in typed if x["tag"] == c["tag"])
        ch = {}
        if c["path"] == "READ":
            c["decoded"] = decode(s, c["modbus_raw"], ordering["value"])
            ch["modbus_read_ok"] = c["modbus_raw"] is not None
            ch["plc_stable_across_modbus_read"] = c["plc_stable_across_modbus_read"]
            ch["decoded_equals_plc"] = same(dt, c["decoded"], c["plc_value"])
            if c["intended"] is not None:
                ch["plc_equals_intended"] = same(dt, c["plc_value"], c["intended"])
                ch["decoded_equals_intended"] = same(dt, c["decoded"], c["intended"])
        else:
            ch["write_accepted"] = bool(c.get("write_accepted"))
            ch["modbus_readback_equals_written"] = c.get("modbus_readback") == c.get("written_raw")
            ch["plc_equals_intended"] = same(dt, c.get("plc_value"), c["intended"])
        c["checks"] = ch
        c["pass"] = all(ch.values())

    tags = {s["tag"] for s in typed}
    if {"SupplyTemp", "Setpoint", "HeatingValve"} <= tags:
        for ph in sorted({c["phase"] for c in res["cases"] if c["path"] == "READ"}):
            obs = {c["tag"]: c for c in res["cases"] if c["phase"] == ph and c["path"] == "READ"}
            sp_case = [c for c in res["cases"] if c["tag"] == "Setpoint" and c["path"] == "WRITE"
                       and ph == "after_" + c["phase"]]
            if not sp_case or "SupplyTemp" not in obs or "HeatingValve" not in obs:
                continue
            sp, st = sp_case[0]["plc_value"], obs["SupplyTemp"]["plc_value"]
            want = 100.0 if st < sp else 0.0
            hv = obs["HeatingValve"]
            res["behavior"].append({"phase": ph, "SupplyTemp": st, "Setpoint": sp, "expected_HeatingValve": want,
                                    "plc_HeatingValve": hv["plc_value"], "modbus_HeatingValve": hv["decoded"],
                                    "pass": same("REAL32", hv["plc_value"], want) and same("REAL32", hv["decoded"], want)})
        res["checks"]["ahu_heating_logic_over_modbus"] = bool(res["behavior"]) and all(b["pass"] for b in res["behavior"])
    return finish(stage, res, mapping, mpath, bridge, None)


def finish(stage, res, mapping, mpath, bridge, fatal):
    try:
        bridge.call({"op": "quit"}, timeout=30)
        res["bridge_quit"] = True
    except Exception as ex:
        res["bridge_quit"] = False
        res["bridge_quit_error"] = str(ex)
    s1 = {}
    p = stage / "logs" / "s1_regression.json"
    if p.exists():
        s1 = json.loads(p.read_text(encoding="utf-8"))
    per = {}
    for s in mapping["signals"]:
        if s.get("bits"):
            ok = s1.get("operation_status") == "PASS"
            per[s["tag"]] = {"pass": ok, "cases": 1, "method": "F06 S1 regression (HR command word -> IR status word)"}
            continue
        cs = [c for c in res["cases"] if c["tag"] == s["tag"]]
        ok = bool(cs) and all(c["pass"] for c in cs)
        if s["datatype"] == "REAL32":
            ok = ok and res.get("real32_ordering") is not None
        per[s["tag"]] = {"pass": ok, "cases": len(cs),
                         "paths": sorted({c["path"] for c in cs}),
                         "method": "pymodbus + PLC online read-back"}
    res["per_signal"] = per
    for s in mapping["signals"]:
        v = per[s["tag"]]
        s["verified"] = bool(v["pass"]) and fatal is None
        s["verification"] = dict(v, stage=str(stage)) if s["verified"] else None
        if s["verified"] and s["datatype"] == "REAL32":
            o = res["real32_ordering"]
            s["byte_order"], s["word_order"], s["register_order"] = o["byte_order"], o["word_order"], o["register_order"]
            s["measured_ordering"] = o["name"]
        elif s["verified"] and s["datatype"] in ("INT16", "UINT16", "WORD"):
            s["byte_order"] = "big-endian within the register (Modbus standard), measured: decoded == PLC value"
    if res.get("real32_ordering"):
        mapping["real32"] = {"registers_per_value": 2, "measured_ordering": res["real32_ordering"],
                             "verified": any(s["verified"] for s in mapping["signals"] if s["datatype"] == "REAL32")}
    mpath.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    c = res["checks"]
    c["all_cases_pass"] = bool(res["cases"]) and all(x["pass"] for x in res["cases"])
    c["all_signals_verified"] = all(v["pass"] for v in per.values())
    c["bridge_quit"] = res["bridge_quit"]
    failed = [k for k, v in c.items() if not v]
    ok = fatal is None and not failed
    res["operation_status"] = "PASS" if ok else "FAILED"
    res["reason"] = fatal or ("all typed cases passed; %d signals verified" % len(per) if ok
                              else "failed: " + ", ".join(failed))
    res["exit_code_intended"] = 0 if ok else 20
    (stage / "logs" / "typed_verify.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return res["exit_code_intended"]


if __name__ == "__main__":
    sys.exit(main())
