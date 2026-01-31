# vsg_qt/add_job_dialog/ui.py
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vsg_core.job_discovery import discover_jobs


class SourceInputWidget(QWidget):
    """A self-contained widget for a single source input row that handles drag-and-drop."""
    def __init__(self, source_num: int, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)

        label_text = f"Source {source_num} (Reference):" if source_num == 1 else f"Source {source_num}:"
        label = QLabel(label_text)
        self.line_edit = QLineEdit()
        browse_btn = QPushButton("Browse…")

        browse_btn.clicked.connect(self._browse_for_path)

        layout.addWidget(label, 1)
        layout.addWidget(self.line_edit, 4)
        layout.addWidget(browse_btn)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # Use the path of the first dropped file
            path = event.mimeData().urls()[0].toLocalFile()
            self.line_edit.setText(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _browse_for_path(self):
        dialog = QFileDialog(self, "Select Source")
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        if dialog.exec():
            self.line_edit.setText(dialog.selectedFiles()[0])

    def text(self) -> str:
        return self.line_edit.text()

class AddJobDialog(QDialog):
    """
    A dialog for dynamically adding sources to discover jobs.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Job(s) to Queue")
        self.setMinimumSize(700, 300)

        self.discovered_jobs: list[dict] = []
        self.source_widgets: list[SourceInputWidget] = []
        self._build_ui()

        # Start with 2 sources by default
        self.add_source_input()
        self.add_source_input()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        self.inputs_layout = QVBoxLayout(container)
        scroll_area.setWidget(container)

        layout.addWidget(scroll_area)

        add_source_btn = QPushButton("Add Another Source")
        add_source_btn.clicked.connect(self.add_source_input)
        layout.addWidget(add_source_btn)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        ok_button.setText("Find & Add Jobs")

        ok_button.clicked.connect(self.find_and_accept)
        dialog_btns.rejected.connect(self.reject)

        layout.addWidget(dialog_btns)

    def add_source_input(self):
        """Adds a new SourceInputWidget to the dialog."""
        source_num = len(self.source_widgets) + 1
        source_widget = SourceInputWidget(source_num)
        self.source_widgets.append(source_widget)
        self.inputs_layout.addWidget(source_widget)

    def populate_sources_from_paths(self, paths: list[str]):
        """Pre-fills the source inputs from a list of paths."""
        # Clear any default inputs
        while self.inputs_layout.count():
            child = self.inputs_layout.takeAt(0)
            if child and child.widget():
                child.widget().deleteLater()
        self.source_widgets.clear()

        # Add an input for each dropped path
        for path in paths:
            self.add_source_input()
            self.source_widgets[-1].line_edit.setText(path)

        # Ensure at least two inputs exist if user drops only one file
        if len(self.source_widgets) < 2:
            self.add_source_input()

    def find_and_accept(self):
        """Discover jobs from paths and accept the dialog if any are found."""
        sources: dict[str, str] = {}
        for i, source_widget in enumerate(self.source_widgets):
            path = source_widget.text().strip()
            if path:
                sources[f"Source {i+1}"] = path

        if "Source 1" not in sources:
            QMessageBox.warning(self, "Input Required", "Source 1 (Reference) cannot be empty.")
            return

        try:
            self.discovered_jobs = discover_jobs(sources)
            if not self.discovered_jobs:
                QMessageBox.information(self, "No Jobs Found", "No matching jobs could be discovered from the provided paths.")
                return

            self.accept()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.critical(self, "Error Discovering Jobs", str(e))

    def get_discovered_jobs(self) -> list[dict]:
        return self.discovered_jobs
