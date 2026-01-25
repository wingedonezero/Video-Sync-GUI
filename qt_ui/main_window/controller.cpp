// Main Window Controller Implementation

#include "controller.hpp"
#include "window.hpp"
#include "../options_dialog/ui.hpp"
#include "../job_queue_dialog/ui.hpp"
#include "../add_job_dialog/ui.hpp"
#include "vsg_bridge.hpp"

#include <QFileDialog>
#include <QFileInfo>
#include <QMessageBox>
#include <QScrollBar>
#include <QTimer>
#include <QApplication>

MainController::MainController(MainWindow* view)
    : QObject(view)
    , m_view(view)
    , m_logPollTimer(new QTimer(this))
{
    // Set up log polling timer
    connect(m_logPollTimer, &QTimer::timeout, this, &MainController::pollLogs);
    m_logPollTimer->start(50); // Poll every 50ms
}

MainController::~MainController() = default;

void MainController::pollLogs()
{
    // Poll for log messages from bridge
    if (VsgBridge::isAvailable()) {
        QString msg = VsgBridge::pollLog();
        while (!msg.isEmpty()) {
            appendLog(msg);
            msg = VsgBridge::pollLog();
        }

        // Update progress
        auto [percent, status] = VsgBridge::getProgress();
        if (!status.isEmpty()) {
            updateProgress(percent);
            updateStatus(status);
        }
    }
}

void MainController::applyConfigToUi()
{
    // Show version and bridge status
    appendLog(QString("Video Sync GUI v%1").arg(VsgBridge::version()));

    if (VsgBridge::isAvailable()) {
        appendLog(QString("Config: %1").arg(VsgBridge::getConfigPath()));

        // Load settings from config
        auto settings = VsgBridge::loadSettings();

#ifdef VSG_HAS_BRIDGE
        // Convert rust::String to QString
        QString source1 = QString::fromStdString(std::string(settings.paths.last_source1_path));
        QString source2 = QString::fromStdString(std::string(settings.paths.last_source2_path));
#else
        QString source1 = settings.paths.last_source1_path;
        QString source2 = settings.paths.last_source2_path;
#endif

        // Apply last used paths if available
        if (!source1.isEmpty()) {
            m_view->refInput()->setText(source1);
        }
        if (!source2.isEmpty()) {
            m_view->secInput()->setText(source2);
        }
    } else {
        appendLog("[WARNING] Rust bridge not available - running in standalone mode");
    }

    appendLog("Ready.");
}

void MainController::saveUiToConfig()
{
    if (!VsgBridge::isAvailable()) return;

    // Load current settings, update paths, save
    auto settings = VsgBridge::loadSettings();

#ifdef VSG_HAS_BRIDGE
    settings.paths.last_source1_path = rust::String(m_view->refInput()->text().toStdString());
    settings.paths.last_source2_path = rust::String(m_view->secInput()->text().toStdString());
#else
    settings.paths.last_source1_path = m_view->refInput()->text();
    settings.paths.last_source2_path = m_view->secInput()->text();
#endif

    VsgBridge::saveSettings(settings);
}

void MainController::openOptionsDialog()
{
    OptionsDialog dialog(m_view);
    if (dialog.exec() == QDialog::Accepted) {
        appendLog("Settings saved.");
    }
}

void MainController::openJobQueue()
{
    saveUiToConfig();

    // Pre-populate with current source paths if any
    JobQueueDialog dialog(m_view);

    // Add initial job from main window if sources are specified
    QString ref = m_view->refInput()->text().trimmed();
    QString sec = m_view->secInput()->text().trimmed();
    QString ter = m_view->terInput()->text().trimmed();

    if (!ref.isEmpty()) {
        JobData job;
        job.name = QFileInfo(ref).baseName();
        job.sources["Source 1"] = ref;
        if (!sec.isEmpty()) job.sources["Source 2"] = sec;
        if (!ter.isEmpty()) job.sources["Source 3"] = ter;
        job.status = "Needs Configuration";
        dialog.addJobs({job});
    }

    if (dialog.exec() == QDialog::Accepted) {
        auto jobs = dialog.getFinalJobs();
        appendLog(QString("Starting %1 job(s)...").arg(jobs.size()));
        // TODO: Process jobs via bridge
    }
}

