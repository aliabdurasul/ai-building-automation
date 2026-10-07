# -*- coding: utf-8 -*-
"""S1-FIX: agentless download + start of the generated application (IronPython 2.7).

Credentials come only from the environment (CODESYS_USER / CODESYS_PASSWORD, or the POC
convention CODESYS_DEMO_USER / CODESYS_DEMO_PASS) and are never written anywhere.
No runtime user is created. Exit: 0 PASS, 20 FAILED, 3 BLOCKED, 1 exception.

Env: S1FIX_STAGE, S1FIX_TARGET_IP (default 127.0.0.1)
"""
from __future__ import print_function
import os
import json
import traceback

STAGE = os.environ["S1FIX_STAGE"]
GEN = os.path.join(STAGE, "generated")
LOGS = os.path.join(STAGE, "logs")
PLAN = json.load(open(os.path.join(STAGE, "engineering", "codesys_plan.json")))
PROJECT = os.path.join(GEN, PLAN["project_file"])
RESULT = os.path.join(LOGS, "deployment_result.json")
DEPLOY_LOG = os.path.join(LOGS, "deployment.log")
TARGET_IP = os.environ.get("S1FIX_TARGET_IP", "127.0.0.1")

res = {"step": "deploy", "project": PROJECT, "target_ip": TARGET_IP}
lines = []


def log(msg):
    print(msg)
    lines.append(msg)


def credentials():
    for u, p in (("CODESYS_USER", "CODESYS_PASSWORD"), ("CODESYS_DEMO_USER", "CODESYS_DEMO_PASS")):
        if os.environ.get(u) and os.environ.get(p) is not None and os.environ.get(p) != "":
            return os.environ[u], os.environ[p], u + "/" + p
    return None, None, None


def main():
    user, pw, source = credentials()
    res["credentials_source"] = source
    res["credentials_present"] = user is not None
    if user is None:
        res["operation_status"] = "BLOCKED"
        res["reason"] = "no CODESYS credentials in environment (CODESYS_USER/CODESYS_PASSWORD)"
        log("BLOCKED: " + res["reason"])
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
    res["simulation_mode"] = bool(dev.get_simulation_mode())

    gateways = list(online.gateways)
    res["gateways"] = [str(g.name) for g in gateways]
    if not gateways:
        res["operation_status"] = "BLOCKED"
        res["reason"] = "no gateway configured in CODESYS"
        return 3
    gw = gateways[0]
    try:
        dev.set_gateway_and_ip_address(str(gw.name), TARGET_IP)
        res["gateway_used"] = str(gw.name)
    except Exception as ex:
        res["gateway_by_name_error"] = str(ex)[:200]
        dev.set_gateway_and_ip_address(str(gw.guid), TARGET_IP)
        res["gateway_used"] = "guid:" + str(gw.guid)
    log("gateway=%s target=%s simulation=%s" % (gw.name, TARGET_IP, res["simulation_mode"]))

    online.set_default_credentials(user, pw)
    oapp = online.create_online_application(app)
    try:
        res["before_login"] = {"application_state": str(oapp.application_state),
                               "is_logged_in": bool(oapp.is_logged_in)}
    except Exception as ex:
        res["before_login"] = {"error": str(ex)[:200]}
    try:
        oapp.login(OnlineChangeOption.Never, True)
    except Exception as ex:
        res["operation_status"] = "FAILED"
        res["reason"] = "login/download failed: " + str(ex).replace(pw, "***")[:400]
        log(res["reason"])
        return 20
    res["logged_in"] = bool(oapp.is_logged_in)
    log("logged_in=%s" % res["logged_in"])
    oapp.start()
    res["application_state"] = str(oapp.application_state)
    log("application_state=%s" % res["application_state"])
    try:
        # The plan decides what is checked online (every channel-bound image + required variable);
        # the adapter itself knows no equipment names.
        exprs = sorted(set([m["variable"].replace("Application.", "", 1) for m in PLAN.get("io_mappings", [])]
                           + ["PLC_PRG." + v for v in PLAN.get("required_variables", [])]))
        vals = oapp.read_values(exprs)
        res["online_values"] = dict((e, str(v)) for e, v in zip(exprs, vals))
        log("online_values=%s" % res["online_values"])
    except Exception as ex:
        res["online_values_error"] = str(ex)[:300]
    try:
        oapp.create_boot_application()
        res["runtime_boot_application"] = "created"
    except Exception as ex:
        res["runtime_boot_application"] = "error: " + str(ex)[:200]
    oapp.logout()
    proj.close()

    running = res["logged_in"] and res["application_state"].lower() == "run"
    vars_ok = "online_values" in res
    ok = running and vars_ok
    res["operation_status"] = "PASS" if ok else "FAILED"
    res["reason"] = ("downloaded, running, generated variables readable online" if ok else
                     "application not in RUN state" if not running else "generated variables not readable online")
    return 0 if ok else 20


code = 1
try:
    code = main()
except Exception:
    res["operation_status"] = "FAILED"
    res["reason"] = "exception"
    res["exception"] = traceback.format_exc()
    log(res["exception"])
res["exit_code_intended"] = code
log("OPERATION_STATUS=%s" % res["operation_status"])
open(RESULT, "w").write(json.dumps(res, indent=2))
open(DEPLOY_LOG, "w").write("\n".join(lines) + "\n")
system.exit(code)
