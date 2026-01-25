#pragma once

// Track Settings Dialog Logic

#include <QObject>
#include <QVariant>
#include <map>

class TrackSettingsDialog;

class TrackSettingsLogic : public QObject
{
    Q_OBJECT

public:
    explicit TrackSettingsLogic(TrackSettingsDialog* dialog);

    /// Apply initial values to dialog controls
    void applyInitialValues(const std::map<QString, QVariant>& values);

    /// Read current values from dialog controls
    std::map<QString, QVariant> readValues() const;

private:
    TrackSettingsDialog* m_dialog;
};
