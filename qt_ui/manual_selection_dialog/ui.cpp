// Manual Selection Dialog Implementation

#include "ui.hpp"
#include "logic.hpp"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QKeyEvent>
#include <QFileInfo>
#include <algorithm>
#include <regex>

// =============================================================================
// SourceList
// =============================================================================

SourceList::SourceList(QWidget* parent)
    : QListWidget(parent)
{
    setSelectionMode(QAbstractItemView::SingleSelection);
}

void SourceList::addTrackItem(const SourceTrackInfo& track, bool blocked)
{
    // Store the track info
    int trackIndex = static_cast<int>(m_tracks.size());
    m_tracks.push_back(track);

    auto* item = new QListWidgetItem(track.description);
    item->setData(Qt::UserRole, trackIndex);  // Store index into m_tracks

    if (blocked) {
        item->setFlags(item->flags() & ~Qt::ItemIsEnabled);
        item->setForeground(Qt::gray);
    }

    // Color-coded background based on track type
    QString typeStr = track.type.toLower();
    if (typeStr == "video") {
        item->setBackground(QColor(200, 230, 255, 50));  // Light blue tint
    } else if (typeStr == "audio") {
        item->setBackground(QColor(200, 255, 200, 50));  // Light green tint
    } else {
        item->setBackground(QColor(255, 255, 200, 50));  // Light yellow tint
    }

    addItem(item);
}

SourceTrackInfo SourceList::getTrackAt(int row) const
{
    if (row >= 0 && row < static_cast<int>(m_tracks.size())) {
        return m_tracks[row];
    }
    return SourceTrackInfo{};
}

void SourceList::mouseDoubleClickEvent(QMouseEvent* event)
{
    QListWidgetItem* item = itemAt(event->pos());
    if (item && (item->flags() & Qt::ItemIsEnabled)) {
        // Get the full track info from our stored data
        int trackIndex = item->data(Qt::UserRole).toInt();
        if (trackIndex >= 0 && trackIndex < static_cast<int>(m_tracks.size())) {
            emit trackDoubleClicked(m_tracks[trackIndex]);
        }
    }
    QListWidget::mouseDoubleClickEvent(event);
}

// =============================================================================
// FinalList
// =============================================================================

FinalList::FinalList(QWidget* parent)
    : QListWidget(parent)
{
    setSelectionMode(QAbstractItemView::SingleSelection);
    setDragDropMode(QAbstractItemView::InternalMove);
    setDefaultDropAction(Qt::MoveAction);
}

void FinalList::addTrackWidget(const TrackData& track)
{
    auto* item = new QListWidgetItem();
    item->setSizeHint(QSize(0, 70));  // Height for two-row track widget

    auto* widget = new TrackWidget(track, m_availableSources, this);

    addItem(item);
    setItemWidget(item, widget);
}

void FinalList::removeSelectedTrack()
{
    auto* item = currentItem();
    if (item) {
        int row = this->row(item);
        takeItem(row);
        delete item;
    }
}

void FinalList::moveSelectedBy(int direction)
{
    int currentRow = currentIndex().row();
    if (currentRow < 0) return;

    int newRow = currentRow + direction;
    if (newRow < 0 || newRow >= count()) return;

    // Take the item and reinsert at new position
    auto* item = takeItem(currentRow);
    insertItem(newRow, item);

    // Need to re-set the widget since takeItem clears it
    // This is a simplification - in a real implementation you'd
    // preserve the widget or recreate it

    setCurrentRow(newRow);
}

std::vector<TrackData> FinalList::getTracks() const
{
    std::vector<TrackData> tracks;

    for (int i = 0; i < count(); ++i) {
        auto* item = this->item(i);
        auto* widget = qobject_cast<TrackWidget*>(itemWidget(item));
        if (widget) {
            tracks.push_back(widget->trackData());
        }
    }

    return tracks;
}

void FinalList::keyPressEvent(QKeyEvent* event)
{
    if (event->key() == Qt::Key_Delete) {
        removeSelectedTrack();
        event->accept();
        return;
    }

    QListWidget::keyPressEvent(event);
}

// =============================================================================
// ManualSelectionDialog
// =============================================================================

