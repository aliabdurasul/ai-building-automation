"""S6 S1 regression over real Modbus TCP (pymodbus); addresses come from the revision mapping.

Command word (HOLDING, bit0 Start, bit1 Stop) -> Status word (INPUT, bit0 FanCommand, bit1 FanRunning,
bit2 FanFault). HR=1 -> IR=3 and HR=2 -> IR=0 must be observed, every status bit is checked by name, and
a FanRunning discrete input (if mapped in this revision) must follow the fan state.
Usage: python s1_regression.py --stage <deploy stage>    Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

POLL_S, TIMEOUT_S = 0.2, 10.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    stage = Path(ap.parse_args().stage)
    mapping = json.loads((stage / "engineering" / "modbus_mapping.json").read_text(encoding="utf-8"))
    by = {s["tag"]: s for s in mapping["signals"]}
    cmd, sts = by["Command"], by["Status"]
    hr, ir = cmd["address"], sts["address"]
    status_bits = {n: int(b) for b, n in sts["bits"].items()}
    di = next((s for s in mapping["signals"] if s["area"] == "DISCRETE_INPUT" and s["plc_var"] == "FanRunning"), None)
    host, port, unit = mapping["host"], mapping["port"], mapping["unit_id"]
    res = {"step": "s1_regression", "revision": mapping.get("revision"), "host": host, "port": port, "unit_id": unit,
           "hr": hr, "ir": ir, "status_bits": status_bits, "fan_running_di": di["address"] if di else None, "checks": {}}
    c = res["checks"]
    try:
        socket.create_connection((host, port), timeout=3).close()
        c["tcp_connect"] = True
    except OSError as ex:
        c["tcp_connect"] = False
        res["error"] = str(ex)
    cli = ModbusTcpClient(host, port=port, timeout=3)
    c["pymodbus_connect"] = bool(cli.connect())

    def rd(fn, a):
        r = fn(a, count=1, device_id=unit)
        return None if r.isError() else r.registers[0]

    def rd_di():
        r = cli.read_discrete_inputs(di["address"], count=1, device_id=unit)
        return None if r.isError() else bool(r.bits[0])

    def wait_ir(want):
        t0, last = time.time(), None
        while time.time() - t0 < TIMEOUT_S:
            last = rd(cli.read_input_registers, ir)
            if last == want:
                return True, last
            time.sleep(POLL_S)
        return False, last

    def bits(word):
        return None if word is None else {n: bool(word >> b & 1) for n, b in sorted(status_bits.items())}

    if c["pymodbus_connect"]:
        res["baseline"] = {"hr": rd(cli.read_holding_registers, hr), "ir": rd(cli.read_input_registers, ir)}
        c["start_write_accepted"] = not cli.write_register(hr, 1, device_id=unit).isError()
        c["start_hr_readback"] = rd(cli.read_holding_registers, hr) == 1
        c["start_ir_reached_3"], res["start_ir_last"] = wait_ir(3)
        res["bits_after_start"] = bits(res["start_ir_last"])
        c["start_bits"] = res["bits_after_start"] == {"FanCommand": True, "FanFault": False, "FanRunning": True}
        if di:
            res["di_after_start"] = rd_di()
            c["start_fan_running_di"] = res["di_after_start"] is True
        c["stop_write_accepted"] = not cli.write_register(hr, 2, device_id=unit).isError()
        c["stop_hr_readback"] = rd(cli.read_holding_registers, hr) == 2
        c["stop_ir_reached_0"], res["stop_ir_last"] = wait_ir(0)
        res["bits_after_stop"] = bits(res["stop_ir_last"])
        c["stop_bits"] = res["bits_after_stop"] == {"FanCommand": False, "FanFault": False, "FanRunning": False}
        if di:
            res["di_after_stop"] = rd_di()
            c["stop_fan_running_di"] = res["di_after_stop"] is False
        cli.write_register(hr, 0, device_id=unit)
        cli.close()
    required = ["tcp_connect", "pymodbus_connect", "start_write_accepted", "start_hr_readback", "start_ir_reached_3",
                "start_bits", "stop_write_accepted", "stop_hr_readback", "stop_ir_reached_0", "stop_bits"]
    if di:
        required += ["start_fan_running_di", "stop_fan_running_di"]
    ok = all(c.get(k) for k in required)
    res["operation_status"] = "PASS" if ok else "FAILED"
    res["reason"] = ("HR%d=1 -> IR%d=3 (FanCommand, FanRunning set, FanFault clear) and HR%d=2 -> IR%d=0 observed%s"
                     % (hr, ir, hr, ir, "; FanRunning DI%d followed" % di["address"] if di else "")) if ok \
        else "S1 regression failed: " + ", ".join(k for k in required if not c.get(k))
    res["exit_code_intended"] = 0 if ok else 20
    (stage / "logs").mkdir(exist_ok=True)
    (stage / "logs" / "s1_regression.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return res["exit_code_intended"]


if __name__ == "__main__":
    sys.exit(main())
