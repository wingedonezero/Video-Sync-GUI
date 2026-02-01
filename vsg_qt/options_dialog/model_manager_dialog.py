# vsg_qt/options_dialog/model_manager_dialog.py
"""Dialog for browsing, downloading, and managing audio separation models."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from vsg_core.analysis.source_separation import (
    download_model,
    get_all_available_models_from_registry,
    get_installed_models,
    update_installed_models_json,
)


class ModelDownloadThread(QThread):
    """Thread for downloading models without blocking the UI."""

    progress = Signal(int, str)  # (percent, message)
    finished = Signal(bool, str, dict)  # (success, error_message, model_metadata)

    def __init__(self, model: dict, model_dir: str):
        super().__init__()
        self.model = model  # Store full model metadata
        self.model_dir = model_dir
        self.error_message = ""

    def run(self):
        """Download the model."""

        # Capture the last progress message as error message
        def progress_with_capture(percent: int, message: str):
            if (percent == 0 and "not installed" in message.lower()) or (
                percent == 0 and "failed" in message.lower()
            ):
                self.error_message = message
            self.progress.emit(percent, message)

        success = download_model(
            self.model["filename"],
            self.model_dir,
            progress_callback=progress_with_capture,
        )
        self.finished.emit(success, self.error_message, self.model)


class ModelManagerDialog(QDialog):
    """Dialog for browsing, downloading, and managing audio separation models."""

    def __init__(self, model_dir: str, parent=None):
        super().__init__(parent)
        self.model_dir = model_dir
        self.all_models: list[dict] = []
        self.installed_models: list[dict] = []
        self.download_thread: ModelDownloadThread | None = None

        self.setWindowTitle("Source Separation Model Manager")
        self.resize(900, 600)

        self._setup_ui()
        self._load_models()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Type:"))

        self.type_filter = QComboBox()
        self.type_filter.addItems(
            [
                "All Types",
                "Demucs v4",
                "BS-Roformer",
                "MelBand Roformer",
                "MDX-Net",
                "VR Arch",
            ]
        )
        self.type_filter.currentTextChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.type_filter)

        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Installed", "Available"])
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.status_filter)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by name...")
        self.search_box.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.search_box)

        layout.addLayout(filter_layout)

        # Model table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Quality", "Type", "SDR (V/I)", "Stems", "Status", "Action"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel()
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Model info panel
        info_group = QGroupBox("Model Information")
        info_layout = QVBoxLayout(info_group)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(120)
        info_layout.addWidget(self.info_text)
        layout.addWidget(info_group)

        # Bottom buttons
        button_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self._load_models)
        button_layout.addWidget(self.refresh_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _load_models(self):
        """Load available and installed models."""
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Loading...")

        try:
            # Load installed models
            self.installed_models = get_installed_models(self.model_dir)
            print(
                f"[Model Manager] Loaded {len(self.installed_models)} installed models"
            )

            # Query audio-separator for all available models
            print("[Model Manager] Querying audio-separator registry...")
            self.all_models = get_all_available_models_from_registry()
            print(f"[Model Manager] Found {len(self.all_models)} models in registry")

            if not self.all_models:
                QMessageBox.warning(
                    self,
                    "No Models Found",
                    "Failed to load model list from audio-separator.\n\n"
                    "This could mean:\n"
                    "• audio-separator is not installed\n"
                    "• The command timed out\n"
                    "• There was a network issue\n\n"
                    "Check the terminal for error messages.",
                )

            # Merge: mark which models are installed
            installed_filenames = {m["filename"] for m in self.installed_models}
            for model in self.all_models:
                model["installed"] = model["filename"] in installed_filenames

            self._populate_table()

        except Exception as e:
            print(f"[Model Manager] Error loading models: {e}")
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to load models:\n\n{e}")
        finally:
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("Refresh List")

    def _populate_table(self):
        """Populate the table with models."""
        self.table.setRowCount(0)

        # Sort models by rank (best first), then by name
        sorted_models = sorted(
            self.all_models,
            key=lambda m: (m.get("rank", 999), m.get("name", m.get("filename", ""))),
        )

        for model in sorted_models:
            self._add_model_row(model)

        self._apply_filters()

    def _add_model_row(self, model: dict):
        """Add a row to the table for a model."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Name (with star for recommended models)
        name_text = model.get("name", model["filename"])
        if model.get("recommended"):
            name_text = f"⭐ {name_text}"
        name_item = QTableWidgetItem(name_text)
        name_item.setData(Qt.ItemDataRole.UserRole, model)
        self.table.setItem(row, 0, name_item)

        # Quality tier
        quality_tier = model.get("quality_tier", "C-Tier")
        quality_item = QTableWidgetItem(quality_tier)
        # Add color coding
        if quality_tier == "S-Tier":
            quality_item.setForeground(Qt.GlobalColor.darkGreen)
        elif quality_tier == "A-Tier":
            quality_item.setForeground(Qt.GlobalColor.darkBlue)
        elif quality_tier == "B-Tier":
            quality_item.setForeground(Qt.GlobalColor.darkYellow)
        self.table.setItem(row, 1, quality_item)

        # Type
        self.table.setItem(row, 2, QTableWidgetItem(model.get("type", "Unknown")))

        # SDR scores
        sdr_text = ""
        if model.get("sdr_vocals") and model.get("sdr_instrumental"):
            sdr_text = f"{model['sdr_vocals']:.1f} / {model['sdr_instrumental']:.1f}"
        elif model.get("sdr_vocals"):
            sdr_text = f"{model['sdr_vocals']:.1f}"
        self.table.setItem(row, 3, QTableWidgetItem(sdr_text))

        # Stems
        self.table.setItem(row, 4, QTableWidgetItem(model.get("stems", "Unknown")))

        # Status
        status = "✓ Installed" if model.get("installed") else "Available"
        self.table.setItem(row, 5, QTableWidgetItem(status))

        # Action button
        action_btn = QPushButton("Delete" if model.get("installed") else "Download")
        action_btn.setProperty("model", model)
        if model.get("installed"):
            action_btn.clicked.connect(lambda checked, m=model: self._delete_model(m))
        else:
            action_btn.clicked.connect(lambda checked, m=model: self._download_model(m))
        self.table.setCellWidget(row, 6, action_btn)

    def _apply_filters(self):
        """Apply filters to the table."""
        type_filter = self.type_filter.currentText()
        status_filter = self.status_filter.currentText()
        search_text = self.search_box.text().lower()

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue

            model = item.data(Qt.ItemDataRole.UserRole)

            # Type filter
            type_match = type_filter == "All Types" or model.get("type") == type_filter

            # Status filter
            status_match = True
            if status_filter == "Installed":
                status_match = model.get("installed", False)
            elif status_filter == "Available":
                status_match = not model.get("installed", False)

            # Search filter
            search_match = (
                not search_text
                or search_text in model.get("name", "").lower()
                or search_text in model.get("filename", "").lower()
            )

            # Show/hide row
            self.table.setRowHidden(
                row, not (type_match and status_match and search_match)
            )

    def _on_selection_changed(self):
        """Update info panel when selection changes."""
        selected = self.table.selectedItems()
        if not selected:
            self.info_text.clear()
            return

        item = self.table.item(selected[0].row(), 0)
        model = item.data(Qt.ItemDataRole.UserRole)

        # Build info text
        name_display = model.get("name", model["filename"])
        if model.get("recommended"):
            name_display = f"⭐ {name_display} (Recommended)"

        info_lines = [
            f"<b>{name_display}</b>",
            "",
            f"<b>Filename:</b> {model['filename']}",
            f"<b>Type:</b> {model.get('type', 'Unknown')}",
            f"<b>Quality Tier:</b> {model.get('quality_tier', 'C-Tier')}",
            f"<b>Stems:</b> {model.get('stems', 'Unknown')}",
        ]

        if model.get("sdr_vocals"):
            info_lines.append(f"<b>Vocal SDR:</b> {model['sdr_vocals']:.1f} dB")
        if model.get("sdr_instrumental"):
            info_lines.append(
                f"<b>Instrumental SDR:</b> {model['sdr_instrumental']:.1f} dB"
            )

        # Add use cases
        use_cases = model.get("use_cases", [])
        if use_cases:
            info_lines.append(f"<b>Best For:</b> {', '.join(use_cases)}")

        if model.get("description"):
            info_lines.append("")
            info_lines.append(f"<b>Description:</b> {model['description']}")

        self.info_text.setHtml("<br>".join(info_lines))

    def _download_model(self, model: dict):
        """Download a model."""
        if self.download_thread and self.download_thread.isRunning():
            QMessageBox.warning(
                self,
                "Download in Progress",
                "Please wait for the current download to complete.",
            )
            return

        # Confirm download
        reply = QMessageBox.question(
            self,
            "Download Model",
            f"Download {model['name']}?\n\nFilename: {model['filename']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Start download
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"Downloading {model['filename']}...")
        self.progress_label.setVisible(True)
        self.refresh_btn.setEnabled(False)

        self.download_thread = ModelDownloadThread(model, self.model_dir)
        self.download_thread.progress.connect(self._on_download_progress)
        self.download_thread.finished.connect(self._on_download_finished)
        self.download_thread.start()

    def _on_download_progress(self, percent: int, message: str):
        """Handle download progress updates."""
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def _on_download_finished(
        self,
        success: bool,
        error_message: str = "",
        downloaded_model: dict | None = None,
    ):
        """Handle download completion."""
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.refresh_btn.setEnabled(True)

        if success:
            print(
                f"[Model Manager] Download successful: {downloaded_model.get('filename')}"
            )

            # Update installed models JSON with the new model
            installed = get_installed_models(self.model_dir)
            print(f"[Model Manager] Current installed models: {len(installed)}")

            # Add the downloaded model if not already in the list
            model_filename = downloaded_model["filename"]
            if not any(m["filename"] == model_filename for m in installed):
                installed.append(downloaded_model)
                print(f"[Model Manager] Adding {model_filename} to installed list")

                # Save to JSON
                from vsg_core.analysis.source_separation import (
                    update_installed_models_json,
                )

                if update_installed_models_json(installed, self.model_dir):
                    print("[Model Manager] Successfully updated installed_models.json")
                else:
                    print(
                        "[Model Manager] WARNING: Failed to update installed_models.json"
                    )
            else:
                print(
                    f"[Model Manager] Model {model_filename} already in installed list"
                )

            # Reload the model list to show the model as installed
            self._load_models()

            QMessageBox.information(
                self,
                "Success",
                f"Model downloaded successfully!\n\n{downloaded_model['name']}",
            )
        # Show detailed error message
        elif error_message and "not installed" in error_message.lower():
            # audio-separator not installed - show helpful message
            QMessageBox.critical(
                self,
                "audio-separator Not Installed",
                "audio-separator is not installed.\n\n"
                "To download models, you need to install audio-separator first:\n\n"
                "1. Open a terminal/command prompt\n"
                "2. Run one of these commands:\n\n"
                "   pip install audio-separator\n\n"
                "   OR for GPU support:\n\n"
                "   pip install 'audio-separator[gpu]'\n\n"
                "After installing, restart this application and try again.",
            )
        else:
            # Generic error
            error_text = "Failed to download model."
            if error_message:
                error_text += f"\n\n{error_message}"
            else:
                error_text += "\n\nCheck the terminal/console for details."
            QMessageBox.critical(self, "Download Error", error_text)

    def _delete_model(self, model: dict):
        """Delete an installed model."""
        reply = QMessageBox.question(
            self,
            "Delete Model",
            f"Delete {model['name']}?\n\nThis will remove the model file from disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Find and delete the model file
        model_path = Path(self.model_dir) / model["filename"]
        try:
            if model_path.exists():
                model_path.unlink()

            # Update JSON
            installed = get_installed_models(self.model_dir)
            installed = [m for m in installed if m["filename"] != model["filename"]]
            update_installed_models_json(installed, self.model_dir)

            QMessageBox.information(self, "Success", "Model deleted successfully!")
            self._load_models()

        except OSError as e:
            QMessageBox.critical(self, "Error", f"Failed to delete model: {e}")
