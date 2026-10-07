"""S2 run-vs-run semantic comparison (measurement only).

Every string is normalised by replacing the run stage root with <STAGE>; timestamps, durations and poll counters
are dropped. Compared: every immutable revision store (PUMP-DEMO, BMS-DEMO, AHU-DEMO: every artifact of every
accepted revision, rejected attempts, index), every run-level result, every deploy chain (CODESYS project/build,
deploy, runtime, S1 regression where AHU-01 is present, template behaviour / isolation scenario, typed verification,
verified mapping) and the step status vector. .project/.app bytes are hashed for information only.
Usage: python compare_s2.py [runA runB]   (default run1 run2)
Output: docs/phase0/S2_comparison_<a>_<b>.json
Other phases reuse this module through configure() (stage root, stores, extra volatile keys, report name).
"""
import hashlib
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
NAME = "S2"
STAGE = r"C:\AI_BMS_PHASE0\s2\{run}"
STORES = ("pump", "combined", "ahu")
DROP = ("timestamp", "duration_seconds", "time", "t", "size", "elapsed_s", "poll_attempts", "plc_poll_attempts")


def configure(name, stage, stores, extra_drop=()):
    global NAME, STAGE, STORES, DROP
    NAME, STAGE, STORES, DROP = name, stage, tuple(stores), DROP + tuple(extra_drop)
CASE_KEYS = ("phase", "tag", "path", "datatype", "intended", "plc_raw", "plc_value", "modbus_raw",
             "decoded", "function", "written_raw", "write_accepted", "modbus_readback",
             "overlay_register_raw", "checks", "pass")


def root(run):
    return STAGE.format(run=run)


def load(run, *parts):
    p = os.path.join(root(run), *parts)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8-sig")) if p.endswith(".json") else raw


def files_under(run, *parts):
    base = os.path.join(root(run), *parts)
    out = []
    for d, _, fs in os.walk(base):
        for f in fs:
            out.append(os.path.relpath(os.path.join(d, f), base).replace("\\", "/"))
    return sorted(out)


def sha(b):
    return hashlib.sha256(b).hexdigest() if b is not None else None


def norm(obj, run):
    r = root(run)
    if isinstance(obj, dict):
        return {k: norm(v, run) for k, v in obj.items() if k not in DROP}
    if isinstance(obj, list):
        return [norm(v, run) for v in obj]
    if isinstance(obj, str):
        return obj.replace(r, "<STAGE>").replace(r.replace("\\", "/"), "<STAGE>")
    return obj


