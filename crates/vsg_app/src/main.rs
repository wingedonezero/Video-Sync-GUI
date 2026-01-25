//! Video Sync GUI Application
//!
//! This crate builds the Qt UI via CMake during cargo build.
//! The actual executable is `target/{debug,release}/video-sync-gui`.
//!
//! Usage:
//!   cargo build --release -p vsg_app
//!   ./target/release/video-sync-gui

fn main() {
    // The Qt executable is built by build.rs and copied to target/
    // This Rust binary just prints a help message
    let qt_app = env!("VSG_QT_APP");
    println!("Video Sync GUI");
    println!();
    println!("The Qt application has been built at:");
    println!("  {}", qt_app);
    println!();
    println!("Run it directly:");
    println!("  {}", qt_app);
}
