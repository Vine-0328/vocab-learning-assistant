import json
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

DAILY_GOAL = 70


class VocabLearner:
    """主应用类，负责管理界面、数据库和学习流程。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("托福/SAT词汇学习助手")
        self.root.geometry("800x600")

        self.daily_goal = DAILY_GOAL
        self.current_word = None

        self.init_database()
        self.create_gui()
        self.update_progress()

    def init_database(self):
        """初始化 SQLite 数据库并确保基础数据存在。"""
        self.conn = sqlite3.connect("vocabulary.db")
        self.cursor = self.conn.cursor()

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY,
                word TEXT NOT NULL,
                definition TEXT NOT NULL,
                example TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                last_reviewed DATE,
                mastery_level INTEGER DEFAULT 0
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_history (
                id INTEGER PRIMARY KEY,
                word_id INTEGER,
                review_date DATE,
                correct BOOLEAN,
                FOREIGN KEY (word_id) REFERENCES words (id)
            )
            """
        )

        self.conn.commit()
        self.ensure_initial_data()

    def ensure_initial_data(self):
        """如果数据库为空，则尝试导入默认词汇数据。"""
        self.cursor.execute("SELECT COUNT(*) FROM words")
        word_count = self.cursor.fetchone()[0]
        if word_count:
            return

        imported = self.load_words_from_json()
        if not imported:
            self.insert_sample_words()

    def load_words_from_json(self):
        """从 data/word_list.json 导入词汇数据。"""
        data_path = Path(__file__).resolve().parent / "data" / "word_list.json"
        if not data_path.exists():
            return False

        try:
            with data_path.open("r", encoding="utf-8") as file:
                vocab_data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return False

        entries = []
        for difficulty, words in vocab_data.items():
            for item in words:
                word = item.get("word")
                definition = item.get("definition", "暂无释义")
                example = item.get("example", "暂无例句")
                if word:
                    entries.append((word, definition, example, difficulty))

        if not entries:
            return False

        self.cursor.executemany(
            """
            INSERT OR IGNORE INTO words (word, definition, example, difficulty)
            VALUES (?, ?, ?, ?)
            """,
            entries,
        )
        self.conn.commit()
        return True

    def insert_sample_words(self):
        """插入少量示例单词，便于首次体验。"""
        sample_words = [
            (
                "ameliorate",
                "改善，改进",
                "The new policies are designed to ameliorate the living conditions of the poor.",
                "TOEFL",
            ),
            (
                "ephemeral",
                "短暂的，瞬息的",
                "Fame in the entertainment industry can be ephemeral.",
                "SAT",
            ),
            (
                "ubiquitous",
                "无所不在的，普遍的",
                "Mobile phones have become ubiquitous in modern society.",
                "TOEFL",
            ),
        ]

        self.cursor.executemany(
            """
            INSERT OR IGNORE INTO words (word, definition, example, difficulty)
            VALUES (?, ?, ?, ?)
            """,
            sample_words,
        )
        self.conn.commit()

    def create_gui(self):
        """创建图形界面组件。"""
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.progress_var = tk.StringVar(value="今日进度: 0/70")
        ttk.Label(self.main_frame, textvariable=self.progress_var, font=("Arial", 12)).grid(
            row=0, column=0, pady=10
        )

        self.word_display = ttk.Label(self.main_frame, text="点击开始学习", font=("Arial", 24))
        self.word_display.grid(row=1, column=0, pady=20)

        self.meaning_text = tk.Text(self.main_frame, height=6, width=60, font=("Arial", 12))
        self.meaning_text.grid(row=2, column=0, pady=10)
        self.set_meaning_placeholder()

        button_frame = ttk.Frame(self.main_frame)
        button_frame.grid(row=3, column=0, pady=20)

        ttk.Button(button_frame, text="开始学习", command=self.next_word).grid(row=0, column=0, padx=5)
        ttk.Button(button_frame, text="显示释义", command=self.show_meaning).grid(row=0, column=1, padx=5)
        ttk.Button(button_frame, text="认识", command=lambda: self.mark_word(True)).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(button_frame, text="不认识", command=lambda: self.mark_word(False)).grid(
            row=0, column=3, padx=5
        )

    def set_meaning_placeholder(self, message="点击“显示释义”查看详细信息"):
        self.meaning_text.config(state="normal")
        self.meaning_text.delete("1.0", tk.END)
        self.meaning_text.insert("1.0", message)
        self.meaning_text.config(state="disabled")

    def get_today_progress(self):
        self.cursor.execute("SELECT COUNT(*) FROM learning_history WHERE review_date = DATE('now')")
        return self.cursor.fetchone()[0]

    def update_progress(self):
        learned = self.get_today_progress()
        self.progress_var.set(f"今日进度: {learned}/{self.daily_goal}")

    def next_word(self):
        if self.get_today_progress() >= self.daily_goal:
            messagebox.showinfo("完成", "今天的学习任务已完成！")
            self.word_display.config(text="今日学习已完成")
            self.set_meaning_placeholder("太棒了！明天继续加油～")
            self.current_word = None
            return

        self.cursor.execute(
            """
            SELECT * FROM words
            WHERE id NOT IN (
                SELECT word_id FROM learning_history WHERE review_date = DATE('now')
            )
            ORDER BY RANDOM()
            LIMIT 1
            """
        )
        word_data = self.cursor.fetchone()

        if word_data:
            self.current_word = word_data
            self.word_display.config(text=word_data[1])
            self.set_meaning_placeholder()
        else:
            self.current_word = None
            self.word_display.config(text="暂无可学习的单词")
            self.set_meaning_placeholder("请稍后再试或导入更多词汇。")
            messagebox.showinfo("提示", "数据库中没有更多可学习的单词，请导入新词汇。")

    def show_meaning(self):
        if not self.current_word:
            return

        _, _, definition, example, *_ = self.current_word
        example = example.strip() or "暂无例句"

        meaning_text = f"释义：{definition}\n\n例句：{example}"
        self.meaning_text.config(state="normal")
        self.meaning_text.delete("1.0", tk.END)
        self.meaning_text.insert("1.0", meaning_text)
        self.meaning_text.config(state="disabled")

    def mark_word(self, known: bool):
        if not self.current_word:
            return

        word_id = self.current_word[0]
        mastery_level = self.current_word[6]
        new_mastery = max(0, mastery_level + (1 if known else -1))

        self.cursor.execute(
            """
            INSERT INTO learning_history (word_id, review_date, correct)
            VALUES (?, DATE('now'), ?)
            """,
            (word_id, int(known)),
        )

        self.cursor.execute(
            """
            UPDATE words
            SET mastery_level = ?, last_reviewed = DATE('now')
            WHERE id = ?
            """,
            (new_mastery, word_id),
        )

        self.conn.commit()
        self.update_progress()
        self.next_word()

    def run(self):
        self.root.mainloop()

    def __del__(self):
        try:
            self.conn.close()
        except AttributeError:
            pass


if __name__ == "__main__":
    learner = VocabLearner()
    learner.run()
