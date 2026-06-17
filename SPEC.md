# `rkn.bloom` format specification (v1)

A Bloom filter of RKN-blocked domains. Built by `scripts/build_bloom.py`, consumed
by the OBFSN extension. This file is the **single source of truth** for the binary
format and the hashing — the Python generator and the TypeScript client MUST agree
byte-for-byte and bit-for-bit.

## File layout

```
offset  size  field      type            notes
0       4     magic      bytes            ASCII "BLOM" (0x42 0x4C 0x4F 0x4D), in order
4       4     version    uint32 LE        currently 1
8       4     m          uint32 LE        number of bits in the bit array
12      4     k          uint32 LE        number of hash functions
16      4     n          uint32 LE        number of domains inserted (informational)
20      ceil(m/8)  bits  raw bytes        the bit array, LSB-first within each byte
```

Total size = 20 + ceil(m/8) bytes. All header integers are **little-endian**.
The reader MUST validate `magic == "BLOM"` and `version == 1`, then read `m` and `k`
from the header (they are NOT hardcoded — the generator may change them as the list grows).

### Bit addressing (LSB-first)

Bit index `i` lives in `bits[i >> 3]` at position `i & 7`, least-significant bit first:

```
set:  bits[i >> 3] |= (1 << (i & 7))
test: (bits[i >> 3] >> (i & 7)) & 1
```

## Domain normalization (applied identically on both sides before hashing)

1. Trim surrounding whitespace and `"` quotes.
2. Lowercase.
3. Strip a trailing `.`.
4. Strip a leading `*.` (wildcard entries `*.example.com` are stored as `example.com`).
5. If the domain contains non-ASCII characters, convert to punycode (IDNA → `xn--…`).
   (Chrome already reports IDN hosts as punycode, so the client rarely needs this step.)
6. Reject if empty, has no `.`, or contains characters outside `[a-z0-9.-]`.

The generator stores the registrable/blocked domain. The **client** tests the host AND
its parent domains (walking left-label-stripping down to 2 labels), so a stored
`example.com` also matches `cdn.example.com`.

## Hashing (double hashing, Kirsch–Mitzenmacher)

Input is the UTF-8 bytes of the normalized domain (ASCII in practice).

Two independent 32-bit hashes:

```
FNV-1a (32-bit):   h = 0x811C9DC5
                   for each byte b: h = ((h XOR b) * 0x01000193) mod 2^32

djb2a  (32-bit):   h = 5381
                   for each byte b: h = ((h * 33) XOR b) mod 2^32
```

Then, with `h1 = fnv1a32(domain)` and `h2 = djb2a(domain) | 1` (forced odd):

```
for i in 0 .. k-1:
    pos = (h1 + i * h2) mod m      # computed as an exact integer (< 2^53), then mod m
    set/test bit at pos
```

`h1 + i*k*h2` stays below 2^53 for any realistic `k`, so the client can use plain
JS `Number` arithmetic (no BigInt) and still match Python's exact integer math.

## Sizing (generator side)

Given `n` domains and target false-positive rate `p` (default `p = 0.005`):

```
m = ceil(-n * ln(p) / (ln 2)^2)     rounded up to a multiple of 8
k = max(1, round((m / n) * ln 2))
```

At `p = 0.005` this is ≈ 11.03 bits/element and `k = 8`.

## Membership semantics

- "present" → the domain (or a parent it inherits a block from) is in the RKN registry
  **as captured by the source lists** — treat as an informational signal, not ground truth.
- Bloom filters have false positives (≈ `p` per test, compounded slightly by the parent walk)
  but **never** false negatives for a domain that was actually inserted.
