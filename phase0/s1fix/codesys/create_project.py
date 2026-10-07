# -*- coding: utf-8 -*-
"""S1-FIX: create the CODESYS project from generator output (IronPython 2.7 / ScriptEngine).

Device tree: Device -> Application/PLC_PRG/MainTask, Device -> Ethernet -> Modbus_TCP_Server.
Device descriptors are resolved from device_repository by (type, id) given in codesys_plan.json;
no MCP, no patched handlers. Exit: 0 PASS, 20 FAILED, 1 exception.

Env: S1FIX_STAGE  staging root (contains generated/, engineering/, logs/)
"""
from __future__ import print_function
import os
import json
import traceback

STAGE = os.environ["S1FIX_STAGE"]
GEN = os.path.join(STAGE, "generated")
ENG = os.path.join(STAGE, "engineering")
LOGS = os.path.join(STAGE, "logs")
PLAN = json.load(open(os.path.join(ENG, "codesys_plan.json")))
PROJECT = os.path.join(GEN, PLAN["project_file"])
BOOT_APP = os.path.join(GEN, PLAN["boot_app_file"])
RESULT = os.path.join(LOGS, "create_result.json")
BUILD_LOG = os.path.join(LOGS, "build.log")

res = {"step": "codesys_create_build", "project": PROJECT, "checks": {}, "devices": [], "io_mappings": []}


def log(msg):
    print(msg)


def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def ver_key(v):
    out = []
    for p in str(v).split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def resolve_repo(type_, id_, expect_name):
    matches = []
    for d in device_repository.get_all_devices():
        did = safe(d, "device_id")
        if did is None:
            continue
        if int(safe(did, "type", -1)) == int(type_) and str(safe(did, "id", "")) == str(id_):
            matches.append(d)
    if not matches:
        raise RuntimeError("repo has no device type=%s id=%s" % (type_, id_))
    best = sorted(matches, key=lambda d: ver_key(d.device_id.version))[-1]
    name = str(safe(best.device_info, "name", ""))
    if name != expect_name:
        raise RuntimeError("repo device type=%s id=%s is %r, expected %r" % (type_, id_, name, expect_name))
    return best


def find_one(proj, name):
    found = proj.find(name, True)
    return found[0] if found else None


def host_param(dev, name):
    for cn in list(dev.connectors):
        for p in list(cn.host_parameters):
            if str(safe(p, "name", "")) == name:
                return p
    return None


def child_at(param, index):
    subs = list(param)
    if index < 0 or index >= len(subs):
        return None
    return subs[index]


def write_build_log():
    errors, warnings, lines = 0, 0, []
    for m in system.get_message_objects():
        sev = str(safe(m, "severity", ""))
        text = str(safe(m, "text", ""))
        lines.append("%s: %s" % (sev, text))
        if m.severity == Severity.Error or m.severity == Severity.FatalError:
            errors += 1
        elif m.severity == Severity.Warning:
            warnings += 1
    f = open(BUILD_LOG, "w")
    f.write("\n".join(lines) + "\n")
    f.write("errors=%d warnings=%d\n" % (errors, warnings))
    f.close()
    return errors, warnings


