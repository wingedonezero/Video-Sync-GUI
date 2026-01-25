#pragma once

// Options Dialog Logic
// Handles loading/saving settings to bridge

#include <QObject>

class OptionsDialog;

class OptionsLogic : public QObject
{
    Q_OBJECT

public:
    explicit OptionsLogic(OptionsDialog* dialog);

    /// Load settings from config (via bridge) into UI widgets
    void loadSettings();

    /// Save UI widget values to config (via bridge)
    void saveSettings();

private:
    OptionsDialog* m_dialog;
};
