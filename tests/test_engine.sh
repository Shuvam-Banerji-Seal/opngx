#!/usr/bin/env bash
# test_engine.sh — end-to-end + edge-case tests for the opngx-engine CLI.
# Requires: bash, python3 (numpy+PIL for fixture generation), built binary.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="${ENGINE:-$HERE/../build/opngx-engine}"
TMP="$(mktemp -d /tmp/opngxtest.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
check(){ if [ $? -eq 0 ]; then ok "$1"; else bad "$1"; fi }

echo "== T-1: synthetic fixture, full pipeline =="
python3 "$HERE/gen_fixture.py" "$TMP/fix" >/dev/null || { echo "fixture gen failed"; exit 1; }
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
                  --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
                  --out "$TMP/fix/out" --prefix cam_ --timestamps --metadata -v 2>/dev/null
check "extract runs on synthetic bin"
VOUT=$("$ENGINE" verify "$TMP/fix/ref_pngs" "$TMP/fix/out" --prefix cam_ 2>&1)
if [ $? -eq 0 ]; then ok "pixel-exact vs independently computed refs"; else bad "pixel-exact vs independently computed refs"; echo "$VOUT" | sed 's/^/    | /'; fi

echo "== T-2: timestamps CSV correctness =="
python3 - "$TMP/fix/out/cam__timestamps.csv" << 'EOF'
import sys, csv
rows = list(csv.reader(open(sys.argv[1])))
assert rows[0] == ["frame_index","timestamp_raw","timestamp_hex"], rows[0]
assert len(rows) == 201, f"expected 200 rows+header, got {len(rows)}"
for i, r in enumerate(rows[1:]):
    assert int(r[0]) == i and int(r[1]) == 10_000_000 + i*2000, (i, r)
EOF
check "timestamps: index/tick math exact for all 200 frames"

echo "== T-3: metadata.json validity =="
python3 -c "
import json,sys
m=json.load(open('$TMP/fix/out/metadata.json'))
assert m['width']==64 and m['height']==48 and m['frames']==200
assert m['effective_fps_from_timestamps']==500.0, m['effective_fps_from_timestamps']
"
check "metadata.json parses; geometry + derived fps correct"

echo "== T-4: jobs=1 vs jobs=16 determinism =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/fix/out_j1" --prefix cam_ -j 1 --timestamps --metadata 2>/dev/null
if diff -rq <(cd "$TMP/fix/out" && md5sum *.Png | awk '{print $1}') \
            <(cd "$TMP/fix/out_j1" && md5sum *.Png | awk '{print $1}') >/dev/null; then
  # byte-level compare too
  if diff -r "$TMP/fix/out" "$TMP/fix/out_j1" >/dev/null 2>&1; then
    check "jobs=1 output byte-identical to jobs=default"
  else
    bad "jobs=1 byte-identical"
  fi
else
  bad "jobs=1 md5 sets equal"
fi

echo "== T-5: truncated bin clamps frame count =="
head -c $((8 + 64*48)) "$TMP/fix/cam_9.9/cam_9.9.bin" > "$TMP/trunc.bin"   # XML claims 200 frames, file has 1
"$ENGINE" extract --bin "$TMP/trunc.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/trunc_out" --prefix cam_ 2>/dev/null
N=$(ls "$TMP/trunc_out" | wc -l)
[ "$N" -eq 1 ]; check "truncated bin extracts exactly 1 frame (got $N)"

echo "== T-6: missing footage + no geometry => clear error =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --out "$TMP/noft_out" 2>"$TMP/err.txt"
RC=$?
grep -q "footage\|geometry" "$TMP/err.txt" && [ $RC -ne 0 ]
check "errors with guidance when geometry unknown (rc=$RC)"

echo "== T-7: explicit geometry overrides missing footage =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --out "$TMP/geo_out" --prefix cam_ --width 64 --height 48 --mode raw 2>/dev/null
[ $? -eq 0 ] && [ "$(ls "$TMP/geo_out" | wc -l)" -eq 200 ]
check "raw mode + explicit geometry works"

echo "== T-8: level bounds clamp (0 and 99) =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/lv0" --prefix cam_ -l 0 2>/dev/null && \
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/lv99" --prefix cam_ -l 99 2>/dev/null
check "extreme levels accepted (clamped internally)"

echo "== T-9: 16-bit mode produces valid deeper PNGs =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/bit16" --prefix cam_ --bit-depth 16 2>/dev/null
python3 -c "
import struct, zlib
import numpy as np
from PIL import Image

def read_png_raw(path):
    d=open(path,'rb').read()
    assert d[:8]==b'\x89PNG\r\n\x1a\n'
    pos=8; idat=b''; ihdr=None
    while pos<len(d):
        ln=struct.unpack('>I',d[pos:pos+4])[0]; typ=d[pos+4:pos+8]
        if typ==b'IHDR': ihdr=struct.unpack('>IIBBBBB',d[pos+8:pos+21])
        elif typ==b'IDAT': idat+=d[pos+8:pos+8+ln]
        pos+=12+ln
    return ihdr, zlib.decompress(idat)

