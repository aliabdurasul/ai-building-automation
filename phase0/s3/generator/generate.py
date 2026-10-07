"""S3 deterministic generator (CPython, no LLM).

canonical model + profile -> validate -> allocate
  -> generated/PLC_PRG_{decl,impl}.st, PLC_PRG.st
  -> engineering/allocation.json        (resolved, stable addresses)
  -> engineering/modbus_mapping.json    (canonical mapping, verified=false until real read-back)
  -> engineering/codesys_plan.json      (device tree + channel mappings for the ScriptEngine adapter)

Usage: python generate.py --model <s3_model.json> --profile <types|ahu> --stage <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import canonical as cn  # noqa: E402

AREA_SHORT = {"HOLDING_REGISTER": "HR", "INPUT_REGISTER": "IR", "COIL": "C", "DISCRETE_INPUT": "DI"}
TO_WORD = {"INT16": "INT_TO_WORD", "UINT16": "UINT_TO_WORD"}
FROM_WORD = {"INT16": "WORD_TO_INT", "UINT16": "WORD_TO_UINT"}
APP = "Application.PLC_PRG."


def literal(type_: str, v) -> str:
    if type_ == "BOOL":
        return "TRUE" if v else "FALSE"
    if type_ == "REAL":
        return repr(float(v))
    if type_ == "WORD":
        return f"16#{int(v):04X}"
    return str(int(v))


def loc(e: dict) -> str:
    s = AREA_SHORT[e["area"]]
    if e["length"] == 2:
        return f"{s}{e['address']}..{s}{e['address'] + 1}"
    return f"{s}{e['address']}"


def image_words(e: dict) -> list[str]:
    """Generated image variables bound to Modbus channels.

    CODESYS only updates I/O-mapped variables that a task references, so every channel is bound
    to an image variable that PLC_PRG reads or writes (bit-packed S1 words are their own image)."""
    if e["datatype"] == "REAL32":
        return [f"Mb_{e['tag']}_W0", f"Mb_{e['tag']}_W1"]
    if e["datatype"] == "WORD" and e.get("bits"):
        return [e["plc_var"]]
    return [f"Mb_{e['tag']}"]


def declared_variables(model: dict, entries: list[dict]) -> list[str]:
    ahu = [n for n, v in model["variables"].items() if v["role"] != "s3_test"]
    used = {e["plc_var"] for e in entries}
    tests = [n for n, v in model["variables"].items() if v["role"] == "s3_test" and n in used]
    return ahu + tests


# S1-FIX AHU behaviour; the default logic block for S3/S6 models (S2 models select logic templates instead).
AHU_S1FIX_LOGIC = (
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
)


def generate_st(model: dict, entries: list[dict], logic: list[str] | None = None,
                title: str | None = None) -> tuple[str, str]:
    """I/O image code is generic; `logic` is the equipment behaviour block (default: S1-FIX AHU)."""
    vars_ = model["variables"]
    decl = ["PROGRAM PLC_PRG", "VAR", f"    (* Deterministic demo for {title or model['ahu_id']} *)"]
    for name in declared_variables(model, entries):
        v = vars_[name]
        decl.append(f"    {name} : {v['type']} := {literal(v['type'], v['initial'])};")
    decl.append("    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)")
    for e in entries:
        if e["datatype"] == "WORD" and e.get("bits"):
            bits = ", ".join(f"bit{b}={n}" for b, n in e["bits"].items())
            decl.append(f"    {e['plc_var']} : WORD; (* {loc(e)} {e['tag']}: {bits} *)")
        elif e["datatype"] == "WORD":
            decl.append(f"    Mb_{e['tag']} : WORD; (* {loc(e)} {e['tag']} WORD {e['direction']} *)")
        elif e["datatype"] == "BOOL":
            ov = e["overlay"]
            decl.append(f"    Mb_{e['tag']} : BOOL; (* {loc(e)} {e['tag']} = {AREA_SHORT[ov['register_area']]}{ov['register']} PLC bit {ov['plc_bit']} *)")
        elif e["datatype"] in ("INT16", "UINT16"):
            decl.append(f"    Mb_{e['tag']} : WORD; (* {loc(e)} {e['tag']} {e['datatype']} {e['direction']} *)")
        elif e["datatype"] == "REAL32":
            w0, w1 = image_words(e)
            decl.append(f"    {w0} : WORD; (* {AREA_SHORT[e['area']]}{e['address']} {e['tag']} REAL32 memory word 0 *)")
            decl.append(f"    {w1} : WORD; (* {AREA_SHORT[e['area']]}{e['address'] + 1} {e['tag']} REAL32 memory word 1 *)")
            decl.append(f"    p_{e['tag']} : POINTER TO ARRAY[0..1] OF WORD;")
            if e["direction"] == "READ_WRITE":
                decl.append(f"    {w0}_prev : WORD;")
                decl.append(f"    {w1}_prev : WORD;")
    decl += ["END_VAR", ""]

    impl = []
    for e in (x for x in entries if x["direction"] in ("WRITE", "READ_WRITE")):
        dt = e["datatype"]
        if dt == "WORD" and e.get("bits"):
            impl.append(f"(* MODBUS IN: {loc(e)} {e['tag']} word -> commands *)")
            for b, n in e["bits"].items():
                impl.append(f"{n} := {e['plc_var']}.{int(b)};")
            impl.append("")
        elif dt in ("WORD", "BOOL"):
            impl.append(f"(* MODBUS IN: {loc(e)} {e['tag']} {dt} *)")
            impl.append(f"{e['plc_var']} := Mb_{e['tag']};")
            impl.append("")
        elif dt in ("INT16", "UINT16"):
            impl.append(f"(* MODBUS IN: {loc(e)} {e['tag']} {dt} *)")
            impl.append(f"{e['plc_var']} := {FROM_WORD[dt]}(Mb_{e['tag']});")
            impl.append("")
        elif dt == "REAL32":
            w0, w1 = image_words(e)
            impl.append(f"(* MODBUS IN: {loc(e)} {e['tag']} REAL32 (register words -> REAL memory) *)")
            if e["direction"] == "READ_WRITE":
                impl.append(f"IF {w0} <> {w0}_prev OR {w1} <> {w1}_prev THEN")
                impl.append(f"    p_{e['tag']} := ADR({e['plc_var']});")
                impl.append(f"    p_{e['tag']}^[0] := {w0};")
                impl.append(f"    p_{e['tag']}^[1] := {w1};")
                impl.append(f"    {w0}_prev := {w0};")
                impl.append(f"    {w1}_prev := {w1};")
                impl.append("END_IF;")
            else:
                impl.append(f"p_{e['tag']} := ADR({e['plc_var']});")
                impl.append(f"p_{e['tag']}^[0] := {w0};")
                impl.append(f"p_{e['tag']}^[1] := {w1};")
            impl.append("")

    impl += list(AHU_S1FIX_LOGIC if logic is None else logic)

    for e in (x for x in entries if x["direction"] == "READ"):
        dt = e["datatype"]
        if dt == "WORD" and e.get("bits"):
            impl.append(f"(* MODBUS OUT: status -> {loc(e)} {e['tag']} word *)")
            impl.append(f"{e['plc_var']} := 0;")
            for b, n in e["bits"].items():
                impl.append(f"{e['plc_var']}.{int(b)} := {n};")
            impl.append("")
        elif dt in ("WORD", "BOOL"):
            impl.append(f"(* MODBUS OUT: {e['tag']} {dt} -> {loc(e)} *)")
            impl.append(f"Mb_{e['tag']} := {e['plc_var']};")
            impl.append("")
        elif dt in ("INT16", "UINT16"):
            impl.append(f"(* MODBUS OUT: {e['tag']} {dt} -> {loc(e)} *)")
            impl.append(f"Mb_{e['tag']} := {TO_WORD[dt]}({e['plc_var']});")
            impl.append("")
        elif dt == "REAL32":
            w0, w1 = image_words(e)
            impl.append(f"(* MODBUS OUT: {e['tag']} REAL32 (REAL memory -> register words) -> {loc(e)} *)")
            impl.append(f"p_{e['tag']} := ADR({e['plc_var']});")
            impl.append(f"{w0} := p_{e['tag']}^[0];")
            impl.append(f"{w1} := p_{e['tag']}^[1];")
            impl.append("")
    return "\n".join(decl), "\n".join(impl)


def channel_mappings(model: dict, entries: list[dict]) -> list[dict]:
    cs = model["platform"]["codesys"]
    io = []
    for e in entries:
        if e["area"] in cn.REGISTER_AREAS:
            for k, w in enumerate(image_words(e)):
                io.append({"tag": e["tag"], "device": cs["server"]["name"],
                           "parameter": cs["area_parameter"][e["area"]],
                           "word_index": e["address"] + k, "variable": APP + w})
        else:
            ov = e["overlay"]
            io.append({"tag": e["tag"], "device": cs["server"]["name"],
                       "parameter": cs["area_parameter"][ov["register_area"]],
                       "word_index": ov["register"], "bit_index": ov["plc_bit"], "variable": APP + image_words(e)[0]})
    return io


def mapping_artifact(model: dict, profile: str, entries: list[dict], model_sha: str, io: list[dict]) -> dict:
    sigs = []
    src = {s["tag"]: s for s in cn.signals_for(model, profile)}
    for e in entries:
        s = dict(e)
        s["plc_path"] = APP + e["plc_var"]
        var = model["variables"].get(e["plc_var"])
        if var is not None:
            s["role"] = var["role"]
            s["plc_initial"] = var["initial"]
        if "verification_values" in src[e["tag"]]:
            s["verification_values"] = src[e["tag"]]["verification_values"]
        s["codesys_channels"] = [{k: m[k] for k in ("parameter", "word_index", "bit_index", "variable") if k in m}
                                 for m in io if m["tag"] == e["tag"]]
        if e["datatype"] == "REAL32":
            s["encoding"] = "IEEE 754 binary32 in 2 consecutive 16-bit registers"
            s["byte_order"] = s["word_order"] = s["register_order"] = "UNVERIFIED"
        elif e["datatype"] == "BOOL":
            s["encoding"] = f"single bit; overlays {e['overlay']['register_area']} {e['overlay']['register']} PLC bit {e['overlay']['plc_bit']}"
            s["byte_order"] = s["word_order"] = "n/a"
        else:
            s["encoding"] = "16-bit register"
            s["byte_order"] = "UNVERIFIED"
            s["word_order"] = "n/a (1 register)"
        s["verified"] = False
        s["verification"] = None
        sigs.append(s)
    mapped = {e["plc_var"] for e in entries} | {n for e in entries for n in e.get("bits", {}).values()}
    declared = declared_variables(model, entries)
    unmapped = [{"var": n, "type": model["variables"][n]["type"],
                 "reason": "not selected in profile '%s' (mapped in another profile / register capacity 10 per area)" % profile}
                for n in declared if n not in mapped]
    return {
        "schema": "s3.modbus_mapping.v1",
        "protocol": model["modbus"]["protocol"],
        "host": model["modbus"]["host"],
        "port": model["modbus"]["port"],
        "unit_id": model["modbus"]["slave"],
        "model_id": model["model_id"],
        "model_sha256": model_sha,
        "profile": profile,
        "platform": {k: model["platform"][k] for k in ("register_capacity", "bit_overlay", "real32_layout_rule")},
        "real32": {"registers_per_value": 2, "measured_ordering": None, "verified": False},
        "signals": sigs,
        "unmapped": unmapped,
        "unsupported": model["platform"].get("unsupported", []),
        "verified_rule": "verified=true only after real runtime + external pymodbus read/write with PLC-side online read-back",
    }


def codesys_plan(model: dict, profile: str, entries: list[dict], io: list[dict]) -> dict:
    cs = model["platform"]["codesys"]
    expect = dict(cs["server_expect"])
    expect["Port"] = str(model["modbus"]["port"])
    return {
        "project_file": f"AI_BMS_S3_{profile}.project",
        "boot_app_file": f"AI_BMS_S3_{profile}.app",
        "plc_device_repo_name": cs["plc_device_repo_name"],
        "devices": [
            {"parent": "Device", **cs["adapter"]},
            {"parent": cs["adapter"]["name"], **cs["server"]},
        ],
        "server_expect": expect,
        "channel_counts": {cs["area_parameter"][a]: model["platform"]["register_capacity"][a] for a in cn.REGISTER_AREAS},
        "io_mappings": [{k: v for k, v in m.items() if k != "tag"} for m in io],
        "required_variables": declared_variables(model, entries)
                              + [w for e in entries for w in image_words(e) if w != e["plc_var"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--stage", required=True)
    a = ap.parse_args()

    stage = Path(a.stage)
    gen, eng, logs = stage / "generated", stage / "engineering", stage / "logs"
    for d in (gen, eng, logs):
        d.mkdir(parents=True, exist_ok=True)
    raw = Path(a.model).read_bytes()
    model = json.loads(raw.decode("utf-8"))
    model_sha = hashlib.sha256(raw).hexdigest()
    result = {"step": "generate", "profile": a.profile, "model": str(Path(a.model).resolve()),
              "model_sha256": model_sha, "artifacts": []}

    errors = cn.validate(model, a.profile)
    if errors:
        result.update(operation_status="FAILED", reason="model validation failed (before CODESYS generation)", errors=errors)
        (logs / "generate_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("GENERATE FAILED: " + "; ".join(errors))
        return 20

    entries = cn.allocate(model, a.profile)
    io = channel_mappings(model, entries)
    decl, impl = generate_st(model, entries)
    allocation = {"model_id": model["model_id"], "profile": a.profile, "model_sha256": model_sha,
                  "allocation": [{k: e[k] for k in ("tag", "datatype", "direction", "area", "address", "length", "allocation")}
                                 for e in entries]}
    outputs = {
        gen / "PLC_PRG_decl.st": decl,
        gen / "PLC_PRG_impl.st": impl,
        gen / "PLC_PRG.st": decl + "\n" + impl,
        eng / "allocation.json": json.dumps(allocation, indent=2),
        eng / "modbus_mapping.json": json.dumps(mapping_artifact(model, a.profile, entries, model_sha, io), indent=2),
        eng / "codesys_plan.json": json.dumps(codesys_plan(model, a.profile, entries, io), indent=2),
    }
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        result["artifacts"].append(str(path))
        print(f"WROTE {path}")
    result["allocation"] = allocation["allocation"]
    result.update(operation_status="PASS", reason="validated, allocated, ST + mapping + codesys plan generated")
    (logs / "generate_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
