#!/usr/bin/env python3
"""Unlock holdings.csv.age -> holdings.csv using the HOLDINGS_KEY environment variable (a GitHub secret)."""
import os
from pathlib import Path
import pyrage
from pyrage import x25519

ROOT = Path(__file__).resolve().parent.parent
key = os.environ.get("HOLDINGS_KEY", "").strip()
if not key:
    raise SystemExit("::error::HOLDINGS_KEY secret is missing.")
try:
    data = pyrage.decrypt((ROOT / "holdings.csv.age").read_bytes(), [x25519.Identity.from_str(key)])
except Exception:
    raise SystemExit("::error::Could not unlock holdings.csv.age - check the HOLDINGS_KEY secret (copy the whole line).")
(ROOT / "holdings.csv").write_bytes(data)
print(f"Unlocked {len(data.splitlines()) - 1} holdings")
