// Track Widget Implementation

#include "ui.hpp"
#include "logic.hpp"

#include <QVBoxLayout>
#include <QHBoxLayout>

TrackWidget::TrackWidget(const TrackData& track, const QStringList& availableSources,
                         QWidget* parent)
    : QWidget(parent)
    , m_trackData(track)
    , m_availableSources(availableSources)
{
    // Create UI elements
    m_summaryLabel = new QLabel("...");
    m_summaryLabel->setStyleSheet("font-weight: bold;");

    m_sourceLabel = new QLabel("...");

    m_badgeLabel = new QLabel("");
    m_badgeLabel->setStyleSheet("color: #E0A800; font-weight: bold;");

    m_cbDefault = new QCheckBox("Default");
    m_cbForced = new QCheckBox("Forced");
    m_cbName = new QCheckBox("Set Name");

    m_syncToLabel = new QLabel("Sync to Source:");
    m_syncToCombo = new QComboBox();
    for (const QString& src : availableSources) {
        m_syncToCombo->addItem(src);
    }

    m_styleEditorBtn = new QPushButton("Style Editor...");
    m_settingsBtn = new QPushButton("Settings...");

    // Hidden controls (state managed by settings dialog)
    m_cbOcr = new QCheckBox("Perform OCR");
    m_cbOcr->setVisible(false);
    m_cbConvert = new QCheckBox("To ASS");
    m_cbConvert->setVisible(false);
    m_cbRescale = new QCheckBox("Rescale");
    m_cbRescale->setVisible(false);

    m_sizeMultiplier = new QDoubleSpinBox();
    m_sizeMultiplier->setRange(0.1, 10.0);
    m_sizeMultiplier->setSingleStep(0.1);
    m_sizeMultiplier->setDecimals(2);
    m_sizeMultiplier->setPrefix("Size x");
    m_sizeMultiplier->setVisible(false);

    buildLayout();

    // Create logic controller
    m_logic = std::make_unique<TrackWidgetLogic>(this, track, availableSources);

    // Connections
    connect(m_settingsBtn, &QPushButton::clicked, this, &TrackWidget::onSettingsClicked);
    connect(m_styleEditorBtn, &QPushButton::clicked, this, &TrackWidget::onStyleEditorClicked);
    connect(m_cbDefault, &QCheckBox::stateChanged, this, [this]() {
        m_logic->refreshBadges();
        emit configChanged();
    });
    connect(m_cbForced, &QCheckBox::stateChanged, this, [this]() {
        m_logic->refreshBadges();
        emit configChanged();
    });
    connect(m_cbName, &QCheckBox::stateChanged, this, [this]() {
        emit configChanged();
    });

    // Initial refresh
    refresh();
}

TrackWidget::~TrackWidget() = default;

void TrackWidget::buildLayout()
{
    auto* rootLayout = new QVBoxLayout(this);
    rootLayout->setContentsMargins(5, 5, 5, 5);

    // Top row: summary, badges, source
    auto* topRow = new QHBoxLayout();
    topRow->addWidget(m_summaryLabel, 1);
    topRow->addWidget(m_badgeLabel);
    topRow->addWidget(m_sourceLabel);
    rootLayout->addLayout(topRow);

    // Bottom row: controls
    auto* bottomRow = new QHBoxLayout();
    bottomRow->addStretch();

    // Only show sync combo for external subtitles
    m_syncToLabel->setVisible(false);
    m_syncToCombo->setVisible(false);
    bottomRow->addWidget(m_syncToLabel);
    bottomRow->addWidget(m_syncToCombo);

    bottomRow->addWidget(m_cbDefault);

    // Only show forced for subtitles
    m_cbForced->setVisible(m_trackData.type == TrackType::Subtitle);
    bottomRow->addWidget(m_cbForced);

    bottomRow->addWidget(m_cbName);

    // Only show style editor for subtitles
    m_styleEditorBtn->setVisible(m_trackData.type == TrackType::Subtitle);
    bottomRow->addWidget(m_styleEditorBtn);

    bottomRow->addWidget(m_settingsBtn);

    rootLayout->addLayout(bottomRow);
}

void TrackWidget::refresh()
{
    m_logic->refreshSummary();
    m_logic->refreshBadges();
}

std::map<QString, QVariant> TrackWidget::getConfig() const
{
    return m_logic->getConfig();
}

void TrackWidget::onSettingsClicked()
{
    emit settingsRequested();
}

void TrackWidget::onStyleEditorClicked()
{
    emit styleEditorRequested();
}
