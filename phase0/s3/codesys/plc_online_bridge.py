# -*- coding: utf-8 -*-
"""S3: thin CODESYS online bridge for PLC-side read-back / test-value injection (IronPython 2.7).

Logs in to the application that F05 already downloaded (same generated project, no new
download expected), then serves file-based requests from the CPython verifier:
  <bridge>/cmd_NNNN.json  {"op": "read", "exprs": [...]}
                          {"op": "write", "values": {"PLC_PRG.X": "literal", ...}}
                          {"op": "quit"}
  <bridge>/res_NNNN.json  {"ok": bool, "values": {...} | "error": "..."}
No test logic and no decoding here. Credentials only from the environment, never written.
Exit: 0 served and quit cleanly, 20 login/online failure, 1 exception.

Env: S1FIX_STAGE, S3_BRIDGE_DIR, S1FIX_TARGET_IP (default 127.0.0.1), S3_BRIDGE_IDLE_S (default 300)
"""
from __future__ import print_function
import os
import json
import time
import traceback

STAGE = os.environ["S1FIX_STAGE"]
BRIDGE = os.environ["S3_BRIDGE_DIR"]
TARGET_IP = os.environ.get("S1FIX_TARGET_IP", "127.0.0.1")
IDLE_S = int(os.environ.get("S3_BRIDGE_IDLE_S", "300"))
PLAN = json.load(open(os.path.join(STAGE, "engineering", "codesys_plan.json")))
PROJECT = os.path.join(STAGE, "generated", PLAN["project_file"])
RESULT = os.path.join(STAGE, "logs", "bridge_result.json")

res = {"step": "plc_online_bridge", "project": PROJECT, "requests": 0}
PW = [None]


def scrub(text):
    text = str(text)
    if PW[0]:
        text = text.replace(PW[0], "***")
    return text[:400]


def write_json(path, obj):
    tmp = path + ".tmp"
    f = open(tmp, "w")
    f.write(json.dumps(obj))
    f.close()
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def credentials():
    for u, p in (("CODESYS_USER", "CODESYS_PASSWORD"), ("CODESYS_DEMO_USER", "CODESYS_DEMO_PASS")):
        if os.environ.get(u) and os.environ.get(p):
            return os.environ[u], os.environ[p]
    return None, None


def serve(oapp):
    done = set()
    last = time.time()
    while time.time() - last < IDLE_S:
        cmds = sorted(n for n in os.listdir(BRIDGE) if n.startswith("cmd_") and n.endswith(".json") and n not in done)
        if not cmds:
            time.sleep(0.05)
            continue
        for name in cmds:
            done.add(name)
            last = time.time()
            req = json.load(open(os.path.join(BRIDGE, name)))
            out = {"ok": True}
            try:
                if req["op"] == "read":
                    vals = oapp.read_values(req["exprs"])
                    out["values"] = dict((e, str(v)) for e, v in zip(req["exprs"], vals))
                elif req["op"] == "write":
                    for expr, lit in sorted(req["values"].items()):
                        oapp.set_prepared_value(expr, lit)
                    oapp.write_prepared_values()
                elif req["op"] == "quit":
                    write_json(os.path.join(BRIDGE, name.replace("cmd_", "res_")), out)
                    return True
                else:
                    out = {"ok": False, "error": "unknown op " + str(req["op"])}
            except Exception as ex:
                out = {"ok": False, "error": scrub(ex)}
            res["requests"] += 1
            write_json(os.path.join(BRIDGE, name.replace("cmd_", "res_")), out)
    return False


def main():
    user, pw = credentials()
    PW[0] = pw
    if user is None:
        res.update(operation_status="BLOCKED", reason="no CODESYS credentials in environment")
        write_json(os.path.join(BRIDGE, "ready.json"), {"ready": False, "reason": res["reason"]})
        return 3
    try:
        if projects.primary is not None:
            projects.primary.close()
    except Exception:
        pass
    proj = projects.open(PROJECT, update_flags=VersionUpdateFlags.NoUpdates)
    dev = proj.find("Device", True)[0]
    app = proj.find("Application", True)[0]
    proj.active_application = app
    dev.set_simulation_mode(False)
    gw = list(online.gateways)[0]
    dev.set_gateway_and_ip_address(str(gw.name), TARGET_IP)
    online.set_default_credentials(user, pw)
    oapp = online.create_online_application(app)
    try:
        oapp.login(OnlineChangeOption.Never, False)
    except Exception as ex:
        res.update(operation_status="FAILED", reason="login failed: " + scrub(ex))
        write_json(os.path.join(BRIDGE, "ready.json"), {"ready": False, "reason": res["reason"]})
        return 20
    state = str(oapp.application_state)
    res["application_state_at_login"] = state
    if state.lower() != "run":
        oapp.start()
        res["started_by_bridge"] = True
    res["application_state"] = str(oapp.application_state)
    write_json(os.path.join(BRIDGE, "ready.json"), {"ready": True, "logged_in": bool(oapp.is_logged_in),
                                                    "application_state": res["application_state"],
                                                    "application_state_at_login": state})
    quit_ok = serve(oapp)
    res["quit_received"] = quit_ok
    oapp.logout()
    proj.close()
    res.update(operation_status="PASS" if quit_ok else "FAILED",
               reason="served %d requests" % res["requests"] if quit_ok else "idle timeout without quit")
    return 0 if quit_ok else 20


code = 1
try:
    code = main()
except Exception:
    res.update(operation_status="FAILED", reason="exception", exception=scrub(traceback.format_exc()))
    try:
        write_json(os.path.join(BRIDGE, "ready.json"), {"ready": False, "reason": res["exception"]})
    except Exception:
        pass
res["exit_code_intended"] = code
write_json(RESULT, res)
print("OPERATION_STATUS=%s" % res.get("operation_status"))
system.exit(code)
