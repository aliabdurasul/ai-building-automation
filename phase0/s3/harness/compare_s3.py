"""S3 run-vs-run semantic comparison (measurement only).

Every string is normalised by replacing the run stage root with <STAGE>; timestamps and durations
are dropped. Binary files (.project/.app) are hashed for information; byte equality is not required.
Usage: python compare_s3.py [runA runB]   (default run1 run2)
Output: docs/phase0/S3_comparison_<a>_<b>.json
"""
import hashlib
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
STAGE = r"C:\AI_BMS_PHASE0\s3\{run}"
PROFILES = ("types", "ahu")
DROP = ("timestamp", "duration_seconds", "time", "t", "size", "elapsed_s")
CASE_KEYS = ("phase", "tag", "path", "datatype", "intended", "plc_raw", "plc_value", "modbus_raw",
             "decoded", "function", "written_raw", "write_accepted", "modbus_readback",
             "overlay_register_raw", "checks", "pass")


def load(run, *parts):
    p = os.path.join(STAGE.format(run=run), *parts)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8-sig")) if p.endswith(".json") else raw


def sha(b):
    return hashlib.sha256(b).hexdigest() if b is not None else None


def norm(obj, run):
    root = STAGE.format(run=run)
    if isinstance(obj, dict):
        return {k: norm(v, run) for k, v in obj.items() if k not in DROP}
    if isinstance(obj, list):
        return [norm(v, run) for v in obj]
    if isinstance(obj, str):
        return obj.replace(root, "<STAGE>").replace(root.replace("\\", "/"), "<STAGE>")
    return obj


def main():
    ra, rb = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("run1", "run2")
    out_path = os.path.join(REPO, "docs", "phase0", "S3_comparison_%s_%s.json" % (ra, rb))
    items = []

    def add(label, a, b, kind="semantic"):
        items.append({"item": label, "kind": kind, "equal": a == b, ra: a, rb: b})

    def pair(*parts):
        return norm(load(ra, *parts), ra), norm(load(rb, *parts), rb)

    st = pair("logs", "engine_selftest.json")
    add("engine self-test (tests, operation_status)",
        {k: (st[0] or {}).get(k) for k in ("tests_run", "tests", "failures", "errors", "operation_status")},
        {k: (st[1] or {}).get(k) for k in ("tests_run", "tests", "failures", "errors", "operation_status")})

    for p in PROFILES:
        g = pair(p, "logs", "generate_result.json")
        for k in ("model_sha256", "allocation", "operation_status"):
            add("%s/generate.%s" % (p, k), (g[0] or {}).get(k), (g[1] or {}).get(k))
        for f in ("PLC_PRG_decl.st", "PLC_PRG_impl.st", "PLC_PRG.st"):
            add("%s/generated ST %s (sha256)" % (p, f), sha(load(ra, p, "generated", f)),
                sha(load(rb, p, "generated", f)))
        add("%s/allocation.json" % p, *pair(p, "engineering", "allocation.json"))
        add("%s/codesys_plan.json" % p, *pair(p, "engineering", "codesys_plan.json"))
        add("%s/modbus_mapping.json (incl. verified flags + measured orders)" % p,
            *pair(p, "engineering", "modbus_mapping.json"))

        c = pair(p, "logs", "create_result.json")
        for k in ("devices", "server_parameters", "channel_counts", "io_mappings", "build", "checks",
                  "operation_status"):
            add("%s/create_result.%s" % (p, k), (c[0] or {}).get(k), (c[1] or {}).get(k))
        v = pair(p, "logs", "verify_result.json")
        for k in ("device_tree", "server_parameters", "channel_counts", "io_mappings", "plc_prg_decl",
                  "plc_prg_impl", "missing_variables", "rebuild", "checks", "operation_status"):
            add("%s/verify_result.%s" % (p, k), (v[0] or {}).get(k), (v[1] or {}).get(k))
        d = pair(p, "logs", "deployment_result.json")
        for k in ("simulation_mode", "logged_in", "application_state", "runtime_boot_application",
                  "operation_status"):
            add("%s/deployment.%s" % (p, k), (d[0] or {}).get(k), (d[1] or {}).get(k))
        r = pair(p, "logs", "s1_regression.json")
        for k in ("hr", "ir", "checks", "start_ir_last", "stop_ir_last", "operation_status"):
            add("%s/s1_regression.%s" % (p, k), (r[0] or {}).get(k), (r[1] or {}).get(k))

        t = pair(p, "logs", "typed_verify.json")
        ta, tb = t[0] or {}, t[1] or {}
        add("%s/typed_verify.cases" % p,
            [{k: c.get(k) for k in CASE_KEYS} for c in ta.get("cases", [])],
            [{k: c.get(k) for k in CASE_KEYS} for c in tb.get("cases", [])])
        for k in ("real32_samples", "real32_candidates_after_reads", "real32_ordering", "behavior",
                  "checks", "per_signal", "tolerance", "operation_status"):
            add("%s/typed_verify.%s" % (p, k), ta.get(k), tb.get(k))

        for ext in (".project", ".app"):
            f = "AI_BMS_S3_%s%s" % (p, ext)
            a, b = load(ra, p, "generated", f), load(rb, p, "generated", f)
            items.append({"item": "%s/%s (byte hash, informational)" % (p, f), "kind": "hash",
                          "equal": sha(a) == sha(b),
                          ra: {"sha256": sha(a), "size": len(a) if a else None},
                          rb: {"sha256": sha(b), "size": len(b) if b else None}})

    h1 = load(ra, "evidence", "harness_%s.json" % ra) or {"steps": []}
    h2 = load(rb, "evidence", "harness_%s.json" % rb) or {"steps": []}
    vec1 = [[s["step"], s["operation_status"], s.get("process_exit_code")] for s in h1["steps"]]
    vec2 = [[s["step"], s["operation_status"], s.get("process_exit_code")] for s in h2["steps"]]
    add("step status vector (step, operation_status, process_exit_code)", vec1, vec2)

    semantic = [i for i in items if i["kind"] == "semantic"]
    missing = [i["item"] for i in semantic if i[ra] is None and i[rb] is None]
    verdict = "DETERMINISTIC" if all(i["equal"] for i in semantic) and not missing else "NON-DETERMINISTIC"
    byte = "IDENTICAL" if all(i["equal"] for i in items if i["kind"] == "hash") else "DIFFERENT"
    result = {"test": "S3 determinism %s vs %s" % (ra, rb), "semantic_verdict": verdict,
              "binary_bytes": byte, "binary_note": "byte equality of .project/.app not required",
              "differences": [i["item"] for i in semantic if not i["equal"]],
              "missing_in_both": missing, "items": items}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({"semantic_verdict": verdict, "binary_bytes": byte,
                      "differences": result["differences"], "missing_in_both": missing}, indent=2))
    return 0 if verdict == "DETERMINISTIC" else 1


if __name__ == "__main__":
    sys.exit(main())
