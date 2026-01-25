// Job Queue Dialog Implementation

#include "ui.hpp"
#include "logic.hpp"
#include "../add_job_dialog/ui.hpp"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QHeaderView>
#include <QMenu>
#include <QShortcut>
#include <QKeySequence>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QMimeData>
#include <QUrl>
#include <QFileInfo>

JobQueueDialog::JobQueueDialog(QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle("Job Queue");
    setMinimumSize(1000, 500);
    setAcceptDrops(true);

    buildUi();
    connectSignals();

    m_logic = std::make_unique<JobQueueLogic>(this);
    populateTable();
}

JobQueueDialog::~JobQueueDialog() = default;

void JobQueueDialog::buildUi()
{
    auto* mainLayout = new QVBoxLayout(this);

    // Table
    m_table = new QTableWidget();
    m_table->setAcceptDrops(true);
    m_table->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->verticalHeader()->setVisible(false);
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->setContextMenuPolicy(Qt::CustomContextMenu);
    mainLayout->addWidget(m_table);

    // Button row
    auto* buttonLayout = new QHBoxLayout();

    m_addJobBtn = new QPushButton("Add Job(s)...");
    buttonLayout->addWidget(m_addJobBtn);

    buttonLayout->addStretch();

    m_moveUpBtn = new QPushButton("Move Up");
    buttonLayout->addWidget(m_moveUpBtn);

    m_moveDownBtn = new QPushButton("Move Down");
    buttonLayout->addWidget(m_moveDownBtn);

    m_removeBtn = new QPushButton("Remove Selected");
    buttonLayout->addWidget(m_removeBtn);

    mainLayout->addLayout(buttonLayout);

    // Dialog buttons
    auto* dialogBtns = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel);

    m_okButton = dialogBtns->button(QDialogButtonBox::Ok);
    m_okButton->setText("Start Processing Queue");

    connect(dialogBtns, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(dialogBtns, &QDialogButtonBox::rejected, this, &QDialog::reject);

    mainLayout->addWidget(dialogBtns);
}

void JobQueueDialog::connectSignals()
{
    connect(m_table, &QTableWidget::cellDoubleClicked,
            this, &JobQueueDialog::onTableDoubleClicked);
    connect(m_table, &QTableWidget::customContextMenuRequested,
            this, &JobQueueDialog::onContextMenuRequested);

    connect(m_addJobBtn, &QPushButton::clicked,
            this, &JobQueueDialog::onAddJobsClicked);
    connect(m_removeBtn, &QPushButton::clicked,
            this, &JobQueueDialog::onRemoveSelectedClicked);
    connect(m_moveUpBtn, &QPushButton::clicked,
            this, &JobQueueDialog::onMoveUpClicked);
    connect(m_moveDownBtn, &QPushButton::clicked,
            this, &JobQueueDialog::onMoveDownClicked);

    // Keyboard shortcuts
    auto* moveUpShortcut = new QShortcut(QKeySequence(Qt::CTRL | Qt::Key_Up), this);
    connect(moveUpShortcut, &QShortcut::activated, this, &JobQueueDialog::onMoveUpClicked);

    auto* moveDownShortcut = new QShortcut(QKeySequence(Qt::CTRL | Qt::Key_Down), this);
    connect(moveDownShortcut, &QShortcut::activated, this, &JobQueueDialog::onMoveDownClicked);
}

void JobQueueDialog::dragEnterEvent(QDragEnterEvent* event)
{
    if (event->mimeData()->hasUrls()) {
        event->acceptProposedAction();
    } else {
        event->ignore();
    }
}

void JobQueueDialog::dropEvent(QDropEvent* event)
{
    if (event->mimeData()->hasUrls()) {
        QStringList paths;
        for (const QUrl& url : event->mimeData()->urls()) {
            paths.append(url.toLocalFile());
        }

        AddJobDialog dialog(this);
        dialog.populateSourcesFromPaths(paths);
        if (dialog.exec() == QDialog::Accepted) {
            auto discovered = dialog.getDiscoveredJobs();
            std::vector<JobData> jobs;
            for (const auto& d : discovered) {
                JobData job;
                job.sources = d;
                job.status = "Needs Configuration";
                // Get name from Source 1
                auto it = d.find("Source 1");
                if (it != d.end()) {
                    QFileInfo fi(it->second);
                    job.name = fi.baseName();
                }
                jobs.push_back(job);
            }
            addJobs(jobs);
        }
        event->acceptProposedAction();
    } else {
        event->ignore();
    }
}

void JobQueueDialog::populateTable()
{
    m_logic->populateTable();
}

void JobQueueDialog::addJobs(const std::vector<JobData>& jobs)
{
    m_logic->addJobs(jobs);
}

std::vector<JobData> JobQueueDialog::getFinalJobs() const
{
    return m_logic->getFinalJobs();
}

void JobQueueDialog::onAddJobsClicked()
{
    AddJobDialog dialog(this);
    if (dialog.exec() == QDialog::Accepted) {
        auto discovered = dialog.getDiscoveredJobs();
        std::vector<JobData> jobs;
        for (const auto& d : discovered) {
            JobData job;
            job.sources = d;
            job.status = "Needs Configuration";
            auto it = d.find("Source 1");
            if (it != d.end()) {
                QFileInfo fi(it->second);
                job.name = fi.baseName();
            }
            jobs.push_back(job);
        }
        addJobs(jobs);
    }
}

void JobQueueDialog::onRemoveSelectedClicked()
{
    m_logic->removeSelectedJobs();
}

void JobQueueDialog::onMoveUpClicked()
{
    moveSelectedJobs(-1);
}

void JobQueueDialog::onMoveDownClicked()
{
    moveSelectedJobs(1);
}

void JobQueueDialog::moveSelectedJobs(int direction)
{
    QList<int> selectedRows;
    for (const auto& index : m_table->selectionModel()->selectedRows()) {
        selectedRows.append(index.row());
    }

    if (selectedRows.isEmpty()) return;

    std::sort(selectedRows.begin(), selectedRows.end());

    m_logic->moveJobs(selectedRows, direction);
}

void JobQueueDialog::onTableDoubleClicked(int row, int column)
{
    Q_UNUSED(column);
    m_logic->configureJobAtRow(row);
}

void JobQueueDialog::onContextMenuRequested(const QPoint& pos)
{
    QList<int> selectedRows;
    for (const auto& index : m_table->selectionModel()->selectedRows()) {
        selectedRows.append(index.row());
    }

    if (selectedRows.isEmpty()) return;

    QMenu menu;
    QAction* configAction = menu.addAction("Configure...");
    QAction* removeAction = menu.addAction("Remove from Queue");
    menu.addSeparator();
    QAction* copyAction = menu.addAction("Copy Layout");
    QAction* pasteAction = menu.addAction("Paste Layout");

    configAction->setEnabled(selectedRows.size() == 1);
    copyAction->setEnabled(selectedRows.size() == 1);
    pasteAction->setEnabled(m_logic->hasClipboard());

    QAction* action = menu.exec(m_table->viewport()->mapToGlobal(pos));

    if (action == configAction) {
        m_logic->configureJobAtRow(selectedRows.first());
    } else if (action == removeAction) {
        m_logic->removeSelectedJobs();
    } else if (action == copyAction) {
        m_logic->copyLayout(selectedRows.first());
    } else if (action == pasteAction) {
        m_logic->pasteLayout();
    }
}
