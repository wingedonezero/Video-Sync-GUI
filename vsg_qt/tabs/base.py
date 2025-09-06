# vsg_qt/tabs/base.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List, Type
from PySide6.QtWidgets import QWidget

class TabBase:
    """
    Base class every settings tab should inherit.
    """
    title: str = "Tab"

    def __init__(self, config, parent=None):
        self.config = config
        self._widget = None  # lazy-built QWidget

    def build(self, parent=None) -> QWidget:
        """
        Build and return the tab widget. Called once.
        """
        raise NotImplementedError

    def widget(self) -> QWidget:
        if self._widget is None:
            self._widget = self.build()
        return self._widget

    def load(self):
        """
        Pull values from config into UI controls.
        """
        raise NotImplementedError

    def save(self):
        """
        Push values from UI controls back into config.
        """
        raise NotImplementedError


# ---- Registry --------------------------------------------------------------

class _TabRegistry:
    def __init__(self):
        self._items: List[Type[TabBase]] = []

    def register(self, cls: Type[TabBase]):
        if cls not in self._items:
            self._items.append(cls)
        return cls

    def all(self) -> List[Type[TabBase]]:
        return list(self._items)


registry = _TabRegistry()
register_tab = registry.register