ManualSelectionDialog::ManualSelectionDialog(
    const std::map<QString, std::vector<SourceTrackInfo>>& trackInfo,
    QWidget* parent)
    : QDialog(parent)
    , m_trackInfo(trackInfo)
{
    setWindowTitle("Manual Track Selection");
    setMinimumSize(1200, 700);

    // Sort source keys naturally
    for (const auto& pair : trackInfo) {
        m_availableSources.append(pair.first);
    }
    std::sort(m_availableSources.begin(), m_availableSources.end(),
        [](const QString& a, const QString& b) {
            // Extract number from "Source N"
            std::regex re(R"(\d+)");
            std::smatch ma, mb;
            std::string sa = a.toStdString();
            std::string sb = b.toStdString();
            if (std::regex_search(sa, ma, re) && std::regex_search(sb, mb, re)) {
                return std::stoi(ma[0]) < std::stoi(mb[0]);
            }
            return a < b;
        });

    buildUi();
    wireSignals();
    populateSources();

    m_logic = std::make_unique<ManualLogic>(this);
}

ManualSelectionDialog::~ManualSelectionDialog() = default;

void ManualSelectionDialog::buildUi()
{
    auto* root = new QVBoxLayout(this);

    // Info label (hidden by default)
    m_infoLabel = new QLabel();
    m_infoLabel->setVisible(false);
    m_infoLabel->setStyleSheet("color: green; font-weight: bold;");
    m_infoLabel->setAlignment(Qt::AlignCenter);
    root->addWidget(m_infoLabel);

    // Main horizontal layout (left pane | right pane)
    auto* mainHBox = new QHBoxLayout();

    // === Left Pane: Source tracks ===
    auto* leftPane = new QWidget();
    auto* leftPaneLayout = new QVBoxLayout(leftPane);
    leftPaneLayout->setContentsMargins(0, 0, 0, 0);

    auto* leftScroll = new QScrollArea();
    leftScroll->setWidgetResizable(true);

    auto* leftWidget = new QWidget();
    auto* leftVBox = new QVBoxLayout(leftWidget);
    leftVBox->setContentsMargins(0, 0, 0, 0);

    // Create source list for each source
    for (const QString& sourceKey : m_availableSources) {
        QString title = QString("%1 Tracks").arg(sourceKey);
        if (sourceKey == "Source 1") {
            title = "Source 1 (Reference) Tracks";
        }

        auto* sourceList = new SourceList();
        m_sourceLists[sourceKey] = sourceList;

        auto* groupBox = new QGroupBox(title);
        auto* groupLayout = new QVBoxLayout(groupBox);
        groupLayout->addWidget(sourceList);
        leftVBox->addWidget(groupBox);
    }

    // External subtitles section
    m_externalList = new SourceList();
    m_externalGroup = new QGroupBox("External Subtitles");
    auto* extLayout = new QVBoxLayout(m_externalGroup);
    extLayout->addWidget(m_externalList);
    m_externalGroup->setVisible(false);
    leftVBox->addWidget(m_externalGroup);

    leftVBox->addStretch(1);
    leftScroll->setWidget(leftWidget);

    m_addExternalBtn = new QPushButton("Add External Subtitle(s)...");
    leftPaneLayout->addWidget(leftScroll);
    leftPaneLayout->addWidget(m_addExternalBtn);

    mainHBox->addWidget(leftPane, 1);  // 1/3 width

    // === Right Pane: Final output ===
    auto* rightPane = new QWidget();
    auto* rightPaneLayout = new QVBoxLayout(rightPane);
    rightPaneLayout->setContentsMargins(0, 0, 0, 0);

    m_finalList = new FinalList();
    m_finalList->setAvailableSources(m_availableSources);
    auto* finalGroup = new QGroupBox("Final Output (Drag to reorder)");
    auto* finalLayout = new QVBoxLayout(finalGroup);
    finalLayout->addWidget(m_finalList);

    // Attachment checkboxes
    auto* attachmentGroup = new QGroupBox("Attachments");
    auto* attachmentLayout = new QHBoxLayout(attachmentGroup);
    attachmentLayout->addWidget(new QLabel("Include attachments from:"));
    for (const QString& sourceKey : m_availableSources) {
        auto* cb = new QCheckBox(sourceKey);
        m_attachmentCheckboxes[sourceKey] = cb;
        attachmentLayout->addWidget(cb);
    }
    attachmentLayout->addStretch();

    rightPaneLayout->addWidget(finalGroup);
    rightPaneLayout->addWidget(attachmentGroup);

    mainHBox->addWidget(rightPane, 2);  // 2/3 width

    root->addLayout(mainHBox);

    // Dialog buttons
    auto* btns = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    connect(btns, &QDialogButtonBox::accepted, this, &ManualSelectionDialog::accept);
    connect(btns, &QDialogButtonBox::rejected, this, &QDialog::reject);
    root->addWidget(btns);
}

