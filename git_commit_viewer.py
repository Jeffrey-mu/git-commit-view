import csv
import os
import sys
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional
import re

from PyQt6.QtCore import Qt, QDate, QSettings
from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "GitCommitViewer"
APP_VERSION = "0.1.0"

APP_ICON_XPM = [
    "32 32 6 1",
    " 	c None",
    ".	c #0E0F12",
    "+	c #FFFFFF",
    "@	c #22C55E",
    "#	c #A855F7",
    "$	c #60A5FA",
    "................................",
    "................................",
    "..............+++++.............",
    "...........+++++++++++..........",
    ".........+++++++@@++++++........",
    "........++++++@@@@@++++++.......",
    ".......++++++@@@@@@@++++++......",
    "......++++++@@@@.@@@@++++++.....",
    "......+++++@@@@...@@@@+++++.....",
    ".....+++++@@@@.....@@@@+++++....",
    ".....++++@@@@.......@@@@++++....",
    ".....++++@@@.........@@@++++....",
    ".....++++++...........+++++.....",
    ".....+++++++.........++++++.....",
    "......+++++++.......++++++......",
    ".......+++++++.....++++++.......",
    "........++++++.....+++++........",
    ".........++++.......++++........",
    "..........+++.......+++.........",
    "...........++.......++..........",
    "...........+++.....+++..........",
    "..........+++++...+++++.........",
    ".........++++$$+++$$++++........",
    "........++++$$$$+$$$$++++.......",
    ".......++++$$$$$+$$$$$++++......",
    "......++++$$$$$$+$$$$$$++++.....",
    "......++++$$$$$$+$$$$$$++++.....",
    "......+++++$$$$$+$$$$$+++++.....",
    ".......+++++$$$$+$$$$+++++......",
    "........++++++$$+$$++++++.......",
    "..........+++++#+#+#+#++++......",
    "................................",
]


def get_app_icon() -> QIcon:
    pixmap = QPixmap(APP_ICON_XPM)
    return QIcon(pixmap)


@dataclass(frozen=True)
class CommitItem:
    hash_full: str
    hash_short: str
    author: str
    author_email: str
    date: datetime
    subject: str
    message_full: str
    parents: str


