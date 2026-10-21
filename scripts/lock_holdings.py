#!/usr/bin/env python3
"""Lock (encrypt) holdings.csv -> holdings.csv.age using the public key in holdings.pub.
Anyone can lock; only the HOLDINGS_KEY secret in GitHub can unlock.

  python scripts/lock_holdings.py path/to/holdings.csv
"""
import sys
from pathlib import Path
import pyrage
from pyrage import x25519

ROOT = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "holdings.csv"
data = src.read_bytes()
if not data.lstrip().startswith(b"account,ticker"):
    raise SystemExit("This doesn't look like a holdings file (first line should start with 'account,ticker').")
recipient = x25519.Recipient.from_str((ROOT / "holdings.pub").read_text().strip())
(ROOT / "holdings.csv.age").write_bytes(pyrage.encrypt(data, [recipient]))
print(f"Locked {len(data.splitlines()) - 1} holdings -> holdings.csv.age")
