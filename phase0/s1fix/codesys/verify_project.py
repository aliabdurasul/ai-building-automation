# -*- coding: utf-8 -*-
"""S1-FIX: fresh-process read-back of the generated CODESYS project (IronPython 2.7).

Checks: device tree (PLC, Ethernet, Modbus_TCP_Server with expected ids), server Port,
I/O mapping variables + IEC addresses, PLC_PRG text == generator output, required
variables declared, rebuild 0 errors / 0 warnings. Exit: 0 PASS, 20 FAILED, 1 exception.

Env: S1FIX_STAGE
"""
from __future__ import print_function
import os
import re
import json
import traceback

STAGE = os.environ["S1FIX_STAGE"]
GEN = os.path.join(STAGE, "generated")
ENG = os.path.join(STAGE, "engineering")
LOGS = os.path.join(STAGE, "logs")
PLAN = json.load(open(os.path.join(ENG, "codesys_plan.json")))
PROJECT = os.path.join(GEN, PLAN["project_file"])
RESULT = os.path.join(LOGS, "verify_result.json")
VERIFY_LOG = os.path.join(LOGS, "verify.log")

res = {"step": "codesys_verify", "project": PROJECT, "checks": {}}
lines = []


def log(msg):
    print(msg)
    lines.append(msg)


def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def norm(text):
    return "\n".join(l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))


def host_param(dev, name):
    for cn in list(dev.connectors):
        for p in list(cn.host_parameters):
            if str(safe(p, "name", "")) == name:
                return p
    return None


def tree(node, depth, out):
    name = node.get_name() if callable(safe(node, "get_name")) else "?"
    row = {"depth": depth, "name": str(name), "is_device": bool(safe(node, "is_device", False))}
    if row["is_device"]:
        did = node.get_device_identification()
        row.update(type=int(did.type), id=str(did.id), version=str(did.version))
    out.append(row)
    for ch in node.get_children(False):
        tree(ch, depth + 1, out)


