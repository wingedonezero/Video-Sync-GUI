// Job Queue Logic Implementation

#include "logic.hpp"
#include "../manual_selection_dialog/ui.hpp"
#include "../bridge/vsg_bridge.hpp"

#include <QTableWidgetItem>
#include <QHeaderView>
#include <QMessageBox>
#include <QFileInfo>
#include <algorithm>

JobQueueLogic::JobQueueLogic(JobQueueDialog* dialog)
    : QObject(dialog)
    , m_dialog(dialog)
{
}

void JobQueueLogic::addJobs(const std::vector<JobData>& jobs)
{
    for (const auto& job : jobs) {
        m_jobs.push_back(job);
    }

    // Sort by name (natural sort would be better, but simple for now)
    std::sort(m_jobs.begin(), m_jobs.end(), [](const JobData& a, const JobData& b) {
        return a.name.toLower() < b.name.toLower();
    });

    populateTable();
}

void JobQueueLogic::populateTable()
{
    QTableWidget* table = m_dialog->table();

    table->setRowCount(0);
    table->setColumnCount(3);
    table->setHorizontalHeaderLabels({"#", "Status", "Sources"});

    QHeaderView* header = table->horizontalHeader();
    header->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    header->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    header->setSectionResizeMode(2, QHeaderView::Stretch);

    table->setRowCount(static_cast<int>(m_jobs.size()));

    for (int row = 0; row < static_cast<int>(m_jobs.size()); ++row) {
        updateRow(row, m_jobs[row]);
    }
}

void JobQueueLogic::updateRow(int row, const JobData& job)
{
    QTableWidget* table = m_dialog->table();

    // Column 0: Row number
    auto* orderItem = new QTableWidgetItem(QString::number(row + 1));
    orderItem->setTextAlignment(Qt::AlignCenter);
    table->setItem(row, 0, orderItem);

    // Column 1: Status
    auto* statusItem = new QTableWidgetItem(job.status);
    table->setItem(row, 1, statusItem);

    // Column 2: Sources summary
    QString sourcesSummary;
    auto it = job.sources.find("Source 1");
    if (it != job.sources.end()) {
        QFileInfo fi(it->second);
        sourcesSummary = fi.fileName();

        // Add count of other sources
        int otherCount = static_cast<int>(job.sources.size()) - 1;
        if (otherCount > 0) {
            sourcesSummary += QString(" (+%1 source%2)")
                .arg(otherCount)
                .arg(otherCount > 1 ? "s" : "");
        }
    }
    auto* sourcesItem = new QTableWidgetItem(sourcesSummary);
    table->setItem(row, 2, sourcesItem);
}

void JobQueueLogic::removeSelectedJobs()
{
    QTableWidget* table = m_dialog->table();

    QList<int> selectedRows;
    for (const auto& index : table->selectionModel()->selectedRows()) {
        selectedRows.append(index.row());
    }

    if (selectedRows.isEmpty()) return;

    // Sort in reverse to remove from end first
    std::sort(selectedRows.begin(), selectedRows.end(), std::greater<int>());

    for (int row : selectedRows) {
        if (row >= 0 && row < static_cast<int>(m_jobs.size())) {
            m_jobs.erase(m_jobs.begin() + row);
        }
    }

    populateTable();
}

void JobQueueLogic::moveJobs(const QList<int>& selectedRows, int direction)
{
    if (selectedRows.isEmpty()) return;

    QList<int> sortedRows = selectedRows;
    std::sort(sortedRows.begin(), sortedRows.end());

    if (direction == -1) {
        // Move up
        if (sortedRows.first() <= 0) return;

        for (int row : sortedRows) {
            if (row > 0 && row < static_cast<int>(m_jobs.size())) {
                std::swap(m_jobs[row], m_jobs[row - 1]);
            }
        }
    } else {
        // Move down
        if (sortedRows.last() >= static_cast<int>(m_jobs.size()) - 1) return;

        // Process in reverse for moving down
        for (int i = sortedRows.size() - 1; i >= 0; --i) {
            int row = sortedRows[i];
            if (row >= 0 && row < static_cast<int>(m_jobs.size()) - 1) {
                std::swap(m_jobs[row], m_jobs[row + 1]);
            }
        }
    }

    populateTable();

    // Reselect moved rows
    QTableWidget* table = m_dialog->table();
    table->clearSelection();
    for (int row : sortedRows) {
        int newRow = row + direction;
        if (newRow >= 0 && newRow < table->rowCount()) {
            table->selectRow(newRow);
        }
    }
}

