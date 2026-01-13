//! Video Sync GUI - Main Application Entry Point
//!
//! A desktop application for analyzing audio/video timing discrepancies
//! and performing lossless MKV remuxing with automatic synchronization.

mod app;
mod config;
mod i18n;
mod pages;
mod dialogs;
mod widgets;

use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

fn main() -> cosmic::iced::Result {
    // Set up logging
    tracing_subscriber::registry()
        .with(EnvFilter::from_default_env().add_directive(tracing::Level::INFO.into()))
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Get the system's preferred languages for i18n
    let requested_languages = i18n_embed::DesktopLanguageRequester::requested_languages();
    i18n::init(&requested_languages);

    // Configure application window settings
    let settings = cosmic::app::Settings::default()
        .size_limits(
            cosmic::iced::Limits::NONE
                .min_width(800.0)
                .min_height(500.0),
        )
        .size(cosmic::iced::Size::new(1000.0, 600.0));

    // Run the application
    cosmic::app::run::<app::App>(settings, app::Flags::default())
}
