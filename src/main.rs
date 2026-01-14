//! Video-Sync-GUI Binary Entry Point

use anyhow::Result;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "video_sync_gui=debug,info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    tracing::info!("Video-Sync-GUI starting...");

    // TODO: Initialize libcosmic Application when UI is implemented
    // For now, just print version info
    println!("Video-Sync-GUI v{}", env!("CARGO_PKG_VERSION"));
    println!("Rust rewrite in progress...");

    Ok(())
}
