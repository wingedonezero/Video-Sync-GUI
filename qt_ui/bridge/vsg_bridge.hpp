#pragma once

// VSG Bridge - C++ wrapper for Rust vsg_core via CXX
// This header provides a clean interface to the Rust bridge functions

#ifdef VSG_HAS_BRIDGE
// Include the CXX-generated header when bridge is available
#include "vsg_bridge/src/lib.rs.h"
#include <QString>
#include <QStringList>
#include <vector>

namespace VsgBridge {

/// Load application settings from config file
inline vsg::AppSettings loadSettings() {
    return vsg::bridge_load_settings();
}

/// Save application settings to config file
inline bool saveSettings(const vsg::AppSettings& settings) {
    return vsg::bridge_save_settings(settings);
}

/// Get the config file path
inline QString getConfigPath() {
    return QString::fromStdString(std::string(vsg::bridge_get_config_path()));
}

/// Get vsg_core version
inline QString version() {
    return QString::fromStdString(std::string(vsg::bridge_version()));
}

/// Run analysis on source paths
inline std::vector<vsg::AnalysisResult> runAnalysis(const QStringList& paths) {
    rust::Vec<rust::String> rustPaths;
    for (const auto& path : paths) {
        rustPaths.push_back(rust::String(path.toStdString()));
    }

    auto results = vsg::bridge_run_analysis(
        rust::Slice<const rust::String>(rustPaths.data(), rustPaths.size())
    );

    std::vector<vsg::AnalysisResult> out;
    for (const auto& r : results) {
        out.push_back(r);
    }
    return out;
}

/// Check if bridge is available
inline constexpr bool isAvailable() { return true; }

} // namespace VsgBridge

#else
// Stub implementation when bridge is not available

#include <QString>
#include <QStringList>
#include <vector>

namespace VsgBridge {

struct PathSettings {
    QString output_folder = "sync_output";
    QString temp_root = ".temp";
    QString logs_folder = ".logs";
    QString last_source1_path;
    QString last_source2_path;
};

struct LoggingSettings {
    bool compact = true;
    bool autoscroll = true;
    int error_tail = 20;
    int progress_step = 20;
    bool show_options_pretty = false;
    bool show_options_json = false;
    bool archive_logs = true;
};

struct AnalysisSettings {
    QString mode = "audio";
    QString correlation_method = "scc";
    int chunk_count = 10;
    int chunk_duration = 15;
    double min_match_pct = 5.0;
    double scan_start_pct = 5.0;
    double scan_end_pct = 95.0;
    bool use_soxr = true;
    bool audio_peak_fit = true;
    QString sync_mode = "positive_only";
};

struct ChapterSettings {
    bool rename = false;
    bool snap_enabled = false;
    QString snap_mode = "previous";
    int snap_threshold_ms = 250;
    bool snap_starts_only = true;
};

struct PostProcessSettings {
    bool disable_track_stats_tags = false;
    bool disable_header_compression = true;
    bool apply_dialog_norm = false;
};

struct AppSettings {
    PathSettings paths;
    LoggingSettings logging;
    AnalysisSettings analysis;
    ChapterSettings chapters;
    PostProcessSettings postprocess;
};

struct AnalysisResult {
    int source_index = 0;
    double delay_ms = 0.0;
    double confidence = 0.0;
    bool success = false;
    QString error_message = "Bridge not available";
};

inline AppSettings loadSettings() {
    return AppSettings{};
}

inline bool saveSettings(const AppSettings&) {
    return false;
}

inline QString getConfigPath() {
    return "settings.toml";
}

inline QString version() {
    return "0.0.0 (no bridge)";
}

inline std::vector<AnalysisResult> runAnalysis(const QStringList&) {
    return {};
}

inline constexpr bool isAvailable() { return false; }

} // namespace VsgBridge

#endif
