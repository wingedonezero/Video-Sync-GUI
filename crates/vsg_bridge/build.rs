use std::env;
use std::path::PathBuf;

fn main() {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());

    cxx_build::bridge("src/lib.rs")
        .std("c++17")
        .compile("vsg_bridge");

    println!("cargo:rerun-if-changed=src/lib.rs");

    // Export paths for dependent crates' build scripts.
    // These become DEP_VSG_BRIDGE_* environment variables in dependents.

    // The cxxbridge directory contains generated C++ headers
    let cxxbridge_dir = out_dir.join("cxxbridge");
    println!("cargo:cxxbridge={}", cxxbridge_dir.display());

    // The OUT_DIR for this crate (useful for finding build artifacts)
    println!("cargo:out_dir={}", out_dir.display());
}
