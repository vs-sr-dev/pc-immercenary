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
| `tools/` | Python tools: Opera (3DO) filesystem reader, AIF/ARM image metrics, string dumper |
| `docs/` | Findings: disc layout, file formats, executable analysis, port roadmap |

## Quick start

```sh
python -m pip install -r tools/requirements.txt

# List the contents of a retail disc image (raw MODE1/2352 .img/.bin or 2048-byte .iso)
python tools/operafs.py "Immercenary (USA).img"

# Extract every file
python tools/operafs.py "Immercenary (USA).img" -x extracted
```

## Status

Early. The disc filesystem is fully readable, the asset inventory is complete,
and the executables have been characterised. Nothing is playable yet.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).
