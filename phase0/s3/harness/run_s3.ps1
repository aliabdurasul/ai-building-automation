# S3 harness: canonical model -> engine self-test -> per profile (types, ahu):
#   generate (validate + allocate) -> CODESYS create + mapping + build -> fresh-process verify ->
#   deploy preflight -> deploy -> runtime verify -> S1 regression (pymodbus) ->
#   typed verification (pymodbus + PLC online read-back via the S3 bridge).
# Reuses the S1-FIX CODESYS adapter scripts. Process exit code and operation status are recorded
# separately; downstream steps of a FAILED/BLOCKED step are NOT_RUN. Credentials are never printed.
param(
    [Parameter(Mandatory = $true)][ValidatePattern("^(run|dev)\d+$")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Src      = Join-Path $Repo "phase0\s3"
$S1       = Join-Path $Repo "phase0\s1fix"
$Model    = Join-Path $Src "model\s3_model.json"
$RunRoot  = "C:\AI_BMS_PHASE0\s3\$Run"
$RepoRun  = Join-Path $Repo "docs\phase0\s3_evidence\$Run"
$Codesys  = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile  = "CODESYS V3.5 SP22 Patch 3"
$Service  = "CODESYS Control Win V3 - x64"
$Profiles = @("types", "ahu")
$py       = (Get-Command python).Source
$cdsArgs  = "--culture=en --profile=`"$Profile`" --noUI --runscript="

if (Test-Path $RunRoot) { throw "Staging not clean: $RunRoot exists" }
New-Item -ItemType Directory -Force -Path $RunRoot, (Join-Path $RunRoot "logs"), (Join-Path $RunRoot "evidence"), $RepoRun | Out-Null
$Stage = $RunRoot; $Logs = Join-Path $RunRoot "logs"; $Ev = Join-Path $RunRoot "evidence"; $Prefix = ""

$steps = New-Object System.Collections.ArrayList
$ReplaceRuntimeApp = ($env:S1FIX_REPLACE_RUNTIME_APP -eq "1")

function Listening([int]$port) { [bool](@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }).Count) }
function Port-Owner([int]$port) {
    $c = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port })
    if ($c.Count) { return [int]$c[0].OwningProcess }; return $null
}
function Runtime-Pid {
    $s = Get-CimInstance Win32_Service | Where-Object { $_.Name -eq $Service -or $_.DisplayName -eq $Service } | Select-Object -First 1
    if ($s -and $s.ProcessId) { return [int]$s.ProcessId }; return $null
}
function Read-Result([string]$file) { if (Test-Path $file) { return (Get-Content $file -Raw | ConvertFrom-Json) }; return $null }

function Start-Proc([string]$Exe, [string]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe; $psi.Arguments = $Arguments; $psi.WorkingDirectory = $Stage
    $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    return @{ p = $p; so = $p.StandardOutput.ReadToEndAsync(); se = $p.StandardError.ReadToEndAsync() }
}

function Stop-Proc($h, [int]$TimeoutSec, [string]$Id) {
    $timedOut = -not $h.p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) { & taskkill.exe /PID $h.p.Id /T /F | Out-Null; $h.p.WaitForExit(15000) | Out-Null }
    $exit = $null; try { $exit = $h.p.ExitCode } catch {}
    [System.IO.File]::WriteAllText((Join-Path $Ev "$Id.stdout.txt"), $h.so.Result)
    [System.IO.File]::WriteAllText((Join-Path $Ev "$Id.stderr.txt"), $h.se.Result)
    return @{ exit = $exit; timedOut = $timedOut }
}

function Add-StepRecord([string]$Id, $start, $x, [string]$Exe, [string]$Arguments, [string]$ResultFile, [int]$TimeoutSec) {
    $r = Read-Result $ResultFile
    $op = if ($x.timedOut) { "FAILED" } elseif ($r -and $r.operation_status) { $r.operation_status } else { "FAILED" }
    $reason = if ($x.timedOut) { "timeout after $TimeoutSec s" } elseif ($r) { $r.reason } else { "no result file written" }
    $rec = [ordered]@{
        step = "$Prefix$Id"; timestamp = $start.ToString("o")
        duration_seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        command = "`"$Exe`" $Arguments"
        process = [ordered]@{ exit_code = $x.exit; timed_out = $x.timedOut }
        operation = [ordered]@{ status = $op; reason = $reason }
        process_exit_code = $x.exit; operation_status = $op; reason = $reason; result_file = $ResultFile
        manual_intervention = $false
    }
    [void]$steps.Add($rec)
    Write-Host "[$Prefix$Id] exit=$($x.exit) op=$op reason=$reason"
    return $rec
}

function Invoke-Step([string]$Id, [string]$Exe, [string]$Arguments, [int]$TimeoutSec, [string]$ResultFile) {
    Write-Host "[$Prefix$Id] start"
    $start = Get-Date
    $h = Start-Proc $Exe $Arguments
    $x = Stop-Proc $h $TimeoutSec $Id
    return Add-StepRecord $Id $start $x $Exe $Arguments $ResultFile $TimeoutSec
}

