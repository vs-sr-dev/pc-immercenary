# The 64 DSP instruments

`System/Audio/dsp` holds sixty-four `.dsp` files, and they were the last unread
asset format on the disc. They are **not Immercenary's work**: they are the
stock 3DO Portfolio instrument library that every title ships, and the names
say so — `mixer4x2`, `sawtooth`, `envelope`, `directout`, `svfilter`.

That does not make them irrelevant to a port. A port has to reproduce whatever
the game asks the audio folio to build, and these files are where "what does
`halfmono8` actually do, and what can you turn on it" is written down. So the
useful questions are two: what is the format, and **which of the sixty-four
does Immercenary actually name**.

`tools/dsp.py` answers both. `--verify` walks every file to its last byte and
checks every structural claim below: 64 instruments, 1,950 DSP code words,
220 knobs, 668 relocations, no violations.

## The format

Plain IFF, big-endian, no compression.

```
FORM 3INS
  NAME                  the file's own name
  FORM DSPP
    DHDR                4 words: a catalogue number, a format version of 2,
                        then two zeros
    DCOD                3 words -- 0, 12, and a code word count -- then that
                        many 16-bit DSP instructions
    DRSC                16 bytes a resource: type, count, 0, 0
    DRLC                16 bytes a relocation: mask, 0, resource index,
                        code word to patch
    DNMS                the resource names, NUL-separated, in DRSC's order
    DKNB                a linked list of 68-byte knob records
  FORM ATNV / ENVL      attenuation and envelope tables, on three files each
```

`DHDR`'s first word is a small integer, unique per instrument except that
`envelope` and `envfollower` both hold 12. Sorted by it, the first fifty-three
instruments come out in alphabetical order and the rest look appended as the
library grew — `halfstereosample` 56, `samplermod` 57, `submixer2x2` 58, up to
`directin` 72. It reads as a catalogue number rather than as anything computed
from the file: it is not a size, a count or an offset.

### Resource types, read off the files rather than out of a header

There is no SDK header here to copy from, so the type numbers were pinned by
correlating each one with the names that carry it across all sixty-four files.

| Type | What it is | The names that carry it |
|---|---|---|
| 0 | the code block; its count is the code length in words | `Entry`, once per instrument |
| 1 | a knob — a host-writable parameter, described further by `DKNB` | `Amplitude` (41), `Frequency` (22), the gains |
| 2 | a variable; its count is how many words of DSP data memory it needs | `Output` (37), `Input0`, `LeftOutput`, … |
| 3 | a variable the host reads back | `Monitor`, `EO_LeftCount`, `EO_RightCount` |
| 5 | a ring-buffer base | `MYRB` (5), `LeftRBASE`, `RightRBASE` |
| 6 | an input FIFO | `InFIFO` (20), `Tap0`, `LeftInFIFO` |
| 7 | an output FIFO | `OutFIFO` (3) |
| 8 | the tick cost | `Ticks`, once per instrument |
| 9, 10 | the left and right ADC | `LeftADC`, `RightADC` |
| `0x4000` | a subroutine this file **exports** | `DecodeADPCM`, `OscUpDownFP` |
| `0x8000` | a subroutine this file **imports** | the same two, from five other files |

Two things make that reading solid rather than plausible:

- `decodeadpcm.dsp` asks for **89 words** of `StepSizes` and **8** of
  `IndexDeltas` — exactly the two IMA ADPCM tables. A type-2 resource's second
  field is a word count and nothing else.
- Exactly one file declares each `0x4000` name, and its filename is that name
  lowercased: `decodeadpcm.dsp` exports `DecodeADPCM`, `oscupdownfp.dsp`
  exports `OscUpDownFP`. Five other files import them.

`Entry`'s count is the **code length**, not a start offset: it equals `DCOD`'s
own word count on all sixty-four. `Ticks` is an independent figure and exceeds
the code length on twenty-six of them, so it is a real cost estimate rather
than a byte count — `sampler` is eleven words and thirty-six ticks.

### Knobs

`DKNB` is a linked list, not an array: the first word of a record is the byte
offset of the next, and zero ends the chain. Each record is 68 bytes.