class CommitDetailDialog(QDialog):
    def __init__(self, commit: CommitItem, repo_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("提交详情")
        self.setMinimumSize(760, 520)

        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Monaco", 11))

        local_dt = commit.date
        if local_dt.tzinfo is not None:
            local_dt = local_dt.astimezone()

        shortstat = ""
        try:
            out = subprocess.check_output(
                ["git", "-C", repo_path, "show", "-s", "--format=", "--shortstat", commit.hash_full],
                encoding="utf-8",
                stderr=subprocess.STDOUT,
            ).strip()
            if out:
                shortstat = out
        except Exception:
            shortstat = ""

        detail = "\n".join(
            [
                f"短哈希：{commit.hash_short}",
                f"完整哈希：{commit.hash_full}",
                f"作者：{commit.author} <{commit.author_email}>",
                f"时间：{local_dt.strftime('%Y-%m-%d %H:%M:%S')}",
                f"父提交：{commit.parents or '无'}",
                f"统计：{shortstat or '无'}",
                "",
                "完整信息：",
                commit.message_full,
            ]
        )
        text_edit.setText(detail)
        layout.addWidget(text_edit)
        self.setLayout(layout)


class ChecklistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("验收清单")
        self.setMinimumSize(740, 520)

        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Monaco", 11))

        content = "\n".join(
            [
                "1. 选择一个包含 .git 的仓库目录，点击“刷新”。",
                "2. 表格应显示：序号、短哈希、作者、时间、信息。",
                "3. 输入作者/关键词并设置日期范围，点击“筛选”，状态栏显示匹配数量。",
                "4. 点击“日期升序/降序”，排序后第一行时间符合预期。",
                "5. 双击任意行，弹窗显示完整哈希与完整提交信息。",
                "6. 点击“导出CSV”，用 Excel/Numbers 打开不乱码（UTF-8 带 BOM）。",
                "7. 输入一个非仓库目录，提示“不是 Git 仓库”。",
                "8. 在未安装 Git 的环境，提示“未找到 Git 命令”。",
                "9. 打包命令：pyinstaller -F -w --name GitCommitViewer git_commit_viewer.py",
            ]
        )
        text_edit.setText(content)
        layout.addWidget(text_edit)
        self.setLayout(layout)


class GitCommitViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Git 提交查看工具（Windows/macOS）")
        self.setMinimumSize(1100, 720)
        self.setWindowIcon(get_app_icon())

        self.settings = QSettings(APP_NAME, APP_NAME)
        self.recent_repos: List[str] = []
        self.all_commits: List[CommitItem] = []
        self.filtered_commits: List[CommitItem] = []
        self.current_repo_path: str = ""

        self._init_ui()

        self._load_settings()
        self.load_commits(show_errors=False)

    def _default_start_date(self) -> QDate:
        return QDate.currentDate().addDays(-5)

    def _normalize_repo_path(self, repo_path: str) -> str:
        s = (repo_path or "").strip()
        if not s:
            return ""
        try:
            return str(Path(s))
        except Exception:
            return s

    def _repo_path_key(self, repo_path: str) -> str:
        p = self._normalize_repo_path(repo_path)
        if os.name == "nt":
            return p.lower()
        return p

    def _get_repo_path(self) -> str:
        return self._normalize_repo_path(self.repo_path_combo.currentText())

    def _set_repo_path(self, repo_path: str):
        p = self._normalize_repo_path(repo_path)
        if not p:
            return
        self.repo_path_combo.setCurrentText(p)
        self._remember_repo(p)

    def _remember_repo(self, repo_path: str):
        p = self._normalize_repo_path(repo_path)
        if not p:
            return
        key = self._repo_path_key(p)
        new_list: List[str] = [p]
        seen = {key}
        for item in self.recent_repos:
            k = self._repo_path_key(item)
            if k in seen:
                continue
            seen.add(k)
            new_list.append(item)
            if len(new_list) >= 20:
                break
        self.recent_repos = new_list
        self.repo_path_combo.blockSignals(True)
        try:
            self.repo_path_combo.clear()
            self.repo_path_combo.addItems(self.recent_repos)
            self.repo_path_combo.setCurrentText(p)
        finally:
            self.repo_path_combo.blockSignals(False)
        self.settings.setValue("recent_repos", self.recent_repos)
        self.settings.setValue("repo_path", p)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self._init_menu()

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("仓库路径"))
        self.repo_path_combo = QComboBox()
        self.repo_path_combo.setEditable(True)
        self.repo_path_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.repo_path_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        if self.repo_path_combo.lineEdit() is not None:
            self.repo_path_combo.lineEdit().setPlaceholderText("请选择包含 .git 的目录")
            self.repo_path_combo.lineEdit().returnPressed.connect(self.load_commits)
        self.btn_path = QPushButton("选择")
        self.btn_refresh = QPushButton("刷新")
        path_layout.addWidget(self.repo_path_combo)
        path_layout.addWidget(self.btn_path)
        path_layout.addWidget(self.btn_refresh)
        main_layout.addLayout(path_layout)

        export_layout = QHBoxLayout()
        export_layout.addWidget(QLabel("导出目录"))
        self.export_dir_edit = QLineEdit()
        self.export_dir_edit.setPlaceholderText("选择导出保存目录")
        self.btn_export_dir = QPushButton("选择")
        export_layout.addWidget(self.export_dir_edit)
        export_layout.addWidget(self.btn_export_dir)
        main_layout.addLayout(export_layout)

        filter_layout = QHBoxLayout()
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("作者（模糊匹配）")
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("提交信息（关键词）")
        self.start_date = QDateEdit(self._default_start_date())
        self.start_date.setCalendarPopup(True)
        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.btn_filter = QPushButton("筛选")
        self.btn_clear = QPushButton("清空")
        self.btn_asc = QPushButton("日期升序")
        self.btn_desc = QPushButton("日期降序")
        self.btn_export = QPushButton("导出CSV")

        self.keyword_edit.returnPressed.connect(self.do_filter)
        self.author_edit.returnPressed.connect(self.do_filter)

        filter_layout.addWidget(QLabel("作者"))
        filter_layout.addWidget(self.author_edit)
        filter_layout.addWidget(QLabel("关键词"))
        filter_layout.addWidget(self.keyword_edit)
        filter_layout.addWidget(QLabel("开始"))
        filter_layout.addWidget(self.start_date)
        filter_layout.addWidget(QLabel("结束"))
        filter_layout.addWidget(self.end_date)
        filter_layout.addWidget(self.btn_filter)
        filter_layout.addWidget(self.btn_clear)
        filter_layout.addWidget(self.btn_asc)
        filter_layout.addWidget(self.btn_desc)
        filter_layout.addWidget(self.btn_export)
        main_layout.addLayout(filter_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["序号", "哈希", "作者", "时间", "信息"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.show_detail)
        main_layout.addWidget(self.table)

        self.btn_path.clicked.connect(self.select_folder)
        self.btn_refresh.clicked.connect(self.load_commits)
        self.btn_filter.clicked.connect(self.do_filter)
        self.btn_clear.clicked.connect(self.clear_filter)
        self.btn_asc.clicked.connect(lambda: self.sort_commits(asc=True))
        self.btn_desc.clicked.connect(lambda: self.sort_commits(asc=False))
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export_dir.clicked.connect(self.select_export_folder)
        self.repo_path_combo.activated.connect(lambda _idx: self.load_commits())

        self.status = self.statusBar()
        self.status.showMessage("就绪")

    def _init_menu(self):
        menu_bar = self.menuBar()

        menu_file = menu_bar.addMenu("文件")
        action_open = QAction("选择仓库…", self)
        action_open.setShortcut(QKeySequence.StandardKey.Open)
        action_open.triggered.connect(self.select_folder)
        menu_file.addAction(action_open)

        action_refresh = QAction("刷新", self)
        action_refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        action_refresh.triggered.connect(self.load_commits)
        menu_file.addAction(action_refresh)

        menu_file.addSeparator()
        action_export = QAction("导出CSV…", self)
        action_export.setShortcut(QKeySequence("Ctrl+E"))
        action_export.triggered.connect(self.export_csv)
        menu_file.addAction(action_export)

        menu_file.addSeparator()
        action_quit = QAction("退出", self)
        action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        action_quit.triggered.connect(self.close)
        menu_file.addAction(action_quit)

        menu_help = menu_bar.addMenu("帮助")
        action_checklist = QAction("验收清单", self)
        action_checklist.triggered.connect(self.show_checklist)
        menu_help.addAction(action_checklist)

        action_about = QAction("关于", self)
        action_about.triggered.connect(self.show_about)
        menu_help.addAction(action_about)

    def show_about(self):
        QMessageBox.information(
            self,
            "关于",
            f"Git 提交查看工具\n版本：{APP_VERSION}\n\n"
            "功能：查看、筛选、排序、导出提交记录；双击查看详情。\n"
            "依赖：系统 Git + PyQt6",
        )

    def show_checklist(self):
        dlg = ChecklistDialog(self)
        dlg.exec()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择仓库目录", self._get_repo_path() or str(Path.home()))
        if folder:
            self._set_repo_path(folder)
            self.load_commits()

    def select_export_folder(self):
        current = self.export_dir_edit.text().strip()
        base_dir = current if current else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择导出目录", base_dir)
        if folder:
            self.export_dir_edit.setText(folder)
            self.settings.setValue("export_dir", folder)

    def _load_settings(self):
        repo_path = str(self.settings.value("repo_path", "") or "").strip()
        recent = self.settings.value("recent_repos", [])
        export_dir = str(self.settings.value("export_dir", "") or "").strip()

        recent_list: List[str] = []
        if isinstance(recent, list):
            recent_list = [self._normalize_repo_path(x) for x in recent if str(x).strip()]
        elif isinstance(recent, str) and recent.strip():
            recent_list = [self._normalize_repo_path(recent)]

        if repo_path:
            self.recent_repos = [self._normalize_repo_path(repo_path)] + [
                x for x in recent_list if self._repo_path_key(x) != self._repo_path_key(repo_path)
            ]
        else:
            self.recent_repos = recent_list

        self.recent_repos = [x for x in self.recent_repos if x]
        if not self.recent_repos:
            self.recent_repos = [str(Path.home())]

        self.repo_path_combo.clear()
        self.repo_path_combo.addItems(self.recent_repos)
        if repo_path:
            self.repo_path_combo.setCurrentText(self._normalize_repo_path(repo_path))
        else:
            self.repo_path_combo.setCurrentText(self.recent_repos[0])

        if export_dir:
            self.export_dir_edit.setText(export_dir)
        else:
            self.export_dir_edit.setText(str(Path.home()))

    def closeEvent(self, event):
        self.settings.setValue("repo_path", self._get_repo_path())
        self.settings.setValue("recent_repos", self.recent_repos)
        self.settings.setValue("export_dir", self.export_dir_edit.text().strip())
        super().closeEvent(event)

    def _run_git(self, args: List[str], repo_path: str) -> str:
        try:
            out = subprocess.check_output(
                ["git", "-C", repo_path, *args],
                encoding="utf-8",
                stderr=subprocess.STDOUT,
            )
            return out
        except FileNotFoundError as e:
            raise RuntimeError("未找到 Git 命令，请先安装 Git 并配置环境变量。") from e
        except subprocess.CalledProcessError as e:
            msg = (e.output or "").strip()
            if msg:
                raise RuntimeError(f"Git 执行失败：{msg}") from e
            raise RuntimeError("Git 执行失败。") from e

    def _is_git_repo(self, repo_path: str) -> bool:
        try:
            out = self._run_git(["rev-parse", "--is-inside-work-tree"], repo_path).strip().lower()
            return out == "true"
        except Exception:
            return False

    def _parse_git_date(self, date_s: str) -> datetime:
        s = date_s.strip()
        s = re.sub(r"\s+([+-]\d{2})(\d{2})$", r" \1:\2", s)
        s = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.now()

    def get_commits(self, repo_path: str) -> List[CommitItem]:
        out = self._run_git(
            [
                "log",
                "--pretty=format:%H%x1f%an%x1f%ae%x1f%aI%x1f%P%x1f%B%x1e",
            ],
            repo_path,
        )
        commits: List[CommitItem] = []
        for record in out.split("\x1e"):
            record = record.strip("\n")
            if not record:
                continue
            parts = record.split("\x1f", 5)
            if len(parts) != 6:
                continue
            h, author, author_email, date_s, parents, body = parts
            dt = self._parse_git_date(date_s)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            body = body.replace("\r\n", "\n").rstrip("\n")
            subject = ""
            for line in body.split("\n"):
                if line.strip():
                    subject = line.strip()
                    break
            commits.append(
                CommitItem(
                    hash_full=h,
                    hash_short=h[:8],
                    author=author.strip(),
                    author_email=author_email.strip(),
                    date=dt,
                    subject=subject,
                    message_full=body.strip(),
                    parents=parents.strip(),
                )
            )
        return commits

    def load_commits(self, show_errors: bool = True):
        repo_path = self._get_repo_path()
        if not repo_path:
            return

        p = Path(repo_path)
        if not p.exists():
            if show_errors:
                QMessageBox.warning(self, "提示", "路径不存在，请选择有效目录。")
            return

        if not self._is_git_repo(repo_path):
            if show_errors:
                QMessageBox.warning(self, "提示", "该目录不是 Git 仓库，请选择包含 .git 的目录。")
            self.all_commits = []
            self.filtered_commits = []
            self.render_table()
            self.status.showMessage("未加载：不是 Git 仓库")
            return

        self.status.showMessage("加载中…")
        try:
            self.all_commits = self.get_commits(repo_path)
        except Exception as e:
            self.all_commits = []
            self.filtered_commits = []
            self.render_table()
            if show_errors:
                QMessageBox.warning(self, "错误", str(e))
            self.status.showMessage("加载失败")
            return

        self.current_repo_path = repo_path
        self._remember_repo(repo_path)
        self.filtered_commits = list(self.all_commits)
        self.render_table()
        self.status.showMessage(f"加载完成：共 {len(self.all_commits)} 条记录")

    def render_table(self):
        self.table.setRowCount(0)
        for i, c in enumerate(self.filtered_commits):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(c.hash_short))
            self.table.setItem(row, 2, QTableWidgetItem(c.author))

            dt = c.date
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            self.table.setItem(row, 3, QTableWidgetItem(dt.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(row, 4, QTableWidgetItem(c.subject))
            for col in range(5):
                item = self.table.item(row, col)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

    def _apply_filters(self, items: Iterable[CommitItem]) -> List[CommitItem]:
        author = self.author_edit.text().strip().lower()
        keyword = self.keyword_edit.text().strip().lower()
        s_date = self.start_date.date().toPyDate()
        e_date = self.end_date.date().toPyDate()

        res: List[CommitItem] = []
        for c in items:
            if author and author not in c.author.lower() and author not in c.author_email.lower():
                continue
            if keyword and keyword not in c.subject.lower() and keyword not in c.message_full.lower():
                continue
            c_date = c.date.date()
            if not (s_date <= c_date <= e_date):
                continue
            res.append(c)
        return res

    def do_filter(self):
        if not self.all_commits:
            return
        self.filtered_commits = self._apply_filters(self.all_commits)
        self.render_table()
        self.status.showMessage(f"筛选完成：匹配 {len(self.filtered_commits)} 条")

    def clear_filter(self):
        self.author_edit.clear()
        self.keyword_edit.clear()
        self.start_date.setDate(self._default_start_date())
        self.end_date.setDate(QDate.currentDate())
        self.filtered_commits = list(self.all_commits)
        self.render_table()
        self.status.showMessage("已清空筛选")

    def sort_commits(self, asc: bool):
        if not self.filtered_commits:
            return
        self.filtered_commits.sort(key=lambda x: x.date, reverse=not asc)
        self.render_table()
        self.status.showMessage("已按日期排序")

    def _commit_by_row(self, row: int) -> Optional[CommitItem]:
        if 0 <= row < len(self.filtered_commits):
            return self.filtered_commits[row]
        return None

    def show_detail(self, row: int, _col: int):
        commit = self._commit_by_row(row)
        if commit is None:
            return
        repo_path = self.current_repo_path or self._get_repo_path()
        dlg = CommitDetailDialog(commit, repo_path, self)
        dlg.exec()

    def export_csv(self):
        if not self.filtered_commits:
            QMessageBox.information(self, "提示", "没有可导出的记录。")
            return

        default_name = f"commits_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        export_dir = self.export_dir_edit.text().strip()
        default_path = default_name
        if export_dir:
            try:
                p = Path(export_dir)
                if p.exists():
                    default_path = str(p / default_name)
            except Exception:
                default_path = default_name

        path, _ = QFileDialog.getSaveFileName(self, "保存CSV", default_path, "CSV 文件 (*.csv)")
        if not path:
            return

        try:
            parent_dir = str(Path(path).parent)
            if parent_dir:
                self.export_dir_edit.setText(parent_dir)
                self.settings.setValue("export_dir", parent_dir)

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "短哈希", "完整哈希", "作者", "邮箱", "时间", "父提交", "标题", "完整信息"])
                for i, c in enumerate(self.filtered_commits):
                    dt = c.date
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    writer.writerow(
                        [
                            i + 1,
                            c.hash_short,
                            c.hash_full,
                            c.author,
                            c.author_email,
                            dt.strftime("%Y-%m-%d %H:%M:%S"),
                            c.parents,
                            c.subject,
                            c.message_full,
                        ]
                    )
            QMessageBox.information(self, "成功", "导出完成。")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导出失败：{str(e)}")


