// Options Dialog UI Implementation

#include "ui.hpp"
#include "logic.hpp"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFormLayout>
#include <QGroupBox>
#include <QDialogButtonBox>
#include <QScrollArea>
#include <QPushButton>
#include <QFileDialog>
#include <QLabel>

// Helper to wrap a widget in a scroll area
static QScrollArea* wrapScroll(QWidget* widget)
{
    auto* sa = new QScrollArea();
    sa->setWidgetResizable(true);
    sa->setWidget(widget);
    return sa;
}

// =============================================================================
// OptionsDialog
// =============================================================================

OptionsDialog::OptionsDialog(QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle("Application Settings");
    setMinimumSize(800, 600);

    buildUi();

    m_logic = std::make_unique<OptionsLogic>(this);
    m_logic->loadSettings();
}

OptionsDialog::~OptionsDialog() = default;

void OptionsDialog::buildUi()
{
    auto* mainLayout = new QVBoxLayout(this);

    m_tabs = new QTabWidget();

    // Create tabs
    m_storageTab = new StorageTab();
    m_analysisTab = new AnalysisTab();
    m_chaptersTab = new ChaptersTab();
    m_mergeBehaviorTab = new MergeBehaviorTab();
    m_loggingTab = new LoggingTab();

    // Add tabs (wrapped in scroll areas)
    m_tabs->addTab(wrapScroll(m_storageTab), "Storage");
    m_tabs->addTab(wrapScroll(m_analysisTab), "Analysis");
    m_tabs->addTab(wrapScroll(m_chaptersTab), "Chapters");
    m_tabs->addTab(wrapScroll(m_mergeBehaviorTab), "Merge Behavior");
    m_tabs->addTab(wrapScroll(m_loggingTab), "Logging");

    mainLayout->addWidget(m_tabs);

    // Button box
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Save | QDialogButtonBox::Cancel);
    connect(buttons, &QDialogButtonBox::accepted, this, &OptionsDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    mainLayout->addWidget(buttons);
}

void OptionsDialog::accept()
{
    m_logic->saveSettings();
    QDialog::accept();
}

QWidget* OptionsDialog::getWidget(const QString& section, const QString& key)
{
    // This could be expanded to return widgets by name
    Q_UNUSED(section);
    Q_UNUSED(key);
    return nullptr;
}

// =============================================================================
// StorageTab
// =============================================================================

StorageTab::StorageTab(QWidget* parent)
    : QWidget(parent)
{
    auto* mainLayout = new QVBoxLayout(this);

    auto* pathsGroup = new QGroupBox("Paths");
    auto* form = new QFormLayout(pathsGroup);

    form->addRow("Output Directory:", createDirInput(m_outputFolder));
    m_outputFolder->setToolTip("Default directory for merged output files");

    form->addRow("Temporary Directory:", createDirInput(m_tempRoot));
    m_tempRoot->setToolTip("Root directory for temporary files during processing");

    form->addRow("Reports Directory:", createDirInput(m_logsFolder));
    m_logsFolder->setToolTip("Directory for batch report files");

    mainLayout->addWidget(pathsGroup);
    mainLayout->addStretch();
}

QWidget* StorageTab::createDirInput(QLineEdit*& lineEdit)
{
    auto* container = new QWidget();
    auto* layout = new QHBoxLayout(container);
    layout->setContentsMargins(0, 0, 0, 0);

    lineEdit = new QLineEdit();
    auto* browseBtn = new QPushButton("Browse...");

    layout->addWidget(lineEdit);
    layout->addWidget(browseBtn);

    connect(browseBtn, &QPushButton::clicked, this, [lineEdit]() {
        QString dir = QFileDialog::getExistingDirectory(
            nullptr, "Select Directory", lineEdit->text());
        if (!dir.isEmpty()) {
            lineEdit->setText(dir);
        }
    });

    return container;
}

// =============================================================================
// AnalysisTab
// =============================================================================

