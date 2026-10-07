"""S1-FIX external Modbus verification (CPython + pymodbus).

TCP connect -> baseline HR0/IR0 -> HR0=1, poll IR0 until 3 -> HR0=2, poll IR0 until 0.
Polls real register state (no fixed sleeps as evidence). Updates
engineering/modbus_mapping.json: verified=true only for registers whose read-back passed.
Exit: 0 PASS, 20 FAILED.

Usage: python modbus_probe.py --stage <dir> [--timeout 10] [--interval 0.2]
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

from pymodbus.client import ModbusTcpClient


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--interval", type=float, default=0.2)
    a = ap.parse_args()
    stage = Path(a.stage)
    mapping_path = stage / "engineering" / "modbus_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    host, port, unit = mapping["host"], mapping["port"], mapping["slave"]
    hr = next(r for r in mapping["registers"] if r["area"] == "holding")
    ir = next(r for r in mapping["registers"] if r["area"] == "input")
    out = {"step": "modbus_probe", "host": host, "port": port, "slave": unit,
           "hr_address": hr["address"], "ir_address": ir["address"], "events": [], "checks": {}}

    def ev(kind, **kw):
        out["events"].append({"t": now(), "kind": kind, **kw})

    def finish(status, reason, code):
        out["operation_status"], out["reason"] = status, reason
        out["exit_code_intended"] = code
        (stage / "logs" / "modbus_probe.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"OPERATION_STATUS={status} {reason}")
        return code

    try:
        with socket.create_connection((host, port), timeout=3):
            pass
        out["checks"]["tcp_connect"] = True
        ev("tcp_connect", ok=True)
    except OSError as ex:
        out["checks"]["tcp_connect"] = False
        ev("tcp_connect", ok=False, error=str(ex))
        return finish("FAILED", f"TCP connect to {host}:{port} failed: {ex}", 20)

    c = ModbusTcpClient(host, port=port, timeout=2.0)
    if not c.connect():
        out["checks"]["pymodbus_connect"] = False
        return finish("FAILED", "pymodbus connect failed", 20)
    out["checks"]["pymodbus_connect"] = True

    def read(area):
        if area == "holding":
            r = c.read_holding_registers(hr["address"], count=1, device_id=unit)
        else:
            r = c.read_input_registers(ir["address"], count=1, device_id=unit)
        if r.isError():
            raise RuntimeError(f"read {area} error: {r}")
        return int(r.registers[0])

    def write_hr(value):
        r = c.write_register(hr["address"], value, device_id=unit)
        ok = not r.isError()
        ev("write_hr", value=value, ok=ok, response=str(r))
        return ok

    def poll_ir(expected):
        deadline = time.monotonic() + a.timeout
        samples = []
        while True:
            v = read("input")
            samples.append({"t": now(), "ir": v})
            if v == expected:
                return True, samples
            if time.monotonic() >= deadline:
                return False, samples
            time.sleep(a.interval)

    try:
        b_hr, b_ir = read("holding"), read("input")
        out["baseline"] = {"hr": b_hr, "ir": b_ir}
        out["checks"]["baseline_hr0_ir0_zero"] = b_hr == 0 and b_ir == 0
        ev("baseline", hr=b_hr, ir=b_ir)

        for name, cmd, expect in (("start", 1, 3), ("stop", 2, 0)):
            out["checks"][f"{name}_write_accepted"] = write_hr(cmd)
            rb = read("holding")
            out["checks"][f"{name}_hr_readback"] = rb == cmd
            ev("hr_readback", value=rb)
            reached, samples = poll_ir(expect)
            out[f"{name}_ir_samples"] = samples
            out["checks"][f"{name}_ir_reached_{expect}"] = reached
            ev("ir_poll", expected=expect, reached=reached, last=samples[-1]["ir"], n=len(samples))

        write_hr(0)
        out["final"] = {"hr": read("holding"), "ir": read("input")}
    except Exception as ex:
        ev("exception", error=str(ex))
        c.close()
        return finish("FAILED", f"modbus exception: {ex}", 20)
    c.close()

    acceptance = ["tcp_connect", "pymodbus_connect", "start_write_accepted", "start_hr_readback",
                  "start_ir_reached_3", "stop_write_accepted", "stop_hr_readback", "stop_ir_reached_0"]
    failed = [k for k in acceptance if not out["checks"].get(k)]
    passed = not failed
    hr["verified"] = bool(out["checks"].get("start_hr_readback") and out["checks"].get("stop_hr_readback") and passed)
    ir["verified"] = bool(out["checks"].get("start_ir_reached_3") and out["checks"].get("stop_ir_reached_0") and passed)
    for r in (hr, ir):
        r["verification"] = {"probe": str(stage / "logs" / "modbus_probe.json"), "time": now()} if r["verified"] else None
    mapping_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    if not out["checks"].get("baseline_hr0_ir0_zero"):
        ev("note", text="baseline not zero; recorded, not part of acceptance")
    return finish("PASS" if passed else "FAILED",
                  "HR0=1 -> IR0=3 and HR0=2 -> IR0=0 observed" if passed else "failed checks: " + ", ".join(failed),
                  0 if passed else 20)


if __name__ == "__main__":
    sys.exit(main())
