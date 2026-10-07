"""S1-FIX deterministic generator (CPython, no LLM).

engineering model (JSON) -> PLC_PRG ST with a 16-bit Modbus image
                         -> engineering/modbus_mapping.json (verified=false until read-back)
                         -> engineering/codesys_plan.json (device tree + I/O mapping for ScriptEngine)

Usage: python generate.py --model <ahu01.json> --stage <staging dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORD_BITS = 16
SUPPORTED_IMAGE_TYPES = {"WORD"}


def bool_st(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def real_st(v: float) -> str:
    return f"{float(v):.1f}"


def literal(var: dict) -> str:
    if var["type"] == "BOOL":
        return bool_st(var["initial"])
    if var["type"] == "REAL":
        return real_st(var["initial"])
    raise ValueError(f"unsupported variable type {var['type']}")


def validate(model: dict) -> list[str]:
    errors = []
    vars_ = model["variables"]
    mb = model["modbus"]
    seen = set()
    for img in mb["images"]:
        if img["iec_type"] not in SUPPORTED_IMAGE_TYPES:
            errors.append(f"{img['tag']}: image type {img['iec_type']} not supported (16-bit WORD only)")
        key = (img["area"], img["address"])
        if key in seen:
            errors.append(f"{img['tag']}: duplicate register {key}")
        seen.add(key)
        if img["plc_var"] in vars_:
            errors.append(f"{img['tag']}: image variable {img['plc_var']} collides with a model variable")
        for bit, name in img["bits"].items():
            if not 0 <= int(bit) < WORD_BITS:
                errors.append(f"{img['tag']}: bit {bit} out of range")
            if name not in vars_:
                errors.append(f"{img['tag']}: bit {bit} references unknown variable {name}")
            elif vars_[name]["type"] != "BOOL":
                errors.append(f"{img['tag']}: bit {bit} variable {name} is {vars_[name]['type']}, only BOOL can be packed")
    for u in mb.get("unmapped", []):
        if u["var"] not in vars_:
            errors.append(f"unmapped entry references unknown variable {u['var']}")
    return errors


def generate_st(model: dict) -> tuple[str, str]:
    vars_ = model["variables"]
    images = model["modbus"]["images"]
    decl = ["PROGRAM PLC_PRG", "VAR", f"    (* Deterministic demo for {model['ahu_id']} *)"]
    for name, v in vars_.items():
        decl.append(f"    {name} : {v['type']} := {literal(v)};")
    decl.append("    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)")
    for img in images:
        area = "HR" if img["area"] == "holding" else "IR"
        bits = ", ".join(f"bit{b}={n}" for b, n in sorted(img["bits"].items(), key=lambda kv: int(kv[0])))
        decl.append(f"    {img['plc_var']} : {img['iec_type']}; (* {area}{img['address']} {img['tag']}: {bits} *)")
    decl += ["END_VAR", ""]

    impl = []
    for img in (i for i in images if i["direction"] == "client_to_plc"):
        area = "HR" if img["area"] == "holding" else "IR"
        impl.append(f"(* MODBUS IN: {area}{img['address']} {img['tag']} word -> commands *)")
        for b, n in sorted(img["bits"].items(), key=lambda kv: int(kv[0])):
            impl.append(f"{n} := {img['plc_var']}.{int(b)};")
        impl.append("")

    impl += [
        "(* FAN START *)",
        "IF StartCommand = TRUE AND FanFault = FALSE THEN",
        "    FanCommand := TRUE;",
        "    FanRunning := TRUE;",
        "END_IF;",
        "",
        "(* FAN STOP *)",
        "IF StopCommand = TRUE THEN",
        "    FanCommand := FALSE;",
        "    FanRunning := FALSE;",
        "END_IF;",
        "",
        "(* FAN FAULT *)",
        "IF FanFault = TRUE THEN",
        "    FanCommand := FALSE;",
        "    FanRunning := FALSE;",
        "END_IF;",
        "",
        "(* HEATING - simple demo, not PID *)",
        "IF SupplyTemp < Setpoint THEN",
        "    HeatingValve := 100.0;",
        "ELSE",
        "    HeatingValve := 0.0;",
        "END_IF;",
        "",
    ]

    for img in (i for i in images if i["direction"] == "plc_to_client"):
        area = "HR" if img["area"] == "holding" else "IR"
        impl.append(f"(* MODBUS OUT: status -> {area}{img['address']} {img['tag']} word *)")
        impl.append(f"{img['plc_var']} := 0;")
        for b, n in sorted(img["bits"].items(), key=lambda kv: int(kv[0])):
            impl.append(f"{img['plc_var']}.{int(b)} := {n};")
        impl.append("")
    return "\n".join(decl), "\n".join(impl)


def mapping_artifact(model: dict) -> dict:
    mb = model["modbus"]
    regs = []
    for img in mb["images"]:
        regs.append({
            "address": img["address"],
            "area": img["area"],
            "function_read": "FC3" if img["area"] == "holding" else "FC4",
            "function_write": "FC6/FC16" if img["area"] == "holding" else "none",
            "tag": img["tag"],
            "plc_var": f"Application.PLC_PRG.{img['plc_var']}",
            "datatype": img["iec_type"],
            "register_count": 1,
            "bits": {b: n for b, n in sorted(img["bits"].items(), key=lambda kv: int(kv[0]))},
            "verified": False,
            "verification": None,
        })
    return {
        "protocol": mb["protocol"],
        "host": mb["host"],
        "port": mb["port"],
        "slave": mb["slave"],
        "source_model": model["ahu_id"],
        "registers": regs,
        "unmapped": mb.get("unmapped", []),
        "verified_rule": "verified=true only after external pymodbus read-back against the running generated PLC",
    }


def codesys_plan(model: dict) -> dict:
    mb = model["modbus"]
    cs = mb["codesys"]
    io = []
    for img in mb["images"]:
        io.append({
            "device": cs["server"]["name"],
            "parameter": cs["holding_parameter"] if img["area"] == "holding" else cs["input_parameter"],
            "word_index": img["address"],
            "variable": f"Application.PLC_PRG.{img['plc_var']}",
            "iec_type": img["iec_type"],
        })
    return {
        "project_file": "AI_BMS_AHU_DEMO.project",
        "boot_app_file": "AI_BMS_AHU_DEMO.app",
        "plc_device_repo_name": cs["plc_device_repo_name"],
        "devices": [
            {"parent": "Device", **cs["adapter"]},
            {"parent": cs["adapter"]["name"], **cs["server"]},
        ],
        "server_expect": {cs["port_parameter"]: mb["port"]},
        "io_mappings": io,
        "required_variables": list(model["variables"].keys()) + [i["plc_var"] for i in mb["images"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--stage", required=True)
    a = ap.parse_args()

    stage = Path(a.stage)
    gen, eng, logs = stage / "generated", stage / "engineering", stage / "logs"
    for d in (gen, eng, logs):
        d.mkdir(parents=True, exist_ok=True)
    result = {"step": "generate", "model": str(Path(a.model).resolve()), "artifacts": []}

    model = json.loads(Path(a.model).read_text(encoding="utf-8"))
    errors = validate(model)
    if errors:
        result.update(operation_status="FAILED", reason="model validation failed", errors=errors)
        (logs / "generate_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("GENERATE FAILED: " + "; ".join(errors))
        return 2

    decl, impl = generate_st(model)
    outputs = {
        gen / "PLC_PRG_decl.st": decl,
        gen / "PLC_PRG_impl.st": impl,
        gen / "PLC_PRG.st": decl + "\n" + impl,
        eng / "modbus_mapping.json": json.dumps(mapping_artifact(model), indent=2),
        eng / "codesys_plan.json": json.dumps(codesys_plan(model), indent=2),
    }
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        result["artifacts"].append(str(path))
        print(f"WROTE {path}")
    result.update(operation_status="PASS", reason="ST + mapping + codesys plan generated")
    (logs / "generate_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
