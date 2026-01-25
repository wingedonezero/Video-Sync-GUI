#pragma once

// Track Widget Logic
// Handles track display and configuration

#include "ui.hpp"
#include <QObject>
#include <map>

class TrackWidget;

class TrackWidgetLogic : public QObject
{
    Q_OBJECT

public:
    TrackWidgetLogic(TrackWidget* widget, const TrackData& track,
                     const QStringList& availableSources);

    /// Update the summary label based on track data
    void refreshSummary();

    /// Update the badge label based on configuration
    void refreshBadges();

    /// Get the current configuration from widget controls
    std::map<QString, QVariant> getConfig() const;

private:
    QString getTrackTypeName() const;

    TrackWidget* m_widget;
    TrackData m_trackData;
    QStringList m_availableSources;
};
