"""S1-FIX run-vs-run semantic comparison (measurement only).

Semantic fields are compared after dropping run-specific values (paths, timestamps).
Binary files (.project/.app) are hashed for information; byte equality is not required.
Usage: python compare_s1fix.py [runA runB]   (default run1 run2)
Output: docs/phase0/S1_FIX_comparison.json (default pair) or S1_FIX_comparison_<a>_<b>.json
"""
import hashlib
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
STAGE = r"C:\AI_BMS_PHASE0\s1fix\{run}"


def load(run, *parts):
    p = os.path.join(STAGE.format(run=run), *parts)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8-sig")) if p.endswith(".json") else raw


def sha(b):
    return hashlib.sha256(b).hexdigest() if b is not None else None


def strip(obj, drop=("project", "model", "artifacts", "path", "log", "result_file", "stdout", "stderr",
                     "timestamp", "duration_seconds", "command", "verification", "time", "t")):
    if isinstance(obj, dict):
        return {k: strip(v, drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [strip(v, drop) for v in obj]
    return obj


def main():
    ra, rb = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("run1", "run2")
    name = "S1_FIX_comparison.json" if (ra, rb) == ("run1", "run2") else "S1_FIX_comparison_%s_%s.json" % (ra, rb)
    out_path = os.path.join(REPO, "docs", "phase0", name)
    items = []

    def add(label, a, b, kind="semantic"):
        items.append({"item": label, "kind": kind, "equal": a == b, ra: a, rb: b})

    for f in ("PLC_PRG_decl.st", "PLC_PRG_impl.st", "PLC_PRG.st"):
        add("generated ST " + f + " (sha256)", sha(load(ra, "generated", f)), sha(load(rb, "generated", f)))
    add("modbus_mapping.json", strip(load(ra, "engineering", "modbus_mapping.json")),
        strip(load(rb, "engineering", "modbus_mapping.json")))
    add("codesys_plan.json", load(ra, "engineering", "codesys_plan.json"), load(rb, "engineering", "codesys_plan.json"))

    c1, c2 = load(ra, "logs", "create_result.json") or {}, load(rb, "logs", "create_result.json") or {}
    for k in ("devices", "server_parameters", "io_mappings", "build", "checks", "operation_status"):
        add("create_result." + k, strip(c1.get(k)), strip(c2.get(k)))
    v1, v2 = load(ra, "logs", "verify_result.json") or {}, load(rb, "logs", "verify_result.json") or {}
    for k in ("device_tree", "server_parameters", "io_mappings", "plc_prg_decl", "plc_prg_impl",
              "missing_variables", "rebuild", "checks", "operation_status"):
        add("verify_result." + k, strip(v1.get(k)), strip(v2.get(k)))
    for f in ("deployment_result.json", "modbus_probe.json"):
        a, b = load(ra, "logs", f), load(rb, "logs", f)
        add(f + " status", (a or {}).get("operation_status"), (b or {}).get("operation_status"))
    pa, pb = load(ra, "logs", "modbus_probe.json") or {}, load(rb, "logs", "modbus_probe.json") or {}
    add("modbus_probe.checks", pa.get("checks"), pb.get("checks"))

    h1 = load(ra, "evidence", "harness_%s.json" % ra)
    h2 = load(rb, "evidence", "harness_%s.json" % rb)
    vec1 = [(s["step"], s["operation_status"], s.get("process_exit_code")) for s in h1["steps"]]
    vec2 = [(s["step"], s["operation_status"], s.get("process_exit_code")) for s in h2["steps"]]
    add("step status vector (step, operation_status, process_exit_code)", vec1, vec2)

    for f in ("AI_BMS_AHU_DEMO.project", "AI_BMS_AHU_DEMO.app"):
        a, b = load(ra, "generated", f), load(rb, "generated", f)
        items.append({"item": f + " (byte hash, informational)", "kind": "hash", "equal": sha(a) == sha(b),
                      ra: {"sha256": sha(a), "size": len(a) if a else None},
                      rb: {"sha256": sha(b), "size": len(b) if b else None}})

    semantic = [i for i in items if i["kind"] == "semantic"]
    verdict = "DETERMINISTIC" if all(i["equal"] for i in semantic) else "NON-DETERMINISTIC"
    byte = "IDENTICAL" if all(i["equal"] for i in items if i["kind"] == "hash") else "DIFFERENT"
    result = {"test": "S1-FIX determinism %s vs %s" % (ra, rb), "semantic_verdict": verdict,
              "binary_bytes": byte, "binary_note": "byte equality of .project/.app not required",
              "differences": [i["item"] for i in semantic if not i["equal"]], "items": items}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({"semantic_verdict": verdict, "binary_bytes": byte, "differences": result["differences"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
