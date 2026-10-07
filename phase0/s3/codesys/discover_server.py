# -*- coding: utf-8 -*-
"""S3 discovery (scratch only): structure of the ModbusTCP Server Device parameters.

Creates a throwaway project from scratch (PLC -> Ethernet -> ModbusTCP Server Device), dumps all
host parameters with their channel structure, then toggles DistinctBitAreas and the assembly
sizes to observe which mappable areas appear and which counts change. IronPython 2.7.

Env: S3_DISCOVERY_DIR  output directory (project + discovery_server.json)
"""
from __future__ import print_function
import os
import json
import traceback

OUT_DIR = os.environ["S3_DISCOVERY_DIR"]
PROJECT = os.path.join(OUT_DIR, "discovery_scratch.project")
OUT = os.path.join(OUT_DIR, "discovery_server.json")
res = {"snapshots": []}


def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def chan(p, depth):
    d = {"identifier": str(safe(p, "identifier", "") or ""), "name": str(safe(p, "name", "") or ""),
         "iec_type": str(safe(p, "iec_type", "") or ""), "is_mappable_io": bool(safe(p, "is_mappable_io", False)),
         "channel_type": str(safe(p, "channel_type", "") or "")}
    try:
        subs = list(p)
    except Exception:
        subs = []
    d["n_children"] = len(subs)
    if depth > 0 and subs:
        d["first_children"] = [chan(s, depth - 1) for s in subs[:2]]
        if len(subs) > 2:
            d["last_child"] = chan(subs[-1], 0)
    return d


def snapshot(server, label):
    rows = []
    for cn in list(server.connectors):
        for p in list(cn.host_parameters):
            v = ""
            try:
                v = str(p.value)[:80]
            except Exception:
                pass
            row = {"id": str(safe(p, "id", "")), "name": str(safe(p, "name", "")), "value": v,
                   "is_mappable_io": bool(safe(p, "is_mappable_io", False))}
            if row["is_mappable_io"]:
                row["structure"] = chan(p, 3)
            rows.append(row)
    res["snapshots"].append({"label": label, "params": rows})
    print("SNAPSHOT " + label + " params=%d" % len(rows))


def host_param(dev, name):
    for cn in list(dev.connectors):
        for p in list(cn.host_parameters):
            if str(safe(p, "name", "")) == name:
                return p
    return None


def set_param(server, name, value):
    p = host_param(server, name)
    if p is None:
        res.setdefault("set_errors", []).append(name + ": not found")
        return
    try:
        p.value = value
        res.setdefault("set_ok", []).append("%s=%s -> %s" % (name, value, str(host_param(server, name).value)))
    except Exception as ex:
        res.setdefault("set_errors", []).append("%s=%s: %s" % (name, value, ex))


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
    snapshot(server, "default")
    set_param(server, "DistinctBitAreas", "TRUE")
    snapshot(server, "DistinctBitAreas=TRUE")
    set_param(server, "InputAssemblySize", "20")
    snapshot(server, "InputAssemblySize=20")
    set_param(server, "OutputAssemblySize", "12")
    snapshot(server, "OutputAssemblySize=12")
    set_param(server, "Coils Size", "8")
    set_param(server, "Discrete Inputs Size", "8")
    snapshot(server, "Coils/Discrete Size=8")
    proj.close()
except Exception:
    res["exception"] = traceback.format_exc()
    print(res["exception"])

open(OUT, "w").write(json.dumps(res, indent=1))
print("WROTE " + OUT)
system.exit(0)
