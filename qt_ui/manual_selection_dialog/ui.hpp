#pragma once

// Manual Selection Dialog
// Two-pane dialog for selecting and configuring tracks for output

#include <QDialog>
#include <QListWidget>
#include <QGroupBox>
#include <QCheckBox>
#include <QLabel>
#include <map>
#include <vector>
#include <memory>

#include "../track_widget/ui.hpp"

class QPushButton;
class ManualLogic;

/// Track info from source file
struct SourceTrackInfo {
    int id = 0;
    QString type;           // "video", "audio", "subtitles"
    QString codecId;
    QString language;
    QString name;
    QString description;    // Summary for display
    QString originalPath;
};

/// Source list widget (left pane) - shows available tracks from a source
class SourceList : public QListWidget
{
    Q_OBJECT

public:
    explicit SourceList(QWidget* parent = nullptr);

    void addTrackItem(const SourceTrackInfo& track, bool blocked = false);

signals:
    void trackDoubleClicked(const SourceTrackInfo& track);

protected:
    void mouseDoubleClickEvent(QMouseEvent* event) override;
};

/// Final list widget (right pane) - shows selected tracks with drag-to-reorder
class FinalList : public QListWidget
{
    Q_OBJECT

public:
    explicit FinalList(QWidget* parent = nullptr);

    void addTrackWidget(const TrackData& track);
    void removeSelectedTrack();
    void moveSelectedBy(int direction);

    std::vector<TrackData> getTracks() const;

protected:
    void keyPressEvent(QKeyEvent* event) override;

private:
    QStringList m_availableSources;
};

/// Manual Selection Dialog
class ManualSelectionDialog : public QDialog
{
    Q_OBJECT

public:
    /// Constructor
    /// @param trackInfo Map of source key ("Source 1", etc.) to list of tracks
    explicit ManualSelectionDialog(
        const std::map<QString, std::vector<SourceTrackInfo>>& trackInfo,
        QWidget* parent = nullptr);
    ~ManualSelectionDialog() override;

    /// Get the final track layout after accepting
    std::vector<TrackData> getFinalLayout() const;

    /// Get which sources to include attachments from
    QStringList getAttachmentSources() const;

    // Accessors for logic layer
    QLabel* infoLabel() { return m_infoLabel; }
    FinalList* finalList() { return m_finalList; }
    std::map<QString, SourceList*>& sourceLists() { return m_sourceLists; }
    std::map<QString, QCheckBox*>& attachmentCheckboxes() { return m_attachmentCheckboxes; }

public slots:
    void accept() override;

protected:
    void keyPressEvent(QKeyEvent* event) override;

private slots:
    void onSourceTrackDoubleClicked(const SourceTrackInfo& track);
    void onAddExternalSubtitles();

private:
    void buildUi();
    void wireSignals();
    void populateSources();

    std::map<QString, std::vector<SourceTrackInfo>> m_trackInfo;
    QStringList m_availableSources;

    // UI Elements
    QLabel* m_infoLabel;
    std::map<QString, SourceList*> m_sourceLists;
    SourceList* m_externalList;
    QGroupBox* m_externalGroup;
    QPushButton* m_addExternalBtn;
    FinalList* m_finalList;
    std::map<QString, QCheckBox*> m_attachmentCheckboxes;

    std::unique_ptr<ManualLogic> m_logic;
};
