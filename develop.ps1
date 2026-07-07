param(
  [string]$Time = "30m",
  [int]$MaxCycles = 1,
  [string]$Deploy = "false",
  [string]$EvaluationTarget = "sparky2",
  [string]$Models = "director=agents-a1,builder=agents-a1,reviewer=agents-a1,art_director=agents-a1,player=agents-a1",
  [switch]$FullLoop
)

$ErrorActionPreference = "Stop"

$dryRunArg = if ($FullLoop) { "" } else { "--dry-run" }
$remoteCommand = @"
cd ~/ai_roguelike
export XDG_RUNTIME_DIR=/run/user/`$(id -u)
mkdir -p studio/state
python3 -m studio.orchestrator --time "$Time" --max-cycles $MaxCycles --deploy "$Deploy" --evaluation-target "$EvaluationTarget" --models "$Models" $dryRunArg
"@

Write-Host "Starting ai_roguelike studio on sparky1..."
if (-not $FullLoop) {
  Write-Host "Running safe Phase 0 dry-run. Use -FullLoop only after the autonomous loop is enabled."
}

ssh sparky1 $remoteCommand
