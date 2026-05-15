// Minimal smoke target for the rust-cargo runtime stub.
//
// build-engineer invokes `./smoke-test --version` after a fresh build to fill
// manifest.smoke_test. The output here is what ends up in
// manifest.smoke_test.stdout_tail.
//
// Replace or delete this once you have your first real native experiment.

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 && args[1] == "--version" {
        println!("experiment-smoke-test 0.0.0");
        return;
    }
    println!("experiment template smoke OK");
}
