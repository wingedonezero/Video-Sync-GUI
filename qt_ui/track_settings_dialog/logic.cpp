// Track Settings Dialog Logic Implementation

#include "logic.hpp"
#include "ui.hpp"

TrackSettingsLogic::TrackSettingsLogic(TrackSettingsDialog* dialog)
    : QObject(dialog)
    , m_dialog(dialog)
{
}

void TrackSettingsLogic::applyInitialValues(const std::map<QString, QVariant>& values)
{
    // Language
    auto langIt = values.find("language");
    if (langIt != values.end()) {
        QString lang = langIt->second.toString();
        int idx = m_dialog->langCombo()->findData(lang);
        if (idx >= 0) {
            m_dialog->langCombo()->setCurrentIndex(idx);
        } else {
            m_dialog->langCombo()->setEditText(lang);
        }
    }

    // Custom name
    auto nameIt = values.find("custom_name");
    if (nameIt != values.end()) {
        m_dialog->customNameInput()->setText(nameIt->second.toString());
    }

    // OCR
    auto ocrIt = values.find("perform_ocr");
    if (ocrIt != values.end()) {
        m_dialog->cbOcr()->setChecked(ocrIt->second.toBool());
    }

    // Convert to ASS
    auto convertIt = values.find("convert_to_ass");
    if (convertIt != values.end()) {
        m_dialog->cbConvert()->setChecked(convertIt->second.toBool());
    }

    // Rescale
    auto rescaleIt = values.find("rescale");
    if (rescaleIt != values.end()) {
        m_dialog->cbRescale()->setChecked(rescaleIt->second.toBool());
    }

    // Size multiplier
    auto sizeIt = values.find("size_multiplier");
    if (sizeIt != values.end()) {
        m_dialog->sizeMultiplier()->setValue(sizeIt->second.toDouble());
    }
}

std::map<QString, QVariant> TrackSettingsLogic::readValues() const
{
    std::map<QString, QVariant> values;

    // Language
    QString lang = m_dialog->langCombo()->currentData().toString();
    if (lang.isEmpty()) {
        lang = m_dialog->langCombo()->currentText();
    }
    values["language"] = lang;

    // Custom name
    values["custom_name"] = m_dialog->customNameInput()->text();

    // Subtitle options
    values["perform_ocr"] = m_dialog->cbOcr()->isChecked();
    values["convert_to_ass"] = m_dialog->cbConvert()->isChecked();
    values["rescale"] = m_dialog->cbRescale()->isChecked();
    values["size_multiplier"] = m_dialog->sizeMultiplier()->value();

    return values;
}
