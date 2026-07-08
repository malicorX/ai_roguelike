param(
  [string]$Time = "30m",
  [int]$MaxCycles = 1,
  [string]$Deploy = "false",
  [string]$EvaluationTarget = "sparky2",
  [string]$DirectorMode = "model",
  [int]$RoleTimeoutSeconds = 600,
  [Alias("Models")]
  [string]$ModelAssignments = "",
  [switch]$FullLoop,
  [switch]$ApplyWrites,
  [switch]$Detached
)

$ErrorActionPreference = "Stop"

$dryRunArg = if ($FullLoop) { "" } else { "--dry-run" }
$applyWritesArg = if ($ApplyWrites) { "--apply-writes" } else { "" }
$orchestratorCommand = "PYTHONUNBUFFERED=1 python3 -u -m studio.orchestrator --time '$Time' --max-cycles $MaxCycles --deploy '$Deploy' --evaluation-target '$EvaluationTarget' --director-mode '$DirectorMode' --role-timeout-seconds $RoleTimeoutSeconds --models '$ModelAssignments' $dryRunArg $applyWritesArg"
$remoteCommand = if ($Detached) {
  @(
    "cd ~/ai_roguelike"
    'export XDG_RUNTIME_DIR=/run/user/$UID'
    "mkdir -p studio/state"
    "rm -f studio/state/STOP"
    "nohup $orchestratorCommand > ~/ai_roguelike/studio/state/loop.log 2>&1 < /dev/null &"
    'echo $! > ~/ai_roguelike/studio/state/loop.pid'
    'echo "launched loop pid $(cat ~/ai_roguelike/studio/state/loop.pid)"'
    "tail -n 20 ~/ai_roguelike/studio/state/loop.log"
  ) -join "; "
} else {
  @(
    "cd ~/ai_roguelike"
    'export XDG_RUNTIME_DIR=/run/user/$UID'
    "mkdir -p studio/state"
    $orchestratorCommand
  ) -join "; "
}

$modeMessage = if ($ApplyWrites) {
  "Running Phase 1 write loop: Builder diffs apply on feature branches and merge on green sparky2 evaluation."
} elseif ($FullLoop) {
  "Running Phase 1 pilot loop: Director and Builder write artifacts; repository code writes remain disabled."
} else {
  "Running safe Phase 0 dry-run. Use -FullLoop for the bounded Phase 1 pilot loop."
}
Write-Host "Starting ai_roguelike studio on sparky1..."
Write-Host $modeMessage
if ($Detached) {
  Write-Host "Detached mode: loop keeps running on sparky1 after this shell exits. Stop with: ssh sparky1 'touch ~/ai_roguelike/studio/state/STOP'"
}

ssh sparky1 $remoteCommand