```
+0x00  u32  offset of the next knob, 0 at the end
+0x04  s32  minimum
+0x08  s32  maximum
+0x0c  s32  default
+0x10  u32  always 1 on all 220
+0x14  char[32]  name, NUL-padded
+0x34  u32  the index of the type-1 resource this drives
+0x38  s32  } a conversion hint, zero on 206 of 220
+0x3c  s32  }
+0x40  u32  zero
```

Every knob's name matches the resource it points at, and every default lies
inside its own range. The hint at `+0x38` is non-zero on exactly fourteen
knobs, and always the `Frequency` of an oscillator: 3 on eleven of them, 4 with
a second word of 8 on `square_lfo` and `triangle_lfo`, −1 on `pulse_lfo`. It is
how a frequency in hertz becomes a phase increment; the rule is not derivable
from the file alone and is **not** worked out here.

`svfilter` is a good short example of what the format buys you:

```
Amplitude   0 .. 32767  default 32767
Resonance   0 .. 24576  default 4096
Frequency   0 .. 16384  default 8192
```

### Relocations

A `DRLC` entry names a code word for the loader to patch with a resource's
address once it has been placed. The claim is checkable and it checks out:
**every one of the 668 words a relocation points at has its top bit set**, and
the low fifteen bits are an addend. So the shipped code carries `0x8000 |
offset` wherever an address belongs, and `directout`'s eight words

```
4627 8906 8000 4627 8907 8000 8380 8000
```

have their two relocations aimed at words 2 and 5 — both `0x8000` — for
`InputLeft` and `InputRight`.

The mask word is `0x00020a00` on 519 of the 668 and `0x00010a00` on 128, with
`0x01020a00`, `0x00000600` and `0x02020a00` making up the rest. It presumably
says which field of the instruction word takes the address. That is not pinned
down here either.

## What the game actually names

`p` names **21 of the 64**, and `p1e` the same 21. The other 43 are dead weight
on the disc, shipped because the library ships whole.

The 21 split by who asks for them:

| Where | Instruments |
|---|---|
| `0x0261ec`, the game's own sound setup, by the path `$audio/dsp/…` | `mixer4x2`, `directout`, `halfmono8` |
| `0x027138`, likewise | `noise` |
| `0x047a28` | `mixer2x2`, `envelope` |
| `0x04d160`, the SDK's sample-player chooser | eighteen decoder names: `adpcm{,half}{mono,stereo}`, `dcsqxd{,half}{mono,stereo}`, `fixed{mono,stereo}{8,sample}`, `half{mono,stereo}{8,sample}`, `varmono8`, `sampler` |

Four, two and sixteen — `halfmono8` is named twice and two of the chooser's
eighteen are not on the disc — which is the twenty-one.

So the game's own code builds a four-in mixer, a direct output, a half-rate
8-bit mono player and a noise source; everything else is the audio folio
choosing a decoder to match a sample's format. `0x04d160` reads the sample's
attributes through audio folio slot `0x55be0` and branches on channel count and
compression to pick the name. Several of the eighteen are reached as an offset
from a neighbouring string rather than by their own literal, which is why a
plain string cross-reference finds only eleven of them.

It also asks for **two instruments the disc does not carry**:
`adpcmstereo.dsp` and `adpcmhalfstereo.dsp`. Neither exists anywhere in the
filesystem, so a stereo ADPCM sample would fail to load — the game never has
one.

## What is not done

The DSP instruction set itself. `DCOD` is 1,950 sixteen-bit words across the
sixty-four files and nothing here decodes a single one of them; the structure
around the code is read, the code is not. A port that wants these instruments
bit-exact has that ahead of it. A port that only wants them *working* has
enough here: the twenty-one names, their inputs, outputs, knobs and ranges.

## Using it

```sh
python tools/dsp.py extracted/System/Audio/dsp                  # the catalogue
python tools/dsp.py extracted/System/Audio/dsp/svfilter.dsp     # one, in full
python tools/dsp.py extracted/System/Audio/dsp --verify
python tools/dsp.py extracted/System/Audio/dsp --used extracted/p
```
