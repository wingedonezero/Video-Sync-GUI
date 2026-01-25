// Manual Selection Dialog Logic Implementation

#include "logic.hpp"
#include "ui.hpp"

ManualLogic::ManualLogic(ManualSelectionDialog* dialog)
    : QObject(dialog)
    , m_dialog(dialog)
{
}

bool ManualLogic::isBlockedVideo(const QString& type, const QString& sourceKey) const
{
    // Only allow video from Source 1 (reference)
    return (type == "video" && sourceKey != "Source 1");
}
