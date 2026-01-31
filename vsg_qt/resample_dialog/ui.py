# vsg_qt/resample_dialog/ui.py
import json
import shutil

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from vsg_core.io.runner import CommandRunner


class ResampleDialog(QDialog):
    """A dialog for resampling subtitle PlayResX/Y values."""

    def __init__(self, current_x: int, current_y: int, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resample Resolution")
        self.video_path = video_path

        self.src_x = QLabel(str(current_x))
        self.src_y = QLabel(str(current_y))

        self.dest_x = QSpinBox()
        self.dest_x.setRange(1, 9999)
        self.dest_x.setValue(current_x)
        self.dest_y = QSpinBox()
        self.dest_y.setRange(1, 9999)
        self.dest_y.setValue(current_y)

        # Layout
        main_layout = QVBoxLayout(self)

        src_group = QGroupBox("Source Resolution (from Script)")
        src_form = QFormLayout(src_group)
        src_form.addRow("Width (X):", self.src_x)
        src_form.addRow("Height (Y):", self.src_y)

        dest_group = QGroupBox("Destination Resolution")
        dest_form = QFormLayout(dest_group)
        dest_form.addRow("Width (X):", self.dest_x)
        dest_form.addRow("Height (Y):", self.dest_y)

        from_video_btn = QPushButton("From Video")
        from_video_btn.clicked.connect(self._probe_video_resolution)
        dest_form.addRow(from_video_btn)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        main_layout.addWidget(src_group)
        main_layout.addWidget(dest_group)
        main_layout.addWidget(button_box)

    def _probe_video_resolution(self):
        """Runs ffprobe to get the video dimensions and updates the destination fields."""
        # This uses a dummy config and log callback for a one-off command
        runner = CommandRunner({}, lambda msg: print(f"[ffprobe] {msg}"))
        tool_paths = {"ffprobe": shutil.which("ffprobe")}

        if not tool_paths["ffprobe"]:
            print("ffprobe not found in PATH")
            return

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            self.video_path,
        ]

        output = runner.run(cmd, tool_paths)
        if output:
            try:
                data = json.loads(output)
                stream = data["streams"][0]
                self.dest_x.setValue(int(stream["width"]))
                self.dest_y.setValue(int(stream["height"]))
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                print(f"Error parsing ffprobe output: {e}")

    def get_resolution(self) -> tuple[int, int]:
        """Returns the new destination resolution chosen by the user."""
        return self.dest_x.value(), self.dest_y.value()
