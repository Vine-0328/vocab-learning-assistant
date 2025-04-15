import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import random
from datetime import datetime
import json

class VocabLearner:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("托福/SAT词汇学习助手")
        self.root.geometry("800x600")
        
        # 初始化数据库
        self.init_database()
        
        # 创建主界面
        self.create_gui()
        
        # 当前学习的单词
        self.current_word = None
        self.words_learned_today = []
        
    def init_database(self):
        self.conn = sqlite3.connect('vocabulary.db')
        self.cursor = self.conn.cursor()
        
        # 创建单词表
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            definition TEXT NOT NULL,
            example TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            last_reviewed DATE,
            mastery_level INTEGER DEFAULT 0
        )''')
        
        # 创建学习记录表
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_history (
            id INTEGER PRIMARY KEY,
            word_id INTEGER,
            review_date DATE,
            correct BOOLEAN,
            FOREIGN KEY (word_id) REFERENCES words (id)
        )''')
        
        self.conn.commit()
        
    def create_gui(self):
        # 创建主框架
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 进度显示
        self.progress_var = tk.StringVar(value="今日进度: 0/70")
        ttk.Label(self.main_frame, textvariable=self.progress_var, font=('Arial', 12)).grid(row=0, column=0, pady=10)
        
        # 单词显示区域
        self.word_display = ttk.Label(self.main_frame, text="点击开始学习", font=('Arial', 24))
        self.word_display.grid(row=1, column=0, pady=20)
        
        # 释义和例句区域（初始隐藏）
        self.meaning_text = tk.Text(self.main_frame, height=6, width=60, font=('Arial', 12))
        self.meaning_text.grid(row=2, column=0, pady=10)
        self.meaning_text.insert('1.0', "点击显示释义查看详细信息")
        self.meaning_text.config(state='disabled')
        
        # 按钮区域
        button_frame = ttk.Frame(self.main_frame)
        button_frame.grid(row=3, column=0, pady=20)
        
        ttk.Button(button_frame, text="开始学习", command=self.next_word).grid(row=0, column=0, padx=5)
        ttk.Button(button_frame, text="显示释义", command=self.show_meaning).grid(row=0, column=1, padx=5)
        ttk.Button(button_frame, text="认识", command=lambda: self.mark_word(True)).grid(row=0, column=2, padx=5)
        ttk.Button(button_frame, text="不认识", command=lambda: self.mark_word(False)).grid(row=0, column=3, padx=5)
        
    def next_word(self):
        # 从数据库中获取一个新单词
        self.cursor.execute('''
        SELECT * FROM words 
        WHERE id NOT IN (SELECT word_id FROM learning_history WHERE review_date = DATE('now'))
        ORDER BY RANDOM() LIMIT 1
        ''')
        word_data = self.cursor.fetchone()
        
        if word_data:
            self.current_word = word_data
            self.word_display.config(text=word_data[1])  # 显示单词
            self.meaning_text.config(state='normal')
            self.meaning_text.delete('1.0', tk.END)
            self.meaning_text.insert('1.0', "点击"显示释义"查看详细信息")
            self.meaning_text.config(state='disabled')
        else:
            messagebox.showinfo("完成", "今天的学习任务已完成！")
            
    def show_meaning(self):
        if self.current_word:
            self.meaning_text.config(state='normal')
            self.meaning_text.delete('1.0', tk.END)
            meaning_text = f"释义：{self.current_word[2]}\n\n例句：{self.current_word[3]}"
            self.meaning_text.insert('1.0', meaning_text)
            self.meaning_text.config(state='disabled')
            
    def mark_word(self, known):
        if self.current_word:
            # 记录学习历史
            self.cursor.execute('''
            INSERT INTO learning_history (word_id, review_date, correct)
            VALUES (?, DATE('now'), ?)
            ''', (self.current_word[0], known))
            
            # 更新掌握度
            new_mastery = self.current_word[6] + (1 if known else -1)
            self.cursor.execute('''
            UPDATE words SET mastery_level = ?, last_reviewed = DATE('now')
            WHERE id = ?
            ''', (new_mastery, self.current_word[0]))
            
            self.conn.commit()
            self.words_learned_today.append(self.current_word[0])
            
            # 更新进度
            self.progress_var.set(f"今日进度: {len(self.words_learned_today)}/70")
            
            # 获取下一个单词
            self.next_word()
            
    def run(self):
        self.root.mainloop()
        
    def __del__(self):
        self.conn.close()

# 添加示例单词数据的函数
def add_sample_words():
    vocab_learner = VocabLearner()
    sample_words = [
        ("ameliorate", "改善，改进", "The new policies are designed to ameliorate the living conditions of the poor.", "TOEFL"),
        ("ephemeral", "短暂的，瞬息的", "Fame in the entertainment industry can be ephemeral.", "SAT"),
        ("ubiquitous", "无所不在的，普遍的", "Mobile phones have become ubiquitous in modern society.", "TOEFL"),
        # 可以继续添加更多单词...
    ]
    
    for word in sample_words:
        vocab_learner.cursor.execute('''
        INSERT OR IGNORE INTO words (word, definition, example, difficulty)
        VALUES (?, ?, ?, ?)
        ''', word)
    
    vocab_learner.conn.commit()
    return vocab_learner

if __name__ == "__main__":
    # 首次运行时添加示例单词
    learner = add_sample_words()
    learner.run()