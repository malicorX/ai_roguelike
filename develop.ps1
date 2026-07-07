param(
  [string]$Time = "30m",
  [int]$MaxCycles = 1,
  [string]$Deploy = "false",
  [string]$EvaluationTarget = "sparky2",
  [string]$DirectorMode = "model",
  [int]$RoleTimeoutSeconds = 600,
  [Alias("Models")]
  [string]$ModelAssignments = "",
  [switch]$FullLoop
)

$ErrorActionPreference = "Stop"

$dryRunArg = if ($FullLoop) { "" } else { "--dry-run" }
$remoteCommand = "cd ~/ai_roguelike; export XDG_RUNTIME_DIR=/run/user/`$(id -u); mkdir -p studio/state; python3 -m studio.orchestrator --time '$Time' --max-cycles $MaxCycles --deploy '$Deploy' --evaluation-target '$EvaluationTarget' --director-mode '$DirectorMode' --role-timeout-seconds $RoleTimeoutSeconds --models '$ModelAssignments' $dryRunArg"

Write-Host "Starting ai_roguelike studio on sparky1..."
if (-not $FullLoop) {
  Write-Host "Running safe Phase 0 dry-run. Use -FullLoop only after the autonomous loop is enabled."
}

ssh sparky1 $remoteCommand
