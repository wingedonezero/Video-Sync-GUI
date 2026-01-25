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

    // The cxxbridge/include directory contains generated C++ headers
    // Headers are at: cxxbridge/include/vsg_bridge/src/lib.rs.h
    //                 cxxbridge/include/rust/cxx.h
    let cxxbridge_include = out_dir.join("cxxbridge").join("include");
    println!("cargo:cxxbridge={}", cxxbridge_include.display());

    // The OUT_DIR for this crate (useful for finding build artifacts)
    println!("cargo:out_dir={}", out_dir.display());
}
