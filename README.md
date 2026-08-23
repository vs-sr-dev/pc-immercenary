# pc-immercenary

Reverse-engineering notes and tooling for **Immercenary** (Panasonic 3DO, 1995,
Five Miles Out / Panasonic Software Company), with the long-term goal of a
native PC port.

Immercenary never received a port or a re-release on any other platform. The
only shipping build is the 3DO ARM6 executable on the retail CD.

> **This repository contains no game data.** No ROM/ISO images, no extracted
> assets, no copyrighted media. The tools here operate on a disc image that you
> must supply yourself from your own copy of the game.

## What is here

| Path | Contents |
|---|---|
| `tools/` | Opera (3DO) filesystem reader, CEL/anim decoder, B3D world parser, ARM cross-referencer |
| `docs/` | Findings: disc layout, file formats, executables, roadmap, B3D format, code map |

## Quick start

```sh
python -m pip install -r tools/requirements.txt

# List the contents of a retail disc image (raw MODE1/2352 .img/.bin or 2048-byte .iso)
python tools/operafs.py "Immercenary (USA).img"

# Extract every file
python tools/operafs.py "Immercenary (USA).img" -x extracted

# Decode every cel, anim and screen image to PNG
python tools/celbatch.py extracted/Perfect png

# Parse the world and encounter geometry files
python tools/b3d.py -r "extracted/Perfect/**/*.B3D"

# Cross-reference the executable: which code uses which string?
python tools/armxref.py extracted/p -s 'load the world'
python tools/armxref.py extracted/p -d 13e4c -n 60
```

## Status

Early, but moving. Nothing is playable yet.

- The Opera filesystem is fully readable: 747 files, 552 MiB.
- The 3DO CEL format decodes: 449 asset files to 5,874 PNGs, no failures.
- The `.B3D` world container is solved and confirmed against the game's own
  loader, disassembled.
- The executable is being mapped: the world loader, the record parser, the
  object id table and the world globals are identified.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).
