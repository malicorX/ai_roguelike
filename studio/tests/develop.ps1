param(
  [string]$Time = "100h",
  [int]$MaxCycles = 1,
  [string]$EvaluationTarget = "sparky2",
  [string]$DirectorMode = "model",
  [int]$RoleTimeoutSeconds = 900,
  [ValidateSet("Auto", "NvidiaFirst", "LocalOnly")]
  [string]$ModelMode = "Auto",
  [Alias("Models")]
  [string]$ModelAssignments = "enemy_designer=nvidia:nvidia/nemotron-3-nano-30b-a3b,systems_designer=nvidia:nvidia/nemotron-3-nano-30b-a3b,art_director_concept=nvidia:nvidia/nemotron-3-nano-30b-a3b,qa_critic=nvidia:nvidia/nemotron-3-nano-30b-a3b,director=nvidia:nvidia/nemotron-3-nano-30b-a3b,designer=nvidia:nvidia/nemotron-3-nano-30b-a3b,builder=nvidia:nvidia/nemotron-3-nano-30b-a3b,reviewer=nvidia:nvidia/nemotron-3-nano-30b-a3b,art_director=nvidia:nvidia/nemotron-3-nano-30b-a3b,player=nvidia:nvidia/nemotron-3-nano-30b-a3b",
  [switch]$ProposalOnly,
  [switch]$DryRun,
  [switch]$NoDeploy,
  [switch]$Detached,
  [switch]$SingleCycle,
  [switch]$FullLoop,
  [switch]$ApplyWrites
)

$ErrorActionPreference = "Stop"

# Default: one full studio cycle with writes, deploy, and until-green retries.
# Advanced: -ProposalOnly, -DryRun, -NoDeploy, -Detached, -SingleCycle (no retry loop).
$isProposalOnly = $ProposalOnly
$isDryRun = $DryRun -and -not $ProposalOnly
$applyWrites = if ($ApplyWrites -or $FullLoop) { $true } elseif ($isProposalOnly -or $isDryRun) { $false } else { $true }
$deployTarget = if ($NoDeploy -or $isProposalOnly -or $isDryRun) { "false" } else { "theebie" }
$untilGreen = -not $SingleCycle -and -not $isDryRun

$preferNvidiaEnv = switch ($ModelMode) {
  "NvidiaFirst" { "STUDIO_PREFER_NVIDIA=nvidia-first" }
  "LocalOnly" { "STUDIO_PREFER_NVIDIA=local-only" }
  default { "STUDIO_PREFER_NVIDIA=auto" }
}
if ($ModelMode -eq "LocalOnly") {
  $ModelAssignments = "enemy_designer=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,systems_designer=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,art_director_concept=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,qa_critic=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,director=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,designer=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,builder=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,reviewer=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,art_director=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest,player=hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest"
}

$dryRunArg = if ($isDryRun) { "--dry-run" } else { "" }
$applyWritesArg = if ($applyWrites) { "--apply-writes" } else { "" }
$proposalOnlyArg = if ($isProposalOnly) { "--proposal-only" } else { "" }
$untilGreenArg = if ($untilGreen) { "--until-green" } else { "--single-cycle" }
$orchestratorCommand = "set -a; for f in ~/.config/ai_roguelike/env ~/ai_roguelike/.env; do [ -f `"`$f`" ] && . `"`$f`"; done; set +a; env PYTHONUNBUFFERED=1 $preferNvidiaEnv python3 -u -m studio.orchestrator --time '$Time' --max-cycles $MaxCycles --deploy '$deployTarget' --evaluation-target '$EvaluationTarget' --director-mode '$DirectorMode' --role-timeout-seconds $RoleTimeoutSeconds --models '$ModelAssignments' $dryRunArg $applyWritesArg $proposalOnlyArg $untilGreenArg"
$remoteCommand = if ($Detached) {
  @(
    "cd ~/ai_roguelike"
    'export XDG_RUNTIME_DIR=/run/user/$UID'
    "mkdir -p studio/state"
    "rm -f studio/state/STOP"
    "nohup $orchestratorCommand > ~/ai_roguelike/studio/state/loop.log 2>&1 < /dev/null & echo `$! > ~/ai_roguelike/studio/state/loop.pid"
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

$modeMessage = if ($isProposalOnly) {
  if ($untilGreen) {
    "Proposal-only until green: specialists pitch and critique until QA passes."
  } else {
    "Proposal-only: specialists pitch and critique; no Director/Builder writes."
  }
} elseif ($isDryRun) {
  "Dry-run: evaluation only; no code writes or deploy."
} elseif ($applyWrites -and $deployTarget -ne "false") {
  if ($untilGreen) {
    "Full studio cycle until green: proposals -> Director -> Builder -> evaluation -> merge -> deploy (retries on block)."
  } else {
    "Full studio cycle: proposals -> Director -> Builder -> evaluation -> merge -> deploy."
  }
} elseif ($applyWrites) {
  "Write cycle: proposals -> Director -> Builder -> evaluation -> merge (no deploy)."
} else {
  "Pilot loop: agents write artifacts; repository code writes remain disabled."
}
Write-Host "Starting ai_roguelike studio on sparky1..."
Write-Host $modeMessage
Write-Host "At the end: short summary in this window; full expandable story on the devlog."
if ($Detached) {
  Write-Host "Detached mode: loop keeps running on sparky1 after this shell exits. Stop with: ssh sparky1 'touch ~/ai_roguelike/studio/state/STOP'"
}

ssh sparky1 $remoteCommand
