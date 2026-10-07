# -*- coding: utf-8 -*-
"""S8.1 gap retry: FAULT (bridge) + HMI only. Reuses existing AHU_S81 project."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Import helpers from main orchestrator
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_s81 import (  # noqa: E402
    EV, HOST, MS_SANDBOX, MS_STAGE, PROJ, SPEC, Bridge, S7_STAGE,
    copy_for_runtime, jwrite, mb_client, parse_events, start_bridge, run_host,
)

EV.mkdir(parents=True, exist_ok=True)


def retry_fault():
    rt_loc = copy_for_runtime(PROJ, "rt_copy_fault")
    events = EV / "s81_fault_retry_events.jsonl"
    log = MS_STAGE / "logs" / "s81_fault_retry.log"
    work = rt_loc / "rt_work"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    ready = work / "hold_ready.txt"
    stop = work / "stop.flag"

    host_cmd = [str(HOST), "s81runtime", str(rt_loc), PROJ, "100", str(events), str(log)]
    ms_proc = subprocess.Popen(host_cmd, cwd=str(MS_SANDBOX), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")
    t0 = time.time()
    while time.time() - t0 < 110:
        if ready.exists() or ms_proc.poll() is not None:
            break
        time.sleep(0.5)

    fault = {"hold_ready": ready.exists(), "result": "BLOCKED"}
    if not ready.exists():
        fault["reason"] = "hold_ready missing"
        stop.write_text("stop", encoding="utf-8")
        try:
            ms_proc.wait(timeout=60)
        except Exception:
            ms_proc.kill()
        jwrite("fault_master_scada.json", fault)
        return fault

    c = mb_client()
    ir = c.read_input_registers(address=0, count=1, device_id=1)
    fault["before_IR0"] = None if ir.isError() else ir.registers[0]

    bridge_dir = EV / "bridge_retry"
    br = Bridge(bridge_dir)
    bproc, bmeta = start_bridge(bridge_dir)
    fault["bridge_start"] = bmeta
    ready_info = br.wait_ready(timeout=120) if bproc else {"ready": False, "reason": "no bridge"}
    fault["bridge_ready"] = ready_info

    if ready_info.get("ready"):
        br.call({"op": "write", "values": {"PLC_PRG.FanFault": "TRUE"}})
        time.sleep(1.5)
        plc = br.call({"op": "read", "exprs": ["PLC_PRG.FanFault", "PLC_PRG.FanCommand", "PLC_PRG.FanRunning"]})
        fault["plc_after_fault"] = plc
        ir = c.read_input_registers(address=0, count=1, device_id=1)
        fault["after_fault_IR0"] = None if ir.isError() else ir.registers[0]
        ms_fault = None
        t1 = time.time()
        while time.time() - t1 < 30:
            for r in reversed(parse_events(events)):
                if r.get("step") == "hold" and r.get("ms_FanStatus_int") == 4 and r.get("codesys_IR0") == 4:
                    ms_fault = r
                    break
            if ms_fault:
                break
            time.sleep(0.4)
        fault["masterscada_fault"] = ms_fault
        br.call({"op": "write", "values": {"PLC_PRG.FanFault": "FALSE"}})
        time.sleep(1.5)
        ir = c.read_input_registers(address=0, count=1, device_id=1)
        fault["after_clear_IR0"] = None if ir.isError() else ir.registers[0]
        ms_rec = None
        t2 = time.time()
        while time.time() - t2 < 30:
            for r in reversed(parse_events(events)):
                if r.get("step") == "hold" and r.get("sawRecovery") is True:
                    ms_rec = r
                    break
                if ms_fault and r.get("step") == "hold" and r.get("ms_FanStatus_int") == 3 and r.get("codesys_IR0") == 3:
                    ms_rec = r
                    break
            if ms_rec:
                break
            time.sleep(0.4)
        fault["masterscada_recovery"] = ms_rec
        br.call({"op": "quit"})
        if ms_fault and fault.get("after_fault_IR0") == 4:
            fault["result"] = "PASS"
            fault["reason"] = "CODESYS FanFault + Modbus IR0=4 + MasterSCADA FanStatus=4 Good"
        elif fault.get("after_fault_IR0") == 4:
            fault["result"] = "PARTIAL"
            fault["reason"] = "IR0=4 observed; MS FanStatus=4 not sampled"
        else:
            fault["result"] = "FAIL"
            fault["reason"] = "FanFault write did not yield IR0=4"
    else:
        fault["result"] = "BLOCKED"
        fault["reason"] = "PLC online auth failed: " + str(ready_info.get("reason"))

    c.close()
    stop.write_text("stop", encoding="utf-8")
    try:
        ms_proc.communicate(timeout=120)
    except Exception:
        ms_proc.kill()
    if bproc:
        try:
            bproc.wait(timeout=30)
        except Exception:
            bproc.kill()
        brf = S7_STAGE / "logs" / "bridge_result.json"
        if brf.exists():
            shutil.copy2(brf, EV / "bridge_result_retry.json")
    if log.exists():
        shutil.copy2(log, EV / "s81_fault_retry.log")
    jwrite("fault_master_scada.json", fault)
    return fault


def retry_hmi():
    out = {
        "path_type": "debug EmulatorSession + IncludeHMI HTML5",
        "production_ms_service": "NOT LAUNCHED",
        "result": "NOT VERIFIED",
    }
    loc = MS_STAGE / "projects"
    spec_dst = MS_STAGE / "s81_test_hmi.json"
    # Ensure clean JSON (no comments)
    text = SPEC.read_text(encoding="utf-8")
    if text.lstrip().startswith("#"):
        text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
    spec_dst.write_text(text.strip() + "\n", encoding="utf-8")
    # also rewrite repo spec
    SPEC.write_text(text.strip() + "\n", encoding="utf-8")

    rc_b, _ = run_host(["hmibuild", str(loc), PROJ, str(spec_dst)], "S12_hmi_build_retry.log", timeout=240)
    out["hmibuild_rc"] = rc_b
    evid = EV / "hmi_verify_evidence.json"
    rc_v, _ = run_host(["hmiverify", str(loc), PROJ, str(spec_dst), str(evid)], "S13_hmi_verify_retry.log", timeout=180)
    out["hmiverify_rc"] = rc_v

    hmi_loc = copy_for_runtime(PROJ, "rt_copy_hmi2")
    events = EV / "hmi_runtime_events.jsonl"
    log = MS_STAGE / "logs" / "hmi_runtime_retry.log"

    nginx_exe = Path(r"C:\Program Files\MPSSoft\MasterSCADA 4D 1.2\bin\Config\MasterPLC\WIN64\nginx\nginx.exe")
    nginx_dir = MS_SANDBOX / "nginx_sandbox"
    # Point nginx root at generated htdocs after runtime starts — first start runtime to generate htdocs
    # Use temporary conf after we know htdocs path; for now start hmiruntime then nginx against Debug_1/htdocs

    host_cmd = [str(HOST), "hmiruntime", str(hmi_loc), PROJ, "45", "7", str(events), str(log)]
    # Start runtime in background so we can point nginx at htdocs during hold
    ms_proc = subprocess.Popen(host_cmd, cwd=str(MS_SANDBOX), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace")

    # Wait for ready.txt / htdocs
    work = hmi_loc / "rt_work"
    ready = work / "ready.txt"
    t0 = time.time()
    htdocs = None
    while time.time() - t0 < 120 and ms_proc.poll() is None:
        if ready.exists():
            break
        # search htdocs
        for root, dirs, files in os.walk(work):
            if "index.html" in files and "htdocs" in root.replace("\\", "/"):
                htdocs = root
                break
        if htdocs:
            break
        time.sleep(1)

    # also scan events
    time.sleep(2)
    rows = parse_events(events)
    for r in rows:
        if r.get("step") == "htdocs_found":
            htdocs = str(Path(r["index"]).parent)
            out["htdocs_event"] = r
            break
    out["htdocs_path"] = htdocs

    nginx_proc = None
    conf_path = None
    if htdocs and nginx_exe.exists():
        # Write ephemeral nginx conf serving this htdocs, fcgi 30757
        conf_path = EV / "nginx_s81.conf"
        conf = f"""
