# 12. The DataStream: 473 MiB of film, and what else rides in it

Four fifths of the disc is streamed video. It is the stock 3DO Portfolio
DataStream, so most of this is not Immercenary's invention — but two things
are worth having written down: the exact 3DO Cinepak dialect, and what the
game's private `FMOD` subscriber actually carries, which is not what the
name suggests.

Implemented in [`tools/strm.py`](../tools/strm.py). Video decodes to PNG,
audio to WAV, and the private channel reassembles to files.

## What is on the disc

| Group | Files | Contents |
|---|---|---|
| `Film/I*.strm` | 27 | the interview clips, one film each |
| `Film/*.strm` | 9 | `Opening`, `GameWin`, `RavensPlea`, `DeathScene`, `FMOCID`, three `P1*Death`, `ealogo` |
| `Film/*Files` | 8 | one per character — 7 to 13 films in one container, with a seek table |
| `Stream/AllCinepaks.strm` | 1 | 13 streams, 15 films, **and 61 cel files** |

`Film/CinepakSubroutine` is a separate 86 KB ARM AIF module, the decoder
itself, and is not part of the container.

## Container

A stream is a run of fixed-size blocks — `streamBlockSize` from the header,
128 KiB for the standalone films and 64 KiB for the containers. A chunk
never straddles a block boundary; slack at the end of a block is covered by
a `FILL` chunk, and when fewer than eight bytes remain the writer drops a
bare four-byte `FILL` tag with no size word behind it. That last detail is
what makes a naive walk of `I32.strm` and `Opening.strm` derail — both have
exactly that four-byte tag at a block end.

Every chunk:

| Offset | Type | Meaning |
|---|---|---|
| 0x00 | char[4] | chunk type |
| 0x04 | u32 | size, header included |
| 0x08 | u32 | presentation time, stream ticks |
| 0x0c | u32 | channel |
| 0x10 | char[4] | sub-type |

`FILL` is the exception: type and size only.

| Type | Sub | Meaning |
|---|---|---|
| `SHDR` | — | stream header; a new one begins a new stream |
| `FILM` | `FHDR` | codec, frame size, frame count |
| `FILM` | `FRME` | one compressed video frame |
| `SNDS` | `SHDR` | rate, sample width, channels, codec |
| `SNDS` | `SSMP` | a run of compressed samples |
| `CTRL` | `SYNC` | resynchronise |
| `CTRL` | `STOP` | end of this film |
| `DACQ` | `MTBL` | marker table |
| `FMOD` | `DHDR` `DDAT` | the game's own subscriber |

### `SHDR`

Block size is the `u32` at 0x18 and is the only field a reader must trust.
The subscriber list starts at 0x74 as `(tag, u32)` pairs terminated by a
zero tag; every stream on the disc declares `FILM:7 SNDS:10 CTRL:11`, which
are subscriber priorities, and none declares `FMOD` — the game installs that
one itself.

### `DACQ` / `MTBL`

A flat list of `(time, byteOffset)` `u32` pairs starting at 0x14. This is
the index the `*Files` containers were missing: `AllCinepaks.strm` has 34
markers, and each of its thirteen films begins at one of them.

```
time         0  offset 0x00010000
time       999  offset 0x00020000
time      1000  offset 0x00030000
time      4000  offset 0x00130000
...
```

## Video

`FILM`/`FRME` carries `duration` and `frameSize` at 0x14 and 0x18, then the
compressed frame at 0x1c. `FHDR` gives `cvid` — plain Cinepak — at 320x240
or 288x216.

The `u32` at 0x24 is a tick rate: 30 on nine films, 15 on a hundred and
twenty, 12 on one, and an unrecognised `0x4080ddd8` on `FMOCID`, `Opening`
and `RavensPlea`. It is only self-consistent on the first group —
`I01.strm` sums 1,213 frame ticks at scale 30, which is 40.43 seconds, and
its audio is 891,555 samples at 22,050 Hz, which is also 40.43 seconds. The
scale-15 films run at twice their nominal rate. Measured against their own
audio, everything on the disc plays at 15 frames a second.

