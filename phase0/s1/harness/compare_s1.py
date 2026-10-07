"""S1 determinism measurement: compares RUN 1 vs RUN 2 artifacts.

Measurement only. Text artifacts are compared raw and after normalizing run-specific
noise (timestamps, run folder names, GUIDs, PIDs, ephemeral ports, durations).
Binary containers can only be compared byte-wise.
"""
import hashlib
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EV = os.path.join(REPO, "docs", "phase0", "evidence")
OUT = os.path.join(REPO, "docs", "phase0", "S1_comparison.json")
CDS = r"C:\AI_BMS_PHASE0\s1\{run}\codesys"
MS = r"C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s1\{run}"

NORMALIZERS = [
    ("run_folder", re.compile(r"\brun[12]\b"), "RUN"),
    ("iso_timestamp", re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?"), "<TS>"),
    ("ms_sourcetime", re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}:\d{2}:\d{2}\.\d+"), "<TS>"),
    ("guid", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<GUID>"),
    ("pid", re.compile(r"(\"?pids?\"?\s*[:=]\s*\"?)\d+"), r"\g<1><PID>"),
    ("ephemeral_port", re.compile(r"(TCP|UDP) 0\.0\.0\.0:\d+"), r"\1 0.0.0.0:<PORT>"),
    ("duration", re.compile(r"(dur(ation)?[_ ]?(ms|s|seconds)?\s*[:=]\s*)[\d.]+"), r"\g<1><DUR>"),
]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def normalize(text):
    for _, rx, rep in NORMALIZERS:
        text = rx.sub(rep, text)
    return text


def first_diff(a, b):
    al, bl = a.splitlines(), b.splitlines()
    for i in range(max(len(al), len(bl))):
        x = al[i] if i < len(al) else "<EOF>"
        y = bl[i] if i < len(bl) else "<EOF>"
        if x != y:
            return {"line": i + 1, "run1": x[:300], "run2": y[:300]}
    return None


def cmp_text(name, p1, p2, category):
    rec = {"artifact": name, "category": category, "kind": "text", "run1": p1, "run2": p2}
    if not (os.path.isfile(p1) and os.path.isfile(p2)):
        rec.update(result="MISSING", run1_exists=os.path.isfile(p1), run2_exists=os.path.isfile(p2))
        return rec
    t1, t2 = read_text(p1), read_text(p2)
    rec["raw_identical"] = t1 == t2
    n1, n2 = normalize(t1), normalize(t2)
    rec["normalized_identical"] = n1 == n2
    rec["normalized_sha256_run1"] = hashlib.sha256(n1.encode("utf-8")).hexdigest()
    rec["normalized_sha256_run2"] = hashlib.sha256(n2.encode("utf-8")).hexdigest()
    if not rec["normalized_identical"]:
        rec["first_normalized_diff"] = first_diff(n1, n2)
    rec["result"] = "IDENTICAL" if rec["raw_identical"] else ("IDENTICAL_AFTER_NORMALIZATION" if rec["normalized_identical"] else "DIFFERENT")
    return rec


def cmp_binary(name, p1, p2, category):
    rec = {"artifact": name, "category": category, "kind": "binary", "run1": p1, "run2": p2}
    if not (os.path.isfile(p1) and os.path.isfile(p2)):
        rec.update(result="MISSING", run1_exists=os.path.isfile(p1), run2_exists=os.path.isfile(p2))
        return rec
    rec.update(size_run1=os.path.getsize(p1), size_run2=os.path.getsize(p2),
               sha256_run1=sha(p1), sha256_run2=sha(p2))
    rec["result"] = "IDENTICAL" if rec["sha256_run1"] == rec["sha256_run2"] else "DIFFERENT"
    return rec


def cmp_tree(name, d1, d2, category):
    rec = {"artifact": name, "category": category, "kind": "tree", "run1": d1, "run2": d2}
    if not (os.path.isdir(d1) and os.path.isdir(d2)):
        rec.update(result="MISSING", run1_exists=os.path.isdir(d1), run2_exists=os.path.isdir(d2))
        return rec

    def listing(d):
        out = {}
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                out[os.path.relpath(p, d).replace("\\", "/")] = p
        return out

    l1, l2 = listing(d1), listing(d2)
    only1 = sorted(set(l1) - set(l2))
    only2 = sorted(set(l2) - set(l1))
    raw_diff, norm_diff = [], []
    for rel in sorted(set(l1) & set(l2)):
        if sha(l1[rel]) == sha(l2[rel]):
            continue
        raw_diff.append(rel)
        try:
            if normalize(read_text(l1[rel])) != normalize(read_text(l2[rel])):
                norm_diff.append(rel)
        except Exception:
            norm_diff.append(rel)
    rec.update(files_run1=len(l1), files_run2=len(l2), only_in_run1=only1, only_in_run2=only2,
               raw_different=raw_diff, normalized_different=norm_diff)
    if only1 or only2 or norm_diff:
        rec["result"] = "DIFFERENT"
    elif raw_diff:
        rec["result"] = "IDENTICAL_AFTER_NORMALIZATION"
    else:
        rec["result"] = "IDENTICAL"
    return rec


def harness_steps(run):
    p = os.path.join(EV, run, "harness_%s.json" % run)
    data = json.loads(read_text(p))
    return {s["step"]: s for s in data["steps"]}


def main():
    c1, c2 = CDS.format(run="run1"), CDS.format(run="run2")
    m1, m2 = MS.format(run="run1"), MS.format(run="run2")
    e1, e2 = os.path.join(EV, "run1"), os.path.join(EV, "run2")
    items = []

    for f in ("PLC_PRG_decl.st", "PLC_PRG_impl.st", "PLC_PRG.st"):
        items.append(cmp_text("generated/" + f, os.path.join(c1, "generated", f), os.path.join(c2, "generated", f), "plc_source"))
    items.append(cmp_binary("CODESYS .project", os.path.join(c1, "AI_BMS_AHU_DEMO.project"), os.path.join(c2, "AI_BMS_AHU_DEMO.project"), "codesys_binary"))
    items.append(cmp_binary("CODESYS boot app .app", os.path.join(c1, "generated", "AI_BMS_AHU_DEMO.app"), os.path.join(c2, "generated", "AI_BMS_AHU_DEMO.app"), "codesys_binary"))
    for f in ("generate_result.txt", "verify_result.txt", "modbus_io_map.json", "runtime_result.txt", "modbus_v2_probe.json"):
        items.append(cmp_text("codesys logs/" + f, os.path.join(c1, "logs", f), os.path.join(c2, "logs", f), "codesys_readback"))

    for f in ("S04_codesys_verify.stdout.txt", "S09_ms_create.log", "S10_ms_modbus.log", "S11_ms_verify.log",
              "S12_hmi_build.log", "S13_hmi_verify.log", "S13_hmi_verify_evidence.json",
              "S15_ms_runtime.log", "S16_hmi_runtime.log"):
        cat = "codesys_readback" if f.startswith("S04") else ("hmi_readback" if f.startswith(("S12", "S13")) else
              ("runtime" if f.startswith(("S15", "S16")) else "masterscada_readback"))
        items.append(cmp_text("evidence/" + f, os.path.join(e1, f), os.path.join(e2, f), cat))

    items.append(cmp_binary("MasterSCADA AHU_S1.fdb", os.path.join(m1, "projects", "AHU_S1", "AHU_S1.fdb"), os.path.join(m2, "projects", "AHU_S1", "AHU_S1.fdb"), "masterscada_binary"))
    items.append(cmp_text("MasterSCADA info.xml", os.path.join(m1, "projects", "AHU_S1", "info.xml"), os.path.join(m2, "projects", "AHU_S1", "info.xml"), "masterscada_readback"))
    items.append(cmp_tree("HMI htdocs (HTML5 generated by debug runtime)",
                          os.path.join(m1, "rt_copy_hmi", "rt_work", "Debug_1", "htdocs"),
                          os.path.join(m2, "rt_copy_hmi", "rt_work", "Debug_1", "htdocs"), "hmi_generated"))

    h1, h2 = harness_steps("run1"), harness_steps("run2")
    exit_codes = []
    for step in sorted(set(h1) | set(h2)):
        a, b = h1.get(step, {}), h2.get(step, {})
        if "exit_code" in a or "exit_code" in b:
            exit_codes.append({"step": step, "run1": a.get("exit_code"), "run2": b.get("exit_code"),
                               "run1_timed_out": a.get("timed_out"), "run2_timed_out": b.get("timed_out"),
                               "run1_duration_s": a.get("duration_seconds"), "run2_duration_s": b.get("duration_seconds"),
                               "same": a.get("exit_code") == b.get("exit_code")})

    def verdict(cats):
        sel = [i for i in items if i["category"] in cats]
        if not sel or any(i["result"] == "MISSING" for i in sel):
            return "UNKNOWN"
        return "DETERMINISTIC" if all(i["result"] != "DIFFERENT" for i in sel) else "NON-DETERMINISTIC"

    per_cat = {c: verdict([c]) for c in sorted({i["category"] for i in items})}
    semantic_cats = ["plc_source", "codesys_readback", "masterscada_readback", "hmi_readback"]
    result = {
        "test": "S1 determinism RUN1 vs RUN2",
        "normalization_rules": [n for n, _, _ in NORMALIZERS],
        "binary_note": "Binary containers (.project, .app, .fdb) cannot be normalized; compared byte-wise only.",
        "verdict_per_category": per_cat,
        "verdict_semantic_readback": verdict(semantic_cats),
        "verdict_byte_level": verdict(["codesys_binary", "masterscada_binary"]),
        "verdict_exit_codes": "DETERMINISTIC" if all(e["same"] for e in exit_codes) else "NON-DETERMINISTIC",
        "exit_codes": exit_codes,
        "artifacts": items,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: result[k] for k in ("verdict_per_category", "verdict_semantic_readback", "verdict_byte_level", "verdict_exit_codes")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
