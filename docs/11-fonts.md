# 11. The fonts

Ten `.font` files, 616 to 4,344 bytes. They are not cels and they are not a
3DO SDK format — the `Text` folio is never called. Immercenary has its own
anti-aliased font format, three bits of coverage per pixel, compressed by a
16-bit token stream that a hand-written ARM blitter interprets by dropping
each token into the condition-code flags.

All ten now decode, every glyph consuming exactly the bytes up to the next
glyph's offset. Implemented in [`tools/font.py`](../tools/font.py).

| File | Height | Glyphs | Range | Advance |
|---|---|---|---|---|
| `menu.font` | 12 | 96 | 0x20 … 0x7f | proportional |
| `Menu2.font` | 14 | 127 | 0x00 … 0x7f | proportional |
| `Display/Narration.font` | 14 | 127 | 0x00 … 0x7f | proportional |
| `HUD/LED12.font` | 14 | 126 | 0x00 … 0x7f | proportional |
| `HUD/Message.font` | 10 | 59 | 0x20 … 0x5a | fixed 9 |
| `HUD/Mon6.font` | 8 | 126 | 0x00 … 0x7f | proportional |
| `HUD/Mon8.font` | 10 | 124 | 0x00 … 0x7f | proportional |
| `HUD/MICR.font` | 12 | 10 | 0x30 … 0x39 | fixed 14 |
| `Film/Stats12.font` | 12 | 28 | 0x20 … 0x3b | fixed 7 |
| `Film/Stats14.font` | 14 | 28 | 0x20 … 0x3b | fixed 9 |

`Narration.font` and `Menu2.font` are byte-identical — the same 4,288 bytes
shipped twice under two names.
`MICR.font` is the ten bank-cheque digits, which is what the HUD's account
readout is drawn with.

## File layout

All big-endian. The loader maps the file and hands the rest of the game a
pointer to **fileBase + 0x0c**, so every in-memory offset the code uses is
twelve less than the file offset below.

| Offset | Type | Meaning |
|---|---|---|
| 0x00 | char[4] | `FONT` |
| 0x04 | u32 | file size |
| 0x08 | u32 | flag, 0 or 1 |
| 0x0c | u32 | flag, 0 or 1 |
| 0x10 | u32 | glyph height in rows |
| 0x14 | u32 | widest glyph |
| 0x18 | u32 | bits per pixel — always 3 |
| 0x1c | u32 | first character code |
| 0x20 | u32 | last character code |
| 0x24 | u32 | ? |
| 0x28 | u32 | line height |
| 0x2c | u32 | descent |
| 0x30 | u32 | ? |
| 0x34 | u32 | char table offset — always 0x54 |
| 0x38 | u32 | char table size, `4 * charCount` |
| 0x3c | u32 | glyph data offset |
| 0x40 | u32 | glyph data size |
| 0x44 | u32 | fixed advance, 0 = proportional |
| 0x48 | u32 | zero on disc; the loader writes the char table pointer here |
| 0x4c | u32 | zero on disc; the loader writes the glyph data pointer here |
| 0x50 | u32 | ? |
| 0x54 | u32[] | char table |

The two pointer slots are what identifies the in-memory bias: the blitter
reads the table through `[font + 0x3c]` and the pixels through
`[font + 0x40]`, which are file offsets 0x48 and 0x4c.

### The char table

One `u32` per code from `first` to `last`, read by `FontCharWidth` at
`0x0001b680`:

```
0x1b688   lr = font->firstChar          ; [r0, #0x10]
0x1b68c   if (ch < lr) -> width 0
0x1b698   r0 = font->lastChar           ; [r0, #0x14]
0x1b6a0   if (ch > r0) -> width 0
0x1b6a4   r3 = font->charTable + (ch - firstChar) * 4
0x1b6ac   r0 = *r3
0x1b6b0   width = r0 & 0xff
```

and by the blit setup at `0x0001b728`:

```
0x1b730   r1 = font->glyphData          ; [r4, #0x40]
0x1b734   r0 = r1 + (entry >> 10)
```

