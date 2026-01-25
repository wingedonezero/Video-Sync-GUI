// Options Dialog Logic Implementation

#include "logic.hpp"
#include "ui.hpp"

OptionsLogic::OptionsLogic(OptionsDialog* dialog)
    : QObject(dialog)
    , m_dialog(dialog)
{
}

void OptionsLogic::loadSettings()
{
    // TODO: Load from bridge
    // auto settings = vsg::bridge_load_settings();

    // For now, set defaults
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

void OptionsLogic::saveSettings()
{
    // TODO: Save to bridge
    // vsg::AppSettings settings;
    //
    // auto* storage = m_dialog->storageTab();
    // settings.paths.output_folder = storage->outputFolder()->text().toStdString();
    // settings.paths.temp_root = storage->tempRoot()->text().toStdString();
    // settings.paths.logs_folder = storage->logsFolder()->text().toStdString();
    //
    // ... etc ...
    //
    // vsg::bridge_save_settings(settings);
}
