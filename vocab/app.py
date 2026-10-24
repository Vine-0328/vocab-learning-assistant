"""Accessible, offline Tk desktop interface."""
from __future__ import annotations
import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import Store, normalized_word, resource_dir, schedule, stamp, user_data_dir
from .widgets import ProgressTrack, SlimScrollbar

BG = "#f3f5f1"
WHITE = "#ffffff"
INK = "#20332e"
MUTED = "#71817a"
GREEN = "#24634c"
PALE = "#e6eee7"
NAV = "#192e27"
GOLD = "#b47928"
RED = "#b24d42"
FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "Arial"
MODES = {"study": "每日学习", "review": "到期复习", "spelling": "拼写练习", "mistakes": "错词巩固", "favorites": "收藏练习"}


def frame(parent, bg=BG, **kw):
    return tk.Frame(parent, bg=bg, **kw)


def label(parent, text, size=11, color=INK, bold=False, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), anchor="w", **kw)


def button(parent, text, command, primary=False, bg=None, fg=None, **kw):
    padx, pady = kw.pop("padx", 16), kw.pop("pady", 9)
    return tk.Button(parent, text=text, command=command, bg=bg or (GREEN if primary else PALE),
        fg=fg or (WHITE if primary else GREEN), activebackground=GREEN if primary else "#d8e5db",
        activeforeground=WHITE if primary else INK, relief="flat", bd=0, cursor="hand2",
        font=(FONT, 10), padx=padx, pady=pady, highlightthickness=0, **kw)


def readonly(parent, text, height=4, size=11, bg=WHITE):
    box = tk.Text(parent, height=height, bg=bg, fg=INK, relief="flat", bd=0, wrap="word",
                  font=(FONT, size), padx=0, pady=4, spacing1=2, spacing3=6,
                  highlightthickness=0, selectbackground=PALE)
    box.insert("1.0", text)
    box.configure(state="disabled")
    return box


def memory_status(word):
    if word.get("reviews") is None:
        return "未学"
    return "已掌握" if word.get("repetitions", 0) >= 3 and word.get("interval_days", 0) >= 21 else "学习中"


def interval_text(days):
    if days < 1:
        return f"{max(1, round(days*1440))} 分钟"
    return f"{days:.0f} 天"


