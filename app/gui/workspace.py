"""Recursive split container hosting a tree of `GraphPanel` leaves.

Layout model (VS Code-ish but deliberately simple):

- A workspace is a tree whose internal nodes are `QSplitter`s (horizontal
  = side-by-side, vertical = stacked) and whose leaves are `GraphPanel`s.
- Splitting a panel places a fresh empty panel either as a sibling within
  the panel's current splitter (when that splitter already has the
  requested orientation) or inside a brand-new nested splitter.
- Closing a panel removes it and unwraps single-child splitters so the
  tree never keeps useless nesting. The last remaining panel cannot be
  closed.
- Divider dragging (resizing) is native `QSplitter` behavior.

Panels never talk to the workspace directly - they emit generic signals
(splitRequested/closeRequested/activated) that the workspace connects when
it creates them. That keeps `GraphPanel` reusable and this module the only
place that knows about tree structure.
"""
from __future__ import annotations

from typing import Iterator, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from models.signal_config import SignalConfig
from gui.graph_panel import GraphPanel


class Workspace(QWidget):
    panelAdded = Signal(object)          # GraphPanel
    panelRemoved = Signal(object)        # GraphPanel
    activePanelChanged = Signal(object)  # GraphPanel

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._root_splitter = QSplitter(Qt.Horizontal, self)
        layout.addWidget(self._root_splitter)

        self._active: Optional[GraphPanel] = None
        self.add_panel()

    # -- enumeration ----------------------------------------------------------
    def panels(self) -> List[GraphPanel]:
        return list(self._iter_panels(self._root_splitter))

    def count_panels(self) -> int:
        return sum(1 for _ in self._iter_panels(self._root_splitter))

    def _iter_panels(self, splitter: QSplitter) -> Iterator[GraphPanel]:
        for i in range(splitter.count()):
            child = splitter.widget(i)
            if isinstance(child, GraphPanel):
                yield child
            elif isinstance(child, QSplitter):
                yield from self._iter_panels(child)

    # -- active panel ----------------------------------------------------------
    def active_panel(self) -> Optional[GraphPanel]:
        active = self._active
        if active is None or active not in self.panels():
            panels = self.panels()
            return panels[0] if panels else None
        return active

    def set_active_panel(self, panel: GraphPanel) -> None:
        if panel is self._active:
            return
        self._active = panel
        self.activePanelChanged.emit(panel)

    # -- structural operations ---------------------------------------------------
    def add_panel(self, signals: Optional[List[SignalConfig]] = None) -> GraphPanel:
        panel = self._create_panel()
        self._root_splitter.addWidget(panel)
        if signals:
            panel.set_signals(signals)
        self.set_active_panel(panel)
        self._update_close_enabled()
        return panel

    def split_panel(self, panel: GraphPanel, orientation: Qt.Orientation) -> Optional[GraphPanel]:
        """Split `panel` by placing a new sibling panel next to it."""
        if panel not in self.panels():
            return None

        container = self._container_of(panel) or self._root_splitter
        new_panel = self._create_panel()

        if container.orientation() == orientation:
            idx = container.indexOf(panel)
            container.insertWidget(idx + 1, new_panel)
        else:
            idx = container.indexOf(panel)
            new_splitter = QSplitter(orientation)
            container.removeWidget(panel)
            new_splitter.addWidget(panel)
            new_splitter.addWidget(new_panel)
            container.insertWidget(idx, new_splitter)

        self.set_active_panel(new_panel)
        self._update_close_enabled()
        return new_panel

    def close_panel(self, panel: GraphPanel) -> bool:
        """Remove a panel. Refuses to remove the last remaining one."""
        if self.count_panels() <= 1:
            return False
        self._remove_panel(panel)
        return True

    def rebuild(self, panels_signals: List[List[SignalConfig]]) -> None:
        """Replace every panel with a fresh set, seeding each with the given
        per-panel signal lists. At least one panel always remains."""
        for panel in self.panels():
            self._remove_panel(panel)

        seeds = panels_signals if panels_signals else [[]]
        for signals in seeds:
            self.add_panel(signals or [])

    # -- internals ---------------------------------------------------------------
    def _create_panel(self) -> GraphPanel:
        panel = GraphPanel(self)
        panel.splitRequested.connect(
            lambda orientation, p=panel: self.split_panel(p, orientation)
        )
        panel.closeRequested.connect(lambda p=panel: self.close_panel(p))
        panel.activated.connect(lambda p=panel: self.set_active_panel(p))
        self.panelAdded.emit(panel)
        return panel

    @staticmethod
    def _container_of(panel: GraphPanel) -> Optional[QSplitter]:
        parent = panel.parentWidget()
        return parent if isinstance(parent, QSplitter) else None

    def _remove_panel(self, panel: GraphPanel) -> None:
        container = self._container_of(panel)
        if container is not None:
            container.removeWidget(panel)
        panel.deleteLater()
        self.panelRemoved.emit(panel)
        if container is not None:
            self._collapse_if_needed(container)
        if self._active is panel:
            self._active = None
        self._update_close_enabled()

    def _collapse_if_needed(self, container: QSplitter) -> None:
        """If a splitter is down to one child, splice that child up into the
        parent (or leave it alone when it is the root splitter)."""
        if container.count() != 1:
            return
        grand = container.parentWidget()
        if not isinstance(grand, QSplitter):
            return  # root splitter: a single child is fine
        gi = grand.indexOf(container)
        child = container.widget(0)
        container.removeWidget(child)
        container.deleteLater()
        grand.insertWidget(gi, child)

    def _update_close_enabled(self) -> None:
        can_close = self.count_panels() > 1
        for panel in self.panels():
            panel.set_can_close(can_close)
