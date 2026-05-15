/* Minimal smoke target for the make runtime stub.
 *
 * build-engineer invokes `./smoke-test --version` after a fresh build to fill
 * manifest.smoke_test. The output here is what ends up in
 * manifest.smoke_test.stdout_tail.
 *
 * Replace or delete this once you have your first real native experiment.
 */

#include <stdio.h>
#include <string.h>

int main(int argc, char** argv) {
    if (argc > 1 && strcmp(argv[1], "--version") == 0) {
        printf("experiment-smoke-test 0.0.0\n");
        return 0;
    }
    printf("experiment template smoke OK\n");
    return 0;
}
