# -*- coding: utf-8 -*-
"""S3 discovery (scratch only): set server sizes/DistinctBitAreas by parameter id, save, reopen,
and dump the regenerated parameter/channel structure. IronPython 2.7.

Env: S3_DISCOVERY_DIR
"""
from __future__ import print_function
import os
import json
import traceback

OUT_DIR = os.environ["S3_DISCOVERY_DIR"]
PROJECT = os.path.join(OUT_DIR, "discovery_reopen.project")
OUT = os.path.join(OUT_DIR, "discovery_reopen.json")
res = {"phases": []}


def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def dump(server, label):
    rows = []
    for ci, cn in enumerate(list(server.connectors)):
        for p in list(cn.host_parameters):
            v = ""
            try:
                v = str(p.value)[:60]
            except Exception:
                pass
            row = {"connector": ci, "connector_id": str(safe(cn, "connector_id", "")), "id": str(safe(p, "id", "")),
                   "name": str(safe(p, "name", "")), "value": v, "mappable": bool(safe(p, "is_mappable_io", False))}
            if row["mappable"]:
                subs = list(p)
                row["n_children"] = len(subs)
                row["channel_type"] = str(safe(p, "channel_type", ""))
                if subs:
                    row["first_child_id"] = str(safe(subs[0], "identifier", ""))
                    row["first_child_n"] = len(list(subs[0]))
            rows.append(row)
    res["phases"].append({"label": label, "params": rows})
    print("DUMP " + label)


def param_by_id(server, pid):
    out = []
    for cn in list(server.connectors):
        for p in list(cn.host_parameters):
            if str(safe(p, "id", "")) == str(pid):
                out.append(p)
    return out


def repo(type_, id_):
    best = None
    for d in device_repository.get_all_devices():
        did = safe(d, "device_id")
        if did is not None and int(did.type) == type_ and str(did.id) == id_:
            best = d
    return best.device_id


try:
    if os.path.exists(PROJECT):
        os.remove(PROJECT)
    proj = projects.create(PROJECT, True)
    plc = list(device_repository.get_all_devices("CODESYS Control Win V3 x64"))[0]
    proj.add("Device", plc.device_id)
    dev = proj.find("Device", True)[0]
    e = repo(110, "0000 0002")
    dev.add("Ethernet", int(e.type), str(e.id), str(e.version))
    eth = proj.find("Ethernet", True)[0]
    s = repo(115, "0000 0002")
    eth.add("Modbus_TCP_Server", int(s.type), str(s.id), str(s.version))
    server = proj.find("Modbus_TCP_Server", True)[0]
    dump(server, "fresh")
    for pid, val in (("12", "TRUE"), ("13", "8"), ("14", "8"), ("103", "16"), ("104", "12")):
        for p in param_by_id(server, pid):
            p.value = val
    proj.save()
    proj.close()
    proj = projects.open(PROJECT)
    server = proj.find("Modbus_TCP_Server", True)[0]
    dump(server, "after set ids 12/13/14/103/104 + save + reopen")
    proj.close()
except Exception:
    res["exception"] = traceback.format_exc()
    print(res["exception"])

open(OUT, "w").write(json.dumps(res, indent=1))
system.exit(0)
