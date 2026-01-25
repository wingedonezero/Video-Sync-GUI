use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let profile = env::var("PROFILE").unwrap(); // "debug" or "release"

    // Workspace root
    let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();

    // Path to qt_ui sources
    let qt_ui_dir = workspace_root.join("qt_ui");

    // Target directory where Rust libraries are built
    let target_dir = workspace_root.join("target").join(&profile);

    // Path to libvsg_bridge.a
    let bridge_lib = target_dir.join("libvsg_bridge.a");

    // CXX bridge generates headers - we need to find the OUT_DIR for vsg_bridge
    // The headers are at: target/{profile}/build/vsg_bridge-{hash}/out/cxxbridge/
    // We'll search for it
    let cxxbridge_dir = find_cxxbridge_dir(&workspace_root.join("target").join(&profile).join("build"));

    let build_dir = out_dir.join("qt_build");
    std::fs::create_dir_all(&build_dir).unwrap();

    // Determine build type
    let build_type = if profile == "release" {
        "Release"
    } else {
        "Debug"
    };

    // Build CMake args
    let mut cmake_args = vec![
        qt_ui_dir.to_string_lossy().to_string(),
        format!("-DCMAKE_BUILD_TYPE={}", build_type),
    ];

    // Add Rust bridge paths if available
    if bridge_lib.exists() {
        cmake_args.push(format!("-DVSG_BRIDGE_LIB={}", bridge_lib.display()));
        println!("cargo:warning=Found Rust bridge: {}", bridge_lib.display());
    } else {
        println!("cargo:warning=Rust bridge not found at {}", bridge_lib.display());
    }

    if let Some(ref cxx_dir) = cxxbridge_dir {
        cmake_args.push(format!("-DVSG_CXXBRIDGE_DIR={}", cxx_dir.display()));
        println!("cargo:warning=Found CXX headers: {}", cxx_dir.display());
    } else {
        println!("cargo:warning=CXX headers not found");
    }

    // Run CMake configure
    let cmake_status = Command::new("cmake")
        .current_dir(&build_dir)
        .args(&cmake_args)
        .status()
        .expect("Failed to run cmake. Is cmake installed?");

    if !cmake_status.success() {
        panic!("CMake configuration failed. Make sure Qt6 is installed.");
    }

    // Run CMake build
    let build_status = Command::new("cmake")
        .current_dir(&build_dir)
        .args(["--build", ".", "--parallel"])
        .status()
        .expect("Failed to run cmake build");

    if !build_status.success() {
        panic!("CMake build failed");
    }

    // Copy the executable to target directory
    std::fs::create_dir_all(&target_dir).ok();

    let src_exe = build_dir.join("video-sync-gui");
    let dst_exe = target_dir.join("video-sync-gui-qt");

    if src_exe.exists() {
        std::fs::copy(&src_exe, &dst_exe).expect("Failed to copy executable");
        println!("cargo:warning=Built: {}", dst_exe.display());
    }

    // Tell cargo where to find the executable
    println!("cargo:rustc-env=VSG_QT_APP={}", dst_exe.display());

    // Note: We do NOT link vsg_bridge into the Rust binary.
    // The Rust binary (vsg_app) just exec's the Qt application.
    // The Qt binary (built by CMake above) links against libvsg_bridge.a directly.

    // Rerun if sources change
    for entry in walkdir(&qt_ui_dir) {
        if entry.extension().map_or(false, |e| e == "cpp" || e == "hpp") {
            println!("cargo:rerun-if-changed={}", entry.display());
        }
    }
    println!("cargo:rerun-if-changed={}", qt_ui_dir.join("CMakeLists.txt").display());

    // Rerun if bridge changes
    let bridge_src = workspace_root.join("crates").join("vsg_bridge").join("src");
    println!("cargo:rerun-if-changed={}", bridge_src.join("lib.rs").display());
}

/// Find the CXX bridge header directory
fn find_cxxbridge_dir(build_dir: &PathBuf) -> Option<PathBuf> {
    if !build_dir.exists() {
        return None;
    }

    // Look for vsg_bridge-*/out/cxxbridge/
    if let Ok(entries) = std::fs::read_dir(build_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                let name = path.file_name()?.to_string_lossy();
                if name.starts_with("vsg_bridge-") {
                    let cxxbridge = path.join("out").join("cxxbridge");
                    if cxxbridge.exists() {
                        return Some(cxxbridge);
                    }
                }
            }
        }
    }
    None
}

fn walkdir(dir: &PathBuf) -> Vec<PathBuf> {
    let mut files = Vec::new();
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                files.extend(walkdir(&path));
            } else {
                files.push(path);
            }
        }
    }
    files
}
