# -*- coding: utf-8 -*-
"""GenshinLyre 主界面"""
import os
import sys
import time
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import lyre_player as lp

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCORE_DIR = os.path.join(BASE_DIR, "scores")


def fmt_time(sec):
    sec = max(0, int(sec))
    return "%d:%02d" % (sec // 60, sec % 60)


class App:
    def __init__(self, root):
        self.root = root
        root.title("GenshinLyre  原神自动弹琴")
        root.geometry("660x560")
        root.resizable(False, False)
        ico = os.path.join(BASE_DIR, "app.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(default=ico)
            except Exception:
                pass

        self.player = lp.Player()
        self.state = "idle"          # idle / countdown / playing / paused
        self.countdown = 0
        self.pending = None          # start / resume
        self._selected = None
        self._files = []
        self.play_started = 0.0
        self.total_s = 1.0
        self._auto_paused = False

        self._build_ui()
        self.refresh_scores()
        root.after(50, self._tick)

    def _build_ui(self):
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=12, pady=10)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="曲目").grid(row=0, column=0, columnspan=3, sticky="w", padx=10)

        self.listbox = tk.Listbox(frm, height=9, activestyle="dotbox",
                                  font=("Microsoft YaHei UI", 10))
        self.listbox.grid(row=1, column=0, columnspan=2, sticky="we", padx=10, pady=2)
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.listbox.yview)
        sb.grid(row=1, column=2, sticky="ns", pady=2)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())
        self.listbox.bind("<Double-Button-1>", lambda e: self.on_main())

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        self.btn_main = ttk.Button(btns, text="▶  开始", width=10, command=self.on_main)
        self.btn_main.pack(side="left", padx=2)
        self.btn_stop = ttk.Button(btns, text="⏹  停止", width=10, command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=2)
        ttk.Button(btns, text="导入琴谱", width=10, command=self.open_import).pack(side="left", padx=10)
        ttk.Button(btns, text="删除曲目", width=10, command=self.on_delete).pack(side="left", padx=4)

        opt = ttk.Frame(frm)
        opt.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        self.var_accomp = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="伴奏", variable=self.var_accomp).pack(side="left", padx=2)
        self.var_autostop = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="切出游戏自动暂停",
                        variable=self.var_autostop).pack(side="left", padx=12)

        spd = ttk.Frame(frm)
        spd.grid(row=4, column=0, columnspan=3, sticky="w", padx=8, pady=2)
        ttk.Label(spd, text="速度").pack(side="left")
        self.var_speed = tk.DoubleVar(value=1.0)
        ttk.Scale(spd, from_=0.5, to=2.0, variable=self.var_speed, length=260,
                  command=self._on_speed).pack(side="left", padx=6)
        self.lbl_speed = ttk.Label(spd, text="1.00 倍速", width=10,
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.lbl_speed.pack(side="left")

        self.lbl_status = tk.Label(frm, text="选一首曲子，点「开始」。", fg="#2266cc",
                                   anchor="w", font=("Microsoft YaHei UI", 10))
        self.lbl_status.grid(row=5, column=0, columnspan=3, sticky="we", padx=10, pady=(8, 2))

        self.lbl_note = tk.Label(frm, text="--", fg="#111111", anchor="center",
                                 font=("Consolas", 26, "bold"), bg="#f2f2f2", height=2)
        self.lbl_note.grid(row=6, column=0, columnspan=3, sticky="we", padx=10, pady=6)

        prog = ttk.Frame(frm)
        prog.grid(row=7, column=0, columnspan=3, sticky="we", padx=10, pady=2)
        self.pcv = tk.Canvas(prog, height=20, bg="#e6e6e6", highlightthickness=1,
                             highlightbackground="#cccccc", cursor="hand2")
        self.pcv.pack(side="left", fill="x", expand=True)
        self.pcv.bind("<Button-1>", self._on_seek)
        self.pcv.bind("<B1-Motion>", self._on_seek)
        self.lbl_time = ttk.Label(prog, text="0:00 / 0:00  0%", width=18, anchor="e")
        self.lbl_time.pack(side="left", padx=(8, 0))

        self.lbl_admin = tk.Label(frm, text="当前不是管理员，可能按不到管理员运行的游戏。",
                                  fg="#cc2222", anchor="w")
        self.btn_admin = ttk.Button(frm, text="以管理员身份重启", command=self.restart_as_admin)
        if not lp.is_admin():
            self.lbl_admin.grid(row=8, column=0, columnspan=2, sticky="w", padx=10, pady=2)
            self.btn_admin.grid(row=8, column=2, sticky="e", padx=10, pady=2)

    def _draw_progress(self, frac):
        w = self.pcv.winfo_width()
        h = self.pcv.winfo_height()
        if w < 20 or h < 5:
            return
        self.pcv.delete("all")
        self.pcv.create_rectangle(0, 0, int(w * frac), h, fill="#4a90d9", outline="")
        self.pcv.create_line(int(w * frac), 0, int(w * frac), h, fill="#2e6bb0", width=2)

    def _seek_from_x(self, x):
        w = self.pcv.winfo_width()
        if w < 20:
            return 0.0
        frac = max(0.0, min(1.0, float(x) / float(w)))
        self._draw_progress(frac)
        self.lbl_time.config(text="%s / %s  %d%%" % (fmt_time(frac * self.total_s),
                                                     fmt_time(self.total_s), int(frac * 100)))
        return frac

    def _on_seek(self, event):
        frac = self._seek_from_x(event.x)
        if self.player.playing:
            self.player.seek(frac)

    def refresh_scores(self):
        self.listbox.delete(0, tk.END)
        if not os.path.isdir(SCORE_DIR):
            os.makedirs(SCORE_DIR, exist_ok=True)
        self._files = sorted(f for f in os.listdir(SCORE_DIR)
                             if f.lower().endswith((".txt", ".mid", ".midi")))
        for f in self._files:
            self.listbox.insert(tk.END, os.path.splitext(f)[0])
        if self._files:
            self.listbox.selection_set(0)
            self._on_select()

    def _on_select(self):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self._files):
            self._selected = os.path.join(SCORE_DIR, self._files[sel[0]])

    def open_import(self):
        win = tk.Toplevel(self.root)
        win.title("导入琴谱")
        win.geometry("560x420")
        win.transient(self.root)

        ttk.Label(win, text="曲名").pack(anchor="w", padx=12, pady=(10, 2))
        ent = ttk.Entry(win, width=30)
        ent.pack(anchor="w", padx=12)
        ttk.Label(win, text="把网上的琴谱粘进来（字母谱 / 简谱 / 音符谱都行）").pack(
            anchor="w", padx=12, pady=(10, 2))
        txt = tk.Text(win, height=14, wrap="none", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, padx=12, pady=4)

        def do_pick_midi():
            f = filedialog.askopenfilename(title="选择 MIDI",
                                           filetypes=[("MIDI", "*.mid *.midi")])
            if not f:
                return
            import shutil
            shutil.copy(f, os.path.join(SCORE_DIR, os.path.basename(f)))
            win.destroy()
            self.refresh_scores()

        def do_save():
            name = ent.get().strip() or "新曲目"
            body = txt.get("1.0", "end").strip()
            if not body:
                messagebox.showinfo("提示", "内容为空")
                return
            if "@" not in body:
                body = "@title %s\n@keys\n%s" % (name, body)
            path = os.path.join(SCORE_DIR, name.replace("/", "_") + ".txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(body + "\n")
            win.destroy()
            self.refresh_scores()

        bar = ttk.Frame(win)
        bar.pack(pady=8)
        ttk.Button(bar, text="保存到曲目", command=do_save).pack(side="left", padx=6)
        ttk.Button(bar, text="选 .mid 文件", command=do_pick_midi).pack(side="left", padx=6)

    def on_delete(self):
        if self.state in ("playing", "paused", "countdown"):
            self.on_stop()
        if not self._selected:
            messagebox.showinfo("提示", "先选一首曲子")
            return
        name = os.path.splitext(os.path.basename(self._selected))[0]
        if not messagebox.askyesno("永久删除",
                                   "确定把《%s》从硬盘上永久删除吗？\n\n此操作不可恢复。" % name):
            return
        try:
            os.remove(self._selected)
        except OSError as e:
            messagebox.showerror("删除失败", str(e))
            return
        self._selected = None
        self.refresh_scores()
        self.lbl_status.config(text="已删除《%s》。" % name)

    def on_main(self):
        if self.state == "idle":
            self.start_fresh()
        elif self.state == "playing":
            self.player.pause()
            self._auto_paused = False
            self.state = "paused"
            self.btn_main.config(text="▶  继续")
            self.lbl_note.config(text="已暂停", fg="#999999")
            self.lbl_status.config(text="已暂停，点「继续」后 3 秒开始。")
        elif self.state == "paused":
            self.begin_countdown("resume")
        elif self.state == "countdown":
            self.lbl_status.config(text="倒计时中…稍等")

    def start_fresh(self):
        if not self._selected:
            messagebox.showinfo("提示", "请先选一首曲子")
            return
        self.player.melody_only = not self.var_accomp.get()
        err = self.player.load(self._selected)
        if err:
            messagebox.showerror("琴谱错误", err)
            return
        st = self.player.stats
        self.total_s = max(0.1, st["total_s"])
        self.lbl_status.config(
            text="%s　|　%d 键　|　%s" % (self.player.meta["title"], st["notes"],
                                          fmt_time(self.total_s)))
        self._draw_progress(0.0)
        self.lbl_time.config(text="0:00 / %s  0%%" % fmt_time(self.total_s))
        self.begin_countdown("start")

    def begin_countdown(self, mode):
        self.pending = mode
        self.state = "countdown"
        self.countdown = 3
        self.btn_main.config(text="… %d" % self.countdown)
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="3 秒后开始，请切回游戏窗口…")
        self.root.after(1000, self._tick_countdown)

    def _tick_countdown(self):
        if self.state != "countdown":
            return
        self.countdown -= 1
        if self.countdown > 0:
            self.btn_main.config(text="… %d" % self.countdown)
            self.lbl_status.config(text="%d 秒后开始，请切回游戏窗口…" % self.countdown)
            self.root.after(1000, self._tick_countdown)
            return
        self.player.speed = self.var_speed.get()
        if self.pending == "start":
            self.player.play()
        else:
            self.player.resume()
        self.state = "playing"
        self.play_started = time.monotonic()
        self._auto_paused = False
        self.btn_main.config(text="⏸  暂停")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="演奏中…（切出游戏会自动暂停）")

    def on_stop(self):
        self.state = "idle"
        self.countdown = 0
        self.pending = None
        self.player.stop()
        self._auto_paused = False
        self.btn_main.config(text="▶  开始")
        self.btn_stop.config(state="disabled")
        self._draw_progress(0.0)
        self.lbl_note.config(text="--", fg="#111111")
        self.lbl_time.config(text="0:00 / %s  0%%" % fmt_time(self.total_s))
        self.lbl_status.config(text="已停止。")

    def _on_speed(self, v):
        val = float(v)
        self.player.set_speed(val)
        self.lbl_speed.config(text="%.2f 倍速" % val)

    def _tick(self):
        try:
            if self.state == "playing":
                cur = self.player.current
                if cur:
                    note = lp.KEY2NOTE.get(cur)
                    note_txt = "%s%d" % (note[1], note[0]) if note else cur
                    self.lbl_note.config(text="%s   %s" % (cur, note_txt), fg="#0a7a3d")
                p = max(0.0, min(1.0, self.player.progress))
                self._draw_progress(p)
                self.lbl_time.config(text="%s / %s  %d%%" % (fmt_time(p * self.total_s),
                                                             fmt_time(self.total_s), int(p * 100)))
                if not self.player.playing:
                    self.state = "idle"
                    self.btn_main.config(text="▶  开始")
                    self.btn_stop.config(state="disabled")
                    self.lbl_status.config(text="演奏结束。")
                    self.lbl_note.config(text="--", fg="#111111")

                if (self.var_autostop.get() and self.state == "playing"
                        and time.monotonic() - self.play_started > 0.6
                        and not lp.is_game_foreground()):
                    self.player.pause()
                    self._auto_paused = True
                    self.state = "paused"
                    self.btn_main.config(text="▶  继续")
                    self.lbl_status.config(text="已切出游戏，自动暂停。点「继续」后 3 秒接着弹。")
                    self.lbl_note.config(text="已暂停", fg="#999999")

            elif self.state == "paused":
                p = max(0.0, min(1.0, self.player.progress))
                self._draw_progress(p)
                self.lbl_time.config(text="%s / %s  %d%%" % (fmt_time(p * self.total_s),
                                                             fmt_time(self.total_s), int(p * 100)))
        except tk.TclError:
            return
        self.root.after(50, self._tick)

    def restart_as_admin(self):
        script = os.path.abspath(__file__)
        exe = sys.executable
        if not exe.lower().endswith("pythonw.exe"):
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, '"%s"' % script, None, 1)
        except Exception as e:
            messagebox.showerror("失败", "无法提权: %s" % e)
        self.root.destroy()


def main():
    if "--smoke" in sys.argv:
        root = tk.Tk()
        App(root)
        root.after(1500, root.destroy)
        root.mainloop()
        print("SMOKE OK")
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
