from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .fenix import ConversionBlocked, build_rejection_report, convert
from .source import load_naip
from .update_manager import check_prerelease
from .validation import validate_candidate
from .version import __version__


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"424 到 Fenix 导航数据转换器 · {__version__} 测试版")
        self.root.geometry("940x680")
        self.root.minsize(780, 560)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.official = tk.StringVar(value=r"C:\ProgramData\Fenix\Navdata")
        self.naip = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.cwd() / "output" / "fenix-2608-test"))
        self.reference = tk.StringVar()
        self.status = tk.StringVar(value="等待输入")
        self._build()
        self.root.after(100, self._drain)
        self.root.after(700, self._check_update)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"), foreground="#E7EEF7")
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9), foreground="#A7B8C9")
        self.root.configure(bg="#10202D")
        header = tk.Frame(self.root, bg="#10202D", padx=22, pady=18)
        header.pack(fill=tk.X)
        ttk.Label(header, text="424 → FENIX", style="Title.TLabel", background="#10202D").pack(anchor=tk.W)
        ttk.Label(header, text="官方全球模板与 NAIP 中国补丁合成 · 所有结果均为测试候选", style="Sub.TLabel", background="#10202D").pack(anchor=tk.W, pady=(3, 0))
        notice = tk.Frame(self.root, bg="#F5D66E", padx=14, pady=9)
        notice.pack(fill=tk.X, padx=22)
        tk.Label(notice, text="测试版不会直接写入游戏。程序图表无法可靠解析时，候选会被阻止部署。", bg="#F5D66E", fg="#27333D", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
        form = ttk.LabelFrame(self.root, text=" 输入与候选输出 ", padding=12)
        form.pack(fill=tk.X, padx=22, pady=12)
        self._path(form, 0, "官方 Fenix Navdata", self.official, True)
        self._path(form, 1, "2608 NAIP 数据根目录", self.naip, True)
        self._path(form, 2, "候选输出目录", self.output, False)
        self._path(form, 3, "本地参考成品（可选）", self.reference, True)
        actions = ttk.Frame(self.root, padding=(22, 4))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="生成候选", command=self._convert).pack(side=tk.LEFT)
        ttk.Button(actions, text="校验候选", command=self._validate).pack(side=tk.LEFT, padx=8)
        ttk.Button(actions, text="检查测试更新", command=self._check_update).pack(side=tk.LEFT)
        ttk.Label(actions, textvariable=self.status).pack(side=tk.RIGHT)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill=tk.X, padx=22, pady=(5, 8))
        frame = ttk.LabelFrame(self.root, text=" 运行报告 ", padding=6)
        frame.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 18))
        self.log = tk.Text(frame, bg="#0B141D", fg="#C7D6E5", insertbackground="#C7D6E5", font=("Consolas", 10), relief=tk.FLAT, wrap=tk.WORD, state=tk.DISABLED)
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _path(self, parent, row: int, text: str, value: tk.StringVar, directory: bool) -> None:
        ttk.Label(parent, text=text, width=22, anchor=tk.E).grid(row=row, column=0, sticky=tk.E, pady=4)
        ttk.Entry(parent, textvariable=value).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4)
        ttk.Button(parent, text="浏览", command=lambda: self._browse(value, directory)).grid(row=row, column=2, pady=4)
        parent.columnconfigure(1, weight=1)

    def _browse(self, value: tk.StringVar, directory: bool) -> None:
        selected = filedialog.askdirectory() if directory else filedialog.asksaveasfilename()
        if selected:
            value.set(selected)

    def _write(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _run(self, work) -> None:
        self.progress.start(12)
        threading.Thread(target=lambda: self.events.put(("done", work())), daemon=True).start()

    def _convert(self) -> None:
        def work():
            model = load_naip(Path(self.naip.get()))
            try:
                return convert(Path(self.official.get()), model, Path(self.output.get()), Path(self.reference.get()) if self.reference.get() else None)
            except ConversionBlocked as error:
                report = build_rejection_report(model, Path(self.output.get()))
                return {"blocked": str(error), "report": str(report)}
        self.status.set("正在解析输入")
        self._run(work)

    def _validate(self) -> None:
        self.status.set("正在校验候选")
        self._run(lambda: validate_candidate(Path(self.output.get()), Path(self.reference.get()) if self.reference.get() else None))

    def _check_update(self) -> None:
        threading.Thread(target=lambda: self.events.put(("update", check_prerelease())), daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "done":
                    self.progress.stop(); self.status.set("完成")
                    self._write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
                elif kind == "update" and payload:
                    self._write(f"发现测试更新 v{payload.version}，请从 GitHub 预发布页下载并校验。")
        except queue.Empty:
            pass
        except Exception as error:
            self.progress.stop(); self.status.set("失败"); self._write(f"失败: {error}")
        self.root.after(100, self._drain)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
