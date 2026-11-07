import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal, QMimeData, QTimer, QPoint
from PySide6.QtGui import QDrag, QPainter, QColor, QPen, QPolygon, QImage, QPixmap, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QSlider, QComboBox, QPushButton, QStackedWidget,
    QTextEdit
)
from ui.highlighter import PythonSyntaxHighlighter

from core import blocks as B

MIME = "application/x-lab-block"
SLOT_H = 14
THUMB_W, THUMB_H = 48, 36


def _darker(color, f=0.75):
    c = QColor(color)
    return QColor(int(c.red() * f), int(c.green() * f), int(c.blue() * f)).name()


class PaletteItem(QLabel):
    """A block in the palette: drag it into the program (or double-click to append it to the end)."""
    def __init__(self, btype, editor):
        d = B.BLOCKS[btype]
        super().__init__(d.title)
        self.btype = btype
        self.editor = editor
        col = B.CATEGORY_COLORS[d.category]
        self.setStyleSheet(
            f"background:{col}; color:white; font-weight:bold; border-radius:6px; padding:3px 7px; font-size:11px; "
            f"border-bottom:2px solid {_darker(col)};")
        self.setToolTip(d.help)
        self.setCursor(Qt.OpenHandCursor)
        self._press = None

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        start_drag(self, f"new:{self.btype}")

    def mouseDoubleClickEvent(self, e):
        self.editor.append_new(self.btype)


def start_drag(widget, payload):
    drag = QDrag(widget)
    mime = QMimeData()
    mime.setData(MIME, payload.encode())
    drag.setMimeData(mime)
    drag.setPixmap(widget.grab().scaledToWidth(min(widget.width(), 260), Qt.SmoothTransformation))
    drag.exec(Qt.MoveAction)


class DropSlot(QWidget):
    """Gap between blocks: draws the connecting arrow and accepts dropped blocks."""
    def __init__(self, editor, owner, which, index):
        super().__init__()
        self.editor, self.owner, self.which, self.index = editor, owner, which, index
        self.setAcceptDrops(True)
        self.setFixedHeight(SLOT_H)
        self.hover = False

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self.hover = True
            self.setFixedHeight(SLOT_H * 2)
            self.update()

    def dragLeaveEvent(self, e):
        self.hover = False
        self.setFixedHeight(SLOT_H)
        self.update()

    def dropEvent(self, e):
        payload = bytes(e.mimeData().data(MIME)).decode()
        e.acceptProposedAction()
        self.editor.drop(payload, self.owner, self.which, self.index)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() // 2
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4daafc"))
            p.drawRoundedRect(10, self.height() // 2 - 3, self.width() - 20, 6, 3, 3)
            return
        col = QColor("#8a8f98")
        p.setPen(QPen(col, 2))
        p.drawLine(cx, 0, cx, self.height() - 5)
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(cx - 4, self.height() - 6), QPoint(cx + 4, self.height() - 6),
                                QPoint(cx, self.height() - 1)]))


