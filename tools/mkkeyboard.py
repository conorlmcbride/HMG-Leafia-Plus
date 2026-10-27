#!/usr/bin/env python3
"""Keep the CarPlay keyboard and phone keypad available while driving (US/Canada DiPO).

usage: mkkeyboard.py <variant> <stock dir> [--patches DIR] [--work DIR]

  <variant>    a patch set with HKMC_DiPO deltas (ev6, neev, ...)
  <stock dir>  that car's stock tree (a port kit's LEAFIA/private/stock/) with
               app/HKMC_DiPO.apk and app/HKMC_DiPO.odex

Stock US/Canada DiPO tells the phone, when a CarPlay session starts, that the soft keyboard
and the soft phone keypad are limited elements (`DipoService.b(true, true)` from
updateInitAppState, in `y(Z)` and `eJ()`); while the car is driving the phone then hides them.
Other regions pass (false, false). This changes the two US/Canada calls to (false, false) in
both DiPO builds (turn-by-turn and bridge), so they behave like the other regions.

The calls are found by structure in the rebuilt classes.dex: the invoke-direct of that method
with both arguments in register v6 (= true), each followed by the same call with v7 (= false)
for the other regions. The script stops unless there are exactly two of each. It then
rewrites the two arguments, fixes the dex checksum and signature, and rewrites the
patches/<variant>/HKMC_DiPO.{tbt,bridge}.lpd deltas and their manifest lines.
Run it once, on the deltas as they were before this change.

Needs the host lpatch (tools/lpatch/build.sh) and bsdiff4 (tools/requirements.txt).
"""
import argparse, hashlib, os, re, subprocess, sys, tempfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
LPATCH = os.path.join(HERE, 'lpatch', 'lpatch-host')
MKDELTA = os.path.join(HERE, 'mkdelta.py')
STAGES = ('tbt', 'bridge')
PART = {'tbt': '2_tbt', 'bridge': '3_bridge'}
# invoke-direct {p0, v6, v6}, DipoService->b(ZZ)V and the (v7, v7) call for other regions:
# 70 30 <method idx> <F|E|D|C>, with C = p0
TRUE_CALL = re.compile(rb'\x70\x30(..)([\x00-\xff])\x06', re.S)
REACH = 0x800


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def run(*a, **kw):
    subprocess.run(a, check=True, **kw)


def patch_dex(d):
    """Return the dex with both US/Canada calls changed to (false, false)."""
    d = bytearray(d)
    sites = []
    for m in TRUE_CALL.finditer(bytes(d)):
        idx, c = m.group(1), m.group(2)
        # the other-region call: same method, same p0 (low nibble), both arguments v7
        sib = bytes(d).find(b'\x70\x30' + idx + bytes([0x70 | c[0] & 0x0f]) + b'\x07', m.end(), m.end() + REACH)
        if sib > 0 and c[0] >> 4 == 6:
            sites.append(m.start())
    if len(sites) != 2:
        sys.exit('found %d US/Canada setLimitedUIElements calls, expected 2: not the known shape, '
                 'or the fix is already applied' % len(sites))
    for s in sites:
        d[s + 4] = (d[s + 4] & 0x0f) | 0x70   # D = v7
        d[s + 5] = 0x07                      # E = v7, F = 0
    d[12:32] = hashlib.sha1(bytes(d[32:])).digest()
    d[8:12] = (zlib.adler32(bytes(d[12:])) & 0xffffffff).to_bytes(4, 'little')
    return bytes(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('variant')
    ap.add_argument('stock')
    ap.add_argument('--patches', default=os.path.join(HERE, '..', 'patches'))
    ap.add_argument('--work')
    a = ap.parse_args()
    odex = os.path.join(a.stock, 'app', 'HKMC_DiPO.odex')
    apk = os.path.join(a.stock, 'app', 'HKMC_DiPO.apk')
    for f in (odex, apk, LPATCH):
        if not os.path.isfile(f):
            sys.exit('missing %s (see --help)' % f)
    manifest = os.path.join(a.patches, a.variant, 'manifest')
    lines = open(manifest).read().splitlines()
    work = a.work or tempfile.mkdtemp(prefix='mkkeyboard.')
    os.makedirs(work, exist_ok=True)
    for stage in STAGES:
        name = 'HKMC_DiPO.%s.lpd' % stage
        lpd = os.path.join(a.patches, a.variant, name)
        cur = os.path.join(work, stage + '.cur.dex')
        new = os.path.join(work, stage + '.new.dex')
        run(LPATCH, 'delta', lpd, odex, cur, stdout=subprocess.DEVNULL)
        open(new, 'wb').write(patch_dex(open(cur, 'rb').read()))
        run(sys.executable, MKDELTA, odex, new, lpd, stdout=subprocess.DEVNULL)
        rebuilt, built = os.path.join(work, stage + '.re.dex'), os.path.join(work, stage + '.apk')
        run(LPATCH, 'delta', lpd, odex, rebuilt, stdout=subprocess.DEVNULL)
        run(LPATCH, 'zipadd', apk, rebuilt, built, stdout=subprocess.DEVNULL)
        want = '%s app HKMC_DiPO %s/%s' % (PART[stage], a.variant, name)
        hits = [i for i, l in enumerate(lines) if l.startswith(want + ' ')]
        if len(hits) != 1:
            sys.exit('manifest %s has %d lines for %s' % (manifest, len(hits), want))
        lines[hits[0]] = '%s %s' % (want, md5(built))
        print(lines[hits[0]])
    open(manifest, 'w').write('\n'.join(lines) + '\n')
    others = []
    for v in sorted(os.listdir(a.patches)):
        m = os.path.join(a.patches, v, 'manifest')
        if v != a.variant and os.path.isfile(m) and ('%s/HKMC_DiPO.' % a.variant) in open(m).read():
            others.append(v)
    if others:
        print('NOTE: also uses these deltas, with its own APKs: %s. Update their manifest md5s '
              'from that car\'s stock files.' % ', '.join(others))
    print('Now: tools/compat-built.py to refresh docs/data/compat.json')


if __name__ == '__main__':
    main()
