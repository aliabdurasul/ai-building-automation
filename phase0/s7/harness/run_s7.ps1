# S7 harness: CODESYS behavioural validation of the generated AHU and PUMP logic on the running SoftPLC.
#   canonical model -> revision engine + logic templates -> immutable store -> deploy stage -> CODESYS project + build ->
#   verify -> deploy -> runtime verify -> S1 regression (AHU applications) -> behaviour scenarios (Modbus commands,
#   PLC online fault injection, Modbus trace of state sequences / template timings, Modbus + PLC online read-back) ->
#   typed verification -> S7 test matrix.
# Stores: PUMP-DEMO (S2 V1 r001 offline, V2 r002 deployed), BMS-DEMO (S2 combined AHU-01 + PUMP-01), AHU-SEQ
# (AHU_SEQ_V1 sequence template), AHU-S1 (existing AHU_S1FIX_V1 logic). Composes the S1-FIX adapter, S3 bridge / typed
# verifier, S6 regenerate / revision checks / S1 regression and the S2 behaviour executor / checks.
# Process exit code and operation status are recorded separately; downstream steps of a FAILED/BLOCKED step are
# NOT_RUN. Credentials are never printed.
param(
    [Parameter(Mandatory = $true)][ValidatePattern("^(run|dev)\d+$")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Src      = Join-Path $Repo "phase0\s7"
$S2       = Join-Path $Repo "phase0\s2"
$S6       = Join-Path $Repo "phase0\s6"
$S3       = Join-Path $Repo "phase0\s3"
$S1       = Join-Path $Repo "phase0\s1fix"
$Models   = Join-Path $Src "model"
$S2Models = Join-Path $S2 "model"
$Target   = Join-Path $Models "target_codesys_softplc.json"
$ScenIso  = Join-Path $S2Models "isolation_scenario_bms.json"
$ScenSeq  = Join-Path $Models "ahu_seq_behavior.json"
$ScenS1   = Join-Path $Models "ahu_s1fix_behavior.json"
$ScenPump = Join-Path $Models "pump_behavior.json"
$Ref      = Join-Path $Repo "docs\phase0\s3_evidence\run2\types\logs\typed_verify.json"
$S6Ev     = Join-Path $Repo "docs\phase0\s6_evidence\run1"
$S2Ev     = Join-Path $Repo "docs\phase0\s2_evidence\run1"
$RunRoot  = "C:\AI_BMS_PHASE0\s7\$Run"
$RepoRun  = Join-Path $Repo "docs\phase0\s7_evidence\$Run"
$Codesys  = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile  = "CODESYS V3.5 SP22 Patch 3"
$Service  = "CODESYS Control Win V3 - x64"
$py       = (Get-Command python).Source
$cdsArgs  = "--culture=en --profile=`"$Profile`" --noUI --runscript="
$Checks   = "`"$S2\probe\s2_checks.py`""

function Store-Args([string]$Name) {
    return "--eng-root `"$RunRoot\engineering\$Name`" --gen-root `"$RunRoot\generated\$Name`""
}
function Regen([string]$Name) { return "`"$S6\generator\regenerate.py`" $(Store-Args $Name)" }
function RevCheck([string]$Name) { return "`"$S6\probe\revision_checks.py`" $(Store-Args $Name)" }

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

function Py-Step([string]$Id, [string]$Arguments, [string]$ResultName, [int]$TimeoutSec = 180) {
    $script:Stage = $RunRoot; $script:Logs = $RootLogs; $script:Ev = $RootEv; $script:Prefix = ""
    $rf = Join-Path $RootLogs $ResultName
    $f = Invoke-Step $Id $py ($Arguments + " --result `"$rf`"") $TimeoutSec $rf
    return ($f.operation_status -eq "PASS")
}
function Skip([string]$Id, [string]$Why) {
    $script:Prefix = ""; Add-Record $Id "NOT_RUN" $Why $null | Out-Null
}

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
# F07b S1 regression (AHU applications) -> F07c behaviour -> F07d typed verification.
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
            $ok = Bridge-Probe "F07c_behavior" "bridge_behavior" "`"$S2\probe\behavior.py`" --stage `"$script:Stage`" --reference `"$Ref`" $BehaviorArgs" "behavior.json" 600
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
function Commit-Stage([string]$StoreName, [string]$ModelFile, [string]$Label, [int]$Rev, [bool]$Gate, [string]$GateWhy) {
    $tag = "{0}_r{1:D3}" -f $StoreName, $Rev
    $names = @("F01_model_$tag", "F02_validation_$tag", "F03_mapping_$tag", "F03b_stage_$tag")
    if (-not $Gate) { foreach ($n in $names) { Skip $n $GateWhy }; return $false }
    $ok = Py-Step $names[0] "$(Regen $StoreName) commit --model `"$ModelFile`" --target `"$Target`" --label $Label" "commit_$tag.json"
    if (-not $ok) { foreach ($n in $names[1..3]) { Skip $n "$($names[0]) FAILED" }; return $false }
    $v = Py-Step $names[1] "$Checks validation $(Store-Args $StoreName) --revision $Rev" "validation_$tag.json"
    $m = Py-Step $names[2] "$Checks mapping $(Store-Args $StoreName) --revision $Rev" "mapping_$tag.json"
    $s = Py-Step $names[3] "$(Regen $StoreName) stage --revision $Rev --out `"$RunRoot\deploy\$tag`"" "stage_$tag.json"
    return ($v -and $m -and $s)
}

# ---------- F00 preflight + offline regression ----------
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$hashes = [ordered]@{}
foreach ($f in @(Get-ChildItem $Models -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName }) +
               @(Get-ChildItem $S2Models -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName }) +
               @(Get-ChildItem (Join-Path $S2 "logic\templates") -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName })) {
    $hashes[(Split-Path (Split-Path $f -Parent) -Leaf) + "/" + (Split-Path $f -Leaf)] = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
}
$refOrder = $null; if (Test-Path $Ref) { $refOrder = (Read-Result $Ref).real32_ordering.name }
$s6Store = Test-Path (Join-Path $S6Ev "engineering\revisions\index.json")
$s2Stores = @("pump", "combined", "ahu" | Where-Object { -not (Test-Path (Join-Path $S2Ev "engineering\$_\revisions\index.json")) }).Count -eq 0
$preOk = [bool]$refOrder -and $s6Store -and $s2Stores
Add-Record "F00_preflight" ($(if ($preOk) { "INFO" } else { "BLOCKED" })) ($(if ($preOk) { "environment facts" } else { "missing reference input (S3 REAL32 reference: $([bool]$refOrder), S6 store evidence: $s6Store, S2 store evidence: $s2Stores)" })) ([ordered]@{
    elevated = $elevated; softplc_service = (Get-Service $Service).Status.ToString()
    tcp_502 = Listening 502; tcp_11740 = Listening 11740; tcp_1217 = Listening 1217
    input_sha256 = $hashes; s3_reference = $Ref; s3_reference_real32_ordering = $refOrder
    s6_store_evidence = $S6Ev; s2_store_evidence = $S2Ev
    mcp_used = $false; llm_used = $false; temp_patch_used = $false; gui_automation_used = $false; old_poc_used = $false
    physical_plc_used = $false; masterscada_used = $false }) | Out-Null
$t3 = Py-Step "F00b_s3_engine_selftest" "`"$S3\engine\test_engine.py`"" "s3_engine_selftest.json" 120
$t6 = Py-Step "F00c_s6_revision_selftest" "`"$S6\engine\test_revision.py`"" "s6_revision_selftest.json" 180
$t2 = Py-Step "F00d_s2_selftest" "`"$S2\engine\test_s2.py`"" "s2_selftest.json" 180
$t7 = Py-Step "F00e_s7_selftest" "`"$Src\engine\test_s7.py`"" "s7_selftest.json" 180
$r6 = $false
if ($s6Store) {
    $r6 = Py-Step "F00f_s6_store_reproduction" "`"$S6\probe\revision_checks.py`" --eng-root `"$S6Ev\engineering`" --gen-root `"$S6Ev\generated`" repro --out `"$RunRoot\work\s6_repro`"" "s6_store_reproduction.json" 300
} else { Skip "F00f_s6_store_reproduction" "S6 store evidence missing" }
$r2 = $s2Stores
foreach ($n in "pump", "combined", "ahu") {
    if ($s2Stores) {
        $ok = Py-Step "F00g_s2_store_reproduction_$n" "`"$S6\probe\revision_checks.py`" --eng-root `"$S2Ev\engineering\$n`" --gen-root `"$S2Ev\generated\$n`" repro --out `"$RunRoot\work\s2_repro_$n`"" "s2_store_reproduction_$n.json" 300
        $r2 = $r2 -and $ok
    } else { Skip "F00g_s2_store_reproduction_$n" "S2 store evidence missing" }
}
$ag = Py-Step "F00h_adapter_generic" "$Checks adapter-generic --adapter-dir `"$S1\codesys`" --control-file `"$S3\generator\generate.py`" --models `"$S2Models\pump_v1.json`" `"$S2Models\pump_v2.json`" `"$S2Models\combined_v1.json`" `"$S2Models\ahu_v1.json`" `"$Models\ahu_seq_v1.json`" `"$Models\ahu_s1fix_v1.json`"" "adapter_generic.json"
$te = Py-Step "F00i_template_equivalence" "$Checks template-equivalence --legacy-model `"$S6\model\revisions\v1.json`" --legacy-target `"$S6\model\target_codesys_softplc.json`" --model `"$S2Models\ahu_v1.json`" --target `"$Target`"" "template_equivalence.json"
$gate = $preOk -and $t3 -and $t6 -and $t2 -and $t7 -and $r6 -and $r2 -and $ag -and $te
$why = "F00 gate (inputs=$preOk, s3=$t3, s6=$t6, s2=$t2, s7=$t7, s6_repro=$r6, s2_repro=$r2, adapter_generic=$ag, template_equivalence=$te)"

# ---------- PUMP: S2 V1 (r001, store only) -> V2 (r002, deployed): template behaviour + S7 pump scenario ----------
$p1s = Commit-Stage "pump" "$S2Models\pump_v1.json" "PUMP_V1" 1 $gate $why
$p2s = Commit-Stage "pump" "$S2Models\pump_v2.json" "PUMP_V2" 2 $p1s "pump r001 commit/stage $(if ($p1s) { 'PASS' } else { 'FAILED' })"
$p2 = Deploy-Chain "pump_r002" $p2s "pump r002 commit/stage $(if ($p2s) { 'PASS' } else { 'FAILED' })" $false "--equipment PUMP-01 --scenario `"$ScenPump`""

# ---------- S2 regression: AHU-01 + PUMP-01 in one application ----------
$cs = Commit-Stage "combined" "$S2Models\combined_v1.json" "BMS_V1" 1 $gate $why
$cb = Deploy-Chain "combined_r001" $cs "combined r001 commit/stage $(if ($cs) { 'PASS' } else { 'FAILED' })" $true "--equipment PUMP-01 --scenario `"$ScenIso`""

# ---------- AHU_SEQ_V1 sequence ----------
$qs = Commit-Stage "ahu_seq" "$Models\ahu_seq_v1.json" "AHU_SEQ_V1" 1 $gate $why
$qb = Deploy-Chain "ahu_seq_r001" $qs "ahu_seq r001 commit/stage $(if ($qs) { 'PASS' } else { 'FAILED' })" $true "--scenario `"$ScenSeq`""

# ---------- existing AHU_S1FIX_V1 logic (last: leaves the S1 AHU behaviour deployed) ----------
$ss = Commit-Stage "ahu_s1" "$Models\ahu_s1fix_v1.json" "AHU_S1_V1" 1 $gate $why
$sb = Deploy-Chain "ahu_s1_r001" $ss "ahu_s1 r001 commit/stage $(if ($ss) { 'PASS' } else { 'FAILED' })" $true "--scenario `"$ScenS1`""

# ---------- F11 reproduction + store integrity (every store) ----------
foreach ($n in "pump", "combined", "ahu_seq", "ahu_s1") {
    if (Test-Path (Join-Path $RunRoot "engineering\$n\revisions\index.json")) {
        Py-Step "F11a_reproduce_$n" "$(RevCheck $n) repro --out `"$RunRoot\repro\$n`"" "repro_$n.json" 300 | Out-Null
        Py-Step "F11b_integrity_$n" "$(RevCheck $n) integrity" "integrity_$n.json" | Out-Null
    } else { Skip "F11a_reproduce_$n" "no $n store"; Skip "F11b_integrity_$n" "no $n store" }
}

# ---------- F13 S7 test matrix (derived from the result files above) ----------
Py-Step "F13_test_matrix" "`"$Src\probe\test_matrix.py`" --run-root `"$RunRoot`"" "test_matrix.json" | Out-Null

$Prefix = ""
Add-Record "F14_post_state" "INFO" "post-run facts" ([ordered]@{
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
