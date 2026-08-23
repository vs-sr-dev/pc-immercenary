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
| `tools/` | Opera (3DO) filesystem reader, CEL/anim decoder, CEL bank reader, B3D world parser, ground tile map reader, OBJ exporter, textured software renderer, font decoder, DataStream demuxer with Cinepak and SDX2 decoders, ARM cross-referencer, OS-surface scanner |
| `docs/` | Findings: disc layout, file formats, executables, roadmap, B3D format, code map, CEL banks, the ground, the OS surface, the second B3D family, the fonts, the DataStream |

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
python tools/b3d.py --check extracted/Perfect/CondensedPerfectWorld.B3D

# ...and the second .B3D family, which is a different format again
python tools/b3d2.py extracted/Perfect

# Render a top-down map of the overworld
python tools/b3dmap.py extracted/Perfect/CondensedPerfectWorld.B3D worldmap.png \
                       extracted/Perfect/PerfectLocation.Init

# Cross-reference the executable: which code uses which string?
python tools/armxref.py extracted/p -s 'load the world'
python tools/armxref.py extracted/p -d 13e4c -n 60
python tools/armxref.py extracted/p -a 89680

# Decode the ten anti-aliased fonts
python tools/font.py extracted/Perfect --verify -o sheets/fonts

# Demux a film: PNG frames, a WAV, and the cels that ride in the same pipe
python tools/strm.py extracted/Perfect/Film/I01.strm -f out/i01 -w out/i01.wav
python tools/strm.py extracted/Perfect/Stream/AllCinepaks.strm -m out/fmod

# What of the 3DO OS does the game actually touch?
python tools/swiscan.py extracted/p
```

## Status

Early, but moving. Nothing is playable yet.

- The Opera filesystem is fully readable: 747 files, 552 MiB.
- The 3DO CEL format decodes: 449 asset files to 5,874 PNGs, no failures.
- **The `.B3D` world format is solved**, every rule taken from the game's own
  parser rather than fitted to the data. All seven files of the family walk to
  the last byte of every cell — the overworld is 2,680 records and 8,463 quads.
  Every header field is now read: `type` is a lieutenant's territory tag,
  `field` is the record's own grid cell, and the shipping game's `skipLength`
  bug is reachable on exactly five records — after you beat Chameleon.
- **The texture pipeline is solved.** `PerfectWorld.CELS` is a bank of 3,603
  bare 3DO CCBs; each wall face names one by index, at one texture pixel per
  world unit.
- **The ground is solved too.** It is not in the world file at all: a 4-bit
  256 x 256 tile map lives in the pixels of the last cel of
  `Perfect/Floor/AllFloor`, one nibble per 16-unit tile, and the lake animates
  by palette cycling. The whole ground pipeline now reads end to end: a
  precomputed reciprocal table for the perspective divide, a precomputed
  horizon curve per camera height, the 52-unit switch between the two tile
  detail levels, and a sixteen-step distance fade written straight into each
  quad's pixel-processor word.
- The overworld therefore renders: a top-down city plan, a Wavefront OBJ, and a
  textured perspective view with walls and ground — all from the disc, with no
  ARM emulation.
- **The fonts are solved.** All ten are one private format: three-bit
  anti-aliased coverage compressed by a 16-bit token stream that the game's
  blitter dispatches through the ARM condition-code flags. All 851 glyphs
  decode byte-exactly.
- **The 473 MiB of film opens up.** The `.strm` and `*Files` containers are 3DO
  DataStreams; video is Cinepak with one constant six-byte quirk, audio is
  SDX2. And the game's private `FMOD` channel is not gameplay data at all —
  it delivers whole cel files down the same pipe, 61 of them in
  `AllCinepaks.strm`, every one reassembling to its declared length.
- **The second `.B3D` family is decoded too** — all twelve files read to the
  last byte, and `PerfectMovers.B3D` turns out to be the game's cast list and
  stat table: nineteen characters, their animation sets, their patrol
  rectangles and the boss ladder's numbers.
- The executable is being mapped: the world loader, the record parser and all
  seven of its sub-handlers, the CEL bank loader, the floor renderer, the object
  id table and the world globals are identified.
- **The OS surface is enumerated**: 671 call sites reaching at most 146 entry
  points — 42 direct SWIs plus the folio function vectors, 46 of them audio,
  22 Graphics, 8 Operamath. That is the exact set a port must implement.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).
