"""S6 revision engine (CPython, deterministic, vendor-neutral, no LLM).

canonical model revision N + parent revision record + allocation history
  -> canonical checks (schema, revision metadata, identity)
  -> S3 model rules (phase0/s3/engine/canonical.validate)
  -> revision diff (per stable identity project/equipment/tag)
  -> change policy (breaking changes are BLOCKED unless approved in the model)
  -> lock-aware allocation through the S3 allocator:
       * an identity present in the parent with the same datatype + area keeps its address (PRESERVED)
       * an identity that existed earlier with the same datatype + area gets its old address back (RESTORED)
       * every address ever assigned to an identity is reserved for that identity forever:
         it is never handed to another identity (removed / reallocated addresses stay RETIRED)
       * new identities get the lowest free addresses (S3 rule, ordered by symbol)
The result is an S3-format resolved model (all addresses pinned); vendor output (ST, CODESYS plan)
is produced by the generator / adapter, never here.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "s3" / "engine"))
import canonical as cn  # noqa: E402

SCHEMA = "ai_bms.engineering_model.v1"
PROFILE = "rev"
RESERVED_PREFIX = "~reserved~"
FIELDS = ("datatype", "direction", "area", "symbol", "plc_var", "scale", "bits", "verification_values")
BREAKING_FIELDS = {"datatype", "area", "address"}
PRIMARY = (("datatype", "TYPE_CHANGED"), ("direction", "DIRECTION_CHANGED"), ("area", "AREA_CHANGED"),
           ("address", "ADDRESS_CHANGED"))


def err(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def symbol(s: dict):
    return s.get("symbol", s.get("tag"))


def plc_var(s: dict):
    return s.get("plc_var", symbol(s))


def identity(project_id: str, s: dict) -> str:
    return f"{project_id}/{s.get('equipment')}/{s.get('tag')}"


def view(s: dict) -> dict:
    mb = s.get("modbus") or {}
    return {"datatype": s.get("datatype"), "direction": s.get("direction"), "area": mb.get("area"),
            "address": mb.get("address"), "symbol": symbol(s), "plc_var": plc_var(s),
            "scale": float(mb.get("scale", 1.0)) if isinstance(mb.get("scale", 1.0), (int, float)) else mb.get("scale"),
            "bits": s.get("bits"), "verification_values": s.get("verification_values")}


def loc(e: dict | None) -> dict | None:
    return None if e is None else {"area": e["area"], "address": e["address"], "length": e["length"]}


def check_canonical(canon: dict) -> list[dict]:
    """Revision metadata, equipment and identity rules (vendor-neutral)."""
    errors = []
    if canon.get("schema") != SCHEMA:
        errors.append(err("SCHEMA", f"schema must be {SCHEMA!r} (got {canon.get('schema')!r})"))
    if not isinstance(canon.get("project_id"), str) or not canon.get("project_id"):
        errors.append(err("SCHEMA", "project_id missing"))
    rev, parent = canon.get("revision"), canon.get("parent_revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        errors.append(err("SCHEMA", f"revision must be a positive integer (got {rev!r})"))
    elif parent is not None and (not isinstance(parent, int) or isinstance(parent, bool) or not 1 <= parent < rev):
        errors.append(err("SCHEMA", f"parent_revision must be null or an integer in 1..{rev - 1} (got {parent!r})"))
    eq = canon.get("equipment")
    ids = [e.get("id") for e in eq] if isinstance(eq, list) else []
    if not ids or any(not i for i in ids):
        errors.append(err("SCHEMA", "equipment list missing or has an entry without id"))
    if len(ids) != len(set(ids)):
        errors.append(err("SCHEMA", "duplicate equipment id"))
    if not isinstance(canon.get("signals"), list):
        errors.append(err("SCHEMA", "signals list missing"))
        return errors
    for name, v in (canon.get("variables") or {}).items():
        if "equipment" in v and v["equipment"] not in ids:
            errors.append(err("EQUIPMENT", f"variable {name}: unknown equipment {v['equipment']!r}"))
    seen_id, seen_sym = {}, {}
    for k, s in enumerate(canon["signals"]):
        if not s.get("equipment"):
            errors.append(err("EQUIPMENT", f"signal[{k}] ({s.get('tag')}): missing equipment"))
            continue
        if s["equipment"] not in ids:
            errors.append(err("EQUIPMENT", f"signal[{k}] ({s.get('tag')}): unknown equipment {s['equipment']!r}"))
        if not s.get("tag"):
            continue
        i = identity(canon.get("project_id"), s)
        if i in seen_id:
            errors.append(err("DUPLICATE_TAG", f"duplicate tag {s['tag']} in equipment {s['equipment']} (identity {i})"))
        seen_id[i] = k
        sy = symbol(s)
        if sy in seen_sym and seen_sym[sy] != i:
            errors.append(err("DUPLICATE_SYMBOL", f"symbol {sy} used by {seen_sym[sy]} and {i}; give one an explicit 'symbol'"))
        seen_sym.setdefault(sy, i)
    for a in canon.get("approvals") or []:
        if not a.get("identity") or not a.get("change"):
            errors.append(err("SCHEMA", f"approval entry needs identity and change: {a}"))
    return errors


def to_s3_signal(s: dict, address=None) -> dict:
    t = {"tag": symbol(s), "plc_var": plc_var(s), "profiles": [PROFILE]}
    for k in ("datatype", "direction", "bits", "verification_values", "initial"):
        if k in s:
            t[k] = copy.deepcopy(s[k])
    mb = copy.deepcopy(s.get("modbus") or {})
    if address is not None:
        mb["address"] = address
    t["modbus"] = mb
    return t


def to_s3_model(canon: dict, target: dict, signals3: list[dict]) -> dict:
    """S3-format model (consumed by phase0/s3 validator/allocator/generator)."""
    return {
        "model_id": f"{canon['project_id']}-r{canon['revision']:03d}",
        "ahu_id": canon["equipment"][0]["id"],
        "platform": target["platform"],
        "modbus": canon["modbus"],
        "variables": canon.get("variables") or {},
        "signals": signals3,
    }


def compute_diff(parent: dict | None, parent_lock: dict | None, canon: dict) -> dict:
    pid = canon["project_id"]
    new = {identity(pid, s): s for s in canon["signals"]}
    old = {identity(pid, s): s for s in parent["signals"]} if parent else {}
    active = {e["identity"]: e for e in (parent_lock or {}).get("active", [])}
    approvals = {(a["identity"], a["change"]) for a in canon.get("approvals") or []}
    changes = []
    for i in sorted(set(new) | set(old)):
        s = new.get(i) or old[i]
        rec = {"identity": i, "equipment": s["equipment"], "tag": s["tag"]}
        if i not in old:
            rec.update(type="ADDED", breaking=False, after=view(new[i]))
        elif i not in new:
            rec.update(type="REMOVED", breaking=False, before=view(old[i]))
        else:
            b, a = view(old[i]), view(new[i])
            fc = [{"field": k, "from": b[k], "to": a[k]} for k in FIELDS if b[k] != a[k]]
            locked = active.get(i)
            if (a["address"] is not None and locked and a["area"] == locked["area"]
                    and a["address"] != locked["address"]):
                fc.append({"field": "address", "from": locked["address"], "to": a["address"]})
            fields = {f["field"] for f in fc}
            t = next((name for f, name in PRIMARY if f in fields), "ATTRIBUTE_CHANGED" if fields else "UNCHANGED")
            rec.update(type=t, breaking=bool(fields & BREAKING_FIELDS), field_changes=fc, before=b, after=a)
            field = next((f for f, name in PRIMARY if name == t), None)
            if field:
                x = next(f for f in fc if f["field"] == field)
                rec["from"], rec["to"] = x["from"], x["to"]
            if rec["breaking"]:
                rec["approved"] = (i, t) in approvals
        changes.append(rec)
    old_eq = {e["id"] for e in parent["equipment"]} if parent else set()
    new_eq = {e["id"] for e in canon["equipment"]}
    for e in sorted(new_eq - old_eq):
        changes.append({"identity": f"{pid}/{e}", "equipment": e, "type": "EQUIPMENT_ADDED", "breaking": False})
    for e in sorted(old_eq - new_eq):
        changes.append({"identity": f"{pid}/{e}", "equipment": e, "type": "EQUIPMENT_REMOVED", "breaking": False})
    changes.sort(key=lambda c: c["identity"])

    ov, nv = (parent or {}).get("variables") or {}, canon.get("variables") or {}
    var_changes = []
    for n in sorted(set(ov) | set(nv)):
        if n not in ov:
            var_changes.append({"variable": n, "type": "VARIABLE_ADDED", "after": nv[n]})
        elif n not in nv:
            var_changes.append({"variable": n, "type": "VARIABLE_REMOVED", "before": ov[n]})
        elif ov[n] != nv[n]:
            var_changes.append({"variable": n, "type": "VARIABLE_CHANGED", "before": ov[n], "after": nv[n]})
    summary = {}
    for c in changes:
        summary[c["type"]] = summary.get(c["type"], 0) + 1
    return {
        "schema": "ai_bms.revision_diff.v1",
        "project_id": pid,
        "from_revision": parent["revision"] if parent else None,
        "to_revision": canon["revision"],
        "summary": dict(sorted(summary.items())),
        "breaking_changes": [c["identity"] for c in changes if c.get("breaking")],
        "changes": changes,
        "variable_changes": var_changes,
    }


def _cells(e: dict) -> list[tuple]:
    return [(e["area"], e["address"] + k) for k in range(e["length"])]


def allocate_with_lock(canon: dict, target: dict, parent_lock: dict | None, history: list[dict], diff: dict):
    """Returns (lock, actions, prev, errors). `history` = [{"revision": n, "active": [...]}] for every
    accepted revision committed before this one."""
    pid = canon["project_id"]
    by = {c["identity"]: c for c in diff["changes"]}
    parent_active = {e["identity"]: e for e in (parent_lock or {}).get("active", [])}
    sigs = sorted(canon["signals"], key=lambda s: identity(pid, s))
    pins, actions, prev = {}, {}, {}
    for s in sigs:
        i, v = identity(pid, s), view(s)
        old = parent_active.get(i)
        if old and not by[i]["breaking"]:
            pins[i], actions[i], prev[i] = old["address"], "PRESERVED", old
            continue
        past = [e for h in sorted(history, key=lambda h: -h["revision"]) for e in h["active"]
                if e["identity"] == i and e["datatype"] == v["datatype"] and e["area"] == v["area"]]
        if past and not old and v["address"] in (None, past[0]["address"]):
            pins[i], actions[i], prev[i] = past[0]["address"], "RESTORED", past[0]
        else:
            pins[i], actions[i], prev[i] = v["address"], ("REALLOCATED" if old else "NEW"), old

    keep = set()
    for i, a in actions.items():
        if a in ("PRESERVED", "RESTORED"):
            keep |= set(_cells(prev[i]))
    owners: dict[tuple, set] = {}
    for h in history:
        for e in h["active"]:
            for c in _cells(e):
                owners.setdefault(c, set()).add(e["identity"])
    reserved = sorted((c for c in owners if c not in keep), key=lambda c: (cn.AREAS.index(c[0]), c[1]))
    res_sigs, res_owner = [], {}
    for k, (area, addr) in enumerate(reserved):
        tag = f"{RESERVED_PREFIX}{k:04d}"
        res_owner[tag] = sorted(owners[(area, addr)])
        res_sigs.append({"tag": tag, "plc_var": tag, "datatype": "BOOL" if area in cn.BIT_AREAS else "WORD",
                         "direction": "READ", "profiles": [PROFILE], "modbus": {"area": area, "address": addr}})

    m = to_s3_model(canon, target, [to_s3_signal(s, pins[identity(pid, s)]) for s in sigs] + res_sigs)
    try:
        entries = cn.allocate(m, PROFILE)
    except cn.ValidationError as ex:
        msgs = []
        for e in ex.errors:
            for tag, own in res_owner.items():
                e = e.replace(f"'{tag}'", f"'address retired from {'/'.join(own)}'").replace(tag, f"retired address of {'/'.join(own)}")
            msgs.append(err("ALLOCATION", e))
        return None, actions, prev, msgs

    sym2id = {symbol(s): identity(pid, s) for s in sigs}
    active = []
    for e in entries:
        if e["tag"].startswith(RESERVED_PREFIX):
            continue
        i = sym2id[e["tag"]]
        active.append({"identity": i, "symbol": e["tag"], "datatype": e["datatype"], "direction": e["direction"],
                       "area": e["area"], "address": e["address"], "length": e["length"], "action": actions[i]})
    active.sort(key=lambda e: (cn.AREAS.index(e["area"]), e["address"], e["identity"]))
    now = {(e["identity"], e["area"], e["address"], e["length"]) for e in active}
    retired = {}
    for h in sorted(history, key=lambda h: h["revision"]):
        for e in h["active"]:
            if (e["identity"], e["area"], e["address"], e["length"]) in now:
                continue
            key = (e["identity"], e["datatype"], e["area"], e["address"], e["length"])
            retired[key] = {"identity": e["identity"], "datatype": e["datatype"], "area": e["area"],
                            "address": e["address"], "length": e["length"], "last_active_revision": h["revision"],
                            "rule": "reserved for this identity; never assigned to another identity"}
    lock = {"active": active,
            "retired": sorted(retired.values(), key=lambda r: (cn.AREAS.index(r["area"]), r["address"], r["identity"]))}
    return lock, actions, prev, []


def build(canon: dict, target: dict, parent: dict | None, history: list[dict]) -> dict:
    """parent = {"model": canonical dict, "lock": allocation lock} of parent_revision (None for revision 1).
    Returns {"status": ACCEPTED|REJECTED, "errors", "stages", "diff", "lock", "model", "entries"}."""
    out = {"status": "REJECTED", "errors": [], "stages": {}, "diff": None, "lock": None, "model": None, "entries": None}
    st = out["stages"]
    errors = check_canonical(canon)
    st["canonical"] = "PASS" if not errors else "FAILED"
    if isinstance(canon.get("signals"), list) and canon.get("equipment") and canon.get("project_id"):
        try:
            # Structural S3 rules only: capacity/overlap are judged later against the allocation lock + history,
            # so the S3 trial allocation runs with the capacity lifted.
            unbounded = copy.deepcopy(target)
            unbounded["platform"]["register_capacity"] = {a: 4096 for a in cn.REGISTER_AREAS}
            cand = to_s3_model(dict(canon, revision=canon.get("revision") if isinstance(canon.get("revision"), int) else 0),
                               unbounded, [to_s3_signal(s) for s in canon["signals"]])
            rule_errors = [err("MODEL_RULE", m) for m in cn.validate(cand, PROFILE)]
        except Exception as ex:  # malformed input must reject, never crash the pipeline
            rule_errors = [err("MODEL_RULE", f"model not processable: {type(ex).__name__}: {ex}")]
        st["model_rules"] = "PASS" if not rule_errors else "FAILED"
        errors += rule_errors
    if errors:
        out["errors"] = errors
        return out

    diff = compute_diff(parent and parent["model"], parent and parent["lock"], canon)
    out["diff"] = diff
    blocked = [c for c in diff["changes"] if c.get("breaking") and not c.get("approved")]
    st["policy"] = "PASS" if not blocked else "BLOCKED"
    if blocked:
        out["errors"] = [err("BREAKING_CHANGE_REQUIRES_APPROVAL",
                             f"{c['identity']}: {c['type']} {c.get('from')!r} -> {c.get('to')!r} is a breaking change; "
                             f"add approvals [{{\"identity\": \"{c['identity']}\", \"change\": \"{c['type']}\"}}] to apply it "
                             f"(the old mapping is then retired and a new mapping allocated)") for c in blocked]
        return out

    lock, actions, prev, aerr = allocate_with_lock(canon, target, parent and parent["lock"], history, diff)
    st["allocation"] = "PASS" if not aerr else "FAILED"
    if aerr:
        out["errors"] = aerr
        return out

    parent_active = {e["identity"]: e for e in ((parent or {}).get("lock") or {}).get("active", [])}
    now = {e["identity"]: e for e in lock["active"]}
    for c in diff["changes"]:
        if c["type"].startswith("EQUIPMENT"):
            continue
        i = c["identity"]
        action = "RETIRED" if c["type"] == "REMOVED" else actions[i]
        c["mapping"] = {"action": action, "from": loc(parent_active.get(i)), "to": loc(now.get(i))}
        if action == "RESTORED":
            c["mapping"]["restored_from_revision"] = next(
                h["revision"] for h in sorted(history, key=lambda h: -h["revision"])
                for e in h["active"] if e["identity"] == i and e["address"] == now[i]["address"])

    pid = canon["project_id"]
    addr = {e["identity"]: e["address"] for e in lock["active"]}
    resolved = to_s3_model(canon, target, [to_s3_signal(s, addr[identity(pid, s)]) for s in canon["signals"]])
    final_errors = cn.validate(resolved, PROFILE)
    st["resolved_model"] = "PASS" if not final_errors else "FAILED"
    if final_errors:
        out["errors"] = [err("INTERNAL", m) for m in final_errors]
        return out
    out.update(status="ACCEPTED", lock=lock, model=resolved, entries=cn.allocate(resolved, PROFILE))
    return out
