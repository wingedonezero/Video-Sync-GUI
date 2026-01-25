// Options Dialog Logic Implementation

#include "logic.hpp"
#include "ui.hpp"
#include "vsg_bridge.hpp"

OptionsLogic::OptionsLogic(OptionsDialog* dialog)
    : QObject(dialog)
    , m_dialog(dialog)
{
}

void OptionsLogic::loadSettings()
{
    if (!VsgBridge::isAvailable()) {
        loadDefaults();
        return;
    }

    auto settings = VsgBridge::loadSettings();

    // Storage tab
    auto* storage = m_dialog->storageTab();
#ifdef VSG_HAS_BRIDGE
    storage->outputFolder()->setText(QString::fromStdString(std::string(settings.paths.output_folder)));
    storage->tempRoot()->setText(QString::fromStdString(std::string(settings.paths.temp_root)));
    storage->logsFolder()->setText(QString::fromStdString(std::string(settings.paths.logs_folder)));
#else
    storage->outputFolder()->setText(settings.paths.output_folder);
    storage->tempRoot()->setText(settings.paths.temp_root);
    storage->logsFolder()->setText(settings.paths.logs_folder);
#endif

    // Analysis tab
    auto* analysis = m_dialog->analysisTab();
#ifdef VSG_HAS_BRIDGE
    QString mode = QString::fromStdString(std::string(settings.analysis.mode));
    QString corrMethod = QString::fromStdString(std::string(settings.analysis.correlation_method));
    QString syncMode = QString::fromStdString(std::string(settings.analysis.sync_mode));
#else
    QString mode = settings.analysis.mode;
    QString corrMethod = settings.analysis.correlation_method;
    QString syncMode = settings.analysis.sync_mode;
#endif
    analysis->analysisMode()->setCurrentIndex(mode == "video" ? 1 : 0);
    analysis->correlationMethod()->setCurrentIndex(corrMethod == "gcc_phat" ? 1 : 0);
    analysis->syncMode()->setCurrentIndex(syncMode == "allow_negative" ? 1 : 0);
    analysis->chunkCount()->setValue(settings.analysis.chunk_count);
    analysis->chunkDuration()->setValue(settings.analysis.chunk_duration);
    analysis->minMatchPct()->setValue(settings.analysis.min_match_pct);
    analysis->scanStartPct()->setValue(settings.analysis.scan_start_pct);
    analysis->scanEndPct()->setValue(settings.analysis.scan_end_pct);
    analysis->useSoxr()->setChecked(settings.analysis.use_soxr);
    analysis->audioPeakFit()->setChecked(settings.analysis.audio_peak_fit);

    // Chapters tab
    auto* chapters = m_dialog->chaptersTab();
#ifdef VSG_HAS_BRIDGE
    QString snapMode = QString::fromStdString(std::string(settings.chapters.snap_mode));
#else
    QString snapMode = settings.chapters.snap_mode;
#endif
    chapters->rename()->setChecked(settings.chapters.rename);
    chapters->snapEnabled()->setChecked(settings.chapters.snap_enabled);
    chapters->snapMode()->setCurrentIndex(snapMode == "nearest" ? 1 : 0);
    chapters->snapThresholdMs()->setValue(settings.chapters.snap_threshold_ms);
    chapters->snapStartsOnly()->setChecked(settings.chapters.snap_starts_only);

    // Merge behavior tab
    auto* merge = m_dialog->mergeBehaviorTab();
    merge->disableTrackStatsTags()->setChecked(settings.postprocess.disable_track_stats_tags);
    merge->disableHeaderCompression()->setChecked(settings.postprocess.disable_header_compression);
    merge->applyDialogNorm()->setChecked(settings.postprocess.apply_dialog_norm);

    // Logging tab
    auto* logging = m_dialog->loggingTab();
    logging->compact()->setChecked(settings.logging.compact);
    logging->autoscroll()->setChecked(settings.logging.autoscroll);
    logging->errorTail()->setValue(settings.logging.error_tail);
    logging->progressStep()->setValue(settings.logging.progress_step);
    logging->showOptionsPretty()->setChecked(settings.logging.show_options_pretty);
    logging->showOptionsJson()->setChecked(settings.logging.show_options_json);
    logging->archiveLogs()->setChecked(settings.logging.archive_logs);
}

