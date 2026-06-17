# obfsnproxy — RKN blocklist Bloom filter

This repo builds **`rkn.bloom`**, a compact [Bloom filter](https://en.wikipedia.org/wiki/Bloom_filter)
of domains in the Russian RKN (Roskomnadzor) blocked-sites registry. The
[OBFSN](https://obfsn.com) proxy extension downloads this single file and checks domains
**locally and offline** — it never sends the domains you visit to any server.

## Why a Bloom filter?

The full RKN registry is ~1M domains (tens of MB). A Bloom filter compresses that to
**~1.5 MB** while answering "is this domain in the list?" in microseconds, entirely
client-side. The tradeoff: a small false-positive rate (~0.5%) — it may occasionally say
"listed" for a domain that isn't. It **never** misses a domain that is listed.

## How it works

- A daily [GitHub Action](.github/workflows/build-bloom.yml) runs
  [`scripts/build_bloom.py`](scripts/build_bloom.py), which downloads the source lists,
  normalizes domains, builds the filter, and publishes it as the asset on the stable
  `latest` release.
- The extension fetches the filter from the stable URL and caches it:

  ```
  https://github.com/bymakk/obfsnproxy/releases/latest/download/rkn.bloom
  ```

The exact binary format and hashing are documented in [SPEC.md](SPEC.md) so any client
(JS, Python, Go, …) can read it.

## Sources

| Source | Role | Notes |
| --- | --- | --- |
| [antizapret `domains-export.txt`](https://antizapret.prostovpn.org/domains-export.txt) | primary | fresh (updated several times/day), curated, bare domains |
| [zapret-info/z-i `dump.csv.gz`](https://github.com/zapret-info/z-i) | backfill | full registry incl. wildcards/IDN; best-effort |

The two are **unioned**. If the backfill source is unreachable, the build still ships the
primary list.

## Local build

```sh
pip install -r requirements.txt
python scripts/build_bloom.py   # writes dist/rkn.bloom
```

## Data & license

The underlying data is the public RKN registry (a government fact-list). Neither upstream
source ships an explicit license. This repository's **code** is provided as-is; the
**blocklist data** is redistributed best-effort with attribution to the sources above and
carries no warranty. Use at your own risk.
