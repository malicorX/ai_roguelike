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
$orchestratorCommand = "python3 -m studio.orchestrator --time '$Time' --max-cycles $MaxCycles --deploy '$Deploy' --evaluation-target '$EvaluationTarget' --director-mode '$DirectorMode' --role-timeout-seconds $RoleTimeoutSeconds --models '$ModelAssignments' $dryRunArg"
$remoteCommand = @(
  "cd ~/ai_roguelike"
  'export XDG_RUNTIME_DIR=/run/user/$UID'
  "mkdir -p studio/state"
  $orchestratorCommand
) -join "; "

$modeMessage = if ($FullLoop) {
  "Running Phase 1 pilot loop: Director and Builder write artifacts; repository code writes remain disabled."
} else {
  "Running safe Phase 0 dry-run. Use -FullLoop for the bounded Phase 1 pilot loop."
}
Write-Host "Starting ai_roguelike studio on sparky1..."
Write-Host $modeMessage

ssh sparky1 $remoteCommand
