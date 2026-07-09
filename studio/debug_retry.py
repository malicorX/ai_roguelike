from pathlib import Path

from studio.orchestrator import (
    blocked_cycle_for_retry,
    next_cycle_number,
    next_cycle_number_until_green,
)

state_dir = Path("studio/state")
print("blocked_cycle_for_retry:", blocked_cycle_for_retry(state_dir))
print("next_cycle_number_until_green:", next_cycle_number_until_green(state_dir, until_green=True))
print("next_cycle_number:", next_cycle_number(state_dir))