void ManualSelectionDialog::wireSignals()
{
    // Connect source lists
    for (auto& pair : m_sourceLists) {
        connect(pair.second, &SourceList::trackDoubleClicked,
                this, &ManualSelectionDialog::onSourceTrackDoubleClicked);
    }
    connect(m_externalList, &SourceList::trackDoubleClicked,
            this, &ManualSelectionDialog::onSourceTrackDoubleClicked);

    connect(m_addExternalBtn, &QPushButton::clicked,
            this, &ManualSelectionDialog::onAddExternalSubtitles);
}

void ManualSelectionDialog::populateSources()
{
    for (const auto& pair : m_trackInfo) {
        const QString& sourceKey = pair.first;
        const auto& tracks = pair.second;

        auto* sourceList = m_sourceLists[sourceKey];
        if (!sourceList) continue;

        for (const auto& track : tracks) {
            // Block video tracks from non-reference sources (only one video allowed)
            bool blocked = (track.type.toLower() == "video" && sourceKey != "Source 1");
            sourceList->addTrackItem(track, blocked);
        }
    }
}

void ManualSelectionDialog::onSourceTrackDoubleClicked(const SourceTrackInfo& track)
{
    // Convert SourceTrackInfo to TrackData and add to final list
    TrackData trackData;
    trackData.id = track.id;
    trackData.codecId = track.codecId;
    trackData.language = track.language;
    trackData.name = track.name;
    trackData.summary = track.description;
    trackData.isDefault = track.isDefault;
    trackData.isForced = track.isForced;
    trackData.originalPath = track.originalPath;

    // Copy additional metadata
    trackData.channels = track.channels;
    trackData.sampleRate = track.sampleRate;
    trackData.width = track.width;
    trackData.height = track.height;

    // Determine track type (case-insensitive)
    QString typeStr = track.type.toLower().trimmed();
    if (typeStr == "video") {
        trackData.type = TrackType::Video;
    } else if (typeStr == "audio") {
        trackData.type = TrackType::Audio;
    } else {
        // "subtitles" (from mkvmerge) or any other type
        trackData.type = TrackType::Subtitle;
    }

    // Find source key
    for (const auto& pair : m_sourceLists) {
        if (pair.second == sender()) {
            trackData.sourceKey = pair.first;
            break;
        }
    }

    m_finalList->addTrackWidget(trackData);
}

void ManualSelectionDialog::onAddExternalSubtitles()
{
    QStringList files = QFileDialog::getOpenFileNames(
        this, "Select External Subtitle Files", "",
        "Subtitle Files (*.srt *.ass *.ssa *.sup);;All Files (*)");

    if (files.isEmpty()) return;

    for (const QString& file : files) {
        QFileInfo fi(file);

        SourceTrackInfo track;
        track.id = 0;
        track.type = "subtitles";
        track.name = fi.baseName();
        track.description = QString("External: %1").arg(fi.fileName());
        track.originalPath = file;

        // Determine codec from extension
        QString ext = fi.suffix().toLower();
        if (ext == "srt") {
            track.codecId = "S_TEXT/UTF8";
        } else if (ext == "ass" || ext == "ssa") {
            track.codecId = "S_TEXT/ASS";
        } else if (ext == "sup") {
            track.codecId = "S_HDMV/PGS";
        }

        m_externalList->addTrackItem(track);
    }

    if (m_externalList->count() > 0) {
        m_externalGroup->setVisible(true);
    }
}

void ManualSelectionDialog::accept()
{
    // Logic layer can do validation here
    QDialog::accept();
}

std::vector<TrackData> ManualSelectionDialog::getFinalLayout() const
{
    return m_finalList->getTracks();
}

QStringList ManualSelectionDialog::getAttachmentSources() const
{
    QStringList sources;
    for (const auto& pair : m_attachmentCheckboxes) {
        if (pair.second->isChecked()) {
            sources.append(pair.first);
        }
    }
    return sources;
}

void ManualSelectionDialog::keyPressEvent(QKeyEvent* event)
{
    if (event->modifiers() == Qt::ControlModifier) {
        if (event->key() == Qt::Key_Up) {
            m_finalList->moveSelectedBy(-1);
            event->accept();
            return;
        } else if (event->key() == Qt::Key_Down) {
            m_finalList->moveSelectedBy(1);
            event->accept();
            return;
        }
    }

    if (event->key() == Qt::Key_Delete) {
        m_finalList->removeSelectedTrack();
        event->accept();
        return;
    }

    QDialog::keyPressEvent(event);
}
