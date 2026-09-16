# Contributing to OpenSEGY

## Running the tests

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

228 tests, no network, no fixtures on disk: every SEG-Y the suite reads is built
by `opensegy.synthetic` through the same field tables the parser reads through.
`python -m opensegy fixtures ./fixtures` writes the set out if you want files to
hand to another tool.

## Committing

Commits are timestamped in **America/Chicago**, not in the timezone of whatever
machine happens to build them. The development host runs in Europe, so a commit
made there without this would be stamped seven hours ahead — the wrong hour and
sometimes the wrong day.

Two aliases are configured in the repository for it:

```bash
git ci -m "..."        # instead of git commit
git tagv -a v0.2.0     # instead of git tag
```

They are ordinary local aliases that set `TZ` and nothing more. If you commit
some other way, set it yourself:

```bash
TZ=America/Chicago git commit -m "..."
```

Commits carry the GitHub-provided private address rather than a personal one.
Both settings are local to this clone, so `git config --local --get-regexp alias`
and `git config --local user.email` show what a clone is actually using.

## Releasing

Releases are published from a tag, never from a branch, and they go out through
PyPI Trusted Publishing — **there is no API token anywhere, and none should be
created.**

```bash
# 1. bump the version in pyproject.toml, then
git ci -am "Bump to 0.2.0"
git push
# 2. only then the tag
git tagv -a v0.2.0 -m "OpenSEGY 0.2.0"
git push origin v0.2.0
```

The workflow refuses to publish if the tag and the version in `pyproject.toml`
disagree, because a release that claims a version it does not carry cannot be
withdrawn afterwards. It also runs `twine check --strict`, since a README that
fails to render is the classic way to spoil a release and cannot be fixed in
place.

## What belongs in this library, and what does not

OpenSEGY produces **readings**: a byte range, a type, the raw bytes, the decoded
value. It does not produce **claims** — it will report that a stanza declares a
coordinate system as the text `SIRGAS 2000 / UTM 24S`, and it will not tell you
which EPSG code that is, because deciding needs evidence from outside the file.

Keep that line where it is. It is what lets the same parser serve an inspector,
a converter and somebody else's notebook without any of them inheriting
somebody else's guess.

Two more rules that have already earned their keep:

- **Be strict when writing, tolerant when reading.** A value that does not fit
  its field raises on the way out; a truncated or self-contradicting file is
  described on the way in, never refused.
- **Never discard the raw bytes.** When a delivery turns out to carry
  centimetres where its header promised metres, the bytes are the only thing
  that settles it.

## Licensing

Apache-2.0. Byte positions come from the SEG-Y specifications and may be
cross-checked against the Apache-2.0 `segy` package from TGS. **No code may be
copied or transcribed from `segyio` or `seisio`**; both are LGPL and are
reference implementations and test oracles here, nothing else.