def main():
    try:
        if projects.primary is not None:
            projects.primary.close()
    except Exception:
        pass
    proj = projects.open(PROJECT, update_flags=VersionUpdateFlags.NoUpdates)
    c = res["checks"]

    rows = []
    for top in proj.get_children(False):
        tree(top, 0, rows)
    res["device_tree"] = rows
    for r in rows:
        log("%s%s%s" % ("  " * r["depth"], r["name"],
                        (" [%s %s %s]" % (r["type"], r["id"], r["version"])) if r["is_device"] else ""))

    def node_row(name):
        for r in rows:
            if r["name"] == name and r["is_device"]:
                return r
        return None

    dev_ok = node_row("Device") is not None
    for spec in PLAN["devices"]:
        r = node_row(spec["name"])
        parent_ok = False
        if r is not None:
            idx = rows.index(r)
            for prev in reversed(rows[:idx]):
                if prev["depth"] == r["depth"] - 1:
                    parent_ok = prev["name"] == spec["parent"]
                    break
        ok = r is not None and r["type"] == spec["type"] and r["id"] == spec["id"] and parent_ok
        log("CHECK device %s under %s: %s" % (spec["name"], spec["parent"], ok))
        dev_ok = dev_ok and ok
    c["device_tree"] = dev_ok

    server = proj.find(PLAN["devices"][-1]["name"], True)[0]
    params = {}
    for pname, pval in PLAN["server_expect"].items():
        p = host_param(server, pname)
        actual = str(p.value).strip() if p is not None else None
        params[pname] = {"expected": str(pval), "actual": actual, "ok": actual == str(pval)}
        log("CHECK server %s expected=%s actual=%s" % (pname, pval, actual))
    res["server_parameters"] = params
    c["server_parameters"] = all(v["ok"] for v in params.values())

    counts = {}
    for pname, n in PLAN.get("channel_counts", {}).items():
        p = host_param(server, pname)
        actual = len(list(p)) if p is not None else None
        counts[pname] = {"expected": n, "actual": actual, "ok": actual == n}
        log("CHECK channels %s expected=%s actual=%s" % (pname, n, actual))
    if counts:
        res["channel_counts"] = counts
        c["channel_counts"] = all(v["ok"] for v in counts.values())

    maps = []
    for m in PLAN["io_mappings"]:
        dev = proj.find(m["device"], True)[0]
        param = host_param(dev, m["parameter"])
        word = list(param)[m["word_index"]]
        if "bit_index" in m:
            word = list(word)[m["bit_index"]]
        iom = word.io_mapping
        var = str(safe(iom, "variable", "") or "")
        entry = {"parameter": m["parameter"], "word_index": m["word_index"], "bit_index": m.get("bit_index"),
                 "expected": m["variable"],
                 "actual": var, "ok": var == m["variable"],
                 "iec_address_is_automatic": str(safe(iom, "automatic_iec_address", "")),
                 "channel_identifier": str(safe(word, "identifier", ""))}
        maps.append(entry)
        log("CHECK map %s[%d]%s (%s) -> %s: %s" % (m["parameter"], m["word_index"],
                                                  (".%d" % m["bit_index"]) if "bit_index" in m else "",
                                                  entry["channel_identifier"],
                                                var, entry["ok"]))
    res["io_mappings"] = maps
    c["io_mappings"] = all(m["ok"] for m in maps)

    pous = [o for o in proj.find("PLC_PRG", True) if safe(o, "textual_declaration") is not None]
    if len(pous) != 1:
        raise RuntimeError("expected exactly one PLC_PRG POU, found %d" % len(pous))
    pou = pous[0]
    decl = pou.textual_declaration.text
    impl = pou.textual_implementation.text
    gen_decl = open(os.path.join(GEN, "PLC_PRG_decl.st")).read()
    gen_impl = open(os.path.join(GEN, "PLC_PRG_impl.st")).read()
    c["plc_prg_matches_generator"] = norm(decl) == norm(gen_decl) and norm(impl) == norm(gen_impl)
    missing = [v for v in PLAN["required_variables"] if not re.search(r"^\s*%s\s*:" % re.escape(v), decl, re.M)]
    res["missing_variables"] = missing
    c["required_variables"] = not missing
    log("CHECK PLC_PRG == generator: %s; missing vars: %s" % (c["plc_prg_matches_generator"], missing))
    res["plc_prg_decl"] = norm(decl)
    res["plc_prg_impl"] = norm(impl)

    app = proj.find("Application", True)[0]
    proj.active_application = app
    app.build()
    errors = warnings = 0
    for msg in system.get_message_objects():
        if msg.severity == Severity.Error or msg.severity == Severity.FatalError:
            errors += 1
        elif msg.severity == Severity.Warning:
            warnings += 1
    res["rebuild"] = {"errors": errors, "warnings": warnings}
    c["rebuild_0_errors"] = errors == 0
    c["rebuild_0_warnings"] = warnings == 0
    log("CHECK rebuild errors=%d warnings=%d" % (errors, warnings))

    failed = [k for k, v in c.items() if not v]
    res["operation_status"] = "PASS" if not failed else "FAILED"
    res["reason"] = "all checks passed" if not failed else "failed checks: " + ", ".join(failed)
    proj.close()


code = 1
try:
    main()
    code = 0 if res["operation_status"] == "PASS" else 20
except Exception:
    res["operation_status"] = "FAILED"
    res["reason"] = "exception"
    res["exception"] = traceback.format_exc()
    log(res["exception"])
res["exit_code_intended"] = code
log("OPERATION_STATUS=%s" % res["operation_status"])
open(RESULT, "w").write(json.dumps(res, indent=2))
open(VERIFY_LOG, "w").write("\n".join(lines) + "\n")
system.exit(code)
