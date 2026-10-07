# -*- coding: utf-8 -*-
"""S8.1 anonymous-capable PLC online bridge (copy of S3 bridge credentials gate only).

SoftPLC has SECURITY.UserMgmtAllowAnonymous=YES. This wrapper allows empty password
so FAULT inject can run without CODESYS_PASSWORD in the agent env.
Does NOT modify phase0/s3. Credentials never logged.
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

res = {"step": "plc_online_bridge_s81", "project": PROJECT, "requests": 0}
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
    # Prefer real env credentials when present
    for u, p in (("CODESYS_USER", "CODESYS_PASSWORD"), ("CODESYS_DEMO_USER", "CODESYS_DEMO_PASS")):
        if os.environ.get(u) and os.environ.get(p) is not None and os.environ.get(p) != "":
            return [(os.environ[u], os.environ[p])]
    # SoftPLC has UserMgmtAllowAnonymous=YES — try anonymous variants
    candidates = []
    if os.environ.get("CODESYS_USER") is not None:
        candidates.append((os.environ.get("CODESYS_USER"), os.environ.get("CODESYS_PASSWORD") or ""))
    candidates.extend([
        ("", ""),
        ("Administrator", ""),
        ("Administrator", "Administrator"),
        ("Administrator", "admin"),
        ("Administrator", "codesys"),
        ("admin", "admin"),
        ("Device", ""),
        ("Anonymous", ""),
    ])
    return candidates


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
    candidates = credentials()
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
    oapp = None
    last_err = None
    for user, pw in candidates:
        PW[0] = pw
        try:
            online.set_default_credentials(user, pw)
            oapp = online.create_online_application(app)
            oapp.login(OnlineChangeOption.Never, False)
            res["auth_mode"] = "user_len=%d pass_len=%d" % (len(user or ""), len(pw or ""))
            break
        except Exception as ex:
            last_err = scrub(ex)
            oapp = None
            continue
    if oapp is None:
        res.update(operation_status="FAILED", reason="login failed: " + str(last_err))
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
                                                    "application_state_at_login": state,
                                                    "auth": res.get("auth_mode")})
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
