#!/usr/bin/env python
"""Command wrapper: verify-monitoring"""
import sys
from pathlib import Path

# Ensure project root is in path
_scripts_dir = Path(__file__).parent
_project_root = _scripts_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from cli.cli import main

if __name__ == '__main__':
    sys.exit(main(['verify-monitoring'] + sys.argv[1:]))

