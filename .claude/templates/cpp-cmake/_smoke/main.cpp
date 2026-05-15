// Minimal smoke target for the cpp-cmake runtime stub.
//
// build-engineer invokes `./smoke-test --version` after a fresh build to fill
// manifest.smoke_test. The output here is what ends up in
// manifest.smoke_test.stdout_tail.
//
// Replace or delete this once you have your first real native experiment.

#include <cstring>
#include <iostream>

int main(int argc, char** argv) {
    if (argc > 1 && std::strcmp(argv[1], "--version") == 0) {
        std::cout << "experiment-smoke-test 0.0.0" << std::endl;
        return 0;
    }
    std::cout << "experiment template smoke OK" << std::endl;
    return 0;
}
