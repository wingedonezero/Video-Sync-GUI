#pragma once

// Job Queue Dialog
// Displays and manages the queue of jobs to be processed

#include <QDialog>
#include <QTableWidget>
#include <QStringList>
#include <vector>
#include <map>
#include <memory>

#include "../track_widget/ui.hpp"  // For TrackData

class QPushButton;
class JobQueueLogic;

/// Job data structure
struct JobData {
    QString name;
    std::map<QString, QString> sources;     // "Source 1" -> path, etc.
    QString status;                         // "Needs Configuration", "Configured"
    std::vector<TrackData> trackLayout;     // Final track layout (from ManualSelection)
    QStringList attachmentSources;          // Sources to include attachments from
};

class JobQueueDialog : public QDialog
{
    Q_OBJECT

public:
    explicit JobQueueDialog(QWidget* parent = nullptr);
    ~JobQueueDialog() override;

    /// Get jobs that are ready to be processed (accepted dialog)
    std::vector<JobData> getFinalJobs() const;

    /// Access to table for logic layer
    QTableWidget* table() { return m_table; }

    /// Add jobs to the queue
    void addJobs(const std::vector<JobData>& jobs);

protected:
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dropEvent(QDropEvent* event) override;

public slots:
    void populateTable();

private slots:
    void onAddJobsClicked();
    void onRemoveSelectedClicked();
    void onMoveUpClicked();
    void onMoveDownClicked();
    void onTableDoubleClicked(int row, int column);
    void onContextMenuRequested(const QPoint& pos);

private:
    void buildUi();
    void connectSignals();
    void moveSelectedJobs(int direction);

    QTableWidget* m_table;
    QPushButton* m_addJobBtn;
    QPushButton* m_removeBtn;
    QPushButton* m_moveUpBtn;
    QPushButton* m_moveDownBtn;
    QPushButton* m_okButton;

    std::unique_ptr<JobQueueLogic> m_logic;
};
