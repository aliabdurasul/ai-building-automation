# S1-FIX harness: generator -> CODESYS project (Ethernet/Modbus_TCP_Server) -> build ->
# fresh-process verify -> deploy preflight -> deploy -> external pymodbus verification.
# Records process exit code and engineering operation status separately; downstream steps
# of a FAILED/BLOCKED step are recorded as NOT_RUN. Credentials are never printed.
param(
    [Parameter(Mandatory = $true)][ValidateSet("run1", "run2", "run3", "run4")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Src      = Join-Path $Repo "phase0\s1fix"
$Stage    = "C:\AI_BMS_PHASE0\s1fix\$Run"
$Logs     = Join-Path $Stage "logs"
$Ev       = Join-Path $Stage "evidence"
$RepoEv   = Join-Path $Repo "docs\phase0\s1fix_evidence\$Run"
$Codesys  = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile  = "CODESYS V3.5 SP22 Patch 3"
$Service  = "CODESYS Control Win V3 - x64"
$py       = (Get-Command python).Source

if (Test-Path $Stage) { throw "Staging not clean: $Stage exists" }
New-Item -ItemType Directory -Force -Path $Stage, $Logs, $Ev, $RepoEv | Out-Null
$env:S1FIX_STAGE = $Stage

$steps = New-Object System.Collections.ArrayList

function Listening([int]$port) { [bool](@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }).Count) }

function Port-Owner([int]$port) {
    $c = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port })
    if ($c.Count) { return [int]$c[0].OwningProcess }
    return $null
}

function Runtime-Pid {
    $s = Get-CimInstance Win32_Service | Where-Object { $_.Name -eq $Service -or $_.DisplayName -eq $Service } | Select-Object -First 1
    if ($s -and $s.ProcessId) { return [int]$s.ProcessId }
    return $null
}

$ReplaceRuntimeApp = ($env:S1FIX_REPLACE_RUNTIME_APP -eq "1")

function Read-Result([string]$file) {
    if (Test-Path $file) { return (Get-Content $file -Raw | ConvertFrom-Json) }
    return $null
}

function Invoke-Step {
    param([string]$Id, [string]$Exe, [string]$Arguments, [int]$TimeoutSec, [string]$ResultFile, [string[]]$Artifacts)
    $out = Join-Path $Ev "$Id.stdout.txt"; $err = Join-Path $Ev "$Id.stderr.txt"
    $start = Get-Date
    Write-Host "[$Id] start"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe; $psi.Arguments = $Arguments; $psi.WorkingDirectory = $Stage
    $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
    $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) { & taskkill.exe /PID $p.Id /T /F | Out-Null; $p.WaitForExit(15000) | Out-Null }
    $exit = $null; try { $exit = $p.ExitCode } catch {}
    [System.IO.File]::WriteAllText($out, $so.Result); [System.IO.File]::WriteAllText($err, $se.Result)
    $end = Get-Date
    $r = Read-Result $ResultFile
    $op = if ($timedOut) { "FAILED" } elseif ($r -and $r.operation_status) { $r.operation_status } else { "FAILED" }
    $reason = if ($timedOut) { "timeout after $TimeoutSec s" } elseif ($r) { $r.reason } else { "no result file written" }
    $rec = [ordered]@{
        step = $Id; status = $op; timestamp = $start.ToString("o")
        duration_seconds = [math]::Round(($end - $start).TotalSeconds, 1)
        command = "`"$Exe`" $Arguments"; process_exit_code = $exit; timed_out = $timedOut
        operation_status = $op; reason = $reason; result_file = $ResultFile
        artifacts = @($Artifacts | Where-Object { Test-Path $_ }); stdout = $out; stderr = $err
        manual_intervention = $false; notes = ""
    }
    [void]$steps.Add($rec)
    Write-Host "[$Id] exit=$exit op=$op reason=$reason"
    return $rec
}

function Add-Record([string]$Id, [string]$Status, [string]$Reason, $Data) {
    $rec = [ordered]@{ step = $Id; status = $Status; timestamp = (Get-Date).ToString("o"); duration_seconds = $null
        command = $null; process_exit_code = $null; operation_status = $Status; reason = $Reason; data = $Data
        artifacts = @(); manual_intervention = $false; notes = "" }
    [void]$steps.Add($rec)
    Write-Host "[$Id] $Status $Reason"
    return $rec
}

function Write-NotRun([string]$file, [string]$step, [string]$why) {
    ([ordered]@{ step = $step; operation_status = "NOT_RUN"; reason = $why } | ConvertTo-Json) | Out-File -Encoding utf8 $file
}

function Cred-Present {
    foreach ($pair in @(@("CODESYS_USER", "CODESYS_PASSWORD"), @("CODESYS_DEMO_USER", "CODESYS_DEMO_PASS"))) {
        foreach ($n in $pair) {
            if (-not [Environment]::GetEnvironmentVariable($n, "Process")) {
                $v = [Environment]::GetEnvironmentVariable($n, "User")
                if ($v) { [Environment]::SetEnvironmentVariable($n, $v, "Process") }
            }
        }
        if ([Environment]::GetEnvironmentVariable($pair[0], "Process") -and [Environment]::GetEnvironmentVariable($pair[1], "Process")) { return $pair -join "/" }
    }
    return $null
}

# ---------- F00 preflight ----------
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add-Record "F00_preflight" "INFO" "environment facts" ([ordered]@{
    elevated = $elevated; softplc_service = (Get-Service $Service).Status.ToString()
    tcp_502 = Listening 502; tcp_11740 = Listening 11740; tcp_1217 = Listening 1217
    mcp_used = $false; temp_patch_used = $false; gui_automation_used = $false }) | Out-Null

$cdsArgs = "--culture=en --profile=`"$Profile`" --noUI --runscript="

# ---------- F01 generate ----------
$f01 = Invoke-Step "F01_generate" $py "`"$Src\generator\generate.py`" --model `"$Src\model\ahu01.json`" --stage `"$Stage`"" 60 `
    (Join-Path $Logs "generate_result.json") @("$Stage\generated\PLC_PRG.st", "$Stage\engineering\modbus_mapping.json", "$Stage\engineering\codesys_plan.json")

$gate = $f01.operation_status -eq "PASS"; $gateWhy = "F01_generate $($f01.operation_status)"

# ---------- F02 create + Modbus server + mapping + build ----------
if ($gate) {
    $f02 = Invoke-Step "F02_codesys_create_build" $Codesys ($cdsArgs + "`"$Src\codesys\create_project.py`"") 400 `
        (Join-Path $Logs "create_result.json") @("$Stage\generated\AI_BMS_AHU_DEMO.project", "$Stage\generated\AI_BMS_AHU_DEMO.app", "$Logs\build.log")
    $gate = $f02.operation_status -eq "PASS"; $gateWhy = "F02_codesys_create_build $($f02.operation_status)"
} else { Add-Record "F02_codesys_create_build" "NOT_RUN" $gateWhy $null | Out-Null }

