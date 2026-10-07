"""S6 revision verification checks (CPython, measurement only; every check writes a result JSON).

  diff           --revision N --scenario S          stored diff vs independent recomputation + scenario expectations
  stability      --from A --to B [--deployed-a D --deployed-b D]
                                                    unchanged identities keep area/address/length (store + runtime-verified
                                                    mappings); new mappings avoid every address owned by another identity
                                                    and take the lowest free run; naive (lock-less) allocation shown
  rollback-compare --revision N --a D --b D         deploy stage of rN vs deploy stage of the rollback (artifacts + runtime)
  invalid        --base M --target T --work W       invalid revisions are REJECTED and accepted revisions stay intact
  expect-reject  --model M --target T --label L --code C --text X
  dry-run-check  --model M --target T --label L --identity I --type T --action A
  repro          --out W                            every accepted revision regenerated twice: identical to store and each other
  integrity                                         manifests, no extra files, index consistent
Common: --eng-root, --gen-root, --result. Exit: 0 PASS, 20 FAILED.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "generator"))
import regenerate as rg  # noqa: E402

rv, cn = rg.rv, rg.cn
REGEN = str(HERE.parents[1] / "generator" / "regenerate.py")


def jload(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def norm(obj, root: str):
    if isinstance(obj, dict):
        return {k: norm(v, root) for k, v in obj.items() if k not in ("timestamp", "duration_seconds")}
    if isinstance(obj, list):
        return [norm(v, root) for v in obj]
    if isinstance(obj, str):
        return obj.replace(root, "<STAGE>").replace(root.replace("\\", "/"), "<STAGE>")
    return obj


def snapshot(store: rg.Store) -> dict:
    """Accepted revision content + index history pointer (rejections may only append to index.rejected/events)."""
    snap = {}
    for n in store.accepted():
        for d in store.dirs(n):
            for f in sorted(p for p in d.rglob("*") if p.is_file()):
                snap[str(f.relative_to(d.parent.parent))] = hashlib.sha256(f.read_bytes()).hexdigest()
    idx = store.index() or {}
    snap["<index.revisions>"] = json.dumps(idx.get("revisions"))
    snap["<index.current>"] = json.dumps(idx.get("current"))
    return snap


def regen(store: rg.Store, *args) -> dict:
    tmp = store.eng.parent / "_check_result.json"
    cmd = [sys.executable, REGEN, *args, "--eng-root", str(store.eng.parent), "--gen-root", str(store.gen.parent),
           "--result", str(tmp)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    r = jload(tmp) if tmp.exists() else {"operation_status": "FAILED", "reason": p.stderr[-400:]}
    tmp.unlink(missing_ok=True)
    r["process_exit_code"] = p.returncode
    return r


# ---------------------------------------------------------------- diff
def independent_types(parent: dict | None, model: dict) -> dict:
    pid = model["project_id"]
    key = lambda s: f"{pid}/{s['equipment']}/{s['tag']}"  # noqa: E731
    old = {key(s): s for s in (parent or {}).get("signals", [])}
    new = {key(s): s for s in model["signals"]}
    out = {}
    for i in set(old) | set(new):
        if i not in old:
            out[i] = "ADDED"
        elif i not in new:
            out[i] = "REMOVED"
        else:
            a, b = old[i], new[i]
            if a["datatype"] != b["datatype"]:
                out[i] = "TYPE_CHANGED"
            elif a["direction"] != b["direction"]:
                out[i] = "DIRECTION_CHANGED"
            elif a["modbus"].get("area") != b["modbus"].get("area"):
                out[i] = "AREA_CHANGED"
            else:
                strip = lambda s: {k: v for k, v in s.items() if k not in ("datatype", "direction")}  # noqa: E731
                out[i] = "UNCHANGED" if strip(a) == strip(b) else "ATTRIBUTE_CHANGED"
    oe = {e["id"] for e in (parent or {}).get("equipment", [])}
    ne = {e["id"] for e in model["equipment"]}
    for e in ne - oe:
        out[f"{pid}/{e}"] = "EQUIPMENT_ADDED"
    for e in oe - ne:
        out[f"{pid}/{e}"] = "EQUIPMENT_REMOVED"
    return out


def cmd_diff(a, store, res):
    files = store.read(a.revision)
    model, diff = json.loads(files["engineering/model.json"]), json.loads(files["engineering/revision_diff.json"])
    parent = json.loads(store.read(model["parent_revision"])["engineering/model.json"]) if model["parent_revision"] else None
    exp = jload(a.scenario)["diffs"][str(a.revision)]
    got = {c["identity"]: c for c in diff["changes"]}
    indep = independent_types(parent, model)
    c = res["checks"]
    c["revision_metadata"] = (diff["from_revision"], diff["to_revision"]) == (model["parent_revision"], model["revision"])
    c["independent_recomputation_matches"] = {i: g["type"] for i, g in got.items()} == indep
    mism = []
    for i, g in got.items():
        want = exp["expect"].get(i, exp.get("default"))
        if want is None:
            mism.append(f"{i}: no expectation")
            continue
        action = (g.get("mapping") or {}).get("action")
        if [g["type"], action] != want:
            mism.append(f"{i}: got {[g['type'], action]} want {want}")
        m = g.get("mapping")
        if m and ((m["action"] == "PRESERVED" and m["from"] != m["to"]) or (m["action"] in ("NEW", "RESTORED") and m["from"] is not None)
                  or (m["action"] == "RETIRED" and m["to"] is not None)):
            mism.append(f"{i}: mapping action {m['action']} inconsistent with from/to")
    c["scenario_expectations"] = not mism
    c["no_breaking_changes"] = not diff["breaking_changes"]
    res.update(mismatches=mism, summary=diff["summary"],
               changes=[{k: x.get(k) for k in ("identity", "type", "breaking", "mapping")} for x in diff["changes"]])


# ---------------------------------------------------------------- stability
def cells(e):
    return [(e["area"], e["address"] + k) for k in range(e["length"])]


def cmd_stability(a, store, res):
    A = json.loads(store.read(a.frm)["engineering/allocation.json"])
    B = json.loads(store.read(a.to)["engineering/allocation.json"])
    diff = json.loads(store.read(a.to)["engineering/revision_diff.json"])
    realloc = {x["identity"] for x in diff["changes"] if (x.get("mapping") or {}).get("action") == "REALLOCATED"}
    ea, eb = {e["identity"]: e for e in A["active"]}, {e["identity"]: e for e in B["active"]}
    c = res["checks"]
    kept, moved = [], []
    for i in sorted(set(ea) & set(eb)):
        x, y = ea[i], eb[i]
        same = (x["area"], x["address"], x["length"]) == (y["area"], y["address"], y["length"])
        (kept if same else moved).append({"identity": i, "from": rv.loc(x), "to": rv.loc(y)})
    c["existing_mappings_unchanged"] = all(m["identity"] in realloc for m in moved)
    owners = {}
    for n in store.accepted():
        if n < a.to:
            for e in json.loads(store.read(n)["engineering/allocation.json"])["active"]:
                for cl in cells(e):
                    owners.setdefault(cl, set()).add(e["identity"])
    new = [eb[i] for i in sorted(set(eb) - set(ea))]
    clashes = [f"{e['identity']} {cl}" for e in new for cl in cells(e) if owners.get(cl, {e["identity"]}) - {e["identity"]}]
    c["new_mappings_avoid_owned_addresses"] = not clashes
    m = json.loads(store.read(a.to)["engineering/model.json"])
    tgt = jload(Path(store.dirs(a.to)[0]) / "target.json")
    cap = tgt["platform"]["register_capacity"]
    model_pinned = {rv.symbol(s) for s in m["signals"] if "address" in (s.get("modbus") or {})}
    auto = [x for x in B["active"] if x["action"] in ("NEW", "REALLOCATED") and x["symbol"] not in model_pinned]
    auto_syms = {x["symbol"] for x in auto}
    lowest = []
    for e in sorted((x for x in auto if x["area"] in cn.REGISTER_AREAS), key=lambda x: x["symbol"]):
        busy = {cl for cl in owners if owners[cl] - {e["identity"]}}
        busy |= {cl for x in B["active"] if x["area"] in cn.REGISTER_AREAS and x is not e
                 and (x["symbol"] not in auto_syms or x["symbol"] < e["symbol"]) for cl in cells(x)}
        busy |= {(cn.BIT_OVERLAY[x["area"]], x["address"] // 16) for x in B["active"]
                 if x["area"] in cn.BIT_AREAS and x["symbol"] not in auto_syms}
        busy |= {(cn.BIT_OVERLAY[cl[0]], cl[1] // 16) for cl in owners if cl[0] in cn.BIT_AREAS and owners[cl] - {e["identity"]}}
        first = next((s for s in range(cap[e["area"]] - e["length"] + 1)
                      if all((e["area"], s + k) not in busy for k in range(e["length"]))), None)
        lowest.append({"identity": e["identity"], "address": e["address"], "lowest_free": first})
    c["new_mappings_lowest_free"] = all(x["address"] == x["lowest_free"] for x in lowest)
    naive = cn.allocate(rv.to_s3_model(m, tgt, [rv.to_s3_signal(s) for s in m["signals"]]), rv.PROFILE)
    sym = {e["symbol"]: e for e in B["active"]}
    res["naive_lockless_allocation_would_move"] = [
        {"identity": sym[e["tag"]]["identity"], "locked": rv.loc(sym[e["tag"]]), "naive": rv.loc(e)}
        for e in naive if (e["area"], e["address"]) != (sym[e["tag"]]["area"], sym[e["tag"]]["address"])]
    if a.deployed_a and a.deployed_b:
        da = {s["identity"]: s for s in jload(Path(a.deployed_a) / "engineering" / "modbus_mapping.json")["signals"]}
        db = {s["identity"]: s for s in jload(Path(a.deployed_b) / "engineering" / "modbus_mapping.json")["signals"]}
        c["runtime_verified_all_signals_to"] = bool(db) and all(s["verified"] for s in db.values())
        c["runtime_verified_common_same_address"] = all(
            da[i]["verified"] and db[i]["verified"] and (da[i]["area"], da[i]["address"], da[i]["length"])
            == (db[i]["area"], db[i]["address"], db[i]["length"]) for i in set(da) & set(db) if i not in realloc)
        res["runtime_verified"] = {i: {"area": s["area"], "address": s["address"], "verified": s["verified"]}
                                   for i, s in sorted(db.items())}
    res.update(preserved=kept, moved=moved, new=[{"identity": e["identity"], **rv.loc(e)} for e in new],
               lowest_free=lowest, clashes=clashes, retired=B["retired"])


# ---------------------------------------------------------------- rollback
def cmd_rollback(a, store, res):
    A, B = Path(a.a), Path(a.b)
    c = res["checks"]
    eng_same = []
    for f in ("model.json", "target.json", "allocation.json", "codesys_plan.json", "revision_diff.json", "validation.json"):
        eng_same.append(jload(A / "engineering" / f) == jload(B / "engineering" / f))
    c["engineering_artifacts_identical"] = all(eng_same)
    c["plc_source_identical"] = all((A / "generated" / f).read_bytes() == (B / "generated" / f).read_bytes()
                                    for f in rg.PLC_FILES)
    strip_v = lambda m: [{k: v for k, v in s.items() if k != "verification"} for s in m["signals"]]  # noqa: E731
    ma, mb = jload(A / "engineering" / "modbus_mapping.json"), jload(B / "engineering" / "modbus_mapping.json")
    c["verified_mapping_identical"] = strip_v(ma) == strip_v(mb) and ma["real32"] == mb["real32"]
    c["all_signals_verified_after_rollback"] = all(s["verified"] for s in mb["signals"])
    keys = {
        "create_result.json": ("devices", "server_parameters", "channel_counts", "io_mappings", "build", "checks", "operation_status"),
        "verify_result.json": ("device_tree", "server_parameters", "channel_counts", "io_mappings", "plc_prg_decl",
                               "plc_prg_impl", "missing_variables", "rebuild", "checks", "operation_status"),
        "deployment_result.json": ("simulation_mode", "logged_in", "application_state", "operation_status"),
        "s1_regression.json": ("hr", "ir", "checks", "bits_after_start", "bits_after_stop", "di_after_start",
                               "di_after_stop", "operation_status"),
        "typed_verify.json": ("real32_candidates_after_reads", "real32_ordering", "checks", "per_signal", "tolerance",
                              "operation_status"),
    }
    diffs = []
    for f, ks in keys.items():
        x, y = norm(jload(A / "logs" / f), str(A)), norm(jload(B / "logs" / f), str(B))
        for k in ks:
            if x.get(k) != y.get(k):
                diffs.append(f"{f}:{k}")
    case_keys = ("phase", "tag", "path", "datatype", "intended", "plc_value", "modbus_raw", "decoded", "written_raw",
                 "modbus_readback", "overlay_register_raw", "checks", "pass")
    ca = [{k: x.get(k) for k in case_keys} for x in jload(A / "logs" / "typed_verify.json")["cases"]]
    cb = [{k: x.get(k) for k in case_keys} for x in jload(B / "logs" / "typed_verify.json")["cases"]]
    if ca != cb:
        diffs.append("typed_verify.json:cases")
    c["codesys_and_runtime_results_identical"] = not diffs
    c["rollback_runtime_pass"] = all(jload(B / "logs" / f).get("operation_status") == "PASS"
                                     for f in ("create_result.json", "verify_result.json", "deployment_result.json",
                                               "s1_regression.json", "typed_verify.json"))
    idx = store.index()
    c["index_rollback_event"] = any(e == {"event": "rollback", "from": e.get("from"), "to": a.revision}
                                    for e in idx["events"])
    res.update(differences=diffs, typed_cases_compared=len(ca))


# ---------------------------------------------------------------- invalid / reject / dry-run
def sig(m, tag, eq="AHU-01"):
    return next(s for s in m["signals"] if s["tag"] == tag and s["equipment"] == eq)


def add_var_sig(m, tag, typ, init, signal):
    m["variables"][tag] = {"type": typ, "initial": init, "role": "process", "equipment": "AHU-01"}
    m["signals"].append(dict({"equipment": "AHU-01", "tag": tag}, **signal))


INVALID_CASES = [
    ("duplicate_tag", "DUPLICATE_TAG", "duplicate tag",
     lambda m: m["signals"].append(copy.deepcopy(sig(m, "ReturnTemp")))),
    ("duplicate_address", "ALLOCATION", "overlaps",
     lambda m: add_var_sig(m, "ExhaustRaw", "WORD", 0, {"datatype": "WORD", "direction": "READ",
                                                       "modbus": {"area": "INPUT_REGISTER", "address": 3}})),
    ("real32_length_1", "MODEL_RULE", "requires length=2", lambda m: sig(m, "ReturnTemp")["modbus"].update(length=1)),
    ("missing_datatype", "MODEL_RULE", "missing datatype", lambda m: sig(m, "ReturnTemp").pop("datatype")),
    ("missing_area", "MODEL_RULE", "missing area", lambda m: sig(m, "ReturnTemp")["modbus"].pop("area")),
    ("invalid_direction", "MODEL_RULE", "unsupported direction",
     lambda m: sig(m, "ReturnTemp").update(direction="BIDIRECTIONAL")),
    ("direction_area_mismatch", "MODEL_RULE", "must use INPUT_REGISTER",
     lambda m: sig(m, "ReturnTemp")["modbus"].update(area="HOLDING_REGISTER")),
    ("overlapping_real32", "ALLOCATION", "overlaps",
     lambda m: add_var_sig(m, "MixedAirTemp", "REAL", 15.0, {"datatype": "REAL32", "direction": "READ",
                                                            "modbus": {"area": "INPUT_REGISTER", "address": 4, "length": 2}})),
    ("capacity_exceeded", "ALLOCATION", "free register",
     lambda m: [add_var_sig(m, t, "REAL", 10.0, {"datatype": "REAL32", "direction": "READ",
                                                 "modbus": {"area": "INPUT_REGISTER", "length": 2}})
                for t in ("OutdoorTemp", "MixedAirTemp")]),
    ("revision_already_exists", "STORE", "already exists", "REV_EXISTS"),
    ("unknown_parent", "STORE", "not an accepted revision", "BAD_PARENT"),
]


def reject_case(store, model: Path, target: str, label: str, code: str, text: str) -> dict:
    before = snapshot(store)
    r = regen(store, "commit", "--model", str(model), "--target", target, "--label", label)
    after = snapshot(store)
    errs = r.get("errors") or []
    out = {"label": label, "expected_code": code, "expected_text": text, "status": r.get("status"),
           "process_exit_code": r["process_exit_code"], "errors": errs,
           "rejected": r.get("status") == "REJECTED",
           "expected_error_found": any(e["code"] == code and text in e["message"] for e in errs),
           "accepted_revisions_unchanged": before == after, "diff_summary": r.get("diff_summary")}
    out["pass"] = out["rejected"] and out["expected_error_found"] and out["accepted_revisions_unchanged"]
    return out


def cmd_invalid(a, store, res):
    base = jload(a.base)
    acc = store.accepted()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, code, text, mut in INVALID_CASES:
        m = copy.deepcopy(base)
        m["revision"], m["parent_revision"] = max(acc) + 1, max(acc)
        if mut == "REV_EXISTS":
            m["revision"], m["parent_revision"] = max(acc), max(acc) - 1 if max(acc) > 1 else None
        elif mut == "BAD_PARENT":
            m["parent_revision"] = 99
        else:
            mut(m)
        p = work / f"invalid_{name}.json"
        p.write_text(json.dumps(m, indent=2), encoding="utf-8")
        cases.append(dict(reject_case(store, p, a.target, f"invalid_{name}", code, text), case=name))
    latest = max(acc)
    rp = regen(store, "reproduce", "--revision", str(latest))
    res["checks"] = {f"{x['case']}_rejected": x["pass"] for x in cases}
    res["checks"]["previous_valid_revision_reproducible"] = rp["operation_status"] == "PASS"
    res["checks"]["store_revisions_unchanged"] = store.accepted() == acc
    res.update(cases=cases, latest_valid_revision=latest, latest_reproduce=rp.get("reason"))


def cmd_expect_reject(a, store, res):
    x = reject_case(store, Path(a.model), a.target, a.label, a.code, a.text)
    res["checks"] = {"rejected": x["rejected"], "expected_error_found": x["expected_error_found"],
                     "accepted_revisions_unchanged": x["accepted_revisions_unchanged"]}
    d = store.eng / "rejected" / a.label / "revision_diff.json"
    if d.exists():
        diff = jload(d)
        res["breaking_changes"] = [{k: c.get(k) for k in ("identity", "type", "from", "to", "breaking", "approved", "field_changes")}
                                   for c in diff["changes"] if c.get("breaking")]
    res["case"] = x


def cmd_dry_run(a, store, res):
    before = snapshot(store)
    r = regen(store, "dry-run", "--model", a.model, "--target", a.target, "--label", a.label)
    after = snapshot(store)
    c = res["checks"]
    c["dry_run_accepted"] = r.get("status") == "ACCEPTED"
    c["store_untouched"] = before == after
    d = store.eng / "attempts" / a.label / "revision_diff.json"
    ch = next((x for x in jload(d)["changes"] if x["identity"] == a.identity), {}) if d.exists() else {}
    c["change_type"] = ch.get("type") == a.type
    c["mapping_action"] = (ch.get("mapping") or {}).get("action") == a.action
    c["non_breaking"] = ch.get("breaking") is False
    res["change"] = {k: ch.get(k) for k in ("identity", "type", "from", "to", "breaking", "mapping", "field_changes")}


# ---------------------------------------------------------------- repro / integrity
def cmd_repro(a, store, res):
    out = Path(a.out)
    rows = []
    for n in store.accepted():
        ra = regen(store, "reproduce", "--revision", str(n), "--out", str(out / f"r{n:03d}_a"))
        rb = regen(store, "reproduce", "--revision", str(n), "--out", str(out / f"r{n:03d}_b"))
        fa = {p.relative_to(out / f"r{n:03d}_a").as_posix(): p.read_bytes() for p in (out / f"r{n:03d}_a").rglob("*") if p.is_file()}
        fb = {p.relative_to(out / f"r{n:03d}_b").as_posix(): p.read_bytes() for p in (out / f"r{n:03d}_b").rglob("*") if p.is_file()}
        rows.append({"revision": n, "a_matches_store": ra["operation_status"] == "PASS",
                     "b_matches_store": rb["operation_status"] == "PASS", "a_equals_b": bool(fa) and fa == fb,
                     "files": len(fa)})
    res["checks"] = {f"r{x['revision']:03d}": x["a_matches_store"] and x["b_matches_store"] and x["a_equals_b"] for x in rows}
    res["revisions"] = rows


def cmd_integrity(a, store, res):
    idx = store.index()
    c = res["checks"]
    rows = []
    for n in store.accepted():
        e, g = store.dirs(n)
        try:
            files = store.read(n)
            man_ok = True
        except rg.StoreError as ex:
            files, man_ok = {}, str(ex)
        on_disk = {f"engineering/{p.relative_to(e).as_posix()}" for p in e.rglob("*") if p.is_file()} | \
                  {f"generated/{p.relative_to(g).as_posix()}" for p in g.rglob("*") if p.is_file()}
        extra = sorted(on_disk - set(files) - {"engineering/manifest.json"})
        entry = next(r for r in idx["revisions"] if r["revision"] == n)
        man_sha = hashlib.sha256((e / "manifest.json").read_bytes()).hexdigest()
        rows.append({"revision": n, "manifest_matches": man_ok is True, "extra_files": extra,
                     "index_manifest_sha_matches": entry["manifest_sha256"] == man_sha, "files": len(files)})
    dirs = sorted(int(p.name[1:]) for p in store.eng.glob("r[0-9][0-9][0-9]") if p.is_dir())
    c["all_manifests_match"] = all(r["manifest_matches"] for r in rows)
    c["no_extra_files"] = all(not r["extra_files"] for r in rows)
    c["index_manifest_hashes_match"] = all(r["index_manifest_sha_matches"] for r in rows)
    c["index_lists_every_revision_dir"] = dirs == store.accepted()
    c["no_temp_dirs_left"] = not list(store.eng.glob(".r*.tmp")) and not list(store.gen.glob(".r*.tmp"))
    res.update(revisions=rows, current=idx["current"], events=idx["events"], rejected=idx["rejected"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("diff", "stability", "rollback-compare", "invalid", "expect-reject",
                                        "dry-run-check", "repro", "integrity"))
    ap.add_argument("--eng-root", required=True)
    ap.add_argument("--gen-root", required=True)
    ap.add_argument("--result", required=True)
    for k in ("scenario", "deployed-a", "deployed-b", "a", "b", "base", "target", "work", "model", "label", "code",
              "text", "identity", "type", "action", "out"):
        ap.add_argument("--" + k)
    ap.add_argument("--revision", type=int)
    ap.add_argument("--from", dest="frm", type=int)
    ap.add_argument("--to", type=int)
    a = ap.parse_args()
    store = rg.Store(a.eng_root, a.gen_root)
    res = {"step": "revision_check_" + a.command, "checks": {}}
    try:
        {"diff": cmd_diff, "stability": cmd_stability, "rollback-compare": cmd_rollback, "invalid": cmd_invalid,
         "expect-reject": cmd_expect_reject, "dry-run-check": cmd_dry_run, "repro": cmd_repro,
         "integrity": cmd_integrity}[a.command](a, store, res)
        failed = [k for k, v in res["checks"].items() if v is not True]
        ok = bool(res["checks"]) and not failed
        res["operation_status"] = "PASS" if ok else "FAILED"
        res["reason"] = f"{len(res['checks'])} checks passed" if ok else "failed: " + ", ".join(failed)
    except Exception as ex:
        res["operation_status"], res["reason"] = "FAILED", f"{type(ex).__name__}: {ex}"
    Path(a.result).parent.mkdir(parents=True, exist_ok=True)
    Path(a.result).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(res["operation_status"], res["reason"])
    return 0 if res["operation_status"] == "PASS" else 20


if __name__ == "__main__":
    sys.exit(main())