void MainController::startAnalyzeOnly()
{
    // Get source paths from UI
    QString ref = m_view->refInput()->text().trimmed();
    QString sec = m_view->secInput()->text().trimmed();
    QString ter = m_view->terInput()->text().trimmed();

    // Validate inputs
    if (ref.isEmpty()) {
        QMessageBox::warning(m_view, "Missing Input",
            "Please specify at least Source 1 (Reference).");
        return;
    }

    if (sec.isEmpty() && ter.isEmpty()) {
        QMessageBox::warning(m_view, "Missing Input",
            "Please specify at least one additional source (Source 2 or 3).");
        return;
    }

    // Save paths to config
    saveUiToConfig();

    // Clear previous results
    clearDelayLabels();

    // Update status
    updateStatus("Analyzing...");
    updateProgress(0);

    // Build path list
    QStringList paths;
    paths << ref;
    if (!sec.isEmpty()) paths << sec;
    if (!ter.isEmpty()) paths << ter;

    if (VsgBridge::isAvailable()) {
        // Run analysis via bridge
        // Note: This is synchronous for now - consider threading for long operations
        auto results = VsgBridge::runAnalysis(paths);

        // Process results
        for (const auto& result : results) {
#ifdef VSG_HAS_BRIDGE
            if (result.success) {
                updateDelayLabel(result.source_index, result.delay_ms);
            }
#else
            if (result.success) {
                updateDelayLabel(result.source_index, result.delay_ms);
            }
#endif
        }

        // Poll any remaining log messages
        pollLogs();

        updateStatus("Ready");
        updateProgress(100);
    } else {
        appendLog("[ERROR] Bridge not available - cannot run analysis");
        updateStatus("Ready");
        updateProgress(100);
    }
}

void MainController::browseForPath(QLineEdit* lineEdit, const QString& caption)
{
    // Determine starting directory
    QString startDir;
    QString currentPath = lineEdit->text();
    if (!currentPath.isEmpty()) {
        QFileInfo fi(currentPath);
        startDir = fi.absolutePath();
    }

    // Open file dialog - allow selecting files or directories
    QFileDialog dialog(m_view, caption);
    dialog.setFileMode(QFileDialog::AnyFile);
    if (!startDir.isEmpty()) {
        dialog.setDirectory(startDir);
    }

    // Set filter for video files
    dialog.setNameFilter("Video Files (*.mkv *.mp4 *.avi *.m4v *.mov *.ts);;All Files (*)");

    if (dialog.exec() == QDialog::Accepted) {
        QStringList selected = dialog.selectedFiles();
        if (!selected.isEmpty()) {
            lineEdit->setText(selected.first());
        }
    }
}

void MainController::appendLog(const QString& message)
{
    m_view->logOutput()->append(message);

    // Auto-scroll to bottom
    QScrollBar* scrollBar = m_view->logOutput()->verticalScrollBar();
    scrollBar->setValue(scrollBar->maximum());
}

void MainController::updateProgress(int percent)
{
    m_view->progressBar()->setValue(percent);
}

void MainController::updateStatus(const QString& status)
{
    m_view->statusLabel()->setText(status);
}

void MainController::updateDelayLabel(int sourceIndex, double delayMs)
{
    // sourceIndex is 2, 3, or 4 - map to array index 0, 1, 2
    int arrayIndex = sourceIndex - 2;
    auto& labels = m_view->delayLabels();

    if (arrayIndex >= 0 && arrayIndex < static_cast<int>(labels.size())) {
        QString text;
        if (delayMs >= 0) {
            text = QString("+%1 ms").arg(delayMs, 0, 'f', 1);
        } else {
            text = QString("%1 ms").arg(delayMs, 0, 'f', 1);
        }
        labels[arrayIndex]->setText(text);
    }
}

void MainController::clearDelayLabels()
{
    for (auto* label : m_view->delayLabels()) {
        label->setText(QString::fromUtf8("\u2014")); // em-dash
    }
}
