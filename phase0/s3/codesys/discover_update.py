# -*- coding: utf-8 -*-
"""S3 discovery (scratch only): does device.update() regenerate the register channel arrays after
the assembly-size parameters change? IronPython 2.7. Env: S3_DISCOVERY_DIR
"""
from __future__ import print_function
import os
import json
import traceback

OUT_DIR = os.environ["S3_DISCOVERY_DIR"]
PROJECT = os.path.join(OUT_DIR, "discovery_update.project")
OUT = os.path.join(OUT_DIR, "discovery_update.json")
res = {"steps": []}


def counts(server):
    out = {}
    for cn in list(server.connectors):
        for p in list(cn.host_parameters):
            pid = str(p.id)
            if pid in ("3", "4", "103", "104"):
                out["p" + pid] = str(p.value)
            if pid in ("1000", "2000"):
                out["n" + pid] = len(list(p))
    return out


def setp(server, pid, val):
    for cn in list(server.connectors):
        for p in list(cn.host_parameters):
            if str(p.id) == pid:
                p.value = val


def repo(type_, id_):
    best = None
    for d in device_repository.get_all_devices():
        did = d.device_id
        if int(did.type) == type_ and str(did.id) == id_:
            best = d
    return best.device_id


try:
    if os.path.exists(PROJECT):
        os.remove(PROJECT)
    proj = projects.create(PROJECT, True)
    plc = list(device_repository.get_all_devices("CODESYS Control Win V3 x64"))[0]
    proj.add("Device", plc.device_id)
    proj.find("Device", True)[0].add("Ethernet", 110, "0000 0002", str(repo(110, "0000 0002").version))
    s = repo(115, "0000 0002")
    proj.find("Ethernet", True)[0].add("Modbus_TCP_Server", int(s.type), str(s.id), str(s.version))
    server = proj.find("Modbus_TCP_Server", True)[0]
    res["steps"].append({"fresh": counts(server)})
    for pid in ("3", "103"):
        setp(server, pid, "16")
    for pid in ("4", "104"):
        setp(server, pid, "12")
    res["steps"].append({"after_set_3_4_103_104": counts(server)})
    try:
        server.update(int(s.type), str(s.id), str(s.version))
        server = proj.find("Modbus_TCP_Server", True)[0]
        res["steps"].append({"after_update": counts(server)})
    except Exception as ex:
        res["steps"].append({"update_error": str(ex)[:300]})
    proj.save()
    proj.close()
    proj = projects.open(PROJECT)
    res["steps"].append({"after_reopen": counts(proj.find("Modbus_TCP_Server", True)[0])})
    proj.close()
except Exception:
    res["exception"] = traceback.format_exc()
open(OUT, "w").write(json.dumps(res, indent=1))
system.exit(0)
