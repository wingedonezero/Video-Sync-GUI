// Add Job Dialog Implementation

#include "ui.hpp"

#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QScrollArea>
#include <QFileDialog>
#include <QMessageBox>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QMimeData>
#include <QUrl>

// =============================================================================
// SourceInputWidget
// =============================================================================

SourceInputWidget::SourceInputWidget(int sourceNum, QWidget* parent)
    : QWidget(parent)
{
    setAcceptDrops(true);

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);

    QString labelText = (sourceNum == 1)
        ? QString("Source %1 (Reference):").arg(sourceNum)
        : QString("Source %1:").arg(sourceNum);

    auto* label = new QLabel(labelText);
    label->setMinimumWidth(120);

    m_lineEdit = new QLineEdit();

    auto* browseBtn = new QPushButton("Browse...");
    connect(browseBtn, &QPushButton::clicked, this, &SourceInputWidget::browseForPath);

    layout->addWidget(label, 1);
    layout->addWidget(m_lineEdit, 4);
    layout->addWidget(browseBtn);
}

void SourceInputWidget::dragEnterEvent(QDragEnterEvent* event)
{
    if (event->mimeData()->hasUrls()) {
        event->acceptProposedAction();
    } else {
        event->ignore();
    }
}

void SourceInputWidget::dropEvent(QDropEvent* event)
{
    if (event->mimeData()->hasUrls()) {
        QList<QUrl> urls = event->mimeData()->urls();
        if (!urls.isEmpty()) {
            m_lineEdit->setText(urls.first().toLocalFile());
        }
        event->acceptProposedAction();
    } else {
        event->ignore();
    }
}

void SourceInputWidget::browseForPath()
{
    QFileDialog dialog(this, "Select Source");
    dialog.setFileMode(QFileDialog::AnyFile);
    dialog.setNameFilter("Video Files (*.mkv *.mp4 *.avi *.m4v *.mov *.ts);;All Files (*)");

    if (!m_lineEdit->text().isEmpty()) {
        QFileInfo fi(m_lineEdit->text());
        dialog.setDirectory(fi.absolutePath());
    }

    if (dialog.exec() == QDialog::Accepted) {
        QStringList files = dialog.selectedFiles();
        if (!files.isEmpty()) {
            m_lineEdit->setText(files.first());
        }
    }
}

// =============================================================================
// AddJobDialog
// =============================================================================

AddJobDialog::AddJobDialog(QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle("Add Job(s) to Queue");
    setMinimumSize(700, 300);

    buildUi();

    // Start with 2 sources by default
    addSourceInput();
    addSourceInput();
}

void AddJobDialog::buildUi()
{
    auto* mainLayout = new QVBoxLayout(this);

    // Scroll area for source inputs
    auto* scrollArea = new QScrollArea();
    scrollArea->setWidgetResizable(true);

    auto* container = new QWidget();
    m_inputsLayout = new QVBoxLayout(container);
    scrollArea->setWidget(container);

    mainLayout->addWidget(scrollArea);

    // Add source button
    auto* addSourceBtn = new QPushButton("Add Another Source");
    connect(addSourceBtn, &QPushButton::clicked, this, &AddJobDialog::addSourceInput);
    mainLayout->addWidget(addSourceBtn);

    // Dialog buttons
    auto* buttonBox = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel);

    auto* okBtn = buttonBox->button(QDialogButtonBox::Ok);
    okBtn->setText("Find && Add Jobs");

    connect(okBtn, &QPushButton::clicked, this, &AddJobDialog::findAndAccept);
    connect(buttonBox, &QDialogButtonBox::rejected, this, &QDialog::reject);

    mainLayout->addWidget(buttonBox);
}

void AddJobDialog::addSourceInput()
{
    int sourceNum = static_cast<int>(m_sourceWidgets.size()) + 1;
    auto* widget = new SourceInputWidget(sourceNum);
    m_sourceWidgets.push_back(widget);
    m_inputsLayout->addWidget(widget);
}

void AddJobDialog::populateSourcesFromPaths(const QStringList& paths)
{
    // Clear existing inputs
    while (m_inputsLayout->count() > 0) {
        QLayoutItem* item = m_inputsLayout->takeAt(0);
        if (item && item->widget()) {
            item->widget()->deleteLater();
        }
        delete item;
    }
    m_sourceWidgets.clear();

    // Add an input for each path
    for (const QString& path : paths) {
        addSourceInput();
        m_sourceWidgets.back()->setText(path);
    }

    // Ensure at least two inputs
    while (m_sourceWidgets.size() < 2) {
        addSourceInput();
    }
}

void AddJobDialog::findAndAccept()
{
    // Collect non-empty source paths
    std::map<QString, QString> sources;
    for (size_t i = 0; i < m_sourceWidgets.size(); ++i) {
        QString path = m_sourceWidgets[i]->text().trimmed();
        if (!path.isEmpty()) {
            sources[QString("Source %1").arg(i + 1)] = path;
        }
    }

    // Validate
    if (sources.find("Source 1") == sources.end()) {
        QMessageBox::warning(this, "Input Required",
            "Source 1 (Reference) cannot be empty.");
        return;
    }

    if (sources.size() < 2) {
        QMessageBox::warning(this, "Input Required",
            "At least two sources are required to discover jobs.");
        return;
    }

    // TODO: Call bridge to discover jobs
    // auto jobs = vsg::bridge_discover_jobs(paths);

    // For now, create a stub job from the inputs
    m_discoveredJobs.clear();
    m_discoveredJobs.push_back(sources);

    accept();
}

std::vector<std::map<QString, QString>> AddJobDialog::getDiscoveredJobs() const
{
    return m_discoveredJobs;
}
