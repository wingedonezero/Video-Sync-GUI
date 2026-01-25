// Main Window UI Shell Implementation

#include "window.hpp"
#include "controller.hpp"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGroupBox>
#include <QWidget>

MainWindow::MainWindow(QWidget* parent)
    : QMainWindow(parent)
{
    setWindowTitle("Video/Audio Sync & Merge");
    setGeometry(100, 100, 1000, 600);

    buildUi();

    // Create controller and wire up signals
    m_controller = std::make_unique<MainController>(this);
    m_controller->applyConfigToUi();

    // Connect signals to controller slots
    connect(m_optionsBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::openOptionsDialog);
    connect(m_queueJobsBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::openJobQueue);
    connect(m_analyzeBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::startAnalyzeOnly);
}

MainWindow::~MainWindow() = default;

void MainWindow::buildUi()
{
    auto* central = new QWidget(this);
    setCentralWidget(central);
    auto* mainLayout = new QVBoxLayout(central);

    // =========================================================================
    // Top Row - Settings button
    // =========================================================================
    auto* topRow = new QHBoxLayout();
    m_optionsBtn = new QPushButton("Settings...");
    topRow->addWidget(m_optionsBtn);
    topRow->addStretch();
    mainLayout->addLayout(topRow);

    // =========================================================================
    // Main Workflow Group
    // =========================================================================
    auto* actionsGroup = new QGroupBox("Main Workflow");
    auto* actionsLayout = new QVBoxLayout(actionsGroup);

    m_queueJobsBtn = new QPushButton("Open Job Queue for Merging...");
    m_queueJobsBtn->setStyleSheet("font-size: 14px; padding: 5px;");
    actionsLayout->addWidget(m_queueJobsBtn);

    m_archiveLogsCheck = new QCheckBox("Archive logs to a zip file on batch completion");
    actionsLayout->addWidget(m_archiveLogsCheck);

    mainLayout->addWidget(actionsGroup);

    // =========================================================================
    // Quick Analysis Group
    // =========================================================================
    auto* analysisGroup = new QGroupBox("Quick Analysis (Analyze Only)");
    auto* analysisLayout = new QVBoxLayout(analysisGroup);

    // Create input fields
    m_refInput = new QLineEdit();
    m_secInput = new QLineEdit();
    m_terInput = new QLineEdit();

    // Add file input rows
    analysisLayout->addLayout(createFileInput(
        "Source 1 (Reference):", m_refInput,
        [this]() { m_controller->browseForPath(m_refInput, "Select Reference File or Directory"); }
    ));
    analysisLayout->addLayout(createFileInput(
        "Source 2:", m_secInput,
        [this]() { m_controller->browseForPath(m_secInput, "Select Secondary File or Directory"); }
    ));
    analysisLayout->addLayout(createFileInput(
        "Source 3:", m_terInput,
        [this]() { m_controller->browseForPath(m_terInput, "Select Tertiary File or Directory"); }
    ));

    // Analyze button (right-aligned)
    auto* analyzeBtnLayout = new QHBoxLayout();
    analyzeBtnLayout->addStretch();
    m_analyzeBtn = new QPushButton("Analyze Only");
    analyzeBtnLayout->addWidget(m_analyzeBtn);
    analysisLayout->addLayout(analyzeBtnLayout);

    mainLayout->addWidget(analysisGroup);

    // =========================================================================
    // Status Row
    // =========================================================================
    auto* statusLayout = new QHBoxLayout();
    statusLayout->addWidget(new QLabel("Status:"));
    m_statusLabel = new QLabel("Ready");
    statusLayout->addWidget(m_statusLabel, 1);
    m_progressBar = new QProgressBar();
    m_progressBar->setRange(0, 100);
    m_progressBar->setValue(0);
    m_progressBar->setTextVisible(true);
    statusLayout->addWidget(m_progressBar);
    mainLayout->addLayout(statusLayout);

    // =========================================================================
    // Latest Job Results Group
    // =========================================================================
    auto* resultsGroup = new QGroupBox("Latest Job Results");
    auto* resultsLayout = new QHBoxLayout(resultsGroup);

    // Create delay labels for Source 2, 3, 4
    for (int i = 2; i <= 4; ++i) {
        resultsLayout->addWidget(new QLabel(QString("Source %1 Delay:").arg(i)));
        auto* delayLabel = new QLabel(QString::fromUtf8("\u2014")); // em-dash
        m_delayLabels.push_back(delayLabel);
        resultsLayout->addWidget(delayLabel);
        resultsLayout->addSpacing(20);
    }
    resultsLayout->addStretch();

    mainLayout->addWidget(resultsGroup);

    // =========================================================================
    // Log Group
    // =========================================================================
    auto* logGroup = new QGroupBox("Log");
    auto* logLayout = new QVBoxLayout(logGroup);
    m_logOutput = new QTextEdit();
    m_logOutput->setReadOnly(true);
    m_logOutput->setFontFamily("monospace");
    logLayout->addWidget(m_logOutput);
    mainLayout->addWidget(logGroup);
}

QLayout* MainWindow::createFileInput(const QString& label, QLineEdit* input,
                                      const std::function<void()>& browseCallback)
{
    auto* layout = new QHBoxLayout();
    auto* labelWidget = new QLabel(label);
    labelWidget->setMinimumWidth(140);
    layout->addWidget(labelWidget);
    layout->addWidget(input, 1);

    auto* browseBtn = new QPushButton("Browse...");
    connect(browseBtn, &QPushButton::clicked, this, browseCallback);
    layout->addWidget(browseBtn);

    return layout;
}
