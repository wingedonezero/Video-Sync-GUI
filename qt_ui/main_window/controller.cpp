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
#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QDateTime>

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
        if (jobs.empty()) {
            appendLog("No jobs to process.");
            return;
        }

        appendLog(QString("Starting %1 job(s)...").arg(jobs.size()));
        processJobs(jobs);
    }
}

void MainController::processJobs(const std::vector<JobData>& jobs)
{
    if (!VsgBridge::isAvailable()) {
        appendLog("[ERROR] Bridge not available - cannot process jobs");
        return;
    }

    int completedCount = 0;
    int failedCount = 0;
    QStringList workDirs;  // Track work directories for cleanup

    for (size_t i = 0; i < jobs.size(); ++i) {
        const auto& job = jobs[i];

        // Update status
        QString statusMsg = QString("Processing job %1/%2: %3")
            .arg(i + 1).arg(jobs.size()).arg(job.name);
        updateStatus(statusMsg);
        appendLog(QString("\n=== %1 ===").arg(statusMsg));

        // Build source paths list (ordered by source key)
        QStringList sourcePaths;
        bool hasSource1 = false;
        for (int j = 1; j <= 4; ++j) {
            QString key = QString("Source %1").arg(j);
            auto it = job.sources.find(key);
            if (it != job.sources.end()) {
                sourcePaths << it->second;
                if (j == 1) hasSource1 = true;
            } else if (j > 1) {
                break; // Stop at first missing source after Source 1
            }
        }

        if (!hasSource1) {
            // Source 1 is required
            appendLog("[ERROR] Job missing Source 1, skipping");
            failedCount++;
            continue;
        }

        // Generate job ID from timestamp and index
        QString jobId = QString("job_%1_%2").arg(QDateTime::currentMSecsSinceEpoch()).arg(i);

        // Track work directory for cleanup later
        auto settings = VsgBridge::loadSettings();
#ifdef VSG_HAS_BRIDGE
        QString tempRoot = QString::fromStdString(std::string(settings.paths.temp_root));
#else
        QString tempRoot = settings.paths.temp_root;
#endif
        QString workDir = QString("%1/%2").arg(tempRoot).arg(jobId);
        workDirs << workDir;

        // Convert track layout to JSON if available
        QString layoutJson;
        if (!job.trackLayout.empty()) {
            // Serialize layout to JSON
            QJsonArray tracksArray;
            for (const auto& track : job.trackLayout) {
                QJsonObject trackObj;
                trackObj["track_id"] = track.id;
                trackObj["source_key"] = track.sourceKey;

                // Convert track type enum to string
                QString typeStr = "video";
                if (track.type == TrackType::Audio) typeStr = "audio";
                else if (track.type == TrackType::Subtitle) typeStr = "subtitles";
                trackObj["track_type"] = typeStr;

                QJsonObject configObj;
                configObj["is_default"] = track.isDefault;
                configObj["is_forced"] = track.isForced;
                if (!track.name.isEmpty()) {
                    configObj["custom_name"] = track.name;
                }
                if (!track.language.isEmpty() && track.language != "und") {
                    configObj["custom_lang"] = track.language;
                }
                trackObj["config"] = configObj;

                tracksArray.append(trackObj);
            }

            QJsonObject layoutObj;
            layoutObj["final_tracks"] = tracksArray;

            QJsonArray attachmentSources;
            for (const auto& src : job.attachmentSources) {
                attachmentSources.append(src);
            }
            layoutObj["attachment_sources"] = attachmentSources;

            QJsonDocument doc(layoutObj);
            layoutJson = QString::fromUtf8(doc.toJson(QJsonDocument::Compact));
        }

        // Run the job
        auto result = VsgBridge::runJob(jobId, job.name, sourcePaths, layoutJson);

        // Poll remaining log messages
        pollLogs();

        if (result.success) {
            completedCount++;
            appendLog(QString("[SUCCESS] Output: %1").arg(result.output_path));
            appendLog(QString("Steps completed: %1").arg(result.steps_completed.join(", ")));
            if (!result.steps_skipped.isEmpty()) {
                appendLog(QString("Steps skipped: %1").arg(result.steps_skipped.join(", ")));
            }
        } else {
            failedCount++;
            appendLog(QString("[FAILED] %1").arg(result.error_message));
        }
    }

    // Final summary
    appendLog(QString("\n=== Processing Complete ==="));
    appendLog(QString("Completed: %1, Failed: %2").arg(completedCount).arg(failedCount));
    updateStatus("Ready");
    updateProgress(100);

    // Clean up temp work directories
    for (const QString& workDir : workDirs) {
        VsgBridge::cleanupTemp(workDir);
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
