cmake_minimum_required(VERSION 3.16)
project(opngx C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Portability: NEVER -march=native in shipped binaries. Runtime dispatch
# (target_clones on GCC/glibc x86-64) selects AVX-512/AVX2 when present.
add_compile_options(-Wall -Wextra -Werror)

option(OPNGX_WITH_LIBDEFLATE "Use libdeflate backend" ON)
option(OPNGX_WITH_ZLIB       "Allow zlib fallback backend" ON)
option(OPNGX_BUILD_SHARED    "Build libopngx shared library" ON)
option(OPNGX_LTO             "Link-time optimization for Release" ON)

set(CORE_SOURCES
  src/footage.c src/transform.c src/pngout.c src/compress.c
  src/extract.c src/verify.c src/util.c src/cpu.c src/port.c)

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

find_package(OpenMP)
if(OpenMP_C_FOUND)
  target_link_libraries(opngx-engine PRIVATE OpenMP::OpenMP_C)
endif()

if(WIN32)
  # fully static-ish CLI: no runtime DLL hunting (incl. OpenMP runtime)
  target_link_options(opngx-engine PRIVATE -static -static-libgcc)
  if(OpenMP_C_FOUND)
    # mingw gcc lacks -static-openmp; link the static libgomp archive
    find_library(MINGW_LIBGOMP_AR NAMES libgomp.a
                 PATHS /usr/x86_64-w64-mingw32/lib NO_DEFAULT_PATH)
    if(MINGW_LIBGOMP_AR)
      target_link_libraries(opngx-engine PRIVATE ${MINGW_LIBGOMP_AR})
      message(STATUS "static libgomp: ${MINGW_LIBGOMP_AR}")
    endif()
  endif()
endif()

# ---------- shared library for Python bindings ----------
if (OPNGX_BUILD_SHARED)
  add_library(opngx SHARED ${CORE_SOURCES} src/libapi.c)
  target_include_directories(opngx PRIVATE src)
  set_target_properties(opngx PROPERTIES OUTPUT_NAME opngx)
  opngx_apply_backend(opngx)
  if(OpenMP_C_FOUND)
    target_link_libraries(opngx PRIVATE OpenMP::OpenMP_C)
  endif()
  target_link_libraries(opngx PRIVATE Threads::Threads m)
endif()
