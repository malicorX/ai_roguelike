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
  [switch]$ApplyWrites
)

$ErrorActionPreference = "Stop"

$dryRunArg = if ($FullLoop) { "" } else { "--dry-run" }
$applyWritesArg = if ($ApplyWrites) { "--apply-writes" } else { "" }
$orchestratorCommand = "python3 -m studio.orchestrator --time '$Time' --max-cycles $MaxCycles --deploy '$Deploy' --evaluation-target '$EvaluationTarget' --director-mode '$DirectorMode' --role-timeout-seconds $RoleTimeoutSeconds --models '$ModelAssignments' $dryRunArg $applyWritesArg"
$remoteCommand = @(
  "cd ~/ai_roguelike"
  'export XDG_RUNTIME_DIR=/run/user/$UID'
  "mkdir -p studio/state"
  $orchestratorCommand
) -join "; "

$modeMessage = if ($ApplyWrites) {
  "Running Phase 1 write loop: Builder diffs apply on feature branches and merge on green sparky2 evaluation."
} elseif ($FullLoop) {
  "Running Phase 1 pilot loop: Director and Builder write artifacts; repository code writes remain disabled."
} else {
  "Running safe Phase 0 dry-run. Use -FullLoop for the bounded Phase 1 pilot loop."
}
Write-Host "Starting ai_roguelike studio on sparky1..."
Write-Host $modeMessage

ssh sparky1 $remoteCommand
