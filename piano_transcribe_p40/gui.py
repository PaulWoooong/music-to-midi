#!/usr/bin/env python3
"""Piano-only desktop GUI for the portable P40 bundle.

The window is a thin PyQt6 front end over the same transcription CLI used by
``run.sh``.  It launches the bundled executable as a child process so the GUI
itself never imports PyTorch and stays responsive while CUDA work runs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QTextCursor
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

ENGINES = (
    ("transkun", "TransKun"),
    ("transkun_v2_aug", "TransKun V2 Aug（钢琴 + 踏板）"),
    ("aria_amt", "Aria-AMT"),
    ("bytedance_pedal", "ByteDance Piano（带踏板）"),
)

AUDIO_FILTER = (
    "音频/视频 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus *.wma "
    "*.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*)"
)

PROGRESS_RE = re.compile(r"^\[\s*([\d.]+)%\]\s*(.*)$")
DONE_RE = re.compile(r"^Done:\s*(.+)$")
NOTES_RE = re.compile(r"^Notes:\s*(.+)$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_child_command(args: list[str]) -> tuple[list[str], str]:
    """Return the command that runs the CLI in this environment."""

    if getattr(sys, "frozen", False):
        # The frozen executable dispatches to transcription when it receives
        # arguments; without arguments it opens this GUI again.
        return [sys.executable, *args], str(Path(sys.executable).resolve().parent)
    # ``-m`` puts the repository root on sys.path for the child process.
    return [sys.executable, "-m", "piano_transcribe_p40.portable_entry", *args], str(_repo_root())


class TranscriptionThread(QThread):
    """Run the CLI child process and stream its stdout into the UI."""

    line_received = pyqtSignal(str)
    progress_changed = pyqtSignal(float)
    status_changed = pyqtSignal(str)
    completed = pyqtSignal(int)

    def __init__(self, args: list[str], parent=None) -> None:
        super().__init__(parent)
        self._args = list(args)
        self._process: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def run(self) -> None:  # noqa: D401 - QThread entry point
        command, cwd = build_child_command(self._args)
        env = dict(os.environ)
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self._process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:  # pragma: no cover - startup failure
            self.line_received.emit(f"无法启动转写进程: {exc}")
            self.completed.emit(1)
            return

        assert self._process.stdout is not None
        for raw_line in self._process.stdout:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            self.line_received.emit(line)
            match = PROGRESS_RE.match(line)
            if match:
                self.progress_changed.emit(float(match.group(1)))
                self.status_changed.emit(match.group(2).strip())
                continue
            done = DONE_RE.match(line)
            if done:
                self.status_changed.emit(f"完成：{done.group(1)}")
                continue
            notes = NOTES_RE.match(line)
            if notes:
                self.status_changed.emit(f"完成（{notes.group(1)}）")

        exit_code = self._process.wait()
        if self._cancelled and exit_code != 0:
            self.status_changed.emit("已取消")
        self.completed.emit(exit_code)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MusicToMidi 钢琴转录（P40 便携版）")
        self.resize(860, 660)
        self._thread: TranscriptionThread | None = None
        self._last_output: Path | None = None
        self._build_ui()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("钢琴音频转 MIDI")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        subtitle = QLabel(
            "内置 TransKun / TransKun V2 Aug / Aria-AMT / ByteDance 四个引擎；"
            "模型与 ffmpeg 已随包提供，无需联网。"
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        files_box = QGroupBox("输入与输出")
        files_form = QFormLayout(files_box)
        files_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择音频或视频文件（wav / mp3 / mp4 / flac …）")
        input_button = QPushButton("浏览…")
        input_button.clicked.connect(self._choose_input)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(input_button)
        files_form.addRow("输入文件：", input_row)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(Path.home() / "MusicToMidi-Output"))
        output_button = QPushButton("浏览…")
        output_button.clicked.connect(self._choose_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_button)
        files_form.addRow("输出目录：", output_row)
        root.addWidget(files_box)

        settings_box = QGroupBox("转写设置")
        settings_form = QFormLayout(settings_box)
        settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.engine_combo = QComboBox()
        for engine_id, label in ENGINES:
            self.engine_combo.addItem(label, engine_id)
        settings_form.addRow("引擎：", self.engine_combo)

        self.bf16_combo = QComboBox()
        self.bf16_combo.addItem("auto（P40 自动回退 FP32）", "auto")
        self.bf16_combo.addItem("fp32（强制 32-bit 浮点）", "fp32")
        self.bf16_combo.addItem("bf16（支持时使用 BF16）", "bf16")
        settings_form.addRow("CUDA 精度：", self.bf16_combo)

        tempo_row = QHBoxLayout()
        self.tempo_combo = QComboBox()
        self.tempo_combo.addItem("自动检测（Beat This）", "auto")
        self.tempo_combo.addItem("固定 120 BPM（最快）", "fixed")
        self.tempo_combo.addItem("手动指定 BPM", "manual")
        self.tempo_combo.currentIndexChanged.connect(self._update_tempo_state)
        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(20.0, 300.0)
        self.bpm_spin.setDecimals(1)
        self.bpm_spin.setValue(120.0)
        self.bpm_spin.setEnabled(False)
        self.bpm_spin.setSuffix(" BPM")
        tempo_row.addWidget(self.tempo_combo, 1)
        tempo_row.addWidget(self.bpm_spin)
        settings_form.addRow("速度：", tempo_row)

        device_row = QHBoxLayout()
        self.cpu_check = QCheckBox("使用 CPU（无兼容 GPU 时）")
        self.gpu_spin = QSpinBox()
        self.gpu_spin.setRange(0, 15)
        self.gpu_spin.setPrefix("GPU ")
        device_row.addWidget(self.cpu_check, 1)
        device_row.addWidget(self.gpu_spin)
        settings_form.addRow("设备：", device_row)
        root.addWidget(settings_box)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始转写")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_button = QPushButton("打开输出目录")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_output)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        action_row.addWidget(self.open_button)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.status_label = QLabel("就绪。建议先运行 p40-check.sh 确认 GPU 与模型。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Monospace", 9))
        self.log_view.setPlaceholderText("转写日志将显示在这里…")
        root.addWidget(self.log_view, 1)

    # ------------------------------------------------------------------ actions
    def _update_tempo_state(self) -> None:
        self.bpm_spin.setEnabled(self.tempo_combo.currentData() == "manual")

    def _choose_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择音频/视频", str(Path.home()), AUDIO_FILTER)
        if path:
            self.input_edit.setText(path)

    def _choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _collect_args(self) -> list[str] | None:
        input_path = Path(self.input_edit.text().strip()).expanduser()
        if not self.input_edit.text().strip() or not input_path.is_file():
            QMessageBox.warning(self, "缺少输入", "请选择一个存在的音频或视频文件。")
            return None

        output_text = self.output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "缺少输出目录", "请选择输出目录。")
            return None

        args = [
            str(input_path),
            "-o",
            str(Path(output_text).expanduser()),
            "-e",
            str(self.engine_combo.currentData()),
            "--cuda-bf16-policy",
            str(self.bf16_combo.currentData()),
        ]

        tempo_mode = self.tempo_combo.currentData()
        if tempo_mode == "fixed":
            args += ["--skip-beat-detect"]
        elif tempo_mode == "manual":
            args += ["--bpm", f"{self.bpm_spin.value():.1f}"]

        if self.cpu_check.isChecked():
            args += ["--cpu"]
        elif self.gpu_spin.value() > 0:
            args += ["--gpu-device", str(self.gpu_spin.value())]
        return args

    def _start(self) -> None:
        args = self._collect_args()
        if args is None:
            return

        self.log_view.clear()
        self.progress.setValue(0)
        self.status_label.setText("正在启动转写进程…")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self._last_output = None

        self._thread = TranscriptionThread(args, self)
        self._thread.line_received.connect(self._append_log)
        self._thread.progress_changed.connect(self._set_progress)
        self._thread.status_changed.connect(self.status_label.setText)
        self._thread.completed.connect(self._on_completed)
        self._thread.start()

    def _cancel(self) -> None:
        if self._thread is not None:
            self.status_label.setText("正在取消…")
            self.cancel_button.setEnabled(False)
            self._thread.cancel()

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        done = DONE_RE.match(line)
        if done:
            self._last_output = Path(done.group(1))

    def _set_progress(self, value: float) -> None:
        self.progress.setValue(max(0, min(100, int(round(value)))))

    def _on_completed(self, exit_code: int) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if exit_code == 0:
            self.progress.setValue(100)
            if self._last_output is not None:
                self.status_label.setText(f"完成：{self._last_output}")
                self.open_button.setEnabled(True)
            else:
                self.status_label.setText("完成。")
        elif self.status_label.text() != "已取消":
            self.status_label.setText(f"转写失败（退出码 {exit_code}），请查看日志。")
        self._thread = None

    def _open_output(self) -> None:
        target = self._last_output.parent if self._last_output else Path(self.output_edit.text())
        if target.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._thread is not None and self._thread.isRunning():
            answer = QMessageBox.question(
                self,
                "转写仍在进行",
                "关闭窗口会终止当前转写，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._thread.cancel()
            self._thread.wait(5000)
        event.accept()


def render_screenshot(path: str) -> int:
    """Offscreen render used by build-time smoke tests."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    app.processEvents()
    pixmap = window.grab()
    ok = pixmap.save(path)
    window.close()
    print(f"screenshot: {path} ({'ok' if ok else 'failed'})")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--screenshot" in args:
        index = args.index("--screenshot")
        target = args[index + 1] if index + 1 < len(args) else "gui-screenshot.png"
        return render_screenshot(target)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("MusicToMidi 钢琴转录")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
