#pragma once

// Manual Selection Dialog Logic

#include <QObject>

class ManualSelectionDialog;

class ManualLogic : public QObject
{
    Q_OBJECT

public:
    explicit ManualLogic(ManualSelectionDialog* dialog);

    /// Check if a track should be blocked (e.g., video from non-reference source)
    bool isBlockedVideo(const QString& type, const QString& sourceKey) const;

private:
    ManualSelectionDialog* m_dialog;
};