void JobQueueLogic::configureJobAtRow(int row)
{
    if (row < 0 || row >= static_cast<int>(m_jobs.size())) return;

    JobData& job = m_jobs[row];

    // Build track info map by scanning each source file via bridge
    std::map<QString, std::vector<SourceTrackInfo>> trackInfo;

    for (const auto& [sourceKey, path] : job.sources) {
        std::vector<SourceTrackInfo> tracks;

        if (VsgBridge::isAvailable()) {
            auto fileInfo = VsgBridge::scanFile(path);

            if (fileInfo.success) {
#ifdef VSG_HAS_BRIDGE
                for (const auto& t : fileInfo.tracks) {
                    SourceTrackInfo track;
                    track.id = t.id;
                    track.type = QString::fromStdString(std::string(t.track_type));
                    track.codecId = QString::fromStdString(std::string(t.codec_id));
                    track.language = QString::fromStdString(std::string(t.language));
                    track.name = QString::fromStdString(std::string(t.name));
                    track.isDefault = t.is_default;
                    track.isForced = t.is_forced;
                    track.originalPath = path;

                    // Build description
                    QString desc = QString("%1 Track %2 (%3)")
                        .arg(track.type)
                        .arg(track.id)
                        .arg(track.language);
                    if (!track.name.isEmpty()) {
                        desc += QString(" - %1").arg(track.name);
                    }
                    if (track.type == "audio" && t.channels > 0) {
                        desc += QString(" [%1ch]").arg(t.channels);
                    }
                    if (track.type == "video" && t.width > 0) {
                        desc += QString(" [%1x%2]").arg(t.width).arg(t.height);
                    }
                    track.description = desc;

                    tracks.push_back(track);
                }
#else
                // Stub mode - use placeholder tracks
                for (const auto& t : fileInfo.tracks) {
                    SourceTrackInfo track;
                    track.id = t.id;
                    track.type = t.track_type;
                    track.codecId = t.codec_id;
                    track.language = t.language;
                    track.name = t.name;
                    track.isDefault = t.is_default;
                    track.isForced = t.is_forced;
                    track.originalPath = path;
                    track.description = QString("%1 Track %2").arg(track.type).arg(track.id);
                    tracks.push_back(track);
                }
#endif
            } else {
                // Scan failed - add error placeholder
                VsgBridge::log(QString("[WARNING] Failed to scan %1: %2")
                    .arg(path)
#ifdef VSG_HAS_BRIDGE
                    .arg(QString::fromStdString(std::string(fileInfo.error_message)))
#else
                    .arg(fileInfo.error_message)
#endif
                );
            }
        }

        // Fallback: if no tracks found, add placeholders
        if (tracks.empty()) {
            SourceTrackInfo video;
            video.id = 0;
            video.type = "video";
            video.codecId = "V_MPEG4/ISO/AVC";
            video.language = "und";
            video.description = "Video track (scan unavailable)";
            video.originalPath = path;
            tracks.push_back(video);

            SourceTrackInfo audio;
            audio.id = 1;
            audio.type = "audio";
            audio.codecId = "A_AAC";
            audio.language = "eng";
            audio.name = "English";
            audio.description = "Audio track (scan unavailable)";
            audio.originalPath = path;
            tracks.push_back(audio);
        }

        trackInfo[sourceKey] = tracks;
    }

    ManualSelectionDialog dialog(trackInfo, m_dialog);
    if (dialog.exec() == QDialog::Accepted) {
        // Store the track layout in job
        job.trackLayout = dialog.getFinalLayout();
        job.attachmentSources = dialog.getAttachmentSources();
        job.status = "Configured";
    }

    populateTable();
}

std::vector<JobData> JobQueueLogic::getFinalJobs() const
{
    std::vector<JobData> finalJobs;
    for (const auto& job : m_jobs) {
        if (job.status == "Configured") {
            finalJobs.push_back(job);
        }
    }
    return finalJobs;
}

void JobQueueLogic::copyLayout(int row)
{
    if (row < 0 || row >= static_cast<int>(m_jobs.size())) return;

    const JobData& job = m_jobs[row];
    if (job.trackLayout.empty()) {
        // Nothing to copy if job isn't configured
        VsgBridge::log("[WARNING] Cannot copy layout from unconfigured job");
        return;
    }

    m_layoutClipboard = job;
    VsgBridge::log(QString("Copied layout from '%1' (%2 tracks)")
        .arg(job.name)
        .arg(job.trackLayout.size()));
}

void JobQueueLogic::pasteLayout()
{
    if (!m_layoutClipboard.has_value()) return;

    const JobData& source = m_layoutClipboard.value();
    if (source.trackLayout.empty()) return;

    QTableWidget* table = m_dialog->table();
    int pastedCount = 0;

    for (const auto& index : table->selectionModel()->selectedRows()) {
        int row = index.row();
        if (row >= 0 && row < static_cast<int>(m_jobs.size())) {
            // Copy the track layout and attachment sources
            m_jobs[row].trackLayout = source.trackLayout;
            m_jobs[row].attachmentSources = source.attachmentSources;
            m_jobs[row].status = "Configured";
            pastedCount++;
        }
    }

    if (pastedCount > 0) {
        VsgBridge::log(QString("Pasted layout to %1 job(s)").arg(pastedCount));
    }

    populateTable();
}