class VocabLearner:
    def __init__(self, store=None):
        self.store = store or Store()
        self.root = tk.Tk()
        self.root.title("词间 Vocab · 托福 / SAT 词汇学习助手")
        self.root.geometry("1180x820")
        self.root.minsize(1000, 720)
        self.root.configure(bg=BG)
        icon = resource_dir() / "app_icon.png"
        if icon.exists():
            self._icon = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.on_error
        self.current_view = "home"
        self.session = None
        saved = self.store.get_setting("session_v2", {})
        saved = saved if isinstance(saved, dict) else {}
        if saved.get("day") == self.store.clock().date().isoformat() and saved.get("mode") in MODES:
            if isinstance(saved.get("ids"), list) and 0 <= saved.get("index", -1) < len(saved["ids"]):
                try:
                    for wid in saved["ids"]:
                        self.store.get_word(wid)
                    self.session = saved
                except (ValueError, TypeError):
                    pass
        self.revealed = False
        self.search_timer = None
        self.speaking = False
        self._style()
        self._shell()
        self.root.bind("<space>", self.shortcut)
        self.root.bind("<Return>", self.shortcut)
        for key in "1234":
            self.root.bind(key, self.shortcut)
        self.show("home")
        self.root.after(30000, self.tick)

    def _style(self):
        self.root.option_add("*Font", (FONT, 10))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK,
                        rowheight=37, borderwidth=0, font=(FONT, 10))
        style.configure("Treeview.Heading", font=(FONT, 10, "bold"), background=PALE, foreground=INK, relief="flat", padding=8)
        style.map("Treeview", background=[("selected", "#d8e8dd")], foreground=[("selected", INK)])
        style.configure("TCombobox", fieldbackground=WHITE, padding=6)

    def _shell(self):
        self.sidebar = frame(self.root, NAV, width=190)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        brand = frame(self.sidebar, NAV)
        brand.pack(fill="x", padx=24, pady=(30, 32))
        label(brand, "词间", 27, WHITE, True).pack(anchor="w")
        label(brand, "V O C A B", 10, "#a8beb1").pack(anchor="w", pady=(6, 0))
        self.nav_buttons = {}
        for key, title in [("home", "今日概览"), ("study", "学习空间"), ("library", "我的词库"), ("mistakes", "错词与收藏"), ("stats", "学习统计"), ("settings", "计划与数据")]:
            b = button(self.sidebar, title, lambda k=key: self.show(k), bg=NAV, fg="#bdcfc3", anchor="w", width=13)
            b.pack(fill="x", padx=14, pady=4)
            self.nav_buttons[key] = b
        footer = frame(self.sidebar, NAV)
        footer.pack(side="bottom", fill="x", padx=24, pady=26)
        label(footer, "一点积累，日有所获。", 9, "#b6c9bc").pack(anchor="w")
        label(footer, f"离线学习  ·  v{__version__}", 9, "#8ca695").pack(anchor="w", pady=(8, 0))
        right = frame(self.root)
        right.pack(side="left", fill="both", expand=True)
        bar = frame(right, WHITE, height=54)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        label(bar, "TOEFL / SAT   ·   词汇学习助手", 10, MUTED).pack(side="left", padx=28)
        self.date_label = label(bar, self.store.clock().strftime("%Y.%m.%d"), 10, MUTED)
        self.date_label.pack(side="right", padx=28)
        self.status = tk.StringVar(value="已准备就绪 · 学习记录自动保存在本机")
        label(right, "", 9, MUTED, textvariable=self.status).pack(side="bottom", fill="x", padx=28, pady=(0, 10))
        viewport = frame(right)
        viewport.pack(fill="both", expand=True, padx=(28, 8), pady=(20, 8))
        self.canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0)
        scrollbar = SlimScrollbar(viewport, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(6, 0))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = frame(self.canvas)
        self.content_window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self.resize_content)
        self.content.bind("<Configure>", self.resize_content)
        self.root.bind_all("<MouseWheel>", self.mousewheel, add="+")

    def resize_content(self, event=None):
        if getattr(self, "_resizing", False):
            return
        self._resizing = True
        try:
            self.content.update_idletasks()
            self.canvas.itemconfigure(self.content_window, width=self.canvas.winfo_width(),
                height=max(self.canvas.winfo_height(), self.content.winfo_reqheight()))
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        finally:
            self._resizing = False

    def mousewheel(self, event):
        if isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        if self.canvas.bbox("all") and self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta/120), "units")

    def clear(self):
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        for child in self.content.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)

    def heading(self, title, subtitle):
        label(self.content, title, 22, bold=True).pack(anchor="w")
        label(self.content, subtitle, 10, MUTED).pack(anchor="w", pady=(6, 20))

    def show(self, key):
        self.current_view = key
        self.revealed = False
        self.clear()
        for k, b in self.nav_buttons.items():
            b.configure(bg=GREEN if k == key else NAV, fg=WHITE if k == key else "#bdcfc3")
        {"home": self.home, "study": self.study, "library": self.library,
         "mistakes": lambda: self.library(True), "stats": self.statistics, "settings": self.settings}[key]()
        self.root.after_idle(self.resize_content)

    def metric_row(self, metrics):
        row = frame(self.content)
        row.pack(fill="x", pady=(0, 16))
        for i, (title, value, hint) in enumerate(metrics):
            cell = frame(row, WHITE, padx=18, pady=13)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            row.columnconfigure(i, weight=1, uniform="metric")
            label(cell, title, 10, MUTED).pack(anchor="w")
            label(cell, str(value), 25, GREEN, True).pack(anchor="w", pady=(6, 2))
            label(cell, hint, 9, MUTED).pack(anchor="w")

    def home(self):
        s = self.store.stats()
        self.heading("把今天的单词，变成明天的底气。", "先复习，再认识新词。每一次回想，都让记忆更牢一点。")
        hero = frame(self.content, GREEN, padx=24, pady=20)
        hero.pack(fill="x", pady=(0, 16))
        goal = self.store.get_setting("daily_goal")
        label(hero, "TODAY'S PLAN", 9, "#c2d9ca").pack(anchor="w")
        label(hero, f"今日新词  {s['new_today']} / {goal}", 23, WHITE, True).pack(anchor="w", pady=(8, 8))
        line = frame(hero, GREEN)
        line.pack(fill="x")
        label(line, f"学习词库：{self.store.get_setting('deck')}    ·    待复习 {s['due']} 词", 10, "#dfebe2").pack(side="left")
        resume = self.session and self.session["index"] < len(self.session["ids"])
        button(line, "继续这一轮  →" if resume else "开始今日学习  →", lambda: self.show("study") if resume else self.start("study"), bg="#ecf1d7").pack(side="right")
        ProgressTrack(hero, value=min(100, 100*s["new_today"]/goal), track="#477d64", fill="#e6edcc").pack(fill="x", pady=(16, 0))
        self.metric_row([("已学习词汇", s["learned"], f"词库共 {s['total']:,} 词"),
                         ("今日练习", s["today_words"], f"完成 {s['today_reviews']} 次回想"),
                         ("连续学习", f"{s['streak']} 天", "每天一点，保持节奏"),
                         ("已掌握", s["mastered"], "连续回想 + 21 天间隔")])
        tasks = frame(self.content)
        tasks.pack(fill="x", pady=(0, 16))
        for i, (title, desc, mode) in enumerate([("温故知新", "优先处理已经到期的复习卡片", "review"), ("拼写检验", "看释义，试着完整拼出单词", "spelling"), ("攻克错词", f"回顾曾经忘记的 {s['mistakes']} 个单词", "mistakes")]):
            cell = frame(tasks, WHITE, padx=16, pady=14)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if not i else 10, 0))
            tasks.columnconfigure(i, weight=1, uniform="tasks")
            label(cell, title, 13, bold=True).pack(anchor="w")
            label(cell, desc, 9, MUTED).pack(anchor="w", pady=(8, 12))
            button(cell, "开始  →", lambda m=mode: self.start(m)).pack(anchor="w")
        chart = frame(self.content, WHITE, padx=18, pady=12)
        chart.pack(fill="both", expand=True)
        label(chart, "最近 14 天的积累", 11, bold=True).pack(anchor="w")
        self.chart(chart, s["history"], 110)

    def start(self, mode, deck=None):
        rows = self.store.queue(mode, deck=deck)
        self.session = {"ids": [w["id"] for w in rows], "mode": mode, "index": 0,
                        "correct": 0, "day": self.store.clock().date().isoformat()}
        self.persist_session()
        self.show("study")

    def persist_session(self):
        with self.store.conn:
            self.store._set("session_v2", self.session or {})

    def study(self):
        self.heading("学习空间", "给自己一点回想的时间，再揭开答案。")
        tabs = frame(self.content)
        tabs.pack(fill="x", pady=(0, 16))
        mode = self.session["mode"] if self.session else "study"
        for key, title in MODES.items():
            button(tabs, title, lambda k=key: self.start(k), primary=key == mode, padx=11).pack(side="left", padx=(0, 6))
        if not self.session:
            rows = self.store.queue("study")
            self.session = {"ids": [w["id"] for w in rows], "mode": "study", "index": 0, "correct": 0, "day": self.store.clock().date().isoformat()}
            self.persist_session()
        self.card_area = frame(self.content)
        self.card_area.pack(fill="both", expand=True)
        self.render_card()

    def render_card(self):
        self.revealed = False
        self.root.after_idle(self.resize_content)
        for child in self.card_area.winfo_children():
            child.destroy()
        session = self.session
        count, index = len(session["ids"]), session["index"]
        top = frame(self.card_area)
        top.pack(fill="x", pady=(0, 12))
        label(top, f"{MODES[session['mode']]}   /   本轮 {min(index+1, count)} / {count}", 10, MUTED).pack(side="left")
        ProgressTrack(top, value=100*index/max(1, count), length=180).pack(side="right", pady=5)
        if index >= count:
            card = frame(self.card_area, WHITE, padx=32, pady=48)
            card.pack(fill="both", expand=True)
            label(card, "这一轮，完成了。" if count else "现在没有待学的卡片", 25, GREEN, True).pack(anchor="w")
            text = (f"完成 {count} 个单词，回想正确 {session['correct']} 个。学习记录已经保存。" if count else
                    "当前词库没有到期卡片、符合条件的词，或今日新词目标已完成。\n可切换练习模式，在计划中选择其他词库，或稍后再来。")
            label(card, text, 11, MUTED, justify="left", wraplength=650).pack(anchor="w", pady=24)
            button(card, "再来一轮", lambda: self.start(session["mode"]), True).pack(anchor="w", pady=10)
            button(card, "返回今日概览", lambda: self.show("home")).pack(anchor="w")
            return
        try:
            self.word = self.store.get_word(session["ids"][index])
            if self.word["deleted"]:
                self.session["ids"].pop(index)
                self.persist_session()
                self.render_card()
                return
        except ValueError:
            self.session["ids"].pop(index)
            self.render_card()
            return
        w = self.word
        card = frame(self.card_area, WHITE, padx=28, pady=22)
        card.pack(fill="both", expand=True)
        meta = frame(card, WHITE)
        meta.pack(fill="x")
        label(meta, f"{w['deck']}    ·    {memory_status(w)}", 10, MUTED).pack(side="left")
        self.favorite_button = button(meta, "★ 已收藏" if w["favorite"] else "☆ 收藏", self.favorite_current, bg=WHITE)
        self.favorite_button.pack(side="right")
        spelling = session["mode"] == "spelling"
        self.word_label = label(card, "请根据释义拼写单词" if spelling else w["word"], 22 if spelling else 34, GREEN, True, wraplength=700)
        self.word_label.pack(anchor="w", pady=(24, 10))
        if not spelling:
            button(card, "朗读单词", lambda: self.speak(w["word"]), bg=PALE).pack(anchor="w", pady=(0, 12))
        self.answer_area = frame(card, WHITE)
        self.answer_area.pack(fill="both", expand=True)
        self.action_area = frame(card, WHITE)
        self.action_area.pack(fill="x", pady=(16, 0))
        if spelling:
            readonly(self.answer_area, w["definition"], height=3, size=15).pack(fill="x")
            self.spelling = ttk.Entry(self.answer_area, font=(FONT, 17))
            self.spelling.pack(fill="x", pady=(12, 8))
            label(self.answer_area, "Enter 提交答案 · 忽略大小写与首尾空格", 9, MUTED).pack(anchor="w")
            self.spell_feedback = label(self.answer_area, "", 12, GREEN, True, wraplength=700)
            self.spell_feedback.pack(anchor="w", pady=14)
            self.spell_submit = button(self.action_area, "检查拼写", self.check_spelling, True)
            self.spell_submit.pack(side="left")
            self.spelling.focus_set()
        else:
            label(self.answer_area, "先试着回想它的意思……", 13, MUTED).pack(anchor="w", pady=22)
            self.reveal_button = button(self.action_area, "显示释义  ·  Space", self.reveal, True)
            self.reveal_button.pack(side="left")
            label(self.action_area, "揭示答案后，用 1–4 选择掌握程度", 9, MUTED).pack(side="right")
        self.status.set("每次评分后自动保存 · 离开页面可继续这一轮")

    def favorite_current(self):
        self.store.toggle_favorite(self.word["id"])
        self.word = self.store.get_word(self.word["id"])
        self.favorite_button.configure(text="★ 已收藏" if self.word["favorite"] else "☆ 收藏")

    def reveal(self):
        if self.current_view != "study" or self.revealed or self.session["index"] >= len(self.session["ids"]):
            return
        self.revealed = True
        for child in self.answer_area.winfo_children():
            child.destroy()
        for child in self.action_area.winfo_children():
            child.destroy()
        text = self.word["definition"] + "\n\n" + (self.word["example"] or "此扩展词暂未提供例句，可在词库中补充。")
        if self.word["note"]:
            text += "\n\n我的笔记：" + self.word["note"]
        readonly(self.answer_area, text, height=6, size=13).pack(fill="both", expand=True)
        prior = self.store.conn.execute("SELECT * FROM progress WHERE word_id=?", (self.word["id"],)).fetchone()
        self.rating_buttons = []
        for key, title, color in [("again", "1  忘记", RED), ("hard", "2  模糊", GOLD), ("good", "3  记得", GREEN), ("easy", "4  熟悉", GREEN)]:
            p = schedule(dict(prior) if prior else None, key, self.store.clock())
            if prior and prior["due_at"] > stamp(self.store.clock()) and key != "again":
                hint = "保留原计划"
            else:
                hint = interval_text(p["interval_days"])
            b = button(self.action_area, f"{title}\n{hint}", lambda k=key: self.rate(k), bg=PALE, fg=color, width=11, padx=9)
            b.pack(side="left", expand=True, fill="x", padx=(0, 8))
            self.rating_buttons.append(b)
        self.root.after_idle(self.resize_content)

    def rate(self, rating):
        if not self.revealed:
            return
        self.revealed = False
        graded_word = self.word["word"]
        try:
            self.store.grade(self.word["id"], rating)
        except Exception:
            self.revealed = True
            raise
        self.session["index"] += 1
        self.session["correct"] += int(rating != "again")
        self.persist_session()
        self.render_card()
        self.status.set(f"已保存 · {graded_word} 的复习安排将在学习统计中显示")

    def check_spelling(self):
        if self.revealed:
            self.next_spelling()
            return
        answer = normalized_word(self.spelling.get())
        if not answer:
            self.status.set("请先输入你的拼写")
            return
        correct = answer == normalized_word(self.word["word"])
        self.store.grade(self.word["id"], "good" if correct else "again", "spelling")
        self.revealed = True
        self.session["correct"] += int(correct)
        # Persist an answered spelling card as complete even if the window closes on feedback.
        self.session["index"] += 1
        self.persist_session()
        self.word_label.configure(text=self.word["word"])
        self.spell_feedback.configure(text="拼写正确，很好！" if correct else f"再记一次：{self.word['word']}", fg=GREEN if correct else RED)
        self.spelling.configure(state="disabled")
        self.spell_submit.configure(text="下一个  →", command=self.next_spelling)
        readonly(self.answer_area, self.word["example"] or "暂无例句", height=3, size=11).pack(fill="both", expand=True)
        button(self.action_area, "朗读单词", lambda: self.speak(self.word["word"])).pack(side="left", padx=12)
        self.status.set("拼写结果已保存")
        self.root.after_idle(self.resize_content)

    def next_spelling(self):
        if self.revealed:
            self.render_card()

    def shortcut(self, event):
        if self.current_view != "study" or not self.session:
            return
        if isinstance(event.widget, (tk.Text, ttk.Combobox, tk.Button)):
            return
        if isinstance(event.widget, (tk.Entry, ttk.Entry)) and event.keysym != "Return":
            return
        if self.session["mode"] == "spelling":
            if event.keysym == "Return" and hasattr(self, "spelling") and self.spelling.winfo_exists():
                self.check_spelling()
                return "break"
        elif event.keysym in {"space", "Return"}:
            self.reveal()
            return "break"
        elif event.char in "1234" and event.char:
            self.rate(["again", "hard", "good", "easy"][int(event.char)-1])
            return "break"

    def library(self, mistakes=False):
        self.heading("错词与收藏" if mistakes else "我的词库", "检索单词、补充例句和笔记，把词库变成自己的。双击一行即可编辑。")
        tools = frame(self.content)
        tools.pack(fill="x", pady=(0, 12))
        self.query_var = tk.StringVar()
        entry = ttk.Entry(tools, textvariable=self.query_var, width=23)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.filter_var = tk.StringVar(value="错词" if mistakes else "全部")
        statuses = ["错词", "收藏"] if mistakes else ["全部", "未学", "学习中", "已掌握", "待复习", "错词", "收藏", "已归档"]
        ttk.Combobox(tools, textvariable=self.filter_var, values=statuses, state="readonly", width=9).pack(side="left", padx=(0, 8))
        self.library_deck = tk.StringVar(value="全部")
        ttk.Combobox(tools, textvariable=self.library_deck, values=self.store.decks(), state="readonly", width=12).pack(side="left", padx=(0, 8))
        button(tools, "+ 添加", lambda: self.edit_word()).pack(side="right")
        actions = frame(self.content)
        actions.pack(fill="x", pady=(0, 12))
        if mistakes:
            button(actions, "开始当前分类练习", lambda: self.start("favorites" if self.filter_var.get() == "收藏" else "mistakes", self.library_deck.get()), True).pack(side="left")
        else:
            button(actions, "导入 JSON / CSV", self.import_words).pack(side="left")
        button(actions, "导出筛选结果", self.export_words).pack(side="left", padx=8)
        self.result_label = label(actions, "", 9, MUTED)
        self.result_label.pack(side="right")
        table = frame(self.content, WHITE)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("word", "meaning", "deck", "state", "star"), show="headings", selectmode="browse", height=8)
        for key, title, width in [("word", "单词", 160), ("meaning", "释义", 340), ("deck", "词库", 90), ("state", "掌握状态", 85), ("star", "收藏", 45)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=40, stretch=key == "meaning")
        scrollbar = SlimScrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select_word)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.detail = readonly(self.content, "搜索单词或中文释义，选择一行查看例句、笔记和复习时间。", height=4, size=10, bg=BG)
        self.detail.pack(fill="x", pady=(10, 0))
        bottom = frame(self.content)
        bottom.pack(fill="x")
        for text, command in [("编辑 / 笔记", self.edit_selected), ("收藏 / 取消", self.favorite_selected), ("朗读", self.speak_selected), ("归档 / 恢复", self.archive_selected)]:
            button(bottom, text, command).pack(side="left", padx=(0, 8))
        self.query_var.trace_add("write", lambda *a: self.delay_search())
        self.filter_var.trace_add("write", lambda *a: self.refresh_library())
        self.library_deck.trace_add("write", lambda *a: self.refresh_library())
        self.refresh_library()

    def delay_search(self):
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
        self.search_timer = self.root.after(180, self.refresh_library)

    def refresh_library(self):
        self.search_timer = None
        if not hasattr(self, "tree") or not self.tree.winfo_exists():
            return
        self.library_rows = self.store.search(self.query_var.get(), self.filter_var.get(), self.library_deck.get(), limit=100000)
        self.tree.delete(*self.tree.get_children())
        for w in self.library_rows:
            self.tree.insert("", "end", iid=str(w["id"]), values=(w["word"], w["definition"].replace("\n", " "), w["deck"], "已归档" if w["deleted"] else memory_status(w), "★" if w["favorite"] else ""))
        self.result_label.configure(text=f"{len(self.library_rows):,} 个结果")

    def selected(self):
        ids = self.tree.selection()
        if not ids:
            self.status.set("请先在列表中选择一个单词")
            return None
        return self.store.get_word(int(ids[0]))

    def select_word(self, event=None):
        w = self.selected()
        if not w:
            return
        text = f"{w['word']}  ·  {w['definition']}\n例句：{w['example'] or '暂无例句，可双击补充'}\n笔记：{w['note'] or '暂无'}  |  下次复习：{(w['due_at'] or '尚未学习').replace('T', ' ')}"
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def edit_selected(self):
        w = self.selected()
        if w:
            self.edit_word(w)

    def favorite_selected(self):
        w = self.selected()
        if w:
            self.store.toggle_favorite(w["id"])
            self.refresh_library()
            self.status.set("收藏状态已保存")

    def speak_selected(self):
        w = self.selected()
        if w:
            self.speak(w["word"])

    def archive_selected(self):
        w = self.selected()
        if w:
            self.store.archive(w["id"], not w["deleted"])
            self.refresh_library()
            self.status.set("已恢复词汇" if w["deleted"] else "已归档；可在「已归档」筛选中恢复，学习记录保留")

    def edit_word(self, word=None):
        win = tk.Toplevel(self.root)
        win.title("编辑词汇" if word else "添加词汇")
        win.geometry("650x700")
        win.minsize(550, 620)
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()
        body = frame(win, padx=24, pady=18)
        body.pack(fill="both", expand=True)
        fields = {}
        for key, title, height in [("word", "英文单词 / 短语 *", 1), ("definition", "释义 *", 3), ("example", "例句", 3), ("deck", "词库名称", 1), ("note", "我的笔记", 3)]:
            label(body, title, 10, MUTED).pack(anchor="w", pady=(8, 5))
            if height == 1:
                widget = ttk.Entry(body)
                widget.insert(0, (word or {}).get(key, "自定义" if key == "deck" else ""))
            else:
                widget = tk.Text(body, height=height, wrap="word", relief="flat", bg=WHITE, fg=INK, padx=8, pady=6)
                widget.insert("1.0", (word or {}).get(key, ""))
            widget.pack(fill="x")
            fields[key] = widget
        def save():
            values = {k: w.get("1.0", "end-1c") if isinstance(w, tk.Text) else w.get() for k, w in fields.items()}
            values["difficulty"] = (word or {}).get("difficulty", "medium")
            try:
                self.store.save_word(values, word["id"] if word else None)
            except ValueError as exc:
                messagebox.showerror("未能保存", str(exc), parent=win)
                return
            win.destroy()
            self.show(self.current_view)
            self.status.set("词汇已保存")
        bottom = frame(body)
        bottom.pack(fill="x", pady=16)
        button(bottom, "保存词汇", save, True).pack(side="right")
        button(bottom, "取消", win.destroy).pack(side="right", padx=10)
        fields["word"].focus_set()

    def chart(self, parent, data, height=180):
        canvas = tk.Canvas(parent, bg=WHITE, height=height, highlightthickness=0)
        canvas.pack(fill="both", expand=True, pady=(8, 0))
        def draw(event=None):
            canvas.delete("all")
            width, h = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 70)
            left, bottom, top = 28, h-24, 18
            maximum = max(1, *(r["total"] for r in data))
            canvas.create_line(left, bottom, width-12, bottom, fill=PALE)
            step = (width-left-12)/len(data)
            for i, r in enumerate(data):
                x = left+step*i+step/2
                bar = (bottom-top)*r["total"]/maximum
                canvas.create_rectangle(x-step*.25, bottom-max(2, bar), x+step*.25, bottom, fill=GREEN if r["total"] else PALE, outline="")
                if r["total"]:
                    canvas.create_text(x, bottom-bar-9, text=str(r["total"]), fill=MUTED, font=(FONT, 8))
                canvas.create_text(x, bottom+14, text=r["day"][5:].replace("-", "/"), fill=MUTED, font=(FONT, 8))
        canvas.bind("<Configure>", draw)

    def statistics(self):
        s = self.store.stats()
        self.heading("每一点积累，都看得见。", "数据来自你的真实学习记录。到期时间按本机日期计算。")
        accuracy = f"{s['today_correct']/s['today_reviews']:.0%}" if s["today_reviews"] else "—"
        self.metric_row([("累计学习", s["learned"], f"未学 {s['total']-s['learned']:,} 词"), ("今日回想正确率", accuracy, "忘记 / 拼写错误计为不正确"),
                         ("待复习", s["due"], "包含已经逾期的单词"), ("连续学习", f"{s['streak']} 天", "跨日自动更新")])
        chart = frame(self.content, WHITE, padx=20, pady=16)
        chart.pack(fill="both", expand=True, pady=(0, 16))
        label(chart, "近 14 天练习次数", 12, bold=True).pack(anchor="w")
        self.chart(chart, s["history"], 160)
        future = frame(self.content, WHITE, padx=20, pady=16)
        future.pack(fill="x", pady=(0, 12))
        label(future, "未来 7 天复习计划", 12, bold=True).pack(anchor="w")
        row = frame(future, WHITE)
        row.pack(fill="x", pady=(14, 0))
        for i, item in enumerate(s["forecast"]):
            cell = frame(row, WHITE)
            cell.grid(row=0, column=i, sticky="ew")
            row.columnconfigure(i, weight=1, uniform="forecast")
            label(cell, "今天*" if i == 0 else item["day"][5:].replace("-", "/"), 10, MUTED).pack()
            label(cell, str(item["total"]), 20, GREEN, True).pack(pady=6)
        label(future, "* 今天包含逾期及今天稍后到期的词；计划会随评分更新。", 9, MUTED).pack(anchor="w", pady=(12, 0))
        label(self.content, "掌握标准：连续成功回想至少 3 次，且复习间隔达到 21 天。错词本保留曾经忘记的词。", 9, MUTED, wraplength=800).pack(anchor="w")

    def settings(self):
        self.heading("找到适合自己的节奏。", "学习计划可以随时调整，所有变更会立即保存到本机。")
        plan = frame(self.content, WHITE, padx=22, pady=18)
        plan.pack(fill="x", pady=(0, 16))
        label(plan, "每日计划", 13, bold=True).pack(anchor="w")
        row = frame(plan, WHITE)
        row.pack(fill="x", pady=16)
        fields = {}
        for i, (key, title, values) in enumerate([("daily_goal", "每日新词目标", None), ("session_size", "每轮卡片数量", None), ("deck", "学习词库", self.store.decks())]):
            cell = frame(row, WHITE)
            cell.pack(side="left", padx=(0, 24))
            label(cell, title, 10, MUTED).pack(anchor="w", pady=(0, 6))
            var = tk.StringVar(value=str(self.store.get_setting(key)))
            if values:
                ttk.Combobox(cell, textvariable=var, values=values, state="readonly", width=16).pack()
            else:
                ttk.Spinbox(cell, textvariable=var, from_=1, to=500 if key == "daily_goal" else 200, width=12).pack()
            fields[key] = var
        def save():
            try:
                self.store.save_settings(fields["daily_goal"].get(), fields["deck"].get(), fields["session_size"].get())
            except ValueError as exc:
                messagebox.showerror("检查学习计划", str(exc), parent=self.root)
                return
            # A changed plan starts a fresh queue instead of retaining stale deck/goal choices.
            self.session = None
            self.persist_session()
            self.status.set("学习计划已保存，下一轮将使用新设置")
        button(plan, "保存计划", save, True).pack(anchor="w")
        label(plan, "到期复习不占新词目标。错词、收藏和额外拼写练习可按需进行。", 9, MUTED).pack(anchor="w", pady=(12, 0))
        data = frame(self.content, WHITE, padx=22, pady=18)
        data.pack(fill="x", pady=(0, 16))
        label(data, "词库与学习数据", 13, bold=True).pack(anchor="w")
        first = frame(data, WHITE)
        first.pack(fill="x", pady=(14, 10))
        for title, command in [("导入词库", self.import_words), ("导出全部词库", lambda: self.export_words(True)), ("导入旧版记录", self.import_legacy)]:
            button(first, title, command).pack(side="left", padx=(0, 8))
        second = frame(data, WHITE)
        second.pack(fill="x")
        for title, command in [("完整备份", self.backup), ("恢复备份", self.restore), ("打开数据目录", self.open_data_dir)]:
            button(second, title, command).pack(side="left", padx=(0, 8))
        label(data, "完整备份包含词库、笔记、收藏、复习记录及计划；CSV 仅导出词汇内容。", 9, MUTED).pack(anchor="w", pady=(12, 0))
        about = frame(self.content, WHITE, padx=22, pady=16)
        about.pack(fill="both", expand=True)
        text = ("关于词库与复习\n\n"
                "内置 100 个中文释义及例句核心词（TOEFL / SAT 为学习分类，非官方考试词表）。\n"
                "扩展词库来自原项目，清理空格和重复项后保留；其英文释义及生僻词建议结合词典核对。\n"
                "复习采用可解释的间隔规则：忘记约 10 分钟；模糊至少 1 天；记得逐步延长；熟悉首次 4 天。\n"
                "提前练习不会重复拉长间隔；忘记会缩短间隔。Windows 发音使用系统离线语音。\n"
                "无需注册、API 密钥或联网。数据位置：" + str(self.store.path.parent))
        readonly(about, text, height=7, size=9).pack(fill="both", expand=True)

    def import_words(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择词库", filetypes=[("JSON / CSV 词库", "*.json *.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            added, skipped = self.store.import_words(path)
        except (ValueError, OSError, csv.Error) as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return
        self.show(self.current_view)
        self.status.set(f"导入完成：新增 {added} 词，跳过 {skipped} 个已存在词条")

    def export_words(self, all_words=False):
        path = filedialog.asksaveasfilename(parent=self.root, title="导出词库", defaultextension=".csv", initialfile="vocabulary.csv", filetypes=[("CSV 词库", "*.csv")])
        if path:
            rows = None if all_words else self.store.search(self.query_var.get(), self.filter_var.get(), self.library_deck.get(), limit=100000)
            self.store.export_csv(path, rows)
            self.status.set("词库已导出："+path)

    def backup(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="完整备份", defaultextension=".json", initialfile=f"vocab-backup-{self.store.clock():%Y%m%d}.json", filetypes=[("完整备份", "*.json")])
        if path:
            self.store.export_backup(path)
            self.status.set("完整备份已保存："+path)

    def restore(self):
        path = filedialog.askopenfilename(parent=self.root, title="恢复完整备份", filetypes=[("完整备份", "*.json")])
        if not path:
            return
        if not messagebox.askyesno("恢复备份", "恢复会替换当前词库和全部学习记录。\n程序会先自动保留当前数据库副本。\n\n确定恢复所选备份吗？", parent=self.root):
            return
        try:
            safety = self.store.restore_backup(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("恢复失败", str(exc), parent=self.root)
            return
        self.session = None
        self.persist_session()
        self.show("home")
        self.status.set("恢复成功；原数据保留于："+str(safety))

    def import_legacy(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择旧版 vocabulary.db", filetypes=[("旧版 SQLite 数据库", "*.db")])
        if path:
            try:
                self.store.import_legacy_database(path)
            except (ValueError, OSError) as exc:
                messagebox.showerror("迁移失败", str(exc), parent=self.root)
                return
            self.show(self.current_view)
            self.status.set("旧版记录已导入；已有新版本进度优先，原文件保留")

    def open_data_dir(self):
        path = str(self.store.path.parent)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def speak(self, word):
        if self.speaking:
            return
        if sys.platform != "win32":
            if sys.platform == "darwin":
                subprocess.Popen(["say", "--", word])
                return
            self.status.set("当前系统未接入语音；Windows 版支持系统离线发音")
            return
        self.speaking = True
        self.status.set("正在朗读……")
        # User text only enters stdin; it is never interpolated into a shell command.
        script = ("[Console]::InputEncoding=[System.Text.Encoding]::UTF8; "
                  "$word=[Console]::In.ReadToEnd(); Add-Type -AssemblyName System.Speech; "
                  "$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$voices=@($voice.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Culture.Name -like 'en-*'}); "
                  "if($voices.Count -eq 0){exit 3}; $voice.SelectVoice($voices[0].VoiceInfo.Name); "
                  "$voice.Rate=-1; $voice.Speak($word); $voice.Dispose()")
        def run():
            try:
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                    input=word, encoding="utf-8", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
                text = "朗读完成" if result.returncode == 0 else "系统没有可用的英语语音；可在 Windows 语言设置中安装英语语音包"
            except (OSError, subprocess.TimeoutExpired):
                text = "无法使用系统发音，请检查 Windows 语音设置"
            self.speaking = False
            try:
                self.root.after(0, lambda: self.status.set(text))
            except (RuntimeError, tk.TclError):
                pass
        threading.Thread(target=run, daemon=True).start()

    def tick(self):
        self.date_label.configure(text=self.store.clock().strftime("%Y.%m.%d"))
        if self.current_view in {"home", "stats"}:
            self.show(self.current_view)
        self.root.after(30000, self.tick)

    def on_error(self, exc_type, exc, trace):
        logging.error("Desktop callback failed", exc_info=(exc_type, exc, trace))
        messagebox.showerror("操作未完成", f"{exc}\n\n详细信息已写入数据目录的 app.log。", parent=self.root)

    def close(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.persist_session()
        self.store.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="词间 · 托福/SAT 词汇学习助手")
    parser.add_argument("--data-dir", type=Path, help="指定独立的数据目录")
    parser.add_argument("--self-check", action="store_true", help="检查程序及词库后退出")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["VOCAB_DATA_DIR"] = str(args.data_dir.resolve())
    folder = user_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=folder / "app.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        store = Store()
        if args.self_check:
            report = {"version": __version__, "database": str(store.path), "words": store.stats()["total"], "integrity": store.conn.execute("PRAGMA integrity_check").fetchone()[0]}
            (folder / "self-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if sys.stdout:
                print(json.dumps(report, ensure_ascii=False))
            store.close()
            return
        VocabLearner(store).run()
    except Exception as exc:
        logging.exception("Startup failed")
        if args.self_check:
            raise
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("无法启动词间", f"{exc}\n\n数据目录：{folder}\n请查看 app.log 获取详细信息。", parent=root)
        root.destroy()
