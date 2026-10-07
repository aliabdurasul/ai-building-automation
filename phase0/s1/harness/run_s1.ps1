# S1 measurement harness. Executes existing POC scripts unchanged (path constants relocated only),
# with timeouts, and records raw facts. It does NOT decide PASS/FAIL.
param(
    [Parameter(Mandatory = $true)][ValidateSet("run1", "run2")][string]$Run
)
$ErrorActionPreference = "Stop"

$Repo      = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Poc       = "C:\AI_BMS_POC"
$Stage     = "C:\AI_BMS_PHASE0\s1\$Run"
$CdsStage  = Join-Path $Stage "codesys"
$MsSandbox = "C:\AI_BMS_POC\master_scada_research\hmi_api_poc"
$MsStage   = Join-Path $MsSandbox "phase0_s1\$Run"
$Ev        = Join-Path $Repo "docs\phase0\evidence\$Run"
$Codesys   = "C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe"
$Profile   = "CODESYS V3.5 SP22 Patch 3"
$MsHost    = Join-Path $MsSandbox "host\AiBmsHmiPoc.exe"
$Spec      = Join-Path $MsSandbox "specs\ahu_01_test_v3.json"
$ProjName  = "AHU_S1"

$steps = New-Object System.Collections.ArrayList

function Now { (Get-Date).ToString("o") }

function New-FileSnapshot([string[]]$roots) {
    $h = @{}
    foreach ($r in $roots) {
        if (Test-Path $r) {
            Get-ChildItem $r -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $h[$_.FullName] = $_.LastWriteTimeUtc.Ticks }
        }
    }
    return $h
}

function Get-NewFiles($before, [string[]]$roots) {
    $after = New-FileSnapshot $roots
    $list = @()
    foreach ($k in $after.Keys) {
        if (-not $before.ContainsKey($k) -or $before[$k] -ne $after[$k]) { $list += $k }
    }
    return @($list | Sort-Object)
}

function Get-PortState {
    $l = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 502 })
    return [bool]($l.Count -gt 0)
}

