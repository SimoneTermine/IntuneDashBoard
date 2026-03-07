"""
app/ui/pages/security_page.py  —  v1.4.1

Security Hardening Hub.

Struttura:
  Header:   titolo + ultimo audit + pulsante Esegui Audit
  KPI row:  4 card  (Score %, Coperti, Parziali, Mancanti)
  Tabs:
    🛡️  Baseline Audit  — tabella categorie con status e pannello dettaglio
    💡  Policy Advisor  — card per ogni categoria missing/partial con raccomandazione
    📄  Security Report — testo riepilogativo strutturato + export CSV
"""

from __future__ import annotations

import csv
import logging
import webbrowser
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFrame, QScrollArea, QTextEdit, QFileDialog,
    QMessageBox, QSizePolicy, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QApplication, QSplitter,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont

from app.ui.widgets.kpi_card import KpiCard

logger = logging.getLogger(__name__)

# ─── Palette Catppuccin Mocha ─────────────────────────────────────────────────
_GREEN  = "#a6e3a1"
_RED    = "#f38ba8"
_YELLOW = "#f9e2af"
_MAUVE  = "#cba6f7"
_BLUE   = "#89dceb"
_BG     = "#1e1e2e"
_MANTLE = "#181825"
_S0     = "#313244"
_S1     = "#45475a"
_OV0    = "#6c7086"
_SUB    = "#a6adc8"
_TEXT   = "#cdd6f4"

_STATUS_COLOR = {"covered": _GREEN, "partial": _YELLOW, "missing": _RED}
_STATUS_LABEL = {"covered": "✅  Coperto", "partial": "⚠️  Parziale", "missing": "❌  Mancante"}
_STATUS_ICON  = {"covered": "✅", "partial": "⚠️", "missing": "❌"}

_BTN = (
    f"QPushButton {{ background:{_S0}; color:{_TEXT}; border:1px solid {_S1}; "
    f"border-radius:6px; padding:6px 14px; font-size:12px; }}"
    f"QPushButton:hover {{ background:{_S1}; }}"
    f"QPushButton:disabled {{ color:{_OV0}; }}"
)
_BTN_PRIMARY = (
    f"QPushButton {{ background:#7f52c9; color:#fff; border:none; "
    f"border-radius:6px; padding:6px 16px; font-size:12px; font-weight:bold; }}"
    f"QPushButton:hover {{ background:#9370db; }}"
    f"QPushButton:disabled {{ background:{_S1}; color:{_OV0}; }}"
)


# ─── Background worker ────────────────────────────────────────────────────────

class _AuditWorker(QThread):
    finished = Signal(list)
    error    = Signal(str)

    def run(self):
        try:
            from app.analytics.security_baseline import run_audit
            self.finished.emit(run_audit())
        except Exception as exc:
            self.error.emit(str(exc))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _score_color(pct: int) -> str:
    if pct >= 75:
        return _GREEN
    if pct >= 40:
        return _YELLOW
    return _RED


# ─── Category card (Policy Advisor) ──────────────────────────────────────────

