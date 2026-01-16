// vsg_core_rs/src/mux/options_builder.rs
//
// Build mkvmerge options tokens from a MergePlan + AppSettings.
//
// Mirrors Python's vsg_core/mux/options_builder.py behavior.

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};
use std::collections::HashMap;
use std::path::Path;

use super::{calculate_track_delay, TrackType};

#[derive(Clone, Debug)]
struct ItemInfo {
    track_type: String,
    track_source: String,
    is_preserved: bool,
    is_default: bool,
    is_forced_display: bool,
    apply_track_name: bool,
    custom_lang: String,
    custom_name: String,
    container_delay_ms: i32,
    stepping_adjusted: bool,
    frame_adjusted: bool,
    sync_to: Option<String>,
    extracted_path: Option<String>,
    aspect_ratio: Option<String>,
    props_lang: Option<String>,
    props_name: Option<String>,
    codec_id: Option<String>,
}

fn extract_optional_string_attr(obj: &Bound<'_, PyAny>, name: &str) -> PyResult<Option<String>> {
    let value = match obj.getattr(name) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    if value.is_none() {
        return Ok(None);
    }
    let text = value.str()?.to_str()?.to_string();
    if text.is_empty() {
        Ok(None)
    } else {
        Ok(Some(text))
    }
}

fn extract_string_attr(obj: &Bound<'_, PyAny>, name: &str) -> PyResult<String> {
    let value = match obj.getattr(name) {
        Ok(value) => value,
        Err(_) => return Ok(String::new()),
    };
    if value.is_none() {
        return Ok(String::new());
    }
    Ok(value.str()?.to_str()?.to_string())
}

fn extract_bool_attr(obj: &Bound<'_, PyAny>, name: &str, default: bool) -> PyResult<bool> {
    let value = match obj.getattr(name) {
        Ok(value) => value,
        Err(_) => return Ok(default),
    };
    if value.is_none() {
        return Ok(default);
    }
    value.extract::<bool>().or(Ok(default))
}

fn extract_track_type(track: &Bound<'_, PyAny>) -> PyResult<String> {
    let track_type = track.getattr("type")?;
    if let Ok(value) = track_type.getattr("value") {
        Ok(value.extract::<String>()?)
    } else {
        Ok(track_type.extract::<String>()?)
    }
}

fn parse_item(item: &Bound<'_, PyAny>) -> PyResult<ItemInfo> {
    let track = item.getattr("track")?;
    let props = track.getattr("props")?;
    let track_type = extract_track_type(&track)?.to_lowercase();
    let track_source = extract_string_attr(&track, "source")?;

    let props_lang = extract_optional_string_attr(&props, "lang")?;
    let props_name = extract_optional_string_attr(&props, "name")?;
    let codec_id = extract_optional_string_attr(&props, "codec_id")?;

    let extracted_path = match item.getattr("extracted_path") {
        Ok(path_value) => {
            if path_value.is_none() {
                None
            } else {
                Some(path_value.str()?.to_str()?.to_string())
            }
        }
        Err(_) => None,
    };

    Ok(ItemInfo {
        track_type,
        track_source,
        is_preserved: extract_bool_attr(item, "is_preserved", false)?,
        is_default: extract_bool_attr(item, "is_default", false)?,
        is_forced_display: extract_bool_attr(item, "is_forced_display", false)?,
        apply_track_name: extract_bool_attr(item, "apply_track_name", false)?,
        custom_lang: extract_string_attr(item, "custom_lang")?,
        custom_name: extract_string_attr(item, "custom_name")?,
        container_delay_ms: item
            .getattr("container_delay_ms")?
            .extract::<i32>()
            .unwrap_or(0),
        stepping_adjusted: extract_bool_attr(item, "stepping_adjusted", false)?,
        frame_adjusted: extract_bool_attr(item, "frame_adjusted", false)?,
        sync_to: extract_optional_string_attr(item, "sync_to")?,
        extracted_path,
        aspect_ratio: extract_optional_string_attr(item, "aspect_ratio")?,
        props_lang,
        props_name,
        codec_id,
    })
}

fn insert_preserved(items: &mut Vec<ItemInfo>, preserved: Vec<ItemInfo>, kind: &str) {
    if preserved.is_empty() {
        return;
    }

    let mut last_idx = None;
    for (idx, item) in items.iter().enumerate() {
        if item.track_type == kind {
            last_idx = Some(idx);
        }
    }

    if let Some(idx) = last_idx {
        items.splice(idx + 1..idx + 1, preserved);
    } else {
        items.extend(preserved);
    }
}

fn first_index(items: &[ItemInfo], kind: &str, predicate: impl Fn(&ItemInfo) -> bool) -> Option<usize> {
    for (idx, item) in items.iter().enumerate() {
        if item.track_type == kind && predicate(item) {
            return Some(idx);
        }
    }
    None
}

fn to_track_type(track_type: &str) -> PyResult<TrackType> {
    match track_type {
        "video" => Ok(TrackType::Video),
        "audio" => Ok(TrackType::Audio),
        "subtitles" => Ok(TrackType::Subtitles),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Invalid track type: {track_type}"
        ))),
    }
}