def main():
    decl = open(os.path.join(GEN, "PLC_PRG_decl.st")).read()
    impl = open(os.path.join(GEN, "PLC_PRG_impl.st")).read()
    if os.path.exists(PROJECT):
        raise RuntimeError("refusing to overwrite existing project " + PROJECT)
    try:
        if projects.primary is not None:
            projects.primary.close()
    except Exception:
        pass

    proj = projects.create(PROJECT, True)
    plc = list(device_repository.get_all_devices(PLAN["plc_device_repo_name"]) or [])
    if not plc:
        raise RuntimeError("PLC device not in repo: " + PLAN["plc_device_repo_name"])
    proj.add("Device", plc[0].device_id)
    res["devices"].append({"name": "Device", "repo_name": PLAN["plc_device_repo_name"],
                           "type": int(plc[0].device_id.type), "id": str(plc[0].device_id.id),
                           "version": str(plc[0].device_id.version)})

    app = find_one(proj, "Application")
    proj.active_application = app
    tcs = proj.find("TaskConfiguration", True)
    tc = tcs[0] if tcs else app.create_task_configuration()
    task = tc.create_task("MainTask")
    pou = app.create_pou(name="PLC_PRG", type=PouType.Program)
    pou.textual_declaration.replace(decl)
    pou.textual_implementation.replace(impl)
    task.pous.add("PLC_PRG")

    for spec in PLAN["devices"]:
        parent = find_one(proj, spec["parent"])
        if parent is None:
            raise RuntimeError("parent node not found: " + spec["parent"])
        repo = resolve_repo(spec["type"], spec["id"], spec["repo_name"])
        did = repo.device_id
        parent.add(spec["name"], int(did.type), str(did.id), str(did.version))
        node = find_one(proj, spec["name"])
        got = node.get_device_identification() if node is not None else None
        entry = {"name": spec["name"], "parent": spec["parent"], "repo_name": spec["repo_name"],
                 "type": int(did.type), "id": str(did.id), "version": str(did.version),
                 "present_after_add": node is not None,
                 "identification_matches": got is not None and int(got.type) == int(did.type) and str(got.id) == str(did.id)}
        res["devices"].append(entry)
        log("ADDED %s under %s (%s %s %s)" % (spec["name"], spec["parent"], did.type, did.id, did.version))

    server_name = PLAN["devices"][-1]["name"]
    server = find_one(proj, server_name)
    expect = {}
    for pname, pval in PLAN["server_expect"].items():
        p = host_param(server, pname)
        actual = str(p.value).strip() if p is not None else None
        expect[pname] = {"expected": str(pval), "actual": actual, "ok": actual == str(pval)}
    res["server_parameters"] = expect

    counts = {}
    for pname, n in PLAN.get("channel_counts", {}).items():
        p = host_param(server, pname)
        actual = len(list(p)) if p is not None else None
        counts[pname] = {"expected": n, "actual": actual, "ok": actual == n}
    res["channel_counts"] = counts

    for m in PLAN["io_mappings"]:
        dev = find_one(proj, m["device"])
        param = host_param(dev, m["parameter"])
        entry = dict(m)
        word = child_at(param, m["word_index"]) if param is not None else None
        if word is not None and "bit_index" in m:
            word = child_at(word, m["bit_index"])
        if word is None:
            entry.update(ok=False, error="channel not found")
        elif not bool(safe(word, "is_mappable_io", False)):
            entry.update(ok=False, error="channel not mappable", channel_iec_type=str(safe(word, "iec_type", "")))
        else:
            word.io_mapping.variable = m["variable"]
            after = str(safe(word.io_mapping, "variable", "") or "")
            entry.update(ok=after == m["variable"], read_back=after,
                         channel_identifier=str(safe(word, "identifier", "")),
                         channel_iec_type=str(safe(word, "iec_type", "")))
        res["io_mappings"].append(entry)
        log("MAP %s[%s]%s -> %s ok=%s" % (m["parameter"], m["word_index"],
                                          (".%s" % m["bit_index"]) if "bit_index" in m else "", m["variable"], entry.get("ok")))

    proj.save()
    app.build()
    errors, warnings = write_build_log()
    res["build"] = {"errors": errors, "warnings": warnings, "log": BUILD_LOG}
    log("BUILD errors=%d warnings=%d" % (errors, warnings))

    try:
        app.create_boot_application(BOOT_APP)
    except Exception as ex:
        res["boot_app_error"] = str(ex)
    proj.save()
    res["boot_app"] = {"path": BOOT_APP, "exists": os.path.exists(BOOT_APP),
                       "size": os.path.getsize(BOOT_APP) if os.path.exists(BOOT_APP) else -1}

    c = res["checks"]
    c["devices_added"] = all(d.get("present_after_add", True) and d.get("identification_matches", True) for d in res["devices"])
    c["server_parameters"] = all(v["ok"] for v in expect.values())
    if counts:
        c["channel_counts"] = all(v["ok"] for v in counts.values())
    c["io_mappings"] = len(res["io_mappings"]) > 0 and all(m.get("ok") for m in res["io_mappings"])
    c["build_0_errors"] = errors == 0
    c["build_0_warnings"] = warnings == 0
    c["boot_app"] = res["boot_app"]["exists"] and res["boot_app"]["size"] > 0
    failed = [k for k, v in c.items() if not v]
    res["operation_status"] = "PASS" if not failed else "FAILED"
    res["reason"] = "all checks passed" if not failed else "failed checks: " + ", ".join(failed)
    proj.close()


code = 1
try:
    main()
    code = 0 if res.get("operation_status") == "PASS" else 20
except Exception:
    res["operation_status"] = "FAILED"
    res["reason"] = "exception"
    res["exception"] = traceback.format_exc()
    log(res["exception"])
res["exit_code_intended"] = code
f = open(RESULT, "w")
f.write(json.dumps(res, indent=2))
f.close()
log("OPERATION_STATUS=%s" % res["operation_status"])
system.exit(code)
