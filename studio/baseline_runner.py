#!/usr/bin/env python3
"""Execute baseline gates on commit to capture pass/fail status."""
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent

def run_command(cmd: str) -> bool:
    """Run a command in the root directory and return True if exit code is 0."""
    print(f"Running: {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"✅ Success: {cmd}")
    else:
        print(f"❌ Failed: {cmd}")
        print(result.stderr)
    return result.returncode == 0

def main():
    if not run_command("npm test"):
        sys.exit(1)
    if not run_command("npm run build"):
        sys.exit(1)
    if not run_command("npm run smoke"):
        sys.exit(1)
    
    print("All baseline gates passed.")
