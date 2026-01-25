#pragma once

// Track Widget
// A self-contained widget for displaying and configuring a single track

#include <QWidget>
#include <QLabel>
#include <QCheckBox>
#include <QComboBox>
#include <QPushButton>
#include <QDoubleSpinBox>
#include <map>
#include <memory>

class TrackWidgetLogic;

/// Track type enumeration
enum class TrackType {
    Video,
    Audio,
    Subtitle
};

/// Track data structure
struct TrackData {
    int id = 0;
    TrackType type = TrackType::Video;
    QString codecId;
    QString language;
    QString name;
    QString sourceKey;           // "Source 1", "Source 2", etc.
    bool isDefault = false;
    bool isForced = false;

    // Additional metadata
    QString summary;             // Display summary
    QString badges;              // Warning badges
    std::map<QString, QString> properties;

    // Track-specific metadata
    int channels = 0;            // Audio: number of channels
    int sampleRate = 0;          // Audio: sample rate in Hz
    int width = 0;               // Video: width in pixels
    int height = 0;              // Video: height in pixels
    QString originalPath;        // Source file path
};

class TrackWidget : public QWidget
{
    Q_OBJECT

public:
    explicit TrackWidget(const TrackData& track, const QStringList& availableSources,
                         QWidget* parent = nullptr);
    ~TrackWidget() override;

    /// Get the track configuration for output
    std::map<QString, QVariant> getConfig() const;

    /// Get the underlying track data
    const TrackData& trackData() const { return m_trackData; }

    /// Update the display from track data
    void refresh();

    // Widget accessors for logic layer
    QLabel* summaryLabel() { return m_summaryLabel; }
    QLabel* badgeLabel() { return m_badgeLabel; }
    QLabel* sourceLabel() { return m_sourceLabel; }
    QCheckBox* defaultCheck() { return m_cbDefault; }
    QCheckBox* forcedCheck() { return m_cbForced; }
    QCheckBox* nameCheck() { return m_cbName; }
    QComboBox* syncToCombo() { return m_syncToCombo; }
    QPushButton* settingsBtn() { return m_settingsBtn; }
    QPushButton* styleEditorBtn() { return m_styleEditorBtn; }

signals:
    void configChanged();
    void settingsRequested();
    void styleEditorRequested();

private slots:
    void onSettingsClicked();
    void onStyleEditorClicked();

private:
    void buildLayout();

    TrackData m_trackData;
    QStringList m_availableSources;

    // UI Elements - Top row
    QLabel* m_summaryLabel;
    QLabel* m_badgeLabel;
    QLabel* m_sourceLabel;

    // UI Elements - Bottom row (quick access controls)
    QCheckBox* m_cbDefault;
    QCheckBox* m_cbForced;
    QCheckBox* m_cbName;
    QLabel* m_syncToLabel;
    QComboBox* m_syncToCombo;
    QPushButton* m_styleEditorBtn;
    QPushButton* m_settingsBtn;

    // Hidden controls (managed by settings dialog)
    QCheckBox* m_cbOcr;
    QCheckBox* m_cbConvert;
    QCheckBox* m_cbRescale;
    QDoubleSpinBox* m_sizeMultiplier;

    std::unique_ptr<TrackWidgetLogic> m_logic;
};
