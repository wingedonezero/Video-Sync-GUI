#pragma once

// Main Window Controller
// Handles all logic - config, dialogs, analysis, callbacks

#include <QObject>
#include <QString>

class MainWindow;
class QLineEdit;

class MainController : public QObject
{
    Q_OBJECT

public:
    explicit MainController(MainWindow* view);
    ~MainController() override;

    /// Apply loaded config values to UI widgets
    void applyConfigToUi();

    /// Save current UI values to config
    void saveUiToConfig();

public slots:
    /// Open the settings/options dialog
    void openOptionsDialog();

    /// Open the job queue dialog
    void openJobQueue();

    /// Start analyze-only operation
    void startAnalyzeOnly();

    /// Browse for a file/directory path
    void browseForPath(QLineEdit* lineEdit, const QString& caption);

    /// Append a message to the log output
    void appendLog(const QString& message);

    /// Update progress bar value (0-100)
    void updateProgress(int percent);

    /// Update status label text
    void updateStatus(const QString& status);

    /// Update delay label for a source
    void updateDelayLabel(int sourceIndex, double delayMs);

    /// Clear delay labels
    void clearDelayLabels();

private:
    MainWindow* m_view;
};
