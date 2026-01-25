// Job Queue Logic Implementation

#include "logic.hpp"

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

    // TODO: Open ManualSelectionDialog for this job
    QMessageBox::information(m_dialog, "Configure Job",
        QString("Configuration dialog for job %1 not yet implemented.\n"
                "This will open the Manual Selection Dialog.")
            .arg(row + 1));

    // For now, mark as configured
    m_jobs[row].status = "Configured";
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

    m_layoutClipboard = m_jobs[row];

    // TODO: Actually copy the track layout configuration
}

void JobQueueLogic::pasteLayout()
{
    if (!m_layoutClipboard.has_value()) return;

    QTableWidget* table = m_dialog->table();

    for (const auto& index : table->selectionModel()->selectedRows()) {
        int row = index.row();
        if (row >= 0 && row < static_cast<int>(m_jobs.size())) {
            // TODO: Actually paste the track layout configuration
            m_jobs[row].status = "Configured";
        }
    }

    populateTable();
}
