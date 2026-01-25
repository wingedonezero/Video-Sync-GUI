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

    // Format: [Source] [Type-ID] Codec (lang) "Name" [metadata]
    // e.g.: [Source 1] [V-0] MPEG4/ISO/AVC (eng) [1920x1080]
    // e.g.: [Source 2] [A-1] AAC (jpn) "Japanese Stereo" [2ch 48kHz]

    // Type prefix with track ID
    QString typeChar;
    switch (m_trackData.type) {
        case TrackType::Video: typeChar = "V"; break;
        case TrackType::Audio: typeChar = "A"; break;
        case TrackType::Subtitle: typeChar = "S"; break;
    }
    summary = QString("[%1-%2]").arg(typeChar).arg(m_trackData.id);

    // Codec (simplified)
    if (!m_trackData.codecId.isEmpty()) {
        QString codec = m_trackData.codecId;
        // Remove common prefixes
        if (codec.startsWith("V_")) codec = codec.mid(2);
        if (codec.startsWith("A_")) codec = codec.mid(2);
        if (codec.startsWith("S_")) codec = codec.mid(2);
        summary += QString(" %1").arg(codec);
    }

    // Language
    if (!m_trackData.language.isEmpty() && m_trackData.language != "und") {
        summary += QString(" (%1)").arg(m_trackData.language);
    }

    // Name
    if (!m_trackData.name.isEmpty()) {
        summary += QString(" \"%1\"").arg(m_trackData.name);
    }

    // Video metadata
    if (m_trackData.type == TrackType::Video && m_trackData.width > 0) {
        summary += QString(" [%1x%2]").arg(m_trackData.width).arg(m_trackData.height);
    }

    // Audio metadata
    if (m_trackData.type == TrackType::Audio && m_trackData.channels > 0) {
        summary += QString(" [%1ch").arg(m_trackData.channels);
        if (m_trackData.sampleRate > 0) {
            summary += QString(" %1kHz").arg(m_trackData.sampleRate / 1000.0, 0, 'f', 1);
        }
        summary += "]";
    }

    m_widget->summaryLabel()->setText(summary);

    // Source label in brackets
    m_widget->sourceLabel()->setText(QString("[%1]").arg(m_trackData.sourceKey));
}

void TrackWidgetLogic::refreshBadges()
{
    QStringList badges;

    // Use emoji badges like Python version
    if (m_widget->defaultCheck()->isChecked()) {
        badges << QString::fromUtf8("\u2B50");  // Star emoji for Default
    }

    if (m_widget->forcedCheck()->isChecked() &&
        m_trackData.type == TrackType::Subtitle) {
        badges << QString::fromUtf8("\U0001F4CC");  // Pin emoji for Forced
    }

    if (m_widget->nameCheck()->isChecked()) {
        badges << QString::fromUtf8("\U0001F4DD");  // Memo emoji for Name
    }

    // TODO: Add more badges for OCR, sync exclusions, etc.
    // 🔄 for sync
    // 📝 for OCR

    QString badgeText = badges.join(" ");
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
