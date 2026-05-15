# Top-level Makefile — stub copied by /init-experiment when runtime: make.
# build-engineer reads this when computing the build_id.
#
# Convention: every experiment defines a target named experiment-<id> that
# accepts RUN_ID, OUTPUT_DIR, SEED env vars and runs the experiment.
#
# The `smoke-test` target builds a minimal hello-world from
# src/native/_smoke/main.c. build-engineer compiles + runs it as the
# manifest.smoke_test command before any real experiment exists. Drop this
# target once you have your first real experiment (or keep it as a smoke
# check — it's two lines of source).

CC ?= cc
CFLAGS ?= -O2 -Wall
BUILD_DIR ?= build

.PHONY: all clean smoke-test

all: smoke-test

smoke-test: $(BUILD_DIR)/bin/smoke-test

$(BUILD_DIR)/bin/smoke-test: src/native/_smoke/main.c
	@mkdir -p $(BUILD_DIR)/bin
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -rf $(BUILD_DIR)