# ---------- F03 fresh-process verify ----------
if ($gate) {
    $f03 = Invoke-Step "F03_codesys_verify" $Codesys ($cdsArgs + "`"$Src\codesys\verify_project.py`"") 300 `
        (Join-Path $Logs "verify_result.json") @("$Logs\verify.log")
    $gate = $f03.operation_status -eq "PASS"; $gateWhy = "F03_codesys_verify $($f03.operation_status)"
} else { Add-Record "F03_codesys_verify" "NOT_RUN" $gateWhy $null | Out-Null }

# ---------- F04 deployment preflight ----------
if ($gate) {
    $credSrc = Cred-Present
    $pf = [ordered]@{
        runtime_service_running = ((Get-Service $Service).Status.ToString() -eq "Running")
        runtime_port_11740_listening = Listening 11740
        gateway_port_1217_listening = Listening 1217
        credentials_available = [bool]$credSrc
        credentials_source = $credSrc
        tcp_502_free_before_deploy = -not (Listening 502)
        tcp_502_owner_pid = Port-Owner 502
        runtime_service_pid = Runtime-Pid
        replace_runtime_app_consent = $ReplaceRuntimeApp
        elevated = $elevated
    }
    $pf.tcp_502_owned_by_runtime = ($pf.tcp_502_owner_pid -ne $null -and $pf.tcp_502_owner_pid -eq $pf.runtime_service_pid)
    $missing = @()
    if (-not $pf.runtime_service_running) { $missing += "PRECONDITION: Administrator privileges required to start $Service (service is Stopped; session elevated=$elevated)" }
    if (-not $pf.runtime_port_11740_listening) { $missing += "runtime not reachable (tcp/11740 not listening)" }
    if (-not $pf.gateway_port_1217_listening) { $missing += "gateway not reachable (tcp/1217 not listening)" }
    if (-not $pf.credentials_available) { $missing += "CODESYS credentials not available (CODESYS_USER/CODESYS_PASSWORD not set)" }
    if (-not $pf.tcp_502_free_before_deploy) {
        if ($pf.tcp_502_owned_by_runtime -and $ReplaceRuntimeApp) {
            $pf.note = "tcp/502 held by the existing runtime application; owner consented to replacing it (S1FIX_REPLACE_RUNTIME_APP=1)"
        } elseif ($pf.tcp_502_owned_by_runtime) {
            $missing += "tcp/502 held by an existing runtime application; replacing it requires S1FIX_REPLACE_RUNTIME_APP=1"
        } else {
            $missing += "tcp/502 already in use by a non-CODESYS process (pid $($pf.tcp_502_owner_pid))"
        }
    }
    $st = if ($missing.Count) { "BLOCKED" } else { "PASS" }
    Add-Record "F04_deploy_preflight" $st ($(if ($missing.Count) { $missing -join "; " } else { "all prerequisites present" })) $pf | Out-Null
    $gate = $st -eq "PASS"; $gateWhy = "F04_deploy_preflight $st"
} else { Add-Record "F04_deploy_preflight" "NOT_RUN" $gateWhy $null | Out-Null }

# ---------- F05 deploy ----------
if ($gate) {
    $f05 = Invoke-Step "F05_deploy" $Codesys ($cdsArgs + "`"$Src\codesys\deploy.py`"") 300 (Join-Path $Logs "deployment_result.json") @("$Logs\deployment.log")
    $gate = $f05.operation_status -eq "PASS"; $gateWhy = "F05_deploy $($f05.operation_status)"
    if ($gate) {
        $dr = Read-Result (Join-Path $Logs "deployment_result.json")
        $deadline = (Get-Date).AddSeconds(15)
        while (-not (Listening 502) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
        $rv = [ordered]@{
            application_state = $dr.application_state
            generated_variables_online = [bool]($dr.online_values -and $dr.online_values.'PLC_PRG.Mb_Status' -ne $null -and $dr.online_values.'PLC_PRG.Mb_Command' -ne $null)
            tcp_502_listening = Listening 502
            tcp_502_owner_pid = Port-Owner 502
            runtime_service_pid = Runtime-Pid
        }
        $rv.tcp_502_owned_by_runtime = ($rv.tcp_502_owner_pid -ne $null -and $rv.tcp_502_owner_pid -eq $rv.runtime_service_pid)
        $ok = ("$($rv.application_state)".ToLower() -eq "run") -and $rv.generated_variables_online -and $rv.tcp_502_owned_by_runtime
        $why = if ($ok) { "generated app in RUN, its variables readable online, tcp/502 owned by runtime" } else { "runtime verification failed" }
        Add-Record "F05b_runtime_verify" ($(if ($ok) { "PASS" } else { "FAILED" })) $why $rv | Out-Null
        $gate = $ok; $gateWhy = "F05b_runtime_verify $(if ($ok) { 'PASS' } else { 'FAILED' })"
    }
} else {
    Add-Record "F05_deploy" "NOT_RUN" $gateWhy $null | Out-Null
    Write-NotRun (Join-Path $Logs "deployment_result.json") "deploy" $gateWhy
    "NOT_RUN: $gateWhy" | Out-File -Encoding utf8 (Join-Path $Logs "deployment.log")
}

# ---------- F06 external Modbus verification ----------
if ($gate) {
    $f06 = Invoke-Step "F06_modbus_probe" $py "`"$Src\probe\modbus_probe.py`" --stage `"$Stage`"" 90 (Join-Path $Logs "modbus_probe.json") @("$Logs\modbus_probe.json")
} else {
    Add-Record "F06_modbus_probe" "NOT_RUN" $gateWhy ([ordered]@{ tcp_502_listening = Listening 502 }) | Out-Null
    Write-NotRun (Join-Path $Logs "modbus_probe.json") "modbus_probe" $gateWhy
}

# ---------- F07 post state ----------
Add-Record "F07_post_state" "INFO" "post-run facts" ([ordered]@{
    softplc_service = (Get-Service $Service).Status.ToString(); tcp_502 = Listening 502
    codesys_left_running = @(Get-Process CODESYS -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) }) | Out-Null

$obj = [ordered]@{ run = $Run; stage = $Stage; steps = $steps }
$obj | ConvertTo-Json -Depth 8 | Out-File -Encoding utf8 (Join-Path $Ev "harness_$Run.json")

foreach ($d in "logs", "evidence", "engineering") { Copy-Item (Join-Path $Stage $d) (Join-Path $RepoEv $d) -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $RepoEv "generated") | Out-Null
Copy-Item "$Stage\generated\*.st" (Join-Path $RepoEv "generated") -ErrorAction SilentlyContinue
Write-Host "DONE $Run"
