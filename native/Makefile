# The native viewer.  MinGW-w64 from MSYS2, no WSL.
#
#   python tools/scenepack.py out/world.pack
#   make -C native
#   native/view.exe out/world.pack
#
# MSYS2's toolchain is not usually on PATH, so point at it directly.  Override
# either variable if yours lives elsewhere:
#
#   make -C native MINGW=/c/msys64/ucrt64

MINGW ?= /c/msys64/mingw64
# `?=` will not do here: make defines CC itself, so it would never take.
CC     = $(MINGW)/bin/gcc.exe

# gcc.exe finds its own DLLs beside itself; cc1.exe, off in libexec, does not,
# and a Windows process that cannot load a DLL dies before it can say so -- the
# symptom is gcc exiting 1 with no diagnostic at all.
export PATH := $(MINGW)/bin:$(PATH)

# MSYS2's `make` hands the compiler TMP=C:\WINDOWS, which is not writable, and
# gcc then dies with "Cannot create temporary file". Give it one of our own.
TMPD := $(CURDIR)/.tmp
export TMPDIR := $(TMPD)
export TMP    := $(TMPD)
export TEMP   := $(TMPD)

SDL_CFLAGS := -I$(MINGW)/include -I$(MINGW)/include/SDL2 -Dmain=SDL_main
SDL_LIBS   := -L$(MINGW)/lib -lmingw32 -lSDL2main -lSDL2

# No -ffast-math.  It lets the compiler reassociate floating point, and this
# rasteriser decides which of two surfaces owns an edge pixel by the sign of a
# barycentric that is *exactly* zero there -- so a last-bit difference is a
# whole pixel of a different colour.  It was worth 20 pixels of an 800 x 500
# frame that had been written down as a fill-rule difference for four
# sessions, and it costs about 4% of the frame rate to give up.  Keep it off:
# agreeing with tools/b3dview.py to the pixel is the point of this program.
CFLAGS := -O2 -Wall -Wextra -Wno-unused-parameter $(SDL_CFLAGS)
LIBS   := $(SDL_LIBS) -lm

view.exe: view.c
	@mkdir -p $(TMPD)
	$(CC) $(CFLAGS) -o $@ $< $(LIBS)

clean:
	rm -rf view.exe $(TMPD)

.PHONY: clean
