"""S3 F06: S1 regression over real Modbus TCP (pymodbus), addresses taken from the S3 mapping.

Command word (HOLDING) bit0=Start, bit1=Stop; Status word (INPUT) bit0 FanCommand, bit1 FanRunning.
HR=1 -> IR=3 and HR=2 -> IR=0 must be observed. Exit: 0 PASS, 20 FAILED.

Usage: python s1_regression.py --stage <dir>
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
    hr, ir = by["Command"]["address"], by["Status"]["address"]
    host, port, unit = mapping["host"], mapping["port"], mapping["unit_id"]
    res = {"step": "s1_regression", "host": host, "port": port, "unit_id": unit, "hr": hr, "ir": ir, "checks": {}}
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

    def wait_ir(want):
        t0 = time.time()
        last = None
        while time.time() - t0 < TIMEOUT_S:
            last = rd(cli.read_input_registers, ir)
            if last == want:
                return True, last
            time.sleep(POLL_S)
        return False, last

    if c["pymodbus_connect"]:
        res["baseline"] = {"hr": rd(cli.read_holding_registers, hr), "ir": rd(cli.read_input_registers, ir)}
        c["start_write_accepted"] = not cli.write_register(hr, 1, device_id=unit).isError()
        c["start_hr_readback"] = rd(cli.read_holding_registers, hr) == 1
        c["start_ir_reached_3"], res["start_ir_last"] = wait_ir(3)
        c["stop_write_accepted"] = not cli.write_register(hr, 2, device_id=unit).isError()
        c["stop_hr_readback"] = rd(cli.read_holding_registers, hr) == 2
        c["stop_ir_reached_0"], res["stop_ir_last"] = wait_ir(0)
        cli.write_register(hr, 0, device_id=unit)
        cli.close()
    ok = all(c.get(k) for k in ("tcp_connect", "pymodbus_connect", "start_write_accepted", "start_hr_readback",
                                "start_ir_reached_3", "stop_write_accepted", "stop_hr_readback", "stop_ir_reached_0"))
    res["operation_status"] = "PASS" if ok else "FAILED"
    res["reason"] = "HR%d=1 -> IR%d=3 and HR%d=2 -> IR%d=0 observed" % (hr, ir, hr, ir) if ok else "S1 regression failed"
    res["exit_code_intended"] = 0 if ok else 20
    (stage / "logs" / "s1_regression.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return res["exit_code_intended"]


if __name__ == "__main__":
    sys.exit(main())