class BlockWidget(QFrame):
    def __init__(self, editor, node):
        super().__init__()
        self.editor, self.node = editor, node
        d = B.BLOCKS[node["t"]]
        self.d = d
        self.col = B.CATEGORY_COLORS[d.category]
        self.setObjectName("block")
        self.setToolTip(d.help)
        self._press = None
        self.setStyleSheet(self._style(False))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 3, 6, 4)
        outer.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(d.title)
        self.title.setStyleSheet("color:white; font-weight:bold; font-size:12px; background:transparent;")
        self.title.setCursor(Qt.OpenHandCursor)
        head.addWidget(self.title)
        for spec in d.params:
            head.addLayout(self._param_row(spec), 1)
        head.addStretch(0)
        self.thumb = None
        if d.preview:
            self.thumb = QLabel()
            self.thumb.setFixedSize(THUMB_W, THUMB_H)
            self.thumb.setStyleSheet("background:#101010; border-radius:3px;")
            self.thumb.setAlignment(Qt.AlignCenter)
            head.addWidget(self.thumb)
        btn = QPushButton("\u2715")
        btn.setFixedSize(18, 18)
        btn.setStyleSheet("QPushButton{background:rgba(0,0,0,70);color:white;border-radius:9px;padding:0;font-size:10px;}"
                          "QPushButton:hover{background:rgba(0,0,0,140);}")
        btn.clicked.connect(lambda: editor.delete(node["id"]))
        head.addWidget(btn, 0, Qt.AlignTop)
        outer.addLayout(head)

        self.err = QLabel()
        self.err.setWordWrap(True)
        self.err.setStyleSheet("color:#ffd5d5; background:rgba(160,0,0,160); border-radius:3px; padding:2px 6px; font-size:11px;")
        self.err.hide()
        outer.addWidget(self.err)

        if d.container:
            self.inner = QVBoxLayout()
            self.inner.setContentsMargins(8, 0, 0, 0)
            outer.addLayout(self.inner)

    def _style(self, error):
        border = "#ff4d4d" if error else _darker(self.col)
        return (f"QFrame#block{{background:{self.col}; border-radius:7px; border:{3 if error else 1}px solid {border};}}"
                f"QLabel{{background:transparent;}}")

    def set_error(self, msg):
        self.setStyleSheet(self._style(bool(msg)))
        self.err.setText(msg or "")
        self.err.setVisible(bool(msg))

    def _param_row(self, spec):
        row = QHBoxLayout()
        lab = QLabel(spec["label"])
        lab.setStyleSheet("color:white; background:transparent; font-size:11px;")
        row.addWidget(lab)
        node = self.node
        if spec["kind"] == "int":
            sl = QSlider(Qt.Horizontal)
            sl.setMinimumWidth(70)
            step = spec.get("step", 1)
            sl.setRange(0, (spec["max"] - spec["min"]) // step)
            sl.setValue((int(node["p"][spec["key"]]) - spec["min"]) // step)
            val = QLabel()
            val.setStyleSheet("color:white; font-weight:bold; background:transparent; font-size:11px; min-width:40px;")
            val.setText(f"{node['p'][spec['key']]} {spec.get('unit', '')}".strip())

            def changed(v, spec=spec, val=val, step=step):
                x = spec["min"] + v * step
                node["p"][spec["key"]] = x
                val.setText(f"{x} {spec.get('unit', '')}".strip())
                self.editor.params_changed(node)
            sl.valueChanged.connect(changed)
            row.addWidget(sl, 1)
            row.addWidget(val)
        else:
            cb = QComboBox()
            for value, label in spec["choices"]:
                cb.addItem(label, value)
            cb.setCurrentIndex(max(0, cb.findData(node["p"][spec["key"]])))

            def changed(_i, spec=spec, cb=cb):
                node["p"][spec["key"]] = cb.currentData()
                self.editor.params_changed(node, structural=True)
            cb.currentIndexChanged.connect(changed)
            row.addWidget(cb, 1)
        return row

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        start_drag(self, f"move:{self.node['id']}")


class BlockEditor(QWidget):
    """Visual program editor shown in Stage 0 in place of the code editor."""
    changed = Signal()

    def __init__(self, program=None):
        super().__init__()
        self.program = program or B.new_program()
        self.widgets = {}
        self.errors = {}
        self.warnings = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Palette: a horizontal strip on top, one column per category
        pal_scroll = QScrollArea()
        pal_scroll.setWidgetResizable(True)
        pal_scroll.setFixedHeight(142)
        pal_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pal = QWidget()
        pl = QHBoxLayout(pal)
        pl.setContentsMargins(6, 4, 6, 4)
        pl.setSpacing(10)
        for name, types in B.PALETTE:
            col = QVBoxLayout()
            col.setSpacing(3)
            h = QLabel(name.upper())
            h.setStyleSheet("color:#4daafc; font-weight:bold; font-size:10px;")
            col.addWidget(h)
            for t in types:
                col.addWidget(PaletteItem(t, self))
            col.addStretch(1)
            pl.addLayout(col)
        pl.addStretch(1)
        pal_scroll.setWidget(pal)
        pal_scroll.setToolTip("Drag a block into the program below (double-click appends it to the end).")
        root.addWidget(pal_scroll)

        # Program (or its generated Python code)
        self.view = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.addWidget(self.scroll)
        self.code_view = QTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setFont(QFont("Courier", 10))
        self.highlighter = PythonSyntaxHighlighter(self.code_view.document())
        self.view.addWidget(self.code_view)
        root.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.btn_code = QPushButton("Show code")
        self.btn_code.setCheckable(True)
        self.btn_code.setObjectName("secondary")
        self.btn_code.toggled.connect(self._toggle_code)
        bottom.addWidget(self.btn_code)
        root.addLayout(bottom)

        self.rebuild()

    def _toggle_code(self, show):
        self.btn_code.setText("Show blocks" if show else "Show code")
        self.view.setCurrentIndex(1 if show else 0)

    def show_runtime_error(self, text):
        self.status.setText("\u26a0  " + text.strip().splitlines()[-1][:160])
        self.status.setStyleSheet("color:#ff8080; font-weight:bold;")

    # ---------- model access ----------
    def set_program(self, program):
        self.program = program
        self.rebuild()
        self.changed.emit()

    def code(self):
        return B.generate_code(self.program)

    def is_valid(self):
        return not self.errors and not self.warnings

    def problem_text(self):
        return "; ".join(list(self.errors.values()) + self.warnings)

    def has_content(self):
        return bool(self.program["children"])

    def _list_for(self, owner, which):
        if owner is None:
            return self.program["children"]
        return self._find(self.program["children"], owner)[which]

    def _find(self, nodes, node_id):
        for n in nodes:
            if n["id"] == node_id:
                return n
            for key in ("c", "e"):
                r = self._find(n.get(key, []), node_id)
                if r:
                    return r
        return None

    def _locate(self, nodes, node_id):
        for i, n in enumerate(nodes):
            if n["id"] == node_id:
                return nodes, i
            for key in ("c", "e"):
                r = self._locate(n.get(key, []), node_id)
                if r:
                    return r
        return None

    # ---------- edits ----------
    def append_new(self, btype):
        self.program["children"].append(B.new_node(btype))
        self._structure_changed()

    def drop(self, payload, owner, which, index):
        kind, _, arg = payload.partition(":")
        target = self._list_for(owner, which)
        if kind == "new":
            target.insert(index, B.new_node(arg))
        elif kind == "move":
            node_id = int(arg)
            node = self._find(self.program["children"], node_id)
            if node is None or (owner is not None and self._find([node], owner) is not None):
                return   # cannot drop a block into itself
            lst, i = self._locate(self.program["children"], node_id)
            lst.pop(i)
            if lst is target and i < index:
                index -= 1
            target.insert(index, node)
        QTimer.singleShot(0, self._structure_changed)

    def delete(self, node_id):
        r = self._locate(self.program["children"], node_id)
        if r:
            r[0].pop(r[1])
            QTimer.singleShot(0, self._structure_changed)

    def params_changed(self, node, structural=False):
        if structural:
            QTimer.singleShot(0, self._structure_changed)
        else:
            self._revalidate()
            self.changed.emit()

    def _structure_changed(self):
        self.rebuild()
        self.changed.emit()

    # ---------- view ----------
    def rebuild(self):
        self.widgets = {}
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(0)

        setup = QFrame()
        setup.setObjectName("block")
        col = "#7a63b8"
        setup.setStyleSheet(f"QFrame#block{{background:{col}; border-radius:8px; border:2px solid {_darker(col)};}}"
                            "QLabel{background:transparent;color:white;}")
        sl = QHBoxLayout(setup)
        t = QLabel("Set camera exposure")
        t.setStyleSheet("font-weight:bold;")
        sl.addWidget(t)
        s = QSlider(Qt.Horizontal)
        s.setRange(1, 30)
        s.setValue(int(self.program["exposure_ms"]))
        v = QLabel(f"{self.program['exposure_ms']} ms")
        v.setStyleSheet("font-weight:bold; min-width:50px;")

        def exp_changed(x):
            self.program["exposure_ms"] = x
            v.setText(f"{x} ms")
            self.changed.emit()
        s.valueChanged.connect(exp_changed)
        sl.addWidget(s, 1)
        sl.addWidget(v)
        setup.setToolTip("A short exposure makes the laser spot much brighter than the rest of the picture.")
        lay.addWidget(setup)
        arrow = DropSlot(self, None, "c", 0)
        arrow.setAcceptDrops(False)
        lay.addWidget(arrow)

        loop = QFrame()
        loop.setObjectName("loop")
        loop.setStyleSheet("QFrame#loop{background:#2b2b2e; border-radius:10px; border:2px solid #d9962b;}"
                           "QLabel{background:transparent;}")
        ll = QVBoxLayout(loop)
        ll.setSpacing(0)
        lt = QLabel("⟳  REPEAT FOREVER")
        lt.setStyleSheet("color:#d9962b; font-weight:bold; padding:2px 6px 6px 6px;")
        ll.addWidget(lt)
        self._fill(ll, self.program["children"], None, "c")
        lay.addWidget(loop)
        lay.addStretch(1)
        self.scroll.setWidget(content)
        self._revalidate()

    def _fill(self, layout, nodes, owner, which):
        layout.addWidget(DropSlot(self, owner, which, 0))
        for i, n in enumerate(nodes):
            w = BlockWidget(self, n)
            self.widgets[n["id"]] = w
            layout.addWidget(w)
            if w.d.container:
                self._fill(w.inner, n["c"], n["id"], "c")
                if w.d.has_else:
                    el = QLabel("ELSE (no spot)")
                    el.setStyleSheet("color:white; font-weight:bold; padding:4px 0 0 14px; background:transparent;")
                    w.inner.addWidget(el)
                    self._fill(w.inner, n["e"], n["id"], "e")
            layout.addWidget(DropSlot(self, owner, which, i + 1))

    def _revalidate(self):
        self.errors, self.warnings = B.validate(self.program)
        for nid, w in self.widgets.items():
            w.set_error(self.errors.get(nid))
        self.code_view.setPlainText(self.code())
        if self.errors:
            self.status.setText("⚠  Fix the red blocks to run the program.")
            self.status.setStyleSheet("color:#ff8080; font-weight:bold;")
        elif self.warnings:
            self.status.setText("⚠  " + self.warnings[0])
            self.status.setStyleSheet("color:#ffcc66; font-weight:bold;")
        else:
            self.status.setText("✓  Program is ready.")
            self.status.setStyleSheet("color:#66dd88; font-weight:bold;")

    # ---------- live thumbnails ----------
    def set_probes(self, probes):
        for nid, w in self.widgets.items():
            if w.thumb is None:
                continue
            img = probes.get(nid)
            w.thumb.setPixmap(self._pixmap(img) if isinstance(img, np.ndarray) else QPixmap())

    @staticmethod
    def _pixmap(img):
        small = cv2.resize(img, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
        if small.ndim == 2:
            qi = QImage(small.data, THUMB_W, THUMB_H, THUMB_W, QImage.Format_Grayscale8)
        else:
            qi = QImage(small.data, THUMB_W, THUMB_H, THUMB_W * 3, QImage.Format_BGR888)
        return QPixmap.fromImage(qi.copy())
