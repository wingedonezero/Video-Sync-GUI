# vsg_qt/style_editor_dialog/video_widget.py
# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPixmap
from PySide6.QtWidgets import QWidget

class VideoWidget(QWidget):
    """A custom widget for displaying video frames via a paintEvent."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self._pixmap = None

    def set_pixmap(self, pixmap: QPixmap):
        """Receives a new pixmap and schedules a repaint."""
        self._pixmap = pixmap
        self.update() # Trigger the paintEvent

    def paintEvent(self, event):
        """Handles all drawing for the widget."""
        painter = QPainter(self)

        # 1. Fill the background with black
        painter.fillRect(self.rect(), QColor('black'))

        if self._pixmap:
            # 2. Scale the pixmap to fit while maintaining aspect ratio
            scaled_pixmap = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )

            # 3. Center the scaled pixmap and draw it
            centered_rect = QRect(
                (self.width() - scaled_pixmap.width()) // 2,
                (self.height() - scaled_pixmap.height()) // 2,
                scaled_pixmap.width(),
                scaled_pixmap.height()
            )
            painter.drawPixmap(centered_rect, scaled_pixmap)
