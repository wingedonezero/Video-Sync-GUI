//! Internationalization support using fluent

use i18n_embed::{
    fluent::{fluent_language_loader, FluentLanguageLoader},
    DesktopLanguageRequester, LanguageLoader,
};
use once_cell::sync::Lazy;
use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "i18n/"]
struct Localizations;

pub static LANGUAGE_LOADER: Lazy<FluentLanguageLoader> = Lazy::new(|| {
    let loader = fluent_language_loader!();
    loader
        .load_fallback_language(&Localizations)
        .expect("Failed to load fallback language");
    loader
});

/// Initialize i18n with the given language preferences
pub fn init(requested_languages: &[unic_langid::LanguageIdentifier]) {
    if let Err(e) = i18n_embed::select(&*LANGUAGE_LOADER, &Localizations, requested_languages) {
        tracing::warn!("Failed to load requested languages: {}", e);
    }
}

/// Get a localized string by key
#[macro_export]
macro_rules! fl {
    ($key:expr) => {
        i18n_embed_fl::fl!($crate::i18n::LANGUAGE_LOADER, $key)
    };
    ($key:expr, $($arg:tt)*) => {
        i18n_embed_fl::fl!($crate::i18n::LANGUAGE_LOADER, $key, $($arg)*)
    };
}
