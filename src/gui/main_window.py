# src/gui/main_window.py

import sys
import os
import time
import json
import re
import traceback
import numpy as np
import polars as pl
from PySide6.QtWidgets import (QApplication, QMainWindow, QSplitter, 
                               QTreeView, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QMenu, QTabWidget, QFileDialog,
                               QMessageBox, QComboBox, QColorDialog, QFrame,
                               QLineEdit, QMenuBar, QStackedWidget, QInputDialog, QAbstractItemView,
                               QListWidget, QListWidgetItem, QDialog, QPlainTextEdit, QTextEdit, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QHeaderView)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QFont, QBrush, QColor, QDrag, QClipboard, QPixmap, QIcon, QPainter, QCursor, QVector3D
from PySide6.QtCore import Qt, Signal, QMimeData, QTimer, QEvent, QModelIndex, QUrl, QItemSelectionModel
import pyqtgraph as pg
import math
import inspect
try:
    import pyqtgraph.opengl as gl
except Exception:
    gl = None

# Performance optimization: disable antialiasing for faster rendering
pg.setConfigOptions(antialias=False) 

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)
if src_dir not in sys.path:
    sys.path.append(src_dir)

from engines.io_engine import LogIOEngine
from gui.color_manager import ColorManager
from core.log_model import TopicInstance, Signal as LogSignal

try:
    from analysis.detector import FlightTypeDetector
except ImportError:
    FlightTypeDetector = None

class FileDropWidget(QLabel):
    filesDropped = Signal(list) 

    def __init__(self):
        super().__init__()
        self.setText("Date(ulg) Upload\n(Multiple choices available)")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True) 
        self.apply_theme(is_dark=True) 

    def apply_theme(self, is_dark):
        if is_dark:
            self.setStyleSheet("""
                QLabel { background-color: #2b2b2b; color: #aaaaaa; border: 2px dashed #555555; border-radius: 5px; padding: 8px; font-weight: bold; }
                QLabel:hover { background-color: #3b3b3b; border-color: #1A2D57; color: white; }
            """)
        else:
            self.setStyleSheet("""
                QLabel { background-color: #f0f0f0; color: #555555; border: 2px dashed #cccccc; border-radius: 5px; padding: 8px; font-weight: bold; }
                QLabel:hover { background-color: #e0e0e0; border-color: #1A2D57; color: black; }
            """)

    def dragEnterEvent(self, event):
        # Accept drag entry first; validate exact .ulg paths on drop.
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.setText("📥 여기에 ULG 파일을 놓아주세요")

    def dragMoveEvent(self, event):
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dropEvent(self, event):
        valid_files = self._extract_ulg_files(event.mimeData())
        self.setText("📥 ULG 파일 업로드\n(클릭 또는 드래그 앤 드롭, 다중 선택 가능)")
        if valid_files:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.filesDropped.emit(valid_files)
        else:
            event.ignore()
            self.setText("ULG 파일만 지원합니다.")
            try:
                mime_data = event.mimeData()
                formats = ", ".join(mime_data.formats()) if mime_data else ""
                sample_text = (mime_data.text() or "").strip()[:160] if mime_data else ""
                print(f"[DND][FileDropWidget] no .ulg extracted | formats=[{formats}] | text='{sample_text}'")
            except Exception:
                pass

    def mousePressEvent(self, event):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "ULG 파일 선택", "", "ULG Files (*.ulg)")
        if file_paths: self.filesDropped.emit(file_paths)

    @staticmethod
    def _extract_ulg_files(mime_data):
        if not mime_data:
            return []

        candidates = []

        if mime_data.hasUrls():
            for url in mime_data.urls():
                local_path = url.toLocalFile()
                if not local_path:
                    raw_url = (url.toString(QUrl.FullyDecoded) or "").strip()
                    if raw_url.lower().startswith("file://"):
                        local_path = QUrl(raw_url).toLocalFile()
                    elif raw_url:
                        local_path = raw_url
                if local_path:
                    candidates.append(local_path)

        if mime_data.hasText():
            for raw_line in (mime_data.text() or "").splitlines():
                line = raw_line.strip().strip('"').strip("'")
                if not line:
                    continue
                if line.lower().startswith("file://"):
                    as_local = QUrl(line).toLocalFile()
                    if as_local:
                        line = as_local
                candidates.append(line)

        # Windows Explorer fallback: parse native filename MIME payload.
        for fmt in mime_data.formats():
            if "FileNameW" not in fmt and "FileName" not in fmt:
                continue
            raw = bytes(mime_data.data(fmt))
            if not raw:
                continue
            decoded = ""
            try:
                decoded = raw.decode("utf-16le", errors="ignore")
            except Exception:
                try:
                    decoded = raw.decode("utf-8", errors="ignore")
                except Exception:
                    decoded = ""
            if not decoded:
                continue
            for piece in re.split(r"\x00+", decoded):
                p = piece.strip().strip('"').strip("'")
                if not p:
                    continue
                if p.lower().startswith("file://"):
                    as_local = QUrl(p).toLocalFile()
                    if as_local:
                        p = as_local
                candidates.append(p)

        valid_files = []
        for path in candidates:
            norm_path = os.path.normpath(path.strip())
            # Some drag sources provide '/C:/path/file.ulg' form on Windows.
            if re.match(r"^/[A-Za-z]:[\\/]", norm_path):
                norm_path = norm_path[1:]
            if os.path.splitext(norm_path)[1].lower() == ".ulg":
                valid_files.append(norm_path)

        # Keep order while removing duplicates.
        return list(dict.fromkeys(valid_files))

    @staticmethod
    def _has_file_like_payload(mime_data):
        if not mime_data:
            return False
        if mime_data.hasUrls():
            return True
        if any(("FileNameW" in fmt or "FileName" in fmt) for fmt in mime_data.formats()):
            return True
        if FileDropWidget._extract_ulg_files(mime_data):
            return True
        if mime_data.hasText():
            sample = (mime_data.text() or "").lower()
            if ".ulg" in sample and ("file://" in sample or "\\" in sample or "/" in sample):
                return True
        return False

class DraggableTreeView(QTreeView):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._drag_start_pos = None
        self._drag_start_index = QModelIndex()
        self._drag_start_button = Qt.NoButton
        self._last_drag_was_right = False
        self._pending_ignore_drop_uris = None
        self._pending_ignore_drop_retries = 0

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            point = event.position().toPoint()
            self._drag_start_pos = point
            self._drag_start_index = self.indexAt(point)
            self._drag_start_button = event.button()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & (Qt.LeftButton | Qt.RightButton)):
            super().mouseMoveEvent(event)
            return
        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return
        point = event.position().toPoint()
        if (point - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        if not self._drag_start_index.isValid():
            self._drag_start_index = self.currentIndex()
            if not self._drag_start_index.isValid():
                selected = self.selectionModel().selectedRows(0)
                if selected:
                    self._drag_start_index = selected[0]
            if not self._drag_start_index.isValid():
                super().mouseMoveEvent(event)
                return

        if not self.selectionModel().isSelected(self._drag_start_index):
            self.selectionModel().select(
                self._drag_start_index,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
            )
            self.setCurrentIndex(self._drag_start_index)

        if event.buttons() & Qt.RightButton:
            self._drag_start_button = Qt.RightButton
        elif event.buttons() & Qt.LeftButton:
            self._drag_start_button = Qt.LeftButton

        self.startDrag(Qt.CopyAction)
        self._drag_start_pos = None
        self._drag_start_index = QModelIndex()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._drag_start_pos = None
            self._drag_start_index = QModelIndex()
            self._drag_start_button = Qt.NoButton
            if self._pending_ignore_drop_uris:
                QTimer.singleShot(0, self._flush_pending_ignore_drop)
        super().mouseReleaseEvent(event)

    def startDrag(self, supportedActions):
        indexes = self.selectionModel().selectedRows(0)
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        if not indexes:
            print("[DND][Tree] startDrag: no selection")
            return

        uris = []
        seen = set()
        for index in indexes:
            item = self.model().itemFromIndex(index)
            if not item or not item.parent() or not item.parent().parent():
                continue

            signal_name = item.text()
            topic_name = item.parent().text()
            file_item = item.parent().parent()
            file_name = file_item.data(Qt.UserRole)
            if not file_name:
                display_text = file_item.text()
                if " | Aircraft :" in display_text:
                    display_text = display_text.split(" | Aircraft :", 1)[0]
                if display_text.startswith("[DIR] "):
                    display_text = display_text[6:]
                elif display_text.startswith("[FILE] "):
                    display_text = display_text[7:]
                file_name = display_text.strip()
            if not file_name:
                continue

            uri = f"{file_name}|{topic_name}|{signal_name}"
            if uri not in seen:
                seen.add(uri)
                uris.append(uri)

        if not uris:
            print("[DND][Tree] startDrag: no valid signal URI")
            return
        
        mimeData = QMimeData()
        joined = "\n".join(uris)
        mimeData.setText(joined)
        mimeData.setData("application/x-px4-signal-list", joined.encode("utf-8"))
        drag_origin = b"right" if self._drag_start_button == Qt.RightButton else b"left"
        self._last_drag_was_right = (drag_origin == b"right")
        mimeData.setData("application/x-px4-drag-origin", drag_origin)
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag_pix = self._build_drag_pixmap(len(uris))
        drag.setPixmap(drag_pix)
        drag.setHotSpot(drag_pix.rect().center())
        drag.setDragCursor(drag_pix, Qt.CopyAction)
        print(f"[DND][Tree] startDrag: {len(uris)} signal(s) origin={drag_origin.decode('utf-8')}")
        result = drag.exec(Qt.CopyAction)
        print(f"[DND][Tree] drag result: {result}")
        if result == Qt.IgnoreAction:
            self._pending_ignore_drop_uris = list(uris)
            self._pending_ignore_drop_retries = 0
            self._flush_pending_ignore_drop()
        else:
            self._pending_ignore_drop_uris = None
            self._pending_ignore_drop_retries = 0

    @staticmethod
    def _build_drag_pixmap(count):
        text = f"+ {count} signal(s)"
        pix = QPixmap(120, 26)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(26, 45, 87, 220))
        painter.drawRoundedRect(0, 0, 119, 25, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(pix.rect(), Qt.AlignCenter, text)
        painter.end()
        return pix

    def _flush_pending_ignore_drop(self):
        if not self._pending_ignore_drop_uris:
            return
        if QApplication.mouseButtons() & Qt.LeftButton:
            self._pending_ignore_drop_retries += 1
            if self._pending_ignore_drop_retries < 40:
                QTimer.singleShot(15, self._flush_pending_ignore_drop)
            return

        uris = self._pending_ignore_drop_uris
        self._pending_ignore_drop_uris = None
        self._pending_ignore_drop_retries = 0

        main_window = self.window()
        if main_window and hasattr(main_window, "handle_signal_drop_from_cursor"):
            rendered = main_window.handle_signal_drop_from_cursor(
                uris,
                QCursor.pos(),
                strict_target=False,
                prefer_curve_popup=self._last_drag_was_right,
            )
            print(f"[DND][Tree] release-drop fallback rendered={rendered} uris={len(uris)}")

def _parse_signal_uri_text(uri_text):
    parts = [p.strip() for p in str(uri_text).split("|")]
    if len(parts) < 3:
        return None
    file_name, topic_name, signal_name = parts[:3]
    x_axis_col = parts[3] if len(parts) > 3 and parts[3] else "timestamp_sec"
    return file_name, topic_name, signal_name, x_axis_col

def _format_signal_uri_label(uri_text):
    parsed = _parse_signal_uri_text(uri_text)
    if not parsed:
        return str(uri_text)
    file_name, topic_name, signal_name, _ = parsed
    short_file = file_name[:20] + ".." if len(file_name) > 22 else file_name
    return f"[{short_file}] {topic_name}.{signal_name}"

class PathCurveCreateDialog(QDialog):
    """Popup for mapping dropped series to XY/XYZ path axes."""
    def __init__(self, parent, uri_list):
        super().__init__(parent)
        self.setWindowTitle("New XY/XYZ Curve")
        self.resize(560, 240)
        self.setStyleSheet("""
            QDialog { background-color: #efefef; }
            QLabel { color: #000000; border: none; padding: 0px; }
            QLineEdit, QComboBox {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #a4adb7;
                padding: 2px 4px;
                min-height: 22px;
            }
            QPushButton {
                color: #000000;
                min-height: 24px;
                padding: 2px 10px;
            }
        """)
        self._name_touched = False
        self._result = None
        self._uris = list(dict.fromkeys([str(u).strip() for u in uri_list if str(u).strip()]))

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Curve Type"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("XY (2D Path)", "xy")
        if len(self._uris) >= 3:
            self.cmb_mode.addItem("XYZ (3D Path)", "xyz")
            self.cmb_mode.setCurrentIndex(1)
        top_row.addWidget(self.cmb_mode, 1)
        root.addLayout(top_row)

        self.row_x = QHBoxLayout()
        self.row_x.addWidget(QLabel("X"))
        self.cmb_x = QComboBox()
        self.row_x.addWidget(self.cmb_x, 1)
        root.addLayout(self.row_x)

        self.row_y = QHBoxLayout()
        self.row_y.addWidget(QLabel("Y"))
        self.cmb_y = QComboBox()
        self.row_y.addWidget(self.cmb_y, 1)
        self.btn_swap_xy = QPushButton("Swap X/Y")
        self.btn_swap_xy.clicked.connect(self._swap_xy)
        self.row_y.addWidget(self.btn_swap_xy)
        root.addLayout(self.row_y)

        self.row_z = QHBoxLayout()
        self.lbl_z = QLabel("Z")
        self.row_z.addWidget(self.lbl_z)
        self.cmb_z = QComboBox()
        self.row_z.addWidget(self.cmb_z, 1)
        root.addLayout(self.row_z)

        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Name"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("Curve name")
        self.ed_name.textEdited.connect(lambda _t: setattr(self, "_name_touched", True))
        row_name.addWidget(self.ed_name, 1)
        root.addLayout(row_name)

        info = QLabel("드롭한 시계열을 축에 매핑한 뒤 OK를 누르면 Path가 생성됩니다.")
        info.setStyleSheet("color: #5f6f82;")
        root.addWidget(info)

        for uri in self._uris:
            label = _format_signal_uri_label(uri)
            self.cmb_x.addItem(label, uri)
            self.cmb_y.addItem(label, uri)
            self.cmb_z.addItem(label, uri)

        if self.cmb_y.count() > 1:
            self.cmb_y.setCurrentIndex(1)
        if self.cmb_z.count() > 2:
            self.cmb_z.setCurrentIndex(2)

        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.cmb_x.currentIndexChanged.connect(self._update_default_name)
        self.cmb_y.currentIndexChanged.connect(self._update_default_name)
        self.cmb_z.currentIndexChanged.connect(self._update_default_name)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self._accept_with_validation)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

        self._on_mode_changed()
        self._update_default_name()

    def _current_mode(self):
        return str(self.cmb_mode.currentData() or "xy")

    def _swap_xy(self):
        x_idx = self.cmb_x.currentIndex()
        y_idx = self.cmb_y.currentIndex()
        self.cmb_x.setCurrentIndex(y_idx)
        self.cmb_y.setCurrentIndex(x_idx)

    def _on_mode_changed(self):
        xyz_mode = (self._current_mode() == "xyz")
        self.lbl_z.setVisible(xyz_mode)
        self.cmb_z.setVisible(xyz_mode)
        self._update_default_name()

    def _update_default_name(self):
        if self._name_touched:
            return
        x_uri = self.cmb_x.currentData()
        y_uri = self.cmb_y.currentData()
        z_uri = self.cmb_z.currentData()
        x_sig = _parse_signal_uri_text(x_uri)[2] if _parse_signal_uri_text(x_uri) else "x"
        y_sig = _parse_signal_uri_text(y_uri)[2] if _parse_signal_uri_text(y_uri) else "y"
        if self._current_mode() == "xyz":
            z_sig = _parse_signal_uri_text(z_uri)[2] if _parse_signal_uri_text(z_uri) else "z"
            self.ed_name.setText(f"Path [{x_sig}:{y_sig}:{z_sig}]")
        else:
            self.ed_name.setText(f"Path [{x_sig}:{y_sig}]")

    def _accept_with_validation(self):
        x_uri = str(self.cmb_x.currentData() or "").strip()
        y_uri = str(self.cmb_y.currentData() or "").strip()
        z_uri = str(self.cmb_z.currentData() or "").strip()
        mode = self._current_mode()
        name = self.ed_name.text().strip() or ("3D Flight Path" if mode == "xyz" else "2D Flight Path")

        if not x_uri or not y_uri:
            QMessageBox.warning(self, "Curve", "X/Y 신호를 선택해 주세요.")
            return
        if mode == "xy":
            if x_uri == y_uri:
                QMessageBox.warning(self, "Curve", "X와 Y는 서로 다른 신호여야 합니다.")
                return
        else:
            if not z_uri:
                QMessageBox.warning(self, "Curve", "XYZ 모드에서는 Z 신호가 필요합니다.")
                return
            if len({x_uri, y_uri, z_uri}) < 3:
                QMessageBox.warning(self, "Curve", "X/Y/Z는 서로 다른 신호여야 합니다.")
                return

        self._result = {
            "mode": mode,
            "x_uri": x_uri,
            "y_uri": y_uri,
            "z_uri": z_uri if mode == "xyz" else "",
            "name": name,
        }
        self.accept()

    def result_data(self):
        return self._result

class LogInfoCompareDialog(QDialog):
    """Compare firmware / parameters / messages across multiple loaded logs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Metadata Compare")
        self.resize(1180, 720)
        self._max_message_rows = 300
        self._uniform_col_min_px = 240

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.header_label = QLabel("업로드된 로그의 메타정보 비교")
        self.header_label.setStyleSheet("font-weight: 700; color: #1f2b36;")
        root.addWidget(self.header_label)

        self.tabs = QTabWidget()
        self.tbl_firmware = self._create_table()
        self.tbl_params = self._create_table()
        self.tbl_messages = self._create_table()
        self.tabs.addTab(self.tbl_firmware, "Firmware Info")
        self.tabs.addTab(self.tbl_params, "Parameters")
        self.tabs.addTab(self.tbl_messages, "Messages")
        root.addWidget(self.tabs, 1)

        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet("color: #5f6f82; font-size: 11px;")
        root.addWidget(self.footer_label)

    @staticmethod
    def _create_table():
        table = QTableWidget(0, 0)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setDefaultSectionSize(22)
        h = table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Fixed)
        h.setStretchLastSection(False)
        return table

    @staticmethod
    def _value_to_text(value):
        if value is None:
            return ""
        try:
            text = str(value)
        except Exception:
            text = repr(value)
        return text.replace("\n", " ").strip()

    def _populate_dict_table(self, table, file_names, metadata_map, key_name):
        row_keys = set()
        for file_name in file_names:
            sec = metadata_map.get(file_name, {}).get(key_name, {})
            if isinstance(sec, dict):
                row_keys.update([str(k) for k in sec.keys()])
        row_list = sorted(row_keys, key=lambda x: x.lower())

        table.clear()
        table.setColumnCount(len(file_names))
        table.setRowCount(len(row_list))
        table.setHorizontalHeaderLabels(file_names)
        table.setVerticalHeaderLabels(row_list)

        for row, k in enumerate(row_list):
            for col, file_name in enumerate(file_names):
                sec = metadata_map.get(file_name, {}).get(key_name, {})
                val = ""
                if isinstance(sec, dict):
                    val = self._value_to_text(sec.get(k, ""))
                table.setItem(row, col, QTableWidgetItem(val))

    def _apply_uniform_column_widths(self, table):
        col_count = table.columnCount()
        if col_count <= 0:
            return
        viewport_w = max(1, int(table.viewport().width()))
        target_w = max(self._uniform_col_min_px, int(viewport_w / col_count))
        for col in range(col_count):
            table.setColumnWidth(col, target_w)

    def _highlight_parameter_differences(self):
        table = self.tbl_params
        rows = table.rowCount()
        cols = table.columnCount()
        if rows <= 0 or cols <= 1:
            return

        diff_bg = QBrush(QColor("#FFF3CD"))    # light amber
        diff_fg = QBrush(QColor("#8A4B00"))    # dark amber text
        normal_bg = QBrush(Qt.NoBrush)
        normal_fg = QBrush(QColor("#1f2b36"))

        for row in range(rows):
            values = []
            per_col = []
            for col in range(cols):
                item = table.item(row, col)
                txt = item.text().strip() if item is not None else ""
                per_col.append(txt)
                if txt != "":
                    values.append(txt)

            if len(values) <= 1:
                for col in range(cols):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    item.setBackground(normal_bg)
                    item.setForeground(normal_fg)
                    font = item.font()
                    font.setBold(False)
                    item.setFont(font)
                    item.setToolTip("")
                continue

            counts = {}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            baseline = max(counts.items(), key=lambda kv: kv[1])[0]
            row_has_diff = (len(counts) > 1)

            for col in range(cols):
                item = table.item(row, col)
                if item is None:
                    continue
                txt = per_col[col]
                if row_has_diff and txt != "" and txt != baseline:
                    item.setBackground(diff_bg)
                    item.setForeground(diff_fg)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setToolTip("다른 로그와 값이 다릅니다.")
                else:
                    item.setBackground(normal_bg)
                    item.setForeground(normal_fg)
                    font = item.font()
                    font.setBold(False)
                    item.setFont(font)
                    item.setToolTip("")

    def _populate_message_table(self, table, file_names, metadata_map):
        max_rows = 0
        msg_by_file = {}
        for file_name in file_names:
            raw_msgs = metadata_map.get(file_name, {}).get("messages", [])
            if not isinstance(raw_msgs, list):
                raw_msgs = []
            raw_msgs = raw_msgs[:self._max_message_rows]
            msg_by_file[file_name] = raw_msgs
            if len(raw_msgs) > max_rows:
                max_rows = len(raw_msgs)

        table.clear()
        table.setColumnCount(len(file_names))
        table.setRowCount(max_rows)
        table.setHorizontalHeaderLabels(file_names)
        table.setVerticalHeaderLabels([str(i + 1) for i in range(max_rows)])

        for col, file_name in enumerate(file_names):
            msgs = msg_by_file.get(file_name, [])
            for row in range(max_rows):
                text = ""
                if row < len(msgs):
                    msg = msgs[row]
                    if isinstance(msg, dict):
                        ts = self._value_to_text(msg.get("timestamp", ""))
                        level = self._value_to_text(msg.get("level", ""))
                        body = self._value_to_text(msg.get("text", ""))
                        prefix_parts = [p for p in (ts, level) if p]
                        prefix = f"[{' '.join(prefix_parts)}] " if prefix_parts else ""
                        text = f"{prefix}{body}".strip()
                    else:
                        text = self._value_to_text(msg)
                table.setItem(row, col, QTableWidgetItem(text))

    def update_data(self, metadata_map, active_file=None):
        if not isinstance(metadata_map, dict):
            metadata_map = {}
        file_names = list(metadata_map.keys())
        if active_file and active_file in file_names:
            file_names.remove(active_file)
            file_names.insert(0, active_file)

        if not file_names:
            self.header_label.setText("업로드된 로그가 없습니다.")
            self.footer_label.setText("")
            for table in (self.tbl_firmware, self.tbl_params, self.tbl_messages):
                table.clear()
                table.setRowCount(0)
                table.setColumnCount(0)
            return

        active_prefix = f"Active: {active_file}" if active_file else "Active: (none)"
        self.header_label.setText(f"업로드 로그 {len(file_names)}개 비교 | {active_prefix}")
        self._populate_dict_table(self.tbl_firmware, file_names, metadata_map, "firmware")
        self._populate_dict_table(self.tbl_params, file_names, metadata_map, "parameters")
        self._populate_message_table(self.tbl_messages, file_names, metadata_map)
        self._apply_uniform_column_widths(self.tbl_firmware)
        self._apply_uniform_column_widths(self.tbl_params)
        self._apply_uniform_column_widths(self.tbl_messages)
        self._highlight_parameter_differences()
        self.footer_label.setText(f"Messages 탭은 로그당 최대 {self._max_message_rows}행까지 표시합니다.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_uniform_column_widths(self.tbl_firmware)
        self._apply_uniform_column_widths(self.tbl_params)
        self._apply_uniform_column_widths(self.tbl_messages)

class SignalDropLineEdit(QLineEdit):
    signalChanged = Signal(str)

    def __init__(self, placeholder):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText(placeholder)
        self._signal_uri = ""

    def signal_uri(self):
        return self._signal_uri

    def set_signal_uri(self, uri_text):
        self._signal_uri = str(uri_text or "").strip()
        if self._signal_uri:
            self.setText(_format_signal_uri_label(self._signal_uri))
        else:
            self.clear()
        self.signalChanged.emit(self._signal_uri)

    def clear_signal_uri(self):
        self.set_signal_uri("")

    def dragEnterEvent(self, event):
        uris = AdvancedPlot._signal_uris_from_mime(event.mimeData())
        if uris:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        uris = AdvancedPlot._signal_uris_from_mime(event.mimeData())
        if uris:
            self.set_signal_uri(uris[0])
            event.acceptProposedAction()
            return
        super().dropEvent(event)

class CustomSeriesListWidget(QListWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setObjectName("customSeriesList")
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def startDrag(self, supportedActions):
        lines = []
        for item in self.selectedItems():
            info = item.data(Qt.UserRole)
            if not isinstance(info, dict):
                continue
            file_name = str(info.get("file_name", "")).strip()
            series_name = str(info.get("name", "")).strip()
            if not file_name or not series_name:
                continue
            lines.append(f"{file_name}|{self.main_window.CUSTOM_SERIES_TOPIC}|{series_name}|timestamp_sec")

        if not lines:
            return

        payload = "\n".join(lines)
        mime_data = QMimeData()
        mime_data.setText(payload)
        mime_data.setData("application/x-px4-signal-list", payload.encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag_pix = DraggableTreeView._build_drag_pixmap(len(lines))
        drag.setPixmap(drag_pix)
        drag.setHotSpot(drag_pix.rect().center())
        drag.setDragCursor(drag_pix, Qt.CopyAction)
        drag.exec(Qt.CopyAction)

class CustomSeriesEditorDialog(QDialog):
    def __init__(self, main_window, existing_spec=None):
        super().__init__(main_window)
        self.main_window = main_window
        self.existing_spec = existing_spec
        self.series_spec = None
        self.series_x = None
        self.series_y = None

        self.setWindowTitle("Custom Series Editor")
        self.resize(980, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setBackground("#f8f9fb")
        self.preview_plot.showGrid(x=True, y=True, alpha=0.25)
        self.preview_plot.setMinimumHeight(180)
        root.addWidget(self.preview_plot)

        top_grid = QVBoxLayout()

        row_file = QHBoxLayout()
        row_file.addWidget(QLabel("Dataset"))
        self.cmb_file = QComboBox()
        self.cmb_file.setObjectName("customSeriesFileCombo")
        self.cmb_file.currentTextChanged.connect(self._sync_file_for_fields)
        row_file.addWidget(self.cmb_file, 1)
        top_grid.addLayout(row_file)

        row_input = QHBoxLayout()
        row_input.addWidget(QLabel("Input timeseries"))
        self.ed_input = SignalDropLineEdit("Drop input signal (value)")
        self.ed_input.signalChanged.connect(lambda _u: self._sync_file_for_fields())
        row_input.addWidget(self.ed_input, 1)
        btn_clear_input = QPushButton("Clear")
        btn_clear_input.clicked.connect(self.ed_input.clear_signal_uri)
        row_input.addWidget(btn_clear_input)
        top_grid.addLayout(row_input)

        self.additional_fields = []
        for idx in range(1, 5):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"v{idx}"))
            ed = SignalDropLineEdit(f"Drop additional source for v{idx} (optional)")
            ed.signalChanged.connect(lambda _u, i=idx: self._sync_file_for_fields())
            row.addWidget(ed, 1)
            btn_clear = QPushButton("Clear")
            btn_clear.clicked.connect(ed.clear_signal_uri)
            row.addWidget(btn_clear)
            top_grid.addLayout(row)
            self.additional_fields.append(ed)

        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("New name"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("e.g. pitch_error, roll_deg, throttle_percent")
        row_name.addWidget(self.ed_name, 1)
        top_grid.addLayout(row_name)

        row_globals = QVBoxLayout()
        row_globals.addWidget(QLabel("Global variables"))
        self.ed_globals = QPlainTextEdit()
        self.ed_globals.setPlaceholderText("scale = 57.2958\noffset = 0.0")
        self.ed_globals.setFixedHeight(84)
        row_globals.addWidget(self.ed_globals)
        top_grid.addLayout(row_globals)

        root.addLayout(top_grid)

        lower_split = QHBoxLayout()
        lower_split.setSpacing(8)

        lib_col = QVBoxLayout()
        lib_col.addWidget(QLabel("Function library"))
        self.list_templates = QListWidget()
        self.list_templates.currentItemChanged.connect(self._on_template_selected)
        lib_col.addWidget(self.list_templates, 1)
        lib_col.addWidget(QLabel("Function preview"))
        self.tx_template_desc = QTextEdit()
        self.tx_template_desc.setReadOnly(True)
        self.tx_template_desc.setMinimumHeight(110)
        lib_col.addWidget(self.tx_template_desc)
        lower_split.addLayout(lib_col, 1)

        code_col = QVBoxLayout()
        code_col.addWidget(QLabel("Function editor"))
        self.ed_function = QPlainTextEdit()
        self.ed_function.setPlaceholderText(
            "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
            "    return value"
        )
        self.ed_function.setMinimumHeight(260)
        code_col.addWidget(self.ed_function, 1)
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #C62828; font-size: 11px;")
        code_col.addWidget(self.lbl_error)
        lower_split.addLayout(code_col, 2)

        root.addLayout(lower_split, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_preview = QPushButton("Preview")
        self.btn_create = QPushButton("Create New Time Series" if existing_spec is None else "Save Changes")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_create.clicked.connect(self._on_create)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_create)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

        self.templates = self.main_window._custom_series_templates()
        for temp in self.templates:
            item = QListWidgetItem(temp["name"])
            item.setData(Qt.UserRole, temp["id"])
            self.list_templates.addItem(item)

        self._populate_dataset_combo()
        self._apply_existing_or_default()

    def _set_error(self, msg):
        self.lbl_error.setText(msg or "")

    def _populate_dataset_combo(self):
        self.cmb_file.clear()
        for file_name in self.main_window.loaded_datasets.keys():
            self.cmb_file.addItem(file_name)

    def _find_template(self, template_id):
        for temp in self.templates:
            if temp["id"] == template_id:
                return temp
        return None

    def _apply_existing_or_default(self):
        if self.existing_spec:
            file_name = self.existing_spec.get("file_name", "")
            if file_name:
                idx = self.cmb_file.findText(file_name)
                if idx >= 0:
                    self.cmb_file.setCurrentIndex(idx)

            self.ed_name.setText(self.existing_spec.get("name", ""))
            self.ed_input.set_signal_uri(self.existing_spec.get("input_uri", ""))
            add_uris = self.existing_spec.get("additional_uris", [])
            for i, ed in enumerate(self.additional_fields):
                ed.set_signal_uri(add_uris[i] if i < len(add_uris) else "")
            self.ed_globals.setPlainText(self.existing_spec.get("globals_text", ""))
            self.ed_function.setPlainText(self.existing_spec.get("function_code", ""))

            template_id = self.existing_spec.get("template_id", "")
            if template_id:
                for row in range(self.list_templates.count()):
                    item = self.list_templates.item(row)
                    if item.data(Qt.UserRole) == template_id:
                        self.list_templates.blockSignals(True)
                        self.list_templates.setCurrentRow(row)
                        self.list_templates.blockSignals(False)
                        template = self._find_template(template_id)
                        if template:
                            self.tx_template_desc.setPlainText(template.get("description", ""))
                        break
        else:
            if self.list_templates.count() > 0:
                self.list_templates.setCurrentRow(0)
            self.ed_name.setText(f"custom_{len(self.main_window.custom_series_defs) + 1}")

    def _sync_file_for_fields(self):
        file_name = self.cmb_file.currentText().strip()
        if not file_name:
            return

        candidates = [self.ed_input.signal_uri()] + [ed.signal_uri() for ed in self.additional_fields]
        for uri in candidates:
            parsed = _parse_signal_uri_text(uri)
            if parsed and parsed[0] and parsed[0] != file_name:
                idx = self.cmb_file.findText(parsed[0])
                if idx >= 0:
                    self.cmb_file.setCurrentIndex(idx)
                return

    def _on_template_selected(self, current, previous):
        if current is None:
            return
        template_id = current.data(Qt.UserRole)
        template = self._find_template(template_id)
        if not template:
            return
        self.tx_template_desc.setPlainText(template.get("description", ""))
        self.ed_function.setPlainText(template.get("function_code", ""))
        self.ed_globals.setPlainText(template.get("globals_text", ""))

    def _validate_and_build_spec(self):
        file_name = self.cmb_file.currentText().strip()
        if not file_name:
            raise ValueError("Dataset을 선택해 주세요.")
        if file_name not in self.main_window.loaded_datasets:
            raise ValueError("선택한 Dataset을 찾을 수 없습니다.")

        name = self.ed_name.text().strip()
        if not name:
            raise ValueError("New name을 입력해 주세요.")

        input_uri = self.ed_input.signal_uri().strip()
        if not input_uri:
            raise ValueError("Input timeseries를 지정해 주세요.")
        parsed_input = _parse_signal_uri_text(input_uri)
        if not parsed_input:
            raise ValueError("Input timeseries 형식이 올바르지 않습니다.")
        if parsed_input[0] != file_name:
            raise ValueError("Input timeseries는 선택한 Dataset 파일과 동일해야 합니다.")

        additional_uris = []
        for ed in self.additional_fields:
            uri = ed.signal_uri().strip()
            if not uri:
                additional_uris.append("")
                continue
            parsed = _parse_signal_uri_text(uri)
            if not parsed:
                raise ValueError(f"추가 시계열 형식 오류: {uri}")
            if parsed[0] != file_name:
                raise ValueError("추가 시계열은 입력 시계열과 동일한 파일이어야 합니다.")
            additional_uris.append(uri)

        function_code = self.ed_function.toPlainText().strip()
        if not function_code:
            raise ValueError("Function editor 코드가 비어 있습니다.")

        template_id = ""
        item = self.list_templates.currentItem()
        if item is not None:
            template_id = str(item.data(Qt.UserRole) or "")

        return {
            "name": name,
            "file_name": file_name,
            "input_uri": input_uri,
            "additional_uris": additional_uris,
            "globals_text": self.ed_globals.toPlainText(),
            "function_code": function_code,
            "template_id": template_id,
        }

    def _build_eval_env(self, globals_text):
        safe_builtins = {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "float": float,
            "int": int,
            "round": round,
        }
        env = {"__builtins__": safe_builtins, "np": np, "math": math}
        user_vars = {}

        for line in globals_text.splitlines():
            src = line.strip()
            if not src or src.startswith("#"):
                continue
            if "=" not in src:
                raise ValueError(f"Global variable 형식 오류: {src}")
            name, expr = src.split("=", 1)
            var_name = name.strip()
            if not var_name:
                raise ValueError(f"Global variable 이름이 비어 있습니다: {src}")
            user_vars[var_name] = eval(expr.strip(), env, user_vars)

        env.update(user_vars)
        return env

    def _compute_series(self, spec):
        base_xy = self.main_window._get_series_xy_from_uri(spec["input_uri"], require_time=True)
        if base_xy is None:
            raise ValueError("Input timeseries를 읽지 못했습니다.")
        time_arr, value_arr = base_xy
        if len(time_arr) == 0:
            raise ValueError("Input timeseries 데이터가 비어 있습니다.")

        aligned_sources = []
        for uri in spec["additional_uris"]:
            if not uri:
                aligned_sources.append(None)
                continue
            src_xy = self.main_window._get_series_xy_from_uri(uri, require_time=True)
            if src_xy is None:
                raise ValueError(f"추가 시계열을 읽지 못했습니다: {_format_signal_uri_label(uri)}")
            src_t, src_y = src_xy
            if len(src_t) == 0:
                aligned_sources.append(None)
                continue
            aligned_sources.append(np.interp(time_arr, src_t, src_y))

        env = self._build_eval_env(spec["globals_text"])
        local_ns = {}
        exec(spec["function_code"], env, local_ns)
        fn = local_ns.get("function")
        if not callable(fn):
            raise ValueError("코드에 'def function(...)' 정의가 필요합니다.")

        kwargs = {"time": time_arr, "value": value_arr}
        for i, arr in enumerate(aligned_sources, start=1):
            kwargs[f"v{i}"] = arr

        try:
            sig = inspect.signature(fn)
            accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if accepts_var_kw:
                result = fn(**kwargs)
            else:
                accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
                result = fn(**accepted)
        except TypeError:
            result = fn(
                time_arr,
                value_arr,
                aligned_sources[0],
                aligned_sources[1],
                aligned_sources[2],
                aligned_sources[3],
            )

        out = np.asarray(result, dtype=np.float64)
        if out.ndim == 0:
            out = np.full_like(time_arr, float(out), dtype=np.float64)
        out = np.ravel(out)
        if len(out) != len(time_arr):
            raise ValueError(f"출력 길이({len(out)})가 입력 길이({len(time_arr)})와 다릅니다.")
        return time_arr, out

    def _render_preview(self, x, y, name):
        self.preview_plot.clear()
        self.preview_plot.plot(x, y, pen=pg.mkPen("#1A2D57", width=1.7), autoDownsample=True)
        self.preview_plot.setTitle(f"Preview: {name}")
        self.preview_plot.autoRange()

    def _on_preview(self):
        self._set_error("")
        try:
            spec = self._validate_and_build_spec()
            x, y = self._compute_series(spec)
        except Exception as e:
            self._set_error(str(e))
            return
        self.series_spec = spec
        self.series_x = x
        self.series_y = y
        self._render_preview(x, y, spec["name"])

    def _on_create(self):
        self._set_error("")
        try:
            spec = self._validate_and_build_spec()
            x, y = self._compute_series(spec)
        except Exception as e:
            self._set_error(str(e))
            QMessageBox.warning(self, "Custom Series", f"Custom Series 생성 실패:\n{e}")
            return
        self.series_spec = spec
        self.series_x = x
        self.series_y = y
        self.accept()


if gl is not None:
    class FlightPath3DViewWidget(gl.GLViewWidget):
        """GLViewWidget with controls optimized for flight-path inspection."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self._drag_mode = None
            self._last_pos = None
            self.setMouseTracking(True)
            self.opts["fov"] = 60
            self.setAutoFillBackground(False)
            try:
                self.setUpdateBehavior(self.UpdateBehavior.PartialUpdate)
            except Exception:
                pass

        def mousePressEvent(self, event):
            if event.button() == Qt.MiddleButton:
                self._drag_mode = "rotate"
                self._last_pos = event.position()
                event.accept()
                return

            if (event.modifiers() & Qt.ShiftModifier) and event.button() == Qt.LeftButton:
                self._drag_mode = "pan"
                self._last_pos = event.position()
                event.accept()
                return

            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            if self._drag_mode and self._last_pos is not None:
                pos = event.position()
                dx = float(pos.x() - self._last_pos.x())
                dy = float(pos.y() - self._last_pos.y())
                if self._drag_mode == "rotate":
                    self.orbit(-dx * 0.45, dy * 0.45)
                else:
                    dist = float(self.opts.get("distance", 10.0))
                    pan_scale = max(0.001, dist * 0.002)
                    try:
                        self.pan(-dx * pan_scale, dy * pan_scale, 0.0, relative="view")
                    except TypeError:
                        self.pan(-dx * pan_scale, dy * pan_scale, 0.0, relative=True)
                self._last_pos = pos
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):
            if self._drag_mode and event.button() in (Qt.MiddleButton, Qt.LeftButton):
                self._drag_mode = None
                self._last_pos = None
                event.accept()
                return
            super().mouseReleaseEvent(event)