AnalysisTab::AnalysisTab(QWidget* parent)
    : QWidget(parent)
{
    auto* mainLayout = new QVBoxLayout(this);

    // Mode group
    auto* modeGroup = new QGroupBox("Analysis Mode");
    auto* modeForm = new QFormLayout(modeGroup);

    m_analysisMode = new QComboBox();
    m_analysisMode->addItem("Audio Correlation", "audio");
    m_analysisMode->addItem("Video Diff", "video");
    m_analysisMode->setToolTip("Method for detecting sync offset between sources");
    modeForm->addRow("Mode:", m_analysisMode);

    m_correlationMethod = new QComboBox();
    m_correlationMethod->addItem("SCC (Standard Cross-Correlation)", "scc");
    m_correlationMethod->addItem("GCC-PHAT", "gcc_phat");
    m_correlationMethod->addItem("GCC-SCOT", "gcc_scot");
    m_correlationMethod->addItem("Whitened", "whitened");
    m_correlationMethod->setToolTip("Correlation algorithm for audio analysis");
    modeForm->addRow("Correlation Method:", m_correlationMethod);

    m_syncMode = new QComboBox();
    m_syncMode->addItem("Positive Only (Recommended)", "positive_only");
    m_syncMode->addItem("Allow Negative Delays", "allow_negative");
    m_syncMode->setToolTip(
        "Positive Only: Shifts all tracks to eliminate negative delays\n"
        "Allow Negative: Keeps delays as-is (may not work with some players)");
    modeForm->addRow("Sync Mode:", m_syncMode);

    mainLayout->addWidget(modeGroup);

    // Chunk settings group
    auto* chunkGroup = new QGroupBox("Chunk Settings");
    auto* chunkForm = new QFormLayout(chunkGroup);

    m_chunkCount = new QSpinBox();
    m_chunkCount->setRange(1, 50);
    m_chunkCount->setToolTip("Number of chunks to analyze");
    chunkForm->addRow("Chunk Count:", m_chunkCount);

    m_chunkDuration = new QSpinBox();
    m_chunkDuration->setRange(5, 60);
    m_chunkDuration->setSuffix(" sec");
    m_chunkDuration->setToolTip("Duration of each analysis chunk");
    chunkForm->addRow("Chunk Duration:", m_chunkDuration);

    m_minMatchPct = new QDoubleSpinBox();
    m_minMatchPct->setRange(1.0, 50.0);
    m_minMatchPct->setSuffix(" %");
    m_minMatchPct->setToolTip("Minimum correlation match percentage to accept a chunk");
    chunkForm->addRow("Min Match %:", m_minMatchPct);

    mainLayout->addWidget(chunkGroup);

    // Scan range group
    auto* rangeGroup = new QGroupBox("Scan Range");
    auto* rangeForm = new QFormLayout(rangeGroup);

    m_scanStartPct = new QDoubleSpinBox();
    m_scanStartPct->setRange(0.0, 50.0);
    m_scanStartPct->setSuffix(" %");
    m_scanStartPct->setToolTip("Start scanning at this percentage of file duration");
    rangeForm->addRow("Start:", m_scanStartPct);

    m_scanEndPct = new QDoubleSpinBox();
    m_scanEndPct->setRange(50.0, 100.0);
    m_scanEndPct->setSuffix(" %");
    m_scanEndPct->setToolTip("Stop scanning at this percentage of file duration");
    rangeForm->addRow("End:", m_scanEndPct);

    mainLayout->addWidget(rangeGroup);

    // Advanced options group
    auto* advancedGroup = new QGroupBox("Advanced Options");
    auto* advancedForm = new QFormLayout(advancedGroup);

    m_useSoxr = new QCheckBox("Use SoXR high-quality resampling");
    m_useSoxr->setToolTip("Use SoXR resampling via FFmpeg for better quality");
    advancedForm->addRow(m_useSoxr);

    m_audioPeakFit = new QCheckBox("Use quadratic peak fitting");
    m_audioPeakFit->setToolTip("Sub-sample accuracy using quadratic interpolation");
    advancedForm->addRow(m_audioPeakFit);

    mainLayout->addWidget(advancedGroup);
    mainLayout->addStretch();
}

// =============================================================================
// ChaptersTab
// =============================================================================

