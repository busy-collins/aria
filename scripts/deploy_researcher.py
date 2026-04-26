#!/usr/bin/env python3
"""
Project-level script to deploy the Aria Researcher service.
Run from the project root: uv run scripts/deploy_researcher.py
"""
import subprocess
import sys
from pathlib import Path

researcher_dir = Path(__file__).parent.parent / "backend" / "researcher"

result = subprocess.run(
    [sys.executable, "deploy.py"],
    cwd = researcher_dir
)

sys.exit(result.returncode)