//! Video Sync GUI Application
//!
//! This crate builds the Qt UI via CMake during cargo build.
//! The actual executable is `target/{debug,release}/video-sync-gui`.
//!
//! Usage:
//!   cargo build --release -p vsg_app
//!   ./target/release/video-sync-gui

use std::os::unix::process::CommandExt;
use std::process::Command;

fn main() {
    // The Qt executable is built by build.rs and copied to target/
    let qt_app = env!("VSG_QT_APP");

    // Replace this process with the Qt application
    let err = Command::new(qt_app)
        .args(std::env::args().skip(1))
        .exec();

    // exec() only returns on error
    eprintln!("Failed to launch Qt application: {}", err);
    eprintln!("Expected at: {}", qt_app);
    std::process::exit(1);
}