function Invoke-Step {
    param([string]$Id, [string]$Purpose, [string]$Exe, [string]$Arguments, [int]$TimeoutSec, [string]$WorkDir = $Stage)
    $out = Join-Path $Ev "$Id.stdout.txt"
    $err = Join-Path $Ev "$Id.stderr.txt"
    $before = New-FileSnapshot @($Stage, $MsStage)
    $start = Get-Date
    Write-Host "[$Id] $Purpose"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    $null = $p.Start()
    $so = $p.StandardOutput.ReadToEndAsync()
    $se = $p.StandardError.ReadToEndAsync()
    $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) {
        & taskkill.exe /PID $p.Id /T /F | Out-Null
        $p.WaitForExit(15000) | Out-Null
    }
    $exit = $null
    try { $exit = $p.ExitCode } catch { $exit = $null }
    [System.IO.File]::WriteAllText($out, $so.Result)
    [System.IO.File]::WriteAllText($err, $se.Result)
    $end = Get-Date
    $rec = [ordered]@{
        step             = $Id
        purpose          = $Purpose
        timestamp_start  = $start.ToString("o")
        timestamp_end    = $end.ToString("o")
        duration_seconds = [math]::Round(($end - $start).TotalSeconds, 1)
        command          = "`"$Exe`" $Arguments"
        exit_code        = $exit
        timed_out        = $timedOut
        timeout_seconds  = $TimeoutSec
        stdout_file      = $out
        stderr_file      = $err
        created_or_modified_files = @(Get-NewFiles $before @($Stage, $MsStage))
        manual_intervention = $false
    }
    [void]$steps.Add($rec)
    Write-Host "[$Id] exit=$exit timedOut=$timedOut dur=$($rec.duration_seconds)s"
    return $rec
}

function Add-Fact([string]$Id, [string]$Purpose, $Data) {
    $rec = [ordered]@{ step = $Id; purpose = $Purpose; timestamp_start = (Now); data = $Data; manual_intervention = $false }
    [void]$steps.Add($rec)
    Write-Host "[$Id] $Purpose"
    return $rec
}

function Copy-Relocated([string]$Src, [string]$Dst, [hashtable]$Map) {
    $text = [System.IO.File]::ReadAllText($Src)
    $orig = $text
    $hits = @()
    foreach ($k in $Map.Keys) {
        $n = ([regex]::Matches($text, [regex]::Escape($k))).Count
        if ($n -gt 0) { $hits += "$k -> $($Map[$k]) x$n"; $text = $text.Replace($k, $Map[$k]) }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dst) | Out-Null
    [System.IO.File]::WriteAllText($Dst, $text, (New-Object System.Text.UTF8Encoding($false)))
    return [ordered]@{
        source = $Src; target = $Dst
        source_sha256 = (Get-FileHash $Src -Algorithm SHA256).Hash
        target_sha256 = (Get-FileHash $Dst -Algorithm SHA256).Hash
        substitutions = $hits
    }
}

function Save-RunJson {
    $obj = [ordered]@{ run = $Run; stage = $Stage; ms_stage = $MsStage; evidence = $Ev; steps = $steps }
    $obj | ConvertTo-Json -Depth 8 | Out-File -Encoding utf8 (Join-Path $Ev "harness_$Run.json")
}

# ---------------- S00 preflight ----------------
if (Test-Path $Stage)   { throw "Staging not clean: $Stage exists" }
if (Test-Path $MsStage) { throw "Staging not clean: $MsStage exists" }
New-Item -ItemType Directory -Force -Path $Stage, $MsStage, $Ev | Out-Null

$pre = [ordered]@{
    tcp_502_listening   = Get-PortState
    codesys_ide_running = [bool](Get-Process CODESYS -ErrorAction SilentlyContinue)
    iwin32_running      = [bool](Get-Process IWIN32 -ErrorAction SilentlyContinue)
    softplc_x64_service = (Get-Service "CODESYS Control Win V3 - x64").Status.ToString()
    elevated            = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    mcp_used            = $false
    temp_patch_used     = $false
}
Add-Fact "S00_preflight" "Environment preflight" $pre | Out-Null
$plcPresent = $pre.tcp_502_listening

# ---------------- S01 staging ----------------
$cdsMap = @{
    "C:\AI_BMS_POC\demo" = $CdsStage
    "C:\AI_BMS_POC\simple_ahu_demo\AI_BMS_SIMPLE_AHU.project" = (Join-Path $CdsStage "AI_BMS_AHU_DEMO.project")
    "C:\AI_BMS_POC\simple_ahu_demo\logs" = (Join-Path $CdsStage "logs")
}
$copies = @()
$copies += Copy-Relocated "$Poc\demo\model\ahu01.json"                   (Join-Path $CdsStage "model\ahu01.json") $cdsMap
$copies += Copy-Relocated "$Poc\demo\generator\generate_st.py"           (Join-Path $CdsStage "generator\generate_st.py") $cdsMap
$copies += Copy-Relocated "$Poc\demo\scripts\codesys_generate_ahu.py"    (Join-Path $CdsStage "scripts\codesys_generate_ahu.py") $cdsMap
$copies += Copy-Relocated "$Poc\demo\scripts\codesys_verify.py"          (Join-Path $CdsStage "scripts\codesys_verify.py") $cdsMap
$copies += Copy-Relocated "$Poc\demo\scripts\codesys_runtime.py"         (Join-Path $CdsStage "scripts\codesys_runtime.py") $cdsMap
$copies += Copy-Relocated "$Poc\simple_ahu_demo\scripts\codesys_map_modbus_io.py" (Join-Path $CdsStage "scripts\codesys_map_modbus_io.py") $cdsMap
$copies += Copy-Relocated "$Poc\simple_ahu_demo\scripts\modbus_v2_probe.py"       (Join-Path $CdsStage "scripts\modbus_v2_probe.py") $cdsMap
New-Item -ItemType Directory -Force -Path (Join-Path $CdsStage "logs"), (Join-Path $CdsStage "generated") | Out-Null
Copy-Item $Spec (Join-Path $MsStage "ahu_01_test_v3.json")
$copies += [ordered]@{ source = $Spec; target = (Join-Path $MsStage "ahu_01_test_v3.json"); source_sha256 = (Get-FileHash $Spec -Algorithm SHA256).Hash; substitutions = @() }
$r = Add-Fact "S01_staging" "Create clean staging; copy POC inputs/scripts; relocate hardcoded root paths (string substitution only)" ([ordered]@{ copies = $copies })
$r.manual_intervention = $true
$r.manual_reason = "POC scripts hardcode C:\AI_BMS_POC paths; staging copies require literal path substitution (no logic change)."

# ---------------- CODESYS chain ----------------
$py = (Get-Command python).Source
Invoke-Step "S02_generate_st" "Deterministic ST generation from ahu01.json" $py "`"$CdsStage\generator\generate_st.py`"" 60 | Out-Null

$cdsArgs = "--culture=en --profile=`"$Profile`" --noUI --runscript="
Invoke-Step "S03_codesys_generate_build" "ScriptEngine: create project + device + PLC_PRG + task + build" $Codesys ($cdsArgs + "`"$CdsStage\scripts\codesys_generate_ahu.py`"") 300 | Out-Null
Invoke-Step "S04_codesys_verify" "ScriptEngine: reopen project, check generated symbols" $Codesys ($cdsArgs + "`"$CdsStage\scripts\codesys_verify.py`"") 180 | Out-Null
Invoke-Step "S05_codesys_clean_mapping" "ScriptEngine: clean Modbus I/O mapping on generated project (no MCP, no %TEMP% patch)" $Codesys ($cdsArgs + "`"$CdsStage\scripts\codesys_map_modbus_io.py`"") 300 | Out-Null
Invoke-Step "S06_codesys_online_attempt" "ScriptEngine: boot app + online login attempt (only agentless online path in POC)" $Codesys ($cdsArgs + "`"$CdsStage\scripts\codesys_runtime.py`"") 150 | Out-Null

$svcRes = [ordered]@{ before = (Get-Service "CODESYS Control Win V3 - x64").Status.ToString() }
try { Start-Service "CODESYS Control Win V3 - x64" -ErrorAction Stop; $svcRes.start = "ok" } catch { $svcRes.start = "error: " + $_.Exception.Message }
Start-Sleep -Seconds 3
$svcRes.after = (Get-Service "CODESYS Control Win V3 - x64").Status.ToString()
$svcRes.tcp_502_listening_after = Get-PortState
Add-Fact "S07_softplc_service_start" "Non-elevated SoftPLC service start (run_demo.ps1 behaviour)" $svcRes | Out-Null
$plcPresent = Get-PortState

if ($plcPresent) {
    Add-Fact "S08_modbus_probe" "SKIPPED: a PLC of unknown provenance is listening on 502; generated PLC was not downloaded" ([ordered]@{ skipped = $true }) | Out-Null
} else {
    Invoke-Step "S08_modbus_probe" "pymodbus external probe against 127.0.0.1:502" $py "`"$CdsStage\scripts\modbus_v2_probe.py`"" 90 | Out-Null
}

# ---------------- MasterSCADA chain ----------------
$prj = Join-Path $MsStage "projects"
Invoke-Step "S09_ms_create"   "MasterSCADA: create project via vendor .NET API" $MsHost "create `"$prj`" $ProjName `"$Ev\S09_ms_create.log`"" 240 $MsSandbox | Out-Null
Invoke-Step "S10_ms_modbus"   "MasterSCADA: workstation + Modbus TCP protocol/module/channels" $MsHost "modbus `"$prj`" $ProjName `"$Ev\S10_ms_modbus.log`"" 240 $MsSandbox | Out-Null
Invoke-Step "S11_ms_verify"   "MasterSCADA: fresh-process read-back verify of Modbus config" $MsHost "verify `"$prj`" $ProjName `"$Ev\S11_ms_verify.log`"" 240 $MsSandbox | Out-Null
Invoke-Step "S12_hmi_build"   "MasterSCADA HMI: window/controls/links from spec v3" $MsHost "hmibuild `"$prj`" $ProjName `"$MsStage\ahu_01_test_v3.json`" `"$Ev\S12_hmi_build.log`"" 240 $MsSandbox | Out-Null
Invoke-Step "S13_hmi_verify"  "MasterSCADA HMI: fresh-process persistence verify" $MsHost "hmiverify `"$prj`" $ProjName `"$MsStage\ahu_01_test_v3.json`" `"$Ev\S13_hmi_verify_evidence.json`" `"$Ev\S13_hmi_verify.log`"" 240 $MsSandbox | Out-Null

$rtLoc = Join-Path $MsStage "rt_copy"
New-Item -ItemType Directory -Force -Path $rtLoc | Out-Null
Copy-Item (Join-Path $prj $ProjName) (Join-Path $rtLoc $ProjName) -Recurse
Add-Fact "S14_rt_copy" "Byte copy of project for runtime test" ([ordered]@{ target = (Join-Path $rtLoc $ProjName) }) | Out-Null
Invoke-Step "S15_ms_runtime" "MasterSCADA debug runtime (EmulatorSession) read/write vs 127.0.0.1:502" $MsHost "runtime `"$rtLoc`" $ProjName `"$Ev\S15_ms_runtime_events.jsonl`" `"$Ev\S15_ms_runtime.log`"" 480 $MsSandbox | Out-Null

$hmiLoc = Join-Path $MsStage "rt_copy_hmi"
New-Item -ItemType Directory -Force -Path $hmiLoc | Out-Null
Copy-Item (Join-Path $prj $ProjName) (Join-Path $hmiLoc $ProjName) -Recurse
Add-Fact "S16a_rt_copy_hmi" "Byte copy of project for HMI runtime test" ([ordered]@{ target = (Join-Path $hmiLoc $ProjName) }) | Out-Null
Invoke-Step "S16_hmi_runtime" "MasterSCADA debug runtime with IncludeHMI (HTML5 generation), hold 20 s" $MsHost "hmiruntime `"$hmiLoc`" $ProjName 20 7 `"$Ev\S16_hmi_runtime_events.jsonl`" `"$Ev\S16_hmi_runtime.log`"" 480 $MsSandbox | Out-Null

# ---------------- post state ----------------
$post = [ordered]@{
    tcp_502_listening   = Get-PortState
    iwin32_left_running = @(Get-Process IWIN32 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    codesys_left_running = @(Get-Process CODESYS -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    softplc_x64_service = (Get-Service "CODESYS Control Win V3 - x64").Status.ToString()
}
Add-Fact "S17_post_state" "Post-run environment state" $post | Out-Null
Save-RunJson
Write-Host "DONE $Run"
