"""3dokit - game-agnostic building blocks for 3DO reverse engineering and ports.

Each module handles one thing the 3DO, its Portfolio OS or its SDK imposes
on every game, independent of any particular title:

    disc       disc images (.iso, raw .img/.bin, .cue): the Opera filesystem,
               its copies, the ROM tags, extraction
    aif        executables: the AIF header, the 3DO binary header, the
               relocation list, where the code really ends
    arm        ARM60 code: function starts, calls, tail calls, references,
               control flow, disassembly with symbols (needs capstone)
    portfolio  the OS surface a program touches: SWIs and folio vectors
    shapes     function shapes: library code proved against a corpus, and
               the functions of two programs paired
    cel        cel, anim and image files, and the CEL engine's pixel decoder
    stream     the DataStream container: films, sounds, markers, payloads
    cinepak    Cinepak as 3DO films carry it, with a game's dither optional
    audio      SDX2, AIFF/AIFC with loops, WAV out
    dsp        the Portfolio DSP instrument library
    pixels     RGB555, PNG and PPM
    check      the Python half of runtime/tdkcheck
    runtime/   C99 for the engine side: files out of a disc image, cels,
               DataStream, Cinepak, SDX2

The package name starts with a digit, so from Python it is imported with
importlib (`importlib.import_module('3dokit.cel')`) and from a shell run as
`python -m 3dokit.<module>`.  Everything is pure Python 3.8+ with no
dependencies except arm, portfolio and shapes (capstone).  Game-specific
knowledge belongs in the game's own tools/, not here.
"""
