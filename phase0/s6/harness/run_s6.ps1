# S6 harness: revision / regeneration engine end-to-end.
#   canonical revision model -> revision engine (diff, policy, lock-aware allocation) -> immutable store ->
#   deploy stage -> CODESYS create + build -> verify -> deploy -> runtime -> S1 regression + typed verification.
# Lineage: V1 (r001) -> V2 (r002) -> rollback to r001 -> invalid revisions -> V3 (r003) -> V4 breaking attempts ->
#          V5 equipment (r004) -> V6 direction attempts -> reproduction + store integrity.
# Reuses the S1-FIX CODESYS adapter and the S3 bridge / typed verifier. Process exit code and operation status are
# recorded separately; downstream steps of a FAILED/BLOCKED step are NOT_RUN. Credentials are never printed.
param(
    [Parameter(Mandatory = $true)][ValidatePattern("^(run|dev)\d+$")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Src      = Join-Path $Repo "phase0\s6"
$S3       = Join-Path $Repo "phase0\s3"
$S1       = Join-Path $Repo "phase0\s1fix"
$Models   = Join-Path $Src "model\revisions"
$Target   = Join-Path $Src "model\target_codesys_softplc.json"
$Scenario = Join-Path $Src "model\scenario.json"
$Ref      = Join-Path $Repo "docs\phase0\s3_evidence\run2\types\logs\typed_verify.json"
$RunRoot  = "C:\AI_BMS_PHASE0\s6\$Run"
$EngRoot  = Join-Path $RunRoot "engineering"
$GenRoot  = Join-Path $RunRoot "generated"
$RepoRun  = Join-Path $Repo "docs\phase0\s6_evidence\$Run"
$Codesys  = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile  = "CODESYS V3.5 SP22 Patch 3"
$Service  = "CODESYS Control Win V3 - x64"
$py       = (Get-Command python).Source
$cdsArgs  = "--culture=en --profile=`"$Profile`" --noUI --runscript="
$Regen    = "`"$Src\generator\regenerate.py`" --eng-root `"$EngRoot`" --gen-root `"$GenRoot`""
$Check    = "`"$Src\probe\revision_checks.py`" --eng-root `"$EngRoot`" --gen-root `"$GenRoot`""

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

# Offline python step (store / checks) at run level; returns $true when operation_status is PASS.
function Py-Step([string]$Id, [string]$Arguments, [string]$ResultName, [int]$TimeoutSec = 180) {
    $script:Stage = $RunRoot; $script:Logs = $RootLogs; $script:Ev = $RootEv; $script:Prefix = ""
    $rf = Join-Path $RootLogs $ResultName
    $f = Invoke-Step $Id $py ($Arguments + " --result `"$rf`"") $TimeoutSec $rf
    return ($f.operation_status -eq "PASS")
}
function Skip([string]$Id, [string]$Why) {
    $script:Prefix = ""; Add-Record $Id "NOT_RUN" $Why $null | Out-Null
}

# CODESYS create/build -> verify -> preflight -> deploy -> runtime verify -> S1 regression -> typed verification.
function Deploy-Chain([string]$Label, [bool]$Gate, [string]$GateWhy) {
    $script:Stage = Join-Path $RunRoot "deploy\$Label"; $script:Logs = Join-Path $script:Stage "logs"
    $script:Ev = Join-Path $script:Stage "evidence"; $script:Prefix = "$Label/"
    New-Item -ItemType Directory -Force -Path $script:Logs, $script:Ev, (Join-Path $script:Stage "bridge") | Out-Null
    $env:S1FIX_STAGE = $script:Stage
    $Logs = $script:Logs; $gate = $Gate; $gateWhy = $GateWhy; $all = $Gate

    if ($gate) {
        $f = Invoke-Step "F02_codesys_create_build" $Codesys ($cdsArgs + "`"$S1\codesys\create_project.py`"") 400 (Join-Path $Logs "create_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F02_codesys_create_build $($f.operation_status)"
    } else { Add-Record "F02_codesys_create_build" "NOT_RUN" $gateWhy $null | Out-Null }

    if ($gate) {
        $f = Invoke-Step "F03_codesys_verify" $Codesys ($cdsArgs + "`"$S1\codesys\verify_project.py`"") 300 (Join-Path $Logs "verify_result.json")
        $gate = $f.operation_status -eq "PASS"; $gateWhy = "F03_codesys_verify $($f.operation_status)"
    } else { Add-Record "F03_codesys_verify" "NOT_RUN" $gateWhy $null | Out-Null }

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

    if ($gate) {
        $f = Invoke-Step "F06_s1_regression" $py "`"$Src\probe\s1_regression.py`" --stage `"$script:Stage`"" 90 (Join-Path $Logs "s1_regression.json")
        $all = $all -and ($f.operation_status -eq "PASS")
    } else { Add-Record "F06_s1_regression" "NOT_RUN" $gateWhy $null | Out-Null }

    if ($gate) {
        $env:S3_BRIDGE_DIR = Join-Path $script:Stage "bridge"
        $bStart = Get-Date
        $bArgs = $cdsArgs + "`"$S3\codesys\plc_online_bridge.py`""
        $bridge = Start-Proc $Codesys $bArgs
        $f = Invoke-Step "F06b_typed_verify" $py "`"$S3\probe\typed_verify.py`" --stage `"$script:Stage`" --reference `"$Ref`"" 600 (Join-Path $Logs "typed_verify.json")
        $bx = Stop-Proc $bridge 90 "F06c_plc_online_bridge"
        $b = Add-StepRecord "F06c_plc_online_bridge" $bStart $bx $Codesys $bArgs (Join-Path $Logs "bridge_result.json") 90
        $all = $all -and ($f.operation_status -eq "PASS") -and ($b.operation_status -eq "PASS")
    } else { Add-Record "F06b_typed_verify" "NOT_RUN" $gateWhy $null | Out-Null }

    $all = $all -and $gate
    $script:deployed[$Label] = $all
    $script:Stage = $RunRoot; $script:Logs = $RootLogs; $script:Ev = $RootEv; $script:Prefix = ""
    return $all
}

# Commit a revision model and write its deploy stage; then run the full deploy chain.
function Commit-And-Deploy([string]$Id, [string]$ModelFile, [string]$ModelLabel, [int]$Rev, [bool]$Gate, [string]$GateWhy) {
    $tag = "r{0:D3}" -f $Rev
    if (-not $Gate) {
        Skip "${Id}_commit_$ModelLabel" $GateWhy; Skip "${Id}b_stage_$tag" $GateWhy
        return (Deploy-Chain $tag $false $GateWhy)
    }
    $ok = Py-Step "${Id}_commit_$ModelLabel" "$Regen commit --model `"$Models\$ModelFile`" --target `"$Target`" --label $ModelLabel" "commit_$tag.json"
    if (-not $ok) { Skip "${Id}b_stage_$tag" "${Id}_commit FAILED"; return (Deploy-Chain $tag $false "${Id}_commit FAILED") }
    $ok = Py-Step "${Id}b_stage_$tag" "$Regen stage --revision $Rev --out `"$RunRoot\deploy\$tag`"" "stage_$tag.json"
    return (Deploy-Chain $tag $ok "${Id}b_stage $(if ($ok) { 'PASS' } else { 'FAILED' })")
}

# ---------- F00 preflight + self-tests ----------
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$hashes = [ordered]@{}
foreach ($f in @($Target, $Scenario) + @(Get-ChildItem $Models -Filter *.json | Sort-Object Name | ForEach-Object { $_.FullName })) {
    $hashes[(Split-Path $f -Leaf)] = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
}
$refOrder = $null; if (Test-Path $Ref) { $refOrder = (Read-Result $Ref).real32_ordering.name }
$pre = Add-Record "F00_preflight" ($(if ($refOrder) { "INFO" } else { "BLOCKED" })) ($(if ($refOrder) { "environment facts" } else { "S3 measured REAL32 reference missing: $Ref" })) ([ordered]@{
    elevated = $elevated; softplc_service = (Get-Service $Service).Status.ToString()
    tcp_502 = Listening 502; tcp_11740 = Listening 11740; tcp_1217 = Listening 1217
    input_sha256 = $hashes; s3_reference = $Ref; s3_reference_real32_ordering = $refOrder
    mcp_used = $false; llm_used = $false; temp_patch_used = $false; gui_automation_used = $false; old_poc_used = $false
    physical_plc_used = $false })
$t3 = Py-Step "F00b_s3_engine_selftest" "`"$S3\engine\test_engine.py`"" "s3_engine_selftest.json" 120
$t6 = Py-Step "F00c_s6_revision_selftest" "`"$Src\engine\test_revision.py`"" "s6_revision_selftest.json" 180
$gate = [bool]$refOrder -and $t3 -and $t6
$why = "F00 gate (reference=$([bool]$refOrder), s3_selftest=$t3, s6_selftest=$t6)"

# ---------- F01-F06: V1 -> r001 ----------
$v1 = Commit-And-Deploy "F01" "v1.json" "V1" 1 $gate $why
$why1 = "r001 deploy chain $(if ($v1) { 'PASS' } else { 'FAILED' })"

# ---------- F07-F08: V2 -> r002 (add ReturnTemp) ----------
$v2 = Commit-And-Deploy "F07" "v2.json" "V2" 2 $v1 $why1
$why2 = "r002 deploy chain $(if ($v2) { 'PASS' } else { 'FAILED' })"
$storeOk = Test-Path (Join-Path $EngRoot "revisions\r002\manifest.json")

# ---------- F09 diff + F10 stability (r001 -> r002) ----------
if ($storeOk) {
    foreach ($n in 1, 2) { Py-Step ("F09_diff_r{0:D3}" -f $n) "$Check diff --revision $n --scenario `"$Scenario`"" ("diff_r{0:D3}.json" -f $n) | Out-Null }
    Py-Step "F10_stability_r001_r002" "$Check stability --from 1 --to 2 --deployed-a `"$RunRoot\deploy\r001`" --deployed-b `"$RunRoot\deploy\r002`"" "stability_r001_r002.json" | Out-Null
} else { Skip "F09_diff" "r002 not in store"; Skip "F10_stability_r001_r002" "r002 not in store" }

# ---------- F11 rollback V2 -> V1 ----------
if ($v2) {
    $ok = Py-Step "F11a_rollback_to_r001" "$Regen rollback --to 1 --out `"$RunRoot\deploy\rollback_r001`"" "rollback_r001.json"
    $rb = Deploy-Chain "rollback_r001" $ok "F11a_rollback $(if ($ok) { 'PASS' } else { 'FAILED' })"
    if ($rb) {
        Py-Step "F11j_rollback_compare" "$Check rollback-compare --revision 1 --a `"$RunRoot\deploy\r001`" --b `"$RunRoot\deploy\rollback_r001`"" "rollback_compare.json" | Out-Null
    } else { Skip "F11j_rollback_compare" "rollback deploy chain FAILED" }
} else { Skip "F11a_rollback_to_r001" $why2; $rb = Deploy-Chain "rollback_r001" $false $why2; Skip "F11j_rollback_compare" $why2 }

# ---------- F12 invalid revisions (store must stay intact) ----------
if ($storeOk) {
    Py-Step "F12_invalid_revisions" "$Check invalid --base `"$Models\v2.json`" --target `"$Target`" --work `"$RunRoot\work\invalid`"" "invalid_revisions.json" 300 | Out-Null
} else { Skip "F12_invalid_revisions" "r002 not in store" }

# ---------- F14 V3 -> r003 (remove FanSpeed) ----------
$v3 = Commit-And-Deploy "F14" "v3.json" "V3" 3 ($v2 -and $rb) "$why2 / rollback $(if ($rb) { 'PASS' } else { 'FAILED' })"
if (Test-Path (Join-Path $EngRoot "revisions\r003\manifest.json")) {
    Py-Step "F14h_diff_r003" "$Check diff --revision 3 --scenario `"$Scenario`"" "diff_r003.json" | Out-Null
    Py-Step "F14i_stability_r002_r003" "$Check stability --from 2 --to 3 --deployed-a `"$RunRoot\deploy\r002`" --deployed-b `"$RunRoot\deploy\r003`"" "stability_r002_r003.json" | Out-Null
} else { Skip "F14h_diff_r003" "r003 not in store"; Skip "F14i_stability_r002_r003" "r003 not in store" }

# ---------- F15 V4 breaking type change (policy A: block; approved -> reallocate) ----------
if (Test-Path (Join-Path $EngRoot "revisions\r003\manifest.json")) {
    Py-Step "F15a_v4_type_change_blocked" "$Check expect-reject --model `"$Models\v4_type_change.json`" --target `"$Target`" --label V4_type_change --code BREAKING_CHANGE_REQUIRES_APPROVAL --text TYPE_CHANGED" "v4_type_change.json" | Out-Null
    Py-Step "F15b_v4_approved_capacity" "$Check expect-reject --model `"$Models\v4_type_change_approved.json`" --target `"$Target`" --label V4_type_change_approved --code ALLOCATION --text `"free register`"" "v4_type_change_approved.json" | Out-Null
} else { Skip "F15a_v4_type_change_blocked" "r003 not in store"; Skip "F15b_v4_approved_capacity" "r003 not in store" }

# ---------- F16 V5 -> r004 (equipment AHU-02) ----------
$v5 = Commit-And-Deploy "F16" "v5_equipment.json" "V5" 4 $v3 "r003 deploy chain $(if ($v3) { 'PASS' } else { 'FAILED' })"
if (Test-Path (Join-Path $EngRoot "revisions\r004\manifest.json")) {
    Py-Step "F16h_diff_r004" "$Check diff --revision 4 --scenario `"$Scenario`"" "diff_r004.json" | Out-Null
    Py-Step "F16i_stability_r003_r004" "$Check stability --from 3 --to 4 --deployed-a `"$RunRoot\deploy\r003`" --deployed-b `"$RunRoot\deploy\r004`"" "stability_r003_r004.json" | Out-Null
    # ---------- F17 V6 direction changes ----------
    Py-Step "F17a_v6_direction_breaking" "$Check expect-reject --model `"$Models\v6_direction_breaking.json`" --target `"$Target`" --label V6_direction_breaking --code BREAKING_CHANGE_REQUIRES_APPROVAL --text DIRECTION_CHANGED" "v6_direction_breaking.json" | Out-Null
    Py-Step "F17b_v6_direction_nonbreaking" "$Check dry-run-check --model `"$Models\v6_direction_nonbreaking.json`" --target `"$Target`" --label V6_direction_nonbreaking --identity AHU-DEMO/AHU-02/Setpoint --type DIRECTION_CHANGED --action PRESERVED" "v6_direction_nonbreaking.json" | Out-Null
} else { foreach ($s in "F16h_diff_r004", "F16i_stability_r003_r004", "F17a_v6_direction_breaking", "F17b_v6_direction_nonbreaking") { Skip $s "r004 not in store" } }

# ---------- F13 reproduction (all revisions, twice) + F18 store integrity ----------
if (Test-Path (Join-Path $EngRoot "revisions\index.json")) {
    Py-Step "F13_reproduce_all" "$Check repro --out `"$RunRoot\repro`"" "repro.json" 300 | Out-Null
    Py-Step "F18_store_integrity" "$Check integrity" "integrity.json" | Out-Null
} else { Skip "F13_reproduce_all" "no store"; Skip "F18_store_integrity" "no store" }

$Prefix = ""
Add-Record "F19_post_state" "INFO" "post-run facts" ([ordered]@{
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