void OptionsLogic::saveSettings()
{
    if (!VsgBridge::isAvailable()) {
        return;
    }

    auto settings = VsgBridge::loadSettings();

    // Storage tab
    auto* storage = m_dialog->storageTab();
#ifdef VSG_HAS_BRIDGE
    settings.paths.output_folder = rust::String(storage->outputFolder()->text().toStdString());
    settings.paths.temp_root = rust::String(storage->tempRoot()->text().toStdString());
    settings.paths.logs_folder = rust::String(storage->logsFolder()->text().toStdString());
#else
    settings.paths.output_folder = storage->outputFolder()->text();
    settings.paths.temp_root = storage->tempRoot()->text();
    settings.paths.logs_folder = storage->logsFolder()->text();
#endif

    // Analysis tab
    auto* analysis = m_dialog->analysisTab();
#ifdef VSG_HAS_BRIDGE
    settings.analysis.mode = rust::String(analysis->analysisMode()->currentIndex() == 1 ? "video" : "audio");
    settings.analysis.correlation_method = rust::String(analysis->correlationMethod()->currentIndex() == 1 ? "gcc_phat" : "scc");
    settings.analysis.sync_mode = rust::String(analysis->syncMode()->currentIndex() == 1 ? "allow_negative" : "positive_only");
    settings.analysis.chunk_count = analysis->chunkCount()->value();
    settings.analysis.chunk_duration = analysis->chunkDuration()->value();
#else
    settings.analysis.mode = analysis->analysisMode()->currentIndex() == 1 ? "video" : "audio";
    settings.analysis.correlation_method = analysis->correlationMethod()->currentIndex() == 1 ? "gcc_phat" : "scc";
    settings.analysis.sync_mode = analysis->syncMode()->currentIndex() == 1 ? "allow_negative" : "positive_only";
    settings.analysis.chunk_count = analysis->chunkCount()->value();
    settings.analysis.chunk_duration = analysis->chunkDuration()->value();
#endif
    settings.analysis.min_match_pct = analysis->minMatchPct()->value();
    settings.analysis.scan_start_pct = analysis->scanStartPct()->value();
    settings.analysis.scan_end_pct = analysis->scanEndPct()->value();
    settings.analysis.use_soxr = analysis->useSoxr()->isChecked();
    settings.analysis.audio_peak_fit = analysis->audioPeakFit()->isChecked();

    // Chapters tab
    auto* chapters = m_dialog->chaptersTab();
    settings.chapters.rename = chapters->rename()->isChecked();
    settings.chapters.snap_enabled = chapters->snapEnabled()->isChecked();
#ifdef VSG_HAS_BRIDGE
    settings.chapters.snap_mode = rust::String(chapters->snapMode()->currentIndex() == 1 ? "nearest" : "previous");
    settings.chapters.snap_threshold_ms = chapters->snapThresholdMs()->value();
#else
    settings.chapters.snap_mode = chapters->snapMode()->currentIndex() == 1 ? "nearest" : "previous";
    settings.chapters.snap_threshold_ms = chapters->snapThresholdMs()->value();
#endif
    settings.chapters.snap_starts_only = chapters->snapStartsOnly()->isChecked();

    // Merge behavior tab
    auto* merge = m_dialog->mergeBehaviorTab();
    settings.postprocess.disable_track_stats_tags = merge->disableTrackStatsTags()->isChecked();
    settings.postprocess.disable_header_compression = merge->disableHeaderCompression()->isChecked();
    settings.postprocess.apply_dialog_norm = merge->applyDialogNorm()->isChecked();

    // Logging tab
    auto* logging = m_dialog->loggingTab();
    settings.logging.compact = logging->compact()->isChecked();
    settings.logging.autoscroll = logging->autoscroll()->isChecked();
    settings.logging.error_tail = logging->errorTail()->value();
    settings.logging.progress_step = logging->progressStep()->value();
    settings.logging.show_options_pretty = logging->showOptionsPretty()->isChecked();
    settings.logging.show_options_json = logging->showOptionsJson()->isChecked();
    settings.logging.archive_logs = logging->archiveLogs()->isChecked();

    VsgBridge::saveSettings(settings);
}

void OptionsLogic::loadDefaults()
{
    // Set defaults when bridge not available
    auto* storage = m_dialog->storageTab();
    storage->outputFolder()->setText("sync_output");
    storage->tempRoot()->setText(".temp");
    storage->logsFolder()->setText(".logs");

    auto* analysis = m_dialog->analysisTab();
    analysis->analysisMode()->setCurrentIndex(0);       // audio
    analysis->correlationMethod()->setCurrentIndex(0);  // scc
    analysis->syncMode()->setCurrentIndex(0);           // positive_only
    analysis->chunkCount()->setValue(10);
    analysis->chunkDuration()->setValue(15);
    analysis->minMatchPct()->setValue(5.0);
    analysis->scanStartPct()->setValue(5.0);
    analysis->scanEndPct()->setValue(95.0);
    analysis->useSoxr()->setChecked(true);
    analysis->audioPeakFit()->setChecked(true);

    auto* chapters = m_dialog->chaptersTab();
    chapters->rename()->setChecked(false);
    chapters->snapEnabled()->setChecked(false);
    chapters->snapMode()->setCurrentIndex(0);           // previous
    chapters->snapThresholdMs()->setValue(250);
    chapters->snapStartsOnly()->setChecked(true);

    auto* merge = m_dialog->mergeBehaviorTab();
    merge->disableTrackStatsTags()->setChecked(false);
    merge->disableHeaderCompression()->setChecked(true);
    merge->applyDialogNorm()->setChecked(false);

    auto* logging = m_dialog->loggingTab();
    logging->compact()->setChecked(true);
    logging->autoscroll()->setChecked(true);
    logging->errorTail()->setValue(20);
    logging->progressStep()->setValue(20);
    logging->showOptionsPretty()->setChecked(false);
    logging->showOptionsJson()->setChecked(false);
    logging->archiveLogs()->setChecked(true);
}
