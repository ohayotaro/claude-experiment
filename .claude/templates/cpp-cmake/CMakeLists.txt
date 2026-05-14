# Top-level CMakeLists.txt — stub copied by /init-experiment when
# runtime: cpp-cmake. Edit freely; build-engineer reads this when computing
# the build_id.
#
# Layout convention (see .claude/agents/build-engineer.md):
#   src/native/<experiment_id>/   — heavy C++ sources
#   build/<build_id>/             — out-of-tree build directory (gitignored)
#   data/builds/<build_id>/       — installed binaries + manifest (immutable)

cmake_minimum_required(VERSION 3.20)
project(experiment LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# add_subdirectory(src/native/<experiment_id>)
