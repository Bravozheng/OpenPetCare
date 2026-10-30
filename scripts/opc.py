#!/usr/bin/env python3
"""Run OpenPetCare from a copied skill folder without installation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpetcare.cli import main

raise SystemExit(main())
