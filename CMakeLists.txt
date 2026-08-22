cmake_minimum_required(VERSION 3.16)
project(opngx C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Portability: NEVER -march=native in shipped binaries. Runtime dispatch
# (target_clones on GCC/glibc x86-64) selects AVX-512/AVX2 when present.
add_compile_options(-Wall -Wextra -Werror -Wno-error=unknown-pragmas)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/vendor/stb)

option(OPNGX_WITH_LIBDEFLATE "Use libdeflate backend" ON)
option(OPNGX_WITH_ZLIB       "Allow zlib fallback backend" ON)
option(OPNGX_BUILD_SHARED    "Build libopngx shared library" ON)
option(OPNGX_LTO             "Link-time optimization for Release" ON)

set(CORE_SOURCES
  src/footage.c src/transform.c src/pngout.c src/compress.c
  src/extract.c src/verify.c src/util.c src/cpu.c src/port.c
  src/encode.c)

find_package(Threads REQUIRED)

# ---- optional LTO ----
include(CheckIPOSupported)
check_ipo_supported(RESULT ipo_ok OUTPUT ipo_msg)
if(OPNGX_LTO AND ipo_ok)
  set(CMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
  message(STATUS "LTO enabled for Release")
endif()

# ---- backends ----
set(HAVE_LD OFF)
if(OPNGX_WITH_LIBDEFLATE)
  find_library(LIBDEFLATE_LIB deflate)
  find_path(LIBDEFLATE_INC libdeflate.h)
  if(LIBDEFLATE_LIB AND LIBDEFLATE_INC)
    set(HAVE_LD ON)
    message(STATUS "libdeflate: ${LIBDEFLATE_LIB}")
  endif()
endif()

set(HAVE_ZLIB OFF)
if(NOT HAVE_LD OR OPNGX_WITH_ZLIB)
  find_package(ZLIB QUIET)
  if(ZLIB_FOUND)
    set(HAVE_ZLIB ON)
  elseif(NOT HAVE_LD)
    message(FATAL_ERROR "neither libdeflate nor zlib found")
  endif()
endif()

function(opngx_apply_backend tgt)
  if(HAVE_LD)
    target_compile_definitions(${tgt} PRIVATE OPNGX_HAVE_LIBDEFLATE)
    target_include_directories(${tgt} PRIVATE ${LIBDEFLATE_INC})
    target_link_libraries(${tgt} PRIVATE ${LIBDEFLATE_LIB})
  endif()
  if(HAVE_ZLIB)
    target_link_libraries(${tgt} PRIVATE ZLIB::ZLIB)
  endif()
endfunction()

# ---------- CLI binary ----------
add_executable(opngx-engine ${CORE_SOURCES} src/main.c)
target_include_directories(opngx-engine PRIVATE src)
target_link_libraries(opngx-engine PRIVATE Threads::Threads m)
opngx_apply_backend(opngx-engine)

# Parallelism is provided by the in-house portable worker pool
# (src/port.c: pthreads / Win32) — no OpenMP runtime dependency at all.
# This enables fully-static single-file executables on every platform.

if(WIN32)
  # fully static CLI: no runtime DLL hunting whatsoever
  target_link_options(opngx-engine PRIVATE -static -static-libgcc)
endif()

# ---------- shared library for Python bindings ----------
if (OPNGX_BUILD_SHARED)
  add_library(opngx SHARED ${CORE_SOURCES} src/libapi.c)
  target_include_directories(opngx PRIVATE src)
  set_target_properties(opngx PROPERTIES OUTPUT_NAME opngx)
  if(WIN32)
    # ctypes needs the whole job API exported. A single explicit
    # __declspec(dllexport) anywhere disables GNU auto-export, so force it:
    set_target_properties(opngx PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
    target_link_options(opngx PRIVATE -Wl,--export-all-symbols)
  endif()
  opngx_apply_backend(opngx)
  target_link_libraries(opngx PRIVATE Threads::Threads m)
endif()
