// Track Widget Logic Implementation

#include "logic.hpp"

TrackWidgetLogic::TrackWidgetLogic(TrackWidget* widget, const TrackData& track,
                                   const QStringList& availableSources)
    : QObject(widget)
    , m_widget(widget)
    , m_trackData(track)
    , m_availableSources(availableSources)
{
}

void TrackWidgetLogic::refreshSummary()
{
    QString summary;

    // Type prefix
    summary = getTrackTypeName();

    // Codec
    if (!m_trackData.codecId.isEmpty()) {
        summary += QString(" [%1]").arg(m_trackData.codecId);
    }

    // Language
    if (!m_trackData.language.isEmpty()) {
        summary += QString(" - %1").arg(m_trackData.language);
    }

    // Name
    if (!m_trackData.name.isEmpty()) {
        summary += QString(" \"%1\"").arg(m_trackData.name);
    }

    m_widget->summaryLabel()->setText(summary);

    // Source label
    m_widget->sourceLabel()->setText(m_trackData.sourceKey);
}

void TrackWidgetLogic::refreshBadges()
{
    QStringList badges;

    if (m_widget->defaultCheck()->isChecked()) {
        badges << "D";
    }

    if (m_widget->forcedCheck()->isChecked() &&
        m_trackData.type == TrackType::Subtitle) {
        badges << "F";
    }

    if (m_widget->nameCheck()->isChecked()) {
        badges << "N";
    }

    // TODO: Add more badges for OCR, sync exclusions, etc.

    QString badgeText = badges.isEmpty() ? "" : QString("[%1]").arg(badges.join(","));
    m_widget->badgeLabel()->setText(badgeText);
}

std::map<QString, QVariant> TrackWidgetLogic::getConfig() const
{
    std::map<QString, QVariant> config;

    config["track_id"] = m_trackData.id;
    config["track_type"] = static_cast<int>(m_trackData.type);
    config["source_key"] = m_trackData.sourceKey;
    config["is_default"] = m_widget->defaultCheck()->isChecked();
    config["is_forced"] = m_widget->forcedCheck()->isChecked();
    config["set_name"] = m_widget->nameCheck()->isChecked();

    if (m_widget->syncToCombo()->isVisible()) {
        config["sync_to_source"] = m_widget->syncToCombo()->currentText();
    }

    return config;
}

QString TrackWidgetLogic::getTrackTypeName() const
{
    switch (m_trackData.type) {
        case TrackType::Video:
            return "Video";
        case TrackType::Audio:
            return "Audio";
        case TrackType::Subtitle:
            return "Subtitle";
        default:
            return "Unknown";
    }
}
