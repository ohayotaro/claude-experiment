# Top-level CMakeLists.txt — stub copied by /init-experiment when
# runtime: cpp-cmake. Edit freely; build-engineer reads this when computing
# the build_id.
#
# Layout convention (see .claude/agents/build-engineer.md):
#   src/native/<experiment_id>/   — heavy C++ sources
#   build/<build_id>/             — out-of-tree build directory (gitignored)
#   data/builds/<build_id>/       — installed binaries + manifest (immutable)
#
# The `_smoke` subdirectory ships a minimal hello-world that build-engineer
# can compile + smoke-test before any real experiment is registered. This
# proves the toolchain is wired up and `manifest.smoke_test` has something
# meaningful to record. Delete `src/native/_smoke/` once you have your first
# real experiment (or keep it as a smoke target — it's two lines of source).

cmake_minimum_required(VERSION 3.20)
project(experiment LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Smoke target: built by build-engineer to verify the toolchain. Honors the
# `_smoke` layout convention. If you remove src/native/_smoke/, drop the
# add_subdirectory line below (CMake will warn otherwise).
if(EXISTS ${CMAKE_SOURCE_DIR}/src/native/_smoke/CMakeLists.txt)
    add_subdirectory(src/native/_smoke)
endif()

# Per-experiment subdirectories — uncomment as /design-experiment registers them.
# add_subdirectory(src/native/<experiment_id>)