class _CategoryCard(QFrame):
    """Card stilizzata per la tab Policy Advisor."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        status = result["status"]
        border = _STATUS_COLOR.get(status, _S1)
        self.setStyleSheet(
            f"QFrame {{ background:{_S0}; border-left:4px solid {border}; "
            f"border-top:1px solid {_S1}; border-right:1px solid {_S1}; "
            f"border-bottom:1px solid {_S1}; border-radius:8px; }}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        # Riga header
        hrow = QHBoxLayout()
        icon_lbl = QLabel(f"{result['icon']}  {result['name']}")
        icon_lbl.setStyleSheet(
            f"color:{_TEXT}; font-size:13px; font-weight:bold; border:none;"
        )
        hrow.addWidget(icon_lbl)
        hrow.addStretch()
        status_lbl = QLabel(_STATUS_LABEL.get(status, status))
        status_lbl.setStyleSheet(
            f"color:{border}; font-size:11px; font-weight:bold; "
            f"background:{_MANTLE}; border-radius:4px; padding:2px 8px; border:none;"
        )
        hrow.addWidget(status_lbl)
        lay.addLayout(hrow)

        # Descrizione
        desc = QLabel(result["description"])
        desc.setStyleSheet(f"color:{_SUB}; font-size:11px; border:none;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # Box raccomandazione
        rec_frame = QFrame()
        rec_frame.setStyleSheet(
            f"QFrame {{ background:{_MANTLE}; border-radius:6px; border:none; }}"
        )
        rec_lay = QVBoxLayout(rec_frame)
        rec_lay.setContentsMargins(10, 8, 10, 8)
        rec_lbl = QLabel("💡  " + result["recommendation"])
        rec_lbl.setStyleSheet(f"color:{_YELLOW}; font-size:11px; border:none;")
        rec_lbl.setWordWrap(True)
        rec_lay.addWidget(rec_lbl)
        lay.addWidget(rec_frame)

        # Policy parzialmente abbinate (se partial)
        if result["matching_policies"]:
            names = [p["display_name"] for p in result["matching_policies"][:3]]
            suffix = "…" if len(result["matching_policies"]) > 3 else ""
            matched_lbl = QLabel("Trovato: " + ", ".join(names) + suffix)
            matched_lbl.setStyleSheet(f"color:{_GREEN}; font-size:10px; border:none;")
            matched_lbl.setWordWrap(True)
            lay.addWidget(matched_lbl)

        # Link documentazione
        url = result.get("reference_url", "")
        if url:
            link_btn = QPushButton("📖  Documentazione Microsoft →")
            link_btn.setStyleSheet(
                f"QPushButton {{ color:{_BLUE}; background:transparent; border:none; "
                f"font-size:11px; text-align:left; padding:0; }}"
                f"QPushButton:hover {{ color:#fff; }}"
            )
            link_btn.setCursor(Qt.PointingHandCursor)
            link_btn.clicked.connect(lambda checked=False, u=url: webbrowser.open(u))
            lay.addWidget(link_btn)


# ─── Main page ────────────────────────────────────────────────────────────────

class SecurityPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audit_results: list[dict] = []
        self._worker: _AuditWorker | None = None
        self._setup_ui()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("🛡️  Security Hardening Hub")
        title.setStyleSheet(f"font-size:22px; font-weight:bold; color:{_MAUVE};")
        hdr.addWidget(title)
        hdr.addStretch()
        self._last_run_lbl = QLabel("")
        self._last_run_lbl.setStyleSheet(f"color:{_OV0}; font-size:11px;")
        hdr.addWidget(self._last_run_lbl)
        self._run_btn = QPushButton("▶  Esegui Audit")
        self._run_btn.setFixedSize(140, 32)
        self._run_btn.setStyleSheet(_BTN_PRIMARY)
        self._run_btn.clicked.connect(self._run_audit)
        hdr.addWidget(self._run_btn)
        root.addLayout(hdr)

        subtitle = QLabel(
            "Verifica se le policy Intune in cache coprono le categorie del Microsoft Security Baseline. "
            "Esegui un sync completo prima dell'audit per ottenere risultati aggiornati."
        )
        subtitle.setStyleSheet(f"color:{_SUB}; font-size:11px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── KPI cards ─────────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self._kpi_score   = KpiCard("SECURITY SCORE", "—", "su 100",    _MAUVE)
        self._kpi_covered = KpiCard("COPERTI",         "—", "categorie", _GREEN)
        self._kpi_partial = KpiCard("PARZIALI",        "—", "categorie", _YELLOW)
        self._kpi_missing = KpiCard("MANCANTI",        "—", "categorie", _RED)
        for card in (self._kpi_score, self._kpi_covered, self._kpi_partial, self._kpi_missing):
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabBar::tab {{ background:{_S0}; color:{_SUB}; padding:8px 16px; border:none; }}"
            f"QTabBar::tab:selected {{ background:{_MANTLE}; color:{_MAUVE}; "
            f"border-bottom:2px solid {_MAUVE}; }}"
            f"QTabWidget::pane {{ border:1px solid {_S1}; border-radius:6px; }}"
        )
        root.addWidget(self._tabs)

        self._build_audit_tab()
        self._build_advisor_tab()
        self._build_report_tab()

    # ── Tab 1: Baseline Audit ─────────────────────────────────────────────────

    def _build_audit_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        hint = QLabel(
            "Ogni riga rappresenta una categoria di sicurezza e quante policy Intune la coprono. "
            "Clicca su una riga per vedere i dettagli."
        )
        hint.setStyleSheet(f"color:{_OV0}; font-size:10px;")
        lay.addWidget(hint)

        # ── Splitter: tabella (top) + dettaglio (bottom, resizable) ──────────
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{_S1}; border-radius:3px; }}"
            f"QSplitter::handle:hover {{ background:{_S0}; }}"
        )

        self._audit_table = QTableWidget()
        self._audit_table.setColumnCount(5)
        self._audit_table.setHorizontalHeaderLabels(
            ["Categoria", "Status", "Policy trovate", "Platform", "Tipo"]
        )
        self._audit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._audit_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._audit_table.verticalHeader().setVisible(False)
        self._audit_table.setShowGrid(False)
        self._audit_table.setAlternatingRowColors(True)
        hdr = self._audit_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        self._audit_table.setColumnWidth(1, 130)
        self._audit_table.setColumnWidth(2, 110)
        self._audit_table.setColumnWidth(3, 100)
        self._audit_table.setColumnWidth(4, 150)
        self._audit_table.itemSelectionChanged.connect(self._on_audit_row_selected)
        splitter.addWidget(self._audit_table)

        self._audit_detail = QTextEdit()
        self._audit_detail.setReadOnly(True)
        self._audit_detail.setMinimumHeight(60)
        self._audit_detail.setPlaceholderText(
            "Seleziona una riga per vedere dettagli e policy abbinate."
        )
        self._audit_detail.setStyleSheet(
            f"QTextEdit {{ background:{_MANTLE}; color:{_TEXT}; "
            f"border:1px solid {_S1}; border-radius:6px; font-size:11px; }}"
        )
        splitter.addWidget(self._audit_detail)

        # Proporzione iniziale: 65% tabella, 35% dettaglio
        splitter.setStretchFactor(0, 65)
        splitter.setStretchFactor(1, 35)
        splitter.setSizes([400, 200])

        lay.addWidget(splitter)

        self._tabs.addTab(w, "🛡️  Baseline Audit")

    # ── Tab 2: Policy Advisor ─────────────────────────────────────────────────

    def _build_advisor_tab(self):
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        self._advisor_scroll = QScrollArea()
        self._advisor_scroll.setWidgetResizable(True)
        self._advisor_scroll.setFrameShape(QFrame.NoFrame)
        self._advisor_inner = QWidget()
        self._advisor_layout = QVBoxLayout(self._advisor_inner)
        self._advisor_layout.setSpacing(10)
        self._advisor_layout.setContentsMargins(12, 12, 12, 12)
        self._advisor_layout.addStretch()
        self._advisor_scroll.setWidget(self._advisor_inner)
        outer_lay.addWidget(self._advisor_scroll)

        self._tabs.addTab(outer, "💡  Policy Advisor")

    # ── Tab 3: Security Report ────────────────────────────────────────────────

    def _build_report_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        btn_row = QHBoxLayout()
        btn_csv = QPushButton("📥  Esporta CSV")
        btn_csv.setStyleSheet(_BTN)
        btn_csv.clicked.connect(self._export_csv)
        btn_copy = QPushButton("📋  Copia Report")
        btn_copy.setStyleSheet(_BTN)
        btn_copy.clicked.connect(self._copy_report)
        btn_row.addWidget(btn_csv)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setPlaceholderText(
            "Esegui un Audit per generare il report di sicurezza del tenant."
        )
        self._report_text.setStyleSheet(
            f"QTextEdit {{ background:{_MANTLE}; color:{_TEXT}; "
            f"border:1px solid {_S1}; border-radius:6px; "
            f"font-family:monospace; font-size:11px; }}"
        )
        lay.addWidget(self._report_text)

        self._tabs.addTab(w, "📄  Security Report")

    # ── Audit execution ───────────────────────────────────────────────────────

    def _run_audit(self):
        self._run_btn.setEnabled(False)
        self._run_btn.setText("⏳  Analisi…")
        self._worker = _AuditWorker()
        self._worker.finished.connect(self._on_audit_done)
        self._worker.error.connect(self._on_audit_error)
        self._worker.start()

    def _on_audit_done(self, results: list[dict]):
        self._audit_results = results
        self._run_btn.setEnabled(True)
        self._run_btn.setText("▶  Esegui Audit")
        self._last_run_lbl.setText(
            f"Ultimo audit: {datetime.now().strftime('%H:%M:%S')}"
        )
        self._update_kpis(results)
        self._update_audit_table(results)
        self._update_advisor(results)
        self._update_report(results)

    def _on_audit_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("▶  Esegui Audit")
        QMessageBox.warning(self, "Audit fallito", f"Errore durante l'audit:\n{msg}")

    # ── Data update ───────────────────────────────────────────────────────────

    def _update_kpis(self, results: list[dict]):
        from app.analytics.security_baseline import compute_score
        score = compute_score(results)
        pct   = score["score_pct"]
        color = _score_color(pct)
        self._kpi_score.value_label.setStyleSheet(
            f"color:{color}; font-size:28px; font-weight:bold;"
        )
        self._kpi_score.set_value(f"{pct}%")
        self._kpi_score.set_subtitle(
            "🟢 Ottimo" if pct >= 75 else ("🟡 Migliorabile" if pct >= 40 else "🔴 Critico")
        )
        self._kpi_covered.set_value(str(score["covered"]))
        self._kpi_partial.set_value(str(score["partial"]))
        self._kpi_missing.set_value(str(score["missing"]))

    def _update_audit_table(self, results: list[dict]):
        self._audit_table.setSortingEnabled(False)
        self._audit_table.setRowCount(len(results))
        for i, r in enumerate(results):
            status = r["status"]
            color  = QColor(_STATUS_COLOR.get(status, _S1))

            cat_item = QTableWidgetItem(f"{r['icon']}  {r['name']}")
            cat_item.setForeground(QColor(_TEXT))
            cat_item.setData(Qt.UserRole, r)
            self._audit_table.setItem(i, 0, cat_item)

            st_item = QTableWidgetItem(_STATUS_LABEL.get(status, status))
            st_item.setForeground(color)
            st_item.setFont(QFont("", -1, QFont.Bold))
            self._audit_table.setItem(i, 1, st_item)

            cnt_item = QTableWidgetItem(str(r["match_count"]))
            cnt_item.setTextAlignment(Qt.AlignCenter)
            cnt_item.setForeground(QColor(_GREEN if r["match_count"] else _OV0))
            self._audit_table.setItem(i, 2, cnt_item)

            platforms = list({p.get("platform", "") for p in r["matching_policies"] if p.get("platform")})
            plat_item = QTableWidgetItem(", ".join(platforms[:2]) or "—")
            plat_item.setForeground(QColor(_SUB))
            self._audit_table.setItem(i, 3, plat_item)

            types = list({p.get("control_type", "") for p in r["matching_policies"] if p.get("control_type")})
            type_item = QTableWidgetItem(", ".join(types[:2]) or "—")
            type_item.setForeground(QColor(_SUB))
            self._audit_table.setItem(i, 4, type_item)

            if status == "missing":
                for col in range(5):
                    it = self._audit_table.item(i, col)
                    if it:
                        it.setBackground(QColor("#2d1f2d"))

        self._audit_table.setSortingEnabled(True)

    def _on_audit_row_selected(self):
        row = self._audit_table.currentRow()
        if row < 0:
            return
        item = self._audit_table.item(row, 0)
        if not item:
            return
        r = item.data(Qt.UserRole)
        if not r:
            return

        lines = [
            f"{'═' * 60}",
            f"  {r['icon']}  {r['name']}   [{_STATUS_LABEL.get(r['status'], r['status'])}]",
            f"{'═' * 60}",
            "",
            "Descrizione:",
            f"  {r['description']}",
            "",
        ]
        if r["matching_policies"]:
            lines.append("Policy abbinate:")
            for p in r["matching_policies"]:
                lines.append(f"  •  [{p['control_type']}]  {p['display_name']}")
        else:
            lines.append("Nessuna policy trovata per questa categoria.")
            lines.append("")
            lines.append("Raccomandazione:")
            lines.append(f"  {r['recommendation']}")

        lines += ["", f"Documentazione: {r['reference_url']}"]
        self._audit_detail.setPlainText("\n".join(lines))

    def _update_advisor(self, results: list[dict]):
        # Rimuovi widget esistenti (eccetto lo stretch in fondo)
        while self._advisor_layout.count() > 1:
            item = self._advisor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        actionable = [r for r in results if r["status"] in ("missing", "partial")]

        if not actionable:
            empty = QLabel("🎉  Tutte le categorie sono coperte. Ottimo lavoro!")
            empty.setStyleSheet(f"color:{_GREEN}; font-size:14px; padding:20px;")
            empty.setAlignment(Qt.AlignCenter)
            self._advisor_layout.insertWidget(0, empty)
            return

        ordered = (
            [r for r in actionable if r["status"] == "missing"] +
            [r for r in actionable if r["status"] == "partial"]
        )
        for idx, r in enumerate(ordered):
            card = _CategoryCard(r, self._advisor_inner)
            self._advisor_layout.insertWidget(idx, card)

    def _update_report(self, results: list[dict]):
        from app.analytics.security_baseline import compute_score
        score = compute_score(results)
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║          INTUNE DASHBOARD — SECURITY BASELINE REPORT         ║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"  Data/ora audit:   {ts}",
            f"  Security Score:   {score['score_pct']}%",
            f"  Categorie totali: {score['total']}",
            f"  ✅ Coperti:       {score['covered']}",
            f"  ⚠️  Parziali:     {score['partial']}",
            f"  ❌ Mancanti:      {score['missing']}",
            "",
            "─" * 66,
            "  DETTAGLIO CATEGORIE",
            "─" * 66,
        ]
        for r in results:
            icon = _STATUS_ICON.get(r["status"], "?")
            lines.append("")
            lines.append(f"  {icon}  {r['name']}")
            if r["matching_policies"]:
                for p in r["matching_policies"]:
                    lines.append(f"       •  {p['display_name']} ({p['control_type']})")
            else:
                lines.append("       [Nessuna policy trovata]")
                rec = r["recommendation"]
                rec_short = (rec[:90] + "…") if len(rec) > 90 else rec
                lines.append(f"       → {rec_short}")

        lines += [
            "",
            "─" * 66,
            "  PROSSIMI PASSI",
            "─" * 66,
            "",
        ]
        missing = [r for r in results if r["status"] == "missing"]
        if missing:
            lines.append("  Categorie prioritarie da implementare:")
            for r in missing:
                lines.append(f"  ❌  {r['name']}")
                lines.append(f"      {r['reference_url']}")
        else:
            lines.append("  ✅ Nessuna categoria completamente mancante.")

        self._report_text.setPlainText("\n".join(lines))

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._audit_results:
            QMessageBox.information(self, "Nessun dato", "Esegui prima un audit.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta Security Report CSV",
            f"security_audit_{ts}.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "name", "icon", "status", "match_count",
                    "matched_policies", "recommendation", "reference_url",
                ])
                writer.writeheader()
                for r in self._audit_results:
                    writer.writerow({
                        "name": r["name"],
                        "icon": r["icon"],
                        "status": r["status"],
                        "match_count": r["match_count"],
                        "matched_policies": " | ".join(
                            p["display_name"] for p in r["matching_policies"]
                        ),
                        "recommendation": r["recommendation"],
                        "reference_url": r["reference_url"],
                    })
            QMessageBox.information(self, "Export completato", f"Salvato in:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export fallito", str(exc))

    def _copy_report(self):
        text = self._report_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copiato", "Report copiato negli appunti.")
        else:
            QMessageBox.information(self, "Nessun dato", "Esegui prima un audit.")

    def refresh(self):
        """Chiamato da MainWindow alla navigazione — nessun auto-run."""
        pass