ChaptersTab::ChaptersTab(QWidget* parent)
    : QWidget(parent)
{
    auto* mainLayout = new QVBoxLayout(this);

    auto* group = new QGroupBox("Chapter Settings");
    auto* form = new QFormLayout(group);

    m_rename = new QCheckBox("Rename chapters");
    m_rename->setToolTip("Rename chapters to a standard format");
    form->addRow(m_rename);

    m_snapEnabled = new QCheckBox("Snap chapters to keyframes");
    m_snapEnabled->setToolTip("Adjust chapter timestamps to align with nearby keyframes");
    form->addRow(m_snapEnabled);

    m_snapMode = new QComboBox();
    m_snapMode->addItem("Previous Keyframe", "previous");
    m_snapMode->addItem("Nearest Keyframe", "nearest");
    m_snapMode->setToolTip("How to select keyframe when snapping");
    form->addRow("Snap Mode:", m_snapMode);

    m_snapThresholdMs = new QSpinBox();
    m_snapThresholdMs->setRange(0, 5000);
    m_snapThresholdMs->setSuffix(" ms");
    m_snapThresholdMs->setToolTip("Maximum distance to search for keyframe");
    form->addRow("Snap Threshold:", m_snapThresholdMs);

    m_snapStartsOnly = new QCheckBox("Only snap chapter starts");
    m_snapStartsOnly->setToolTip("Only snap the start of chapters, not ends");
    form->addRow(m_snapStartsOnly);

    mainLayout->addWidget(group);
    mainLayout->addStretch();
}

// =============================================================================
// MergeBehaviorTab
// =============================================================================

MergeBehaviorTab::MergeBehaviorTab(QWidget* parent)
    : QWidget(parent)
{
    auto* mainLayout = new QVBoxLayout(this);

    auto* group = new QGroupBox("mkvmerge Options");
    auto* form = new QFormLayout(group);

    m_disableTrackStatsTags = new QCheckBox("Disable track statistics tags");
    m_disableTrackStatsTags->setToolTip(
        "Don't write track statistics tags. Faster merge but less metadata.");
    form->addRow(m_disableTrackStatsTags);

    m_disableHeaderCompression = new QCheckBox("Disable header compression");
    m_disableHeaderCompression->setToolTip(
        "Disable header compression for better compatibility");
    form->addRow(m_disableHeaderCompression);

    m_applyDialogNorm = new QCheckBox("Apply dialog normalization gain");
    m_applyDialogNorm->setToolTip(
        "Apply dialog normalization metadata as actual gain adjustment");
    form->addRow(m_applyDialogNorm);

    mainLayout->addWidget(group);
    mainLayout->addStretch();
}

// =============================================================================
// LoggingTab
// =============================================================================

LoggingTab::LoggingTab(QWidget* parent)
    : QWidget(parent)
{
    auto* mainLayout = new QVBoxLayout(this);

    auto* group = new QGroupBox("Logging Options");
    auto* form = new QFormLayout(group);

    m_compact = new QCheckBox("Use compact log format");
    m_compact->setToolTip("Use shorter log messages");
    form->addRow(m_compact);

    m_autoscroll = new QCheckBox("Auto-scroll log output");
    m_autoscroll->setToolTip("Automatically scroll to newest log entries");
    form->addRow(m_autoscroll);

    m_errorTail = new QSpinBox();
    m_errorTail->setRange(5, 100);
    m_errorTail->setToolTip("Number of error lines to show at end of log");
    form->addRow("Error Tail Lines:", m_errorTail);

    m_progressStep = new QSpinBox();
    m_progressStep->setRange(1, 50);
    m_progressStep->setSuffix(" %");
    m_progressStep->setToolTip("Progress update step percentage");
    form->addRow("Progress Step:", m_progressStep);

    m_showOptionsPretty = new QCheckBox("Show mkvmerge options (pretty)");
    m_showOptionsPretty->setToolTip("Log mkvmerge options in readable format");
    form->addRow(m_showOptionsPretty);

    m_showOptionsJson = new QCheckBox("Show mkvmerge options (JSON)");
    m_showOptionsJson->setToolTip("Log mkvmerge options as raw JSON");
    form->addRow(m_showOptionsJson);

    m_archiveLogs = new QCheckBox("Archive logs on batch completion");
    m_archiveLogs->setToolTip("Create zip archive of logs after batch completes");
    form->addRow(m_archiveLogs);

    mainLayout->addWidget(group);
    mainLayout->addStretch();
}
