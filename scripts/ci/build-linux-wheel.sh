#!/usr/bin/env bash
# Build the manylinux2014 x86_64 wheel + the sdist. Runs INSIDE
# quay.io/pypa/manylinux2014_x86_64 (glibc 2.17, so the wheel loads on any
# distro newer than CentOS 7), with the repository mounted at /io:
#
#   docker run --rm -v "$PWD:/io" -w /io quay.io/pypa/manylinux2014_x86_64 \
#       bash scripts/ci/build-linux-wheel.sh
#
# Output: /io/wheelhouse/opngx-<ver>-py3-none-manylinux2014_x86_64.whl
#         /io/wheelhouse/opngx-<ver>.tar.gz
set -euxo pipefail
export PYTHONDONTWRITEBYTECODE=1   # /io is shared with the runner: leave no root-owned caches
cd /io
PY=/opt/python/cp312-cp312/bin/python
"$PY" -m pip install --quiet --upgrade cmake ninja build wheel "setuptools>=77" auditwheel
export PATH="/opt/python/cp312-cp312/bin:$PATH"

# libdeflate: static + PIC, linked into both the .so and the CLI
rm -rf /tmp/ld /tmp/ldb
git clone --depth 1 --branch v1.22 https://github.com/ebiggers/libdeflate.git /tmp/ld
cmake -S /tmp/ld -B /tmp/ldb -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLIBDEFLATE_BUILD_SHARED_LIB=OFF -DLIBDEFLATE_BUILD_TESTS=OFF \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON
cmake --build /tmp/ldb
LDA=$(find /tmp/ldb -name libdeflate.a | head -1)

rm -rf /tmp/bw
cmake -S . -B /tmp/bw -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLIBDEFLATE_LIB="$LDA" -DLIBDEFLATE_INC=/tmp/ld -DOPNGX_WITH_ZLIB=OFF
cmake --build /tmp/bw
strip /tmp/bw/opngx-engine /tmp/bw/libopngx.so
/tmp/bw/opngx-engine --version
objdump -T /tmp/bw/libopngx.so | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1

rm -rf /tmp/raw wheelhouse
"$PY" scripts/build_wheel.py --lib /tmp/bw/libopngx.so --engine /tmp/bw/opngx-engine \
  --plat-tag linux_x86_64 --outdir /tmp/raw
auditwheel show /tmp/raw/*.whl
auditwheel repair --plat manylinux2014_x86_64 -w wheelhouse /tmp/raw/*.whl
"$PY" -m build --sdist --outdir wheelhouse python

# install-test the repaired wheel on the oldest and newest supported CPython
for v in cp39-cp39 cp313-cp313; do
  rm -rf "/tmp/venv-$v"
  "/opt/python/$v/bin/python" -m venv "/tmp/venv-$v"
  "/tmp/venv-$v/bin/python" -m pip install --quiet wheelhouse/*.whl pytest
  (cd /tmp && "/tmp/venv-$v/bin/python" -c "
import opngx, opngx.analysis.native as n
from opngx import _engine
print(opngx.__version__, _engine.library_path(), 'native analysis', n.available())
assert '_native' in str(_engine.library_path()) and n.available()
")
  (cd python/tests && "/tmp/venv-$v/bin/python" -m pytest -q -p no:cacheprovider \
      test_analysis.py test_opngx.py)
done
ls -la wheelhouse
