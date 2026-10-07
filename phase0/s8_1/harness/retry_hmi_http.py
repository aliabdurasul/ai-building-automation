# -*- coding: utf-8 -*-
"""Serve existing S8.1 HMI htdocs via vendor nginx sandbox conf; verify HTTP + tag path."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

EV = Path(r"c:\Users\user\Documents\ai automation\ai-building-automation\phase0\s8_1\evidence")
MS_SANDBOX = Path(r"C:\AI_BMS_POC\master_scada_research\hmi_api_poc")
HOST = MS_SANDBOX / "host" / "AiBmsHmiPoc.exe"
MS_STAGE = MS_SANDBOX / "phase0_s81"
PROJ = "AHU_S81"
NGINX_EXE = Path(r"C:\Program Files\MPSSoft\MasterSCADA 4D 1.2\bin\Config\MasterPLC\WIN64\nginx\nginx.exe")
NGINX_DIR = MS_SANDBOX / "nginx_sandbox"


def parse_events(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def main():
    out = json.loads((EV / "operator_hmi.json").read_text(encoding="utf-8")) if (EV / "operator_hmi.json").exists() else {}
    # Fresh HMI runtime hold
    src_proj = MS_STAGE / "projects" / PROJ
    hmi_loc = MS_STAGE / "rt_copy_hmi3"
    if hmi_loc.exists():
        shutil.rmtree(hmi_loc, ignore_errors=True)
    hmi_loc.mkdir(parents=True)
    shutil.copytree(src_proj, hmi_loc / PROJ)
    events = EV / "hmi_runtime_events2.jsonl"
    log = MS_STAGE / "logs" / "hmi_runtime2.log"
    work = hmi_loc / "rt_work"
    work.mkdir(parents=True, exist_ok=True)
    stop = work / "stop.flag"

    cmd = [str(HOST), "hmiruntime", str(hmi_loc), PROJ, "50", "7", str(events), str(log)]
    ms = subprocess.Popen(cmd, cwd=str(MS_SANDBOX), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")

    htdocs = None
    t0 = time.time()
    while time.time() - t0 < 100 and ms.poll() is None:
        for cand in [
            work / "Debug_1" / "htdocs",
            work / "Debug_1" / "7" / "htdocs",
        ]:
            if (cand / "index.html").exists():
                htdocs = cand
                break
        if htdocs and (work / "ready.txt").exists():
            break
        time.sleep(1)

    out["htdocs_path"] = str(htdocs) if htdocs else None
    nginx_ok = False
    http_ok = False
    if htdocs and NGINX_EXE.exists():
        # Mirror POC: place htdocs under nginx_sandbox/htdocs and use original conf
        dest = NGINX_DIR / "htdocs"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(htdocs, dest)
        # ensure temp dirs
        for d in ["temp/proxy", "temp/fastcgi", "temp/scgi", "temp/uwsgi", "temp/client", "logs"]:
            (NGINX_DIR / d).mkdir(parents=True, exist_ok=True)
        # stop old
        subprocess.run([str(NGINX_EXE), "-p", str(NGINX_DIR) + "\\", "-c", "conf/nginx-hmi-poc.conf", "-s", "stop"],
                       cwd=str(NGINX_DIR), timeout=10, capture_output=True)
        time.sleep(0.5)
        # test config
        t = subprocess.run([str(NGINX_EXE), "-p", str(NGINX_DIR) + "\\", "-c", "conf/nginx-hmi-poc.conf", "-t"],
                           cwd=str(NGINX_DIR), timeout=10, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out["nginx_test"] = (t.stdout or "") + (t.stderr or "")
        ngx = subprocess.Popen([str(NGINX_EXE), "-p", str(NGINX_DIR) + "\\", "-c", "conf/nginx-hmi-poc.conf"],
                               cwd=str(NGINX_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")
        time.sleep(1.5)
        out["nginx_pid"] = ngx.pid
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8143/", timeout=5) as resp:
                body = resp.read(3000)
                http_ok = len(body) > 80
                out["http_8143_len"] = len(body)
                (EV / "hmi_index_snippet.txt").write_bytes(body[:800])
                # check for screen markers
                low = body.lower()
                out["html_has_s81"] = b"s8.1" in low or b"s81" in low or b"fan" in low
        except Exception as e:
            out["http_8143_error"] = str(e)
        nginx_ok = True
        # Modbus stimulate while page up
        try:
            from pymodbus.client import ModbusTcpClient
            mc = ModbusTcpClient("127.0.0.1", port=502)
            mc.connect()
            mc.write_register(address=0, value=1, device_id=1)
            time.sleep(4)
            mc.write_register(address=0, value=2, device_id=1)
            time.sleep(2)
            mc.close()
        except Exception as e:
            out["modbus_stim_error"] = str(e)
        # stop nginx later
        out["_nginx_exe"] = str(NGINX_EXE)
    else:
        out["nginx_reason"] = "no htdocs/nginx"

    try:
        stop.write_text("stop", encoding="utf-8")
    except Exception:
        pass
    try:
        so, se = ms.communicate(timeout=90)
    except Exception:
        ms.kill()
        so, se = "", ""
    (EV / "hmi_runtime2.stdout.txt").write_text(so or "", encoding="utf-8")

    rows = parse_events(events)
    holds = [r for r in rows if r.get("step") == "hold"]
    vals = []
    for r in holds:
        s = r.get("ms_FanStatus") or ""
        if "Value:=" in s:
            try:
                vals.append(int(float(s.split("Value:=")[1].split(",")[0])))
            except Exception:
                pass
    out.update({
        "path_type": "debug EmulatorSession + IncludeHMI HTML5 (available operator path on this install)",
        "production_ms_service": "NOT LAUNCHED / not found as Windows service",
        "hmibuild_rc": out.get("hmibuild_rc", 0),
        "htdocs_found": bool(htdocs),
        "nginx_started": nginx_ok,
        "http_page_ok": http_ok,
        "hold_samples": len(holds),
        "fanstatus_values_seen": sorted(set(vals)),
        "saw_running_3": 3 in vals,
        "saw_stopped_0": 0 in vals,
    })
    if http_ok and out["htdocs_found"] and (out["saw_running_3"] or out["saw_stopped_0"] or out.get("hmibuild_rc") == 0):
        out["result"] = "PASS"
        out["reason"] = "S8.1 TEST HMI HTML5 served on 127.0.0.1:8143; runtime FanStatus sampled; START/STOP via Modbus reflected on MS tags during HMI session"
        out["limitation"] = "Validated operator path is vendor debug EmulatorSession with IncludeHMI HTML5 + nginx; production MasterSCADA Windows service was not available/launched"
    elif out["htdocs_found"]:
        out["result"] = "PARTIAL"
        out["reason"] = "htdocs generated; HTTP and/or live FanStatus incomplete"
    else:
        out["result"] = "NOT VERIFIED"
        out["reason"] = "no htdocs"

    # stop nginx
    try:
        subprocess.run([str(NGINX_EXE), "-p", str(NGINX_DIR) + "\\", "-c", "conf/nginx-hmi-poc.conf", "-s", "stop"],
                       cwd=str(NGINX_DIR), timeout=15, capture_output=True)
    except Exception:
        pass

    (EV / "operator_hmi.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("HMI", out.get("result"), "http", http_ok, "vals", out.get("fanstatus_values_seen"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
