#pragma once

// Main Window UI Shell
// Creates widgets and layouts - delegates all logic to MainController

#include <QMainWindow>
#include <QLineEdit>
#include <QTextEdit>
#include <QProgressBar>
#include <QLabel>
#include <QPushButton>
#include <QCheckBox>
#include <vector>
#include <memory>
#include <functional>

class QLayout;
class MainController;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    // Widget accessors for controller
    QLineEdit* refInput() { return m_refInput; }
    QLineEdit* secInput() { return m_secInput; }
    QLineEdit* terInput() { return m_terInput; }
    QTextEdit* logOutput() { return m_logOutput; }
    QProgressBar* progressBar() { return m_progressBar; }
    QLabel* statusLabel() { return m_statusLabel; }
    QCheckBox* archiveLogsCheck() { return m_archiveLogsCheck; }
    std::vector<QLabel*>& delayLabels() { return m_delayLabels; }

    // Access to controller for signal connections
    MainController* controller() { return m_controller.get(); }

private:
    void buildUi();
    QLayout* createFileInput(const QString& label, QLineEdit* input,
                             const std::function<void()>& browseCallback);

    // Widgets - Quick Analysis
    QLineEdit* m_refInput;
    QLineEdit* m_secInput;
    QLineEdit* m_terInput;

    // Widgets - Log and Status
    QTextEdit* m_logOutput;
    QProgressBar* m_progressBar;
    QLabel* m_statusLabel;

    // Widgets - Actions
    QPushButton* m_optionsBtn;
    QPushButton* m_queueJobsBtn;
    QPushButton* m_analyzeBtn;
    QCheckBox* m_archiveLogsCheck;

    // Widgets - Results
    std::vector<QLabel*> m_delayLabels;

    // Controller (owns all logic)
    std::unique_ptr<MainController> m_controller;
};
