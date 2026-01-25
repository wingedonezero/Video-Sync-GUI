#pragma once

// VSG Bridge - C++ wrapper for Rust vsg_core via CXX
// This header provides a clean interface to the Rust bridge functions

#ifdef VSG_HAS_BRIDGE
// Include the CXX-generated header when bridge is available
#include "lib.rs.h"
#include <QString>
#include <QStringList>
#include <vector>

namespace VsgBridge {

/// Initialize the bridge - call once at app startup
/// Returns true on success
inline bool init(const QString& logsDir = ".logs") {
    return vsg::bridge_init(rust::String(logsDir.toStdString()));
}

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

/// Discover jobs from source paths (files or directories)
inline std::vector<vsg::DiscoveredJob> discoverJobs(const QStringList& paths) {
    rust::Vec<rust::String> rustPaths;
    for (const auto& path : paths) {
        rustPaths.push_back(rust::String(path.toStdString()));
    }

    auto jobs = vsg::bridge_discover_jobs(
        rust::Slice<const rust::String>(rustPaths.data(), rustPaths.size())
    );

    std::vector<vsg::DiscoveredJob> out;
    for (const auto& j : jobs) {
        out.push_back(j);
    }
    return out;
}

/// Scan a media file for tracks and attachments
inline vsg::MediaFileInfo scanFile(const QString& path) {
    return vsg::bridge_scan_file(rust::String(path.toStdString()));
}

/// Poll for next log message - returns empty string if no message
inline QString pollLog() {
    auto msg = vsg::bridge_poll_log();
    if (msg.has_message) {
        return QString::fromStdString(std::string(msg.message));
    }
    return QString();
}

/// Get current progress (percent, status message)
inline std::pair<int, QString> getProgress() {
    auto prog = vsg::bridge_get_progress();
    return {prog.percent, QString::fromStdString(std::string(prog.status))};
}

/// Push a log message
inline void log(const QString& message) {
    vsg::bridge_log(rust::String(message.toStdString()));
}

/// Clear all pending log messages
inline void clearLogs() {
    vsg::bridge_clear_logs();
}

/// Job result from running a job
struct JobResultQt {
    bool success;
    QString output_path;
    QStringList steps_completed;
    QStringList steps_skipped;
    QString error_message;
};

/// Run a full job (extract + analyze + mux)
/// @param jobId Unique job identifier
/// @param jobName Human-readable job name
/// @param sourcePaths Source file paths (index 0 = Source 1, etc.)
/// @param layoutJson Track layout as JSON string (empty = auto)
inline JobResultQt runJob(const QString& jobId, const QString& jobName,
                          const QStringList& sourcePaths, const QString& layoutJson = QString()) {
    vsg::JobInput input;
    input.job_id = rust::String(jobId.toStdString());
    input.job_name = rust::String(jobName.toStdString());

    // Build source paths
    rust::Vec<rust::String> rustPaths;
    for (const auto& path : sourcePaths) {
        rustPaths.push_back(rust::String(path.toStdString()));
    }
    input.source_paths = std::move(rustPaths);

    // Set layout JSON
    input.layout_json = rust::String(layoutJson.toStdString());

    // Run job via bridge
    auto result = vsg::bridge_run_job(input);

    // Convert to Qt result
    JobResultQt out;
    out.success = result.success;
    out.output_path = QString::fromStdString(std::string(result.output_path));
    out.error_message = QString::fromStdString(std::string(result.error_message));

    for (const auto& step : result.steps_completed) {
        out.steps_completed << QString::fromStdString(std::string(step));
    }
    for (const auto& step : result.steps_skipped) {
        out.steps_skipped << QString::fromStdString(std::string(step));
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
#include <utility>

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

struct DiscoveredJob {
    QString name;
    QStringList source_paths;
};

struct TrackInfo {
    int id = 0;
    QString track_type;
    QString codec_id;
    QString language = "und";
    QString name;
    bool is_default = false;
    bool is_forced = false;
    int channels = 0;
    int sample_rate = 0;
    int width = 0;
    int height = 0;
};

struct AttachmentInfo {
    int id = 0;
    QString file_name;
    QString mime_type;
    qint64 size = 0;
};

struct MediaFileInfo {
    QString path;
    std::vector<TrackInfo> tracks;
    std::vector<AttachmentInfo> attachments;
    qint64 duration_ms = 0;
    bool success = false;
    QString error_message = "Bridge not available";
};

inline bool init(const QString& = ".logs") {
    return false;
}

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

inline std::vector<DiscoveredJob> discoverJobs(const QStringList& paths) {
    // Stub: return empty - caller will use fallback
    (void)paths;
    return {};
}

inline MediaFileInfo scanFile(const QString& path) {
    // Stub: return error
    MediaFileInfo info;
    info.path = path;
    info.error_message = "Bridge not available";
    return info;
}

inline QString pollLog() {
    return QString();
}

inline std::pair<int, QString> getProgress() {
    return {0, QString()};
}

inline void log(const QString&) {}

inline void clearLogs() {}

/// Job result stub
struct JobResultQt {
    bool success = false;
    QString output_path;
    QStringList steps_completed;
    QStringList steps_skipped;
    QString error_message = "Bridge not available";
};

/// Run job stub
inline JobResultQt runJob(const QString&, const QString&,
                          const QStringList&, const QString& = QString()) {
    return JobResultQt{};
}

inline constexpr bool isAvailable() { return false; }

} // namespace VsgBridge

#endif
