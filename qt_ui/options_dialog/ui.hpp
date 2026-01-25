#pragma once

// Options Dialog UI
// Tabbed settings dialog matching PySide structure

#include <QDialog>
#include <QTabWidget>
#include <QLineEdit>
#include <QCheckBox>
#include <QComboBox>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <map>
#include <memory>

class QWidget;
class OptionsLogic;

// Forward declare tab classes
class StorageTab;
class AnalysisTab;
class ChaptersTab;
class MergeBehaviorTab;
class LoggingTab;

class OptionsDialog : public QDialog
{
    Q_OBJECT

public:
    explicit OptionsDialog(QWidget* parent = nullptr);
    ~OptionsDialog() override;

    // Access to all widgets by section/key for logic layer
    QWidget* getWidget(const QString& section, const QString& key);

    // Tab accessors for logic
    StorageTab* storageTab() { return m_storageTab; }
    AnalysisTab* analysisTab() { return m_analysisTab; }
    ChaptersTab* chaptersTab() { return m_chaptersTab; }
    MergeBehaviorTab* mergeBehaviorTab() { return m_mergeBehaviorTab; }
    LoggingTab* loggingTab() { return m_loggingTab; }

public slots:
    void accept() override;

private:
    void buildUi();

    QTabWidget* m_tabs;

    // Tab instances
    StorageTab* m_storageTab;
    AnalysisTab* m_analysisTab;
    ChaptersTab* m_chaptersTab;
    MergeBehaviorTab* m_mergeBehaviorTab;
    LoggingTab* m_loggingTab;

    // Logic handler
    std::unique_ptr<OptionsLogic> m_logic;
};

// =============================================================================
// Tab Widgets
// =============================================================================

/// Storage paths tab
class StorageTab : public QWidget
{
    Q_OBJECT
public:
    explicit StorageTab(QWidget* parent = nullptr);

    QLineEdit* outputFolder() { return m_outputFolder; }
    QLineEdit* tempRoot() { return m_tempRoot; }
    QLineEdit* logsFolder() { return m_logsFolder; }

private:
    QWidget* createDirInput(QLineEdit*& lineEdit);

    QLineEdit* m_outputFolder;
    QLineEdit* m_tempRoot;
    QLineEdit* m_logsFolder;
};

/// Analysis settings tab
class AnalysisTab : public QWidget
{
    Q_OBJECT
public:
    explicit AnalysisTab(QWidget* parent = nullptr);

    QComboBox* analysisMode() { return m_analysisMode; }
    QComboBox* correlationMethod() { return m_correlationMethod; }
    QComboBox* syncMode() { return m_syncMode; }
    QSpinBox* chunkCount() { return m_chunkCount; }
    QSpinBox* chunkDuration() { return m_chunkDuration; }
    QDoubleSpinBox* minMatchPct() { return m_minMatchPct; }
    QDoubleSpinBox* scanStartPct() { return m_scanStartPct; }
    QDoubleSpinBox* scanEndPct() { return m_scanEndPct; }
    QCheckBox* useSoxr() { return m_useSoxr; }
    QCheckBox* audioPeakFit() { return m_audioPeakFit; }

private:
    QComboBox* m_analysisMode;
    QComboBox* m_correlationMethod;
    QComboBox* m_syncMode;
    QSpinBox* m_chunkCount;
    QSpinBox* m_chunkDuration;
    QDoubleSpinBox* m_minMatchPct;
    QDoubleSpinBox* m_scanStartPct;
    QDoubleSpinBox* m_scanEndPct;
    QCheckBox* m_useSoxr;
    QCheckBox* m_audioPeakFit;
};

/// Chapter settings tab
class ChaptersTab : public QWidget
{
    Q_OBJECT
public:
    explicit ChaptersTab(QWidget* parent = nullptr);

    QCheckBox* rename() { return m_rename; }
    QCheckBox* snapEnabled() { return m_snapEnabled; }
    QComboBox* snapMode() { return m_snapMode; }
    QSpinBox* snapThresholdMs() { return m_snapThresholdMs; }
    QCheckBox* snapStartsOnly() { return m_snapStartsOnly; }

private:
    QCheckBox* m_rename;
    QCheckBox* m_snapEnabled;
    QComboBox* m_snapMode;
    QSpinBox* m_snapThresholdMs;
    QCheckBox* m_snapStartsOnly;
};

/// Merge behavior tab
class MergeBehaviorTab : public QWidget
{
    Q_OBJECT
public:
    explicit MergeBehaviorTab(QWidget* parent = nullptr);

    QCheckBox* disableTrackStatsTags() { return m_disableTrackStatsTags; }
    QCheckBox* disableHeaderCompression() { return m_disableHeaderCompression; }
    QCheckBox* applyDialogNorm() { return m_applyDialogNorm; }

private:
    QCheckBox* m_disableTrackStatsTags;
    QCheckBox* m_disableHeaderCompression;
    QCheckBox* m_applyDialogNorm;
};

/// Logging settings tab
class LoggingTab : public QWidget
{
    Q_OBJECT
public:
    explicit LoggingTab(QWidget* parent = nullptr);

    QCheckBox* compact() { return m_compact; }
    QCheckBox* autoscroll() { return m_autoscroll; }
    QSpinBox* errorTail() { return m_errorTail; }
    QSpinBox* progressStep() { return m_progressStep; }
    QCheckBox* showOptionsPretty() { return m_showOptionsPretty; }
    QCheckBox* showOptionsJson() { return m_showOptionsJson; }
    QCheckBox* archiveLogs() { return m_archiveLogs; }

private:
    QCheckBox* m_compact;
    QCheckBox* m_autoscroll;
    QSpinBox* m_errorTail;
    QSpinBox* m_progressStep;
    QCheckBox* m_showOptionsPretty;
    QCheckBox* m_showOptionsJson;
    QCheckBox* m_archiveLogs;
};
