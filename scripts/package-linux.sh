#!/usr/bin/env bash
# package-linux.sh — build every distributable Linux form of opngx.
#
#   ./scripts/package-linux.sh [version]
#
# Produces in dist/:
#   opngx-<v>-linux-x86_64.tar.gz   static executable + docs (universal)
#   opngx_<v>_amd64.deb             Debian/Ubuntu/Mint package (if dpkg-deb)
#   opngx-<v>-x86_64.pkg.tar.zst    Arch package (if makepkg available)
#
# The binary is fully static — no runtime dependencies whatsoever.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-1.3.0}"
DIST="$HERE/dist"
BUILD="${OPNGX_PKG_BUILD:-/tmp/opngx-pkgbuild}"
mkdir -p "$DIST" "$BUILD"

echo "== 1. static engine =="
cmake -S "$HERE" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DLIBDEFLATE_LIB="${LIBDEFLATE_STATIC:?run: cmake -S libdeflate... see wiki}" \
  -DLIBDEFLATE_INC="${LIBDEFLATE_INC:?path to libdeflate.h}" \
  -DOPNGX_WITH_ZLIB=OFF -DCMAKE_EXE_LINKER_FLAGS="-static" >/dev/null
cmake --build "$BUILD" -j"$(nproc)"
strip "$BUILD/opngx-engine"

STAGE="$BUILD/stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"

# ---------- universal tarball ----------
TARBALL="opngx-$VERSION-linux-x86_64.tar.gz"
cp "$BUILD/opngx-engine" "$STAGE/"
cp "$HERE/README.md" "$HERE/docs/FORMAT.md" "$HERE/docs/BENCHMARKS.md" "$STAGE/"
tar czf "$DIST/$TARBALL" -C "$STAGE" .
echo "   $DIST/$TARBALL"

# ---------- .deb ----------
if command -v dpkg-deb >/dev/null; then
  DEBROOT="$BUILD/debroot"
  rm -rf "$DEBROOT"
  install -Dm755 "$BUILD/opngx-engine" "$DEBROOT/usr/bin/opngx-engine"
  install -Dm644 "$HERE/README.md"     "$DEBROOT/usr/share/doc/opngx/README.md"
  install -Dm644 "$HERE/docs/FORMAT.md" "$DEBROOT/usr/share/doc/opngx/FORMAT.md"
  install -Dm644 "$HERE/LICENSE"       "$DEBROOT/usr/share/doc/opngx/copyright"
  mkdir -p "$DEBROOT/DEBIAN"
  cat > "$DEBROOT/DEBIAN/control" <<EOF
Package: opngx
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: opngx contributors <opngx@users.noreply.github.com>
Description: Ultra-fast pixel-exact Optronis .bin footage extractor
 Converts Optronis TimeViewer high-speed-camera recordings to
 PNG/JPG/BMP/TIFF using every CPU core. Includes the opngx-engine CLI.
Homepage: https://github.com/Shuvam-Banerji-Seal/opngx
EOF
  dpkg-deb --root-owner-group --build "$DEBROOT" \
           "$DIST/opngx_${VERSION}_amd64.deb" >/dev/null
  echo "   $DIST/opngx_${VERSION}_amd64.deb"
else
  echo "   dpkg-deb not found — skipping .deb"
fi

# ---------- Arch package ----------
if command -v makepkg >/dev/null; then
  PKGDIR="$BUILD/arch"
  rm -rf "$PKGDIR"; mkdir -p "$PKGDIR"
  cp "$BUILD/opngx-engine" "$PKGDIR/"
  cat > "$PKGDIR/PKGBUILD" <<EOF
pkgname=opngx
pkgver=$VERSION
pkgrel=1
pkgdesc='Ultra-fast pixel-exact Optronis .bin footage extractor'
arch=('x86_64')
url='https://github.com/Shuvam-Banerji-Seal/opngx'
license=(MIT)
package() {
  install -Dm755 "\$srcdir/../opngx-engine" "\$pkgdir/usr/bin/opngx-engine"
}
EOF
  (cd "$PKGDIR" && makepkg -f >/dev/null 2>&1 && \
    cp opngx-$VERSION-*.pkg.tar.zst "$DIST/" 2>/dev/null || true)
  ls "$DIST"/opngx-*.pkg.tar.zst 2>/dev/null && echo "   ^ arch package" || \
    echo "   makepkg present but build skipped"
fi

echo "== done =="
