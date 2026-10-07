# -*- coding: utf-8 -*-
"""S1-FIX discovery (read-only): enumerate the CODESYS device repository for
Ethernet / Modbus TCP server descriptors and dump the device tree + parameters of a
COPY of the reference POC project. IronPython 2.7 / CODESYS ScriptEngine.

Env:
  S1FIX_OUT        output JSON path
  S1FIX_REF_COPY   optional path to a copy of the reference project
"""
from __future__ import print_function
import os
import json
import traceback

OUT = os.environ.get("S1FIX_OUT")
REF = os.environ.get("S1FIX_REF_COPY", "")
KEYS = ("ethernet", "modbus")


def safe(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def did_dict(did):
    if did is None:
        return None
    return {"type": safe(did, "type"), "id": str(safe(did, "id", "")), "version": str(safe(did, "version", ""))}


def repo_scan():
    rows = []
    for d in device_repository.get_all_devices():
        info = safe(d, "device_info")
        name = str(safe(info, "name", "") or "")
        desc = str(safe(info, "description", "") or "")
        vendor = str(safe(info, "vendor", "") or "")
        low = (name + " " + desc).lower()
        if not any(k in low for k in KEYS):
            continue
        cats = []
        try:
            cats = [int(c) for c in list(safe(info, "categories", []) or [])]
        except Exception:
            pass
        rows.append({"name": name, "vendor": vendor, "description": desc[:200],
                     "categories": cats, "device_id": did_dict(safe(d, "device_id"))})
    return rows


def params_of(dev):
    out = []
    try:
        for cn in list(dev.connectors):
            c = {"connector_id": str(safe(cn, "connector_id", "")), "interface": str(safe(cn, "interface", "")),
                 "host_parameters": []}
            for p in list(cn.host_parameters):
                v = ""
                try:
                    v = str(p.value)[:120]
                except Exception:
                    pass
                c["host_parameters"].append({"id": str(safe(p, "id", "")), "name": str(safe(p, "name", "")),
                                             "value": v, "is_mappable_io": bool(safe(p, "is_mappable_io", False)),
                                             "iec_type": str(safe(p, "iec_type", "") or "")})
            out.append(c)
    except Exception as ex:
        out.append({"error": str(ex)})
    dp = []
    try:
        for p in list(dev.device_parameters):
            v = ""
            try:
                v = str(p.value)[:120]
            except Exception:
                pass
            dp.append({"id": str(safe(p, "id", "")), "name": str(safe(p, "name", "")), "value": v})
    except Exception as ex:
        dp.append({"error": str(ex)})
    return out, dp


def tree(node, depth, rows):
    is_dev = bool(safe(node, "is_device", False))
    row = {"depth": depth, "name": str(safe(node, "get_name", lambda: "")() if callable(safe(node, "get_name")) else ""),
           "is_device": is_dev}
    if is_dev:
        try:
            row["device_id"] = did_dict(node.get_device_identification())
        except Exception as ex:
            row["device_id_error"] = str(ex)
        conns, dps = params_of(node)
        row["connectors"] = conns
        row["device_parameters"] = dps
    rows.append(row)
    try:
        for ch in node.get_children(False):
            tree(ch, depth + 1, rows)
    except Exception:
        pass


result = {}
try:
    result["repo_matches"] = repo_scan()
except Exception:
    result["repo_error"] = traceback.format_exc()

if REF and os.path.isfile(REF):
    try:
        proj = projects.open(REF)
        rows = []
        for top in proj.get_children(False):
            tree(top, 0, rows)
        result["reference_tree"] = rows
        proj.close()
    except Exception:
        result["reference_error"] = traceback.format_exc()

f = open(OUT, "w")
f.write(json.dumps(result, indent=1))
f.close()
print("DISCOVERY_WRITTEN " + OUT)
system.exit(0)
