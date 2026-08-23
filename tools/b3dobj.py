#!/usr/bin/env python3
"""Export .B3D world geometry to a Wavefront OBJ.

    python tools/b3dobj.py extracted/Perfect/CondensedPerfectWorld.B3D world.obj

World axes are (X east, Y north, Z up); OBJ is written Y-up, so the mapping is
    obj.x = world.x     obj.y = world.z     obj.z = -world.y

Every quad carries a texture id -- an index into the game's CEL bank -- and
those become OBJ groups and `usemtl` names, so a viewer shows the material
split even without the textures themselves.
"""
import sys, os, argparse, collections
from b3d import B3D


def export(path, out, include=(0, 2), mtl=True):
    b = B3D(path)
    recs, failed = b.walk()
    verts = []
    faces = collections.defaultdict(list)     # texid -> [(i0,i1,i2,i3)]
    seen = {}
    for r in recs:
        if r.sub not in include:
            continue
        for corners, tex, ang, flg in b.quads(r):
            idx = []
            for x, y, z in corners:
                key = (x, y, z)
                i = seen.get(key)
                if i is None:
                    verts.append(key)
                    i = seen[key] = len(verts)
                idx.append(i)
            faces[tex].append(tuple(idx))

    name = os.path.splitext(os.path.basename(out))[0]
    with open(out, 'w') as f:
        f.write("# %s -- exported by tools/b3dobj.py\n" % os.path.basename(path))
        f.write("# %d records, %d quads, %d vertices\n"
                % (len(recs), sum(len(v) for v in faces.values()), len(verts)))
        if mtl:
            f.write("mtllib %s.mtl\n" % name)
        for x, y, z in verts:
            f.write("v %d %d %d\n" % (x, z, -y))
        for tex in sorted(faces, key=lambda t: (t is None, t)):
            g = "tex%d" % tex if tex is not None else "tex_none"
            f.write("g %s\n" % g)
            if mtl:
                f.write("usemtl %s\n" % g)
            for q in faces[tex]:
                f.write("f %d %d %d %d\n" % q)

    if mtl:
        with open(os.path.join(os.path.dirname(out) or '.', name + '.mtl'), 'w') as f:
            f.write("# one material per CEL id\n")
            for tex in sorted(faces, key=lambda t: (t is None, t)):
                g = "tex%d" % tex if tex is not None else "tex_none"
                # deterministic pseudo-colour so groups are distinguishable
                h = (tex if tex is not None else 0) * 2654435761 & 0xffffff
                f.write("newmtl %s\nKd %.3f %.3f %.3f\n"
                        % (g, ((h >> 16) & 255) / 255.0,
                           ((h >> 8) & 255) / 255.0, (h & 255) / 255.0))

    print("%s: %d records, %d quads, %d verts, %d texture ids -> %s"
          % (os.path.basename(path), len(recs),
             sum(len(v) for v in faces.values()), len(verts), len(faces), out))
    if failed:
        print("  %d unwalked ranges" % len(failed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('b3d')
    ap.add_argument('obj')
    ap.add_argument('--no-mtl', action='store_true')
    a = ap.parse_args()
    export(a.b3d, a.obj, mtl=not a.no_mtl)


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
