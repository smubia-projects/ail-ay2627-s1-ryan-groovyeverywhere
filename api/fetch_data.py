"""Downloads the demo pool data files into api/data/ and checks their SHA-256 (used by the Dockerfile).

    python api/fetch_data.py <base URL> <name>=<sha256> [...]

The files are made by api/export_pool.py from Ryan's demo bundle and published as assets of a GitHub release on the
club's fork, so the repository itself holds no data (the project's rule: data stays out of git).
"""
import hashlib
import os
import sys
import urllib.request

base, pairs = sys.argv[1].rstrip("/"), sys.argv[2:]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(out, exist_ok=True)
for pair in pairs:
    name, want = pair.split("=", 1)
    path = os.path.join(out, name)
    with urllib.request.urlopen(f"{base}/{name}", timeout=120) as r, open(path, "wb") as f:
        h = hashlib.sha256()
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != want:
        sys.exit(f"{name}: SHA-256 {h.hexdigest()} does not match {want}")
    print(f"{name}: {os.path.getsize(path) / 1e6:.1f} MB, checksum ok")