def self_test(argv: List[str]) -> int:
    repo_path = str(Path.cwd())
    if len(argv) >= 3:
        repo_path = argv[2]

    try:
        subprocess.check_output(["git", "--version"], encoding="utf-8", stderr=subprocess.STDOUT)
    except FileNotFoundError:
        print("自检失败：未找到 Git 命令。")
        return 2
    except Exception as e:
        print(f"自检失败：Git 不可用：{str(e)}")
        return 2

    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "--is-inside-work-tree"],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        ).strip()
        if out.lower() != "true":
            print("自检失败：该目录不是 Git 仓库。")
            return 3
    except Exception as e:
        print(f"自检失败：无法检测仓库：{str(e)}")
        return 3

    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "log", "-n", "1", "--pretty=format:%H|%an|%ad|%s", "--date=iso-strict"],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        )
        if not out.strip():
            print("自检失败：仓库没有提交记录。")
            return 4
        print("自检通过：Git 可用，仓库有效，可读取提交记录。")
        return 0
    except Exception as e:
        print(f"自检失败：无法读取提交记录：{str(e)}")
        return 4


def main():
    if len(sys.argv) >= 2 and sys.argv[1].strip() == "--self-test":
        raise SystemExit(self_test(sys.argv))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(get_app_icon())
    win = GitCommitViewer()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