so

```
width      = entry & 0xff        0 means "no glyph"
byteOffset = entry >> 10
```

Bits 8 and 9 are zero in every entry on the disc, which makes the offset a
word offset scaled by four — but the code shifts by ten, not twelve, so
byte granularity is what the format actually allows.

## The glyph token machine, `0x0001b76c`

The blitter is 128 instructions of dense hand-written ARM. It takes a
five-word destination descriptor `{base, stride, x, y, colour}` and a
three-word source descriptor `{data, width, height}`, and walks the glyph
data as big-endian `u32` words, each holding two 16-bit tokens, high half
first.

The trick that shapes the whole format is at `0x1b7cc`:

```
0x1b7cc   ldr sl, [r0], #4              ; next word
0x1b7d0   msr apsr_nzcvq, sl            ; top four bits -> N Z C V
0x1b7d4   bmi ...                       ; bit 15 of the token
0x1b7d8   beq ...                       ; bit 14
0x1b7dc   bhs ...                       ; bit 13
0x1b7e0   bvs ...                       ; bit 12
0x1b7e4   b   ...                       ; none of them
```

and then at `0x1b7ec` the same word is shifted left sixteen and dispatched
again, which is how the low half is reached. A four-way flag dispatch is
free on ARM, so the token type costs four bits and nothing else.

### Token forms

| Test | Form |
|---|---|
| bit 15 | five pixels: bits 14-12, 11-9, 8-6, 5-3, 2-0 |
| bit 14 | two pixels, bits 13-11 and 10-8, then a tail op |
| bit 13 | one pixel, bits 10-8, then a tail op |
| bit 12 | a tail op alone, with bit 11 live |
| none | four pixels: bits 11-9, 8-6, 5-3, 2-0 |

A pixel is a three-bit coverage value, 0 … 7.

### Tail ops

Read from the low bits of the same token, at `0x1b898`:

| Test | Op |
|---|---|
| bit 11 | skip `tok & 0xff` whole rows |
| bit 7 | copy `(tok >> 2) & 0x1f` pixels from `(tok & 3) + 1` rows above |
| bits 6-0 zero | end of row |
| otherwise | run of `(tok >> 3) & 0xf` pixels of value `tok & 7` |

Bit 11 is only reachable from the bit-12 form. The two- and one-pixel forms
spend it — the two-pixel form uses it as the low bit of its first pixel — and
`bic sl, sl, #0x8000000` at `0x1b894` clears it before the tail runs, so
their tails only ever see bits 7-0.

A row also ends implicitly the moment the width is reached: every pixel write
does `subs r6, r6, #1 / beq 0x1b7ac`, and any pixels still left in the token
are dropped. The other half of the current word is still decoded.

The copy-from-above op is the format's real compression. It is a vertical
back-reference of one to four rows, which is exactly what an anti-aliased
letter stem is, and it is why an eight-by-fourteen `Menu2` glyph fits in
forty bytes.

### The written pixel

```
0x1b808   and ip, fp, sl, lsr #25       ; fp = 7, the coverage value v
0x1b80c   orr ip, ip, ip, lsl #5
0x1b810   eor ip, ip, r7                ; r7 = ((colour & 3) << 3) | 0xe0
0x1b814   strb ip, [r3], #1
```

so the byte that lands in the eight-bit destination is

```
out = ((~v & 7) << 5) | ((colour & 3) << 3) | v
```

— the coverage appears twice, once inverted in the high three bits and once
plain in the low three, with a two-bit colour selector wedged between. The
palette the text is drawn through is built around that layout, so a port can
either reproduce it or, more simply, keep `v` and blend.

## Verifying

```sh
python tools/font.py extracted/Perfect --verify
python tools/font.py extracted/Perfect -o sheets/fonts
python tools/font.py extracted/Perfect/menu.font -c A
```

`--verify` decodes every glyph and checks that it consumed exactly the bytes
between its own offset and the next glyph's. All 851 glyphs across the ten
files pass.
