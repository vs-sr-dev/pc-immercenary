# 2. File formats

Everything is big-endian. Most formats are stock 3DO Portfolio formats, which
is good news: they are documented and there are existing decoders to check
against. Only `.B3D` and a handful of packed containers are specific to this
game.

## Confirmed

### `.img` — uncompressed screen image

IFF-style chunked. Observed on every 153,636-byte file:

```
'IMAG' u32 chunkSize=0x1C
       u32 width  = 320
       u32 height = 240
       u32 bytesPerRow = 640
       u8  bitsPerPixel = 16
       u8  numComponents = 3
       u8  numPlanes = 1
       u8  colorSpace
       u32 ...
'PDAT' u32 chunkSize=0x25808
       320*240 u16 pixels, 3DO RGB555 (bit 15 unused//PLUT select)
```

### `.anim`, `.cel`, `.mask`, `.glow`, `.bcel`, `.scel`, `.hcel`, `.3cel`, `.cels`

3DO CEL data in the standard chunked wrapper. Chunk IDs seen in the executables
and in the files themselves:

```
'CCB '  Cel Control Block (the hardware sprite descriptor)
'PLUT'  Pixel Lookup Table (palette)
'PDAT'  pixel data
'ANIM'  animation: frame count / frame rate / per-frame CCB list
'DESC'  description
'KWRD' 'CPYR' 'CRDT' 'XTRA'  metadata chunks
```

The extension conveys the *role*, not the format: `.mask` and `.glow` are cel
files used as an alpha/additive layer over the matching `.anim`. Characters are
consistently stored as an `<Name>.<action>.anim` + `.mask` (+ `.glow` for the
Perfect One) triple.

Decoding CELs means implementing the 3DO CEL engine's pixel formats: 1/2/4/6/8/16
bits per pixel, packed (RLE-like) or literal, with PLUT indirection and the
per-cel PIXC blending controls. This is the single largest piece of graphics
work in the project.

### `.strm` and the `Stream/` files — 3DO DataStream

Chunked stream container starting with `'SHDR'`. The executables reference the
standard 3DO subscriber set:

```
'FILM' / 'FHDR' / 'FRME'   Cinepak video
'SNDS' / 'SHDR' / 'SSMP'   SAudio
'CTRL'                     control
'CLST' / 'THED'            SCel (streamed cels)
'DDAT' / 'DHDR'            FMOData — game-specific per-frame data
'STOP' 'SYNC'              stream control
```

`FMOData` is a custom subscriber: the game pushes its own per-frame payload
through the video stream (the error string *"Got more data from the FMOData
subscriber than we knew about!"* appears in every encounter loader). This is how
cinematics stay in sync with gameplay state.

`Perfect/Film/CinepakSubroutine` is a separate 86,844-byte ARM AIF module loaded
at runtime to decode Cinepak.

### `.music`, `.aiff`, `.aif`, `.ins`, `.dsp`

Standard 3DO audio. `.dsp` files are DSP instrument binaries from the OS
(`System/Audio/dsp/`, 64 of them); the game names the ones it uses directly:
`mixer4x2.dsp`, `directout.dsp`, `halfmono8.dsp`, `envelope.dsp`,
`fixedstereosample.dsp`, `dcsqxd*.dsp`, `adpcm*.dsp`, `noise.dsp`.

`.music` files are large (11–12 MiB) — streamed music, not sequenced.

### `.Narration` — plain ASCII

Character bios shown on the Display screen, CR-terminated, pre-wrapped to the
on-screen column width.

### `.Init` — plain ASCII

`Perfect/PerfectLocation.Init` is a developer warp table left in the shipping
build:

```
0 -200 64        This is south of the spire...
-570 60 -127     In the middle of the church...
-600 860 64      This is going into see Loki and Two....
...
```

`X Y Z` followed by a comment. Directly useful for testing a port: these are
real, valid world coordinates.

### `.dat`

`Perfect/StartPositions.dat` (604 bytes) is a flat array of big-endian `i32`,
count-prefixed (`0x4B` = 75 entries), holding candidate player spawn points.
The executable logs *"Found %d spots close enough to %d %d to put the player.."*.

## Partially understood

### `.B3D` — world and encounter geometry

The core custom format. 19 files, from 108 bytes to 131,611 bytes
(`CondensedPerfectWorld.B3D`, the overworld).

The header is a shared struct. Comparing the overworld with an encounter file:

```
              CondensedPerfectWorld    balkanencounter
i32[0..3]     -1948 2611 2146 -1483    -1948 2611 2146 -1483   world bounds
i32[4..5]     256 256                  256 256                 grid/cell scale
i32[6..7]     181 210                  0 0                     counts
i32[8]        3634                     0                       count (faces?)
i32[9]        35001  (0x88B9)          0                       file offset
i32[10]       90340  (0x160E4)         844                     file offset
i32[11]       0                        844
i32[12..]     22 38 62 82 104 122 ...  -1 -1 -1 -1 -1 ...      index table
```

The bounds and cell scale are identical across files, so the header is a fixed
struct and the trailing table is a spatial index — ascending byte offsets for
the overworld, all `-1` (empty) for a single-room encounter.

`PerfectMovers.B3D` is a different beast: its body contains four-character
codes (`'Gone'`, …) and reads as a table of *mover* definitions rather than
geometry.

The executable's world loader logs give the vocabulary:

```
Bailed Out with CurrentQuad at %d
Bailed Out QuadIndex Overflow
B_Objects:%d  S_Objects:%d  R_Objects:%d  Anims:%d  Sounds:%d
Face Verts:%d  Static Centers:%d  TotalCharacters:%d
```

So the world is built from **quads** organised into a **quad index**, with
building objects, static objects, "R" objects, animations, sounds, face vertices
and static centres. Rendering is quad-based, not triangle-based — consistent
with the 3DO CEL engine, which draws arbitrary textured quadrilaterals in
hardware.

**Not yet decoded.** This is the first target for the next session.

### Packed containers

Several files are concatenations with an index rather than single assets:
`AllMenuCels`, `AllHUDCels`, `AllWeaponIcons`, `AllWeaponDescs`,
`AllStaticObjects`, `AllFloor`, `AllLakePals`, `AllLargeMaps`,
`PerfectWorld.CELS` (17.8 MiB), and `Perfect/Film/*Files` (8–20 MiB each).
The `*Files` blobs are almost certainly per-boss FMV bundles.
