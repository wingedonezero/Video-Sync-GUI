//! Subtitle style manipulation
//!
//! Provides font size multiplication for ASS/SSA subtitle styles

use crate::core::models::results::CoreResult;
use std::path::Path;

/// Multiply font sizes in ASS/SSA subtitle file
///
/// Parses `Style:` lines in the ASS/SSA format and multiplies the font size field.
/// The ASS format is: `Style: Name,Fontname,Fontsize,PrimaryColour,...`
/// Font size is the 3rd field (index 2 after splitting by comma).
///
/// # Arguments
/// * `subtitle_path` - Path to the ASS/SSA file
/// * `multiplier` - Multiplier for font sizes (e.g., 1.5 = 150%)
///
/// # Returns
/// Number of modified style lines
pub fn multiply_font_sizes(subtitle_path: &Path, multiplier: f64) -> CoreResult<usize> {
    // Read the file
    let content = std::fs::read_to_string(subtitle_path)
        .map_err(|e| format!("Failed to read subtitle file: {}", e))?;

    let mut modified_count = 0;
    let mut new_lines = Vec::new();

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.to_lowercase().starts_with("style:") {
            // Parse style line: Style: Name,Fontname,Fontsize,...
            let parts: Vec<&str> = line.splitn(4, ',').collect();

            if parts.len() >= 4 {
                // parts[0] = "Style: Name"
                // parts[1] = "Fontname"
                // parts[2] = "Fontsize"
                // parts[3] = rest of style definition

                let style_prefix = parts[0]; // "Style: Name"
                let fontname = parts[1];      // "Fontname"
                let fontsize_str = parts[2].trim(); // "Fontsize"
                let style_suffix = parts[3];  // Rest

                // Parse and multiply font size
                if let Ok(original_size) = fontsize_str.parse::<f64>() {
                    let new_size = (original_size * multiplier).round() as i32;
                    let new_line = format!("{},{},{},{}", style_prefix, fontname, new_size, style_suffix);
                    new_lines.push(new_line);
                    modified_count += 1;
                    continue;
                }
            }
        }

        // Keep line unchanged
        new_lines.push(line.to_string());
    }

    // Write back to file
    std::fs::write(subtitle_path, new_lines.join("\n"))
        .map_err(|e| format!("Failed to write subtitle file: {}", e))?;

    Ok(modified_count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_font_size_multiplication() -> CoreResult<()> {
        // Create a temporary ASS file
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "[V4+ Styles]").unwrap();
        writeln!(temp_file, "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour").unwrap();
        writeln!(temp_file, "Style: Default,Arial,20,&H00FFFFFF,&H000000FF").unwrap();
        writeln!(temp_file, "Style: Alt,Verdana,16,&H00FFFF00,&H00000000").unwrap();
        writeln!(temp_file, "").unwrap();
        writeln!(temp_file, "[Events]").unwrap();
        writeln!(temp_file, "Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Hello").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path();

        // Multiply by 1.5
        let modified = multiply_font_sizes(path, 1.5)?;
        assert_eq!(modified, 2);

        // Read back and verify
        let content = std::fs::read_to_string(path)?;
        assert!(content.contains("Style: Default,Arial,30,")); // 20 * 1.5 = 30
        assert!(content.contains("Style: Alt,Verdana,24,")); // 16 * 1.5 = 24

        Ok(())
    }

    #[test]
    fn test_font_size_no_change() -> CoreResult<()> {
        // Multiplier of 1.0 should not change sizes
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "Style: Default,Arial,20,&H00FFFFFF,&H000000FF").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path();
        let modified = multiply_font_sizes(path, 1.0)?;
        assert_eq!(modified, 1);

        let content = std::fs::read_to_string(path)?;
        assert!(content.contains("Style: Default,Arial,20,")); // Unchanged

        Ok(())
    }
}