ihdr, raw = read_png_raw('$TMP/bit16/cam_00000.Png')
w,h,bd,ct = ihdr[0],ihdr[1],ihdr[2],ihdr[3]
assert (bd,ct)==(16,6), (bd,ct)
stride=w*8+1
assert len(raw)==h*stride, (len(raw), h*stride)
# all filter bytes zero (our writer)
assert all(raw[y*stride]==0 for y in range(h))
px=np.frombuffer(bytearray(raw),dtype=np.uint8).reshape(h,stride)[:,1:].reshape(h,w,4,2)
r16=(px[:,:,0,0].astype(np.uint32)<<8)|px[:,:,0,1]
a16=(px[:,:,3,0].astype(np.uint32)<<8)|px[:,:,3,1]
# expected straight from source bytes + verified vendor formula
src=open('$TMP/fix/cam_9.9/cam_9.9.bin','rb').read()
gray=np.frombuffer(src[8:8+w*h],dtype=np.uint8).reshape(h,w)
lut=np.clip(np.floor((np.arange(256)+49)*1.36+0.5),0,255).astype(np.uint32)
exp=lut[gray]*257
assert np.array_equal(r16, exp), 'R16 mismatch'
assert np.array_equal(a16, np.full((h,w),65535,np.uint32)), 'A16 mismatch'
"
check "16-bit PNGs structurally valid; channels exactly 257x the 8-bit values"

echo "== T-10: raw mode is identity (no clipping) =="
python3 -c "
import numpy as np, struct
from PIL import Image
raw=open('$TMP/fix/cam_9.9/cam_9.9.bin','rb').read()
gray=np.frombuffer(raw[8:8+64*48],dtype=np.uint8).reshape(48,64)
img=np.array(Image.open('$TMP/geo_out/cam_00000.Png'))
assert np.array_equal(img[...,0], gray) and np.all(img[...,3]==255)
"
check "raw mode reproduces source bytes exactly"

echo "== T-11: custom mode B/C applied per formula =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/custom" --prefix cam_ -m custom --brightness 10 --contrast 20 2>/dev/null
python3 -c "
import numpy as np
from PIL import Image
lut=np.clip(np.floor((np.arange(256)+10)*1.4+0.5),0,255).astype(np.uint8)
raw=open('$TMP/fix/cam_9.9/cam_9.9.bin','rb').read()
gray=np.frombuffer(raw[8:8+64*48],dtype=np.uint8).reshape(48,64)
img=np.array(Image.open('$TMP/custom/cam_00000.Png'))
assert np.array_equal(img[...,0], lut[gray])
"
check "custom B=10 C=20 matches independent formula"

echo "== T-12: batch mode walks directory =="
mkdir -p "$TMP/batchroot"
"$ENGINE" batch --in-dir "$TMP/fix" --out-root "$TMP/batchroot" --prefix cam_ 2>/dev/null
[ -d "$TMP/batchroot/cam_9_9" ] && [ "$(ls "$TMP/batchroot/cam_9_9" | wc -l)" -eq 200 ]
check "batch creates cam_9_9 (dot->underscore) with 200 files"

echo "== T-13: verify detects corruption =="
cp -r "$TMP/fix/out" "$TMP/corrupt"
python3 -c "
p='$TMP/corrupt/cam_00007.Png'
d=bytearray(open(p,'rb').read()); d[-40]^=0xFF; open(p,'wb').write(bytes(d))
"
"$ENGINE" verify "$TMP/fix/ref_pngs" "$TMP/corrupt" --prefix cam_ >/dev/null 2>&1
[ $? -ne 0 ]; check "verify fails on corrupted pixel data"

echo "== T-14: grayscale fast path =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/grayout" --prefix cam_ --channels gray -j 4 2>/dev/null
python3 -c "
import struct, zlib
import numpy as np
d=open('$TMP/grayout/cam_00009.Png','rb').read()
w,h,bd,ct=struct.unpack('>IIBB', d[16:26])
assert ct==0 and bd==8, (ct,bd)
pos,idat=8,b''
while pos<len(d):
    ln=struct.unpack('>I',d[pos:pos+4])[0]; typ=d[pos+4:pos+8]
    if typ==b'IDAT': idat+=d[pos+8:pos+8+ln]
    pos+=12+ln
raw=zlib.decompress(idat)
stride=w+1
px=np.frombuffer(bytearray(raw),dtype=np.uint8).reshape(h,stride)[:,1:]
lut=np.clip(np.floor((np.arange(256)+49)*1.36+0.5),0,255).astype(np.uint8)
src=open('$TMP/fix/cam_9.9/cam_9.9.bin','rb').read()
off=9*(8+w*h)+8
gray=np.frombuffer(src[off:off+w*h],dtype=np.uint8).reshape(h,w)
assert np.array_equal(px,lut[gray]), 'gray pixel mismatch'
"
check "grayscale PNGs (colortype 0) pixel-exact per formula"

