#pragma once

// Track Settings Dialog
// Per-track configuration popup

#include <QDialog>
#include <QComboBox>
#include <QLineEdit>
#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QGroupBox>
#include <map>
#include <memory>

class TrackSettingsLogic;

class TrackSettingsDialog : public QDialog
{
    Q_OBJECT

public:
    /// Constructor
    /// @param trackType "video", "audio", or "subtitles"
    /// @param codecId Codec identifier (e.g., "S_TEXT/ASS", "A_AAC")
    /// @param initialValues Initial values for the controls
    explicit TrackSettingsDialog(
        const QString& trackType,
        const QString& codecId,
        const std::map<QString, QVariant>& initialValues = {},
        QWidget* parent = nullptr);
    ~TrackSettingsDialog() override;

    /// Read current values from the dialog controls
    std::map<QString, QVariant> readValues() const;

    // Widget accessors for logic layer
    QComboBox* langCombo() { return m_langCombo; }
    QLineEdit* customNameInput() { return m_customNameInput; }
    QCheckBox* cbOcr() { return m_cbOcr; }
    QCheckBox* cbConvert() { return m_cbConvert; }
    QCheckBox* cbRescale() { return m_cbRescale; }
    QDoubleSpinBox* sizeMultiplier() { return m_sizeMultiplier; }

private slots:
    void onSyncExclusionClicked();

private:
    void buildUi();
    void initForTypeAndCodec(const QString& trackType, const QString& codecId);

    QString m_trackType;
    QString m_codecId;

    // Language section
    QComboBox* m_langCombo;

    // Track name section
    QLineEdit* m_customNameInput;

    // Subtitle options section
    QGroupBox* m_subtitleGroup;
    QCheckBox* m_cbOcr;
    QCheckBox* m_cbConvert;
    QCheckBox* m_cbRescale;
    QDoubleSpinBox* m_sizeMultiplier;
    QPushButton* m_syncExclusionBtn;

    std::unique_ptr<TrackSettingsLogic> m_logic;
};