The frame data is ordinary Cinepak with one 3DO peculiarity. Between the
ten-byte frame header and the first strip sits a six-byte record

```
fe00 0006 0000
```

which is **not** counted in `numStrips`. It is byte-identical in all 29,212
frames of all 45 stream files on the disc, and every one of them declares
exactly two strips. The frame header's 24-bit length field also runs
eight bytes short of the real payload. A decoder that trusts `numStrips` and
skips an `0xfe00` record wherever a strip header is expected reads the disc
cleanly; one that trusts the length field, or that treats the record as the
first strip, does not.

Everything else is standard: strip ids `0x1000`/`0x1100`, codebook chunks
`0x2000`-`0x2700` (bit `0x0200` selects the V1 book, `0x0100` makes the
update selective, `0x0400` drops U and V), vector chunks `0x3000`/`0x3100`/
`0x3200`, a strip with `y1 == 0` stacking below the previous one, and
codebooks inherited from the previous strip unless frame flag `0x01` is set.

Colour is the classic Cinepak conversion:

```
r = y + 2v      g = y - u/2 - v      b = y + 2u
```

## Audio

`SNDS`/`SHDR` fields that matter, from the chunk start:

| Offset | Meaning |
|---|---|
| 0x28 | bits per sample — always 16 |
| 0x2c | sample rate — 22050 or 44100 |
| 0x30 | channels — 1, or 2 for `ealogo` |
| 0x34 | codec — always `SDX2` |
| 0x38 | compression ratio — always 2 |
| 0x3c | sample count |

`SSMP` has the byte count at 0x14 and the data at 0x18. SDX2 is one byte
per sample: read the byte signed, and

```
if (b & 1) acc += b * |b| * 2;  else acc = b * |b| * 2;
```

clamped to sixteen bits. Channels interleave byte by byte, each with its own
accumulator.

The sample count at 0x3c is trustworthy for the mono films — `I01.strm`
declares 891,555 and decodes to 891,556 — and is not for the one stereo
file, where it reads 11,024 against 178,376 decoded. Decoding to the end of
the `SSMP` chunks is the reliable rule.

## `FMOD` is a file pipe

The last unexplained subscriber turns out not to be per-frame gameplay data
at all. It is a **file delivery channel**:

```
FMOD DHDR   u32 0, u32 totalLength
FMOD DDAT   u32 length, then that many bytes
```

A `DHDR` announces a byte count; the `DDAT` chunks that follow carry exactly
that many bytes, in order, and the result is a complete file. In
`Stream/AllCinepaks.strm` there are 61 of them and **every one reassembles
to its declared length to the byte** — 59 beginning `CCB `, two `PLUT`.
They are ordinary 3DO cel files, and `tools/cel.py` decodes all 59 to 802
PNGs with no failures. They are world textures and building facades.

So `AllCinepaks.strm` is not a film reel. It is the game hiding a level's
texture load behind a cinematic: video, audio and the next area's artwork
travelling down one 64 KiB-blocked pipe, interleaved by the same scheduler.

That also settles the `*Files` blobs, which were the last file group on the
disc with an unknown index. They are DataStreams: one per character, seven
to thirteen dialogue films each, indexed by the `MTBL` at the front.

## Using it

```sh
python tools/strm.py extracted/Perfect --scan
python tools/strm.py extracted/Perfect/Film/I01.strm -c
python tools/strm.py extracted/Perfect/Film/BalkanFiles -f out/balkan --step 50
python tools/strm.py extracted/Perfect/Film/I01.strm -w out/i01.wav
python tools/strm.py extracted/Perfect/Stream/AllCinepaks.strm -m out/fmod --markers
python tools/celbatch.py out/fmod out/fmodpng
```

Frames are named `film_frame.png`, so a container with thirteen films comes
out already separated.
