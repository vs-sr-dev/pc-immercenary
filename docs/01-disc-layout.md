# 1. Disc layout and filesystem

## The image

The USA retail disc is a raw **MODE1/2352** image: 330,450 sectors of 2352
bytes. Each sector is `sync(12) + header(4) + userdata(2048) + EDC/ECC(288)`,
so payload starts at offset 16 within every sector.

The Opera volume header (sector 0) declares 330,000 blocks of 2048 bytes.

## Opera filesystem

3DO discs use Opera FS, big-endian throughout.

### Volume header (block 0)

| Offset | Size | Field |
|---|---|---|
| 0x00 | 1 | `record_type` = 1 |
| 0x01 | 5 | sync bytes, `"ZZZZZ"` |
| 0x06 | 1 | `record_version` |
| 0x07 | 1 | `flags` |
| 0x08 | 32 | `comment` |
| 0x28 | 32 | `label` (`"CD-ROM"` on this disc) |
| 0x48 | 4 | `identifier` |
| 0x4C | 4 | `block_size` (2048) |
| 0x50 | 4 | `block_count` (330000) |
| 0x54 | 4 | `root_dir_id` |
| 0x58 | 4 | `root_dir_blocks` |
| 0x5C | 4 | `root_dir_block_size` |
| 0x60 | 4 | `root_dir_copies` — index of the **last** copy, so `copies+1` entries follow |
| 0x64 | 4×N | LBA of each root directory copy |

This disc stores 7 root directory copies (`0x6c, 0xc3cf, 0x18039, 0x4f99e,
0x4f99f, 0x4f9a0, 0x4f9a1`). Redundancy is a general Opera feature; individual
files also carry 1–5 copies.

### Directory block header (20 bytes)

| Offset | Field |
|---|---|
| 0x00 | `next_block` |
| 0x04 | `prev_block` |
| 0x08 | `flags` |
| 0x0C | `first_free_byte` — entries occupy `[first_entry, first_free_byte)` |
| 0x10 | `first_entry_offset` (always 0x14 here) |

**Important:** a directory that spans several blocks uses **consecutive LBAs**
(`lba .. lba + block_count - 1`), and `next_block`/`prev_block` are *indices
within that extent*, not absolute LBAs. Following them as LBAs silently
truncates the tree — on this disc that hides 6 directories and ~380 MiB of
content.

### Directory entry (68 bytes + 4 per copy)

| Offset | Size | Field |
|---|---|---|
| 0x00 | 4 | `flags` — low byte: `2` = file, `7` = directory. Bit 30 = last entry in this block, bit 31 = last entry in the directory |
| 0x04 | 4 | `id` (unique per file) |
| 0x08 | 4 | `type` — four-character code, e.g. `'*dir'`, `'anim'`, `'cel '`, `'B3D '` |
| 0x0C | 4 | `block_size` |
| 0x10 | 4 | `byte_count` — real file length |
| 0x14 | 4 | `block_count` |
| 0x18 | 4 | `burst` |
| 0x1C | 4 | `gap` |
| 0x20 | 32 | `name` (NUL-padded) |
| 0x40 | 4 | `last_copy` — index of last copy, so `last_copy+1` LBAs follow |
| 0x44 | 4×N | LBA of each copy |

Implemented in [`tools/operafs.py`](../tools/operafs.py).

## Contents

**747 files, 43 directories, 552.5 MiB logical.**

```
/AppStartup            shell script (stock 3DO boilerplate)
/launchme              12,236 B   ARM AIF   launcher
/p                    390,276 B   ARM AIF   main game
/p1e                  276,200 B   ARM AIF   Perfect One final encounter
/rom_tags, /signatures            disc signing data
/Perfect/              game data (see below)
/System/               stock 3DO Portfolio OS (kernel, folios, DSP instruments,
                       shell utilities) — not part of the game
```

`/Perfect` is the application directory; every path in the executables is
written relative to it (`$Weapons/...`, `$Perfect/Balkan/...`, `$Sound/...`).

### Size breakdown

| Category | Size | Share |
|---|---|---|
| FMV (`Perfect/Film`, `Perfect/Stream`) | 473.1 MiB | 86% |
| Music and sound | 23.5 MiB | 4% |
| **Gameplay assets** | **55.9 MiB** | **10%** |

The playable game — world geometry, sprites, HUD, audio cues — is under 60 MiB.
Everything else is Cinepak video.

### Per-area directories

`Balkan`, `Chameleon`, `Chance`, `Fly`, `Loki`, `Medusa`, `Riberto`, `Silva`,
`Tesla` — one per boss encounter, each holding that area's geometry, wall cels,
character animations and HUD. Plus `Characters`, `Clouds`, `DOASys`, `Display`,
`Floor`, `HUD`, `Objects`, `PerfectOne/{Male,Female,Robot}`, `Sound`,
`StorageTuner`, `Weapons`, `Music`, `Film`, `Stream`.
