#pragma once

// Job Queue Logic
// Handles job management, configuration, and processing

#include "ui.hpp"
#include <QObject>
#include <vector>
#include <optional>

class JobQueueDialog;

class JobQueueLogic : public QObject
{
    Q_OBJECT

public:
    explicit JobQueueLogic(JobQueueDialog* dialog);

    /// Add jobs to the queue
    void addJobs(const std::vector<JobData>& jobs);

    /// Populate the table with current jobs
    void populateTable();

    /// Remove selected jobs from queue
    void removeSelectedJobs();

    /// Move selected jobs up or down
    void moveJobs(const QList<int>& selectedRows, int direction);

    /// Open configuration dialog for a job
    void configureJobAtRow(int row);

    /// Get jobs ready for processing
    std::vector<JobData> getFinalJobs() const;

    /// Copy layout from a configured job
    void copyLayout(int row);

    /// Paste layout to selected jobs
    void pasteLayout();

    /// Check if clipboard has content
    bool hasClipboard() const { return m_layoutClipboard.has_value(); }

private:
    void updateRow(int row, const JobData& job);

    JobQueueDialog* m_dialog;
    std::vector<JobData> m_jobs;
    std::optional<JobData> m_layoutClipboard;
};