echo "== T-15: RGBA default preserved after gray runs =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/rgbadef" --prefix cam_ -j 4 2>/dev/null
python3 -c "
import struct
d=open('$TMP/rgbadef/cam_00000.Png','rb').read()
w,h,bd,ct=struct.unpack('>IIBB', d[16:26])
assert ct==6, ct
"
check "default channels remain RGBA"

echo "== T-16: zlib backend end-to-end (audit #1/#2 regression) =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/zout" --prefix cam_ -j 4 --backend zlib 2>/dev/null
[ "$(ls "$TMP/zout" | wc -l)" -eq 200 ]
check "explicit --backend zlib extracts all frames on libdeflate builds"
python3 -c "
import struct, zlib
import numpy as np
from PIL import Image
a=np.array(Image.open('$TMP/fix/ref_pngs/cam_00003.Png'))
b=np.array(Image.open('$TMP/zout/cam_00003.Png'))
assert np.array_equal(a,b), 'zlib-backend pixels differ'
d=open('$TMP/zout/cam_00003.Png','rb').read()
pos,idat=8,b''
while pos<len(d):
    ln=struct.unpack('>I',d[pos:pos+4])[0]; typ=d[pos+4:pos+8]
    if typ==b'IDAT': idat+=d[pos+8:pos+8+ln]
    pos+=12+ln
raw=zlib.decompress(idat)
assert len(raw)==48*(64*4+1)
"
check "zlib backend output decodes cleanly (no double wrapper)"

echo "== T-17: --start subrange parity (audit #5) =="
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/full" --prefix cam_ -j 4 2>/dev/null
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" --footage "$TMP/fix/cam_9.9/cam_9.9.footage" --out "$TMP/sub" --prefix cam_ --start 100 --frames 50 2>/dev/null
ok=1
for i in $(seq 100 149); do
  cmp -s "$TMP/full/cam_$(printf %05d $i).Png" "$TMP/sub/cam_$(printf %05d $i).Png" || { ok=0; break; }
done
[ $ok -eq 1 ]
check "--start 100 --frames 50 produces byte-identical slice of full run"


echo "== T-18: output directory containing spaces (Windows-user pattern) =="
SPDIR="$TMP/Download 10-02-2025"
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
                  --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
                  --out "$SPDIR/SQ_100_s1_png" --prefix SQ_100_ --timestamps -j 4 2>/dev/null
[ "$(ls "$SPDIR/SQ_100_s1_png" | wc -l)" -eq 201 ]
check "spaces in output path: 200 PNGs + timestamps CSV"
"$ENGINE" verifybin --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
    --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
    "$SPDIR/SQ_100_s1_png" --prefix SQ_100_ --json 2>/dev/null | grep -q '"passed":true'
check "spaces in output path: verifybin PASS"


echo "== T-19: Windows-style backslash + drive-letter output path =="
W32OUT='C:\opngx_t19\SQ 100 out'
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
                  --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
                  --out "$W32OUT" --prefix SQ_100_ -j 4 2>"$TMP/t19err.txt"
RC=$?
if [ "$ENGINE" = "/tmp/opencode/wine-engine.sh" ] || echo "$ENGINE" | grep -q "wine\|\.exe"; then
  [ $RC -eq 0 ] || { cat "$TMP/t19err.txt"; false; }
  N=$(find "$(winepath -u 'C:\opngx_t19\SQ 100 out' 2>/dev/null || echo "$TMP/t19fallback")" -name '*.Png' 2>/dev/null | wc -l)
  [ "${N:-0}" -ge 200 ] || { ls "$TMP/t19fallback" 2>/dev/null; false; }
else
  # POSIX: literal directory name with backslashes must still work
  [ $RC -eq 0 ] && [ "$(ls "$W32OUT" | wc -l)" -eq 200 ]
fi
check "backslash+drive-letter output path (mkdir_p drive skip)"


echo "== T-20: non-ASCII (UTF-8) output directory =="
case "$ENGINE" in
  *wine*|*.exe) UDIR="$TMP/brow ünïcode" ;;   # wine argv is ACP-mangled
  *)            UDIR="$TMP/brow ünïcode भीम" ;;  # real Windows: wmain UTF-16 argv
esac
"$ENGINE" extract --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
                  --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
                  --out "$UDIR" --prefix cam_ -j 4 2>"$TMP/t20err.txt" || \
                  { cat "$TMP/t20err.txt"; false; }
[ "$(ls "$UDIR" | wc -l)" -eq 200 ]
check "UTF-8 output dir: 200 PNGs (wide-API conversion)"
"$ENGINE" verifybin --bin "$TMP/fix/cam_9.9/cam_9.9.bin" \
    --footage "$TMP/fix/cam_9.9/cam_9.9.footage" \
    "$UDIR" --prefix cam_ --json 2>/dev/null | grep -q '"passed":true'
check "UTF-8 output dir: verifybin PASS"

echo
echo "RESULTS: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]

