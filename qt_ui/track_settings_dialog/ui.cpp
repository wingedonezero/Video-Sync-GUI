// Track Settings Dialog Implementation

#include "ui.hpp"
#include "logic.hpp"

#include <QVBoxLayout>
#include <QFormLayout>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QMessageBox>

TrackSettingsDialog::TrackSettingsDialog(
    const QString& trackType,
    const QString& codecId,
    const std::map<QString, QVariant>& initialValues,
    QWidget* parent)
    : QDialog(parent)
    , m_trackType(trackType)
    , m_codecId(codecId)
{
    setWindowTitle("Track Settings");
    setMinimumWidth(400);

    buildUi();

    m_logic = std::make_unique<TrackSettingsLogic>(this);
    m_logic->applyInitialValues(initialValues);

    initForTypeAndCodec(trackType, codecId);
}

TrackSettingsDialog::~TrackSettingsDialog() = default;

void TrackSettingsDialog::buildUi()
{
    auto* layout = new QVBoxLayout(this);

    // === Language section ===
    auto* langGroup = new QGroupBox("Language Settings");
    auto* langLayout = new QFormLayout(langGroup);

    m_langCombo = new QComboBox();
    m_langCombo->setEditable(true);
    // Add common languages
    m_langCombo->addItem("English", "eng");
    m_langCombo->addItem("Japanese", "jpn");
    m_langCombo->addItem("Spanish", "spa");
    m_langCombo->addItem("French", "fra");
    m_langCombo->addItem("German", "deu");
    m_langCombo->addItem("Chinese", "chi");
    m_langCombo->addItem("Korean", "kor");
    m_langCombo->addItem("Undetermined", "und");

    langLayout->addRow("Language Code:", m_langCombo);
    layout->addWidget(langGroup);

    // === Track name section ===
    auto* nameGroup = new QGroupBox("Track Name");
    auto* nameLayout = new QFormLayout(nameGroup);

    m_customNameInput = new QLineEdit();
    m_customNameInput->setPlaceholderText("Leave blank to use default");

    nameLayout->addRow("Custom Name:", m_customNameInput);
    layout->addWidget(nameGroup);

    // === Subtitle options section ===
    m_subtitleGroup = new QGroupBox("Subtitle Options");
    auto* subtitleLayout = new QVBoxLayout(m_subtitleGroup);

    m_cbOcr = new QCheckBox("Perform OCR (for image-based subtitles)");
    m_cbOcr->setToolTip("Convert PGS/VobSub image subtitles to text using OCR");
    subtitleLayout->addWidget(m_cbOcr);

    m_cbConvert = new QCheckBox("Convert to ASS (for SRT files)");
    m_cbConvert->setToolTip("Convert SRT subtitles to ASS format for styling");
    subtitleLayout->addWidget(m_cbConvert);

    m_cbRescale = new QCheckBox("Rescale to video resolution");
    m_cbRescale->setToolTip("Adjust subtitle positioning for different video resolutions");
    subtitleLayout->addWidget(m_cbRescale);

    m_sizeMultiplier = new QDoubleSpinBox();
    m_sizeMultiplier->setRange(0.1, 10.0);
    m_sizeMultiplier->setSingleStep(0.1);
    m_sizeMultiplier->setDecimals(2);
    m_sizeMultiplier->setValue(1.0);
    m_sizeMultiplier->setPrefix("Size multiplier: ");
    m_sizeMultiplier->setSuffix("x");
    m_sizeMultiplier->setToolTip("Scale subtitle size (1.0 = original size)");
    subtitleLayout->addWidget(m_sizeMultiplier);

    m_syncExclusionBtn = new QPushButton("Configure Frame Sync Exclusions...");
    m_syncExclusionBtn->setToolTip("Exclude certain styles from frame-level sync adjustments");
    connect(m_syncExclusionBtn, &QPushButton::clicked,
            this, &TrackSettingsDialog::onSyncExclusionClicked);
    subtitleLayout->addWidget(m_syncExclusionBtn);

    layout->addWidget(m_subtitleGroup);

    // === Dialog buttons ===
    auto* btns = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    connect(btns, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(btns, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(btns);
}

void TrackSettingsDialog::initForTypeAndCodec(const QString& trackType, const QString& codecId)
{
    // Show/hide subtitle options based on track type
    bool isSubtitle = (trackType == "subtitles");
    m_subtitleGroup->setVisible(isSubtitle);

    if (isSubtitle) {
        QString codec = codecId.toUpper();

        // OCR only available for image-based subtitles
        bool isImageBased = codec.contains("VOBSUB") ||
                            codec.contains("PGS") ||
                            codec.contains("HDMV");
        m_cbOcr->setVisible(isImageBased);

        // Convert to ASS only for SRT
        bool isSrt = codec.contains("UTF8") || codec.contains("SRT");
        m_cbConvert->setVisible(isSrt);

        // Sync exclusion only for ASS/SSA
        bool isAss = codec.contains("ASS") || codec.contains("SSA");
        m_syncExclusionBtn->setVisible(isAss);
    }
}

void TrackSettingsDialog::onSyncExclusionClicked()
{
    // TODO: Open sync exclusion dialog
    QMessageBox::information(this, "Sync Exclusions",
        "Sync exclusion configuration not yet implemented.");
}

std::map<QString, QVariant> TrackSettingsDialog::readValues() const
{
    return m_logic->readValues();
}