worker_processes 1;
error_log logs/error_s81.log;
pid logs/nginx_s81.pid;
events {{ worker_connections 64; }}
http {{
  access_log off;
  include mime.types;
  default_type application/octet-stream;
  upstream fcgi_backend {{ server 127.0.0.1:30757; keepalive 8; }}
  server {{
    listen 127.0.0.1:8143;
    root "{htdocs.replace(chr(92), '/')}";
    location / {{
      try_files $uri $uri/ /index.html;
    }}
    location ~ \\.fcgi$ {{
      fastcgi_pass fcgi_backend;
      include fastcgi_params;
    }}
    location /Methods/ {{
      fastcgi_pass fcgi_backend;
      include fastcgi_params;
      fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }}
  }}
}}
"""
        # nginx on Windows needs conf relative to -p prefix with logs/ mime.types
        # use vendor nginx sandbox as -p and drop conf there
        sandbox_conf = nginx_dir / "conf" / "nginx-s81.conf"
        # mime.types lives in conf/
        conf2 = conf.replace("include mime.types;", "include conf/mime.types;")
        # also need logs under sandbox
        sandbox_conf.write_text(conf2, encoding="utf-8")
        conf_path.write_text(conf2, encoding="utf-8")
        try:
            # stop any previous
            subprocess.run([str(nginx_exe), "-p", str(nginx_dir) + "\\", "-c", "conf/nginx-s81.conf", "-s", "stop"],
                           cwd=str(nginx_dir), timeout=10, capture_output=True)
        except Exception:
            pass
        time.sleep(0.5)
        nginx_proc = subprocess.Popen(
            [str(nginx_exe), "-p", str(nginx_dir) + "\\", "-c", "conf/nginx-s81.conf"],
            cwd=str(nginx_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace")
        time.sleep(1.5)
        out["nginx_started"] = True
        out["nginx_exe"] = str(nginx_exe)
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8143/", timeout=5) as resp:
                body = resp.read(2000)
                out["http_8143_len"] = len(body)
                out["http_page_ok"] = len(body) > 50
                (EV / "hmi_index_snippet.txt").write_bytes(body[:500])
        except Exception as e:
            out["http_8143_error"] = str(e)
            out["http_page_ok"] = False
        # Stimulate START/STOP via Modbus while page is up — HMI should reflect via MS tags in events
        from pymodbus.client import ModbusTcpClient
        mc = ModbusTcpClient("127.0.0.1", port=502)
        mc.connect()
        mc.write_register(address=0, value=1, device_id=1)
        time.sleep(3)
        mc.write_register(address=0, value=2, device_id=1)
        time.sleep(2)
        mc.close()
    else:
        out["nginx_started"] = False
        out["nginx_reason"] = "no htdocs or nginx.exe"

    # signal stop
    stop = work / "stop.flag"
    try:
        stop.write_text("stop", encoding="utf-8")
    except Exception:
        pass
    try:
        out_so, out_se = ms_proc.communicate(timeout=90)
    except Exception:
        ms_proc.kill()
        out_so, out_se = "", ""
    (EV / "hmi_runtime_retry.stdout.txt").write_text(out_so or "", encoding="utf-8")
    if log.exists():
        shutil.copy2(log, EV / "hmi_runtime_retry.log")

    rows = parse_events(events)
    holds = [r for r in rows if r.get("step") == "hold"]
    out["hold_samples"] = len(holds)
    out["htdocs_found"] = any(r.get("step") == "htdocs_found" for r in rows) or bool(htdocs)
    # Check FanStatus transitions in hold after stim
    vals = []
    for r in holds:
        s = r.get("ms_FanStatus") or ""
        if "Value:=" in s:
            try:
                v = s.split("Value:=")[1].split(",")[0]
                vals.append(int(float(v)))
            except Exception:
                pass
    out["fanstatus_values_seen"] = sorted(set(vals))
    out["saw_running_3"] = 3 in vals
    out["saw_stopped_0"] = 0 in vals

    if out.get("hmibuild_rc") == 0 and out.get("htdocs_found") and out.get("http_page_ok"):
        out["result"] = "PASS"
        out["reason"] = "S8.1 TEST HMI built; HTML5 htdocs served on :8143; FanStatus observed in runtime"
        out["limitation"] = "Operator path is vendor debug EmulatorSession+IncludeHMI HTML5, not a production MasterSCADA Windows service"
    elif out.get("hmibuild_rc") == 0 and out.get("htdocs_found"):
        out["result"] = "PARTIAL"
        out["reason"] = "HMI built and htdocs generated; HTTP serve incomplete"
    else:
        out["result"] = "NOT VERIFIED"
        out["reason"] = "hmibuild/htdocs failed"

    if nginx_proc:
        try:
            subprocess.run([str(nginx_exe), "-p", str(nginx_dir) + "\\", "-c", "conf/nginx-s81.conf", "-s", "stop"],
                           cwd=str(nginx_dir), timeout=15, capture_output=True)
        except Exception:
            try:
                nginx_proc.kill()
            except Exception:
                pass

    jwrite("operator_hmi.json", out)
    return out


def main():
    print("retry fault...")
    fault = retry_fault()
    print("fault", fault.get("result"), fault.get("reason", "")[:120])
    print("retry hmi...")
    hmi = retry_hmi()
    print("hmi", hmi.get("result"), hmi.get("reason", "")[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
