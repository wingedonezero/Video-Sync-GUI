//! File browsing handlers.

use std::path::PathBuf;

use iced::Task;

use crate::app::{App, FolderType, Message};
use super::helpers::clean_file_url;

impl App {
    /// Browse for a source file.
    pub fn browse_source(&self, idx: usize) -> Task<Message> {
        let title = match idx {
            1 => "Select Source 1 (Reference)",
            2 => "Select Source 2",
            3 => "Select Source 3",
            _ => "Select Source",
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .add_filter(
                        "Video Files",
                        &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
                    )
                    .add_filter("All Files", &["*"])
                    .pick_file()
                    .await
                    .map(|f| f.path().to_path_buf());
                (idx, path)
            },
            |(idx, path)| Message::FileSelected(idx, path),
        )
    }

    /// Handle source path changed.
    pub fn handle_source_path_changed(&mut self, idx: usize, path: String) {
        let clean_path = clean_file_url(&path);
        match idx {
            1 => self.source1_path = clean_path.clone(),
            2 => self.source2_path = clean_path.clone(),
            3 => self.source3_path = clean_path.clone(),
            _ => {}
        }
        if !clean_path.is_empty() {
            self.append_log(&format!("Source {}: {}", idx, clean_path));
        }
    }

    /// Handle file selected from browser.
    pub fn handle_file_selected(&mut self, idx: usize, path: Option<PathBuf>) {
        if let Some(p) = path {
            let path_str = p.to_string_lossy().to_string();
            match idx {
                1 => self.source1_path = path_str.clone(),
                2 => self.source2_path = path_str.clone(),
                3 => self.source3_path = path_str.clone(),
                _ => {}
            }
            self.append_log(&format!("Source {}: {}", idx, path_str));
        }
    }

    /// Browse for a folder in settings.
    pub fn browse_folder(&self, folder_type: FolderType) -> Task<Message> {
        let title = match folder_type {
            FolderType::Output => "Select Output Directory",
            FolderType::Temp => "Select Temporary Directory",
            FolderType::Logs => "Select Logs Directory",
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .pick_folder()
                    .await
                    .map(|f| f.path().to_path_buf());
                (folder_type, path)
            },
            |(folder_type, path)| Message::FolderSelected(folder_type, path),
        )
    }

    /// Handle folder selected from browser.
    pub fn handle_folder_selected(&mut self, folder_type: FolderType, path: Option<PathBuf>) {
        if let (Some(settings), Some(p)) = (&mut self.pending_settings, path) {
            let path_str = p.to_string_lossy().to_string();
            match folder_type {
                FolderType::Output => settings.paths.output_folder = path_str,
                FolderType::Temp => settings.paths.temp_root = path_str,
                FolderType::Logs => settings.paths.logs_folder = path_str,
            }
        }
    }

    /// Browse for add job source file.
    pub fn browse_add_job_source(&self, idx: usize) -> Task<Message> {
        let title = if idx == 0 {
            "Select Source 1 (Reference)"
        } else {
            "Select Source"
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .add_filter(
                        "Video Files",
                        &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
                    )
                    .add_filter("All Files", &["*"])
                    .pick_file()
                    .await
                    .map(|f| f.path().to_path_buf());
                (idx, path)
            },
            |(idx, path)| Message::AddJobFileSelected(idx, path),
        )
    }

    /// Handle add job file selected.
    pub fn handle_add_job_file_selected(&mut self, idx: usize, path: Option<PathBuf>) {
        if let Some(p) = path {
            if idx < self.add_job_sources.len() {
                self.add_job_sources[idx] = p.to_string_lossy().to_string();
            }
        }
    }

    /// Browse for external subtitles.
    pub fn browse_external_subtitles(&self) -> Task<Message> {
        Task::perform(
            async {
                let files = rfd::AsyncFileDialog::new()
                    .set_title("Select External Subtitle File(s)")
                    .add_filter("Subtitle Files", &["srt", "ass", "ssa", "sub", "idx", "sup"])
                    .add_filter("All Files", &["*"])
                    .pick_files()
                    .await
                    .map(|files| files.into_iter().map(|f| f.path().to_path_buf()).collect())
                    .unwrap_or_default();
                files
            },
            Message::ExternalFilesSelected,
        )
    }
}
