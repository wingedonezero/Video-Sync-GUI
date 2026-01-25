use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let profile = env::var("PROFILE").unwrap(); // "debug" or "release"

    // Path to qt_ui sources
    let qt_ui_dir = manifest_dir
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("qt_ui");

    let build_dir = out_dir.join("qt_build");
    std::fs::create_dir_all(&build_dir).unwrap();

    // Determine build type
    let build_type = if profile == "release" {
        "Release"
    } else {
        "Debug"
    };

    // Run CMake configure
    let cmake_status = Command::new("cmake")
        .current_dir(&build_dir)
        .arg(&qt_ui_dir)
        .arg(format!("-DCMAKE_BUILD_TYPE={}", build_type))
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
    let target_dir = manifest_dir
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("target")
        .join(&profile);

    std::fs::create_dir_all(&target_dir).ok();

    let src_exe = build_dir.join("video-sync-gui");
    let dst_exe = target_dir.join("video-sync-gui");

    if src_exe.exists() {
        std::fs::copy(&src_exe, &dst_exe).expect("Failed to copy executable");
        println!("cargo:warning=Built: {}", dst_exe.display());
    }

    // Tell cargo where to find the executable
    println!("cargo:rustc-env=VSG_QT_APP={}", dst_exe.display());

    // Rerun if sources change
    for entry in walkdir(&qt_ui_dir) {
        if entry.extension().map_or(false, |e| e == "cpp" || e == "hpp") {
            println!("cargo:rerun-if-changed={}", entry.display());
        }
    }
    println!("cargo:rerun-if-changed={}", qt_ui_dir.join("CMakeLists.txt").display());
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