function Add-Record([string]$Id, [string]$Status, [string]$Reason, $Data) {
    $rec = [ordered]@{ step = "$Prefix$Id"; timestamp = (Get-Date).ToString("o"); duration_seconds = $null; command = $null
        process = [ordered]@{ exit_code = $null; timed_out = $false }; operation = [ordered]@{ status = $Status; reason = $Reason }
        process_exit_code = $null; operation_status = $Status; reason = $Reason; data = $Data; manual_intervention = $false }
    [void]$steps.Add($rec)
    Write-Host "[$Prefix$Id] $Status $Reason"
    return $rec
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

# ---------- F00 preflight + engine self-test (once per run) ----------
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add-Record "F00_preflight" "INFO" "environment facts" ([ordered]@{
    elevated = $elevated; softplc_service = (Get-Service $Service).Status.ToString()
    tcp_502 = Listening 502; tcp_11740 = Listening 11740; tcp_1217 = Listening 1217
    model_sha256 = (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()
    mcp_used = $false; llm_used = $false; temp_patch_used = $false; gui_automation_used = $false; old_poc_used = $false }) | Out-Null
$self = Invoke-Step "F00b_engine_selftest" $py "`"$Src\engine\test_engine.py`" --result `"$Logs\engine_selftest.json`"" 120 (Join-Path $Logs "engine_selftest.json")
$runGate = $self.operation_status -eq "PASS"

foreach ($p in $Profiles) {
    $Stage = Join-Path $RunRoot $p; $Logs = Join-Path $Stage "logs"; $Ev = Join-Path $Stage "evidence"; $Prefix = "$p/"
    New-Item -ItemType Directory -Force -Path $Stage, $Logs, $Ev, (Join-Path $Stage "bridge") | Out-Null
    $env:S1FIX_STAGE = $Stage
    $gate = $runGate; $gateWhy = "F00b_engine_selftest $($self.operation_status)"

    # ---------- F01 generate (validate + allocate) ----------
    if ($gate) {
        $f = Invoke-Step "F01_generate" $py "`"$Src\generator\generate.py`" --model `"$Model`" --profile $p --stage `"$Stage`"" 60 (Join-Path $Logs "generate_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F01_generate $($f.operation_status)"
    } else { Add-Record "F01_generate" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F02 CODESYS create + mapping + build ----------
    if ($gate) {
        $f = Invoke-Step "F02_codesys_create_build" $Codesys ($cdsArgs + "`"$S1\codesys\create_project.py`"") 400 (Join-Path $Logs "create_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F02_codesys_create_build $($f.operation_status)"
    } else { Add-Record "F02_codesys_create_build" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F03 fresh-process verify ----------
    if ($gate) {
        $f = Invoke-Step "F03_codesys_verify" $Codesys ($cdsArgs + "`"$S1\codesys\verify_project.py`"") 300 (Join-Path $Logs "verify_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F03_codesys_verify $($f.operation_status)"
    } else { Add-Record "F03_codesys_verify" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F04 deploy preflight ----------
    if ($gate) {
        $credSrc = Cred-Present
        $pf = [ordered]@{
            runtime_service_running = ((Get-Service $Service).Status.ToString() -eq "Running")
            runtime_port_11740_listening = Listening 11740; gateway_port_1217_listening = Listening 1217
            credentials_available = [bool]$credSrc; credentials_source = $credSrc
            tcp_502_free_before_deploy = -not (Listening 502); tcp_502_owner_pid = Port-Owner 502
            runtime_service_pid = Runtime-Pid; replace_runtime_app_consent = $ReplaceRuntimeApp; elevated = $elevated }
        $pf.tcp_502_owned_by_runtime = ($pf.tcp_502_owner_pid -ne $null -and $pf.tcp_502_owner_pid -eq $pf.runtime_service_pid)
        $missing = @()
        if (-not $pf.runtime_service_running) { $missing += "PRECONDITION: Administrator privileges required to start $Service" }
        if (-not $pf.runtime_port_11740_listening) { $missing += "runtime not reachable (tcp/11740)" }
        if (-not $pf.gateway_port_1217_listening) { $missing += "gateway not reachable (tcp/1217)" }
        if (-not $pf.credentials_available) { $missing += "CODESYS credentials not available (CODESYS_USER/CODESYS_PASSWORD)" }
        if (-not $pf.tcp_502_free_before_deploy) {
            if ($pf.tcp_502_owned_by_runtime -and $ReplaceRuntimeApp) { $pf.note = "tcp/502 held by the runtime; replacing its application is consented (S1FIX_REPLACE_RUNTIME_APP=1)" }
            elseif ($pf.tcp_502_owned_by_runtime) { $missing += "tcp/502 held by a runtime application; replacing it requires S1FIX_REPLACE_RUNTIME_APP=1" }
            else { $missing += "tcp/502 in use by a non-CODESYS process (pid $($pf.tcp_502_owner_pid))" }
        }
        $st = if ($missing.Count) { "BLOCKED" } else { "PASS" }
        Add-Record "F04_deploy_preflight" $st ($(if ($missing.Count) { $missing -join "; " } else { "all prerequisites present" })) $pf | Out-Null
        $gate = $st -eq "PASS"; $gateWhy = "F04_deploy_preflight $st"
    } else { Add-Record "F04_deploy_preflight" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F05 deploy + F05b runtime verify ----------
    if ($gate) {
        $f = Invoke-Step "F05_deploy" $Codesys ($cdsArgs + "`"$S1\codesys\deploy.py`"") 300 (Join-Path $Logs "deployment_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F05_deploy $($f.operation_status)"
        if ($gate) {
            $dr = Read-Result (Join-Path $Logs "deployment_result.json")
            $deadline = (Get-Date).AddSeconds(15)
            while (-not (Listening 502) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
            $rv = [ordered]@{ application_state = $dr.application_state
                generated_variables_online = [bool]($dr.online_values -and $dr.online_values.'PLC_PRG.Mb_Status' -ne $null -and $dr.online_values.'PLC_PRG.Mb_Command' -ne $null)
                tcp_502_listening = Listening 502; tcp_502_owner_pid = Port-Owner 502; runtime_service_pid = Runtime-Pid }
            $rv.tcp_502_owned_by_runtime = ($rv.tcp_502_owner_pid -ne $null -and $rv.tcp_502_owner_pid -eq $rv.runtime_service_pid)
            $ok = ("$($rv.application_state)".ToLower() -eq "run") -and $rv.generated_variables_online -and $rv.tcp_502_owned_by_runtime
            Add-Record "F05b_runtime_verify" ($(if ($ok) { "PASS" } else { "FAILED" })) ($(if ($ok) { "generated app in RUN, variables online, tcp/502 owned by runtime" } else { "runtime verification failed" })) $rv | Out-Null
            $gate = $ok; $gateWhy = "F05b_runtime_verify $(if ($ok) { 'PASS' } else { 'FAILED' })"
        }
    } else { Add-Record "F05_deploy" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F06 S1 regression (pymodbus) ----------
    if ($gate) {
        $f = Invoke-Step "F06_s1_regression" $py "`"$Src\probe\s1_regression.py`" --stage `"$Stage`"" 90 (Join-Path $Logs "s1_regression.json")
    } else { Add-Record "F06_s1_regression" "NOT_RUN" $gateWhy $null | Out-Null }

    # ---------- F07 typed verification (pymodbus + PLC online read-back) ----------
    if ($gate) {
        $env:S3_BRIDGE_DIR = Join-Path $Stage "bridge"
        $bStart = Get-Date
        $bArgs = $cdsArgs + "`"$Src\codesys\plc_online_bridge.py`""
        $bridge = Start-Proc $Codesys $bArgs
        $refArg = if ($p -ne "types") { " --reference `"$(Join-Path $RunRoot 'types\logs\typed_verify.json')`"" } else { "" }
        $f = Invoke-Step "F07_typed_verify" $py ("`"$Src\probe\typed_verify.py`" --stage `"$Stage`"" + $refArg) 600 (Join-Path $Logs "typed_verify.json")
        $bx = Stop-Proc $bridge 90 "F07a_plc_online_bridge"
        Add-StepRecord "F07a_plc_online_bridge" $bStart $bx $Codesys $bArgs (Join-Path $Logs "bridge_result.json") 90 | Out-Null
    } else { Add-Record "F07_typed_verify" "NOT_RUN" $gateWhy $null | Out-Null }
}

$Prefix = ""
Add-Record "F08_post_state" "INFO" "post-run facts" ([ordered]@{
    softplc_service = (Get-Service $Service).Status.ToString(); tcp_502 = Listening 502
    codesys_left_running = @(Get-Process CODESYS -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) }) | Out-Null

$obj = [ordered]@{ run = $Run; stage = $RunRoot; profiles = $Profiles; steps = $steps }
$obj | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 (Join-Path $RunRoot "evidence\harness_$Run.json")

Copy-Item (Join-Path $RunRoot "logs") (Join-Path $RepoRun "logs") -Recurse -Force
Copy-Item (Join-Path $RunRoot "evidence") (Join-Path $RepoRun "evidence") -Recurse -Force
foreach ($p in $Profiles) {
    $dst = Join-Path $RepoRun $p
    New-Item -ItemType Directory -Force -Path $dst, (Join-Path $dst "generated") | Out-Null
    foreach ($d in "logs", "evidence", "engineering") {
        if (Test-Path (Join-Path $RunRoot "$p\$d")) { Copy-Item (Join-Path $RunRoot "$p\$d") (Join-Path $dst $d) -Recurse -Force }
    }
    Copy-Item "$RunRoot\$p\generated\*.st" (Join-Path $dst "generated") -ErrorAction SilentlyContinue
}
Write-Host "DONE $Run"