def main():
    ra, rb = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("run1", "run2")
    out_path = os.path.join(REPO, "docs", "phase0", "%s_comparison_%s_%s.json" % (NAME, ra, rb))
    items = []

    def add(label, a, b, kind="semantic"):
        items.append({"item": label, "kind": kind, "equal": a == b, ra: a, rb: b})

    def pair(*parts):
        return norm(load(ra, *parts), ra), norm(load(rb, *parts), rb)

    def content(run, *parts):
        v = load(run, *parts)
        return norm(v, run) if isinstance(v, (dict, list)) else sha(v)

    for store in STORES:
        for sub in ("engineering", "generated"):
            parts = (sub, store, "revisions")
            fa, fb = files_under(ra, *parts), files_under(rb, *parts)
            add("%s/%s/revisions file list" % (sub, store), fa, fb)
            for f in sorted(set(fa) | set(fb)):
                add("%s/%s/revisions/%s" % (sub, store, f), content(ra, *parts, *f.split("/")),
                    content(rb, *parts, *f.split("/")))

    la, lb = files_under(ra, "logs"), files_under(rb, "logs")
    add("logs file list", la, lb)
    for f in sorted(set(la) | set(lb)):
        add("logs/%s" % f, *pair("logs", f))

    da, db = sorted(os.listdir(os.path.join(root(ra), "deploy"))), sorted(os.listdir(os.path.join(root(rb), "deploy")))
    add("deploy chains", da, db)
    for lab in sorted(set(da) | set(db)):
        for f in ("model.json", "target.json", "allocation.json", "codesys_plan.json", "revision_diff.json",
                  "validation.json", "logic_templates.json", "logic_instances.json"):
            add("%s/engineering/%s" % (lab, f), *pair("deploy", lab, "engineering", f))
        add("%s/engineering/modbus_mapping.json (incl. verified flags + measured order)" % lab,
            *pair("deploy", lab, "engineering", "modbus_mapping.json"))
        for f in ("PLC_PRG_decl.st", "PLC_PRG_impl.st", "PLC_PRG.st", "PLC_VARIABLES.txt"):
            add("%s/generated/%s (sha256)" % (lab, f), sha(load(ra, "deploy", lab, "generated", f)),
                sha(load(rb, "deploy", lab, "generated", f)))
        ran = [os.path.isdir(os.path.join(root(r), "deploy", lab, "logs")) for r in (ra, rb)]
        add("%s deploy chain executed (staged-only revisions have none)" % lab, ran[0], ran[1])
        if not any(ran):
            continue
        c = pair("deploy", lab, "logs", "create_result.json")
        for k in ("devices", "server_parameters", "channel_counts", "io_mappings", "build", "checks", "operation_status"):
            add("%s/create_result.%s" % (lab, k), (c[0] or {}).get(k), (c[1] or {}).get(k))
        v = pair("deploy", lab, "logs", "verify_result.json")
        for k in ("device_tree", "server_parameters", "channel_counts", "io_mappings", "plc_prg_decl",
                  "plc_prg_impl", "missing_variables", "rebuild", "checks", "operation_status"):
            add("%s/verify_result.%s" % (lab, k), (v[0] or {}).get(k), (v[1] or {}).get(k))
        d = pair("deploy", lab, "logs", "deployment_result.json")
        for k in ("simulation_mode", "logged_in", "application_state", "runtime_boot_application", "operation_status"):
            add("%s/deployment.%s" % (lab, k), (d[0] or {}).get(k), (d[1] or {}).get(k))
        add("%s/deployment.online_variables" % lab, sorted(((d[0] or {}).get("online_values") or {})),
            sorted(((d[1] or {}).get("online_values") or {})))
        r = pair("deploy", lab, "logs", "s1_regression.json")
        if r[0] is not None or r[1] is not None:
            for k in ("hr", "ir", "checks", "bits_after_start", "bits_after_stop", "di_after_start", "di_after_stop",
                      "operation_status"):
                add("%s/s1_regression.%s" % (lab, k), (r[0] or {}).get(k), (r[1] or {}).get(k))
        bh = pair("deploy", lab, "logs", "behavior.json")
        if bh[0] is not None or bh[1] is not None:
            for k in ("tests", "checks", "operation_status", "reason"):
                add("%s/behavior.%s" % (lab, k), (bh[0] or {}).get(k), (bh[1] or {}).get(k))
        t = pair("deploy", lab, "logs", "typed_verify.json")
        ta, tb = t[0] or {}, t[1] or {}
        add("%s/typed_verify.cases" % lab,
            [{k: x.get(k) for k in CASE_KEYS} for x in ta.get("cases", [])],
            [{k: x.get(k) for k in CASE_KEYS} for x in tb.get("cases", [])])
        for k in ("real32_samples", "real32_candidates_after_reads", "real32_ordering", "reference_ordering",
                  "behavior", "checks", "per_signal", "tolerance", "operation_status"):
            add("%s/typed_verify.%s" % (lab, k), ta.get(k), tb.get(k))
        for f in ("bridge_result_bridge.json", "bridge_result_bridge_behavior.json"):
            ba, bb = pair("deploy", lab, "logs", f)
            if ba is not None or bb is not None:
                add("%s/%s.operation_status" % (lab, f), (ba or {}).get("operation_status"), (bb or {}).get("operation_status"))
        gdir = os.path.join(root(ra), "deploy", lab, "generated")
        bins_a = [f for f in os.listdir(gdir) if f.endswith((".project", ".app"))] if os.path.isdir(gdir) else []
        gdir_b = os.path.join(root(rb), "deploy", lab, "generated")
        add("%s binary artifacts present (.project/.app)" % lab, sorted(bins_a),
            sorted(f for f in os.listdir(gdir_b) if f.endswith((".project", ".app"))) if os.path.isdir(gdir_b) else [])
        for f in sorted(bins_a):
            a = load(ra, "deploy", lab, "generated", f)
            b = load(rb, "deploy", lab, "generated", f)
            items.append({"item": "%s/%s (byte hash, informational)" % (lab, f), "kind": "hash",
                          "equal": sha(a) == sha(b),
                          ra: {"sha256": sha(a), "size": len(a) if a else None},
                          rb: {"sha256": sha(b), "size": len(b) if b else None}})

    h1 = load(ra, "evidence", "harness_%s.json" % ra) or {"steps": []}
    h2 = load(rb, "evidence", "harness_%s.json" % rb) or {"steps": []}
    vec1 = [[s["step"], s["operation_status"], s.get("process_exit_code")] for s in h1["steps"]]
    vec2 = [[s["step"], s["operation_status"], s.get("process_exit_code")] for s in h2["steps"]]
    add("step status vector (step, operation_status, process_exit_code)", vec1, vec2)

    semantic = [i for i in items if i["kind"] == "semantic"]
    optional = ("revision_diff.json", "logic_templates.json", "logic_instances.json")
    missing = [i["item"] for i in semantic if i[ra] is None and i[rb] is None and not i["item"].endswith(optional)]
    verdict = "DETERMINISTIC" if all(i["equal"] for i in semantic) and not missing else "NON-DETERMINISTIC"
    byte = "IDENTICAL" if all(i["equal"] for i in items if i["kind"] == "hash") else "DIFFERENT"
    result = {"test": "%s determinism %s vs %s" % (NAME, ra, rb), "semantic_verdict": verdict,
              "binary_bytes": byte, "binary_note": "byte equality of .project/.app not required",
              "semantic_items": len(semantic),
              "differences": [i["item"] for i in semantic if not i["equal"]],
              "missing_in_both": missing, "items": items}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({"semantic_verdict": verdict, "binary_bytes": byte, "semantic_items": len(semantic),
                      "differences": result["differences"], "missing_in_both": missing}, indent=2))
    return 0 if verdict == "DETERMINISTIC" else 1


if __name__ == "__main__":
    sys.exit(main())
