#pragma once

// Add Job Dialog
// Allows user to specify sources to discover jobs from

#include <QDialog>
#include <QLineEdit>
#include <QVBoxLayout>
#include <vector>
#include <map>

class QPushButton;

/// Single source input row with label, line edit, and browse button
class SourceInputWidget : public QWidget
{
    Q_OBJECT

public:
    explicit SourceInputWidget(int sourceNum, QWidget* parent = nullptr);

    QString text() const { return m_lineEdit->text(); }
    void setText(const QString& text) { m_lineEdit->setText(text); }
    QLineEdit* lineEdit() { return m_lineEdit; }

protected:
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dropEvent(QDropEvent* event) override;

private slots:
    void browseForPath();

private:
    QLineEdit* m_lineEdit;
};

/// Dialog for adding jobs to the queue
class AddJobDialog : public QDialog
{
    Q_OBJECT

public:
    explicit AddJobDialog(QWidget* parent = nullptr);

    /// Get the discovered jobs after dialog accepts
    /// Returns list of job specs (as JSON strings for now, TODO: proper struct)
    std::vector<std::map<QString, QString>> getDiscoveredJobs() const;

    /// Pre-populate sources from a list of paths (e.g., from drag-drop)
    void populateSourcesFromPaths(const QStringList& paths);

public slots:
    void addSourceInput();
    void findAndAccept();

private:
    void buildUi();

    QVBoxLayout* m_inputsLayout;
    std::vector<SourceInputWidget*> m_sourceWidgets;
    std::vector<std::map<QString, QString>> m_discoveredJobs;
};
