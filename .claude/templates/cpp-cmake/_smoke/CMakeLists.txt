# Smoke build target. Copied verbatim to src/native/_smoke/CMakeLists.txt by
# /init-experiment when runtime: cpp-cmake. build-engineer invokes
# `./smoke-test --version` as the manifest.smoke_test command.

add_executable(smoke-test main.cpp)
set_target_properties(smoke-test PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