pub fn build_mkvmerge_options(
    plan: &Bound<'_, PyAny>,
    settings: &Bound<'_, PyAny>,
) -> PyResult<Vec<String>> {
    let mut tokens: Vec<String> = Vec::new();

    if let Some(chapters) = extract_optional_string_attr(plan, "chapters_xml")? {
        tokens.push("--chapters".to_string());
        tokens.push(chapters);
    }

    let disable_track_statistics = extract_bool_attr(settings, "disable_track_statistics_tags", false)?;
    if disable_track_statistics {
        tokens.push("--disable-track-statistics-tags".to_string());
    }

    let items_any = plan.getattr("items")?;
    let items_list: &Bound<'_, PyList> = items_any.downcast()?;
    let mut items: Vec<ItemInfo> = Vec::with_capacity(items_list.len());
    for item in items_list.iter() {
        items.push(parse_item(&item)?);
    }

    let mut final_items: Vec<ItemInfo> = items.iter().filter(|item| !item.is_preserved).cloned().collect();
    let preserved_audio: Vec<ItemInfo> = items
        .iter()
        .filter(|item| item.is_preserved && item.track_type == "audio")
        .cloned()
        .collect();
    let preserved_subs: Vec<ItemInfo> = items
        .iter()
        .filter(|item| item.is_preserved && item.track_type == "subtitles")
        .cloned()
        .collect();

    insert_preserved(&mut final_items, preserved_audio, "audio");
    insert_preserved(&mut final_items, preserved_subs, "subtitles");

    let default_audio_idx = first_index(&final_items, "audio", |item| item.is_default);
    let default_sub_idx = first_index(&final_items, "subtitles", |item| item.is_default);
    let first_video_idx = first_index(&final_items, "video", |_| true);
    let forced_sub_idx = first_index(&final_items, "subtitles", |item| item.is_forced_display);

    let delays = plan.getattr("delays")?;
    let source_delays_ms: HashMap<String, i32> = delays.getattr("source_delays_ms")?.extract()?;
    let global_shift_ms: i32 = delays.getattr("global_shift_ms")?.extract()?;

    let disable_header_compression = extract_bool_attr(settings, "disable_header_compression", false)?;
    let apply_dialog_norm_gain = extract_bool_attr(settings, "apply_dialog_norm_gain", false)?;

    let mut order_entries: Vec<String> = Vec::new();
    for (idx, item) in final_items.iter().enumerate() {
        let sync_key = if item.track_source == "External" {
            item.sync_to.clone().unwrap_or_else(|| item.track_source.clone())
        } else {
            item.track_source.clone()
        };

        let track_type = to_track_type(&item.track_type)?;
        let delay_ms = calculate_track_delay(
            track_type,
            &sync_key,
            item.container_delay_ms,
            global_shift_ms,
            &source_delays_ms,
            item.stepping_adjusted,
            item.frame_adjusted,
        );

        let is_default = Some(idx) == first_video_idx
            || Some(idx) == default_audio_idx
            || Some(idx) == default_sub_idx;

        let lang_code = if !item.custom_lang.is_empty() {
            item.custom_lang.clone()
        } else if let Some(lang) = item.props_lang.as_ref().filter(|lang| !lang.is_empty()) {
            lang.clone()
        } else {
            "und".to_string()
        };

        tokens.push("--language".to_string());
        tokens.push(format!("0:{lang_code}"));

        if !item.custom_name.is_empty() {
            tokens.push("--track-name".to_string());
            tokens.push(format!("0:{}", item.custom_name));
        } else if item.apply_track_name {
            if let Some(name) = item.props_name.as_ref().map(|name| name.trim()).filter(|name| !name.is_empty()) {
                tokens.push("--track-name".to_string());
                tokens.push(format!("0:{name}"));
            }
        }

        tokens.push("--sync".to_string());
        tokens.push(format!("0:{:+}", delay_ms));
        tokens.push("--default-track-flag".to_string());
        tokens.push(format!("0:{}", if is_default { "yes" } else { "no" }));

        if Some(idx) == forced_sub_idx && item.track_type == "subtitles" {
            tokens.push("--forced-display-flag".to_string());
            tokens.push("0:yes".to_string());
        }

        if disable_header_compression {
            tokens.push("--compression".to_string());
            tokens.push("0:none".to_string());
        }

        if apply_dialog_norm_gain && item.track_type == "audio" {
            if let Some(codec_id) = item.codec_id.as_ref() {
                let cid = codec_id.to_uppercase();
                if cid.contains("AC3") || cid.contains("EAC3") {
                    tokens.push("--remove-dialog-normalization-gain".to_string());
                    tokens.push("0".to_string());
                }
            }
        }

        if item.track_type == "video" {
            if let Some(aspect_ratio) = item.aspect_ratio.as_ref() {
                tokens.push("--aspect-ratio".to_string());
                tokens.push(format!("0:{aspect_ratio}"));
            }
        }

        let extracted_path = item.extracted_path.as_ref().ok_or_else(|| {
            let name = item.props_name.clone().unwrap_or_default();
            pyo3::exceptions::PyValueError::new_err(format!(
                "Plan item at index {} ('{}') missing extracted_path",
                idx, name
            ))
        })?;

        tokens.push("(".to_string());
        tokens.push(extracted_path.clone());
        tokens.push(")".to_string());

        order_entries.push(format!("{idx}:0"));
    }

    if let Some(attachments_any) = plan.getattr("attachments").ok() {
        if !attachments_any.is_none() {
            let attachments: &Bound<'_, PyList> = attachments_any.downcast()?;
            for attachment in attachments.iter() {
                tokens.push("--attach-file".to_string());
                tokens.push(attachment.str()?.to_str()?.to_string());
            }
        }
    }

    if !order_entries.is_empty() {
        tokens.push("--track-order".to_string());
        tokens.push(order_entries.join(","));
    }

    Ok(tokens)
}

pub fn write_options_file(tokens: &[String], path: &Path) -> Result<(), String> {
    let json = serde_json::to_string(tokens).map_err(|err| format!("Failed to serialize options: {err}"))?;
    std::fs::write(path, json).map_err(|err| format!("Failed to write options file: {err}"))?;
    Ok(())
}
