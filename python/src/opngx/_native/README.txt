The platform wheels put the native engine here: libopngx.so / libopngx.dll
(loaded through ctypes) and the opngx-engine CLI (used for verification).
scripts/build_wheel.py fills this folder; the source tree ships it empty.
