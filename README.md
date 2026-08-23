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
| `tools/` | Opera (3DO) filesystem reader, CEL/anim decoder, CEL bank reader, B3D world parser, OBJ exporter, textured software renderer, ARM cross-referencer |
| `docs/` | Findings: disc layout, file formats, executables, roadmap, B3D format, code map, CEL banks |

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

# Render a top-down map of the overworld
python tools/b3dmap.py extracted/Perfect/CondensedPerfectWorld.B3D worldmap.png \
                       extracted/Perfect/PerfectLocation.Init

# Cross-reference the executable: which code uses which string?
python tools/armxref.py extracted/p -s 'load the world'
python tools/armxref.py extracted/p -d 13e4c -n 60
```

## Status

Early, but moving. Nothing is playable yet.

- The Opera filesystem is fully readable: 747 files, 552 MiB.
- The 3DO CEL format decodes: 449 asset files to 5,874 PNGs, no failures.
- **The `.B3D` world format is solved**, every rule taken from the game's own
  parser rather than fitted to the data. All seven files of the family walk to
  the last byte of every cell — the overworld is 2,680 records and 8,463 quads.
- **The texture pipeline is solved.** `PerfectWorld.CELS` is a bank of 3,603
  bare 3DO CCBs; each wall face names one by index, at one texture pixel per
  world unit.
- The overworld therefore renders: a top-down city plan, a Wavefront OBJ, and a
  textured perspective view — all from the disc, with no ARM emulation.
- The executable is being mapped: the world loader, the record parser and all
  seven of its sub-handlers, the CEL bank loader, the object id table and the
  world globals are identified.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).