class AdvancedPlot(QWidget):
    def __init__(self, main_window, workspace, parent_splitter=None):
        super().__init__()
        self.main_window = main_window 
        self.workspace = workspace 
        self.parent_splitter = parent_splitter 
        self.setMinimumSize(150, 150) 
        self.setAcceptDrops(True) 
        self.is_fft_plot = False 
        self.is_time_plot = False 
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(1, 1, 1, 1) 

        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(4, 2, 4, 0)
        self.control_layout.setSpacing(6)

        self.btn_toggle_legend = QPushButton("")
        self.btn_toggle_legend.setObjectName("legendCircleButton")
        self.btn_toggle_legend.setCheckable(True)
        self.btn_toggle_legend.setChecked(True)
        self.btn_toggle_legend.setFixedSize(7, 7)
        self.btn_toggle_legend.clicked.connect(self.toggle_legend_visibility)
        self.control_layout.addStretch()
        self.control_layout.addWidget(self.btn_toggle_legend)
        self.layout.addLayout(self.control_layout)
        
        self.plot = pg.PlotWidget()
        self.plot.setAcceptDrops(True)
        self.plot.viewport().setAcceptDrops(True)
        self.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode) 
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.legend_visible = True
        self._get_or_create_legend()
        self.plot.setClipToView(False)
        
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#FFD700', width=1, style=Qt.DashLine))
        self.v_line.hide() 
        self.plot.addItem(self.v_line)
        self.plot.scene().sigMouseClicked.connect(self.on_mouse_click)

        self.plot_stack = QStackedWidget()
        self.plot_stack.setContentsMargins(0, 0, 0, 0)
        self.plot_stack.addWidget(self.plot)
        self.plot_stack.setCurrentWidget(self.plot)
        self.layout.addWidget(self.plot_stack)
        
        self.overlay_label = QLabel(self)
        self.apply_theme_to_overlay(is_dark=True)
        self.apply_theme_to_plot_controls(is_dark=True)
        self.overlay_label.move(60, 10) 
        self.overlay_label.hide()
        self.overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents) 
        self._last_overlay_html = ""
        self.toggle_legend_visibility(self.btn_toggle_legend.isChecked())

        self._true_3d_available = gl is not None
        self._true_3d_enabled = False
        self._true_3d_view = None
        self._true_3d_items = []
        self._true_3d_points = None
        self._true_3d_abs_points = None
        self._true_3d_time_arr = None
        self._true_3d_line_item = None
        self._true_3d_time_marker_item = None
        self._true_3d_time_marker_outer_item = None
        self._true_3d_time_marker_idx = None
        self._true_3d_camera_default = None
        self._true_3d_title = "3D Flight Path (Interactive)"
        self._3d_path_style = {
            "color": QColor("#2E86DE"),  # default: readable blue on dark/light themes
            "style": "solid",
            "width": 2.6,
        }
        self._true_3d_hint = QLabel(self)
        self._true_3d_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._true_3d_hint.hide()
        self._true_3d_axis_panel = QLabel(self)
        self._true_3d_axis_panel.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._true_3d_axis_panel.hide()
        self._true_3d_pick_label = QLabel(self)
        self._true_3d_pick_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._true_3d_pick_label.hide()
        self._true_3d_pending_pick = False
        self._true_3d_pick_press_pos = None

        self._flight_path_2d_enabled = False
        self._flight_path_2d_state = None
        self._flight_path_2d_curve_item = None
        self._flight_path_2d_marker_item = None
        self._flight_path_2d_start_item = None
        self._flight_path_2d_end_item = None
        self._flight_path_2d_pick_label = QLabel(self)
        self._flight_path_2d_pick_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._flight_path_2d_pick_label.hide()
        self.apply_theme_to_3d(is_dark=True)

        self.plotted_signals = {} 
        self.signal_cache = {}
        self.plot_item_to_uri = {}
        self.layout_special_spec = None
        self._projected_3d_enabled = False
        self._projected_3d_state = None
        self._projected_3d_line_item = None
        self._projected_3d_scatter_item = None
        self._projected_3d_start_item = None
        self._projected_3d_end_item = None
        self._projected_3d_time_marker_item = None
        self._projected_3d_info_item = None
        self._projected_3d_drag_mode = None
        self._projected_3d_last_pos = None
        self._projected_3d_last_view_update = 0.0
        self._projected_3d_pending_pick = False
        self._projected_3d_pick_press_pos = None
        self._drop_highlight_active = False
        self._last_text_scale_key = None
        self.plot.viewport().installEventFilter(self)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        if self._true_3d_available:
            # Pre-create GL widget in the same stacked container to avoid runtime relayout flicker.
            self._ensure_true_3d_view()
        QTimer.singleShot(0, self._apply_adaptive_plot_text_scale)

    @staticmethod
    def _signal_uris_from_mime(mime):
        if mime is None:
            return []
        raw_text = ""
        if mime.hasFormat("application/x-px4-signal-list"):
            raw_bytes = bytes(mime.data("application/x-px4-signal-list"))
            if raw_bytes:
                raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not raw_text and mime.hasText():
            raw_text = mime.text().strip()
        if not raw_text:
            return []
        uris = []
        for line in raw_text.splitlines():
            s = line.strip()
            if not s:
                continue
            if len(s.split("|")) >= 3:
                uris.append(s)
        return uris

    @staticmethod
    def _parse_signal_uri(uri):
        parts = uri.split("|")
        if len(parts) < 3:
            return None
        file_name, topic_name, signal_name = parts[:3]
        x_axis_col = parts[3] if len(parts) > 3 and parts[3] else "timestamp_sec"
        return file_name, topic_name, signal_name, x_axis_col

    @staticmethod
    def _prefers_curve_popup_from_mime(mime):
        if mime is None:
            return False
        if not mime.hasFormat("application/x-px4-drag-origin"):
            return False
        try:
            raw = bytes(mime.data("application/x-px4-drag-origin"))
            return raw.decode("utf-8", errors="ignore").strip().lower() == "right"
        except Exception:
            return False

    @staticmethod
    def _signal_axis_role(topic_name, signal_name):
        topic = str(topic_name or "").lower()
        sig = str(signal_name or "").strip().lower()
        is_global = "global" in topic
        if is_global:
            if sig in {"lon", "longitude", "longitude_deg", "position[0]"}:
                return "x"
            if sig in {"lat", "latitude", "latitude_deg", "position[1]"}:
                return "y"
            if sig in {"alt", "altitude", "altitude_msl_m", "alt_up", "position[2]", "z"}:
                return "z"
            return None

        if sig in {"x", "north", "position[0]"}:
            return "x"
        if sig in {"y", "east", "position[1]"}:
            return "y"
        if sig in {"z", "alt", "alt_up", "altitude", "position[2]"}:
            return "z"
        return None

    def _series_from_uri_for_curve(self, uri):
        parsed = self._parse_signal_uri(uri)
        if parsed is None:
            return None
        file_name, topic_name, signal_name, x_axis_col = parsed

        if topic_name == self.main_window.CUSTOM_SERIES_TOPIC:
            xy = self.main_window._get_custom_series_xy(file_name, signal_name)
            if xy is None:
                return None
            t, v = xy
            t = np.asarray(t, dtype=np.float64)
            v = np.asarray(v, dtype=np.float64)
        else:
            dataset = self.main_window.loaded_datasets.get(file_name)
            if dataset is None:
                return None
            topic = dataset.topics.get(topic_name)
            if topic is None or topic.dataframe is None:
                return None
            df = topic.dataframe
            if signal_name not in df.columns:
                return None
            if x_axis_col not in df.columns:
                x_axis_col = "timestamp_sec" if "timestamp_sec" in df.columns else ""
            v = np.asarray(df[signal_name].to_numpy(), dtype=np.float64)
            if x_axis_col:
                t = np.asarray(df[x_axis_col].to_numpy(), dtype=np.float64)
            else:
                t = np.arange(len(v), dtype=np.float64)

        if len(t) != len(v) or len(v) == 0:
            return None
        mask = np.isfinite(t) & np.isfinite(v)
        t = t[mask]
        v = v[mask]
        if len(v) < 2:
            return None

        order = np.argsort(t)
        t = t[order]
        v = v[order]
        if len(t) > 1:
            keep = np.concatenate(([True], np.diff(t) > 1e-12))
            t = t[keep]
            v = v[keep]
        if len(v) < 2:
            return None

        return {
            "file_name": file_name,
            "topic_name": topic_name,
            "signal_name": signal_name,
            "x_axis_col": x_axis_col if x_axis_col else "timestamp_sec",
            "t": t,
            "v": v,
            "uri": uri,
        }

    @staticmethod
    def _align_series_to_base_time(base_t, src_t, src_v):
        if len(base_t) < 2 or len(src_t) < 2:
            return None
        return np.interp(base_t, src_t, src_v, left=np.nan, right=np.nan)

    def _render_curve_from_mapping(self, mapping):
        sx = self._series_from_uri_for_curve(mapping.get("x_uri", ""))
        sy = self._series_from_uri_for_curve(mapping.get("y_uri", ""))
        if sx is None or sy is None:
            return False

        base_t = np.asarray(sx["t"], dtype=np.float64)
        x_val = np.asarray(sx["v"], dtype=np.float64)
        y_val = self._align_series_to_base_time(base_t, sy["t"], sy["v"])
        if y_val is None:
            return False

        mode = str(mapping.get("mode", "xy"))
        title = str(mapping.get("name", "")).strip() or ("3D Flight Path" if mode == "xyz" else "2D Flight Path")

        if mode == "xy":
            display_lat = None
            display_lon = None
            role_x = self._signal_axis_role(sx["topic_name"], sx["signal_name"])
            role_y = self._signal_axis_role(sy["topic_name"], sy["signal_name"])
            if {role_x, role_y} == {"x", "y"} and "global" in str(sx["topic_name"]).lower():
                lon = x_val if role_x == "x" else y_val
                lat = x_val if role_x == "y" else y_val
                lat0 = float(lat[0])
                lon0 = float(lon[0])
                earth_r = 6378137.0
                deg_to_rad = np.pi / 180.0
                north = (lat - lat0) * deg_to_rad * earth_r
                east = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
                x2 = north
                y2 = east
                display_lat = lat
                display_lon = lon
            else:
                x2 = x_val - float(x_val[0])
                y2 = y_val - float(y_val[0])

            mask = np.isfinite(base_t) & np.isfinite(x2) & np.isfinite(y2)
            t = base_t[mask]
            x2 = x2[mask]
            y2 = y2[mask]
            if display_lat is not None:
                display_lat = np.asarray(display_lat, dtype=np.float64)[mask]
            if display_lon is not None:
                display_lon = np.asarray(display_lon, dtype=np.float64)[mask]
            if len(x2) < 2:
                return False
            ok = self.render_2d_flight_path(
                x2,
                y2,
                title=title,
                timestamps=t,
                display_lat=display_lat,
                display_lon=display_lon,
                display_alt=None,
            )
            if ok:
                self.layout_special_spec = {
                    "kind": "flight_path_2d",
                    "file_name": sx["file_name"],
                    "topic": sx["topic_name"],
                    "x_signal": sx["signal_name"],
                    "y_signal": sy["signal_name"],
                    "z_signal": None,
                    "time_signal": sx["x_axis_col"],
                }
            return ok

        sz = self._series_from_uri_for_curve(mapping.get("z_uri", ""))
        if sz is None:
            return False
        z_val = self._align_series_to_base_time(base_t, sz["t"], sz["v"])
        if z_val is None:
            return False

        x3 = x_val - float(x_val[0])
        y3 = y_val - float(y_val[0])
        z_role = self._signal_axis_role(sz["topic_name"], sz["signal_name"])
        if "local_position" in str(sz["topic_name"]).lower() and z_role == "z":
            z3 = -(z_val - float(z_val[0]))
        else:
            z3 = z_val - float(z_val[0])

        role_x = self._signal_axis_role(sx["topic_name"], sx["signal_name"])
        role_y = self._signal_axis_role(sy["topic_name"], sy["signal_name"])
        if {role_x, role_y} == {"x", "y"} and "global" in str(sx["topic_name"]).lower():
            lon = x_val if role_x == "x" else y_val
            lat = x_val if role_x == "y" else y_val
            lat0 = float(lat[0])
            lon0 = float(lon[0])
            earth_r = 6378137.0
            deg_to_rad = np.pi / 180.0
            north = (lat - lat0) * deg_to_rad * earth_r
            east = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
            x3 = north
            y3 = east

        mask = np.isfinite(base_t) & np.isfinite(x3) & np.isfinite(y3) & np.isfinite(z3)
        t = base_t[mask]
        x3 = x3[mask]
        y3 = y3[mask]
        z3 = z3[mask]
        if len(x3) < 2:
            return False
        if len(x3) > 8000:
            step = max(1, len(x3) // 8000)
            x3 = x3[::step]
            y3 = y3[::step]
            z3 = z3[::step]
            t = t[::step]

        ok = self.render_3d_path(x3, y3, z3, title, timestamps=t)
        if ok:
            special_kind = "true_3d_path" if getattr(self, "_true_3d_enabled", False) else "projected_3d_path"
            self.layout_special_spec = {
                "kind": special_kind,
                "file_name": sx["file_name"],
                "topic": sx["topic_name"],
                "x_signal": sx["signal_name"],
                "y_signal": sy["signal_name"],
                "z_signal": sz["signal_name"],
                "time_signal": sx["x_axis_col"],
                "line_color": self._3d_path_style["color"].name(),
                "line_style": self._3d_path_style.get("style", "solid"),
                "line_width": float(self._3d_path_style.get("width", 2.6)),
            }
        return ok

    def _show_curve_create_popup_and_render(self, uris):
        if len(uris) < 2:
            return False
        dlg_parent = self.main_window if getattr(self, "main_window", None) is not None else self
        dlg = PathCurveCreateDialog(dlg_parent, uris)
        if dlg.exec() != QDialog.Accepted:
            return False
        mapping = dlg.result_data() or {}
        return self._render_curve_from_mapping(mapping)

    def _try_render_3d_from_signal_uris(self, uris):
        parsed = []
        for uri in uris:
            item = self._parse_signal_uri(uri)
            if item is not None:
                parsed.append(item)
        if len(parsed) < 3:
            return False

        grouped = {}
        for file_name, topic_name, signal_name, x_axis_col in parsed:
            key = (file_name, topic_name)
            grouped.setdefault(key, []).append((signal_name, x_axis_col))

        for (file_name, topic_name), signals in grouped.items():
            if len(signals) < 3:
                continue
            topic_l = str(topic_name or "").lower()
            if not any(k in topic_l for k in ("position", "local_position", "global_position")):
                continue

            axis_map = {}
            time_col = "timestamp_sec"
            for signal_name, x_axis_col in signals:
                role = self._signal_axis_role(topic_name, signal_name)
                if role and role not in axis_map:
                    axis_map[role] = signal_name
                if x_axis_col:
                    time_col = x_axis_col

            if not all(k in axis_map for k in ("x", "y", "z")):
                continue

            dataset = self.main_window.loaded_datasets.get(file_name)
            if dataset is None:
                continue
            topic_inst = dataset.topics.get(topic_name)
            if topic_inst is None or topic_inst.dataframe is None:
                continue

            df = topic_inst.dataframe
            x_sig = axis_map["x"]
            y_sig = axis_map["y"]
            z_sig = axis_map["z"]
            if x_sig not in df.columns or y_sig not in df.columns or z_sig not in df.columns:
                continue
            if time_col not in df.columns:
                time_col = "timestamp_sec" if "timestamp_sec" in df.columns else None

            try:
                x = np.asarray(df[x_sig].to_numpy(), dtype=np.float64)
                y = np.asarray(df[y_sig].to_numpy(), dtype=np.float64)
                z = np.asarray(df[z_sig].to_numpy(), dtype=np.float64)
                t = np.asarray(df[time_col].to_numpy(), dtype=np.float64) if time_col else None
            except Exception:
                continue

            mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            if t is not None and len(t) == len(mask):
                mask = mask & np.isfinite(t)
            x = x[mask]
            y = y[mask]
            z = z[mask]
            if t is not None and len(t) == len(mask):
                t = t[mask]
            else:
                t = None
            if len(x) < 2:
                continue

            is_global_topic = "global" in str(topic_name).lower()
            if is_global_topic:
                lat = y
                lon = x
                alt = z
                lat0 = float(lat[0])
                lon0 = float(lon[0])
                alt0 = float(alt[0])
                earth_r = 6378137.0
                deg_to_rad = np.pi / 180.0
                north = (lat - lat0) * deg_to_rad * earth_r
                east = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
                up = alt - alt0
                x3, y3, z3 = north, east, up
            else:
                x3 = x - float(x[0])
                y3 = y - float(y[0])
                z3 = -(z - float(z[0]))

            if len(x3) > 8000:
                step = max(1, len(x3) // 8000)
                x3 = x3[::step]
                y3 = y3[::step]
                z3 = z3[::step]
                if t is not None:
                    t = t[::step]

            ok = self.render_3d_path(x3, y3, z3, "3D Flight Path (Interactive)", timestamps=t)
            if not ok:
                continue

            special_kind = "true_3d_path" if getattr(self, "_true_3d_enabled", False) else "projected_3d_path"
            self.layout_special_spec = {
                "kind": special_kind,
                "file_name": file_name,
                "topic": topic_name,
                "x_signal": x_sig,
                "y_signal": y_sig,
                "z_signal": z_sig,
                "time_signal": time_col if time_col else "timestamp_sec",
                "line_color": self._3d_path_style["color"].name(),
                "line_style": self._3d_path_style.get("style", "solid"),
                "line_width": float(self._3d_path_style.get("width", 2.6)),
            }
            print(f"[DND][Plot] 3D path auto-rendered from drop: {file_name}|{topic_name} ({x_sig},{y_sig},{z_sig})")
            return True

        return False

    def _apply_signal_uris(self, uris, prefer_curve_popup=False):
        if prefer_curve_popup and len(uris) >= 2:
            rendered_popup = self._show_curve_create_popup_and_render(uris)
            if rendered_popup:
                try:
                    self.main_window.statusBar().showMessage("Curve 생성 완료", 3000)
                except Exception:
                    pass
                return True
            return False

        rendered_count = 0
        for uri in uris:
            parts = uri.split('|')
            if len(parts) >= 3:
                file_name, topic_name, signal_name = parts[:3]
                x_axis_col = parts[3] if len(parts) > 3 else "timestamp_sec"
                if self.render_signal(file_name, topic_name, signal_name, x_axis_col):
                    rendered_count += 1
        return rendered_count > 0

    def _set_drop_highlight(self, active):
        self._drop_highlight_active = bool(active)
        if self._drop_highlight_active:
            self.setStyleSheet("border: 2px dashed #2EA3FF; background-color: rgba(46, 163, 255, 0.05);")
        else:
            self.setStyleSheet("")

    def _get_or_create_legend(self):
        legend = self.plot.plotItem.legend
        if legend is None:
            legend = self.plot.addLegend(offset=(10, 10))
        return legend

    def toggle_legend_visibility(self, checked):
        self.legend_visible = bool(checked)
        legend = self._get_or_create_legend()
        legend.setVisible(self.legend_visible)
        if hasattr(self, "_true_3d_axis_panel") and self._true_3d_enabled:
            self._true_3d_axis_panel.setVisible(self.legend_visible)
        self.btn_toggle_legend.setToolTip("Legend ON" if self.legend_visible else "Legend OFF")
        self._apply_adaptive_plot_text_scale()

    def apply_theme_to_plot_controls(self, is_dark):
        if is_dark:
            self.btn_toggle_legend.setStyleSheet("""
                QPushButton#legendCircleButton {
                    background-color: #f2f6ff;
                    border: 1px solid #3f4b57;
                    border-radius: 3px;
                }
                QPushButton#legendCircleButton:checked {
                    background-color: #1A2D57;
                    border: 1px solid #1A2D57;
                }
            """)
        else:
            self.btn_toggle_legend.setStyleSheet("""
                QPushButton#legendCircleButton {
                    background-color: #ffffff;
                    border: 1px solid #9aa7b7;
                    border-radius: 3px;
                }
                QPushButton#legendCircleButton:checked {
                    background-color: #1A2D57;
                    border: 1px solid #1A2D57;
                }
            """)

    def _apply_adaptive_plot_text_scale(self):
        try:
            pw = float(max(1, self.plot.width()))
            ph = float(max(1, self.plot.height()))
            # More aggressive shrink curve so text does not cover data on compact plots.
            scale = max(0.34, min(0.72, min(pw / 1200.0, ph / 620.0)))

            tick_pt = max(4, int(round(9 * scale)))
            label_pt = max(5, int(round(10 * scale)))
            title_pt = max(6, int(round(12 * scale)))
            legend_pt = max(5, int(round(9 * scale)))

            tick_font = QFont()
            tick_font.setPointSize(tick_pt)
            for axis_name in ("left", "bottom"):
                axis = self.plot.getAxis(axis_name)
                axis.setStyle(tickFont=tick_font)
                try:
                    axis.label.setAttr("size", f"{label_pt}pt")
                except Exception:
                    pass

            plot_item = self.plot.getPlotItem()
            legend = plot_item.legend if plot_item is not None else None
            legend_count = len(getattr(legend, "items", [])) if legend is not None else 0
            title_key = ""
            if plot_item is not None and hasattr(plot_item, "titleLabel"):
                try:
                    title_key = plot_item.titleLabel.text or ""
                except Exception:
                    title_key = ""

            # Re-apply when legend entries or title change, not only when widget size changes.
            key = (tick_pt, label_pt, title_pt, legend_pt, legend_count, title_key)
            if key == self._last_text_scale_key:
                return
            self._last_text_scale_key = key

            if plot_item is not None and hasattr(plot_item, "titleLabel"):
                try:
                    plain_title = re.sub("<[^>]+>", "", plot_item.titleLabel.text or "").strip()
                    if plain_title:
                        plot_item.setTitle(plain_title, size=f"{title_pt}pt")
                    else:
                        plot_item.titleLabel.setAttr("size", f"{title_pt}pt")
                except Exception:
                    pass

            if legend is not None:
                for _sample, label in getattr(legend, "items", []):
                    try:
                        plain_text = re.sub("<[^>]+>", "", getattr(label, "text", "") or "").strip()
                        if plain_text:
                            label.setText(plain_text, size=f"{legend_pt}pt")
                        else:
                            label.setAttr("size", f"{legend_pt}pt")
                    except Exception:
                        pass
        except Exception:
            pass

    def apply_theme_to_overlay(self, is_dark):
        bg_color = "rgba(30, 30, 30, 180)" if is_dark else "rgba(255, 255, 255, 220)"
        text_color = "#FFD700" if is_dark else "#000000"
        border_color = "#555" if is_dark else "#ccc"
        
        self.overlay_label.setStyleSheet(f"""
            color: {text_color}; font-weight: bold; font-size: 8px;
            background-color: {bg_color}; 
            border: 1px solid {border_color}; border-radius: 3px; padding: 2px;
        """)

    def apply_theme_to_3d(self, is_dark):
        hint_bg = "rgba(20, 20, 20, 180)" if is_dark else "rgba(255, 255, 255, 220)"
        hint_fg = "#dce4ec" if is_dark else "#1f2b36"
        hint_border = "#5c6a78" if is_dark else "#b8c2cd"
        if hasattr(self, "_true_3d_hint"):
            self._true_3d_hint.setStyleSheet(
                f"color: {hint_fg}; background-color: {hint_bg}; "
                f"border: 1px solid {hint_border}; border-radius: 3px; "
                "padding: 3px 6px; font-size: 10px; font-weight: 600;"
            )
        # Keep path value panel clean/light in both themes for readability.
        pick_bg = "rgba(250, 252, 255, 235)"
        pick_fg = "#1f2b36"
        pick_border = "#b8c2cd"
        pick_style = (
            f"color: {pick_fg}; background-color: {pick_bg}; "
            f"border: 1px solid {pick_border}; border-radius: 4px; "
            "padding: 4px 7px; font-size: 10px; font-weight: 600;"
        )
        if hasattr(self, "_true_3d_pick_label"):
            self._true_3d_pick_label.setStyleSheet(pick_style)
        if hasattr(self, "_true_3d_axis_panel"):
            self._true_3d_axis_panel.setStyleSheet(
                f"color: {hint_fg}; background-color: {hint_bg}; "
                f"border: 1px solid {hint_border}; border-radius: 4px; "
                "padding: 4px 7px; font-size: 10px; font-weight: 600;"
            )
        if hasattr(self, "_flight_path_2d_pick_label"):
            # Keep 2D-path data box exactly same visual spec as 3D-path data box.
            self._flight_path_2d_pick_label.setStyleSheet(pick_style)
        if self._true_3d_view is not None:
            if is_dark:
                self._true_3d_view.setBackgroundColor((24, 26, 30, 255))
            else:
                self._true_3d_view.setBackgroundColor((245, 247, 250, 255))

    def apply_theme_to_2d_flight_path(self, is_dark):
        if not self._flight_path_2d_enabled:
            return
        if is_dark:
            bg_color = "#181A1E"
            axis_color = "#C8D2DE"
            grid_alpha = 0.24
        else:
            # Match true-3D light background palette.
            bg_color = "#F5F7FA"
            axis_color = "#5F6F82"
            grid_alpha = 0.26

        self.plot.setBackground(bg_color)
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(axis_color, width=1))
            axis.setTextPen(pg.mkPen(axis_color, width=1))
        self.plot.showGrid(x=True, y=True, alpha=grid_alpha)

    def _on_true_3d_context_menu(self, local_pos):
        self.main_window.last_active_plot = self
        global_pos = self._true_3d_view.mapToGlobal(local_pos)
        self.show_context_menu(self.mapFromGlobal(global_pos))

    @staticmethod
    def _gl_rgba_from_qcolor(color):
        q = QColor(color) if not isinstance(color, QColor) else color
        if not q.isValid():
            q = QColor("#2E86DE")
        return (q.redF(), q.greenF(), q.blueF(), q.alphaF())

    @staticmethod
    def _gl_rgba_array_from_qcolor(color, count=1):
        q = QColor(color) if not isinstance(color, QColor) else color
        if not q.isValid():
            q = QColor("#2E86DE")
        c = np.array([[q.redF(), q.greenF(), q.blueF(), q.alphaF()]], dtype=np.float32)
        if count is None or int(count) <= 1:
            return c
        return np.repeat(c, int(count), axis=0)

    @staticmethod
    def _path_cursor_fill_qcolor():
        # Strong yellow for visibility on both light/dark backgrounds.
        return QColor("#FFD400")

    @staticmethod
    def _path_cursor_border_qcolor():
        return QColor("#8A6A00")

    @staticmethod
    def _path_takeoff_fill_qcolor():
        return QColor("#F5A623")

    @staticmethod
    def _path_takeoff_border_qcolor():
        return QColor("#A86200")

    @staticmethod
    def _path_landing_fill_qcolor():
        return QColor("#3DDC76")

    @staticmethod
    def _path_landing_border_qcolor():
        return QColor("#166D2B")

    @staticmethod
    def _line_style_pattern(style_key):
        if style_key == "dash":
            return [12.0, 8.0]
        if style_key == "dense_dash":
            return [6.0, 5.0]
        if style_key == "dot":
            return [2.0, 7.0]
        if style_key == "dash_dot":
            return [10.0, 6.0, 2.0, 6.0]
        return None

    def _build_styled_3d_line(self, points, style_key):
        points = np.asarray(points, dtype=np.float32)
        if points.ndim != 2 or points.shape[0] < 2:
            return points, "line_strip"
        pattern = self._line_style_pattern(style_key)
        if not pattern:
            return points, "line_strip"

        deltas = points[1:] - points[:-1]
        seg_len = np.linalg.norm(deltas, axis=1).astype(np.float64)
        if len(seg_len) == 0 or np.all(seg_len <= 1e-9):
            return points, "line_strip"

        cumulative = np.concatenate(([0.0], np.cumsum(seg_len)))
        cycle = float(sum(pattern))
        if cycle <= 1e-9:
            return points, "line_strip"

        segments = []
        for idx in range(len(seg_len)):
            if seg_len[idx] <= 1e-9:
                continue
            phase = float(((cumulative[idx] + cumulative[idx + 1]) * 0.5) % cycle)
            acc = 0.0
            is_on = False
            for p_idx, p_len in enumerate(pattern):
                if phase < acc + p_len:
                    is_on = (p_idx % 2 == 0)
                    break
                acc += p_len
            if is_on:
                segments.append(points[idx])
                segments.append(points[idx + 1])

        if len(segments) < 2:
            return points, "line_strip"
        return np.asarray(segments, dtype=np.float32), "lines"

    def _build_true_3d_line_item(self, points):
        color = self._3d_path_style["color"]
        width = max(1.0, float(self._3d_path_style.get("width", 2.6)))
        style_key = self._3d_path_style.get("style", "solid")
        line_pos, mode = self._build_styled_3d_line(points, style_key)
        return gl.GLLinePlotItem(
            pos=line_pos,
            color=self._gl_rgba_from_qcolor(color),
            width=width,
            antialias=True,
            mode=mode,
        )

    def _sync_3d_style_to_layout_spec(self):
        if not isinstance(self.layout_special_spec, dict):
            return
        if self.layout_special_spec.get("kind") not in ("true_3d_path", "projected_3d_path"):
            return
        self.layout_special_spec["line_color"] = self._3d_path_style["color"].name()
        self.layout_special_spec["line_style"] = self._3d_path_style.get("style", "solid")
        self.layout_special_spec["line_width"] = float(self._3d_path_style.get("width", 2.6))

    def _apply_projected_3d_style(self):
        if not self._projected_3d_enabled or self._projected_3d_line_item is None:
            return
        style_key = self._3d_path_style.get("style", "solid")
        style_map = {
            "solid": Qt.SolidLine,
            "dash": Qt.DashLine,
            "dense_dash": Qt.CustomDashLine,
            "dot": Qt.DotLine,
            "dash_dot": Qt.DashDotLine,
        }
        pen_style = style_map.get(style_key, Qt.SolidLine)
        pen = pg.mkPen(
            color=self._3d_path_style["color"],
            width=max(1.0, float(self._3d_path_style.get("width", 2.6))),
            style=pen_style,
        )
        if pen_style == Qt.CustomDashLine:
            pen.setDashPattern([2, 2])
        self._projected_3d_line_item.setPen(pen)

    def _apply_true_3d_style(self):
        if not self._true_3d_enabled or self._true_3d_view is None or self._true_3d_points is None:
            return
        if self._true_3d_line_item is not None:
            try:
                self._true_3d_view.removeItem(self._true_3d_line_item)
            except Exception:
                pass
            try:
                self._true_3d_items.remove(self._true_3d_line_item)
            except ValueError:
                pass
        self._true_3d_line_item = self._build_true_3d_line_item(self._true_3d_points)
        self._true_3d_view.addItem(self._true_3d_line_item)
        self._true_3d_items.insert(0, self._true_3d_line_item)
        self._true_3d_view.update()

    def set_3d_path_style(self, color=None, style_key=None, width=None):
        changed = False
        if color is not None:
            q = QColor(color) if not isinstance(color, QColor) else color
            if q.isValid() and q != self._3d_path_style["color"]:
                self._3d_path_style["color"] = q
                changed = True
        if style_key is not None:
            key = str(style_key).strip().lower()
            if key in ("solid", "dash", "dense_dash", "dot", "dash_dot") and key != self._3d_path_style.get("style"):
                self._3d_path_style["style"] = key
                changed = True
        if width is not None:
            try:
                width_val = float(width)
            except Exception:
                width_val = self._3d_path_style.get("width", 2.6)
            width_val = max(1.0, min(8.0, width_val))
            if abs(width_val - float(self._3d_path_style.get("width", 2.6))) > 1e-6:
                self._3d_path_style["width"] = width_val
                changed = True

        if not changed:
            return

        if self._true_3d_enabled:
            self._apply_true_3d_style()
        elif self._projected_3d_enabled:
            self._apply_projected_3d_style()
            self.plot.update()
        self._sync_3d_style_to_layout_spec()

    def change_3d_path_line_color(self):
        color_dialog = QColorDialog(self._3d_path_style["color"], self)
        color_dialog.setWindowTitle("3D Path 선 색상 선택")
        if color_dialog.exec():
            new_color = color_dialog.selectedColor()
            if new_color.isValid():
                self.set_3d_path_style(color=new_color)
                if self.workspace:
                    self.workspace.on_cursor_changed()

    def change_3d_path_line_style(self, style_key):
        self.set_3d_path_style(style_key=style_key)

    def change_3d_path_line_width(self, width_value):
        self.set_3d_path_style(width=width_value)

    def _disable_2d_flight_path_mode(self):
        if not self._flight_path_2d_enabled:
            self._flight_path_2d_state = None
            self._flight_path_2d_curve_item = None
            self._flight_path_2d_marker_item = None
            self._flight_path_2d_start_item = None
            self._flight_path_2d_end_item = None
            self._flight_path_2d_pick_label.hide()
            return

        for item in (
            self._flight_path_2d_curve_item,
            self._flight_path_2d_marker_item,
            self._flight_path_2d_start_item,
            self._flight_path_2d_end_item,
        ):
            if item is None:
                continue
            try:
                self.plot.removeItem(item)
            except Exception:
                pass
        self._flight_path_2d_enabled = False
        self._flight_path_2d_state = None
        self._flight_path_2d_curve_item = None
        self._flight_path_2d_marker_item = None
        self._flight_path_2d_start_item = None
        self._flight_path_2d_end_item = None
        self._flight_path_2d_pick_label.hide()

    def _nearest_time_index(self, time_arr, target_t):
        if time_arr is None or len(time_arr) == 0:
            return None
        idx = int(np.searchsorted(time_arr, float(target_t), side="left"))
        if idx >= len(time_arr):
            idx = len(time_arr) - 1
        elif idx > 0:
            prev_idx = idx - 1
            if abs(float(time_arr[prev_idx]) - float(target_t)) <= abs(float(time_arr[idx]) - float(target_t)):
                idx = prev_idx
        return idx

    def _sync_workspace_time_range(self, t_arr):
        if self.workspace is None or t_arr is None:
            return
        try:
            t = np.asarray(t_arr, dtype=np.float64)
        except Exception:
            return
        if len(t) < 2:
            return
        t = t[np.isfinite(t)]
        if len(t) < 2:
            return
        ws = self.workspace
        was_uninitialized_range = (ws.global_min_x is None or ws.global_max_x is None)
        ws.expand_time_range(t)
        if (
            was_uninitialized_range
            and ws.global_min_x is not None
            and ws.global_max_x is not None
        ):
            ws.set_time_range(ws.global_min_x, ws.global_max_x, clamp_to_global=False)

    def _set_2d_flight_path_cursor_index(self, idx, update_workspace_time=False, show_label=True):
        if not self._flight_path_2d_enabled or not isinstance(self._flight_path_2d_state, dict):
            return False
        t_arr = self._flight_path_2d_state.get("time")
        x_arr = self._flight_path_2d_state.get("x")
        y_arr = self._flight_path_2d_state.get("y")
        z_arr = self._flight_path_2d_state.get("z")
        if t_arr is None or x_arr is None or y_arr is None or len(t_arr) == 0:
            return False
        idx = int(max(0, min(len(t_arr) - 1, idx)))

        if self._flight_path_2d_marker_item is not None:
            marker_pen = pg.mkPen(self._path_cursor_border_qcolor(), width=1.8)
            marker_brush = pg.mkBrush(self._path_cursor_fill_qcolor())
            self._flight_path_2d_marker_item.setData(
                [float(x_arr[idx])],
                [float(y_arr[idx])],
                symbol='o',
                size=9,
                pen=marker_pen,
                brush=marker_brush,
            )

        if show_label:
            t_val = float(t_arr[idx])
            x_val = float(x_arr[idx])
            y_val = float(y_arr[idx])
            lat_disp = self._flight_path_2d_state.get("display_lat")
            lon_disp = self._flight_path_2d_state.get("display_lon")
            alt_disp = self._flight_path_2d_state.get("display_alt")

            if lat_disp is not None and lon_disp is not None and len(lat_disp) > idx and len(lon_disp) > idx:
                coord_line_1 = f"위도: {float(lat_disp[idx]):.6f}"
                coord_line_2 = f"경도: {float(lon_disp[idx]):.6f}"
            else:
                labels = self._flight_path_2d_state.get("coord_labels", ("North", "East"))
                coord_line_1 = f"{labels[0]}: {x_val:.2f} m"
                coord_line_2 = f"{labels[1]}: {y_val:.2f} m"

            if alt_disp is not None and len(alt_disp) > idx and np.isfinite(alt_disp[idx]):
                alt_text = f"\nAltitude: {float(alt_disp[idx]):.2f} m"
            elif z_arr is not None and len(z_arr) > idx and np.isfinite(z_arr[idx]):
                alt_text = f"\nAltitude: {float(z_arr[idx]):.2f} m"
            else:
                alt_text = ""
            self._flight_path_2d_pick_label.setText(
                f"Time: {t_val:.2f} s\n"
                f"{coord_line_1}\n"
                f"{coord_line_2}"
                f"{alt_text}"
            )
            self._flight_path_2d_pick_label.adjustSize()
            pick_x = self.plot_stack.x() + max(6, self.plot_stack.width() - self._flight_path_2d_pick_label.width() - 10)
            pick_y = self.control_layout.geometry().bottom() + 4
            self._flight_path_2d_pick_label.move(int(pick_x), int(pick_y))
            self._flight_path_2d_pick_label.show()

        if update_workspace_time and self.workspace:
            self.workspace.set_current_time(float(t_arr[idx]), immediate_overlay=True)
        return True

    def update_2d_flight_path_cursor_from_time(self, t):
        if not self._flight_path_2d_enabled or not isinstance(self._flight_path_2d_state, dict):
            return
        idx = self._nearest_time_index(self._flight_path_2d_state.get("time"), t)
        if idx is None:
            return
        self._set_2d_flight_path_cursor_index(idx, update_workspace_time=False, show_label=True)

    def render_2d_flight_path(
        self,
        x,
        y,
        title="2D Flight Path",
        timestamps=None,
        altitude=None,
        display_lat=None,
        display_lon=None,
        display_alt=None,
        coord_labels=None,
    ):
        self.clear_plot_data()
        self._disable_true_3d_mode()
        self._disable_projected_3d_mode()
        self._disable_2d_flight_path_mode()

        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if timestamps is not None:
            try:
                t = np.asarray(timestamps, dtype=np.float64)
            except Exception:
                t = None
        else:
            t = None
        if altitude is not None:
            try:
                z = np.asarray(altitude, dtype=np.float64)
            except Exception:
                z = None
        else:
            z = None

        if t is None or len(t) != len(x):
            t = np.linspace(0.0, float(max(len(x) - 1, 1)), num=len(x), dtype=np.float64)
        lat_disp = None
        lon_disp = None
        alt_disp = None
        if display_lat is not None:
            try:
                arr = np.asarray(display_lat, dtype=np.float64)
                if len(arr) == len(x):
                    lat_disp = arr
            except Exception:
                lat_disp = None
        if display_lon is not None:
            try:
                arr = np.asarray(display_lon, dtype=np.float64)
                if len(arr) == len(x):
                    lon_disp = arr
            except Exception:
                lon_disp = None
        if display_alt is not None:
            try:
                arr = np.asarray(display_alt, dtype=np.float64)
                if len(arr) == len(x):
                    alt_disp = arr
            except Exception:
                alt_disp = None
        mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(t)
        if z is not None and len(z) == len(x):
            mask = mask & np.isfinite(z)
        else:
            z = None

        x = x[mask]
        y = y[mask]
        t = t[mask]
        if z is not None:
            z = z[mask]
        if lat_disp is not None:
            lat_disp = lat_disp[mask]
        if lon_disp is not None:
            lon_disp = lon_disp[mask]
        if alt_disp is not None:
            alt_disp = alt_disp[mask]
        if len(x) < 2:
            return False

        self.plot.setTitle(title)
        self.plot.setLabel('bottom', 'North (m)')
        self.plot.setLabel('left', 'East (m)')
        self.is_time_plot = False
        self.is_fft_plot = False
        self.plot.setXLink(None)
        self.v_line.hide()
        self.overlay_label.hide()
        self.plot.getViewBox().setMouseEnabled(x=True, y=True)
        self.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode)

        self._flight_path_2d_curve_item = self.plot.plot(
            x,
            y,
            name="2D Flight Path",
            pen=pg.mkPen("#2E86DE", width=1.8, style=Qt.SolidLine),
            autoDownsample=False,
        )
        self._flight_path_2d_start_item = pg.ScatterPlotItem(
            [float(x[0])],
            [float(y[0])],
            symbol='o',
            size=7,
            pen=pg.mkPen(self._path_takeoff_border_qcolor(), width=1.2),
            brush=pg.mkBrush(self._path_takeoff_fill_qcolor()),
        )
        self._flight_path_2d_end_item = pg.ScatterPlotItem(
            [float(x[-1])],
            [float(y[-1])],
            symbol='o',
            size=7,
            pen=pg.mkPen(self._path_landing_border_qcolor(), width=1.2),
            brush=pg.mkBrush(self._path_landing_fill_qcolor()),
        )
        marker_pen = pg.mkPen(self._path_cursor_border_qcolor(), width=1.8)
        marker_brush = pg.mkBrush(self._path_cursor_fill_qcolor())
        self._flight_path_2d_marker_item = pg.ScatterPlotItem(
            [],
            [],
            symbol='o',
            size=9,
            pen=marker_pen,
            brush=marker_brush,
        )
        self.plot.addItem(self._flight_path_2d_start_item)
        self.plot.addItem(self._flight_path_2d_end_item)
        self.plot.addItem(self._flight_path_2d_marker_item)

        self._flight_path_2d_state = {
            "time": t,
            "x": x,
            "y": y,
            "z": z,
            "display_lat": lat_disp,
            "display_lon": lon_disp,
            "display_alt": alt_disp,
            "coord_labels": coord_labels if isinstance(coord_labels, (tuple, list)) and len(coord_labels) == 2 else ("North", "East"),
        }
        self._flight_path_2d_enabled = True
        self._sync_workspace_time_range(t)
        is_dark = False
        try:
            is_dark = self.main_window.theme_combo.currentText() == "Dark Mode"
        except Exception:
            is_dark = False
        self.apply_theme_to_2d_flight_path(is_dark)
        self.plot.autoRange(padding=0.06)

        if self.workspace is not None:
            self.update_2d_flight_path_cursor_from_time(float(self.workspace.time_cursor.value()))
        else:
            self._set_2d_flight_path_cursor_index(0, update_workspace_time=False, show_label=True)
        return True

    def _prepare_for_3d_render(self):
        # Clear 2D state without forcing a temporary 3D disable/enable cycle.
        self.layout_special_spec = None
        self._disable_projected_3d_mode()
        self._disable_2d_flight_path_mode()
        self._true_3d_hint.hide()
        self._true_3d_axis_panel.hide()
        self._true_3d_pick_label.hide()
        self.plot.clear()
        self._get_or_create_legend().setVisible(self.legend_visible)
        self.plot.addItem(self.v_line)
        self.v_line.hide()
        self.plotted_signals.clear()
        self.signal_cache.clear()
        self.plot_item_to_uri.clear()
        self._last_overlay_html = ""
        self.overlay_label.hide()

    @staticmethod
    def _matrix4_to_numpy(matrix):
        raw = np.array(matrix.copyDataTo(), dtype=np.float64)
        return raw.reshape((4, 4), order="F")

    def _project_true_3d_points_to_screen(self):
        if self._true_3d_view is None or self._true_3d_points is None or len(self._true_3d_points) == 0:
            return None

        view = self._true_3d_view
        w = float(max(1, view.width()))
        h = float(max(1, view.height()))

        try:
            proj_mat = view.projectionMatrix()
            view_mat = view.viewMatrix()
            proj_np = self._matrix4_to_numpy(proj_mat)
            view_np = self._matrix4_to_numpy(view_mat)
            mvp = proj_np @ view_np
        except Exception:
            return None

        pts = np.asarray(self._true_3d_points, dtype=np.float64)
        hom = np.hstack([pts, np.ones((pts.shape[0], 1), dtype=np.float64)])
        clip = hom @ mvp.T
        w_comp = clip[:, 3]
        valid = np.isfinite(w_comp) & (np.abs(w_comp) > 1e-9)
        if not np.any(valid):
            return None

        ndc = np.zeros((pts.shape[0], 3), dtype=np.float64)
        ndc[valid, 0] = clip[valid, 0] / w_comp[valid]
        ndc[valid, 1] = clip[valid, 1] / w_comp[valid]
        ndc[valid, 2] = clip[valid, 2] / w_comp[valid]

        screen = np.zeros((pts.shape[0], 2), dtype=np.float64)
        screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * w
        screen[:, 1] = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * h
        in_frustum = valid & (ndc[:, 2] >= -1.0) & (ndc[:, 2] <= 1.0)
        return screen, in_frustum

    def _pick_true_3d_nearest_index(self, local_pos):
        projected = self._project_true_3d_points_to_screen()
        if projected is None:
            return None
        screen_points, in_frustum = projected
        if len(screen_points) == 0:
            return None

        px = float(local_pos.x())
        py = float(local_pos.y())
        dx = screen_points[:, 0] - px
        dy = screen_points[:, 1] - py
        dist2 = dx * dx + dy * dy
        if np.any(in_frustum):
            masked = np.where(in_frustum, dist2, np.inf)
        else:
            masked = dist2

        idx = int(np.argmin(masked))
        if not np.isfinite(masked[idx]):
            return None
        # Tolerate loose click because trajectory can be thin at some views.
        if masked[idx] > (30.0 * 30.0):
            return None
        return idx

    def _set_true_3d_cursor_index(self, idx, update_workspace_time=False, show_label=True):
        if self._true_3d_points is None or len(self._true_3d_points) == 0:
            return False
        idx = int(max(0, min(len(self._true_3d_points) - 1, idx)))
        self._true_3d_time_marker_idx = idx

        if self._true_3d_time_marker_outer_item is not None:
            try:
                marker_outer_qc = self._path_cursor_border_qcolor()
                marker_pos = self._true_3d_points[idx:idx + 1]
                self._true_3d_time_marker_outer_item.setData(
                    pos=marker_pos.astype(np.float32),
                    color=self._gl_rgba_array_from_qcolor(marker_outer_qc, 1),
                    size=11.0,
                    pxMode=True,
                )
            except Exception:
                pass

        if self._true_3d_time_marker_item is not None:
            try:
                marker_qc = self._path_cursor_fill_qcolor()
                marker_pos = self._true_3d_points[idx:idx + 1]
                self._true_3d_time_marker_item.setData(
                    pos=marker_pos.astype(np.float32),
                    color=self._gl_rgba_array_from_qcolor(marker_qc, 1),
                    size=7.0,
                    pxMode=True,
                )
            except Exception:
                pass

        if show_label and self._true_3d_abs_points is not None and len(self._true_3d_abs_points) > idx:
            north, east, up = self._true_3d_abs_points[idx]
            if self._true_3d_time_arr is not None and len(self._true_3d_time_arr) > idx:
                t = float(self._true_3d_time_arr[idx])
            else:
                t = float(idx)
            self._true_3d_pick_label.setText(
                f"Time: {t:.2f} s\n"
                f"North: {north:.2f} m\n"
                f"East: {east:.2f} m\n"
                f"Altitude: {up:.2f} m"
            )
            self._true_3d_pick_label.adjustSize()
            pick_x = self.plot_stack.x() + max(6, self.plot_stack.width() - self._true_3d_pick_label.width() - 10)
            pick_y = self.control_layout.geometry().bottom() + 4
            self._true_3d_pick_label.move(int(pick_x), int(pick_y))
            self._true_3d_pick_label.show()

        if update_workspace_time and self.workspace and self._true_3d_time_arr is not None and len(self._true_3d_time_arr) > idx:
            self.workspace.set_current_time(float(self._true_3d_time_arr[idx]), immediate_overlay=True)
        return True

    def update_true_3d_cursor_from_time(self, t):
        if not self._true_3d_enabled or self._true_3d_time_arr is None or len(self._true_3d_time_arr) == 0:
            return
        t_arr = self._true_3d_time_arr
        idx = int(np.searchsorted(t_arr, float(t), side="left"))
        if idx >= len(t_arr):
            idx = len(t_arr) - 1
        elif idx > 0:
            prev_idx = idx - 1
            if abs(float(t_arr[prev_idx]) - float(t)) <= abs(float(t_arr[idx]) - float(t)):
                idx = prev_idx
        self._set_true_3d_cursor_index(idx, update_workspace_time=False, show_label=True)

    def move_overlay_near_cursor(self, x_value):
        if not self.overlay_label.isVisible():
            return

        vb = self.plot.plotItem.vb
        scene_rect = vb.sceneBoundingRect()
        if scene_rect.isEmpty():
            return

        scene_point = vb.mapViewToScene(pg.Point(float(x_value), 0.0))
        # Keep a consistent vertical placement across graph sizes.
        scene_point.setY(scene_rect.top() + scene_rect.height() * 0.14)
        widget_point = self.plot.mapFromScene(scene_point)

        line_x = self.plot.x() + widget_point.x()
        y_pos = self.plot.y() + widget_point.y()
        x_pos = line_x + 10

        min_x = self.plot.x() + 4
        max_x = self.plot.x() + self.plot.width() - self.overlay_label.width() - 4
        min_y = self.plot.y() + 4
        max_y = self.plot.y() + self.plot.height() - self.overlay_label.height() - 4

        if x_pos > max_x:
            x_pos = line_x - self.overlay_label.width() - 10
        x_pos = max(min_x, min(max_x, x_pos))
        y_pos = max(min_y, min(max_y, y_pos))

        self.overlay_label.move(int(x_pos), int(y_pos))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_adaptive_plot_text_scale()
        if self._true_3d_enabled and self._true_3d_hint.isVisible():
            hint_x = self.plot_stack.x() + 6
            hint_y = self.control_layout.geometry().bottom() + 4
            self._true_3d_hint.move(int(hint_x), int(hint_y))
        if self._true_3d_enabled and self._true_3d_axis_panel.isVisible():
            axis_x = self.plot_stack.x() + 6
            axis_y = self.control_layout.geometry().bottom() + self._true_3d_hint.height() + 8
            self._true_3d_axis_panel.move(int(axis_x), int(axis_y))
        if self._true_3d_enabled and self._true_3d_pick_label.isVisible():
            pick_x = self.plot_stack.x() + max(6, self.plot_stack.width() - self._true_3d_pick_label.width() - 10)
            pick_y = self.control_layout.geometry().bottom() + 4
            self._true_3d_pick_label.move(int(pick_x), int(pick_y))
        if self._flight_path_2d_enabled and self._flight_path_2d_pick_label.isVisible():
            pick_x = self.plot_stack.x() + max(6, self.plot_stack.width() - self._flight_path_2d_pick_label.width() - 10)
            pick_y = self.control_layout.geometry().bottom() + 4
            self._flight_path_2d_pick_label.move(int(pick_x), int(pick_y))

    def _ensure_true_3d_view(self):
        if not self._true_3d_available:
            return False
        if self._true_3d_view is None:
            self._true_3d_view = FlightPath3DViewWidget(self.plot_stack)
            self._true_3d_view.setAcceptDrops(True)
            self._true_3d_view.installEventFilter(self)
            self._true_3d_view.setContextMenuPolicy(Qt.CustomContextMenu)
            self._true_3d_view.customContextMenuRequested.connect(self._on_true_3d_context_menu)
            self._true_3d_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.plot_stack.addWidget(self._true_3d_view)
            self.plot_stack.setCurrentWidget(self.plot)
        return True

    def _clear_true_3d_items(self):
        if self._true_3d_view is None:
            return
        for item in self._true_3d_items:
            try:
                self._true_3d_view.removeItem(item)
            except Exception:
                pass
        self._true_3d_items.clear()
        self._true_3d_line_item = None
        self._true_3d_time_marker_outer_item = None
        self._true_3d_time_marker_item = None
        self._true_3d_time_marker_idx = None
        self._true_3d_camera_default = None
        self._true_3d_points = None
        self._true_3d_abs_points = None
        self._true_3d_time_arr = None
        self._true_3d_axis_panel.hide()
        self._true_3d_pick_label.hide()
        self._true_3d_pending_pick = False
        self._true_3d_pick_press_pos = None

    def _disable_true_3d_mode(self):
        if not self._true_3d_enabled:
            return
        self._true_3d_enabled = False
        self._clear_true_3d_items()
        if hasattr(self, "plot_stack"):
            self.plot_stack.setCurrentWidget(self.plot)
        self._true_3d_hint.hide()
        self._true_3d_axis_panel.hide()
        self._true_3d_pick_label.hide()

    def render_true_3d_path(self, x, y, z, title, timestamps=None):
        if not self._ensure_true_3d_view():
            return False

        stack_updates_blocked = False
        if hasattr(self, "plot_stack"):
            try:
                self.plot_stack.setUpdatesEnabled(False)
                stack_updates_blocked = True
            except Exception:
                stack_updates_blocked = False

        try:
            self._prepare_for_3d_render()

            x = np.asarray(x, dtype=np.float64)
            y = np.asarray(y, dtype=np.float64)
            z = np.asarray(z, dtype=np.float64)
            ts = None
            if timestamps is not None:
                try:
                    ts = np.asarray(timestamps, dtype=np.float64)
                except Exception:
                    ts = None
            mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            if ts is not None and len(ts) == len(x):
                mask = mask & np.isfinite(ts)
            x = x[mask]
            y = y[mask]
            z = z[mask]
            if ts is not None and len(ts) == len(mask):
                ts = ts[mask]
            else:
                ts = None
            if len(x) < 2:
                return False

            if ts is None or len(ts) != len(x):
                ts = np.linspace(0.0, float(max(len(x) - 1, 1)), num=len(x), dtype=np.float64)

            # Keep interaction smooth by limiting point count.
            max_points = 5000
            if len(x) > max_points:
                step = max(1, len(x) // max_points)
                x = x[::step]
                y = y[::step]
                z = z[::step]
                if ts is not None:
                    ts = ts[::step]

            # Keep local NEU coordinates directly so origin (0,0,0) stays meaningful.
            x0 = x
            y0 = y
            z0 = z

            data_min_x = float(np.min(x0))
            data_min_y = float(np.min(y0))
            data_min_z = float(np.min(z0))
            data_max_x = float(np.max(x0))
            data_max_y = float(np.max(y0))
            data_max_z = float(np.max(z0))

            # Bounds include origin, so axis frame is always anchored at (0, 0, 0).
            min_x = min(data_min_x, 0.0)
            min_y = min(data_min_y, 0.0)
            min_z = min(data_min_z, 0.0)
            max_x = max(data_max_x, 0.0)
            max_y = max(data_max_y, 0.0)
            max_z = max(data_max_z, 0.0)

            # Avoid fully collapsed axes when one dimension is constant.
            if abs(max_x - min_x) < 1e-9:
                min_x, max_x = -0.5, 0.5
            if abs(max_y - min_y) < 1e-9:
                min_y, max_y = -0.5, 0.5
            if abs(max_z - min_z) < 1e-9:
                min_z, max_z = -0.5, 0.5

            span_x = float(max(max_x - min_x, 1.0))
            span_y = float(max(max_y - min_y, 1.0))
            span_z = float(max(max_z - min_z, 1.0))
            span = max(span_x, span_y, span_z, 1.0)
            half_x = max(abs(min_x), abs(max_x), 1.0)
            half_y = max(abs(min_y), abs(max_y), 1.0)
            half_z = max(abs(min_z), abs(max_z), 1.0)
            span_ref = max(half_x, half_y, half_z, 1.0)

            view = self._true_3d_view
            self._clear_true_3d_items()
            self._true_3d_points = np.column_stack([x0, y0, z0]).astype(np.float32)
            self._true_3d_abs_points = np.column_stack([x, y, z]).astype(np.float64)
            self._true_3d_time_arr = ts
            self._sync_workspace_time_range(ts)
            self._true_3d_line_item = self._build_true_3d_line_item(self._true_3d_points)
            view.addItem(self._true_3d_line_item)
            self._true_3d_items.append(self._true_3d_line_item)

            is_dark = self.main_window.theme_combo.currentText() == "Dark Mode"
            if is_dark:
                grid_main = (0.76, 0.82, 0.92, 0.62)
                grid_side = (0.68, 0.75, 0.88, 0.32)
                axis_txt = (0.92, 0.95, 1.0, 0.95)
            else:
                grid_main = (0.26, 0.33, 0.42, 0.56)
                grid_side = (0.34, 0.40, 0.48, 0.28)
                axis_txt = (0.09, 0.14, 0.20, 0.95)

            # 3-plane coordinate grids for clearer spatial orientation.
            spacing_xy = max((half_x * 2.0) / 12.0, 1.0), max((half_y * 2.0) / 12.0, 1.0), 1.0
            grid_xy = gl.GLGridItem()
            grid_xy.setSpacing(*spacing_xy)
            grid_xy.setSize(half_x * 2.2, half_y * 2.2, 1.0)
            grid_xy.translate(0.0, 0.0, 0.0)
            grid_xy.setColor(grid_main)
            view.addItem(grid_xy)
            self._true_3d_items.append(grid_xy)

            grid_xz = gl.GLGridItem()
            grid_xz.setSpacing(max((half_x * 2.0) / 12.0, 1.0), max((half_z * 2.0) / 10.0, 1.0), 1.0)
            grid_xz.setSize(half_x * 2.2, half_z * 2.2, 1.0)
            grid_xz.rotate(90, 1, 0, 0)
            grid_xz.translate(0.0, 0.0, 0.0)
            grid_xz.setColor(grid_side)
            view.addItem(grid_xz)
            self._true_3d_items.append(grid_xz)

            grid_yz = gl.GLGridItem()
            grid_yz.setSpacing(max((half_y * 2.0) / 12.0, 1.0), max((half_z * 2.0) / 10.0, 1.0), 1.0)
            grid_yz.setSize(half_y * 2.2, half_z * 2.2, 1.0)
            grid_yz.rotate(90, 0, 1, 0)
            grid_yz.translate(0.0, 0.0, 0.0)
            grid_yz.setColor(grid_side)
            view.addItem(grid_yz)
            self._true_3d_items.append(grid_yz)

            # Explicit North/East/Up axes crossing at origin, clipped to frame range.
            axis_scale = 0.3
            axis_min_x, axis_max_x = min_x * axis_scale, max_x * axis_scale
            axis_min_y, axis_max_y = min_y * axis_scale, max_y * axis_scale
            # Keep Z axis matched to frame-box height for altitude readability.
            axis_min_z, axis_max_z = min_z, max_z
            axis_specs = [
                ("North (m)", np.array([[axis_min_x, 0.0, 0.0], [axis_max_x, 0.0, 0.0]], dtype=np.float32), (0.22, 0.55, 0.96, 0.98), np.array([axis_max_x, 0.0, 0.0], dtype=np.float32)),
                ("East (m)", np.array([[0.0, axis_min_y, 0.0], [0.0, axis_max_y, 0.0]], dtype=np.float32), (0.95, 0.58, 0.20, 0.98), np.array([0.0, axis_max_y, 0.0], dtype=np.float32)),
                ("Altitude (m)", np.array([[0.0, 0.0, axis_min_z], [0.0, 0.0, axis_max_z]], dtype=np.float32), (0.34, 0.86, 0.42, 0.98), np.array([0.0, 0.0, axis_max_z], dtype=np.float32)),
            ]
            for label, axis_pos, axis_color, label_pos in axis_specs:
                axis_line = gl.GLLinePlotItem(
                    pos=axis_pos,
                    color=axis_color,
                    width=2.0,
                    antialias=True,
                    mode="lines",
                )
                view.addItem(axis_line)
                self._true_3d_items.append(axis_line)
                if hasattr(gl, "GLTextItem"):
                    try:
                        text_item = gl.GLTextItem(
                            pos=tuple(label_pos.tolist()),
                            color=axis_txt,
                            text=label,
                        )
                        view.addItem(text_item)
                        self._true_3d_items.append(text_item)
                    except Exception:
                        pass

            # Bounding-box frame for spatial reading (similar to 3D analysis panels).
            c000 = np.array([min_x, min_y, min_z], dtype=np.float32)
            c100 = np.array([max_x, min_y, min_z], dtype=np.float32)
            c010 = np.array([min_x, max_y, min_z], dtype=np.float32)
            c110 = np.array([max_x, max_y, min_z], dtype=np.float32)
            c001 = np.array([min_x, min_y, max_z], dtype=np.float32)
            c101 = np.array([max_x, min_y, max_z], dtype=np.float32)
            c011 = np.array([min_x, max_y, max_z], dtype=np.float32)
            c111 = np.array([max_x, max_y, max_z], dtype=np.float32)
            box_segments = np.array(
                [
                    c000, c100, c000, c010, c100, c110, c010, c110,
                    c001, c101, c001, c011, c101, c111, c011, c111,
                    c000, c001, c100, c101, c010, c011, c110, c111,
                ],
                dtype=np.float32,
            )
            box_color = (0.75, 0.78, 0.84, 0.35) if is_dark else (0.28, 0.31, 0.36, 0.35)
            box_item = gl.GLLinePlotItem(
                pos=box_segments,
                color=box_color,
                width=1.2,
                antialias=True,
                mode="lines",
            )
            view.addItem(box_item)
            self._true_3d_items.append(box_item)

            start_end = np.array(
                [
                    [x0[0], y0[0], z0[0]],
                    [x0[-1], y0[-1], z0[-1]],
                ],
                dtype=np.float32,
            )
            takeoff_qc = self._path_takeoff_fill_qcolor()
            landing_qc = self._path_landing_fill_qcolor()
            start_end_colors = np.array(
                [
                    [takeoff_qc.redF(), takeoff_qc.greenF(), takeoff_qc.blueF(), 1.0],  # start: orange
                    [landing_qc.redF(), landing_qc.greenF(), landing_qc.blueF(), 1.0],  # end: green
                ],
                dtype=np.float32,
            )
            marker_item = gl.GLScatterPlotItem(pos=start_end, color=start_end_colors, size=9.0, pxMode=True)
            view.addItem(marker_item)
            self._true_3d_items.append(marker_item)

            marker_outer_qc = self._path_cursor_border_qcolor()
            self._true_3d_time_marker_outer_item = gl.GLScatterPlotItem(
                pos=self._true_3d_points[:1],
                color=self._gl_rgba_array_from_qcolor(marker_outer_qc, 1),
                size=11.0,
                pxMode=True,
            )
            try:
                self._true_3d_time_marker_outer_item.setGLOptions("opaque")
            except Exception:
                pass
            view.addItem(self._true_3d_time_marker_outer_item)
            self._true_3d_items.append(self._true_3d_time_marker_outer_item)

            marker_qc = self._path_cursor_fill_qcolor()
            self._true_3d_time_marker_item = gl.GLScatterPlotItem(
                pos=self._true_3d_points[:1],
                color=self._gl_rgba_array_from_qcolor(marker_qc, 1),
                size=7.0,
                pxMode=True,
            )
            try:
                self._true_3d_time_marker_item.setGLOptions("opaque")
            except Exception:
                pass
            view.addItem(self._true_3d_time_marker_item)
            self._true_3d_items.append(self._true_3d_time_marker_item)

            self.apply_theme_to_3d(is_dark)

            if hasattr(self, "plot_stack"):
                self.plot_stack.setCurrentWidget(view)
            camera_center = QVector3D(0.0, 0.0, 0.0)
            camera_distance = max(span_ref * 3.1, span * 1.9)
            try:
                view.setCameraPosition(
                    pos=camera_center,
                    distance=camera_distance,
                    elevation=27,
                    azimuth=-40,
                )
            except Exception:
                pass
            view.update()

            # Some environments can load OpenGL module but fail to create a valid context.
            if hasattr(view, "isValid") and callable(view.isValid) and not view.isValid():
                print("[3D] GL context invalid; fallback to projected 3D.")
                self._disable_true_3d_mode()
                return False

            self._true_3d_enabled = True
            self.is_time_plot = False
            self.is_fft_plot = False
            self._true_3d_title = title
            self.v_line.hide()
            self.overlay_label.hide()
            self._sync_3d_style_to_layout_spec()

            self._true_3d_hint.setText(
                f"{title} | Axis: X=North, Y=East, Z=Up | Start=Red End=Green\n"
                "MMB+Drag: Rotate | Shift+Drag: Pan | Shift+Click: Time Position | Wheel: Zoom"
            )
            self._true_3d_hint.adjustSize()
            hint_x = self.plot_stack.x() + 6
            hint_y = self.control_layout.geometry().bottom() + 4
            self._true_3d_hint.move(int(hint_x), int(hint_y))
            self._true_3d_hint.show()
            self._true_3d_axis_panel.setText(
                "Coordinate Frame (Origin: 0,0,0)\n"
                "Units: meters (m)\n"
                f"X (North): {float(np.min(x)):.1f} .. {float(np.max(x)):.1f} m\n"
                f"Y (East):  {float(np.min(y)):.1f} .. {float(np.max(y)):.1f} m\n"
                f"Z (Alt):   {float(np.min(z)):.1f} .. {float(np.max(z)):.1f} m"
            )
            self._true_3d_axis_panel.adjustSize()
            axis_x = self.plot_stack.x() + 6
            axis_y = self.control_layout.geometry().bottom() + self._true_3d_hint.height() + 8
            self._true_3d_axis_panel.move(int(axis_x), int(axis_y))
            self._true_3d_axis_panel.setVisible(self.legend_visible)
            self._true_3d_camera_default = {
                "distance": camera_distance,
                "elevation": 27.0,
                "azimuth": -40.0,
                "center": camera_center,
            }
            if self.workspace and self._true_3d_time_arr is not None and len(self._true_3d_time_arr) > 0:
                try:
                    self.update_true_3d_cursor_from_time(float(self.workspace.time_cursor.value()))
                except Exception:
                    self._set_true_3d_cursor_index(0, update_workspace_time=False, show_label=True)
            else:
                self._set_true_3d_cursor_index(0, update_workspace_time=False, show_label=True)
            print(f"[3D] true_3d rendered points={len(self._true_3d_points)} span={span:.3f}")
            return True

        except Exception as e:
            print(f"[3D] true_3d render failed: {e}")
            traceback.print_exc()
            self._disable_true_3d_mode()
            return False
        finally:
            if stack_updates_blocked:
                try:
                    self.plot_stack.setUpdatesEnabled(True)
                    self.plot_stack.update()
                except Exception:
                    pass

    def render_3d_path(self, x, y, z, title, timestamps=None):
        if self._true_3d_available:
            try:
                ok = self.render_true_3d_path(x, y, z, title, timestamps=timestamps)
                if ok:
                    return True
            except Exception as e:
                print(f"[3D] true_3d exception, fallback projected: {e}")
                traceback.print_exc()
        return self.render_projected_3d_path(x, y, z, title, timestamps=timestamps)

    def _disable_projected_3d_mode(self):
        if not self._projected_3d_enabled:
            return
        self._projected_3d_enabled = False
        self._projected_3d_state = None
        self._projected_3d_line_item = None
        self._projected_3d_scatter_item = None
        self._projected_3d_start_item = None
        self._projected_3d_end_item = None
        self._projected_3d_time_marker_item = None
        self._projected_3d_info_item = None
        self._projected_3d_drag_mode = None
        self._projected_3d_last_pos = None
        self._projected_3d_last_view_update = 0.0
        self._projected_3d_pending_pick = False
        self._projected_3d_pick_press_pos = None
        self.plot.getViewBox().setMouseEnabled(x=True, y=True)
        self.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode)

    def render_projected_3d_path(self, x, y, z, title, timestamps=None):
        self.clear_plot_data()
        self.plot.setTitle(title)
        self._true_3d_title = title
        self.is_time_plot = False
        self.is_fft_plot = False
        self.plot.setXLink(None)
        self.v_line.hide()
        self.overlay_label.hide()
        self.plot.getViewBox().setMouseEnabled(x=False, y=False)

        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        ts = None
        if timestamps is not None:
            try:
                ts = np.asarray(timestamps, dtype=np.float64)
            except Exception:
                ts = None
        if len(x) == 0:
            return False

        if ts is not None and len(ts) == len(x):
            finite_mask = np.isfinite(ts)
            if np.any(~finite_mask):
                x = x[finite_mask]
                y = y[finite_mask]
                z = z[finite_mask]
                ts = ts[finite_mask]
            if len(x) == 0:
                return False
        else:
            ts = np.linspace(0.0, float(max(len(x) - 1, 1)), num=len(x), dtype=np.float64)

        center_x = float(np.mean(x))
        center_y = float(np.mean(y))
        center_z = float(np.mean(z))

        z_min = float(np.min(z))
        z_max = float(np.max(z))
        if z_max > z_min:
            norm = (z - z_min) / (z_max - z_min)
        else:
            norm = np.zeros_like(z)

        brushes = []
        for ni in norm:
            hue = int(max(0, min(240, (1.0 - float(ni)) * 240.0)))
            brushes.append(pg.mkBrush(QColor.fromHsv(hue, 255, 220)))

        self._projected_3d_state = {
            "x": x,
            "y": y,
            "z": z,
            "timestamps": ts,
            "center_x": center_x,
            "center_y": center_y,
            "center_z": center_z,
            "yaw_deg": -35.0,
            "pitch_deg": 20.0,
            "zoom": 1.0,
            "pan_x": 0.0,
            "pan_y": 0.0,
            "z_min": z_min,
            "z_max": z_max,
            "brushes": brushes,
            "proj_x": None,
            "proj_y": None,
            "cursor_idx": 0,
        }
        self._sync_workspace_time_range(ts)
        self._projected_3d_enabled = True
        self._projected_3d_drag_mode = None
        self._projected_3d_last_pos = None
        self._projected_3d_last_view_update = 0.0

        self._projected_3d_line_item = self.plot.plot(
            [],
            [],
            name="3D Flight Path",
            pen=pg.mkPen(self._3d_path_style["color"], width=max(1.0, float(self._3d_path_style["width"]))),
            autoDownsample=True,
        )
        self._projected_3d_scatter_item = pg.ScatterPlotItem(size=4, pen=None)
        self.plot.addItem(self._projected_3d_scatter_item)
        self._projected_3d_start_item = pg.ScatterPlotItem(
            [],
            [],
            symbol='o',
            size=7,
            pen=pg.mkPen(self._path_takeoff_border_qcolor(), width=1.2),
            brush=pg.mkBrush(self._path_takeoff_fill_qcolor()),
        )
        self.plot.addItem(self._projected_3d_start_item)
        self._projected_3d_end_item = pg.ScatterPlotItem(
            [],
            [],
            symbol='o',
            size=7,
            pen=pg.mkPen(self._path_landing_border_qcolor(), width=1.2),
            brush=pg.mkBrush(self._path_landing_fill_qcolor()),
        )
        self.plot.addItem(self._projected_3d_end_item)
        marker_pen = pg.mkPen(self._path_cursor_border_qcolor(), width=1.8)
        marker_brush = pg.mkBrush(self._path_cursor_fill_qcolor())
        self._projected_3d_time_marker_item = pg.ScatterPlotItem(
            [],
            [],
            symbol='o',
            size=9,
            pen=marker_pen,
            brush=marker_brush,
        )
        self.plot.addItem(self._projected_3d_time_marker_item)
        self._projected_3d_info_item = pg.TextItem("", color="#5f6f82", anchor=(0, 1))
        self.plot.addItem(self._projected_3d_info_item)
        self._apply_projected_3d_style()
        self.plot.setLabel('bottom', 'Projected X')
        self.plot.setLabel('left', 'Projected Y')
        self._update_projected_3d_projection()
        return True

    def _update_projected_3d_projection(self):
        state = self._projected_3d_state
        if not self._projected_3d_enabled or not state:
            return

        x = state["x"] - state["center_x"]
        y = state["y"] - state["center_y"]
        z = state["z"] - state["center_z"]

        yaw = np.deg2rad(state["yaw_deg"])
        pitch = np.deg2rad(state["pitch_deg"])

        cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
        x1 = cos_yaw * x - sin_yaw * y
        y1 = sin_yaw * x + cos_yaw * y
        z1 = z

        cos_pitch, sin_pitch = np.cos(pitch), np.sin(pitch)
        y2 = cos_pitch * y1 - sin_pitch * z1
        z2 = sin_pitch * y1 + cos_pitch * z1

        proj_x = x1 * state["zoom"] + state["pan_x"]
        proj_y = y2 * state["zoom"] + state["pan_y"]
        state["proj_x"] = proj_x
        state["proj_y"] = proj_y

        self._projected_3d_line_item.setData(proj_x, proj_y)
        self._projected_3d_scatter_item.setData(
            x=proj_x,
            y=proj_y,
            brush=state["brushes"],
            size=4,
            pen=None,
        )
        if self._projected_3d_start_item is not None and len(proj_x) > 0:
            self._projected_3d_start_item.setData([float(proj_x[0])], [float(proj_y[0])])
        if self._projected_3d_end_item is not None and len(proj_x) > 0:
            self._projected_3d_end_item.setData([float(proj_x[-1])], [float(proj_y[-1])])

        info = (
            f"MMB+Drag: Rotate | Shift+Drag: Pan | Wheel: Zoom\n"
            f"Yaw: {state['yaw_deg']:.1f}°, Pitch: {state['pitch_deg']:.1f}°, Zoom: {state['zoom']:.2f}x"
        )
        self._projected_3d_info_item.setText(info)
        self._projected_3d_info_item.setPos(float(np.min(proj_x)), float(np.max(proj_y)))
        now = time.perf_counter()
        if (now - self._projected_3d_last_view_update) > 0.08:
            self.plot.autoRange(padding=0.05)
            self._projected_3d_last_view_update = now

        if self._projected_3d_enabled and self.workspace is not None:
            try:
                self.update_projected_3d_cursor_from_time(float(self.workspace.time_cursor.value()), show_label=False)
            except Exception:
                pass

    def _pick_projected_3d_nearest_index(self, local_pos):
        if not self._projected_3d_enabled or not isinstance(self._projected_3d_state, dict):
            return None
        proj_x = self._projected_3d_state.get("proj_x")
        proj_y = self._projected_3d_state.get("proj_y")
        if proj_x is None or proj_y is None or len(proj_x) == 0:
            return None
        vb = self.plot.plotItem.vb
        scene_pos = self.plot.viewport().mapToScene(local_pos.toPoint())
        if not vb.sceneBoundingRect().contains(scene_pos):
            return None
        view_pt = vb.mapSceneToView(scene_pos)
        dx = proj_x - float(view_pt.x())
        dy = proj_y - float(view_pt.y())
        idx = int(np.argmin(dx * dx + dy * dy))
        return idx

    def _set_projected_3d_cursor_index(self, idx, update_workspace_time=False, show_label=True):
        if not self._projected_3d_enabled or not isinstance(self._projected_3d_state, dict):
            return False
        state = self._projected_3d_state
        proj_x = state.get("proj_x")
        proj_y = state.get("proj_y")
        if proj_x is None or proj_y is None or len(proj_x) == 0:
            return False
        idx = int(max(0, min(len(proj_x) - 1, idx)))
        state["cursor_idx"] = idx

        if self._projected_3d_time_marker_item is not None:
            marker_pen = pg.mkPen(self._path_cursor_border_qcolor(), width=1.8)
            marker_brush = pg.mkBrush(self._path_cursor_fill_qcolor())
            self._projected_3d_time_marker_item.setData(
                [float(proj_x[idx])],
                [float(proj_y[idx])],
                symbol='o',
                size=9,
                pen=marker_pen,
                brush=marker_brush,
            )

        t_arr = state.get("timestamps")
        x_arr = state.get("x")
        y_arr = state.get("y")
        z_arr = state.get("z")
        if show_label and t_arr is not None and len(t_arr) > idx and x_arr is not None and y_arr is not None and z_arr is not None:
            t_val = float(t_arr[idx])
            self._true_3d_pick_label.setText(
                f"Time: {t_val:.2f} s\n"
                f"North: {float(x_arr[idx]):.2f} m\n"
                f"East: {float(y_arr[idx]):.2f} m\n"
                f"Altitude: {float(z_arr[idx]):.2f} m"
            )
            self._true_3d_pick_label.adjustSize()
            pick_x = self.plot_stack.x() + max(6, self.plot_stack.width() - self._true_3d_pick_label.width() - 10)
            pick_y = self.control_layout.geometry().bottom() + 4
            self._true_3d_pick_label.move(int(pick_x), int(pick_y))
            self._true_3d_pick_label.show()

        if update_workspace_time and self.workspace and t_arr is not None and len(t_arr) > idx:
            self.workspace.set_current_time(float(t_arr[idx]), immediate_overlay=True)
        return True

    def update_projected_3d_cursor_from_time(self, t, show_label=True):
        if not self._projected_3d_enabled or not isinstance(self._projected_3d_state, dict):
            return
        t_arr = self._projected_3d_state.get("timestamps")
        if t_arr is None or len(t_arr) == 0:
            return
        idx = self._nearest_time_index(t_arr, t)
        if idx is None:
            return
        self._set_projected_3d_cursor_index(idx, update_workspace_time=False, show_label=show_label)

    def eventFilter(self, obj, event):
        if self._true_3d_view is not None and obj is self._true_3d_view:
            etype = event.type()
            if etype == QEvent.ContextMenu:
                self.main_window.last_active_plot = self
                try:
                    global_pos = event.globalPos()
                except Exception:
                    global_pos = self._true_3d_view.mapToGlobal(event.pos())
                self.show_context_menu(self.mapFromGlobal(global_pos))
                event.accept()
                return True
            if etype == QEvent.MouseButtonPress:
                if (
                    event.button() == Qt.LeftButton
                    and bool(event.modifiers() & Qt.ShiftModifier)
                    and self._true_3d_enabled
                ):
                    self._true_3d_pending_pick = True
                    self._true_3d_pick_press_pos = event.position()
                    return False
            if etype == QEvent.MouseMove:
                if self._true_3d_pending_pick and self._true_3d_pick_press_pos is not None:
                    if (event.position() - self._true_3d_pick_press_pos).manhattanLength() > QApplication.startDragDistance():
                        self._true_3d_pending_pick = False
                return False
            if etype == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self._true_3d_pending_pick:
                    self._true_3d_pending_pick = False
                    idx = self._pick_true_3d_nearest_index(event.position())
                    if idx is not None:
                        self._set_true_3d_cursor_index(idx, update_workspace_time=True, show_label=True)
                        event.accept()
                self._true_3d_pending_pick = False
                self._true_3d_pick_press_pos = None
                return False
            if etype in (QEvent.DragEnter, QEvent.DragMove):
                if self._signal_uris_from_mime(event.mimeData()):
                    self._set_drop_highlight(True)
                    event.acceptProposedAction()
                    return True
            elif etype == QEvent.DragLeave:
                self._set_drop_highlight(False)
                event.accept()
                return True
            elif etype == QEvent.Drop:
                self.main_window.last_active_plot = self
                uris = self._signal_uris_from_mime(event.mimeData())
                prefer_curve_popup = self._prefers_curve_popup_from_mime(event.mimeData())
                rendered = self._apply_signal_uris(uris, prefer_curve_popup=prefer_curve_popup)
                self._set_drop_highlight(False)
                print(f"[DND][Plot][GL3D] drop uris={len(uris)} rendered={rendered}")
                if rendered:
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True

        if obj is self.plot.viewport() and self._projected_3d_enabled:
            etype = event.type()
            if etype == QEvent.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    self.main_window.last_active_plot = self
                    global_pos = self.plot.viewport().mapToGlobal(event.position().toPoint())
                    self.show_context_menu(self.mapFromGlobal(global_pos))
                    event.accept()
                    return True
                is_shift = bool(event.modifiers() & Qt.ShiftModifier)
                if event.button() == Qt.LeftButton and is_shift:
                    # Shift+Left click: pick current position. Shift+Left drag: pan.
                    self._projected_3d_pending_pick = True
                    self._projected_3d_pick_press_pos = event.position()
                    self._projected_3d_drag_mode = None
                    event.accept()
                    return True
                if event.button() == Qt.MiddleButton and not is_shift:
                    self._projected_3d_drag_mode = "rotate"
                elif is_shift and event.button() in (Qt.LeftButton, Qt.MiddleButton):
                    self._projected_3d_drag_mode = "pan"
                if self._projected_3d_drag_mode:
                    self._projected_3d_last_pos = event.position()
                    event.accept()
                    return True
            elif etype == QEvent.MouseMove:
                pos = event.position()
                if self._projected_3d_pending_pick and self._projected_3d_pick_press_pos is not None:
                    if (pos - self._projected_3d_pick_press_pos).manhattanLength() > QApplication.startDragDistance():
                        self._projected_3d_pending_pick = False
                        self._projected_3d_drag_mode = "pan"
                        self._projected_3d_last_pos = self._projected_3d_pick_press_pos
                if self._projected_3d_drag_mode:
                    if self._projected_3d_last_pos is None:
                        self._projected_3d_last_pos = pos
                    dx = float(pos.x() - self._projected_3d_last_pos.x())
                    dy = float(pos.y() - self._projected_3d_last_pos.y())
                    state = self._projected_3d_state
                    if self._projected_3d_drag_mode == "rotate":
                        state["yaw_deg"] += dx * 0.5
                        state["pitch_deg"] = float(np.clip(state["pitch_deg"] + dy * 0.35, -85.0, 85.0))
                    else:
                        pan_scale = max(0.1, state["zoom"]) * 0.75
                        state["pan_x"] += dx * pan_scale
                        state["pan_y"] -= dy * pan_scale
                    self._projected_3d_last_pos = pos
                    self._update_projected_3d_projection()
                    event.accept()
                    return True
            elif etype == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self._projected_3d_pending_pick:
                    self._projected_3d_pending_pick = False
                    idx = self._pick_projected_3d_nearest_index(event.position())
                    self._projected_3d_pick_press_pos = None
                    if idx is not None:
                        self._set_projected_3d_cursor_index(idx, update_workspace_time=True, show_label=True)
                        event.accept()
                        return True
                if self._projected_3d_drag_mode and event.button() in (Qt.LeftButton, Qt.MiddleButton):
                    self._projected_3d_drag_mode = None
                    self._projected_3d_last_pos = None
                    self._projected_3d_pick_press_pos = None
                    self._projected_3d_pending_pick = False
                    event.accept()
                    return True
            elif etype == QEvent.Wheel:
                delta = event.angleDelta().y()
                if delta != 0:
                    zoom_factor = 1.1 if delta > 0 else 0.9
                    state = self._projected_3d_state
                    state["zoom"] = float(np.clip(state["zoom"] * zoom_factor, 0.2, 6.0))
                    self._update_projected_3d_projection()
                    event.accept()
                    return True

        if obj is self.plot.viewport():
            etype = event.type()
            if etype in (QEvent.DragEnter, QEvent.DragMove):
                if self._signal_uris_from_mime(event.mimeData()):
                    self._set_drop_highlight(True)
                    event.acceptProposedAction()
                    return True
            elif etype == QEvent.DragLeave:
                self._set_drop_highlight(False)
                event.accept()
                return True
            elif etype == QEvent.Drop:
                self.main_window.last_active_plot = self
                uris = self._signal_uris_from_mime(event.mimeData())
                prefer_curve_popup = self._prefers_curve_popup_from_mime(event.mimeData())
                rendered = self._apply_signal_uris(uris, prefer_curve_popup=prefer_curve_popup)
                self._set_drop_highlight(False)
                print(f"[DND][Plot][Viewport] drop uris={len(uris)} rendered={rendered}")
                if rendered:
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True

        return super().eventFilter(obj, event)

    def on_mouse_click(self, evt):
        self.main_window.last_active_plot = self
        if self._flight_path_2d_enabled and evt.button() == Qt.LeftButton and (evt.modifiers() & Qt.ShiftModifier):
            vb = self.plot.plotItem.vb
            if vb.sceneBoundingRect().contains(evt.scenePos()) and isinstance(self._flight_path_2d_state, dict):
                mouse_point = vb.mapSceneToView(evt.scenePos())
                x_arr = self._flight_path_2d_state.get("x")
                y_arr = self._flight_path_2d_state.get("y")
                t_arr = self._flight_path_2d_state.get("time")
                if x_arr is not None and y_arr is not None and t_arr is not None and len(x_arr) > 0:
                    dx = x_arr - float(mouse_point.x())
                    dy = y_arr - float(mouse_point.y())
                    idx = int(np.argmin(dx * dx + dy * dy))
                    self._set_2d_flight_path_cursor_index(idx, update_workspace_time=True, show_label=True)
                    evt.accept()
            return
        if self._true_3d_enabled:
            return
        if self._projected_3d_enabled:
            return
        if evt.button() == Qt.LeftButton and (evt.modifiers() & Qt.ShiftModifier):
            vb = self.plot.plotItem.vb
            if vb.sceneBoundingRect().contains(evt.scenePos()):
                mousePoint = vb.mapSceneToView(evt.scenePos())
                self.workspace.set_current_time(mousePoint.x(), immediate_overlay=True)
                evt.accept()

    def dragEnterEvent(self, event):
        if self._signal_uris_from_mime(event.mimeData()):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
            return
        event.ignore()
        self._set_drop_highlight(False)

    def dragLeaveEvent(self, event):
        self._set_drop_highlight(False)
        event.accept()
            
    def dropEvent(self, event):
        self.main_window.last_active_plot = self
        uris = self._signal_uris_from_mime(event.mimeData())
        prefer_curve_popup = self._prefers_curve_popup_from_mime(event.mimeData())
        rendered = self._apply_signal_uris(uris, prefer_curve_popup=prefer_curve_popup)
        self._set_drop_highlight(False)
        print(f"[DND][Plot] drop uris={len(uris)} rendered={rendered}")
        if rendered:
            event.acceptProposedAction()
        else:
            event.ignore()

    def render_signal(self, file_name, topic_name, signal_name, x_axis_col="timestamp_sec", color=None, is_fft=False):
        uri = f"{file_name}|{topic_name}|{signal_name}|{x_axis_col}|{is_fft}"
        if uri in self.plotted_signals:
            return True
        self.layout_special_spec = None
        self._disable_2d_flight_path_mode()
        self._disable_true_3d_mode()
        self._disable_projected_3d_mode()

        is_custom_series = (topic_name == self.main_window.CUSTOM_SERIES_TOPIC)

        try:
            if is_custom_series:
                xy = self.main_window._get_custom_series_xy(file_name, signal_name)
                if xy is None:
                    return False
                x, y = xy
            else:
                dataset = self.main_window.loaded_datasets.get(file_name)
                if not dataset:
                    return False
                topic = dataset.topics.get(topic_name)
                if not topic:
                    return False
                x = topic.dataframe[x_axis_col].to_numpy()
                y = topic.dataframe[signal_name].to_numpy()
            
            self.is_time_plot = (x_axis_col == "timestamp_sec" and not is_fft)

            if is_fft:
                self.is_fft_plot = True
                self.plot.setXLink(None)
                self.v_line.hide()
                from engines.math_engine import MathEngine
                x, y = MathEngine.compute_fft(x, y)
                if len(x) == 0:
                    return False
                self.plot.setLabel('bottom', 'Frequency (Hz)')
                self.plot.setLabel('left', 'Amplitude')
            elif not self.is_time_plot:
                self.plot.setXLink(None)
                self.v_line.hide()
            else:
                was_uninitialized_range = (
                    self.workspace.global_min_x is None or self.workspace.global_max_x is None
                )
                self.workspace.expand_time_range(x)
                if (
                    was_uninitialized_range
                    and self.workspace.global_min_x is not None
                    and self.workspace.global_max_x is not None
                ):
                    self.workspace.set_time_range(
                        self.workspace.global_min_x,
                        self.workspace.global_max_x,
                        clamp_to_global=False,
                    )
                self.v_line.show()
                if self.workspace.master_time_plot is None:
                    self.workspace.master_time_plot = self
                elif self != self.workspace.master_time_plot:
                    self.plot.setXLink(self.workspace.master_time_plot.plot)

            is_setpoint_signal = (
                not is_custom_series
                and
                not is_fft
                and (
                    "setpoint" in topic_name.lower()
                    or "_sp" in signal_name.lower()
                    or signal_name.lower().endswith("_sp")
                    or "q_d" in signal_name.lower()
                )
            )

            if color:
                final_color = color
            elif is_setpoint_signal:
                final_color = "#FF4D4D"
            else:
                final_color = ColorManager.get_color(topic_name, signal_name)

            qcolor = QColor(final_color)
            pen_style = Qt.SolidLine
            pen_width = 1.6

            if is_setpoint_signal:
                # Default SP style: red solid line.
                pen_style = Qt.SolidLine
                pen_width = 2.0
                qcolor.setAlphaF(1.0)
            else:
                qcolor.setAlphaF(0.6)
                if is_fft:
                    pen_width = 1.0

            pen = pg.mkPen(color=qcolor, width=pen_width, style=pen_style)
            short_fname = file_name[:8] + ".." if len(file_name) > 10 else file_name
            legend_name = f"[{short_fname}] {topic_name}.{signal_name}"
            legend = self._get_or_create_legend()
            legend.setVisible(self.legend_visible)
            
            plot_item = self.plot.plot(x, y, name=legend_name, pen=pen, autoDownsample=True)
            is_discrete_signal = False
            if not is_fft and len(y) > 0:
                if np.issubdtype(y.dtype, np.floating):
                    y_valid = y[np.isfinite(y)]
                else:
                    y_valid = y
                if len(y_valid) > 0:
                    # Large arrays use sampling for quick type inference.
                    if len(y_valid) > 50000:
                        step = max(1, len(y_valid) // 50000)
                        y_sample = y_valid[::step]
                    else:
                        y_sample = y_valid
                    unique_vals = np.unique(y_sample)
                    if len(unique_vals) <= 6 and np.all(np.isclose(unique_vals, np.round(unique_vals), atol=1e-6)):
                        is_discrete_signal = True
            # Time-series only: clip/downsample works well when X is monotonic.
            # 2D path like (east,north) is non-monotonic and can disappear if clipped.
            if self.is_time_plot and not is_discrete_signal:
                plot_item.setDownsampling(auto=True, method='peak')
                plot_item.setClipToView(True)
            else:
                plot_item.setDownsampling(auto=False)
                plot_item.setClipToView(False)
            self.plotted_signals[uri] = plot_item
            self.plot_item_to_uri[plot_item] = uri
            if len(x) > 0 and len(y) > 0:
                x_is_asc = True
                try:
                    x0 = float(x[0])
                    x1 = float(x[-1])
                    x_is_asc = x1 >= x0
                except Exception:
                    x_is_asc = True
                self.signal_cache[uri] = {
                    "x": x,
                    "y": y,
                    "xmin": min(x[0], x[-1]),
                    "xmax": max(x[0], x[-1]),
                    "signal_name": signal_name,
                    "color": QColor(final_color).name(),
                    "_x_asc": x_is_asc,
                    "_last_idx": None,
                    "_last_t": None,
                }
            self._apply_adaptive_plot_text_scale()
            return True
            
        except Exception as e:
            print(f"\n[GUI] 렌더링 실패 ({topic_name}.{signal_name}): {e}")
            traceback.print_exc()
            return False

    def show_context_menu(self, pos):
        self.main_window.last_active_plot = self
        menu = QMenu(self)

        color_actions = {}
        style_actions = {}
        width_actions = {}
        has_2d_signals = bool(self.plotted_signals)
        has_3d_path = bool(self._true_3d_enabled or self._projected_3d_enabled)
        style_options = [
            ("Solid Line", "solid"),
            ("Dash Line", "dash"),
            ("Dense Dash Line", "dense_dash"),
            ("Dot Line", "dot"),
            ("Dash-Dot Line", "dash_dot"),
        ]
        width_options = [
            ("1.0 px", 1.0),
            ("1.5 px", 1.5),
            ("2.0 px", 2.0),
            ("2.5 px", 2.5),
            ("3.0 px", 3.0),
            ("4.0 px", 4.0),
        ]

        # 선 색상/스타일 변경 하위 메뉴(Sub-menu) 동적 생성
        if has_2d_signals or has_3d_path:
            color_menu = menu.addMenu("선 색상 변경 (Change Line Color)")
            style_menu = menu.addMenu("선 스타일 변경 (Change Line Style)")
            width_menu = menu.addMenu("선 두께 변경 (Change Line Width)")

            if has_2d_signals:
                for uri, plot_item in self.plotted_signals.items():
                    signal_name = uri.split('|')[2]
                    act = color_menu.addAction(f"{signal_name} 색상 변경")
                    color_actions[act] = ("2d", plot_item)

                    sig_style_menu = style_menu.addMenu(f"{signal_name}")
                    for style_label, style_key in style_options:
                        style_act = sig_style_menu.addAction(style_label)
                        style_actions[style_act] = ("2d", plot_item, style_key)

                    sig_width_menu = width_menu.addMenu(f"{signal_name}")
                    for width_label, width_value in width_options:
                        width_act = sig_width_menu.addAction(width_label)
                        width_actions[width_act] = ("2d", plot_item, width_value)

            if has_3d_path:
                act_3d_color = color_menu.addAction("3D Flight Path 색상 변경")
                color_actions[act_3d_color] = ("3d", None)

                style_3d_menu = style_menu.addMenu("3D Flight Path")
                for style_label, style_key in style_options:
                    style_act = style_3d_menu.addAction(style_label)
                    style_actions[style_act] = ("3d", None, style_key)

                width_3d_menu = width_menu.addMenu("3D Flight Path")
                for width_label, width_value in width_options:
                    width_act = width_3d_menu.addAction(width_label)
                    width_actions[width_act] = ("3d", None, width_value)

            menu.addSeparator()

        action_copy = menu.addAction("그래프 이미지 복사 (Copy to Clipboard)")
        menu.addSeparator()
        
        action_stats = menu.addAction("데이터 통계 보기 (View Data Statistics)")
        action_auto_fit = menu.addAction("Auto Fit View")
        menu.addSeparator()
        
        action_v_split = menu.addAction("가로 분할 (상 / 하 추가)")
        action_h_split = menu.addAction("세로 분할 (좌 / 우 추가)")
        menu.addSeparator() 
        action_clear = menu.addAction("이 그래프의 데이터 모두 지우기")
        action_close = menu.addAction("이 그래프 창 닫기")
        
        action = menu.exec(self.mapToGlobal(pos))

        # Handle selected context menu action
        if action in color_actions:
            target_kind, payload = color_actions[action]
            if target_kind == "3d":
                self.change_3d_path_line_color()
            else:
                self.change_line_color(payload)
        elif action in style_actions:
            target_kind, payload, style_key = style_actions[action]
            if target_kind == "3d":
                self.change_3d_path_line_style(style_key)
            else:
                self.change_line_style(payload, style_key)
        elif action in width_actions:
            target_kind, payload, width_value = width_actions[action]
            if target_kind == "3d":
                self.change_3d_path_line_width(width_value)
            else:
                self.change_line_width(payload, width_value)
        elif action == action_copy:
            if self._true_3d_enabled and self._true_3d_view is not None:
                try:
                    image = self._true_3d_view.grabFramebuffer()
                    pixmap = QPixmap.fromImage(image)
                except Exception:
                    pixmap = self.plot.grab()
            else:
                pixmap = self.plot.grab()
            QApplication.clipboard().setPixmap(pixmap)
            self.main_window.statusBar().showMessage("그래프 이미지가 클립보드에 복사되었습니다.", 3000)
        elif action == action_stats: self.show_statistics()
        elif action == action_auto_fit: self.auto_fit_view()
        elif action == action_v_split: self.split_layout(Qt.Vertical)
        elif action == action_h_split: self.split_layout(Qt.Horizontal)
        elif action == action_clear:
            self.clear_plot_data()
        elif action == action_close: self.close_plot()

    def clear_plot_data(self):
        self.layout_special_spec = None
        self._disable_2d_flight_path_mode()
        self._disable_true_3d_mode()
        self._disable_projected_3d_mode()
        self.plot.clear()
        self._get_or_create_legend().setVisible(self.legend_visible)
        self.plot.addItem(self.v_line)
        if self.is_time_plot:
            self.v_line.show()
        else:
            self.v_line.hide()
        self.plotted_signals.clear()
        self.signal_cache.clear()
        self.plot_item_to_uri.clear()
        self._last_overlay_html = ""
        self.overlay_label.hide()
        self._true_3d_hint.hide()
        self._true_3d_axis_panel.hide()
        self._true_3d_pick_label.hide()

    def auto_fit_view(self):
        if self._flight_path_2d_enabled:
            self.plot.autoRange(padding=0.06)
            return
        if self._true_3d_enabled and self._true_3d_view is not None and self._true_3d_points is not None and len(self._true_3d_points) > 1:
            spans = np.ptp(self._true_3d_points, axis=0)
            span = float(max(spans[0], spans[1], spans[2], 1.0))
            try:
                camera = self._true_3d_camera_default or {}
                distance = float(camera.get("distance", span * 2.4))
                elevation = float(camera.get("elevation", 22.0))
                azimuth = float(camera.get("azimuth", -35.0))
                center = camera.get("center", QVector3D(0.0, 0.0, 0.0))
                self._true_3d_view.setCameraPosition(
                    pos=center,
                    distance=distance,
                    elevation=elevation,
                    azimuth=azimuth,
                )
            except Exception:
                pass
            self._true_3d_view.update()
            return

        if self._projected_3d_enabled and self._projected_3d_state:
            self._projected_3d_state["yaw_deg"] = -35.0
            self._projected_3d_state["pitch_deg"] = 20.0
            self._projected_3d_state["zoom"] = 1.0
            self._projected_3d_state["pan_x"] = 0.0
            self._projected_3d_state["pan_y"] = 0.0
            self._update_projected_3d_projection()
            return

        if not self.plotted_signals:
            self.plot.autoRange()
            return

        x_min = np.inf
        x_max = -np.inf
        y_min = np.inf
        y_max = -np.inf

        for cache in self.signal_cache.values():
            x = np.asarray(cache.get("x", []), dtype=np.float64)
            y = np.asarray(cache.get("y", []), dtype=np.float64)
            if len(x) == 0 or len(y) == 0:
                continue

            mask = np.isfinite(x) & np.isfinite(y)
            if not np.any(mask):
                continue

            xv = x[mask]
            yv = y[mask]
            x_min = min(x_min, float(np.min(xv)))
            x_max = max(x_max, float(np.max(xv)))
            y_min = min(y_min, float(np.min(yv)))
            y_max = max(y_max, float(np.max(yv)))

        if not np.isfinite(x_min) or not np.isfinite(x_max) or not np.isfinite(y_min) or not np.isfinite(y_max):
            self.plot.autoRange()
            return

        if x_min == x_max:
            x_min -= 0.5
            x_max += 0.5
        if y_min == y_max:
            y_min -= 0.5
            y_max += 0.5

        x_pad = (x_max - x_min) * 0.03
        y_pad = (y_max - y_min) * 0.08
        self.plot.setXRange(x_min - x_pad, x_max + x_pad, padding=0)
        self.plot.setYRange(y_min - y_pad, y_max + y_pad, padding=0)

    # Open a color picker and apply selected line color
    def change_line_color(self, plot_item):
        current_pen = plot_item.opts['pen']
        current_color = current_pen.color()
        
        # 기본 색상 선택기 팝업
        color_dialog = QColorDialog(current_color, self)
        color_dialog.setWindowTitle("선 색상 선택")
        
        if color_dialog.exec():
            new_color = color_dialog.selectedColor()
            if new_color.isValid():
                # Preserve existing line width/style and only change color.
                new_pen = pg.mkPen(color=new_color, width=current_pen.widthF(), style=current_pen.style())
                plot_item.setPen(new_pen)
                uri = self.plot_item_to_uri.get(plot_item)
                if uri in self.signal_cache:
                    self.signal_cache[uri]["color"] = new_color.name()
                
                # Refresh overlay so color tags update immediately.
                if self.workspace:
                    self.workspace.on_cursor_changed()

    def change_line_style(self, plot_item, style_key):
        current_pen = plot_item.opts['pen']
        color = current_pen.color()
        width = current_pen.widthF()

        if style_key == "solid":
            new_pen = pg.mkPen(color=color, width=width, style=Qt.SolidLine)
        elif style_key == "dash":
            new_pen = pg.mkPen(color=color, width=width, style=Qt.DashLine)
        elif style_key == "dense_dash":
            new_pen = pg.mkPen(color=color, width=width, style=Qt.CustomDashLine)
            new_pen.setDashPattern([2, 2])
        elif style_key == "dot":
            new_pen = pg.mkPen(color=color, width=width, style=Qt.DotLine)
        elif style_key == "dash_dot":
            new_pen = pg.mkPen(color=color, width=width, style=Qt.DashDotLine)
        else:
            return

        plot_item.setPen(new_pen)

    def change_line_width(self, plot_item, width_value):
        current_pen = plot_item.opts['pen']
        color = current_pen.color()
        style = current_pen.style()
        new_pen = pg.mkPen(color=color, width=float(width_value), style=style)
        if style == Qt.CustomDashLine:
            try:
                new_pen.setDashPattern(current_pen.dashPattern())
            except Exception:
                pass
        plot_item.setPen(new_pen)

    def show_statistics(self):
        if not self.plotted_signals:
            QMessageBox.information(self, "통계", "현재 창에 그려진 데이터가 없습니다.")
            return
        stats_text = ""
        for uri, plot_item in self.plotted_signals.items():
            parts = uri.split('|')
            topic_name = parts[1]
            signal_name = parts[2]
            x_axis_col = parts[3] if len(parts) > 3 else "timestamp_sec"
            is_fft = (len(parts) > 4 and str(parts[4]).lower() == "true")

            # Use raw cached arrays for accurate statistics.
            cache = self.signal_cache.get(uri, {})
            x = cache.get("x", None)
            y = cache.get("y", None)
            if x is None or y is None:
                # Fallback: plotted/downsized data
                x, y = plot_item.getData()
            if y is not None and len(y) > 0:
                valid_y = np.asarray(y, dtype=np.float64)
                valid_y = valid_y[np.isfinite(valid_y)]
                if len(valid_y) > 0:
                    hz_text = "N/A"
                    if (not is_fft) and x_axis_col == "timestamp_sec" and x is not None and len(x) > 1:
                        valid_x = np.asarray(x, dtype=np.float64)
                        valid_x = valid_x[np.isfinite(valid_x)]
                        if len(valid_x) > 1:
                            dt = np.diff(valid_x)
                            dt = dt[np.isfinite(dt) & (dt > 1e-9)]
                            if len(dt) > 0:
                                hz = float(1.0 / np.median(dt))
                                if np.isfinite(hz) and hz > 0:
                                    hz_text = f"{hz:.1f}"
                    y_min = np.min(valid_y)
                    y_max = np.max(valid_y)
                    y_mean = np.mean(valid_y)
                    stats_text += (
                        f"[{topic_name}.{signal_name}]\n"
                        f" - Hz:   {hz_text}\n"
                        f" - Min:  {y_min:.4f}\n"
                        f" - Max:  {y_max:.4f}\n"
                        f" - Mean: {y_mean:.4f}\n\n"
                    )
                else:
                    stats_text += f"[{topic_name}.{signal_name}]\n유효한 데이터가 없습니다.\n\n"
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("데이터 통계")
        msg_box.setText(stats_text.strip())
        msg_box.setStyleSheet("QLabel{min-width: 300px; font-size: 13px; font-weight: bold;}")
        msg_box.exec()

    def split_layout(self, orientation):
        if not self.parent_splitter: return None
        my_idx = self.parent_splitter.indexOf(self)
        current_sizes = self.parent_splitter.sizes()
        my_size = current_sizes[my_idx] if my_idx >= 0 else 300

        new_splitter = QSplitter(orientation)
        if self.workspace:
            self.workspace.register_splitter(new_splitter)
        else:
            new_splitter.setChildrenCollapsible(False)
        self.parent_splitter.insertWidget(my_idx, new_splitter)
        new_plot = AdvancedPlot(self.main_window, self.workspace, new_splitter)
        
        is_dark = self.main_window.theme_combo.currentText() == "Dark Mode"
        new_plot.apply_theme_to_overlay(is_dark)
        
        new_splitter.addWidget(self)
        new_splitter.addWidget(new_plot)
        new_splitter.setSizes([my_size // 2, my_size // 2])
        if my_idx >= 0:
            current_sizes[my_idx] = my_size
            self.parent_splitter.setSizes(current_sizes)
        self.parent_splitter = new_splitter
        if self.workspace:
            self.workspace.request_rebalance_layout()
        return new_plot

    def close_plot(self):
        if not self.parent_splitter:
            return

        can_close = (
            self.parent_splitter.count() > 1
            or not getattr(self.parent_splitter, 'is_root', False)
        )
        if not can_close:
            return

        if self.main_window and self.main_window.last_active_plot is self:
            self.main_window.last_active_plot = None

        self.setParent(None)
        self.deleteLater()
        if self.workspace:
            self.workspace.request_rebalance_layout()

class Workspace(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window 
        self.grid_plots = {} 
        self.current_layout_path = None
        self.global_min_x = None
        self.global_max_x = None
        self.is_playing = False
        self.master_time_plot = None 
        self.overlay_hidden_signals = {
            "in_transition_mode_flag",
            "in_transition_to_fw_flag",
            "in_transition_back_flag",
        }
        self._is_rebalancing_layout = False
        
        master_layout = QVBoxLayout(self)
        master_layout.setContentsMargins(0, 0, 0, 0)

        control_layout = QHBoxLayout()
        self.lbl_aircraft_type = QLabel("Type: -")
        self.lbl_aircraft_type.setStyleSheet("color: #FFB300; font-weight: bold; margin-right: 8px;")
        self.btn_reset_zoom = QPushButton("Zoom reset")
        self.btn_reset_zoom.setStyleSheet("padding: 5px; background-color: #1A2D57; color: white; font-weight: bold;")
        self.btn_reset_zoom.clicked.connect(self.reset_zoom)
        self.btn_dark_mode = QPushButton("테마 선택")
        self.btn_dark_mode.setStyleSheet("padding: 5px; background-color: #3b3b3b; color: white; font-weight: bold;")
        self.btn_dark_mode.clicked.connect(self.toggle_theme)
        self.btn_dark_mode.hide()
        
        control_layout.addStretch()
        control_layout.addWidget(self.lbl_aircraft_type)
        control_layout.addWidget(self.btn_reset_zoom)

        self.grid_root = QSplitter(Qt.Vertical)
        self.register_splitter(self.grid_root, is_root=True)
        self.first_plot = AdvancedPlot(self.main_window, self, self.grid_root)
        self.first_plot.plot.setTitle("ULG 파일 업로드 후 그래프가 표시됩니다.")
        self.grid_root.addWidget(self.first_plot)

        bottom_info_layout = QHBoxLayout()
        bottom_info_layout.setContentsMargins(10, 5, 10, 0)
        
        self.lbl_current_time = QLabel("Time: 0.00 s")
        self.lbl_current_time.setStyleSheet("color: #2196F3; font-size: 14px; font-weight: bold;")
        self.input_jump_time = QLineEdit()
        self.input_jump_time.setPlaceholderText("time (s)")
        self.input_jump_time.setFixedWidth(95)
        self.input_jump_time.setStyleSheet(
            "QLineEdit { background-color: #ffffff; color: #1f2b36; border: 1px solid #b8c2cd; border-radius: 3px; padding: 2px 6px; font-weight: bold; }"
        )
        self.input_jump_time.returnPressed.connect(self.jump_to_time_from_input)
        self.btn_jump_time = QPushButton("이동")
        self.btn_jump_time.setFixedSize(44, 24)
        self.btn_jump_time.setStyleSheet(
            "QPushButton { background-color: #1A2D57; color: white; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #223a70; }"
        )
        self.btn_jump_time.clicked.connect(self.jump_to_time_from_input)
        
        self.lbl_range_info = QLabel("Start: 0.00 s | End: 0.00 s | Duration: 0.00 s")
        self.lbl_range_info.setStyleSheet("color: #888888; font-size: 13px; font-weight: bold;")
        
        bottom_info_layout.addWidget(self.lbl_current_time)
        bottom_info_layout.addSpacing(10)
        bottom_info_layout.addWidget(self.input_jump_time)
        bottom_info_layout.addWidget(self.btn_jump_time)
        bottom_info_layout.addStretch()
        bottom_info_layout.addWidget(self.lbl_range_info)

        playback_layout = QHBoxLayout()
        playback_layout.setContentsMargins(5, 0, 5, 5)
        
        self.btn_play = QPushButton(">")
        self.btn_play.setFixedSize(40, 25) 
        self.btn_play.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; border-radius: 3px;")
        self.btn_play.clicked.connect(self.toggle_playback)
        playback_layout.addWidget(self.btn_play)
        
        self.current_speed = 1.0
        self.lbl_speed = QLabel("Playback Speed: 1x")
        self.lbl_speed.setStyleSheet("color: #888888; font-weight: bold; margin-left: 10px; margin-right: 10px;")
        
        speeds = [0.25, 0.5, 1, 1.25, 1.5, 1.75, 2]
        for spd in speeds:
            btn = QPushButton(f"x{spd}")
            btn.setFixedSize(45, 28)
            btn.setStyleSheet("background-color: #1A2D57; color: white; border-radius: 3px;")
            btn.clicked.connect(lambda checked=False, s=spd: self.change_speed(s))
            playback_layout.addWidget(btn)
            
        playback_layout.addWidget(self.lbl_speed)
        
        self.timeline = pg.PlotWidget()
        self.timeline.setFixedHeight(24)
        self.timeline.setYRange(0, 1, padding=0)
        self.timeline.hideAxis('left')
        self.timeline.hideAxis('bottom')
        self.timeline.setBackground('transparent')
        # Keep range control via handles/clicks only; disable timeline wheel/drag zoom-pan.
        self.timeline.setMenuEnabled(False)
        self.timeline.setMouseEnabled(x=False, y=False)

        self.range_start = 0.0
        self.range_end = 1.0
        self.range_track = pg.PlotCurveItem(
            [self.range_start, self.range_end],
            [0.5, 0.5],
            pen=pg.mkPen('#1A2D57', width=2),
        )
        self.timeline.addItem(self.range_track)
        self.range_points = pg.ScatterPlotItem(
            [self.range_start, self.range_end],
            [0.5, 0.5],
            symbol='o',
            size=0,
            pen=pg.mkPen((0, 0, 0, 0), width=0),
            brush=pg.mkBrush((0, 0, 0, 0)),
        )
        self.timeline.addItem(self.range_points)
        self.start_handle = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#1A2D57', width=1))
        self.end_handle = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#1A2D57', width=1))
        self.start_handle.setValue(self.range_start)
        self.end_handle.setValue(self.range_end)
        self.timeline.addItem(self.start_handle)
        self.timeline.addItem(self.end_handle)
        
        self.time_cursor = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen((0, 0, 0, 0), width=1))
        self.timeline.addItem(self.time_cursor)
        self.time_cursor_point = pg.ScatterPlotItem(
            [self.range_start],
            [0.5],
            symbol='o',
            size=10,
            pen=pg.mkPen('#1A2D57', width=2),
            brush=pg.mkBrush('#ffffff'),
        )
        self.timeline.addItem(self.time_cursor_point)
        
        self.start_text = pg.TextItem("", color='#1A2D57', anchor=(1.1, 0.5))
        self.end_text = pg.TextItem("", color='#1A2D57', anchor=(-0.1, 0.5))
        self.timeline.addItem(self.start_text)
        self.timeline.addItem(self.end_text)
        
        playback_layout.addWidget(self.timeline)

        master_layout.addLayout(control_layout)
        master_layout.addWidget(self.grid_root, stretch=1)
        master_layout.addLayout(bottom_info_layout)
        master_layout.addLayout(playback_layout)

        self.start_handle.sigPositionChanged.connect(self.on_range_handle_changed)
        self.end_handle.sigPositionChanged.connect(self.on_range_handle_changed)
        self.time_cursor.sigPositionChanged.connect(self.on_cursor_changed)
        
        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_playback_step)
        self.playback_interval_ms = 33
        self._range_apply_timer = QTimer(self)
        self._range_apply_timer.setSingleShot(True)
        self._range_apply_timer.setInterval(16)
        self._range_apply_timer.timeout.connect(self._apply_range_to_time_plots)
        self._cursor_overlay_timer = QTimer(self)
        self._cursor_overlay_timer.setSingleShot(True)
        self._cursor_overlay_timer.setTimerType(Qt.PreciseTimer)
        self._cursor_overlay_timer.setInterval(16)
        self._cursor_overlay_timer.timeout.connect(self._update_cursor_overlays)
        self._pending_cursor_t = 0.0
        self._layout_rebalance_timer = QTimer(self)
        self._layout_rebalance_timer.setSingleShot(True)
        self._layout_rebalance_timer.setInterval(0)
        self._layout_rebalance_timer.timeout.connect(self.rebalance_layout)
        self.request_rebalance_layout()

    def register_splitter(self, splitter, is_root=False):
        if splitter is None:
            return

        splitter.setChildrenCollapsible(False)
        if is_root:
            splitter.is_root = True
        if not getattr(splitter, "_rebalance_hooked", False):
            splitter.splitterMoved.connect(self.request_rebalance_layout)
            splitter._rebalance_hooked = True

    def request_rebalance_layout(self):
        if not hasattr(self, "_layout_rebalance_timer"):
            return
        if self._is_rebalancing_layout:
            return
        if self._has_active_true_3d_plot():
            return
        if not self._layout_rebalance_timer.isActive():
            self._layout_rebalance_timer.start()

    def _has_active_true_3d_plot(self):
        for plot in self.findChildren(AdvancedPlot):
            try:
                if getattr(plot, "_true_3d_enabled", False):
                    return True
            except RuntimeError:
                continue
        return False

    def rebalance_layout(self):
        if self._is_rebalancing_layout:
            return

        self._is_rebalancing_layout = True
        try:
            self._prune_splitter_children(self.grid_root)
            self._sync_plot_parent_splitters(self.grid_root)
            self._set_equal_sizes_recursive(self.grid_root)
            self._refresh_first_plot_ref()
        finally:
            self._is_rebalancing_layout = False

    def _prune_splitter_children(self, splitter):
        if not isinstance(splitter, QSplitter):
            return

        for idx in range(splitter.count() - 1, -1, -1):
            child = splitter.widget(idx)
            if isinstance(child, QSplitter):
                self._prune_splitter_children(child)

        for idx in range(splitter.count() - 1, -1, -1):
            child = splitter.widget(idx)
            if isinstance(child, QSplitter) and child.count() == 0:
                child.setParent(None)
                child.deleteLater()

        for idx in range(splitter.count() - 1, -1, -1):
            child = splitter.widget(idx)
            if isinstance(child, QSplitter) and child.count() == 1:
                grandchild = child.widget(0)
                if grandchild is None:
                    child.setParent(None)
                    child.deleteLater()
                    continue
                grandchild.setParent(None)
                child.setParent(None)
                splitter.insertWidget(idx, grandchild)
                child.deleteLater()

    def _sync_plot_parent_splitters(self, splitter):
        if not isinstance(splitter, QSplitter):
            return

        for idx in range(splitter.count()):
            child = splitter.widget(idx)
            if isinstance(child, AdvancedPlot):
                child.parent_splitter = splitter
            elif isinstance(child, QSplitter):
                self.register_splitter(child)
                self._sync_plot_parent_splitters(child)

    def _set_equal_sizes_recursive(self, splitter):
        if not isinstance(splitter, QSplitter):
            return

        for idx in range(splitter.count()):
            child = splitter.widget(idx)
            if isinstance(child, QSplitter):
                self._set_equal_sizes_recursive(child)

        count = splitter.count()
        if count < 2:
            return

        total_size = splitter.size().width() if splitter.orientation() == Qt.Horizontal else splitter.size().height()
        if total_size <= 0:
            current_sizes = [s for s in splitter.sizes() if s > 0]
            total_size = sum(current_sizes)
        if total_size <= 0:
            total_size = count

        base = max(1, int(total_size / count))
        sizes = [base] * count
        remainder = int(total_size - (base * count))
        for i in range(max(0, remainder)):
            sizes[i % count] += 1
        splitter.setSizes(sizes)

    def _refresh_first_plot_ref(self):
        plots = self.findChildren(AdvancedPlot)
        if plots:
            self.first_plot = plots[0]
        else:
            self.first_plot = None

        current_last = self.main_window.last_active_plot
        if current_last is not None:
            try:
                if current_last not in plots:
                    self.main_window.last_active_plot = None
            except RuntimeError:
                self.main_window.last_active_plot = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._has_active_true_3d_plot():
            return
        self.request_rebalance_layout()

    def change_speed(self, val):
        if val == 1: self.current_speed = 1.0 
        else: self.current_speed *= val 
        self.lbl_speed.setText(f"Playback Speed: {self.current_speed:g}x")

    def expand_time_range(self, x_array):
        if len(x_array) == 0: return
        
        valid_x = x_array[x_array >= -5.0]
        if len(valid_x) == 0: return
        
        prev_global_min = self.global_min_x
        prev_global_max = self.global_max_x
        min_x, max_x = np.min(valid_x), np.max(valid_x)
        if max_x - min_x > 36000:
            p99 = np.percentile(valid_x, 99)
            valid_x = valid_x[valid_x <= p99 * 1.5]
            if len(valid_x) > 0: max_x = np.max(valid_x)

        updated = False
        if self.global_min_x is None or min_x < self.global_min_x:
            self.global_min_x = min_x
            updated = True
        if self.global_max_x is None or max_x > self.global_max_x:
            self.global_max_x = max_x
            updated = True
            
        if updated:
            self.timeline.setXRange(self.global_min_x, self.global_max_x, padding=0)
            should_follow_global = (
                (not np.isfinite(self.range_start) or not np.isfinite(self.range_end))
                or (abs(self.range_start) < 1e-6 and abs(self.range_end - 1.0) < 1e-6)
            )
            if (not should_follow_global and prev_global_min is not None and prev_global_max is not None):
                # While loading, keep following global range unless user changed range manually.
                if abs(self.range_start - prev_global_min) < 1e-3 and abs(self.range_end - prev_global_max) < 1e-3:
                    should_follow_global = True

            if should_follow_global:
                self.range_start = self.global_min_x
                self.range_end = self.global_max_x
                self.start_handle.setValue(self.range_start)
                self.end_handle.setValue(self.range_end)
                if self.time_cursor.value() < self.range_start or self.time_cursor.value() > self.range_end:
                    self.time_cursor.setValue(self.range_start)
                self.on_range_changed()

    def on_range_handle_changed(self):
        start_val = self.start_handle.value()
        end_val = self.end_handle.value()
        self.range_start = min(start_val, end_val)
        self.range_end = max(start_val, end_val)
        self._update_range_ui()
        if not self._range_apply_timer.isActive():
            self._range_apply_timer.start()

    def on_range_changed(self):
        self._update_range_ui()
        self._apply_range_to_time_plots()

    def _update_range_ui(self):
        minX, maxX = self.range_start, self.range_end
        self.lbl_range_info.setText(f"Start: {minX:.2f} s | End: {maxX:.2f} s | Duration: {(maxX - minX):.2f} s")
        self.range_track.setData([minX, maxX], [0.5, 0.5])
        self.range_points.setData([minX, maxX], [0.5, 0.5])
        self.start_text.setPos(minX, 0.5)
        self.start_text.setText(f"{minX:.1f} s")
        self.end_text.setPos(maxX, 0.5)
        self.end_text.setText(f"{maxX:.1f} s")

    def _apply_range_to_time_plots(self):
        minX, maxX = self.range_start, self.range_end
        for plot in self.findChildren(AdvancedPlot):
            if plot.is_time_plot:
                plot.plot.setXRange(minX, maxX, padding=0)

    def set_current_time(self, t, immediate_overlay=False):
        t = float(t)
        self.time_cursor.setValue(t)
        if immediate_overlay:
            self._pending_cursor_t = t
            if self._cursor_overlay_timer.isActive():
                self._cursor_overlay_timer.stop()
            self._update_cursor_overlays(force=True)

    def jump_to_time_from_input(self):
        raw_text = self.input_jump_time.text().strip()
        if not raw_text:
            return

        normalized = raw_text.lower().replace("sec", "").replace("s", "").strip()
        try:
            target_t = float(normalized)
        except ValueError:
            self.main_window.statusBar().showMessage("시간 형식이 올바르지 않습니다. 예: 123.45", 3000)
            return

        if not np.isfinite(target_t):
            self.main_window.statusBar().showMessage("유효한 숫자를 입력해 주세요.", 3000)
            return

        bound_min = self.global_min_x if self.global_min_x is not None else self.range_start
        bound_max = self.global_max_x if self.global_max_x is not None else self.range_end
        if bound_min is not None and bound_max is not None and bound_max > bound_min:
            target_t = min(max(target_t, bound_min), bound_max)

        if self.range_end <= self.range_start:
            visible_span = 1.0
        else:
            visible_span = self.range_end - self.range_start

        if target_t < self.range_start or target_t > self.range_end:
            if bound_min is not None and bound_max is not None and bound_max > bound_min:
                total_span = bound_max - bound_min
                if visible_span >= total_span:
                    new_start, new_end = bound_min, bound_max
                else:
                    half_span = visible_span / 2.0
                    new_start = target_t - half_span
                    new_end = target_t + half_span
                    if new_start < bound_min:
                        shift = bound_min - new_start
                        new_start += shift
                        new_end += shift
                    if new_end > bound_max:
                        shift = new_end - bound_max
                        new_start -= shift
                        new_end -= shift
                self.set_time_range(new_start, new_end, clamp_to_global=True)
            else:
                self.set_time_range(target_t - 0.5, target_t + 0.5, clamp_to_global=False)

        self.set_current_time(target_t)
        self.input_jump_time.setText(f"{target_t:.2f}")

    def on_cursor_changed(self):
        t = self.time_cursor.value()
        self.time_cursor_point.setData([t], [0.5])
        self.lbl_current_time.setText(f"Time: {t:.2f} s")
        self._pending_cursor_t = t
        self._cursor_overlay_timer.start()

    def _update_cursor_overlays(self, force=False):
        t = float(self._pending_cursor_t)
        hidden = self.overlay_hidden_signals
        for plot in self.findChildren(AdvancedPlot):
            if not plot.isVisible():
                continue
            if plot._flight_path_2d_enabled:
                plot.update_2d_flight_path_cursor_from_time(t)
            if plot._true_3d_enabled:
                plot.update_true_3d_cursor_from_time(t)
            if plot._projected_3d_enabled:
                plot.update_projected_3d_cursor_from_time(t, show_label=True)
            if not plot.is_time_plot or not plot.plotted_signals: 
                plot._last_overlay_html = ""
                plot.overlay_label.hide()
                continue
                
            plot.v_line.setValue(t)
            
            text_lines = []
            for signal_info in plot.signal_cache.values():
                if signal_info["signal_name"] in hidden:
                    continue
                if not (signal_info["xmin"] <= t <= signal_info["xmax"]):
                    continue
                x = signal_info["x"]
                y = signal_info["y"]
                n = len(y)
                if n == 0:
                    continue

                idx = signal_info.get("_last_idx")
                last_t = signal_info.get("_last_t")
                x_is_asc = signal_info.get("_x_asc", True)

                if (
                    force
                    or idx is None
                    or last_t is None
                    or not x_is_asc
                    or idx < 0
                    or idx >= n
                ):
                    idx = int(np.searchsorted(x, t, side="left"))
                else:
                    idx = int(idx)
                    if t >= float(last_t):
                        if idx < n - 1:
                            idx = idx + int(np.searchsorted(x[idx:], t, side="left"))
                    else:
                        if idx > 0:
                            idx = int(np.searchsorted(x[:idx + 1], t, side="left"))
                        else:
                            idx = int(np.searchsorted(x, t, side="left"))

                if idx >= len(y):
                    idx = len(y) - 1
                signal_info["_last_idx"] = int(idx)
                signal_info["_last_t"] = float(t)
                val = y[idx]
                if not np.isfinite(val):
                    continue
                text_lines.append(
                    f"<span style='color:{signal_info['color']};'>{signal_info['signal_name']}: {val:.3f}</span>"
                )
            
            if text_lines:
                html = "<br>".join(text_lines)
                if html != plot._last_overlay_html:
                    plot.overlay_label.setText(html)
                    plot.overlay_label.adjustSize()
                    plot._last_overlay_html = html
                plot.overlay_label.show()
                plot.move_overlay_near_cursor(t)
            else:
                plot._last_overlay_html = ""
                plot.overlay_label.hide()

    def toggle_playback(self):
        if self.is_playing:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self):
        if self.range_end <= self.range_start:
            if self.global_min_x is not None and self.global_max_x is not None and self.global_max_x > self.global_min_x:
                self.range_start = self.global_min_x
                self.range_end = self.global_max_x
            else:
                base_t = self.time_cursor.value()
                self.range_start = base_t
                self.range_end = base_t + 1.0
            self.start_handle.setValue(self.range_start)
            self.end_handle.setValue(self.range_end)
            self.on_range_changed()
            self.main_window.statusBar().showMessage("재생 구간이 없어 기본 1초 구간으로 설정했습니다.", 2500)

        t = self.time_cursor.value()
        if t < self.range_start or t >= self.range_end:
            self.time_cursor.setValue(self.range_start)
            self.on_cursor_changed()

        self.timer.start(self.playback_interval_ms)
        self.is_playing = True
        self.btn_play.setText("||")

    def pause_playback(self):
        self.timer.stop()
        self.is_playing = False
        self.btn_play.setText(">")

    def on_playback_step(self):
        if not self.is_playing:
            return

        t = self.time_cursor.value()
        step = (self.playback_interval_ms / 1000.0) * self.current_speed
        
        minX, maxX = self.range_start, self.range_end
        new_t = t + step
        
        if new_t > maxX:
            self.time_cursor.setValue(maxX)
            self.pause_playback()
            return
            
        self.time_cursor.setValue(new_t)

    def create_grid(self, rows, cols=None):
        if isinstance(rows, int) and cols is not None: row_config = [cols] * rows
        elif isinstance(rows, list): row_config = rows
        else: row_config = [1]
            
        while self.grid_root.count():
            widget = self.grid_root.widget(0)
            widget.setParent(None)
            widget.deleteLater()
        self.grid_plots.clear()
        self.master_time_plot = None 

        for r, col_count in enumerate(row_config):
            row_splitter = QSplitter(Qt.Horizontal)
            self.register_splitter(row_splitter)
            self.grid_root.addWidget(row_splitter)
            
            for c in range(col_count):
                plot_widget = AdvancedPlot(self.main_window, self, row_splitter)
                is_dark = self.main_window.theme_combo.currentText() == "Dark Mode"
                plot_widget.apply_theme_to_overlay(is_dark)

                row_splitter.addWidget(plot_widget)
                self.grid_plots[(r, c)] = plot_widget
                if r == 0 and c == 0:
                    self.first_plot = plot_widget
        self.request_rebalance_layout()

    def get_plot(self, row, col):
        return self.grid_plots.get((row, col), self.first_plot)

    def reset_zoom(self):
        if self.global_min_x is not None:
            self.range_start = self.global_min_x
            self.range_end = self.global_max_x
            self.start_handle.setValue(self.range_start)
            self.end_handle.setValue(self.range_end)
            self.on_range_changed()
        for plot_widget in self.findChildren(AdvancedPlot):
            if not plot_widget.is_time_plot:
                plot_widget.plot.autoRange() 

    def set_time_range(self, start_t, end_t, clamp_to_global=True):
        if start_t is None or end_t is None:
            return
        start_t = float(start_t)
        end_t = float(end_t)
        if end_t <= start_t:
            return

        if clamp_to_global and self.global_min_x is not None and self.global_max_x is not None:
            start_t = max(start_t, self.global_min_x)
            end_t = min(end_t, self.global_max_x)
            if end_t <= start_t:
                return

        self.range_start = start_t
        self.range_end = end_t
        self.start_handle.setValue(self.range_start)
        self.end_handle.setValue(self.range_end)
        self.on_range_changed()

    def toggle_theme(self):
        current = self.main_window.theme_combo.currentText()
        next_mode = "Light Mode" if current == "Dark Mode" else "Dark Mode"
        self.main_window.theme_combo.setCurrentText(next_mode)

    def set_aircraft_type(self, aircraft_type_text):
        self.lbl_aircraft_type.setText(f"Aircraft Type: {aircraft_type_text}")

class MainWindow(QMainWindow):
    CUSTOM_SERIES_TOPIC = "__custom_series__"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NEXT AEROSPACE Log Analayer")
        self.resize(1300, 800)
        self.setAcceptDrops(True)
        self._signal_drop_hover_plot = None
        self._ui_icon_cache = None
        self._startup_splitter_ratio = 0.14
        self._startup_splitter_min_left = 150
        self._startup_splitter_applied = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.loaded_datasets = {}
        self.loaded_aircraft_types = {}
        self.loaded_log_metadata = {}
        self.active_analysis_log = None
        self.log_info_dialog = None
        self.custom_series_defs = {}
        self.custom_series_data = {}
        self.last_active_plot = None

        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', '#aaaaaa')
        self.setStyleSheet("QMainWindow { background-color: #1e1e1e; color: white; }")

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False) 
        self.setCentralWidget(self.main_splitter)

        self.left_container = QWidget()
        self.left_container.setObjectName("leftContainer")
        self.left_container.setMinimumWidth(0)
        left_layout = QVBoxLayout(self.left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.left_brand_bar = QWidget()
        self.left_brand_bar.setObjectName("leftBrandBar")
        brand_layout = QHBoxLayout(self.left_brand_bar)
        brand_layout.setContentsMargins(10, 6, 10, 6)
        brand_layout.setSpacing(12)

        self.logo_label = QLabel("NEXT\nAEROSPACE")
        self.logo_label.setObjectName("logoLabel")
        self.logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.top_menu_bar = QMenuBar()
        self.top_menu_bar.setNativeMenuBar(False)
        self.top_menu_bar.setObjectName("topMenuBar")
        self._build_top_menus()
        brand_layout.addWidget(self.logo_label)
        brand_layout.addWidget(self.top_menu_bar)
        brand_layout.addStretch()
        self._apply_brand_icon()

        self.left_publishers_header = QLabel("Publishers")
        self.left_publishers_header.setObjectName("leftPublishersHeader")
        self.left_publishers_header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.left_publishers_panel = QWidget()
        self.left_publishers_panel.setObjectName("leftPublishersPanel")
        publishers_layout = QVBoxLayout(self.left_publishers_panel)
        publishers_layout.setContentsMargins(10, 8, 10, 8)
        publishers_layout.setSpacing(8)

        csv_row = QHBoxLayout()
        csv_row.setContentsMargins(0, 0, 0, 0)
        self.csv_title_label = QLabel("CSV Export:")
        self.csv_title_label.setObjectName("csvTitleLabel")
        self.csv_export_button = QPushButton("EXPORT")
        self.csv_export_button.setObjectName("layoutActionButton")
        self.csv_export_button.clicked.connect(self.export_current_workspace_csv)
        csv_row.addWidget(self.csv_title_label)
        csv_row.addSpacing(4)
        csv_row.addStretch()
        csv_row.addWidget(self.csv_export_button)

        layout_row = QHBoxLayout()
        layout_row.setContentsMargins(0, 0, 0, 0)
        self.layout_title_label = QLabel("Layout:")
        self.layout_title_label.setObjectName("layoutTitleLabel")
        self.layout_btn_load = QPushButton("IMPORT")
        self.layout_btn_load.setObjectName("layoutActionButton")
        self.layout_btn_save = QPushButton("EXPORT")
        self.layout_btn_save.setObjectName("layoutActionButton")
        self.layout_btn_more = QPushButton(">")
        self.layout_btn_more.setObjectName("layoutToolButton")
        self.layout_btn_more.setFixedSize(24, 22)
        self.layout_btn_load.clicked.connect(self.import_layout_to_workspace)
        self.layout_btn_save.clicked.connect(self.export_current_workspace_layout)
        self.layout_btn_more.clicked.connect(self.show_current_layout_path)
        self.layout_btn_load.setToolTip("레이아웃 불러오기 (Import)")
        self.layout_btn_save.setToolTip("현재 분석창 레이아웃 저장 (Export)")
        self.layout_btn_more.setToolTip("현재 레이아웃 파일 경로 보기")
        self._update_layout_action_button_sizes()
        layout_row.addWidget(self.layout_title_label)
        layout_row.addSpacing(4)
        layout_row.addWidget(self.layout_btn_load)
        layout_row.addWidget(self.layout_btn_save)
        layout_row.addStretch()
        layout_row.addWidget(self.layout_btn_more)

        publishers_layout.addLayout(csv_row)
        publishers_layout.addLayout(layout_row)
        
        self.file_drop_widget = FileDropWidget()
        self.file_drop_widget.filesDropped.connect(self.load_log_files)
        self.file_drop_widget.setFixedHeight(56)
        self.file_drop_widget.setObjectName("uploadDropWidget")

        self.tree_search_input = QLineEdit()
        self.tree_search_input.setObjectName("treeSearchInput")
        self.tree_search_input.setPlaceholderText("Search topic / signal")
        self.tree_search_input.setClearButtonEnabled(True)
        self.tree_search_input.textChanged.connect(self.on_tree_search_changed)
        self._pending_tree_filter_text = ""
        self._tree_search_timer = QTimer(self)
        self._tree_search_timer.setSingleShot(True)
        self._tree_search_timer.setInterval(120)
        self._tree_search_timer.timeout.connect(self.apply_tree_search)
        
        self.tree_view = DraggableTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setAnimated(False)
        self.tree_model = QStandardItemModel()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setIndentation(14)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_tree_context_menu)

        self.tree_container = QFrame()
        self.tree_container.setObjectName("treeContainer")
        tree_container_layout = QVBoxLayout(self.tree_container)
        tree_container_layout.setContentsMargins(0, 0, 0, 0)
        tree_container_layout.setSpacing(0)
        tree_container_layout.addWidget(self.tree_view)

        self.custom_series_panel = QFrame()
        self.custom_series_panel.setObjectName("customSeriesPanel")
        custom_layout = QVBoxLayout(self.custom_series_panel)
        custom_layout.setContentsMargins(8, 6, 8, 8)
        custom_layout.setSpacing(6)

        custom_header = QHBoxLayout()
        custom_header.setContentsMargins(0, 0, 0, 0)
        self.custom_series_label = QLabel("Custom Series:")
        self.custom_series_label.setObjectName("customSeriesLabel")
        self.btn_custom_series_add = QPushButton("+")
        self.btn_custom_series_add.setObjectName("customSeriesToolButton")
        self.btn_custom_series_add.setFixedSize(24, 22)
        self.btn_custom_series_edit = QPushButton("Edit")
        self.btn_custom_series_edit.setObjectName("customSeriesToolButton")
        self.btn_custom_series_edit.setFixedHeight(22)
        self.btn_custom_series_edit.setMinimumWidth(44)
        self.btn_custom_series_add.setToolTip("새 Custom Series 생성")
        self.btn_custom_series_edit.setToolTip("선택한 Custom Series 수정")
        self.btn_custom_series_add.clicked.connect(self.create_custom_series)
        self.btn_custom_series_edit.clicked.connect(self.edit_custom_series)
        custom_header.addWidget(self.custom_series_label)
        custom_header.addStretch()
        custom_header.addWidget(self.btn_custom_series_add)
        custom_header.addWidget(self.btn_custom_series_edit)
        custom_layout.addLayout(custom_header)

        self.custom_series_list = CustomSeriesListWidget(self)
        self.custom_series_list.setMinimumHeight(96)
        self.custom_series_list.itemDoubleClicked.connect(lambda _item: self.edit_custom_series())
        self.custom_series_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.custom_series_list.customContextMenuRequested.connect(self._show_custom_series_context_menu)
        custom_layout.addWidget(self.custom_series_list, 1)
        
        left_layout.addWidget(self.left_brand_bar)
        left_layout.addWidget(self.left_publishers_header)
        left_layout.addWidget(self.left_publishers_panel)
        left_layout.addWidget(self.file_drop_widget)
        left_layout.addWidget(self.tree_search_input)
        left_layout.addWidget(self.tree_container, stretch=1)
        left_layout.addWidget(self.custom_series_panel)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_workspace)
        self.tab_widget.tabBarDoubleClicked.connect(self.rename_workspace_tab)
        
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 12, 0)
        corner_layout.setSpacing(8)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Mode", "Light Mode"])
        self.theme_combo.setCurrentText("Light Mode")
        self.theme_combo.setStyleSheet("background-color: #3b3b3b; color: white; font-weight: bold; border-radius: 3px; padding: 2px;")
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        self.theme_combo.hide()
        
        self.btn_add_workspace = QPushButton("+ New Tab")
        self.btn_add_workspace.setObjectName("newTabButton")
        self.btn_add_workspace.clicked.connect(self.add_workspace)
        
        corner_layout.addWidget(self.btn_add_workspace)
        self.tab_widget.setCornerWidget(corner_widget, Qt.TopLeftCorner)

        self.blank_state_widget = QWidget()
        self.blank_state_widget.setObjectName("blankStateWidget")
        blank_layout = QVBoxLayout(self.blank_state_widget)
        blank_layout.setContentsMargins(20, 20, 20, 20)
        blank_layout.setSpacing(8)
        blank_layout.addStretch()

        self.blank_state_title = QLabel("분석 창이 없습니다.")
        self.blank_state_title.setObjectName("blankStateTitle")
        self.blank_state_title.setAlignment(Qt.AlignCenter)
        self.blank_state_hint = QLabel("좌측에 로그를 업로드한 뒤, + New Tab으로 분석 창을 생성해 주세요.")
        self.blank_state_hint.setObjectName("blankStateHint")
        self.blank_state_hint.setAlignment(Qt.AlignCenter)
        self.blank_state_create_btn = QPushButton("+ New Tab")
        self.blank_state_create_btn.setObjectName("blankStateButton")
        self.blank_state_create_btn.setFixedHeight(34)
        self.blank_state_create_btn.clicked.connect(self.add_workspace)

        blank_layout.addWidget(self.blank_state_title, alignment=Qt.AlignCenter)
        blank_layout.addWidget(self.blank_state_hint, alignment=Qt.AlignCenter)
        blank_layout.addSpacing(8)
        blank_layout.addWidget(self.blank_state_create_btn, alignment=Qt.AlignCenter)
        blank_layout.addStretch()

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.blank_state_widget)
        self.right_stack.addWidget(self.tab_widget)
        
        self.workspace_count = 0

        self.main_splitter.addWidget(self.left_container)
        self.main_splitter.addWidget(self.right_stack)
        self._apply_startup_splitter_ratio(force=True)
        QTimer.singleShot(0, lambda: self._apply_startup_splitter_ratio(force=True))
        self._update_right_panel_state()

        self.change_theme(self.theme_combo.currentText())
        self.statusBar().showMessage("Ready | Upload ULG file", 5000)

    def _icon_search_roots(self):
        roots = []
        if getattr(sys, "frozen", False):
            try:
                roots.append(os.path.dirname(sys.executable))
            except Exception:
                pass
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                roots.append(meipass)
        roots.append(os.path.abspath(os.path.join(src_dir, "../../")))
        roots.append(os.path.abspath(os.path.join(src_dir, "../")))
        roots.append(os.getcwd())
        unique = []
        seen = set()
        for r in roots:
            if not r or r in seen:
                continue
            seen.add(r)
            unique.append(r)
        return unique

    def _find_icon_by_names(self, primary_name, fallback_names=None):
        fallback_names = fallback_names or []
        names = [primary_name] + list(fallback_names)
        for root in self._icon_search_roots():
            for name in names:
                if not name:
                    continue
                rel = name
                if os.path.isabs(rel):
                    cand = rel
                else:
                    cand = os.path.join(root, rel)
                if os.path.exists(cand):
                    return cand
        return None

    def _find_main_icon_path(self):
        return self._find_icon_by_names(
            "Logo_main.ico",
            fallback_names=[
                "Logo (2).ico",
                "1-3e360415.ico",
                os.path.join("assets", "next_aerospace.ico"),
            ],
        )

    def _find_ui_icon_path(self):
        path = self._find_icon_by_names(
            "Logo.ico",
            fallback_names=[
                os.path.join("assets", "logo.ico"),
                "Logo_main.ico",
            ],
        )
        return path

    def _get_ui_icon(self):
        if isinstance(self._ui_icon_cache, QIcon) and not self._ui_icon_cache.isNull():
            return self._ui_icon_cache
        icon_path = self._find_ui_icon_path()
        if icon_path and os.path.exists(icon_path):
            icon = QIcon(icon_path)
            if not icon.isNull():
                self._ui_icon_cache = icon
                return icon
        return QIcon()

    def _apply_startup_splitter_ratio(self, force=False):
        if not hasattr(self, "main_splitter") or self.main_splitter.count() < 2:
            return

        if self._startup_splitter_applied and not force:
            return

        total_w = self.main_splitter.width()
        if total_w <= 1:
            total_w = self.width()
        if total_w <= 1:
            return

        left_w = max(self._startup_splitter_min_left, int(total_w * self._startup_splitter_ratio))
        right_w = max(1, total_w - left_w)

        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 6)
        self.main_splitter.setSizes([left_w, right_w])
        self._startup_splitter_applied = True

    def _update_layout_action_button_sizes(self):
        if not hasattr(self, "layout_btn_load") or not hasattr(self, "layout_btn_save"):
            return

        fm = self.layout_btn_load.fontMetrics()
        text_w = max(
            fm.horizontalAdvance(self.layout_btn_load.text()),
            fm.horizontalAdvance(self.layout_btn_save.text()),
        )
        if hasattr(self, "csv_export_button"):
            text_w = max(text_w, fm.horizontalAdvance(self.csv_export_button.text()))
        # Make IMPORT/EXPORT boxes clearly smaller while keeping text readable.
        btn_h = max(17, fm.height() + 4)
        btn_w = max(50, text_w + 8)
        self.layout_btn_load.setFixedSize(btn_w, btn_h)
        self.layout_btn_save.setFixedSize(btn_w, btn_h)
        if hasattr(self, "csv_export_button"):
            self.csv_export_button.setFixedSize(btn_w, btn_h)
        if hasattr(self, "layout_btn_more"):
            self.layout_btn_more.setFixedSize(22, btn_h)

    def _custom_series_templates(self):
        return [
            {
                "id": "rad_to_deg",
                "name": "rad_to_deg",
                "description": "라디안 입력(value)을 도(deg)로 변환합니다.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    return np.degrees(value)\n"
                ),
            },
            {
                "id": "quat_to_roll",
                "name": "quat_to_roll",
                "description": "쿼터니언(w=value, x=v1, y=v2, z=v3)에서 Roll(deg)을 계산합니다.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    w = np.asarray(value, dtype=float)\n"
                    "    x = np.asarray(v1 if v1 is not None else np.zeros_like(w), dtype=float)\n"
                    "    y = np.asarray(v2 if v2 is not None else np.zeros_like(w), dtype=float)\n"
                    "    z = np.asarray(v3 if v3 is not None else np.zeros_like(w), dtype=float)\n"
                    "    sinr_cosp = 2.0 * (w * x + y * z)\n"
                    "    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)\n"
                    "    return np.degrees(np.arctan2(sinr_cosp, cosr_cosp))\n"
                ),
            },
            {
                "id": "quat_to_pitch",
                "name": "quat_to_pitch",
                "description": "쿼터니언(w=value, x=v1, y=v2, z=v3)에서 Pitch(deg)을 계산합니다.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    w = np.asarray(value, dtype=float)\n"
                    "    x = np.asarray(v1 if v1 is not None else np.zeros_like(w), dtype=float)\n"
                    "    y = np.asarray(v2 if v2 is not None else np.zeros_like(w), dtype=float)\n"
                    "    z = np.asarray(v3 if v3 is not None else np.zeros_like(w), dtype=float)\n"
                    "    sinp = 2.0 * (w * y - z * x)\n"
                    "    sinp = np.clip(sinp, -1.0, 1.0)\n"
                    "    return np.degrees(np.arcsin(sinp))\n"
                ),
            },
            {
                "id": "quat_to_yaw",
                "name": "quat_to_yaw",
                "description": "쿼터니언(w=value, x=v1, y=v2, z=v3)에서 Yaw(deg)을 계산합니다.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    w = np.asarray(value, dtype=float)\n"
                    "    x = np.asarray(v1 if v1 is not None else np.zeros_like(w), dtype=float)\n"
                    "    y = np.asarray(v2 if v2 is not None else np.zeros_like(w), dtype=float)\n"
                    "    z = np.asarray(v3 if v3 is not None else np.zeros_like(w), dtype=float)\n"
                    "    siny_cosp = 2.0 * (w * z + x * y)\n"
                    "    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)\n"
                    "    return np.degrees(np.arctan2(siny_cosp, cosy_cosp))\n"
                ),
            },
            {
                "id": "first_derivative",
                "name": "1st_derivative",
                "description": "value의 시간 미분(d/dt)을 계산합니다.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    t = np.asarray(time, dtype=float)\n"
                    "    v = np.asarray(value, dtype=float)\n"
                    "    if len(v) < 2:\n"
                    "        return np.zeros_like(v)\n"
                    "    return np.gradient(v, t)\n"
                ),
            },
            {
                "id": "integral",
                "name": "integral",
                "description": "value를 시간에 대해 누적 적분합니다 (trapezoidal).",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    t = np.asarray(time, dtype=float)\n"
                    "    v = np.asarray(value, dtype=float)\n"
                    "    if len(v) < 2:\n"
                    "        return np.zeros_like(v)\n"
                    "    dt = np.diff(t, prepend=t[0])\n"
                    "    if len(dt) > 1:\n"
                    "        dt[0] = dt[1]\n"
                    "    return np.cumsum(v * dt)\n"
                ),
            },
            {
                "id": "moving_average",
                "name": "moving_average",
                "description": "이동평균 필터를 적용합니다. global 변수 window 사용.",
                "globals_text": "window = 15",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    w = int(max(1, window))\n"
                    "    v = np.asarray(value, dtype=float)\n"
                    "    if w <= 1 or len(v) == 0:\n"
                    "        return v\n"
                    "    kernel = np.ones(w, dtype=float) / float(w)\n"
                    "    return np.convolve(v, kernel, mode='same')\n"
                ),
            },
            {
                "id": "error_between_two_signals",
                "name": "error_between_two_signals",
                "description": "tracking error = setpoint(value) - actual(v1).",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    actual = np.asarray(v1 if v1 is not None else np.zeros_like(value), dtype=float)\n"
                    "    return np.asarray(value, dtype=float) - actual\n"
                ),
            },
            {
                "id": "ground_speed_from_vx_vy",
                "name": "ground_speed_from_vx_vy",
                "description": "지면속도 = sqrt(vx^2 + vy^2). value=vx, v1=vy.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    vx = np.asarray(value, dtype=float)\n"
                    "    vy = np.asarray(v1 if v1 is not None else np.zeros_like(vx), dtype=float)\n"
                    "    return np.sqrt(vx * vx + vy * vy)\n"
                ),
            },
            {
                "id": "accel_magnitude",
                "name": "accel_magnitude",
                "description": "가속도 크기 = sqrt(ax^2 + ay^2 + az^2). value=ax, v1=ay, v2=az.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    ax = np.asarray(value, dtype=float)\n"
                    "    ay = np.asarray(v1 if v1 is not None else np.zeros_like(ax), dtype=float)\n"
                    "    az = np.asarray(v2 if v2 is not None else np.zeros_like(ax), dtype=float)\n"
                    "    return np.sqrt(ax * ax + ay * ay + az * az)\n"
                ),
            },
            {
                "id": "gyro_magnitude",
                "name": "gyro_magnitude",
                "description": "각속도 크기 = sqrt(gx^2 + gy^2 + gz^2). value=gx, v1=gy, v2=gz.",
                "globals_text": "",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    gx = np.asarray(value, dtype=float)\n"
                    "    gy = np.asarray(v1 if v1 is not None else np.zeros_like(gx), dtype=float)\n"
                    "    gz = np.asarray(v2 if v2 is not None else np.zeros_like(gx), dtype=float)\n"
                    "    return np.sqrt(gx * gx + gy * gy + gz * gz)\n"
                ),
            },
            {
                "id": "pwm_to_throttle_percent",
                "name": "pwm_to_throttle_percent",
                "description": "PWM 값을 스로틀 퍼센트(0~100)로 변환합니다.",
                "globals_text": "pwm_min = 1000\npwm_max = 2000",
                "function_code": (
                    "def function(time, value, v1=None, v2=None, v3=None, v4=None):\n"
                    "    v = np.asarray(value, dtype=float)\n"
                    "    denom = max(1e-9, float(pwm_max) - float(pwm_min))\n"
                    "    out = (v - float(pwm_min)) * 100.0 / denom\n"
                    "    return np.clip(out, 0.0, 100.0)\n"
                ),
            },
        ]

    def _show_custom_series_context_menu(self, pos):
        menu = QMenu(self)
        action_add = menu.addAction("New Custom Series")
        action_edit = menu.addAction("Edit")
        action_delete = menu.addAction("Delete")
        if not self.custom_series_list.selectedItems():
            action_edit.setEnabled(False)
            action_delete.setEnabled(False)
        chosen = menu.exec(self.custom_series_list.mapToGlobal(pos))
        if chosen == action_add:
            self.create_custom_series()
        elif chosen == action_edit:
            self.edit_custom_series()
        elif chosen == action_delete:
            self._delete_selected_custom_series()

    def _refresh_custom_series_list(self, select_key=None):
        selected_keys = set()
        for item in self.custom_series_list.selectedItems():
            info = item.data(Qt.UserRole)
            if isinstance(info, dict):
                selected_keys.add((str(info.get("file_name", "")), str(info.get("name", ""))))
        current_item = self.custom_series_list.currentItem()
        if current_item is not None:
            info = current_item.data(Qt.UserRole)
            if isinstance(info, dict):
                selected_keys.add((str(info.get("file_name", "")), str(info.get("name", ""))))
        if select_key is not None:
            selected_keys.add(select_key)

        self.custom_series_list.blockSignals(True)
        self.custom_series_list.clear()

        restored_current = False
        for file_name in sorted(self.custom_series_defs.keys()):
            spec_map = self.custom_series_defs.get(file_name, {})
            if not isinstance(spec_map, dict):
                continue
            for series_name in sorted(spec_map.keys()):
                label_file = file_name[:18] + ".." if len(file_name) > 20 else file_name
                label = f"{series_name}  [{label_file}]"
                item = QListWidgetItem(label)
                item.setToolTip(f"{file_name} | {series_name}")
                item.setData(
                    Qt.UserRole,
                    {
                        "file_name": file_name,
                        "name": series_name,
                    },
                )
                self.custom_series_list.addItem(item)
                key = (file_name, series_name)
                if key in selected_keys:
                    item.setSelected(True)
                if select_key is not None and key == select_key:
                    self.custom_series_list.setCurrentItem(item)
                    restored_current = True

        if not restored_current and self.custom_series_list.count() > 0 and self.custom_series_list.currentRow() < 0:
            self.custom_series_list.setCurrentRow(0)
        self.custom_series_list.blockSignals(False)

    def _selected_custom_series_info(self):
        item = self.custom_series_list.currentItem()
        if item is None:
            selected = self.custom_series_list.selectedItems()
            item = selected[0] if selected else None
        if item is None:
            return None, None
        info = item.data(Qt.UserRole)
        if not isinstance(info, dict):
            return None, None
        file_name = str(info.get("file_name", "")).strip()
        series_name = str(info.get("name", "")).strip()
        if not file_name or not series_name:
            return None, None
        return file_name, series_name

    def _delete_selected_custom_series(self):
        selected_items = self.custom_series_list.selectedItems()
        if not selected_items:
            return

        targets = []
        for item in selected_items:
            info = item.data(Qt.UserRole)
            if not isinstance(info, dict):
                continue
            file_name = str(info.get("file_name", "")).strip()
            series_name = str(info.get("name", "")).strip()
            if file_name and series_name:
                targets.append((file_name, series_name))
        if not targets:
            return

        unique_targets = []
        seen = set()
        for key in targets:
            if key in seen:
                continue
            seen.add(key)
            unique_targets.append(key)

        if len(unique_targets) == 1:
            msg = f"'{unique_targets[0][1]}' Custom Series를 삭제할까요?"
        else:
            msg = f"선택한 {len(unique_targets)}개의 Custom Series를 삭제할까요?"
        answer = QMessageBox.question(self, "Custom Series", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        removed = 0
        for file_name, series_name in unique_targets:
            spec_map = self.custom_series_defs.get(file_name)
            data_map = self.custom_series_data.get(file_name)
            if isinstance(spec_map, dict) and series_name in spec_map:
                del spec_map[series_name]
                removed += 1
            if isinstance(data_map, dict) and series_name in data_map:
                del data_map[series_name]
            if isinstance(spec_map, dict) and not spec_map:
                self.custom_series_defs.pop(file_name, None)
            if isinstance(data_map, dict) and not data_map:
                self.custom_series_data.pop(file_name, None)

        self._refresh_custom_series_list()
        self.statusBar().showMessage(f"Custom Series {removed}개 삭제 완료", 3000)

    def create_custom_series(self):
        if not self.loaded_datasets:
            QMessageBox.information(self, "Custom Series", "먼저 로그 파일을 로드해 주세요.")
            return

        dlg = CustomSeriesEditorDialog(self)
        if dlg.exec() != QDialog.Accepted or not isinstance(dlg.series_spec, dict):
            return

        spec = dict(dlg.series_spec)
        file_name = str(spec.get("file_name", "")).strip()
        series_name = str(spec.get("name", "")).strip()
        if not file_name or not series_name:
            QMessageBox.warning(self, "Custom Series", "Custom Series 저장 정보가 올바르지 않습니다.")
            return

        if file_name not in self.loaded_datasets:
            QMessageBox.warning(self, "Custom Series", "선택한 Dataset이 현재 로드되어 있지 않습니다.")
            return

        x = np.asarray(dlg.series_x, dtype=np.float64)
        y = np.asarray(dlg.series_y, dtype=np.float64)
        if len(x) == 0 or len(y) == 0:
            QMessageBox.warning(self, "Custom Series", "생성된 시계열 데이터가 비어 있습니다.")
            return

        file_specs = self.custom_series_defs.setdefault(file_name, {})
        file_data = self.custom_series_data.setdefault(file_name, {})
        if series_name in file_specs:
            answer = QMessageBox.question(
                self,
                "Custom Series",
                f"'{series_name}'가 이미 존재합니다. 덮어쓸까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        file_specs[series_name] = spec
        file_data[series_name] = (x, y)
        self._refresh_custom_series_list(select_key=(file_name, series_name))
        self.statusBar().showMessage(f"Custom Series 생성: {series_name}", 4000)

    def edit_custom_series(self):
        file_name, series_name = self._selected_custom_series_info()
        if not file_name or not series_name:
            QMessageBox.information(self, "Custom Series", "수정할 Custom Series를 먼저 선택해 주세요.")
            return

        old_spec_map = self.custom_series_defs.get(file_name, {})
        existing_spec = old_spec_map.get(series_name)
        if not isinstance(existing_spec, dict):
            QMessageBox.warning(self, "Custom Series", "선택한 Custom Series 정의를 찾지 못했습니다.")
            return

        dlg = CustomSeriesEditorDialog(self, existing_spec=dict(existing_spec))
        if dlg.exec() != QDialog.Accepted or not isinstance(dlg.series_spec, dict):
            return

        new_spec = dict(dlg.series_spec)
        new_file = str(new_spec.get("file_name", "")).strip()
        new_name = str(new_spec.get("name", "")).strip()
        if not new_file or not new_name:
            QMessageBox.warning(self, "Custom Series", "수정 결과가 올바르지 않습니다.")
            return

        if new_file not in self.loaded_datasets:
            QMessageBox.warning(self, "Custom Series", "선택한 Dataset이 현재 로드되어 있지 않습니다.")
            return

        x = np.asarray(dlg.series_x, dtype=np.float64)
        y = np.asarray(dlg.series_y, dtype=np.float64)
        if len(x) == 0 or len(y) == 0:
            QMessageBox.warning(self, "Custom Series", "생성된 시계열 데이터가 비어 있습니다.")
            return

        target_specs = self.custom_series_defs.setdefault(new_file, {})
        target_data = self.custom_series_data.setdefault(new_file, {})
        if (new_file, new_name) != (file_name, series_name) and new_name in target_specs:
            answer = QMessageBox.question(
                self,
                "Custom Series",
                f"'{new_name}'가 이미 존재합니다. 덮어쓸까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        old_specs = self.custom_series_defs.get(file_name, {})
        old_data = self.custom_series_data.get(file_name, {})
        if isinstance(old_specs, dict):
            old_specs.pop(series_name, None)
            if not old_specs:
                self.custom_series_defs.pop(file_name, None)
        if isinstance(old_data, dict):
            old_data.pop(series_name, None)
            if not old_data:
                self.custom_series_data.pop(file_name, None)

        self.custom_series_defs.setdefault(new_file, {})[new_name] = new_spec
        self.custom_series_data.setdefault(new_file, {})[new_name] = (x, y)
        self._refresh_custom_series_list(select_key=(new_file, new_name))
        self.statusBar().showMessage(f"Custom Series 수정: {new_name}", 4000)

    def _build_custom_series_eval_env(self, globals_text):
        safe_builtins = {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "float": float,
            "int": int,
            "round": round,
            "pow": pow,
        }
        env = {"__builtins__": safe_builtins, "np": np, "math": math}
        user_vars = {}
        for line in str(globals_text or "").splitlines():
            src = line.strip()
            if not src or src.startswith("#"):
                continue
            if "=" not in src:
                raise ValueError(f"Global variable 형식 오류: {src}")
            name, expr = src.split("=", 1)
            var_name = name.strip()
            if not var_name:
                raise ValueError(f"Global variable 이름 오류: {src}")
            user_vars[var_name] = eval(expr.strip(), env, user_vars)
        env.update(user_vars)
        return env

    def _compute_custom_series_from_spec(self, spec, eval_stack=None):
        base_xy = self._get_series_xy_from_uri(spec.get("input_uri", ""), require_time=True, eval_stack=eval_stack)
        if base_xy is None:
            raise ValueError("Input timeseries를 읽지 못했습니다.")
        time_arr, value_arr = base_xy
        if len(time_arr) == 0:
            raise ValueError("Input timeseries 데이터가 비어 있습니다.")

        aligned_sources = []
        for uri in spec.get("additional_uris", []):
            if not uri:
                aligned_sources.append(None)
                continue
            src_xy = self._get_series_xy_from_uri(uri, require_time=True, eval_stack=eval_stack)
            if src_xy is None:
                raise ValueError(f"추가 시계열을 읽지 못했습니다: {_format_signal_uri_label(uri)}")
            src_t, src_y = src_xy
            if len(src_t) == 0:
                aligned_sources.append(None)
                continue
            aligned_sources.append(np.interp(time_arr, src_t, src_y))

        env = self._build_custom_series_eval_env(spec.get("globals_text", ""))
        local_ns = {}
        exec(str(spec.get("function_code", "")), env, local_ns)
        fn = local_ns.get("function")
        if not callable(fn):
            raise ValueError("코드에 'def function(...)' 정의가 필요합니다.")

        kwargs = {"time": time_arr, "value": value_arr}
        for i, arr in enumerate(aligned_sources, start=1):
            kwargs[f"v{i}"] = arr

        try:
            sig = inspect.signature(fn)
            accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if accepts_var_kw:
                result = fn(**kwargs)
            else:
                accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
                result = fn(**accepted)
        except TypeError:
            result = fn(
                time_arr,
                value_arr,
                aligned_sources[0] if len(aligned_sources) > 0 else None,
                aligned_sources[1] if len(aligned_sources) > 1 else None,
                aligned_sources[2] if len(aligned_sources) > 2 else None,
                aligned_sources[3] if len(aligned_sources) > 3 else None,
            )

        out = np.asarray(result, dtype=np.float64)
        if out.ndim == 0:
            out = np.full_like(time_arr, float(out), dtype=np.float64)
        out = np.ravel(out)
        if len(out) != len(time_arr):
            raise ValueError(f"출력 길이({len(out)})가 입력 길이({len(time_arr)})와 다릅니다.")
        return np.asarray(time_arr, dtype=np.float64), out

    def _get_custom_series_xy(self, file_name, series_name, eval_stack=None):
        file_map = self.custom_series_data.get(file_name, {})
        if isinstance(file_map, dict):
            xy = file_map.get(series_name)
            if xy is not None:
                return xy

        spec_map = self.custom_series_defs.get(file_name, {})
        if not isinstance(spec_map, dict):
            return None
        spec = spec_map.get(series_name)
        if not isinstance(spec, dict):
            return None

        key = (file_name, series_name)
        stack = set(eval_stack or [])
        if key in stack:
            raise ValueError(f"Custom Series 순환 참조 감지: {file_name} | {series_name}")
        stack.add(key)
        xy = self._compute_custom_series_from_spec(spec, eval_stack=stack)
        self.custom_series_data.setdefault(file_name, {})[series_name] = xy
        return xy

    def _get_series_xy_from_uri(self, uri_text, require_time=False, eval_stack=None):
        parsed = _parse_signal_uri_text(uri_text)
        if not parsed:
            return None
        file_name, topic_name, signal_name, x_axis_col = parsed
        if topic_name == self.CUSTOM_SERIES_TOPIC:
            return self._get_custom_series_xy(file_name, signal_name, eval_stack=eval_stack)

        dataset = self.loaded_datasets.get(file_name)
        if dataset is None:
            return None
        topic = dataset.topics.get(topic_name)
        if topic is None or topic.dataframe is None:
            return None
        df = topic.dataframe

        x_col = "timestamp_sec" if require_time else x_axis_col
        if x_col not in df.columns:
            if require_time:
                return None
            if "timestamp_sec" in df.columns:
                x_col = "timestamp_sec"
            else:
                return None
        if signal_name not in df.columns:
            return None

        try:
            x = np.asarray(df[x_col].to_numpy(), dtype=np.float64)
            y = np.asarray(df[signal_name].to_numpy(), dtype=np.float64)
        except Exception:
            return None
        if len(x) == 0 or len(y) == 0 or len(x) != len(y):
            return None
        mask = np.isfinite(x) & np.isfinite(y)
        if not np.any(mask):
            return None
        return x[mask], y[mask]

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_splitter_applied:
            QTimer.singleShot(0, lambda: self._apply_startup_splitter_ratio(force=True))

    def change_theme(self, mode):
        is_dark = (mode == "Dark Mode")
        
        if is_dark:
            bg_color, fg_color = '#1e1e1e', '#aaaaaa'
            tree_bg, tree_fg = '#ffffff', '#333333'
            left_bg = '#d7dbe0'
            brand_bg = '#f3f5f7'
            panel_bg = '#f9fafb'
            header_bg = '#3c4653'
            border_color = '#9ca7b3'
            menu_fg = '#1f2b36'
            logo_fg = '#1d2c5f'
            app_style = """
                QMainWindow { background-color: #1e1e1e; }
                QSplitter::handle { background-color: #333333; }
                QTabBar::tab { background-color: #2b2b2b; color: #aaaaaa; padding: 4px 12px; font-size: 13px; font-weight: 700; }
                QTabBar::tab:selected { background-color: #1A2D57; color: white; }
                QPushButton#newTabButton { background-color: #2196F3; color: #ffffff; padding: 4px 12px; font-size: 13px; font-weight: 700; border-radius: 3px; border: 1px solid #1f7fc9; }
                QPushButton#newTabButton:hover { background-color: #2ea3ff; }
                #blankStateWidget { background-color: #f5f7fa; border-left: 1px solid #c9d2dc; }
                #blankStateTitle { color: #24344f; font-size: 26px; font-weight: 800; }
                #blankStateHint { color: #50627a; font-size: 14px; font-weight: 600; }
                QPushButton#blankStateButton { min-width: 180px; padding: 7px 16px; background-color: #1A2D57; color: #ffffff; border: none; border-radius: 4px; font-weight: 700; font-size: 13px; }
                QPushButton#blankStateButton:hover { background-color: #223a70; }
                #leftContainer { background-color: %s; border-right: 1px solid %s; }
                #leftBrandBar { background-color: %s; border-bottom: 1px solid %s; min-height: 54px; }
                #logoLabel { color: %s; font-size: 18px; font-weight: 800; letter-spacing: 1px; }
                #topMenuBar { background-color: transparent; border: none; color: %s; }
                QMenuBar#topMenuBar::item { background: transparent; color: inherit; padding: 2px 8px; font-size: 13px; font-weight: 600; }
                QMenuBar#topMenuBar::item:selected { background-color: #e2e8f0; border-radius: 3px; }
                QMenu { background-color: #ffffff; color: #1f2b36; border: 1px solid #b8c2cd; padding: 4px; }
                QMenu::item { min-width: 170px; padding: 6px 14px; font-size: 12px; }
                QMenu::item:selected { background-color: #e6ecf5; border-radius: 3px; }
                #leftPublishersHeader { background-color: %s; color: #e9edf1; font-size: 14px; font-weight: 700; padding: 6px 10px; border-top: 1px solid #2e3641; border-bottom: 1px solid #2e3641; }
                #leftPublishersPanel { background-color: %s; border-bottom: 1px solid %s; }
                #csvTitleLabel, #layoutTitleLabel { color: #222831; font-size: 12px; font-weight: 600; }
                QPushButton#layoutActionButton { background-color: #e9edf2; color: #3a4653; border: 1px solid #b8c2cd; border-radius: 2px; font-size: 10px; font-weight: 600; padding: 0px 3px; }
                QPushButton#layoutActionButton:hover { background-color: #dfe5ec; }
                QPushButton#layoutToolButton { background-color: #e9edf2; color: #3a4653; border: 1px solid #b8c2cd; border-radius: 2px; font-size: 12px; font-weight: 700; padding: 0px; }
                QPushButton#layoutToolButton:hover { background-color: #dfe5ec; }
                #customSeriesPanel { background-color: #f3f6fa; border-top: 1px solid #c6d0db; }
                #customSeriesLabel { color: #1f2b36; font-size: 12px; font-weight: 700; }
                QPushButton#customSeriesToolButton { background-color: #e9edf2; color: #2f3b47; border: 1px solid #b8c2cd; border-radius: 3px; font-size: 11px; font-weight: 700; padding: 1px 6px; }
                QPushButton#customSeriesToolButton:hover { background-color: #dfe5ec; }
                QListWidget#customSeriesList { background-color: #ffffff; color: #1f2b36; border: 1px solid #c5ced8; font-size: 12px; }
                QListWidget#customSeriesList::item:selected { background-color: #dbe7f7; color: #0f1f34; }
                QLineEdit#treeSearchInput {
                    margin: 6px 8px 4px 8px;
                    padding: 4px 8px;
                    border: 1px solid #b8c2cd;
                    border-radius: 4px;
                    background-color: #ffffff;
                    color: #1f2b36;
                    font-size: 12px;
                    selection-background-color: #1A2D57;
                    selection-color: #ffffff;
                }
                QLineEdit#treeSearchInput:focus { border: 1px solid #1A2D57; }
                #treeContainer { background-color: %s; border-top: 1px solid %s; }
                QTreeView { background-color: %s; color: %s; border: none; font-size: 14px; }
            """ % (
                left_bg, border_color, brand_bg, border_color, logo_fg, menu_fg, header_bg,
                panel_bg, border_color, panel_bg, border_color, tree_bg, tree_fg
            )
        else:
            bg_color, fg_color = '#ffffff', '#000000'
            tree_bg, tree_fg = '#f5f5f5', '#000000'
            left_bg = '#eceff3'
            brand_bg = '#ffffff'
            panel_bg = '#f9fafc'
            header_bg = '#4f5967'
            border_color = '#c4ccd6'
            menu_fg = '#000000'
            logo_fg = '#243366'
            app_style = """
                QMainWindow { background-color: #f0f0f0; }
                QSplitter::handle { background-color: #cccccc; }
                QTabBar::tab { background-color: #e0e0e0; color: #000000; padding: 4px 12px; font-size: 13px; font-weight: 700; border: 1px solid #ccc; }
                QTabBar::tab:selected { background-color: #1A2D57; color: white; }
                QPushButton#newTabButton { background-color: #2196F3; color: #ffffff; padding: 4px 12px; font-size: 13px; font-weight: 700; border-radius: 3px; border: 1px solid #1f7fc9; }
                QPushButton#newTabButton:hover { background-color: #2ea3ff; }
                #blankStateWidget { background-color: #f7f9fc; border-left: 1px solid #d2d9e2; }
                #blankStateTitle { color: #1f2f49; font-size: 26px; font-weight: 800; }
                #blankStateHint { color: #000000; font-size: 14px; font-weight: 600; }
                QPushButton#blankStateButton { min-width: 180px; padding: 7px 16px; background-color: #1A2D57; color: #ffffff; border: none; border-radius: 4px; font-weight: 700; font-size: 13px; }
                QPushButton#blankStateButton:hover { background-color: #223a70; }
                #leftContainer { background-color: %s; border-right: 1px solid %s; }
                #leftBrandBar { background-color: %s; border-bottom: 1px solid %s; min-height: 54px; }
                #logoLabel { color: %s; font-size: 18px; font-weight: 800; letter-spacing: 1px; }
                #topMenuBar { background-color: transparent; border: none; color: %s; }
                QMenuBar#topMenuBar::item { background: transparent; color: inherit; padding: 2px 8px; font-size: 13px; font-weight: 600; }
                QMenuBar#topMenuBar::item:selected { background-color: #e2e8f0; border-radius: 3px; }
                QMenu { background-color: #ffffff; color: #000000; border: 1px solid #b8c2cd; padding: 4px; }
                QMenu::item { min-width: 170px; padding: 6px 14px; font-size: 12px; }
                QMenu::item:selected { background-color: #e6ecf5; border-radius: 3px; }
                #leftPublishersHeader { background-color: %s; color: #f2f4f7; font-size: 14px; font-weight: 700; padding: 6px 10px; border-top: 1px solid #3f4752; border-bottom: 1px solid #3f4752; }
                #leftPublishersPanel { background-color: %s; border-bottom: 1px solid %s; }
                #csvTitleLabel, #layoutTitleLabel { color: #000000; font-size: 12px; font-weight: 600; }
                QPushButton#layoutActionButton { background-color: #e9edf2; color: #000000; border: 1px solid #b8c2cd; border-radius: 2px; font-size: 10px; font-weight: 600; padding: 0px 3px; }
                QPushButton#layoutActionButton:hover { background-color: #dfe5ec; }
                QPushButton#layoutToolButton { background-color: #e9edf2; color: #000000; border: 1px solid #b8c2cd; border-radius: 2px; font-size: 12px; font-weight: 700; padding: 0px; }
                QPushButton#layoutToolButton:hover { background-color: #dfe5ec; }
                #customSeriesPanel { background-color: #f3f6fa; border-top: 1px solid #c6d0db; }
                #customSeriesLabel { color: #000000; font-size: 12px; font-weight: 700; }
                QPushButton#customSeriesToolButton { background-color: #e9edf2; color: #000000; border: 1px solid #b8c2cd; border-radius: 3px; font-size: 11px; font-weight: 700; padding: 1px 6px; }
                QPushButton#customSeriesToolButton:hover { background-color: #dfe5ec; }
                QListWidget#customSeriesList { background-color: #ffffff; color: #000000; border: 1px solid #c5ced8; font-size: 12px; }
                QListWidget#customSeriesList::item:selected { background-color: #dbe7f7; color: #0f1f34; }
                QLineEdit#treeSearchInput {
                    margin: 6px 8px 4px 8px;
                    padding: 4px 8px;
                    border: 1px solid #b8c2cd;
                    border-radius: 4px;
                    background-color: #ffffff;
                    color: #000000;
                    font-size: 12px;
                    selection-background-color: #1A2D57;
                    selection-color: #ffffff;
                }
                QLineEdit#treeSearchInput:focus { border: 1px solid #1A2D57; }
                #treeContainer { background-color: %s; border-top: 1px solid %s; }
                QTreeView { background-color: %s; color: %s; border: none; font-size: 14px; }
            """ % (
                left_bg, border_color, brand_bg, border_color, logo_fg, menu_fg, header_bg,
                panel_bg, border_color, panel_bg, border_color, tree_bg, tree_fg
            )

        pg.setConfigOption('background', bg_color)
        pg.setConfigOption('foreground', fg_color)
        self.setStyleSheet(app_style)
        self._update_layout_action_button_sizes()
        self.file_drop_widget.apply_theme(is_dark)

        for plot_widget in self.findChildren(AdvancedPlot):
            plot_widget.plot.setBackground(bg_color)
            plot_widget.plot.getAxis('bottom').setPen(fg_color)
            plot_widget.plot.getAxis('left').setPen(fg_color)
            plot_widget.plot.getAxis('bottom').setTextPen(fg_color)
            plot_widget.plot.getAxis('left').setTextPen(fg_color)
            plot_widget.apply_theme_to_overlay(is_dark)
            plot_widget.apply_theme_to_plot_controls(is_dark)
            plot_widget.apply_theme_to_3d(is_dark)
            plot_widget.apply_theme_to_2d_flight_path(is_dark)

        for workspace in self.findChildren(Workspace):
            if is_dark:
                workspace.lbl_range_info.setStyleSheet("color: #888888; font-size: 13px; font-weight: bold;")
                workspace.lbl_speed.setStyleSheet("color: #888888; font-weight: bold; margin-left: 10px; margin-right: 10px;")
            else:
                workspace.lbl_range_info.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold;")
                workspace.lbl_speed.setStyleSheet("color: #000000; font-weight: bold; margin-left: 10px; margin-right: 10px;")

    def _build_top_menus(self):
        self.top_menu_bar.clear()

        app_menu = self.top_menu_bar.addMenu("App")
        action_clear_data = app_menu.addAction("Clear Data Points")
        action_delete_all = app_menu.addAction("Delete Everything")
        app_menu.addSeparator()
        action_exit = app_menu.addAction("Exit")

        tools_menu = self.top_menu_bar.addMenu("Tools")
        theme_menu = tools_menu.addMenu("Theme")
        action_theme_dark = theme_menu.addAction("Dark Mode")
        action_theme_light = theme_menu.addAction("Light Mode")

        angle_menu = tools_menu.addMenu("Angle")
        action_angle_pitch = angle_menu.addAction("Pitch")
        action_angle_roll = angle_menu.addAction("Roll")
        action_angle_yaw = angle_menu.addAction("Yaw")

        angular_menu = tools_menu.addMenu("Angular")
        action_angular_pitch = angular_menu.addAction("Pitch")
        action_angular_roll = angular_menu.addAction("Roll")
        action_angular_yaw = angular_menu.addAction("Yaw")

        tools_menu.addSeparator()
        action_speed = tools_menu.addAction("Airspeed vs Ground Speed")
        action_alt_tracking = tools_menu.addAction("Altitude Tracking")

        fw_menu = tools_menu.addMenu("Fixed Wing")
        action_fw_tecs = fw_menu.addAction("TECS Throttle")

        err_menu = tools_menu.addMenu("Attitude Error")
        action_err_pitch = err_menu.addAction("Pitch Error")
        action_err_roll = err_menu.addAction("Roll Error")
        action_err_yaw = err_menu.addAction("Yaw Error")

        vib_menu = tools_menu.addMenu("Vibration Analysis")
        accel_fft_menu = vib_menu.addMenu("Accel FFT")
        action_accel_fft_0 = accel_fft_menu.addAction("accel[0] FFT")
        action_accel_fft_1 = accel_fft_menu.addAction("accel[1] FFT")
        action_accel_fft_2 = accel_fft_menu.addAction("accel[2] FFT")

        gyro_fft_menu = vib_menu.addMenu("Gyro FFT")
        action_gyro_fft_0 = gyro_fft_menu.addAction("gyro[0] FFT")
        action_gyro_fft_1 = gyro_fft_menu.addAction("gyro[1] FFT")
        action_gyro_fft_2 = gyro_fft_menu.addAction("gyro[2] FFT")

        flight_path_menu = tools_menu.addMenu("Flight Path")
        action_flight_2d = flight_path_menu.addAction("2D Path")
        action_flight_3d = flight_path_menu.addAction("3D Path")

        function_menu = self.top_menu_bar.addMenu("Function")
        mc_panel_menu = function_menu.addMenu("Multicopter")
        action_mc_panel1 = mc_panel_menu.addAction("표준 분석 패널 1")
        action_mc_panel2 = mc_panel_menu.addAction("표준 분석 패널 2")

        fw_panel_menu = function_menu.addMenu("Fixed-Wing")
        action_fw_panel1 = fw_panel_menu.addAction("표준 분석 패널 1")
        action_fw_panel2 = fw_panel_menu.addAction("표준 분석 패널 2")

        vtol_panel_menu = function_menu.addMenu("VTOL")
        action_vtol_panel1 = vtol_panel_menu.addAction("표준 분석 패널 1")
        action_vtol_panel2 = vtol_panel_menu.addAction("표준 분석 패널 2")

        self.top_menu_bar.addMenu("Help")

        action_clear_data.triggered.connect(self.clear_data_points)
        action_delete_all.triggered.connect(self.delete_everything)
        action_exit.triggered.connect(self.close)
        action_theme_dark.triggered.connect(lambda: self.theme_combo.setCurrentText("Dark Mode"))
        action_theme_light.triggered.connect(lambda: self.theme_combo.setCurrentText("Light Mode"))
        action_angle_pitch.triggered.connect(lambda: self.generate_angle_plot("pitch"))
        action_angle_roll.triggered.connect(lambda: self.generate_angle_plot("roll"))
        action_angle_yaw.triggered.connect(lambda: self.generate_angle_plot("yaw"))
        action_angular_pitch.triggered.connect(lambda: self.generate_angular_rate_plot("pitch"))
        action_angular_roll.triggered.connect(lambda: self.generate_angular_rate_plot("roll"))
        action_angular_yaw.triggered.connect(lambda: self.generate_angular_rate_plot("yaw"))
        action_speed.triggered.connect(self.generate_speed_plot)
        action_alt_tracking.triggered.connect(self.generate_altitude_tracking_plot)
        action_fw_tecs.triggered.connect(self.generate_fw_tecs_plot)
        action_err_pitch.triggered.connect(lambda: self.generate_attitude_error_plot("pitch"))
        action_err_roll.triggered.connect(lambda: self.generate_attitude_error_plot("roll"))
        action_err_yaw.triggered.connect(lambda: self.generate_attitude_error_plot("yaw"))
        action_accel_fft_0.triggered.connect(lambda: self.generate_vibration_fft_axis("accel", 0))
        action_accel_fft_1.triggered.connect(lambda: self.generate_vibration_fft_axis("accel", 1))
        action_accel_fft_2.triggered.connect(lambda: self.generate_vibration_fft_axis("accel", 2))
        action_gyro_fft_0.triggered.connect(lambda: self.generate_vibration_fft_axis("gyro", 0))
        action_gyro_fft_1.triggered.connect(lambda: self.generate_vibration_fft_axis("gyro", 1))
        action_gyro_fft_2.triggered.connect(lambda: self.generate_vibration_fft_axis("gyro", 2))
        action_flight_2d.triggered.connect(self.generate_flight_path_2d_plot)
        action_flight_3d.triggered.connect(self.generate_flight_path_3d_plot)
        action_mc_panel1.triggered.connect(lambda: self.generate_standard_panel("Multicopter", 1))
        action_mc_panel2.triggered.connect(lambda: self.generate_standard_panel("Multicopter", 2))
        action_fw_panel1.triggered.connect(lambda: self.generate_standard_panel("Fixed-Wing", 1))
        action_fw_panel2.triggered.connect(lambda: self.generate_standard_panel("Fixed-Wing", 2))
        action_vtol_panel1.triggered.connect(lambda: self.generate_standard_panel("VTOL", 1))
        action_vtol_panel2.triggered.connect(lambda: self.generate_standard_panel("VTOL", 2))

    def clear_data_points(self):
        current_ws = self.tab_widget.currentWidget()
        if not isinstance(current_ws, Workspace):
            return

        target_plot = None
        if self.last_active_plot and self.last_active_plot in current_ws.findChildren(AdvancedPlot):
            target_plot = self.last_active_plot
        else:
            for plot in current_ws.findChildren(AdvancedPlot):
                if plot.plotted_signals:
                    target_plot = plot
                    break
            if target_plot is None:
                target_plot = current_ws.first_plot

        if target_plot is None:
            return

        target_plot.clear_plot_data()
        self.statusBar().showMessage("현재 그래프의 데이터 포인트를 초기화했습니다.", 3000)

    def delete_everything(self):
        answer = QMessageBox.question(
            self,
            "Delete Everything",
            "모든 그래프와 로드된 데이터를 초기화할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.loaded_datasets.clear()
        self.loaded_aircraft_types.clear()
        self.loaded_log_metadata.clear()
        self.active_analysis_log = None
        self.custom_series_defs.clear()
        self.custom_series_data.clear()
        self.tree_model.clear()
        self.tree_view.setHeaderHidden(True)
        self.last_active_plot = None
        if self.log_info_dialog is not None:
            self.log_info_dialog.close()
            self.log_info_dialog.deleteLater()
            self.log_info_dialog = None

        while self.tab_widget.count() > 0:
            ws = self.tab_widget.widget(0)
            self.tab_widget.removeTab(0)
            ws.deleteLater()

        self.workspace_count = 0
        self._update_right_panel_state()
        self._refresh_custom_series_list()
        self.file_drop_widget.setText("Date(ulg) Upload\n(Multiple choices available)")
        self.statusBar().showMessage("전체 데이터가 초기화되었습니다.", 4000)

    @staticmethod
    def _metadata_value_to_text(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            for enc in ("utf-8", "latin-1"):
                try:
                    return value.decode(enc, errors="replace")
                except Exception:
                    continue
            return repr(value)
        try:
            return str(value)
        except Exception:
            return repr(value)

    def _extract_log_metadata(self, file_path):
        result = {
            "firmware": {},
            "parameters": {},
            "messages": [],
        }
        try:
            from pyulog import ULog
            ulog = ULog(file_path)

            info = getattr(ulog, "msg_info_dict", {}) or {}
            info_multi = getattr(ulog, "msg_info_multiple_dict", {}) or {}
            firmware = {}
            for k, v in info.items():
                k_txt = self._metadata_value_to_text(k)
                firmware[k_txt] = self._metadata_value_to_text(v)
            for k, v in info_multi.items():
                k_txt = self._metadata_value_to_text(k)
                if isinstance(v, (list, tuple)):
                    firmware[k_txt] = " | ".join(self._metadata_value_to_text(x) for x in v[:8])
                else:
                    firmware[k_txt] = self._metadata_value_to_text(v)

            params = getattr(ulog, "initial_parameters", {}) or {}
            parameters = {self._metadata_value_to_text(k): self._metadata_value_to_text(v) for k, v in params.items()}

            raw_messages = getattr(ulog, "logged_messages", None) or []
            messages = []
            for msg in raw_messages:
                ts = self._metadata_value_to_text(getattr(msg, "timestamp", ""))
                level = self._metadata_value_to_text(getattr(msg, "log_level", getattr(msg, "level", "")))
                text = self._metadata_value_to_text(getattr(msg, "message", getattr(msg, "msg", "")))
                if not text:
                    text = self._metadata_value_to_text(msg)
                messages.append({"timestamp": ts, "level": level, "text": text})

            result["firmware"] = firmware
            result["parameters"] = parameters
            result["messages"] = messages
        except Exception as e:
            result["firmware"] = {"parse_error": self._metadata_value_to_text(e)}
            result["parameters"] = {}
            result["messages"] = []
        return result

    def _ensure_log_info_dialog(self):
        if self.log_info_dialog is None:
            self.log_info_dialog = LogInfoCompareDialog(self)

    def _refresh_log_info_dialog(self):
        self._ensure_log_info_dialog()
        self.log_info_dialog.update_data(self.loaded_log_metadata, active_file=self.active_analysis_log)

    def show_log_info_dialog(self, target_file=None):
        if target_file and target_file in self.loaded_datasets:
            self._set_active_analysis_log(target_file, show_status=False)
        self._refresh_log_info_dialog()
        self.log_info_dialog.show()
        self.log_info_dialog.raise_()
        self.log_info_dialog.activateWindow()

    def _iter_tree_file_nodes(self):
        root_item = self.tree_model.invisibleRootItem()
        for row in range(root_item.rowCount()):
            item = root_item.child(row)
            if item is not None:
                yield item

    def _update_tree_file_node_styles(self):
        for file_node in self._iter_tree_file_nodes():
            file_name = file_node.data(Qt.UserRole)
            aircraft_type = file_node.data(Qt.UserRole + 1)
            is_active = (file_name == self.active_analysis_log and file_name in self.loaded_datasets)
            prefix = "▶ " if is_active else ""
            file_node.setText(f"{prefix}{file_name} | Type : {aircraft_type}")
            file_node.setForeground(QBrush(QColor("#1A2D57" if is_active else "#000000")))

    def _set_active_analysis_log(self, file_name, show_status=True):
        if not file_name or file_name not in self.loaded_datasets:
            return False
        self.active_analysis_log = file_name
        self._update_tree_file_node_styles()
        self._refresh_log_info_dialog()
        ws = self._current_workspace()
        if isinstance(ws, Workspace):
            ws.set_aircraft_type(self.loaded_aircraft_types.get(file_name, "Unknown"))
        if show_status:
            aircraft = self.loaded_aircraft_types.get(file_name, "Unknown")
            self.statusBar().showMessage(f"Active Analysis Log: {file_name} | Aircraft Type: {aircraft}", 5000)
        return True

    def _show_tree_context_menu(self, pos):
        idx = self.tree_view.indexAt(pos)
        if not idx.isValid():
            return
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return
        file_item = item
        while file_item.parent() is not None:
            file_item = file_item.parent()
        file_name = file_item.data(Qt.UserRole)
        if not file_name or file_name not in self.loaded_datasets:
            return

        menu = QMenu(self)
        act_set_active = menu.addAction("해당 로그로 분석 설정하기")
        act_show_info = menu.addAction("로그 정보 비교 창 열기")
        selected = menu.exec(self.tree_view.viewport().mapToGlobal(pos))
        if selected == act_set_active:
            self._set_active_analysis_log(file_name, show_status=True)
        elif selected == act_show_info:
            self.show_log_info_dialog(target_file=file_name)

    @staticmethod
    def _parse_render_uri(uri_text):
        parts = [p.strip() for p in str(uri_text or "").split("|")]
        if len(parts) < 3:
            return None
        file_name = parts[0]
        topic_name = parts[1]
        signal_name = parts[2]
        x_axis_col = parts[3] if len(parts) >= 4 and parts[3] else "timestamp_sec"
        is_fft = False
        if len(parts) >= 5:
            is_fft = parts[4].lower() == "true"
        return file_name, topic_name, signal_name, x_axis_col, is_fft

    def _collect_workspace_export_targets(self, workspace):
        targets = []
        seen = set()
        for plot in workspace.findChildren(AdvancedPlot):
            for uri in plot.plotted_signals.keys():
                parsed = self._parse_render_uri(uri)
                if parsed is None:
                    continue
                file_name, topic_name, signal_name, x_axis_col, is_fft = parsed
                if is_fft:
                    continue
                if x_axis_col != "timestamp_sec":
                    continue
                key = (file_name, topic_name, signal_name, x_axis_col)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(key)
        return targets

    @staticmethod
    def _estimate_signal_hz(timestamps):
        arr = np.asarray(timestamps, dtype=np.float64)
        if arr.size < 2:
            return None
        dt = np.diff(arr)
        dt = dt[np.isfinite(dt) & (dt > 1e-9)]
        if dt.size == 0:
            return None
        median_dt = float(np.median(dt))
        if not np.isfinite(median_dt) or median_dt <= 0.0:
            return None
        return float(1.0 / median_dt)

    @staticmethod
    def _format_hz_label(hz_value):
        if hz_value is None:
            return "NA"
        try:
            hz = float(hz_value)
        except Exception:
            return "NA"
        if not np.isfinite(hz) or hz <= 0:
            return "NA"
        return f"{hz:.2f}Hz"

    @staticmethod
    def _duration_hz_fallback(timestamps):
        arr = np.asarray(timestamps, dtype=np.float64)
        if arr.size < 2:
            return 0.0
        t_min = float(np.min(arr))
        t_max = float(np.max(arr))
        duration = t_max - t_min
        if not np.isfinite(duration) or duration <= 1e-9:
            return 0.0
        return float((arr.size - 1) / duration)

    @staticmethod
    def _build_export_column_name(file_name, topic_name, signal_name, hz_text, used_columns):
        candidates = [
            f"{signal_name} [{hz_text}]",
            f"{topic_name}.{signal_name} [{hz_text}]",
            f"{file_name}.{topic_name}.{signal_name} [{hz_text}]",
        ]
        for cand in candidates:
            if cand not in used_columns:
                return cand
        idx = 2
        while True:
            fallback = f"{file_name}.{topic_name}.{signal_name} [{hz_text}] ({idx})"
            if fallback not in used_columns:
                return fallback
            idx += 1

    def export_current_workspace_csv(self):
        current_ws = self.tab_widget.currentWidget()
        if not isinstance(current_ws, Workspace):
            QMessageBox.information(self, "CSV Export", "현재 활성화된 분석창이 없습니다. 먼저 + New Tab으로 분석창을 생성해 주세요.")
            return

        export_targets = self._collect_workspace_export_targets(current_ws)
        print(f"[CSV] export targets: {len(export_targets)}")

        if not export_targets:
            QMessageBox.information(
                self,
                "CSV Export",
                "현재 분석창에 CSV로 내보낼 시계열 신호가 없습니다.\n"
                "- 시간축(timestamp_sec) 기반 신호를 그래프에 올린 뒤 다시 시도해 주세요.",
            )
            return

        signal_infos = []
        used_columns = set()
        for file_name, topic_name, signal_name, x_axis_col in export_targets:
            uri_text = f"{file_name}|{topic_name}|{signal_name}|{x_axis_col}"
            try:
                xy = self._get_series_xy_from_uri(uri_text, require_time=True)
            except Exception:
                xy = None
            if xy is None:
                continue
            x, y = xy
            if len(x) == 0 or len(y) == 0:
                continue

            signal_df = pl.DataFrame(
                {
                    "timestamp_sec": np.asarray(x, dtype=np.float64),
                    "value": np.asarray(y, dtype=np.float64),
                }
            )
            signal_df = (
                signal_df
                .drop_nulls(subset=["timestamp_sec"])
                .unique(subset=["timestamp_sec"], keep="first")
                .sort("timestamp_sec")
            )
            if signal_df.height == 0:
                continue

            ts = signal_df["timestamp_sec"].to_numpy()
            hz = self._estimate_signal_hz(ts)
            if hz is None:
                hz = self._duration_hz_fallback(ts)
            hz_text = self._format_hz_label(hz)

            col_name = self._build_export_column_name(file_name, topic_name, signal_name, hz_text, used_columns)
            used_columns.add(col_name)
            signal_df = signal_df.rename({"value": col_name})

            signal_infos.append(
                {
                    "file_name": file_name,
                    "topic_name": topic_name,
                    "signal_name": signal_name,
                    "col_name": col_name,
                    "hz": hz,
                    "hz_text": hz_text,
                    "t_min": float(signal_df["timestamp_sec"].min()),
                    "t_max": float(signal_df["timestamp_sec"].max()),
                    "df": signal_df,
                    "sample_count": int(signal_df.height),
                }
            )

        if not signal_infos:
            QMessageBox.warning(self, "CSV Export", "내보낼 데이터프레임을 생성하지 못했습니다.")
            return

        base_info = max(
            signal_infos,
            key=lambda s: (
                float(s["hz"]) if s["hz"] is not None else 0.0,
                s["sample_count"],
            ),
        )

        # Use the highest-rate signal as the common timeline, then align others
        # using backward asof-join (zero-order hold / forward-fill semantics).
        export_df = base_info["df"].select("timestamp_sec")
        for info in signal_infos:
            col_name = info["col_name"]
            source_df = info["df"]
            export_df = export_df.join_asof(source_df, on="timestamp_sec", strategy="backward")
            t_max = float(info["t_max"])
            export_df = export_df.with_columns(
                pl.when(pl.col("timestamp_sec") > pl.lit(t_max))
                .then(pl.lit(None, dtype=pl.Float64))
                .otherwise(pl.col(col_name))
                .alias(col_name)
            )

        current_idx = self.tab_widget.currentIndex()
        current_tab_text = self.tab_widget.tabText(current_idx) if current_idx >= 0 else ""
        default_stem = current_tab_text.split("|")[0].replace("분석:", "").strip().replace(" ", "_")
        if not default_stem:
            default_stem = "workspace_signals"
        default_name = f"{default_stem}.csv"
        output_path, _ = QFileDialog.getSaveFileName(self, "CSV 저장", default_name, "CSV Files (*.csv)")
        if not output_path:
            self.statusBar().showMessage("CSV 저장이 취소되었습니다.", 2500)
            return

        export_df.write_csv(output_path)
        signal_count = len(export_df.columns) - 1
        base_desc = f"{base_info['signal_name']} ({base_info['hz_text']})"
        self.statusBar().showMessage(
            f"CSV 저장 완료: {os.path.basename(output_path)} ({signal_count}개 신호, 기준축: {base_desc})",
            5000,
        )
        hz_preview_lines = []
        for info in signal_infos[:8]:
            hz_preview_lines.append(f"- {info['topic_name']}.{info['signal_name']}: {info['hz_text']}")
        if len(signal_infos) > 8:
            hz_preview_lines.append(f"- ... 외 {len(signal_infos) - 8}개")
        QMessageBox.information(
            self,
            "CSV Export",
            (
                "CSV 저장 완료\n"
                f"경로: {output_path}\n"
                f"신호 수: {signal_count}\n"
                f"기준 시간축: {base_desc}\n\n"
                "신호별 추정 샘플링 주기:\n"
                + "\n".join(hz_preview_lines)
            ),
        )

    def _get_current_workspace_and_plot(self):
        current_ws = self.tab_widget.currentWidget()
        if not isinstance(current_ws, Workspace):
            return None, None

        target_plot = None
        if self.last_active_plot and self.last_active_plot in current_ws.findChildren(AdvancedPlot):
            target_plot = self.last_active_plot
        if target_plot is None:
            for plot in current_ws.findChildren(AdvancedPlot):
                if plot.plotted_signals:
                    target_plot = plot
                    break
        if target_plot is None:
            target_plot = current_ws.first_plot
        return current_ws, target_plot

    def _get_dataset_for_tools(self, preferred_plot=None):
        if self.active_analysis_log and self.active_analysis_log in self.loaded_datasets:
            file_name = self.active_analysis_log
            return file_name, self.loaded_datasets[file_name], self.loaded_aircraft_types.get(file_name, "Unknown")

        if preferred_plot and preferred_plot.plotted_signals:
            try:
                first_uri = next(iter(preferred_plot.plotted_signals.keys()))
                file_name = first_uri.split("|")[0]
                if file_name in self.loaded_datasets:
                    return file_name, self.loaded_datasets[file_name], self.loaded_aircraft_types.get(file_name, "Unknown")
            except Exception:
                pass

        current_idx = self.tab_widget.currentIndex()
        tab_text = self.tab_widget.tabText(current_idx) if current_idx >= 0 else ""
        if tab_text.startswith("분석:"):
            file_name = tab_text.split("|")[0].replace("분석:", "").strip()
            if file_name in self.loaded_datasets:
                return file_name, self.loaded_datasets[file_name], self.loaded_aircraft_types.get(file_name, "Unknown")

        if self.loaded_datasets:
            file_name = next(iter(self.loaded_datasets.keys()))
            return file_name, self.loaded_datasets[file_name], self.loaded_aircraft_types.get(file_name, "Unknown")
        return None, None, None

    @staticmethod
    def _find_topic_by_prefixes(dataset, prefixes):
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        for prefix in prefixes:
            if prefix in dataset.topics:
                return prefix
        for topic_name in dataset.topics.keys():
            for prefix in prefixes:
                if topic_name.startswith(prefix):
                    return topic_name
        return None

    @staticmethod
    def _find_signal_in_topic(dataset, topic_name, candidates):
        if not topic_name or topic_name not in dataset.topics:
            return None
        cols = dataset.topics[topic_name].dataframe.columns
        for cand in candidates:
            if cand in cols:
                return cand
        return None

    def _prepare_tools_plot(self, title):
        current_ws, target_plot = self._get_current_workspace_and_plot()
        if current_ws is None or target_plot is None:
            self.add_workspace()
            current_ws, target_plot = self._get_current_workspace_and_plot()
            if current_ws is None or target_plot is None:
                return None, None

        if target_plot.plotted_signals:
            new_plot = target_plot.split_layout(Qt.Vertical)
            if new_plot is not None:
                target_plot = new_plot
            else:
                target_plot.clear_plot_data()
        else:
            target_plot.clear_plot_data()

        target_plot.plot.setTitle(title)
        self.last_active_plot = target_plot
        return current_ws, target_plot

    @staticmethod
    def _axis_name(axis):
        return axis.capitalize()

    def _render_pair(self, plot, file_name, sp_topic, sp_signal, act_topic, act_signal, title, show_message=True):
        if not sp_topic or not sp_signal or not act_topic or not act_signal:
            if show_message:
                QMessageBox.warning(self, "Tools", f"필요한 신호를 찾지 못했습니다: {title}")
            return False
        plot.clear_plot_data()
        plot.plot.setTitle(title)
        ok1 = plot.render_signal(file_name, sp_topic, sp_signal, color="#FF6B6B")
        ok2 = plot.render_signal(file_name, act_topic, act_signal, color="#4DA3FF")
        if not (ok1 or ok2):
            if show_message:
                QMessageBox.warning(self, "Tools", f"그래프 생성에 실패했습니다: {title}")
            return False
        plot.auto_fit_view()
        return True

    def generate_angle_plot(self, axis):
        _, target_plot = self._prepare_tools_plot(f"{self._axis_name(axis)} Angle (Actual) vs {self._axis_name(axis)} Angle Setpoint")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude")
        sp_candidates = {
            "pitch": ["pitch_sp_euler", "pitch", "pitch_body"],
            "roll": ["roll_sp_euler", "roll", "roll_body"],
            "yaw": ["yaw_sp_euler", "yaw", "yaw_body"],
        }
        act_candidates = {
            "pitch": ["pitch_euler", "pitch"],
            "roll": ["roll_euler", "roll"],
            "yaw": ["yaw_euler", "yaw"],
        }
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, sp_candidates.get(axis, []))
        act_signal = self._find_signal_in_topic(dataset, act_topic, act_candidates.get(axis, []))
        self._render_pair(
            target_plot,
            file_name,
            sp_topic,
            sp_signal,
            act_topic,
            act_signal,
            f"{self._axis_name(axis)} Angle (Actual) vs {self._axis_name(axis)} Angle Setpoint",
        )

    def generate_angular_rate_plot(self, axis):
        _, target_plot = self._prepare_tools_plot(f"{self._axis_name(axis)} Angular Rate (Actual) vs {self._axis_name(axis)} Angular Rate Setpoint")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_rates_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_angular_velocity")
        idx_map = {"roll": 0, "pitch": 1, "yaw": 2}
        idx = idx_map.get(axis, 0)
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, [axis, f"xyz[{idx}]"])
        act_signal = self._find_signal_in_topic(dataset, act_topic, [f"xyz[{idx}]", axis])
        self._render_pair(
            target_plot,
            file_name,
            sp_topic,
            sp_signal,
            act_topic,
            act_signal,
            f"{self._axis_name(axis)} Angular Rate (Actual) vs {self._axis_name(axis)} Angular Rate Setpoint",
        )

    def generate_speed_plot(self):
        _, target_plot = self._prepare_tools_plot("Airspeed vs GPS Ground Speed")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        ground_topic = self._find_topic_by_prefixes(dataset, ["vehicle_gps_position", "vehicle_local_position"])
        ground_signal = self._find_signal_in_topic(dataset, ground_topic, ["vel_m_s", "ground_speed_mag", "vx"])

        air_topic = self._find_topic_by_prefixes(dataset, ["tecs_status", "airspeed_validated", "airspeed"])
        air_signal = self._find_signal_in_topic(
            dataset,
            air_topic,
            ["true_airspeed_filtered", "true_airspeed_m_s", "indicated_airspeed_m_s"],
        )

        self._render_pair(
            target_plot,
            file_name,
            air_topic,
            air_signal,
            ground_topic,
            ground_signal,
            "Airspeed vs GPS Ground Speed",
        )

    def generate_fw_tecs_plot(self):
        _, target_plot = self._prepare_tools_plot("TECS Throttle Trim vs Throttle Setpoint")
        if target_plot is None:
            return
        file_name, dataset, aircraft_type = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return
        if aircraft_type != "Fixed-Wing":
            QMessageBox.information(self, "Tools", "이 항목은 Fixed-Wing 로그에서 사용하는 것을 권장합니다.")

        tecs_topic = self._find_topic_by_prefixes(dataset, "tecs_status")
        sp_signal = self._find_signal_in_topic(dataset, tecs_topic, ["throttle_sp"])
        act_signal = self._find_signal_in_topic(dataset, tecs_topic, ["throttle_trim"])
        self._render_pair(
            target_plot,
            file_name,
            tecs_topic,
            sp_signal,
            tecs_topic,
            act_signal,
            "TECS Throttle Trim vs Throttle Setpoint",
        )

    def generate_altitude_tracking_plot(self):
        _, target_plot = self._prepare_tools_plot("Altitude vs Altitude Setpoint")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position")
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, ["z"])
        act_signal = self._find_signal_in_topic(dataset, act_topic, ["z"])
        if sp_signal is None:
            sp_signal = self._find_signal_in_topic(dataset, sp_topic, ["alt_sp_up", "z_deriv"])
        if act_signal is None:
            act_signal = self._find_signal_in_topic(dataset, act_topic, ["alt_up"])
        self._render_pair(
            target_plot,
            file_name,
            sp_topic,
            sp_signal,
            act_topic,
            act_signal,
            "Altitude vs Altitude Setpoint",
        )

    def _build_attitude_error_topic(self, dataset, axis):
        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude")
        sp_candidates = {
            "pitch": ["pitch_sp_euler", "pitch"],
            "roll": ["roll_sp_euler", "roll"],
            "yaw": ["yaw_sp_euler", "yaw"],
        }
        act_candidates = {
            "pitch": ["pitch_euler", "pitch"],
            "roll": ["roll_euler", "roll"],
            "yaw": ["yaw_euler", "yaw"],
        }
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, sp_candidates.get(axis, []))
        act_signal = self._find_signal_in_topic(dataset, act_topic, act_candidates.get(axis, []))
        if not sp_topic or not act_topic or not sp_signal or not act_signal:
            return None, None

        act_df = (
            dataset.topics[act_topic].dataframe
            .select([
                pl.col("timestamp_sec").cast(pl.Float64),
                pl.col(act_signal).cast(pl.Float64).alias("actual"),
            ])
            .drop_nulls()
            .sort("timestamp_sec")
        )
        sp_df = (
            dataset.topics[sp_topic].dataframe
            .select([
                pl.col("timestamp_sec").cast(pl.Float64),
                pl.col(sp_signal).cast(pl.Float64).alias("setpoint"),
            ])
            .drop_nulls()
            .sort("timestamp_sec")
        )
        if len(act_df) == 0 or len(sp_df) == 0:
            return None, None

        merged = act_df.join_asof(sp_df, on="timestamp_sec", strategy="nearest")
        merged = merged.drop_nulls(subset=["actual", "setpoint"])
        if len(merged) == 0:
            return None, None
        merged = merged.with_columns((pl.col("actual") - pl.col("setpoint")).alias("error"))
        error_df = merged.select(["timestamp_sec", "error"])

        base_name = f"analysis_attitude_error_{axis}"
        topic_inst = TopicInstance(base_name=base_name, instance_id=0, dataframe=error_df)
        topic_inst.signals["error"] = LogSignal(name="error", data=error_df["error"])
        dataset.add_topic(topic_inst)
        return topic_inst.unique_name, "error"

    def generate_attitude_error_plot(self, axis):
        _, target_plot = self._prepare_tools_plot(f"{self._axis_name(axis)} Attitude Error (Actual - Setpoint)")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        error_topic, error_signal = self._build_attitude_error_topic(dataset, axis)
        if not error_topic:
            QMessageBox.warning(self, "Tools", f"{self._axis_name(axis)} error 계산용 신호를 찾지 못했습니다.")
            return

        target_plot.clear_plot_data()
        target_plot.plot.setTitle(f"{self._axis_name(axis)} Attitude Error (Actual - Setpoint)")
        target_plot.render_signal(file_name, error_topic, error_signal, color="#FFB300")
        target_plot.auto_fit_view()

    def generate_vibration_fft_plot(self):
        _, target_plot = self._prepare_tools_plot("Vibration Analysis: Accel FFT")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        accel_topic = self._find_topic_by_prefixes(dataset, "sensor_combined")
        if not accel_topic:
            QMessageBox.warning(self, "Tools", "sensor_combined 토픽을 찾지 못했습니다.")
            return

        cols = dataset.topics[accel_topic].dataframe.columns
        candidates = [("accelerometer_m_s2[0]", "#FF6B6B"), ("accelerometer_m_s2[1]", "#33CC66"), ("accelerometer_m_s2[2]", "#4DA3FF")]

        target_plot.clear_plot_data()
        target_plot.plot.setTitle("Vibration Analysis: Accel FFT")
        rendered = False
        for col, color in candidates:
            if col in cols:
                rendered = target_plot.render_signal(file_name, accel_topic, col, color=color, is_fft=True) or rendered
        if not rendered:
            QMessageBox.warning(self, "Tools", "가속도 FFT에 사용할 신호를 찾지 못했습니다.")
            return
        target_plot.auto_fit_view()

    @staticmethod
    def _fft_axis_color(axis_idx):
        if axis_idx == 0:
            return "#FF6B6B"
        if axis_idx == 1:
            return "#33CC66"
        if axis_idx == 2:
            return "#4DA3FF"
        return "#4DA3FF"

    @staticmethod
    def _find_signal_with_tokens(columns, axis_idx, token_groups):
        axis_tag = f"[{axis_idx}]"
        for col in columns:
            lower_col = col.lower()
            if axis_tag not in lower_col:
                continue
            for tokens in token_groups:
                if all(t in lower_col for t in tokens):
                    return col
        return None

    def _resolve_fft_source(self, dataset, sensor_kind, axis_idx):
        if sensor_kind == "accel":
            topic_prefixes = ["sensor_combined", "vehicle_acceleration", "vehicle_imu"]
            candidate_signals = [
                f"accelerometer_m_s2[{axis_idx}]",
                f"accel_m_s2[{axis_idx}]",
                f"accelerometer[{axis_idx}]",
                f"accel[{axis_idx}]",
                f"xyz[{axis_idx}]",
            ]
            token_groups = [
                ("accelerometer",),
                ("accel",),
                ("m_s2",),
            ]
        else:
            topic_prefixes = ["sensor_combined", "vehicle_angular_velocity", "vehicle_imu"]
            candidate_signals = [
                f"gyro_rad[{axis_idx}]",
                f"gyroscope_rad[{axis_idx}]",
                f"gyro[{axis_idx}]",
                f"angular_velocity_rad_s[{axis_idx}]",
                f"angular_rate_rad_s[{axis_idx}]",
                f"xyz[{axis_idx}]",
            ]
            token_groups = [
                ("gyro",),
                ("gyroscope",),
                ("angular", "velocity"),
                ("angular", "rate"),
            ]

        for prefix in topic_prefixes:
            topic_name = self._find_topic_by_prefixes(dataset, prefix)
            if not topic_name:
                continue
            signal_name = self._find_signal_in_topic(dataset, topic_name, candidate_signals)
            if signal_name:
                return topic_name, signal_name

            cols = dataset.topics[topic_name].dataframe.columns
            fallback_signal = self._find_signal_with_tokens(cols, axis_idx, token_groups)
            if fallback_signal:
                return topic_name, fallback_signal

        return None, None

    def generate_vibration_fft_axis(self, sensor_kind, axis_idx):
        sensor_kind = (sensor_kind or "").strip().lower()
        if sensor_kind not in ("accel", "gyro"):
            QMessageBox.warning(self, "Tools", "지원하지 않는 FFT 타입입니다.")
            return
        if axis_idx not in (0, 1, 2):
            QMessageBox.warning(self, "Tools", "축 인덱스는 0, 1, 2만 지원합니다.")
            return

        label_prefix = "Accel" if sensor_kind == "accel" else "Gyro"
        target_title = f"Vibration Analysis: {label_prefix}[{axis_idx}] FFT"
        _, target_plot = self._prepare_tools_plot(target_title)
        if target_plot is None:
            return

        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return

        topic_name, signal_name = self._resolve_fft_source(dataset, sensor_kind, axis_idx)
        if not topic_name or not signal_name:
            QMessageBox.warning(
                self,
                "Tools",
                f"{label_prefix}[{axis_idx}] FFT에 사용할 신호를 찾지 못했습니다.",
            )
            return

        target_plot.clear_plot_data()
        target_plot.plot.setTitle(target_title)
        color = self._fft_axis_color(axis_idx)
        ok = target_plot.render_signal(file_name, topic_name, signal_name, color=color, is_fft=True)
        if not ok:
            QMessageBox.warning(self, "Tools", f"{label_prefix}[{axis_idx}] FFT 그래프 생성에 실패했습니다.")
            return
        target_plot.auto_fit_view()

    def generate_flight_path_2d_plot(self):
        _, target_plot = self._prepare_tools_plot("2D Flight Path")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return
        if not self._render_2d_flight_path_in_plot(target_plot, file_name, dataset):
            QMessageBox.warning(self, "Tools", "2D Flight Path 생성에 필요한 좌표 신호를 찾지 못했습니다.")

    def generate_flight_path_3d_plot(self):
        _, target_plot = self._prepare_tools_plot("3D Flight Path (Interactive)")
        if target_plot is None:
            return
        file_name, dataset, _ = self._get_dataset_for_tools(target_plot)
        if dataset is None:
            QMessageBox.information(self, "Tools", "먼저 로그를 로드해 주세요.")
            return
        ok = self._render_3d_flight_path_in_plot(target_plot, file_name, dataset)
        if not ok:
            QMessageBox.warning(self, "Tools", "3D Flight Path 생성에 필요한 좌표 신호를 찾지 못했습니다.")
            return
        mode_text = "True 3D (OpenGL)" if getattr(target_plot, "_true_3d_enabled", False) else "Projected 3D (fallback)"
        self.statusBar().showMessage(f"3D Flight Path 생성 완료: {mode_text}", 4500)

    @staticmethod
    def _normalize_aircraft_label(label):
        normalized = (label or "").strip().lower().replace("_", "-")
        if "fixed" in normalized:
            return "fixed-wing"
        if "multi" in normalized:
            return "multicopter"
        if "vtol" in normalized:
            return "vtol"
        return normalized

    @staticmethod
    def _workspace_has_data(workspace):
        for plot in workspace.findChildren(AdvancedPlot):
            if plot.plotted_signals:
                return True
            if getattr(plot, "layout_special_spec", None):
                return True
        return False

    def _select_workspace_for_standard_panel(self, panel_title):
        current_ws = self.tab_widget.currentWidget()
        if not isinstance(current_ws, Workspace):
            self.add_workspace()
            return self.tab_widget.currentWidget()

        if not self._workspace_has_data(current_ws):
            return current_ws

        msg = QMessageBox(self)
        msg.setWindowTitle("표준 분석 패널")
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"현재 분석창에 기존 그래프가 있습니다.\n'{panel_title}' 패널을 어디에 생성할까요?")
        btn_overwrite = msg.addButton("현재 탭 덮어쓰기", QMessageBox.AcceptRole)
        btn_new_tab = msg.addButton("새 탭에 생성", QMessageBox.ActionRole)
        btn_cancel = msg.addButton("취소", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_new_tab)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return None
        if clicked == btn_new_tab:
            self.add_workspace()
            return self.tab_widget.currentWidget()
        if clicked == btn_overwrite:
            return current_ws
        return None

    def _get_dataset_for_standard_panel(self, target_aircraft_type):
        target_key = self._normalize_aircraft_label(target_aircraft_type)
        if not self.loaded_datasets:
            return None, None, None

        if self.active_analysis_log and self.active_analysis_log in self.loaded_datasets:
            file_name = self.active_analysis_log
            aircraft_type = self.loaded_aircraft_types.get(file_name, "Unknown")
            return file_name, self.loaded_datasets[file_name], aircraft_type

        cur_idx = self.tab_widget.currentIndex()
        if cur_idx >= 0:
            tab_text = self.tab_widget.tabText(cur_idx)
            if tab_text.startswith("분석:"):
                current_file = tab_text.split("|")[0].replace("분석:", "").strip()
                if current_file in self.loaded_datasets:
                    aircraft_type = self.loaded_aircraft_types.get(current_file, "Unknown")
                    if self._normalize_aircraft_label(aircraft_type) == target_key:
                        return current_file, self.loaded_datasets[current_file], aircraft_type

        for file_name, dataset in self.loaded_datasets.items():
            aircraft_type = self.loaded_aircraft_types.get(file_name, "Unknown")
            if self._normalize_aircraft_label(aircraft_type) == target_key:
                return file_name, dataset, aircraft_type

        return None, None, None

    def _render_angle_pair_in_plot(self, plot, file_name, dataset, axis):
        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_attitude")
        sp_candidates = {
            "pitch": ["pitch_sp_euler", "pitch", "pitch_body"],
            "roll": ["roll_sp_euler", "roll", "roll_body"],
            "yaw": ["yaw_sp_euler", "yaw", "yaw_body"],
        }
        act_candidates = {
            "pitch": ["pitch_euler", "pitch"],
            "roll": ["roll_euler", "roll"],
            "yaw": ["yaw_euler", "yaw"],
        }
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, sp_candidates.get(axis, []))
        act_signal = self._find_signal_in_topic(dataset, act_topic, act_candidates.get(axis, []))
        title = f"{self._axis_name(axis)} Angle (Actual) vs {self._axis_name(axis)} Angle Setpoint"
        return self._render_pair(plot, file_name, sp_topic, sp_signal, act_topic, act_signal, title, show_message=False)

    def _render_rate_pair_in_plot(self, plot, file_name, dataset, axis):
        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_rates_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_angular_velocity")
        idx_map = {"roll": 0, "pitch": 1, "yaw": 2}
        idx = idx_map.get(axis, 0)
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, [axis, f"xyz[{idx}]"])
        act_signal = self._find_signal_in_topic(dataset, act_topic, [f"xyz[{idx}]", axis])
        title = f"{self._axis_name(axis)} Angular Rate (Actual) vs {self._axis_name(axis)} Angular Rate Setpoint"
        return self._render_pair(plot, file_name, sp_topic, sp_signal, act_topic, act_signal, title, show_message=False)

    def _render_altitude_tracking_in_plot(self, plot, file_name, dataset):
        sp_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position_setpoint")
        act_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position")
        sp_signal = self._find_signal_in_topic(dataset, sp_topic, ["z"])
        act_signal = self._find_signal_in_topic(dataset, act_topic, ["z"])
        if sp_signal is None:
            sp_signal = self._find_signal_in_topic(dataset, sp_topic, ["alt_sp_up", "z_deriv"])
        if act_signal is None:
            act_signal = self._find_signal_in_topic(dataset, act_topic, ["alt_up"])
        title = "Altitude vs Altitude Setpoint"
        return self._render_pair(plot, file_name, sp_topic, sp_signal, act_topic, act_signal, title, show_message=False)

    def _render_speed_pair_in_plot(self, plot, file_name, dataset):
        ground_topic = self._find_topic_by_prefixes(dataset, ["vehicle_gps_position", "vehicle_local_position"])
        ground_signal = self._find_signal_in_topic(dataset, ground_topic, ["vel_m_s", "ground_speed_mag", "vx"])
        air_topic = self._find_topic_by_prefixes(dataset, ["tecs_status", "airspeed_validated", "airspeed"])
        air_signal = self._find_signal_in_topic(
            dataset,
            air_topic,
            ["true_airspeed_filtered", "true_airspeed_m_s", "indicated_airspeed_m_s"],
        )
        return self._render_pair(
            plot,
            file_name,
            air_topic,
            air_signal,
            ground_topic,
            ground_signal,
            "Airspeed vs GPS Ground Speed",
            show_message=False,
        )

    def _render_tecs_in_plot(self, plot, file_name, dataset):
        tecs_topic = self._find_topic_by_prefixes(dataset, "tecs_status")
        sp_signal = self._find_signal_in_topic(dataset, tecs_topic, ["throttle_sp"])
        act_signal = self._find_signal_in_topic(dataset, tecs_topic, ["throttle_trim"])
        return self._render_pair(
            plot,
            file_name,
            tecs_topic,
            sp_signal,
            tecs_topic,
            act_signal,
            "TECS Throttle Trim vs Throttle Setpoint",
            show_message=False,
        )

    def _render_fft_in_plot(self, plot, file_name, dataset):
        accel_topic = self._find_topic_by_prefixes(dataset, "sensor_combined")
        if not accel_topic:
            return False

        cols = dataset.topics[accel_topic].dataframe.columns
        candidates = [
            ("accelerometer_m_s2[0]", "#FF6B6B"),
            ("accelerometer_m_s2[1]", "#33CC66"),
            ("accelerometer_m_s2[2]", "#4DA3FF"),
        ]

        plot.clear_plot_data()
        plot.plot.setTitle("Vibration Analysis: Accel FFT")
        rendered = False
        for col, color in candidates:
            if col in cols:
                rendered = plot.render_signal(file_name, accel_topic, col, color=color, is_fft=True) or rendered
        if rendered:
            plot.auto_fit_view()
        return rendered

    def _render_2d_flight_path_in_plot(self, plot, file_name, dataset):
        local_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position")
        global_topic = self._find_topic_by_prefixes(dataset, "vehicle_global_position")
        topic = local_topic or global_topic
        if not topic:
            return False

        display_lat = None
        display_lon = None
        display_alt = None

        if "global" in topic:
            lon_signal = self._find_signal_in_topic(dataset, topic, ["lon", "longitude_deg"])
            lat_signal = self._find_signal_in_topic(dataset, topic, ["lat", "latitude_deg"])
            alt_signal = self._find_signal_in_topic(dataset, topic, ["alt", "altitude_msl_m", "altitude"])
            if not lon_signal or not lat_signal:
                return False
            df = dataset.topics[topic].dataframe
            if "timestamp_sec" not in df.columns:
                return False
            t = np.asarray(df["timestamp_sec"].to_numpy(), dtype=np.float64)
            lat = np.asarray(df[lat_signal].to_numpy(), dtype=np.float64)
            lon = np.asarray(df[lon_signal].to_numpy(), dtype=np.float64)
            mask = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
            z = None
            if alt_signal:
                alt = np.asarray(df[alt_signal].to_numpy(), dtype=np.float64)
                mask = mask & np.isfinite(alt)
                z = alt
            t = t[mask]
            lat = lat[mask]
            lon = lon[mask]
            display_lat = lat.copy()
            display_lon = lon.copy()
            if z is not None:
                z = z[mask]
                display_alt = z.copy()
                z = z - float(np.median(z))
            if len(t) < 2:
                return False
            lat0 = float(np.median(lat))
            lon0 = float(np.median(lon))
            earth_r = 6378137.0
            deg_to_rad = np.pi / 180.0
            north = (lat - lat0) * deg_to_rad * earth_r
            east = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
        else:
            x_signal = self._find_signal_in_topic(dataset, topic, ["x", "east", "position[0]"])
            y_signal = self._find_signal_in_topic(dataset, topic, ["y", "north", "position[1]"])
            z_signal = self._find_signal_in_topic(dataset, topic, ["z"])
            if z_signal is None:
                z_signal = self._find_signal_in_topic(dataset, topic, ["alt", "alt_up", "position[2]"])
            alt_signal = z_signal
            if not x_signal or not y_signal:
                return False
            df = dataset.topics[topic].dataframe
            if "timestamp_sec" not in df.columns:
                return False
            t = np.asarray(df["timestamp_sec"].to_numpy(), dtype=np.float64)
            x = np.asarray(df[x_signal].to_numpy(), dtype=np.float64)
            y = np.asarray(df[y_signal].to_numpy(), dtype=np.float64)
            mask = np.isfinite(t) & np.isfinite(x) & np.isfinite(y)
            z = None
            if z_signal:
                z_raw = np.asarray(df[z_signal].to_numpy(), dtype=np.float64)
                mask = mask & np.isfinite(z_raw)
                z = -z_raw
                display_alt = z_raw.copy()
            t = t[mask]
            north = x[mask]
            east = y[mask]
            if z is not None:
                z = z[mask]
            if display_alt is not None:
                display_alt = display_alt[mask]

            # Prefer displaying real GPS lat/lon/alt values in the 2D path info box.
            g_topic = self._find_topic_by_prefixes(dataset, "vehicle_global_position")
            if g_topic and g_topic in dataset.topics:
                g_lat_signal = self._find_signal_in_topic(dataset, g_topic, ["lat", "latitude_deg"])
                g_lon_signal = self._find_signal_in_topic(dataset, g_topic, ["lon", "longitude_deg"])
                g_df = dataset.topics[g_topic].dataframe
                if (
                    g_df is not None
                    and "timestamp_sec" in g_df.columns
                    and g_lat_signal in g_df.columns
                    and g_lon_signal in g_df.columns
                ):
                    tg = np.asarray(g_df["timestamp_sec"].to_numpy(), dtype=np.float64)
                    latg = np.asarray(g_df[g_lat_signal].to_numpy(), dtype=np.float64)
                    long = np.asarray(g_df[g_lon_signal].to_numpy(), dtype=np.float64)
                    g_mask = np.isfinite(tg) & np.isfinite(latg) & np.isfinite(long)
                    tg = tg[g_mask]
                    latg = latg[g_mask]
                    long = long[g_mask]
                    if len(tg) >= 2:
                        order = np.argsort(tg)
                        tg = tg[order]
                        latg = latg[order]
                        long = long[order]
                        unique = np.concatenate(([True], np.diff(tg) > 1e-9))
                        tg = tg[unique]
                        latg = latg[unique]
                        long = long[unique]
                        if len(tg) >= 2:
                            display_lat = np.interp(t, tg, latg, left=np.nan, right=np.nan)
                            display_lon = np.interp(t, tg, long, left=np.nan, right=np.nan)

        if len(t) > 8000:
            step = max(1, len(t) // 8000)
            t = t[::step]
            north = north[::step]
            east = east[::step]
            if z is not None:
                z = z[::step]
            if display_lat is not None:
                display_lat = display_lat[::step]
            if display_lon is not None:
                display_lon = display_lon[::step]
            if display_alt is not None:
                display_alt = display_alt[::step]

        ok = plot.render_2d_flight_path(
            north,
            east,
            title="2D Flight Path",
            timestamps=t,
            altitude=z,
            display_lat=display_lat,
            display_lon=display_lon,
            display_alt=display_alt,
        )
        if ok:
            plot.layout_special_spec = {
                "kind": "flight_path_2d",
                "file_name": file_name,
                "topic": topic,
                "x_signal": lon_signal if "global" in topic else x_signal,
                "y_signal": lat_signal if "global" in topic else y_signal,
                "z_signal": alt_signal if "global" in topic else z_signal,
                "time_signal": "timestamp_sec",
            }
        return ok

    def _render_3d_flight_path_in_plot(self, plot, file_name, dataset):
        local_topic = self._find_topic_by_prefixes(dataset, "vehicle_local_position")
        global_topic = self._find_topic_by_prefixes(dataset, "vehicle_global_position")

        topic = None
        x_signal = None
        y_signal = None
        using_local_xy = False

        if local_topic and local_topic in dataset.topics:
            lx = self._find_signal_in_topic(dataset, local_topic, ["x", "east", "position[0]"])
            ly = self._find_signal_in_topic(dataset, local_topic, ["y", "north", "position[1]"])
            if lx and ly:
                topic = local_topic
                x_signal = lx
                y_signal = ly
                using_local_xy = True

        if topic is None and global_topic and global_topic in dataset.topics:
            gx = self._find_signal_in_topic(dataset, global_topic, ["lon", "longitude_deg"])
            gy = self._find_signal_in_topic(dataset, global_topic, ["lat", "latitude_deg"])
            if gx and gy:
                topic = global_topic
                x_signal = gx
                y_signal = gy
                using_local_xy = False

        if topic is None or not x_signal or not y_signal:
            return False

        # Use vehicle_local_position.z as primary altitude source for both 2D/3D paths.
        z_topic = local_topic if local_topic and local_topic in dataset.topics else topic
        z_signal = self._find_signal_in_topic(dataset, z_topic, ["z"]) if z_topic else None
        if z_signal is None:
            z_topic = topic
            z_signal = self._find_signal_in_topic(
                dataset,
                z_topic,
                ["z", "alt", "altitude_msl_m", "altitude", "alt_up", "position[2]"],
            )
        if z_signal is None:
            return False

        try:
            df_xy = dataset.topics[topic].dataframe
            t = None
            if "timestamp_sec" in df_xy.columns:
                try:
                    t = np.asarray(df_xy["timestamp_sec"].to_numpy(), dtype=np.float64)
                except Exception:
                    t = None

            x_raw = np.asarray(df_xy[x_signal].to_numpy(), dtype=np.float64)
            y_raw = np.asarray(df_xy[y_signal].to_numpy(), dtype=np.float64)
            base_mask = np.isfinite(x_raw) & np.isfinite(y_raw)
            if t is not None and len(t) == len(base_mask):
                base_mask = base_mask & np.isfinite(t)

            x_raw = x_raw[base_mask]
            y_raw = y_raw[base_mask]
            if t is not None and len(t) == len(base_mask):
                t = t[base_mask]
            else:
                t = None

            if len(x_raw) == 0:
                return False

            if z_topic == topic:
                z_raw = np.asarray(df_xy[z_signal].to_numpy(), dtype=np.float64)
                z_raw = z_raw[base_mask]
                finite_z = np.isfinite(z_raw)
                x_raw = x_raw[finite_z]
                y_raw = y_raw[finite_z]
                z_raw = z_raw[finite_z]
                if t is not None and len(t) == len(finite_z):
                    t = t[finite_z]
            else:
                if t is None:
                    return False
                df_z = dataset.topics[z_topic].dataframe
                if df_z is None or "timestamp_sec" not in df_z.columns or z_signal not in df_z.columns:
                    return False
                tz = np.asarray(df_z["timestamp_sec"].to_numpy(), dtype=np.float64)
                zv = np.asarray(df_z[z_signal].to_numpy(), dtype=np.float64)
                z_mask = np.isfinite(tz) & np.isfinite(zv)
                tz = tz[z_mask]
                zv = zv[z_mask]
                if len(tz) < 2:
                    return False
                order = np.argsort(tz)
                tz = tz[order]
                zv = zv[order]
                unique = np.concatenate(([True], np.diff(tz) > 1e-9))
                tz = tz[unique]
                zv = zv[unique]
                if len(tz) < 2:
                    return False
                z_raw = np.interp(t, tz, zv, left=np.nan, right=np.nan)
                finite_z = np.isfinite(z_raw)
                x_raw = x_raw[finite_z]
                y_raw = y_raw[finite_z]
                z_raw = z_raw[finite_z]
                t = t[finite_z]

            if len(x_raw) < 2:
                return False

            if using_local_xy:
                # Local position is NED; convert Z to Up while preserving local_position.z source.
                x = x_raw - float(x_raw[0])
                y = y_raw - float(y_raw[0])
                z = -(z_raw - float(z_raw[0]))
                frame_name = "local_NEU_m(local_z)"
            else:
                # Convert global lon/lat to local North/East meters.
                lat = y_raw
                lon = x_raw
                lat0 = float(lat[0])
                lon0 = float(lon[0])
                earth_r = 6378137.0
                deg_to_rad = np.pi / 180.0
                north_m = (lat - lat0) * deg_to_rad * earth_r
                east_m = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
                x = north_m
                y = east_m
                # Prefer local_position.z-derived altitude when available.
                if z_topic == local_topic and z_signal == "z":
                    z = -(z_raw - float(z_raw[0]))
                    frame_name = "globalXY+localZ_NEU_m"
                else:
                    z = z_raw - float(z_raw[0])
                    frame_name = "global_NEU_m"

            try:
                x_span = float(np.max(x) - np.min(x))
                y_span = float(np.max(y) - np.min(y))
                z_span = float(np.max(z) - np.min(z))
                print(
                    f"[3D][Source] topic={topic} z_topic={z_topic} frame={frame_name} "
                    f"span(x,y,z)=({x_span:.3f}, {y_span:.3f}, {z_span:.3f})"
                )
            except Exception:
                pass

            if len(x) > 8000:
                step = max(1, len(x) // 8000)
                x = x[::step]
                y = y[::step]
                z = z[::step]
                if t is not None:
                    t = t[::step]

            ok = plot.render_3d_path(x, y, z, "3D Flight Path (Interactive)", timestamps=t)
            if ok:
                special_kind = "true_3d_path" if getattr(plot, "_true_3d_enabled", False) else "projected_3d_path"
                plot.layout_special_spec = {
                    "kind": special_kind,
                    "file_name": file_name,
                    "topic": topic,
                    "x_signal": x_signal,
                    "y_signal": y_signal,
                    "z_topic": z_topic,
                    "z_signal": z_signal,
                    "time_signal": "timestamp_sec",
                    "line_color": plot._3d_path_style["color"].name(),
                    "line_style": plot._3d_path_style.get("style", "solid"),
                    "line_width": float(plot._3d_path_style.get("width", 2.6)),
                }
            return ok
        except Exception:
            traceback.print_exc()
            return False

    def _render_gps_speed_in_plot(self, plot, file_name, dataset):
        topic = self._find_topic_by_prefixes(dataset, ["vehicle_gps_position", "vehicle_local_position"])
        signal = self._find_signal_in_topic(dataset, topic, ["vel_m_s", "ground_speed_mag", "speed", "vx"])
        if not topic or not signal:
            return False

        plot.clear_plot_data()
        plot.plot.setTitle("GPS Speed")
        ok = plot.render_signal(file_name, topic, signal, color="#4DA3FF")
        if ok:
            plot.auto_fit_view()
        return ok

    def _render_transition_mode_in_plot(self, plot, file_name, dataset):
        topic = self._find_topic_by_prefixes(dataset, ["vtol_vehicle_status", "vehicle_status"])
        if not topic:
            return False

        cols = dataset.topics[topic].dataframe.columns
        candidates = [
            "in_transition_mode",
            "in_transition_mode_flag",
            "in_transition_to_fw",
            "in_transition_to_fw_flag",
            "in_transition_back",
            "in_transition_back_flag",
        ]

        plot.clear_plot_data()
        plot.plot.setTitle("Transition Mode")
        rendered = False
        for sig in candidates:
            if sig in cols:
                rendered = plot.render_signal(file_name, topic, sig, color=ColorManager.get_color(topic, sig)) or rendered
        if rendered:
            plot.auto_fit_view()
        return rendered

    def _build_multicopter_panel_1(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2, 2])
        return [
            ("Roll Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(0, 0), file_name, dataset, "roll")),
            ("Roll Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(0, 1), file_name, dataset, "roll")),
            ("Pitch Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(1, 0), file_name, dataset, "pitch")),
            ("Pitch Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(1, 1), file_name, dataset, "pitch")),
            ("Yaw Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(2, 0), file_name, dataset, "yaw")),
            ("Accel FFT", self._render_fft_in_plot(workspace.get_plot(2, 1), file_name, dataset)),
        ]

    def _build_multicopter_panel_2(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2])
        return [
            ("2D Flight Path", self._render_2d_flight_path_in_plot(workspace.get_plot(0, 0), file_name, dataset)),
            ("3D Flight Path", self._render_3d_flight_path_in_plot(workspace.get_plot(0, 1), file_name, dataset)),
            ("Altitude Tracking", self._render_altitude_tracking_in_plot(workspace.get_plot(1, 0), file_name, dataset)),
            ("GPS Speed", self._render_gps_speed_in_plot(workspace.get_plot(1, 1), file_name, dataset)),
        ]

    def _build_fixed_wing_panel_1(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2, 2])
        return [
            ("Roll Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(0, 0), file_name, dataset, "roll")),
            ("Roll Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(0, 1), file_name, dataset, "roll")),
            ("Pitch Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(1, 0), file_name, dataset, "pitch")),
            ("Pitch Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(1, 1), file_name, dataset, "pitch")),
            ("Yaw Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(2, 0), file_name, dataset, "yaw")),
            ("Yaw Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(2, 1), file_name, dataset, "yaw")),
        ]

    def _build_fixed_wing_panel_2(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2, 2])
        return [
            ("2D Flight Path", self._render_2d_flight_path_in_plot(workspace.get_plot(0, 0), file_name, dataset)),
            ("3D Flight Path", self._render_3d_flight_path_in_plot(workspace.get_plot(0, 1), file_name, dataset)),
            ("Airspeed vs GPS Speed", self._render_speed_pair_in_plot(workspace.get_plot(1, 0), file_name, dataset)),
            ("Altitude Tracking", self._render_altitude_tracking_in_plot(workspace.get_plot(1, 1), file_name, dataset)),
            ("TECS Throttle", self._render_tecs_in_plot(workspace.get_plot(2, 0), file_name, dataset)),
            ("Accel FFT", self._render_fft_in_plot(workspace.get_plot(2, 1), file_name, dataset)),
        ]

    def _build_vtol_panel_1(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2, 2])
        return [
            ("Roll Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(0, 0), file_name, dataset, "roll")),
            ("Roll Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(0, 1), file_name, dataset, "roll")),
            ("Pitch Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(1, 0), file_name, dataset, "pitch")),
            ("Pitch Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(1, 1), file_name, dataset, "pitch")),
            ("Yaw Angle vs SP", self._render_angle_pair_in_plot(workspace.get_plot(2, 0), file_name, dataset, "yaw")),
            ("Yaw Rate vs SP", self._render_rate_pair_in_plot(workspace.get_plot(2, 1), file_name, dataset, "yaw")),
        ]

    def _build_vtol_panel_2(self, workspace, file_name, dataset):
        workspace.create_grid([2, 2, 2, 1])
        return [
            ("2D Flight Path", self._render_2d_flight_path_in_plot(workspace.get_plot(0, 0), file_name, dataset)),
            ("3D Flight Path", self._render_3d_flight_path_in_plot(workspace.get_plot(0, 1), file_name, dataset)),
            ("Airspeed vs GPS Speed", self._render_speed_pair_in_plot(workspace.get_plot(1, 0), file_name, dataset)),
            ("Altitude Tracking", self._render_altitude_tracking_in_plot(workspace.get_plot(1, 1), file_name, dataset)),
            ("TECS Throttle", self._render_tecs_in_plot(workspace.get_plot(2, 0), file_name, dataset)),
            ("Accel FFT", self._render_fft_in_plot(workspace.get_plot(2, 1), file_name, dataset)),
            ("Transition Mode", self._render_transition_mode_in_plot(workspace.get_plot(3, 0), file_name, dataset)),
        ]

    def generate_standard_panel(self, aircraft_type, panel_index):
        if not self.loaded_datasets:
            QMessageBox.information(self, "Function", "먼저 로그를 로드해 주세요.")
            return

        file_name, dataset, detected_type = self._get_dataset_for_standard_panel(aircraft_type)
        if dataset is None:
            QMessageBox.warning(
                self,
                "Function",
                f"{aircraft_type} 유형 로그를 찾지 못했습니다. 해당 기체 로그를 먼저 로드해 주세요.",
            )
            return

        panel_title = f"{aircraft_type} 표준 분석 패널 {panel_index}"
        target_ws = self._select_workspace_for_standard_panel(panel_title)
        if not isinstance(target_ws, Workspace):
            return

        builders = {
            ("Multicopter", 1): self._build_multicopter_panel_1,
            ("Multicopter", 2): self._build_multicopter_panel_2,
            ("Fixed-Wing", 1): self._build_fixed_wing_panel_1,
            ("Fixed-Wing", 2): self._build_fixed_wing_panel_2,
            ("VTOL", 1): self._build_vtol_panel_1,
            ("VTOL", 2): self._build_vtol_panel_2,
        }
        builder = builders.get((aircraft_type, panel_index))
        if builder is None:
            QMessageBox.warning(self, "Function", "정의되지 않은 표준 분석 패널입니다.")
            return

        results = builder(target_ws, file_name, dataset)
        display_aircraft = detected_type if detected_type else aircraft_type
        target_ws.set_aircraft_type(display_aircraft)
        tab_idx = self.tab_widget.indexOf(target_ws)
        if tab_idx >= 0:
            self.tab_widget.setCurrentIndex(tab_idx)
            self.tab_widget.setTabText(tab_idx, f"분석: {file_name} | {display_aircraft}")

        self.last_active_plot = target_ws.first_plot
        failed = [name for name, ok in results if not ok]
        if failed:
            preview = ", ".join(failed[:3])
            if len(failed) > 3:
                preview += f" 외 {len(failed) - 3}개"
            self.statusBar().showMessage(f"{panel_title} 생성 완료 (일부 미생성: {preview})", 7000)
        else:
            self.statusBar().showMessage(f"{panel_title} 생성 완료", 5000)

    def _current_workspace(self):
        current_ws = self.tab_widget.currentWidget()
        if isinstance(current_ws, Workspace):
            return current_ws
        return None

    def rename_workspace_tab(self, index):
        if index < 0:
            return

        current_name = self.tab_widget.tabText(index)
        new_name, ok = QInputDialog.getText(self, "분석창 이름 변경", "새 탭 이름:", text=current_name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        self.tab_widget.setTabText(index, new_name)

    @staticmethod
    def _sanitize_layout_filename(name):
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
        return safe if safe else "layout"

    @staticmethod
    def _default_layout_dir():
        project_root = os.path.abspath(os.path.join(src_dir, "../"))
        layout_dir = os.path.join(project_root, "layouts")
        os.makedirs(layout_dir, exist_ok=True)
        return layout_dir

    def _select_workspace_for_layout_apply(self, layout_name):
        current_ws = self._current_workspace()
        if current_ws is None:
            self.add_workspace()
            return self._current_workspace()

        if not self._workspace_has_data(current_ws):
            return current_ws

        msg = QMessageBox(self)
        msg.setWindowTitle("Layout Import")
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"현재 분석창에 데이터가 있습니다.\n'{layout_name}' 레이아웃을 어디에 적용할까요?")
        btn_current = msg.addButton("현재 탭 적용", QMessageBox.AcceptRole)
        btn_new_tab = msg.addButton("새 탭 적용", QMessageBox.ActionRole)
        btn_cancel = msg.addButton("취소", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_new_tab)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return None
        if clicked == btn_new_tab:
            self.add_workspace()
            return self._current_workspace()
        if clicked == btn_current:
            return current_ws
        return None

    @staticmethod
    def _pen_style_to_key(pen):
        if pen is None:
            return "solid"
        style = pen.style()
        if style == Qt.SolidLine:
            return "solid"
        if style == Qt.DashLine:
            return "dash"
        if style == Qt.DotLine:
            return "dot"
        if style == Qt.DashDotLine:
            return "dash_dot"
        if style == Qt.CustomDashLine:
            return "dense_dash"
        return "solid"

    @staticmethod
    def _style_key_to_pen(style_key):
        if style_key == "dash":
            return Qt.DashLine
        if style_key == "dot":
            return Qt.DotLine
        if style_key == "dash_dot":
            return Qt.DashDotLine
        if style_key == "dense_dash":
            return Qt.CustomDashLine
        return Qt.SolidLine

    @staticmethod
    def _extract_plot_title(plot):
        try:
            raw = plot.plot.plotItem.titleLabel.text or ""
            plain = re.sub("<[^>]+>", "", raw).strip()
            return plain
        except Exception:
            return ""

    def _serialize_plot_layout(self, plot):
        signals = []
        for uri, plot_item in plot.plotted_signals.items():
            parts = uri.split("|")
            if len(parts) < 5:
                continue
            file_name, topic_name, signal_name, x_axis_col, is_fft_text = parts[:5]
            is_fft = is_fft_text.lower() == "true"
            pen = plot_item.opts.get("pen")
            color = pen.color().name() if pen is not None else "#4DA3FF"
            width = float(pen.widthF()) if pen is not None else 1.5
            style_key = self._pen_style_to_key(pen)
            signals.append(
                {
                    "file_name": file_name,
                    "topic_name": topic_name,
                    "signal_name": signal_name,
                    "x_axis_col": x_axis_col,
                    "is_fft": is_fft,
                    "color": color,
                    "style": style_key,
                    "width": width,
                }
            )

        return {
            "type": "plot",
            "title": self._extract_plot_title(plot),
            "legend_visible": bool(plot.legend_visible),
            "signals": signals,
            "special": plot.layout_special_spec,
        }

    def _serialize_widget_layout(self, widget):
        if isinstance(widget, AdvancedPlot):
            return self._serialize_plot_layout(widget)
        if isinstance(widget, QSplitter):
            orientation = "horizontal" if widget.orientation() == Qt.Horizontal else "vertical"
            children = []
            for i in range(widget.count()):
                child = widget.widget(i)
                node = self._serialize_widget_layout(child)
                if node:
                    children.append(node)
            return {
                "type": "splitter",
                "orientation": orientation,
                "sizes": widget.sizes(),
                "children": children,
            }
        return None

    def _serialize_workspace_layout(self, workspace):
        idx = self.tab_widget.indexOf(workspace)
        tab_name = self.tab_widget.tabText(idx) if idx >= 0 else "분석 창"
        aircraft_type = workspace.lbl_aircraft_type.text().replace("Aircraft Type:", "").strip()
        root_node = self._serialize_widget_layout(workspace.grid_root)
        return {
            "version": 1,
            "tab_name": tab_name,
            "aircraft_type": aircraft_type,
            "theme": self.theme_combo.currentText(),
            "root": root_node,
        }

    def export_current_workspace_layout(self):
        workspace = self._current_workspace()
        if workspace is None:
            QMessageBox.information(self, "Layout Export", "저장할 분석창이 없습니다. 먼저 분석창을 생성해 주세요.")
            return

        data = self._serialize_workspace_layout(workspace)
        idx = self.tab_widget.indexOf(workspace)
        tab_name = self.tab_widget.tabText(idx) if idx >= 0 else "layout"
        default_name = f"{self._sanitize_layout_filename(tab_name)}.px4layout.json"
        default_path = os.path.join(self._default_layout_dir(), default_name)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Layout Export",
            default_path,
            "PX4 Layout (*.px4layout.json);;JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Layout Export", f"레이아웃 저장 실패:\n{e}")
            return

        workspace.current_layout_path = file_path
        self.statusBar().showMessage(f"레이아웃 저장 완료: {os.path.basename(file_path)}", 5000)

    def _apply_plot_style(self, plot, uri, plot_item, color, style_key, width):
        pen_color = QColor(color) if color else plot_item.opts["pen"].color()
        pen_style = self._style_key_to_pen(style_key)
        try:
            pen_width = float(width)
        except Exception:
            pen_width = plot_item.opts["pen"].widthF()
        if pen_width <= 0:
            pen_width = 1.0

        new_pen = pg.mkPen(color=pen_color, width=pen_width, style=pen_style)
        if pen_style == Qt.CustomDashLine:
            new_pen.setDashPattern([2, 2])
        plot_item.setPen(new_pen)

        if uri in plot.signal_cache:
            plot.signal_cache[uri]["color"] = pen_color.name()

    def _restore_plot_from_layout(self, plot, node, missing_items):
        plot.clear_plot_data()

        title = str(node.get("title", "")).strip()
        if title:
            plot.plot.setTitle(title)

        legend_visible = bool(node.get("legend_visible", True))
        plot.btn_toggle_legend.setChecked(legend_visible)
        plot.toggle_legend_visibility(legend_visible)

        special = node.get("special")
        if isinstance(special, dict) and special.get("kind") == "flight_path_2d":
            file_name = special.get("file_name")
            topic = special.get("topic")
            x_signal = special.get("x_signal")
            y_signal = special.get("y_signal")
            z_signal = special.get("z_signal")
            t_signal = special.get("time_signal", "timestamp_sec")
            dataset = self.loaded_datasets.get(file_name)
            if dataset and topic in dataset.topics:
                try:
                    df = dataset.topics[topic].dataframe
                    if t_signal not in df.columns:
                        missing_items.append("2D Flight Path")
                    else:
                        t = np.asarray(df[t_signal].to_numpy(), dtype=np.float64)
                        is_global_topic = ("global" in str(topic))
                        z = None
                        if is_global_topic:
                            lon = np.asarray(df[x_signal].to_numpy(), dtype=np.float64)
                            lat = np.asarray(df[y_signal].to_numpy(), dtype=np.float64)
                            mask = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon)
                            if z_signal and z_signal in df.columns:
                                z_raw = np.asarray(df[z_signal].to_numpy(), dtype=np.float64)
                                mask = mask & np.isfinite(z_raw)
                                z = z_raw
                            t = t[mask]
                            lat = lat[mask]
                            lon = lon[mask]
                            if z is not None:
                                z = z[mask] - float(np.median(z[mask]))
                            lat0 = float(np.median(lat))
                            lon0 = float(np.median(lon))
                            earth_r = 6378137.0
                            deg_to_rad = np.pi / 180.0
                            north = (lat - lat0) * deg_to_rad * earth_r
                            east = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
                        else:
                            x = np.asarray(df[x_signal].to_numpy(), dtype=np.float64)
                            y = np.asarray(df[y_signal].to_numpy(), dtype=np.float64)
                            mask = np.isfinite(t) & np.isfinite(x) & np.isfinite(y)
                            if z_signal and z_signal in df.columns:
                                z_raw = np.asarray(df[z_signal].to_numpy(), dtype=np.float64)
                                mask = mask & np.isfinite(z_raw)
                                z = -z_raw
                            t = t[mask]
                            north = x[mask]
                            east = y[mask]
                            if z is not None:
                                z = z[mask]

                        if len(t) > 8000:
                            step = max(1, len(t) // 8000)
                            t = t[::step]
                            north = north[::step]
                            east = east[::step]
                            if z is not None:
                                z = z[::step]

                        if len(t) > 0 and plot.render_2d_flight_path(north, east, title="2D Flight Path", timestamps=t, altitude=z):
                            plot.layout_special_spec = dict(special)
                        else:
                            missing_items.append("2D Flight Path")
                except Exception:
                    missing_items.append("2D Flight Path")
            else:
                missing_items.append("2D Flight Path")

        if isinstance(special, dict) and special.get("kind") in ("projected_3d_path", "true_3d_path"):
            file_name = special.get("file_name")
            topic = special.get("topic")
            z_topic = special.get("z_topic", topic)
            x_signal = special.get("x_signal")
            y_signal = special.get("y_signal")
            z_signal = special.get("z_signal")
            t_signal = special.get("time_signal", "timestamp_sec")
            line_color = special.get("line_color")
            line_style = special.get("line_style", "solid")
            line_width = special.get("line_width", 2.6)
            dataset = self.loaded_datasets.get(file_name)
            if dataset and topic in dataset.topics:
                try:
                    plot.set_3d_path_style(color=line_color, style_key=line_style, width=line_width)
                    df = dataset.topics[topic].dataframe
                    t = None
                    if t_signal in df.columns:
                        try:
                            t = np.asarray(df[t_signal].to_numpy(), dtype=np.float64)
                        except Exception:
                            t = None
                    x = np.asarray(df[x_signal].to_numpy(), dtype=np.float64)
                    y = np.asarray(df[y_signal].to_numpy(), dtype=np.float64)
                    mask = np.isfinite(x) & np.isfinite(y)
                    if t is not None and len(t) == len(mask):
                        mask = mask & np.isfinite(t)
                    x = x[mask]
                    y = y[mask]
                    if t is not None and len(t) == len(mask):
                        t = t[mask]
                    else:
                        t = None

                    z = None
                    if z_topic == topic:
                        z_raw = np.asarray(df[z_signal].to_numpy(), dtype=np.float64)
                        z_raw = z_raw[mask]
                        valid_z = np.isfinite(z_raw)
                        x = x[valid_z]
                        y = y[valid_z]
                        z = z_raw[valid_z]
                        if t is not None and len(t) == len(valid_z):
                            t = t[valid_z]
                    elif z_topic in dataset.topics and t is not None:
                        z_df = dataset.topics[z_topic].dataframe
                        if z_df is not None and "timestamp_sec" in z_df.columns and z_signal in z_df.columns:
                            tz = np.asarray(z_df["timestamp_sec"].to_numpy(), dtype=np.float64)
                            zv = np.asarray(z_df[z_signal].to_numpy(), dtype=np.float64)
                            z_mask = np.isfinite(tz) & np.isfinite(zv)
                            tz = tz[z_mask]
                            zv = zv[z_mask]
                            if len(tz) >= 2:
                                order = np.argsort(tz)
                                tz = tz[order]
                                zv = zv[order]
                                unique = np.concatenate(([True], np.diff(tz) > 1e-9))
                                tz = tz[unique]
                                zv = zv[unique]
                                if len(tz) >= 2:
                                    z_interp = np.interp(t, tz, zv, left=np.nan, right=np.nan)
                                    valid_z = np.isfinite(z_interp)
                                    x = x[valid_z]
                                    y = y[valid_z]
                                    z = z_interp[valid_z]
                                    t = t[valid_z]
                    if z is None:
                        missing_items.append("3D Flight Path")
                    else:
                        if len(x) > 0:
                            if "global" in topic:
                                lat = y
                                lon = x
                                lat0 = float(lat[0])
                                lon0 = float(lon[0])
                                earth_r = 6378137.0
                                deg_to_rad = np.pi / 180.0
                                north_m = (lat - lat0) * deg_to_rad * earth_r
                                east_m = (lon - lon0) * deg_to_rad * earth_r * np.cos(lat0 * deg_to_rad)
                                x = north_m
                                y = east_m
                                if z_topic != topic and z_signal == "z":
                                    z = -(z - float(z[0]))
                                else:
                                    z = z - float(z[0])
                            else:
                                x = x - float(x[0])
                                y = y - float(y[0])
                                z = -(z - float(z[0]))
                            if len(x) > 8000:
                                step = max(1, len(x) // 8000)
                                x = x[::step]
                                y = y[::step]
                                z = z[::step]
                                if t is not None:
                                    t = t[::step]

                        if len(x) > 0 and plot.render_3d_path(x, y, z, "3D Flight Path (Interactive)", timestamps=t):
                            plot.set_3d_path_style(color=line_color, style_key=line_style, width=line_width)
                            restored_special = dict(special)
                            if getattr(plot, "_true_3d_enabled", False):
                                restored_special["kind"] = "true_3d_path"
                            else:
                                restored_special["kind"] = "projected_3d_path"
                            restored_special["line_color"] = plot._3d_path_style["color"].name()
                            restored_special["line_style"] = plot._3d_path_style.get("style", "solid")
                            restored_special["line_width"] = float(plot._3d_path_style.get("width", 2.6))
                            plot.layout_special_spec = restored_special
                        else:
                            missing_items.append("3D Flight Path")
                except Exception:
                    missing_items.append("3D Flight Path")
            else:
                missing_items.append("3D Flight Path")

        for sig in node.get("signals", []):
            file_name = sig.get("file_name")
            topic_name = sig.get("topic_name")
            signal_name = sig.get("signal_name")
            x_axis_col = sig.get("x_axis_col", "timestamp_sec")
            is_fft = bool(sig.get("is_fft", False))
            color = sig.get("color")
            style_key = sig.get("style", "solid")
            width = sig.get("width", 1.5)
            ok = plot.render_signal(
                file_name,
                topic_name,
                signal_name,
                x_axis_col=x_axis_col,
                color=color,
                is_fft=is_fft,
            )
            if not ok:
                missing_items.append(f"{topic_name}.{signal_name}")
                continue

            uri = f"{file_name}|{topic_name}|{signal_name}|{x_axis_col}|{is_fft}"
            plot_item = plot.plotted_signals.get(uri)
            if plot_item is not None:
                self._apply_plot_style(plot, uri, plot_item, color, style_key, width)

    def _deserialize_widget_layout(self, node, workspace, parent_splitter, missing_items):
        node_type = node.get("type")
        if node_type == "splitter":
            orient_text = node.get("orientation", "horizontal")
            orientation = Qt.Horizontal if orient_text == "horizontal" else Qt.Vertical
            splitter = QSplitter(orientation)
            workspace.register_splitter(splitter)
            for child_node in node.get("children", []):
                child_widget = self._deserialize_widget_layout(child_node, workspace, splitter, missing_items)
                if child_widget is not None:
                    splitter.addWidget(child_widget)
            return splitter

        if node_type == "plot":
            plot = AdvancedPlot(self, workspace, parent_splitter)
            is_dark = self.theme_combo.currentText() == "Dark Mode"
            plot.apply_theme_to_overlay(is_dark)
            plot.apply_theme_to_plot_controls(is_dark)
            self._restore_plot_from_layout(plot, node, missing_items)
            return plot

        return None

    def _apply_layout_to_workspace(self, workspace, layout_data):
        missing_items = []

        workspace.master_time_plot = None
        workspace.global_min_x = None
        workspace.global_max_x = None
        workspace.range_start = 0.0
        workspace.range_end = 1.0
        workspace.timeline.setXRange(0.0, 1.0, padding=0)
        workspace.grid_plots.clear()

        while workspace.grid_root.count():
            child = workspace.grid_root.widget(0)
            child.setParent(None)
            child.deleteLater()

        root_node = layout_data.get("root")
        if not isinstance(root_node, dict):
            return False, ["invalid_layout"]

        if root_node.get("type") == "splitter":
            orient_text = root_node.get("orientation", "vertical")
            workspace.grid_root.setOrientation(Qt.Vertical if orient_text == "vertical" else Qt.Horizontal)
            for child_node in root_node.get("children", []):
                child_widget = self._deserialize_widget_layout(child_node, workspace, workspace.grid_root, missing_items)
                if child_widget is not None:
                    workspace.grid_root.addWidget(child_widget)
        elif root_node.get("type") == "plot":
            workspace.grid_root.setOrientation(Qt.Vertical)
            child_widget = self._deserialize_widget_layout(root_node, workspace, workspace.grid_root, missing_items)
            if child_widget is not None:
                workspace.grid_root.addWidget(child_widget)
        else:
            return False, ["invalid_layout"]

        if workspace.grid_root.count() == 0:
            fallback_plot = AdvancedPlot(self, workspace, workspace.grid_root)
            fallback_plot.plot.setTitle("ULG 파일 업로드 후 그래프가 표시됩니다.")
            workspace.grid_root.addWidget(fallback_plot)

        workspace._refresh_first_plot_ref()
        workspace.start_handle.setValue(workspace.range_start)
        workspace.end_handle.setValue(workspace.range_end)
        workspace.time_cursor.setValue(workspace.range_start)
        workspace.on_range_changed()
        workspace.request_rebalance_layout()
        workspace.on_cursor_changed()
        return True, missing_items

    def import_layout_to_workspace(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Layout Import",
            self._default_layout_dir(),
            "PX4 Layout (*.px4layout.json *.json);;JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                layout_data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Layout Import", f"레이아웃 파일 읽기 실패:\n{e}")
            return

        target_ws = self._select_workspace_for_layout_apply(os.path.basename(file_path))
        if not isinstance(target_ws, Workspace):
            return

        ok, missing_items = self._apply_layout_to_workspace(target_ws, layout_data)
        if not ok:
            QMessageBox.warning(self, "Layout Import", "레이아웃 형식이 올바르지 않습니다.")
            return

        layout_theme = str(layout_data.get("theme", "")).strip()
        if layout_theme in ("Dark Mode", "Light Mode"):
            self.theme_combo.setCurrentText(layout_theme)

        tab_idx = self.tab_widget.indexOf(target_ws)
        layout_tab_name = str(layout_data.get("tab_name", "")).strip()
        if tab_idx >= 0 and layout_tab_name:
            self.tab_widget.setTabText(tab_idx, layout_tab_name)

        aircraft_type = str(layout_data.get("aircraft_type", "")).strip()
        if aircraft_type:
            target_ws.set_aircraft_type(aircraft_type)

        target_ws.current_layout_path = file_path
        self.tab_widget.setCurrentIndex(self.tab_widget.indexOf(target_ws))

        if missing_items:
            unique_missing = []
            for item in missing_items:
                if item not in unique_missing:
                    unique_missing.append(item)
            preview = ", ".join(unique_missing[:4])
            if len(unique_missing) > 4:
                preview += f" 외 {len(unique_missing) - 4}개"
            self.statusBar().showMessage(
                f"레이아웃 로드 완료 (일부 항목 미복원): {preview}",
                7000,
            )
        else:
            self.statusBar().showMessage(f"레이아웃 로드 완료: {os.path.basename(file_path)}", 5000)

    def show_current_layout_path(self):
        workspace = self._current_workspace()
        if workspace is None:
            QMessageBox.information(self, "Layout Path", "현재 활성화된 분석창이 없습니다.")
            return

        layout_path = getattr(workspace, "current_layout_path", None)
        if not layout_path:
            QMessageBox.information(
                self,
                "Layout Path",
                "현재 분석창에 연결된 레이아웃 파일이 없습니다.\n먼저 Layout Export 또는 Import를 수행해 주세요.",
            )
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Layout Path")
        msg.setIcon(QMessageBox.Information)
        msg.setText(layout_path)
        btn_open_dir = msg.addButton("폴더 열기", QMessageBox.ActionRole)
        btn_open_file = msg.addButton("파일 열기", QMessageBox.ActionRole)
        btn_copy = msg.addButton("경로 복사", QMessageBox.ActionRole)
        btn_close = msg.addButton("닫기", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_open_dir)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_copy:
            QApplication.clipboard().setText(layout_path)
            self.statusBar().showMessage("레이아웃 경로를 복사했습니다.", 3000)
            return

        if clicked == btn_open_file:
            if not os.path.exists(layout_path):
                QMessageBox.warning(self, "Layout Path", "파일이 존재하지 않습니다.")
                return
            try:
                os.startfile(layout_path)
            except Exception as e:
                QMessageBox.warning(self, "Layout Path", f"파일 열기 실패:\n{e}")
            return

        if clicked == btn_open_dir:
            target_dir = os.path.dirname(layout_path) if os.path.dirname(layout_path) else layout_path
            if not os.path.exists(target_dir):
                QMessageBox.warning(self, "Layout Path", "폴더가 존재하지 않습니다.")
                return
            try:
                os.startfile(target_dir)
            except Exception as e:
                QMessageBox.warning(self, "Layout Path", f"폴더 열기 실패:\n{e}")
            return

    def add_workspace(self):
        self.workspace_count += 1
        self.right_stack.setUpdatesEnabled(False)
        self.tab_widget.setUpdatesEnabled(False)
        try:
            new_ws = Workspace(self)
            tab_name = f"분석 창 {self.workspace_count}"
            idx = self.tab_widget.addTab(new_ws, tab_name)
            self.tab_widget.setCurrentIndex(idx)
            self._update_right_panel_state()
        finally:
            self.tab_widget.setUpdatesEnabled(True)
            self.right_stack.setUpdatesEnabled(True)

    def close_workspace(self, index):
        ws = self.tab_widget.widget(index)
        if ws is None:
            return

        if self.last_active_plot and isinstance(ws, Workspace):
            try:
                if self.last_active_plot in ws.findChildren(AdvancedPlot):
                    self.last_active_plot = None
            except RuntimeError:
                self.last_active_plot = None

        self.tab_widget.removeTab(index)
        ws.deleteLater()

        if self.tab_widget.count() == 0:
            self.workspace_count = 0
        self._update_right_panel_state()

    def _update_right_panel_state(self):
        if self.tab_widget.count() > 0:
            self.right_stack.setCurrentWidget(self.tab_widget)
        else:
            self.right_stack.setCurrentWidget(self.blank_state_widget)

    def _apply_brand_icon(self):
        main_icon_path = self._find_main_icon_path()
        if main_icon_path:
            main_icon = QIcon(main_icon_path)
            if not main_icon.isNull():
                self.setWindowIcon(main_icon)
                app = QApplication.instance()
                if app is not None:
                    app.setWindowIcon(main_icon)

        ui_icon_path = self._find_ui_icon_path()
        if not ui_icon_path:
            return False

        logo_target_w = max(1, int(64))
        logo_target_h = max(1, int(22))
        pixmap = QPixmap(ui_icon_path)
        if pixmap.isNull():
            ui_icon = QIcon(ui_icon_path)
            if ui_icon.isNull():
                return False
            pixmap = ui_icon.pixmap(logo_target_w, logo_target_h)
        if pixmap.isNull():
            return False

        logo_pix = pixmap.scaled(logo_target_w, logo_target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.logo_label.setText("")
        self.logo_label.setPixmap(logo_pix)
        self.logo_label.setMinimumWidth(logo_pix.width())
        return True

    @staticmethod
    def _format_aircraft_type(airframe_raw):
        mapping = {
            "VTOL": "VTOL",
            "FIXED_WING": "Fixed-Wing",
            "MULTICOPTER": "Multicopter",
        }
        return mapping.get(airframe_raw, "Unknown")

    def _detect_aircraft_type(self, dataset):
        if FlightTypeDetector is None:
            return "Unknown"
        try:
            detector = FlightTypeDetector(dataset)
            return self._format_aircraft_type(detector.detect())
        except Exception as e:
            print(f"[GUI] 기체 타입 분석 실패: {e}")
            return "Unknown"

    @staticmethod
    def _workspace_signal_count(workspace):
        return sum(len(p.plotted_signals) for p in workspace.findChildren(AdvancedPlot))

    def _build_fallback_dashboard(self, workspace, filename, dataset):
        workspace.create_grid([1])
        fallback_plot = workspace.get_plot(0, 0)
        fallback_plot.plot.setTitle("Fallback Dashboard (Auto)")

        numeric_types = {
            pl.Int8, pl.Int16, pl.Int32, pl.Int64,
            pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
            pl.Float32, pl.Float64, pl.Boolean,
        }

        for topic_name in sorted(dataset.topics.keys()):
            topic = dataset.topics[topic_name]
            df = topic.dataframe
            if df is None or "timestamp_sec" not in df.columns:
                continue

            candidate_signals = []
            for col in df.columns:
                if col in ("timestamp", "timestamp_sec"):
                    continue
                if df[col].dtype in numeric_types:
                    candidate_signals.append(col)

            if not candidate_signals:
                continue

            for sig in candidate_signals[:4]:
                fallback_plot.render_signal(filename, topic_name, sig)

            if len(fallback_plot.plotted_signals) > 0:
                fallback_plot.plot.setTitle(f"Fallback Dashboard: {topic_name}")
                return True

        return False

    def _active_workspace(self):
        ws = self.tab_widget.currentWidget()
        if isinstance(ws, Workspace):
            return ws
        return None

    def _resolve_signal_drop_target(self, global_pos, allow_fallback=True):
        widget = QApplication.widgetAt(global_pos)
        while widget is not None:
            if isinstance(widget, AdvancedPlot):
                return widget
            widget = widget.parentWidget()

        if not allow_fallback:
            return None

        ws = self._active_workspace()
        if ws is None:
            return None
        if self.last_active_plot and self.last_active_plot in ws.findChildren(AdvancedPlot):
            return self.last_active_plot
        return ws.first_plot

    @staticmethod
    def _render_signal_uris_to_plot(target_plot, uris, prefer_curve_popup=False):
        if target_plot is None or not uris:
            return False
        if hasattr(target_plot, "_apply_signal_uris"):
            return bool(target_plot._apply_signal_uris(uris, prefer_curve_popup=prefer_curve_popup))
        rendered_any = False
        for uri in uris:
            parts = uri.split('|')
            if len(parts) < 3:
                continue
            file_name, topic_name, signal_name = parts[:3]
            x_axis_col = parts[3] if len(parts) > 3 else "timestamp_sec"
            rendered_any = target_plot.render_signal(file_name, topic_name, signal_name, x_axis_col) or rendered_any
        return rendered_any

    def handle_signal_drop_from_cursor(self, uris, global_pos, strict_target=False, prefer_curve_popup=False):
        target_plot = self._resolve_signal_drop_target(global_pos, allow_fallback=not strict_target)
        rendered = self._render_signal_uris_to_plot(target_plot, uris, prefer_curve_popup=prefer_curve_popup)
        print(f"[DND][Fallback] uris={len(uris)} rendered={rendered} target={type(target_plot).__name__ if target_plot else 'None'}")
        if rendered:
            self.last_active_plot = target_plot
            self.statusBar().showMessage(f"{len(uris)}개 신호를 그래프에 추가했습니다.", 2500)
        return rendered

    def _set_global_signal_drop_highlight(self, target_plot):
        if self._signal_drop_hover_plot is target_plot:
            return
        if self._signal_drop_hover_plot is not None:
            try:
                self._signal_drop_hover_plot._set_drop_highlight(False)
            except Exception:
                pass
        self._signal_drop_hover_plot = target_plot
        if self._signal_drop_hover_plot is not None:
            try:
                self._signal_drop_hover_plot._set_drop_highlight(True)
            except Exception:
                pass

    def _clear_global_signal_drop_highlight(self):
        self._set_global_signal_drop_highlight(None)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.DragLeave and self._signal_drop_hover_plot is not None:
            self._clear_global_signal_drop_highlight()
        if etype in (QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop):
            mime_data_getter = getattr(event, "mimeData", None)
            mime_data = mime_data_getter() if callable(mime_data_getter) else None
            signal_uris = AdvancedPlot._signal_uris_from_mime(mime_data)
            if signal_uris:
                if etype == QEvent.DragLeave:
                    self._clear_global_signal_drop_highlight()
                    event.accept()
                    return True

                target_plot = self._resolve_signal_drop_target(QCursor.pos())
                self._set_global_signal_drop_highlight(target_plot)

                if etype in (QEvent.DragEnter, QEvent.DragMove):
                    event.setDropAction(Qt.CopyAction)
                    event.accept()
                    return True

                if etype == QEvent.Drop:
                    prefer_curve_popup = AdvancedPlot._prefers_curve_popup_from_mime(mime_data)
                    rendered = self._render_signal_uris_to_plot(
                        target_plot,
                        signal_uris,
                        prefer_curve_popup=prefer_curve_popup,
                    )
                    self._clear_global_signal_drop_highlight()
                    print(f"[DND][AppFilter] drop uris={len(signal_uris)} rendered={rendered} target={type(target_plot).__name__ if target_plot else 'None'}")
                    if rendered:
                        self.last_active_plot = target_plot
                        event.setDropAction(Qt.CopyAction)
                        event.accept()
                    else:
                        event.ignore()
                    return True

        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        signal_uris = AdvancedPlot._signal_uris_from_mime(mime_data)
        if signal_uris:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        if mime_data and FileDropWidget._has_file_like_payload(mime_data):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        mime_data = event.mimeData()
        signal_uris = AdvancedPlot._signal_uris_from_mime(mime_data)
        if signal_uris:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        if mime_data and FileDropWidget._has_file_like_payload(mime_data):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        signal_uris = AdvancedPlot._signal_uris_from_mime(mime_data)
        if signal_uris:
            global_pos = self.mapToGlobal(event.position().toPoint())
            target_plot = self._resolve_signal_drop_target(global_pos)
            prefer_curve_popup = AdvancedPlot._prefers_curve_popup_from_mime(mime_data)
            rendered = self._render_signal_uris_to_plot(
                target_plot,
                signal_uris,
                prefer_curve_popup=prefer_curve_popup,
            )
            print(f"[DND][MainWindow] signal drop uris={len(signal_uris)} rendered={rendered} target={type(target_plot).__name__ if target_plot else 'None'}")
            if rendered:
                self.last_active_plot = target_plot
                event.acceptProposedAction()
                return
            self.statusBar().showMessage("드롭은 감지됐지만 신호를 렌더링하지 못했습니다. 콘솔 로그를 확인해 주세요.", 4000)
            event.ignore()
            return

        file_paths = FileDropWidget._extract_ulg_files(mime_data)
        if file_paths:
            event.acceptProposedAction()
            self.load_log_files(file_paths)
            return
        try:
            formats = ", ".join(mime_data.formats()) if mime_data else ""
            sample_text = (mime_data.text() or "").strip()[:160] if mime_data else ""
            print(f"[DND][MainWindow] no .ulg extracted | formats=[{formats}] | text='{sample_text}'")
        except Exception:
            pass
        super().dropEvent(event)

    def load_log_files(self, file_paths):
        io_engine = LogIOEngine()
        loaded_count = 0
        skipped_missing = []
        
        for file_path in file_paths:
            if not file_path or not os.path.isfile(file_path):
                if file_path:
                    skipped_missing.append(file_path)
                continue
            filename = os.path.basename(file_path)
            if filename in self.loaded_datasets: continue

            dataset = io_engine.load(file_path)
            if not dataset: continue
            
            try:
                flight_start_time = None
                for t_name in ["vehicle_attitude_0", "sensor_combined_0", "vehicle_local_position_0"]:
                    if t_name in dataset.topics:
                        t_col = dataset.topics[t_name].dataframe.get_column("timestamp_sec").drop_nulls()
                        t_col = t_col.filter(t_col > 0.1) 
                        if len(t_col) > 0:
                            flight_start_time = t_col.min()
                            break
                
                if flight_start_time is not None:
                    for topic in dataset.topics.values():
                        if "timestamp_sec" in topic.dataframe.columns:
                            df = topic.dataframe.with_columns(
                                (pl.col("timestamp_sec") - flight_start_time).alias("timestamp_sec")
                            )
                            topic.dataframe = df.filter(pl.col("timestamp_sec") >= -30.0)

                from engines.math_engine import MathEngine
                MathEngine.preprocess_dataset(dataset)
            except Exception as e:
                print(f"\n[GUI] 데이터 전처리 오류: {e}")
                traceback.print_exc()
                
            aircraft_type = self._detect_aircraft_type(dataset)
            self.loaded_datasets[filename] = dataset
            self.loaded_aircraft_types[filename] = aircraft_type
            self.loaded_log_metadata[filename] = self._extract_log_metadata(file_path)
            self._add_to_tree(filename, dataset, aircraft_type)
            if self.active_analysis_log is None:
                self.active_analysis_log = filename
            loaded_count += 1
            current_ws = self.tab_widget.currentWidget()
            if isinstance(current_ws, Workspace):
                current_ws.set_aircraft_type(aircraft_type)
            else:
                self.statusBar().showMessage(
                    f"Loaded: {filename} | Aircraft Type: {aircraft_type} | + New Tab으로 분석 창을 생성하세요.",
                    5000,
                )
                continue
            self.statusBar().showMessage(f"Loaded: {filename} | Aircraft Type: {aircraft_type}", 4000)

        self._refresh_custom_series_list()

        if self.loaded_datasets:
            self.file_drop_widget.setText(f"Total {len(self.loaded_datasets)} Log Load complete!\n(You can upload more ulogs)")
        else:
            self.file_drop_widget.setText("Date(ulg) Upload\n(Multiple choices available)")

        if loaded_count > 0:
            if self.active_analysis_log not in self.loaded_datasets:
                self.active_analysis_log = next(iter(self.loaded_datasets.keys()))
            self._update_tree_file_node_styles()
            self.show_log_info_dialog(target_file=self.active_analysis_log)

        if loaded_count == 0:
            if skipped_missing:
                sample = skipped_missing[0]
                self.statusBar().showMessage("드롭은 감지됐지만 유효한 ULG 파일 경로를 확인하지 못했습니다.", 5000)
                QMessageBox.warning(
                    self,
                    "Drag & Drop",
                    f"드롭은 감지됐지만 파일을 열 수 없습니다.\n경로 예시:\n{sample}\n\n"
                    "파일이 존재하는지, 권한 문제(관리자/일반 권한 불일치)가 없는지 확인해 주세요.",
                )
            else:
                self.statusBar().showMessage("드롭된 항목에서 .ulg 파일을 찾지 못했습니다.", 5000)

    def on_tree_search_changed(self, text):
        self._pending_tree_filter_text = (text or "").strip().lower()
        self._tree_search_timer.start()

    def apply_tree_search(self):
        root_item = self.tree_model.invisibleRootItem()
        query = (self._pending_tree_filter_text or "").strip().lower()

        if not query:
            for row in range(root_item.rowCount()):
                top_item = root_item.child(row)
                if top_item is not None:
                    self._set_tree_item_visibility(top_item, True)
            return

        for row in range(root_item.rowCount()):
            top_item = root_item.child(row)
            if top_item is not None:
                self._filter_tree_item(top_item, query, force_visible=False)

    def _set_tree_item_visibility(self, item, visible):
        parent_item = item.parent()
        parent_index = parent_item.index() if parent_item else QModelIndex()
        self.tree_view.setRowHidden(item.row(), parent_index, not visible)
        for row in range(item.rowCount()):
            child_item = item.child(row)
            if child_item is not None:
                self._set_tree_item_visibility(child_item, visible)

    def _filter_tree_item(self, item, query, force_visible=False):
        item_text = item.text().lower()
        if item.parent() is None:
            file_name = item.data(Qt.UserRole)
            if isinstance(file_name, str):
                item_text = f"{item_text} {file_name.lower()}"

        own_match = (query in item_text)
        show_children = force_visible or own_match
        child_match = False

        for row in range(item.rowCount()):
            child_item = item.child(row)
            if child_item is None:
                continue
            child_visible = self._filter_tree_item(child_item, query, force_visible=show_children)
            child_match = child_match or child_visible

        visible = show_children or child_match
        parent_item = item.parent()
        parent_index = parent_item.index() if parent_item else QModelIndex()
        self.tree_view.setRowHidden(item.row(), parent_index, not visible)

        if visible and item.rowCount() > 0 and query and (own_match or child_match):
            self.tree_view.expand(item.index())

        return visible

    def _add_to_tree(self, filename, dataset, aircraft_type):
        root_item = self.tree_model.invisibleRootItem()
        tree_font_size = max(6.0, 14.0 * 0.6)

        file_node = QStandardItem(f"{filename} | Type : {aircraft_type}")
        file_node.setEditable(False)
        file_node.setData(filename, Qt.UserRole)
        file_node.setData(aircraft_type, Qt.UserRole + 1)
        file_font = QFont()
        file_font.setBold(True)
        file_font.setPointSizeF(tree_font_size)
        file_node.setFont(file_font)
        file_node.setForeground(QBrush(QColor("#000000"))) 
        
        for topic_name in sorted(dataset.topics.keys()):
            topic_node = QStandardItem(topic_name)
            topic_node.setEditable(False)
            topic_font = QFont()
            topic_font.setPointSizeF(tree_font_size)
            topic_node.setFont(topic_font)
            for signal_name in dataset.topics[topic_name].signals.keys():
                signal_node = QStandardItem(signal_name)
                signal_node.setEditable(False)
                signal_font = QFont()
                signal_font.setPointSizeF(tree_font_size)
                signal_node.setFont(signal_font)
                signal_node.setForeground(QBrush(QColor("#333333")))
                topic_node.appendRow(signal_node)
            file_node.appendRow(topic_node)
        root_item.appendRow(file_node)
        self.apply_tree_search()
        self._update_tree_file_node_styles()

def _prewarm_gl_context(app):
    if gl is None:
        return
    try:
        warm = FlightPath3DViewWidget()
        warm.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        warm.resize(2, 2)
        warm.move(-20000, -20000)
        warm.show()
        app.processEvents()
        warm.hide()
        warm.deleteLater()
        print("[3D] OpenGL context prewarmed.")
    except Exception as e:
        print(f"[3D] OpenGL prewarm skipped: {e}")

if __name__ == "__main__":
    try:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    except Exception:
        pass
    app = QApplication(sys.argv)
    _prewarm_gl_context(app)
    
    app.setStyleSheet("""
        QSplitter::handle { background-color: #333333; }
        QSplitter::handle:horizontal { width: 5px; }
        QSplitter::handle:vertical { height: 5px; }
        QSplitter::handle:hover { background-color: #4CAF50; }
        QTabBar::tab { padding: 8px 15px; font-weight: bold; background-color: #2b2b2b; color: #aaaaaa; }
        QTabBar::tab:selected { background-color: #1A2D57; color: white; }
    """)
    
    window = MainWindow()
    try:
        if not window.windowIcon().isNull():
            app.setWindowIcon(window.windowIcon())
    except Exception:
        pass
    window.show()
    sys.exit(app.exec())
