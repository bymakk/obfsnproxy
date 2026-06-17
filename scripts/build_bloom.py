#!/usr/bin/env python3
"""Build dist/rkn.bloom — a Bloom filter of RKN-blocked domains.

See SPEC.md for the exact binary format and hashing. The TypeScript client in the
OBFSN extension must stay byte/bit compatible with this file.

Sources (unioned):
  * PRIMARY  antizapret domains-export.txt  — fresh, curated, ~132K bare domains.
  * BACKFILL zapret-info/z-i dump.csv.gz     — complete registry incl. wildcards/IDN
             (~982K domains); best-effort — if it fails or is unreachable we still
             ship the primary list.
"""

import gzip
import math
import os
import re
import struct
import sys
import urllib.request

ANTIZAPRET_URL = "https://antizapret.prostovpn.org/domains-export.txt"
ZI_URL = "https://raw.githubusercontent.com/zapret-info/z-i/master/dump.csv.gz"

TARGET_FPR = 0.001  # 0.1% — keeps the client's compounded false-positive rate low
USER_AGENT = "obfsn-bloom-builder/1 (+https://github.com/bymakk/obfsnproxy)"
OUT_PATH = os.path.join("dist", "rkn.bloom")

MAGIC = b"BLOM"
VERSION = 1

_VALID = re.compile(r"^[a-z0-9.\-]+$")


# --------------------------------------------------------------------------- fetch
def fetch_bytes(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# --------------------------------------------------------------------- normalization
def normalize(raw: str):
    """Return a canonical ASCII domain, or None if it should be skipped."""
    d = raw.strip().strip('"').strip().lower().rstrip(".")
    if d.startswith("*."):
        d = d[2:]
    if not d or "/" in d or " " in d or ".." in d or "." not in d:
        return None
    if any(ord(c) > 127 for c in d):
        try:
            import idna  # IDNA2008, handles .рф etc.

            d = idna.encode(d).decode("ascii").lower()
        except Exception:
            try:
                d = d.encode("idna").decode("ascii").lower()
            except Exception:
                return None
    if not _VALID.match(d):
        return None
    return d


# --------------------------------------------------------------------------- sources
def load_antizapret(domains: set) -> int:
    text = fetch_bytes(ANTIZAPRET_URL).decode("utf-8", errors="replace")
    added = 0
    for line in text.splitlines():
        d = normalize(line)
        if d:
            if d not in domains:
                added += 1
            domains.add(d)
    return added


def load_zi(domains: set) -> int:
    """Best-effort: parse the full z-i registry dump. Returns count of NEW domains."""
    raw = fetch_bytes(ZI_URL)
    text = gzip.decompress(raw).decode("cp1251", errors="replace")
    before = len(domains)
    lines = text.split("\n")
    # First physical line is an "Updated: ..." timestamp header — skip it.
    for line in lines[1:]:
        if not line:
            continue
        # Column layout: ip;domain;url;authority;decision;date — but the authority
        # field can contain unescaped ';', so only the first few fields are reliable.
        parts = line.split(";")
        if len(parts) < 2:
            continue
        d = normalize(parts[1])
        if d:
            domains.add(d)
        # Also pull the host out of any blocked URLs (col 3); adds ~handful of domains.
        if len(parts) >= 3 and parts[2]:
            for u in parts[2].split("|"):
                m = re.match(r"^\s*https?://([^/:?#]+)", u.strip())
                if m:
                    hd = normalize(m.group(1))
                    if hd:
                        domains.add(hd)
    return len(domains) - before


# ------------------------------------------------------------------------------ hash
def fnv1a32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def djb2a(data: bytes) -> int:
    h = 5381
    for b in data:
        h = ((h * 33) ^ b) & 0xFFFFFFFF
    return h


# ----------------------------------------------------------------------------- build
def optimal_m(n: int, p: float) -> int:
    m = math.ceil(-n * math.log(p) / (math.log(2) ** 2))
    m = max(m, 1024)
    return (m + 7) & ~7  # round up to a multiple of 8


def optimal_k(m: int, n: int) -> int:
    return max(1, round((m / n) * math.log(2)))


def build(domains: set) -> bytes:
    n = len(domains)
    if n == 0:
        raise SystemExit("ERROR: no domains collected — refusing to build an empty filter")
    m = optimal_m(n, TARGET_FPR)
    k = optimal_k(m, n)
    nbytes = (m + 7) // 8
    bits = bytearray(nbytes)

    for d in domains:
        data = d.encode("utf-8")
        h1 = fnv1a32(data)
        h2 = djb2a(data) | 1
        for i in range(k):
            pos = (h1 + i * h2) % m
            bits[pos >> 3] |= 1 << (pos & 7)

    # Estimated FPR for reporting: (1 - e^(-k*n/m))^k
    est_fpr = (1 - math.exp(-k * n / m)) ** k
    print(f"  n={n:,}  m={m:,} bits ({nbytes:,} bytes)  k={k}  est. FPR={est_fpr*100:.3f}%")

    header = MAGIC + struct.pack("<IIII", VERSION, m, k, n)
    return bytes(header) + bytes(bits)


# ------------------------------------------------------------------------------ main
def main() -> int:
    domains: set = set()

    print(f"Fetching primary source: {ANTIZAPRET_URL}")
    try:
        added = load_antizapret(domains)
        print(f"  antizapret: +{added:,} domains (total {len(domains):,})")
    except Exception as e:
        print(f"  FATAL: primary source failed: {e}", file=sys.stderr)
        return 1

    print(f"Fetching backfill source: {ZI_URL}")
    try:
        added = load_zi(domains)
        print(f"  z-i: +{added:,} new domains (total {len(domains):,})")
    except Exception as e:
        print(f"  WARN: backfill source skipped: {e}", file=sys.stderr)

    print("Building Bloom filter...")
    blob = build(domains)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(blob)
    print(f"Wrote {OUT_PATH} ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
