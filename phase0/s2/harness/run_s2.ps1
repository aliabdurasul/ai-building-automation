# S2 harness: multi-equipment architecture validation (AHU + PUMP through the same pipeline).
#   canonical model -> revision engine (validation, diff, lock-aware allocation) + logic templates -> immutable store ->
#   deploy stage -> CODESYS project + build -> verify -> deploy -> runtime verify -> S1 regression (AHU stages) ->
#   template behaviour / isolation scenario -> typed verification (pymodbus + PLC online read-back).
# Stores (one per canonical project): PUMP-DEMO (V1 r001, V2 r002, V3 r003, V4 rejected), BMS-DEMO (AHU-01 + PUMP-01),
# AHU-DEMO (AHU-01 through the AHU_S1FIX_V1 template = S1/S3/S6 behaviour).
# Reuses the S1-FIX CODESYS adapter, the S3 bridge / typed verifier, the S6 regenerate / revision checks.
# Process exit code and operation status are recorded separately; downstream steps of a FAILED/BLOCKED step are
# NOT_RUN. Credentials are never printed.
param(
    [Parameter(Mandatory = $true)][ValidatePattern("^(run|dev)\d+$")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Src      = Join-Path $Repo "phase0\s2"
$S6       = Join-Path $Repo "phase0\s6"
$S3       = Join-Path $Repo "phase0\s3"
$S1       = Join-Path $Repo "phase0\s1fix"
$Models   = Join-Path $Src "model"
$Target   = Join-Path $Models "target_codesys_softplc.json"
$ScenPump = Join-Path $Models "scenario_pump.json"
$ScenIso  = Join-Path $Models "isolation_scenario_bms.json"
$Ref      = Join-Path $Repo "docs\phase0\s3_evidence\run2\types\logs\typed_verify.json"
$S6Ev     = Join-Path $Repo "docs\phase0\s6_evidence\run1"
$RunRoot  = "C:\AI_BMS_PHASE0\s2\$Run"
$RepoRun  = Join-Path $Repo "docs\phase0\s2_evidence\$Run"
$Codesys  = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile  = "CODESYS V3.5 SP22 Patch 3"
$Service  = "CODESYS Control Win V3 - x64"
$py       = (Get-Command python).Source
$cdsArgs  = "--culture=en --profile=`"$Profile`" --noUI --runscript="
$Checks   = "`"$Src\probe\s2_checks.py`""

function Store-Args([string]$Name) {
    return "--eng-root `"$RunRoot\engineering\$Name`" --gen-root `"$RunRoot\generated\$Name`""
}
function Regen([string]$Name) { return "`"$S6\generator\regenerate.py`" $(Store-Args $Name)" }
function RevCheck([string]$Name) { return "`"$S6\probe\revision_checks.py`" $(Store-Args $Name)" }
function InStore([string]$Name, [int]$Rev) { return (Test-Path (Join-Path $RunRoot ("engineering\$Name\revisions\r{0:D3}\manifest.json" -f $Rev))) }

if (Test-Path $RunRoot) { throw "Staging not clean: $RunRoot exists" }
$RootLogs = Join-Path $RunRoot "logs"; $RootEv = Join-Path $RunRoot "evidence"
New-Item -ItemType Directory -Force -Path $RunRoot, $RootLogs, $RootEv, (Join-Path $RunRoot "deploy"), (Join-Path $RunRoot "work"), $RepoRun | Out-Null
$Stage = $RunRoot; $Logs = $RootLogs; $Ev = $RootEv; $Prefix = ""

$steps = New-Object System.Collections.ArrayList
$ReplaceRuntimeApp = ($env:S1FIX_REPLACE_RUNTIME_APP -eq "1")
$deployed = [ordered]@{}

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
    $psi.FileName = $Exe; $psi.Arguments = $Arguments; $psi.WorkingDirectory = $script:Stage
    $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    return @{ p = $p; so = $p.StandardOutput.ReadToEndAsync(); se = $p.StandardError.ReadToEndAsync() }
}

function Stop-Proc($h, [int]$TimeoutSec, [string]$Id) {
    $timedOut = -not $h.p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) { & taskkill.exe /PID $h.p.Id /T /F | Out-Null; $h.p.WaitForExit(15000) | Out-Null }
    $exit = $null; try { $exit = $h.p.ExitCode } catch {}
    [System.IO.File]::WriteAllText((Join-Path $script:Ev "$Id.stdout.txt"), $h.so.Result)
    [System.IO.File]::WriteAllText((Join-Path $script:Ev "$Id.stderr.txt"), $h.se.Result)
    return @{ exit = $exit; timedOut = $timedOut }
}

function Add-StepRecord([string]$Id, $start, $x, [string]$Exe, [string]$Arguments, [string]$ResultFile, [int]$TimeoutSec) {
    $r = Read-Result $ResultFile
    $op = if ($x.timedOut) { "FAILED" } elseif ($r -and $r.operation_status) { $r.operation_status } else { "FAILED" }
    $reason = if ($x.timedOut) { "timeout after $TimeoutSec s" } elseif ($r) { $r.reason } else { "no result file written" }
    $rec = [ordered]@{
        step = "$script:Prefix$Id"; timestamp = $start.ToString("o")
        duration_seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        command = "`"$Exe`" $Arguments"
        process = [ordered]@{ exit_code = $x.exit; timed_out = $x.timedOut }
        operation = [ordered]@{ status = $op; reason = $reason }
        process_exit_code = $x.exit; operation_status = $op; reason = $reason; result_file = $ResultFile
        manual_intervention = $false
    }
    [void]$script:steps.Add($rec)
    Write-Host "[$script:Prefix$Id] exit=$($x.exit) op=$op reason=$reason"
    return $rec
}

function Invoke-Step([string]$Id, [string]$Exe, [string]$Arguments, [int]$TimeoutSec, [string]$ResultFile) {
    Write-Host "[$script:Prefix$Id] start"
    $start = Get-Date
    $h = Start-Proc $Exe $Arguments
    $x = Stop-Proc $h $TimeoutSec $Id
    return Add-StepRecord $Id $start $x $Exe $Arguments $ResultFile $TimeoutSec
}

function Add-Record([string]$Id, [string]$Status, [string]$Reason, $Data) {
    $rec = [ordered]@{ step = "$script:Prefix$Id"; timestamp = (Get-Date).ToString("o"); duration_seconds = $null; command = $null
        process = [ordered]@{ exit_code = $null; timed_out = $false }; operation = [ordered]@{ status = $Status; reason = $Reason }
        process_exit_code = $null; operation_status = $Status; reason = $Reason; data = $Data; manual_intervention = $false }
    [void]$script:steps.Add($rec)
    Write-Host "[$script:Prefix$Id] $Status $Reason"
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

# Offline python step at run level; returns $true when operation_status is PASS.
function Py-Step([string]$Id, [string]$Arguments, [string]$ResultName, [int]$TimeoutSec = 180) {
    $script:Stage = $RunRoot; $script:Logs = $RootLogs; $script:Ev = $RootEv; $script:Prefix = ""
    $rf = Join-Path $RootLogs $ResultName
    $f = Invoke-Step $Id $py ($Arguments + " --result `"$rf`"") $TimeoutSec $rf
    return ($f.operation_status -eq "PASS")
}
function Skip([string]$Id, [string]$Why) {
    $script:Prefix = ""; Add-Record $Id "NOT_RUN" $Why $null | Out-Null
}

# One PLC online bridge session around one python probe; the bridge result is kept per session.
function Bridge-Probe([string]$Id, [string]$BridgeDir, [string]$ProbeArgs, [string]$ResultName, [int]$TimeoutSec) {
    $env:S3_BRIDGE_DIR = Join-Path $script:Stage $BridgeDir
    New-Item -ItemType Directory -Force -Path $env:S3_BRIDGE_DIR | Out-Null
    $bStart = Get-Date
    $bArgs = $cdsArgs + "`"$S3\codesys\plc_online_bridge.py`""
    $bridge = Start-Proc $Codesys $bArgs
    $f = Invoke-Step $Id $py $ProbeArgs $TimeoutSec (Join-Path $script:Logs $ResultName)
    $bx = Stop-Proc $bridge 90 "${Id}_bridge"
    $brf = Join-Path $script:Logs "bridge_result_$BridgeDir.json"
    if (Test-Path (Join-Path $script:Logs "bridge_result.json")) { Move-Item -Force (Join-Path $script:Logs "bridge_result.json") $brf }
    $b = Add-StepRecord "${Id}_bridge" $bStart $bx $Codesys $bArgs $brf 90
    return (($f.operation_status -eq "PASS") -and ($b.operation_status -eq "PASS"))
}

# F04 CODESYS project + build -> F05 build verify -> F06 preflight + deploy -> F07 runtime verify ->
# F07b S1 regression (stages with AHU-01) -> F07c behaviour (templates / scenarios) -> F07d typed verification.
function Deploy-Chain([string]$Label, [bool]$Gate, [string]$GateWhy, [bool]$HasAhu, [string]$BehaviorArgs) {
    $script:Stage = Join-Path $RunRoot "deploy\$Label"; $script:Logs = Join-Path $script:Stage "logs"
    $script:Ev = Join-Path $script:Stage "evidence"; $script:Prefix = "$Label/"
    New-Item -ItemType Directory -Force -Path $script:Logs, $script:Ev | Out-Null
    $env:S1FIX_STAGE = $script:Stage
    $Logs = $script:Logs; $gate = $Gate; $gateWhy = $GateWhy; $all = $Gate

    if ($gate) {
        $f = Invoke-Step "F04_codesys_project_build" $Codesys ($cdsArgs + "`"$S1\codesys\create_project.py`"") 400 (Join-Path $Logs "create_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F04_codesys_project_build $($f.operation_status)"
    } else { Add-Record "F04_codesys_project_build" "NOT_RUN" $gateWhy $null | Out-Null }

    if ($gate) {
        $f = Invoke-Step "F05_codesys_build_verify" $Codesys ($cdsArgs + "`"$S1\codesys\verify_project.py`"") 300 (Join-Path $Logs "verify_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F05_codesys_build_verify $($f.operation_status)"
    } else { Add-Record "F05_codesys_build_verify" "NOT_RUN" $gateWhy $null | Out-Null }

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
        Add-Record "F06a_deploy_preflight" $st ($(if ($missing.Count) { $missing -join "; " } else { "all prerequisites present" })) $pf | Out-Null
        $gate = $st -eq "PASS"; $gateWhy = "F06a_deploy_preflight $st"
    } else { Add-Record "F06a_deploy_preflight" "NOT_RUN" $gateWhy $null | Out-Null }

    if ($gate) {
        $f = Invoke-Step "F06_deploy" $Codesys ($cdsArgs + "`"$S1\codesys\deploy.py`"") 300 (Join-Path $Logs "deployment_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F06_deploy $($f.operation_status)"
        if ($gate) {
            $dr = Read-Result (Join-Path $Logs "deployment_result.json")
            $plan = Read-Result (Join-Path $script:Stage "engineering\codesys_plan.json")
            $deadline = (Get-Date).AddSeconds(15)
            while (-not (Listening 502) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
            $ioVars = @($plan.io_mappings | ForEach-Object { $_.variable -replace '^Application\.', '' } | Sort-Object -Unique)
            $missingVars = @($ioVars | Where-Object { -not $dr.online_values -or $dr.online_values.$_ -eq $null -or "$($dr.online_values.$_)" -eq "None" })
            $rv = [ordered]@{ application_state = $dr.application_state; project_file = $plan.project_file
                io_variables = $ioVars.Count; io_variables_missing_online = $missingVars
                tcp_502_listening = Listening 502; tcp_502_owner_pid = Port-Owner 502; runtime_service_pid = Runtime-Pid }
            $rv.tcp_502_owned_by_runtime = ($rv.tcp_502_owner_pid -ne $null -and $rv.tcp_502_owner_pid -eq $rv.runtime_service_pid)
            $ok = ("$($rv.application_state)".ToLower() -eq "run") -and $ioVars.Count -gt 0 -and $missingVars.Count -eq 0 -and $rv.tcp_502_owned_by_runtime
            Add-Record "F07_runtime_verify" ($(if ($ok) { "PASS" } else { "FAILED" })) ($(if ($ok) { "$($plan.project_file) in RUN, all $($ioVars.Count) Modbus image variables online, tcp/502 owned by runtime" } else { "runtime verification failed" })) $rv | Out-Null
            $gate = $ok; $gateWhy = "F07_runtime_verify $(if ($ok) { 'PASS' } else { 'FAILED' })"
        }
    } else { Add-Record "F06_deploy" "NOT_RUN" $gateWhy $null | Out-Null }

    if ($HasAhu) {
        if ($gate) {
            $f = Invoke-Step "F07b_s1_regression" $py "`"$S6\probe\s1_regression.py`" --stage `"$script:Stage`"" 90 (Join-Path $Logs "s1_regression.json")
            $all = $all -and ($f.operation_status -eq "PASS")
        } else { Add-Record "F07b_s1_regression" "NOT_RUN" $gateWhy $null | Out-Null }
    }

    if ($BehaviorArgs) {
        if ($gate) {
            $ok = Bridge-Probe "F07c_behavior" "bridge_behavior" "`"$Src\probe\behavior.py`" --stage `"$script:Stage`" $BehaviorArgs" "behavior.json" 300
            $all = $all -and $ok
        } else { Add-Record "F07c_behavior" "NOT_RUN" $gateWhy $null | Out-Null }
    }

    if ($gate) {
        $ok = Bridge-Probe "F07d_typed_verify" "bridge" "`"$S3\probe\typed_verify.py`" --stage `"$script:Stage`" --reference `"$Ref`"" "typed_verify.json" 600
        $all = $all -and $ok
    } else { Add-Record "F07d_typed_verify" "NOT_RUN" $gateWhy $null | Out-Null }

    $all = $all -and $gate
    $script:deployed[$Label] = $all
    $script:Stage = $RunRoot; $script:Logs = $RootLogs; $script:Ev = $RootEv; $script:Prefix = ""
    return $all
}

# F01 model -> store, F02 validation, F03 mapping, stage. Returns $true when the revision is stored and staged.
function Commit-Stage([string]$Id, [string]$StoreName, [string]$ModelFile, [string]$Label, [int]$Rev, [bool]$Gate, [string]$GateWhy) {
    $tag = "{0}_r{1:D3}" -f $StoreName, $Rev
    $names = @("F01_model_$tag", "F02_validation_$tag", "F03_mapping_$tag", "F03b_stage_$tag")
    if ($Id) { $names = $names | ForEach-Object { "${Id}_$_" } }
    if (-not $Gate) { foreach ($n in $names) { Skip $n $GateWhy }; return $false }
    $ok = Py-Step $names[0] "$(Regen $StoreName) commit --model `"$Models\$ModelFile`" --target `"$Target`" --label $Label" "commit_$tag.json"
    if (-not $ok) { foreach ($n in $names[1..3]) { Skip $n "$($names[0]) FAILED" }; return $false }
    $v = Py-Step $names[1] "$Checks validation $(Store-Args $StoreName) --revision $Rev" "validation_$tag.json"
    $m = Py-Step $names[2] "$Checks mapping $(Store-Args $StoreName) --revision $Rev" "mapping_$tag.json"
    $s = Py-Step $names[3] "$(Regen $StoreName) stage --revision $Rev --out `"$RunRoot\deploy\$tag`"" "stage_$tag.json"
    return ($v -and $m -and $s)
}

# ---------- F00 preflight + regression self-tests ----------
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$hashes = [ordered]@{}
foreach ($f in @(Get-ChildItem $Models -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName }) +
               @(Get-ChildItem (Join-Path $Src "logic\templates") -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName })) {
    $hashes[(Split-Path $f -Leaf)] = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
}
$refOrder = $null; if (Test-Path $Ref) { $refOrder = (Read-Result $Ref).real32_ordering.name }
$s6Store = Test-Path (Join-Path $S6Ev "engineering\revisions\index.json")
$preOk = [bool]$refOrder -and $s6Store
Add-Record "F00_preflight" ($(if ($preOk) { "INFO" } else { "BLOCKED" })) ($(if ($preOk) { "environment facts" } else { "missing reference input (S3 REAL32 reference: $([bool]$refOrder), S6 store evidence: $s6Store)" })) ([ordered]@{
    elevated = $elevated; softplc_service = (Get-Service $Service).Status.ToString()
    tcp_502 = Listening 502; tcp_11740 = Listening 11740; tcp_1217 = Listening 1217
    input_sha256 = $hashes; s3_reference = $Ref; s3_reference_real32_ordering = $refOrder; s6_store_evidence = $S6Ev
    mcp_used = $false; llm_used = $false; temp_patch_used = $false; gui_automation_used = $false; old_poc_used = $false
    physical_plc_used = $false; masterscada_used = $false }) | Out-Null
$t3 = Py-Step "F00b_s3_engine_selftest" "`"$S3\engine\test_engine.py`"" "s3_engine_selftest.json" 120
$t6 = Py-Step "F00c_s6_revision_selftest" "`"$S6\engine\test_revision.py`"" "s6_revision_selftest.json" 180
$t2 = Py-Step "F00d_s2_selftest" "`"$Src\engine\test_s2.py`"" "s2_selftest.json" 180
$r6 = $false
if ($s6Store) {
    $r6 = Py-Step "F00e_s6_store_reproduction" "`"$S6\probe\revision_checks.py`" --eng-root `"$S6Ev\engineering`" --gen-root `"$S6Ev\generated`" repro --out `"$RunRoot\work\s6_repro`"" "s6_store_reproduction.json" 300
} else { Skip "F00e_s6_store_reproduction" "S6 store evidence missing" }
$ag = Py-Step "F00f_adapter_generic" "$Checks adapter-generic --adapter-dir `"$S1\codesys`" --control-file `"$S3\generator\generate.py`" --models `"$Models\pump_v1.json`" `"$Models\pump_v2.json`" `"$Models\pump_v3.json`" `"$Models\pump_v4_type_change.json`" `"$Models\combined_v1.json`" `"$Models\ahu_v1.json`"" "adapter_generic.json"
$te = Py-Step "F00g_template_equivalence" "$Checks template-equivalence --legacy-model `"$S6\model\revisions\v1.json`" --legacy-target `"$S6\model\target_codesys_softplc.json`" --model `"$Models\ahu_v1.json`" --target `"$Target`"" "template_equivalence.json"
$gate = $preOk -and $t3 -and $t6 -and $t2 -and $r6 -and $ag -and $te
$why = "F00 gate (inputs=$preOk, s3=$t3, s6=$t6, s2=$t2, s6_repro=$r6, adapter_generic=$ag, template_equivalence=$te)"

# ---------- PUMP V1 -> pump r001 (F01-F07) ----------
$p1s = Commit-Stage "" "pump" "pump_v1.json" "PUMP_V1" 1 $gate $why
if (InStore "pump" 1) { Py-Step "F03c_diff_pump_r001" "$(RevCheck pump) diff --revision 1 --scenario `"$ScenPump`"" "diff_pump_r001.json" | Out-Null }
else { Skip "F03c_diff_pump_r001" "pump r001 not in store" }
$p1 = Deploy-Chain "pump_r001" $p1s "pump r001 commit/stage $(if ($p1s) { 'PASS' } else { 'FAILED' })" $false "--equipment PUMP-01"

# ---------- F10 revisions: V2 (+FlowRate) deployed, V3 (-Pressure), V4 (PumpSpeed REAL32 -> INT16) ----------
$p2s = Commit-Stage "F10a" "pump" "pump_v2.json" "PUMP_V2" 2 $p1 "pump_r001 chain $(if ($p1) { 'PASS' } else { 'FAILED' })"
$p2 = Deploy-Chain "pump_r002" $p2s "pump r002 commit/stage $(if ($p2s) { 'PASS' } else { 'FAILED' })" $false "--equipment PUMP-01"
if (InStore "pump" 2) {
    Py-Step "F10b_diff_pump_r002" "$(RevCheck pump) diff --revision 2 --scenario `"$ScenPump`"" "diff_pump_r002.json" | Out-Null
    Py-Step "F10c_stability_pump_r001_r002" "$(RevCheck pump) stability --from 1 --to 2 --deployed-a `"$RunRoot\deploy\pump_r001`" --deployed-b `"$RunRoot\deploy\pump_r002`"" "stability_pump_r001_r002.json" | Out-Null
} else { Skip "F10b_diff_pump_r002" "pump r002 not in store"; Skip "F10c_stability_pump_r001_r002" "pump r002 not in store" }
$p3s = Commit-Stage "F10d" "pump" "pump_v3.json" "PUMP_V3" 3 (InStore "pump" 2) "pump r002 not in store"
if (InStore "pump" 3) {
    Py-Step "F10e_diff_pump_r003" "$(RevCheck pump) diff --revision 3 --scenario `"$ScenPump`"" "diff_pump_r003.json" | Out-Null
    Py-Step "F10f_stability_pump_r002_r003" "$(RevCheck pump) stability --from 2 --to 3" "stability_pump_r002_r003.json" | Out-Null
    Py-Step "F10g_v4_type_change_rejected" "$(RevCheck pump) expect-reject --model `"$Models\pump_v4_type_change.json`" --target `"$Target`" --label PUMP_V4_type_change --code BREAKING_CHANGE_REQUIRES_APPROVAL --text TYPE_CHANGED" "v4_type_change.json" | Out-Null
} else { foreach ($s in "F10e_diff_pump_r003", "F10f_stability_pump_r002_r003", "F10g_v4_type_change_rejected") { Skip $s "pump r003 not in store" } }

# ---------- Multi-equipment: AHU-01 + PUMP-01 in one model / one application ----------
$cs = Commit-Stage "" "combined" "combined_v1.json" "BMS_V1" 1 $gate $why
if (InStore "combined" 1) {
    Py-Step "F03d_isolation_combined_r001" "$Checks isolation $(Store-Args combined) --revision 1 --target `"$Target`"" "isolation_combined_r001.json" | Out-Null
} else { Skip "F03d_isolation_combined_r001" "combined r001 not in store" }
$cb = Deploy-Chain "combined_r001" $cs "combined r001 commit/stage $(if ($cs) { 'PASS' } else { 'FAILED' })" $true "--equipment PUMP-01 --scenario `"$ScenIso`""

# ---------- AHU regression: AHU-01 alone through the template layer (last: leaves the S1 AHU app deployed) ----------
$as = Commit-Stage "" "ahu" "ahu_v1.json" "AHU_V1" 1 $gate $why
$ab = Deploy-Chain "ahu_r001" $as "ahu r001 commit/stage $(if ($as) { 'PASS' } else { 'FAILED' })" $true ""

# ---------- F11 reproduction + store integrity (every store) ----------
foreach ($n in "pump", "combined", "ahu") {
    if (Test-Path (Join-Path $RunRoot "engineering\$n\revisions\index.json")) {
        Py-Step "F11a_reproduce_$n" "$(RevCheck $n) repro --out `"$RunRoot\repro\$n`"" "repro_$n.json" 300 | Out-Null
        Py-Step "F11b_integrity_$n" "$(RevCheck $n) integrity" "integrity_$n.json" | Out-Null
    } else { Skip "F11a_reproduce_$n" "no $n store"; Skip "F11b_integrity_$n" "no $n store" }
}

# ---------- F08 / F09 / F10 summaries (derived from the step records above) ----------
function Op([string]$Step) { $r = $steps | Where-Object { $_.step -eq $Step } | Select-Object -Last 1; if ($r) { return $r.operation_status }; return "MISSING" }
function Summary([string]$Id, [string[]]$Need, [string]$What) {
    $st = [ordered]@{}; foreach ($n in $Need) { $st[$n] = Op $n }
    $bad = @($st.Keys | Where-Object { $st[$_] -ne "PASS" })
    Add-Record $Id ($(if ($bad.Count) { "FAILED" } else { "PASS" })) ($(if ($bad.Count) { "not PASS: " + ($bad -join ", ") } else { $What })) $st | Out-Null
}
$chainSteps = { param($l, $ahu, $beh) $s = @("$l/F04_codesys_project_build", "$l/F05_codesys_build_verify", "$l/F06_deploy", "$l/F07_runtime_verify")
    if ($ahu) { $s += "$l/F07b_s1_regression" }; if ($beh) { $s += "$l/F07c_behavior", "$l/F07c_behavior_bridge" }
    return $s + @("$l/F07d_typed_verify", "$l/F07d_typed_verify_bridge") }
Summary "F08_ahu_regression" (@("F00g_template_equivalence", "F02_validation_ahu_r001", "F03_mapping_ahu_r001") + (& $chainSteps "ahu_r001" $true $false) + @("combined_r001/F07b_s1_regression")) `
    "AHU-01 alone and inside BMS-DEMO: build/verify/deploy, HR0=1 -> IR0=3, HR0=2 -> IR0=0, REAL32 + typed signals verified"
Summary "F09_pump_verification" (@("F00f_adapter_generic", "F02_validation_pump_r001", "F03_mapping_pump_r001", "F03c_diff_pump_r001",
    "F02_validation_combined_r001", "F03_mapping_combined_r001", "F03d_isolation_combined_r001") + (& $chainSteps "pump_r001" $false $true) + (& $chainSteps "combined_r001" $true $true)) `
    "PUMP-01 generated, built 0/0, deployed, state machine + BOOL/INT16/REAL32 verified; isolated next to AHU-01"
Summary "F10_revision" (@("F10a_F02_validation_pump_r002", "F10b_diff_pump_r002", "F10c_stability_pump_r001_r002", "F10d_F02_validation_pump_r003",
    "F10e_diff_pump_r003", "F10f_stability_pump_r002_r003", "F10g_v4_type_change_rejected") + (& $chainSteps "pump_r002" $false $true)) `
    "V2 FlowRate NEW + existing PRESERVED (deployed, runtime-verified), V3 Pressure RETIRED, V4 TYPE_CHANGED breaking REJECTED"

$Prefix = ""
Add-Record "F12_post_state" "INFO" "post-run facts" ([ordered]@{
    softplc_service = (Get-Service $Service).Status.ToString(); tcp_502 = Listening 502
    deploy_chains = $deployed
    codesys_left_running = @(Get-Process CODESYS -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) }) | Out-Null

$obj = [ordered]@{ run = $Run; stage = $RunRoot; steps = $steps }
$obj | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 (Join-Path $RootEv "harness_$Run.json")

foreach ($d in "logs", "evidence", "engineering", "generated") {
    if (Test-Path (Join-Path $RunRoot $d)) { Copy-Item (Join-Path $RunRoot $d) (Join-Path $RepoRun $d) -Recurse -Force }
}
foreach ($dep in Get-ChildItem (Join-Path $RunRoot "deploy") -Directory) {
    $dst = Join-Path $RepoRun "deploy\$($dep.Name)"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    foreach ($d in "logs", "evidence", "engineering", "generated") {
        if (Test-Path (Join-Path $dep.FullName $d)) { Copy-Item (Join-Path $dep.FullName $d) (Join-Path $dst $d) -Recurse -Force }
    }
}
Write-Host "DONE $Run"
