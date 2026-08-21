cmake_minimum_required(VERSION 3.16)
project(opngx C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(-Wall -Wextra -Werror)

find_package(Threads REQUIRED)

option(OPNGX_WITH_LIBDEFLATE "Use libdeflate backend" ON)
option(OPNGX_BUILD_SHARED    "Build libopngx shared library" ON)

set(CORE_SOURCES
  src/footage.c src/transform.c src/pngout.c src/compress.c
  src/extract.c src/verify.c src/util.c src/cpu.c)

# Portability: NEVER use -march=native in shipped binaries. Runtime dispatch
# (target_clones on GCC/glibc x86-64) selects AVX-512/AVX2 when present.
add_compile_options(-Wall -Wextra -Werror)

# ---------- CLI binary ----------
add_executable(opngx-engine ${CORE_SOURCES} src/main.c)
target_include_directories(opngx-engine PRIVATE src)
target_link_libraries(opngx-engine PRIVATE Threads::Threads m)

if (OPNGX_WITH_LIBDEFLATE)
  find_library(LIBDEFLATE_LIB deflate)
  find_path(LIBDEFLATE_INC libdeflate.h)
  find_package(ZLIB REQUIRED)   # always linked: runtime-selectable fallback backend
  if (LIBDEFLATE_LIB AND LIBDEFLATE_INC)
    target_compile_definitions(opngx-engine PRIVATE OPNGX_HAVE_LIBDEFLATE)
    target_include_directories(opngx-engine PRIVATE ${LIBDEFLATE_INC})
    target_link_libraries(opngx-engine PRIVATE ${LIBDEFLATE_LIB})
    message(STATUS "libdeflate: ${LIBDEFLATE_LIB}")
  else()
    message(STATUS "libdeflate not found — zlib-only build")
  endif()
  target_link_libraries(opngx-engine PRIVATE ZLIB::ZLIB)
else()
  find_package(ZLIB REQUIRED)
  target_link_libraries(opngx-engine PRIVATE ZLIB::ZLIB)
endif()

# OpenMP for the parallel engine
find_package(OpenMP)
if (OpenMP_C_FOUND)
  target_link_libraries(opngx-engine PRIVATE OpenMP::OpenMP_C)
endif()

# ---------- shared library for Python bindings ----------
if (OPNGX_BUILD_SHARED)
  add_library(opngx SHARED ${CORE_SOURCES} src/libapi.c)
  target_include_directories(opngx PRIVATE src)
  target_compile_definitions(opngx PRIVATE OPNGX_BUILDING_LIB)
  set_target_properties(opngx PROPERTIES OUTPUT_NAME opngx)
  find_package(ZLIB REQUIRED)
  if (OPNGX_WITH_LIBDEFLATE AND LIBDEFLATE_LIB AND LIBDEFLATE_INC)
    target_compile_definitions(opngx PRIVATE OPNGX_HAVE_LIBDEFLATE)
    target_include_directories(opngx PRIVATE ${LIBDEFLATE_INC})
    target_link_libraries(opngx PRIVATE ${LIBDEFLATE_LIB})
  endif()
  target_link_libraries(opngx PRIVATE ZLIB::ZLIB)
  if (OpenMP_C_FOUND)
    target_link_libraries(opngx PRIVATE OpenMP::OpenMP_C)
  endif()
  target_link_libraries(opngx PRIVATE Threads::Threads m)
endif()
