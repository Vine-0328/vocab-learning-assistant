"""SQLite storage and deterministic spaced repetition. No GUI dependencies."""
from __future__ import annotations
import csv
import json
import math
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
 id INTEGER PRIMARY KEY, word TEXT NOT NULL COLLATE NOCASE UNIQUE,
 definition TEXT NOT NULL, example TEXT NOT NULL DEFAULT '',
 deck TEXT NOT NULL DEFAULT '自定义', difficulty TEXT NOT NULL DEFAULT 'medium',
 note TEXT NOT NULL DEFAULT '', favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1)),
 deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)));
CREATE TABLE IF NOT EXISTS progress (
 word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
 repetitions INTEGER NOT NULL DEFAULT 0 CHECK(repetitions>=0),
 interval_days REAL NOT NULL DEFAULT 0 CHECK(interval_days>=0),
 ease REAL NOT NULL DEFAULT 2.5 CHECK(ease>=1.3 AND ease<=3),
 due_at TEXT NOT NULL, last_reviewed TEXT NOT NULL,
 lapses INTEGER NOT NULL DEFAULT 0 CHECK(lapses>=0),
 reviews INTEGER NOT NULL DEFAULT 0 CHECK(reviews>=0),
 correct INTEGER NOT NULL DEFAULT 0 CHECK(correct>=0 AND correct<=reviews));
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
 reviewed_at TEXT NOT NULL, rating TEXT NOT NULL CHECK(rating IN ('again','hard','good','easy')),
 correct INTEGER NOT NULL CHECK(correct IN (0,1)),
 mode TEXT NOT NULL CHECK(mode IN ('study','spelling','legacy')),
 was_new INTEGER NOT NULL CHECK(was_new IN (0,1)));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_due ON progress(due_at);
CREATE INDEX IF NOT EXISTS idx_review_date ON reviews(reviewed_at);
"""
DEFAULTS = {"daily_goal": 70, "deck": "全部", "session_size": 20}
RATINGS = {"again", "hard", "good", "easy"}


def resource_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "data"


def user_data_dir():
    if os.environ.get("VOCAB_DATA_DIR"):
        return Path(os.environ["VOCAB_DATA_DIR"]).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "VocabLearningAssistant"


def stamp(value):
    # Scheduling and daily counters consistently use local wall-clock time.
    return value.replace(microsecond=0).isoformat()


def normalized_word(value):
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


def schedule(previous, rating, now):
    if rating not in RATINGS:
        raise ValueError("无效的掌握程度")
    p = dict(previous or {})
    repetitions, interval, ease = p.get("repetitions", 0), p.get("interval_days", 0), p.get("ease", 2.5)
    if rating == "again":
        interval, repetitions, ease = 10 / 1440, 0, max(1.3, ease - 0.2)
    elif rating == "hard":
        interval, repetitions, ease = max(1, interval * 1.2), repetitions + 1, max(1.3, ease - 0.15)
    elif rating == "good":
        interval = 1 if repetitions == 0 else (3 if repetitions == 1 else max(1, interval * ease))
        repetitions += 1
    else:
        interval = 4 if repetitions == 0 else max(4, interval * ease * 1.3)
        repetitions, ease = repetitions + 1, min(3.0, ease + 0.15)
    interval = min(3650, round(interval, 6))
    return {"repetitions": repetitions, "interval_days": interval, "ease": ease,
            "due_at": stamp(now + timedelta(seconds=round(interval*86400))), "last_reviewed": stamp(now),
            "lapses": p.get("lapses", 0) + int(rating == "again"), "reviews": p.get("reviews", 0) + 1,
            "correct": p.get("correct", 0) + int(rating != "again")}


class Store:
    def __init__(self, path=None, clock=None, seed=True):
        self.path = Path(path) if path else user_data_dir() / "vocabulary.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or datetime.now
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self._initialize()
        self.conn.execute("PRAGMA journal_mode=WAL")
        if seed and not self.get_setting("seed_v2", False):
            self._seed()

    def close(self):
        self.conn.close()

    def _initialize(self):
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(words)")}
        if columns and "deck" not in columns:
            self.database_backup("before-upgrade")
            has_history = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='learning_history'").fetchone()
            self.conn.executescript("BEGIN IMMEDIATE; ALTER TABLE words RENAME TO legacy_words;" +
                ("ALTER TABLE learning_history RENAME TO legacy_history;" if has_history else "") + SCHEMA)
            try:
                self._migrate_legacy_rows()
                self.conn.execute("PRAGMA user_version=2")
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            self.conn.executescript(SCHEMA)
            self.conn.execute("PRAGMA user_version=2")
            self.conn.commit()

    def _migrate_legacy_rows(self):
        id_map = {}
        for row in self.conn.execute("SELECT * FROM legacy_words").fetchall():
            old = dict(row)
            word = normalized_word(str(old.get("word", "")))
            if not word:
                continue
            self.conn.execute("INSERT OR IGNORE INTO words(word,definition,example,deck,difficulty) VALUES(?,?,?,?,?)",
                (word, old.get("definition") or "待补充释义", old.get("example") or "", "旧版词库", old.get("difficulty") or "medium"))
            id_map[old["id"]] = self.conn.execute("SELECT id FROM words WHERE word=?", (word,)).fetchone()[0]
        if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_history'").fetchone():
            for row in self.conn.execute("SELECT * FROM legacy_history ORDER BY review_date,id").fetchall():
                if row["word_id"] not in id_map:
                    continue
                try:
                    when = datetime.fromisoformat(row["review_date"])
                except (ValueError, TypeError):
                    continue
                wid, correct = id_map[row["word_id"]], int(bool(row["correct"]))
                prior = self.conn.execute("SELECT * FROM progress WHERE word_id=?", (wid,)).fetchone()
                self._write_progress(wid, schedule(dict(prior) if prior else None, "good" if correct else "again", when))
                self.conn.execute("INSERT INTO reviews(word_id,reviewed_at,rating,correct,mode,was_new) VALUES(?,?,?,?,?,?)",
                    (wid, stamp(when), "good" if correct else "again", correct, "legacy", int(prior is None)))

    def _seed(self):
        core = json.loads((resource_dir() / "core_words.json").read_text(encoding="utf-8"))
        extra = json.loads((resource_dir() / "6000 words examples.json").read_text(encoding="utf-8"))
        with self.conn:
            for row in core:
                self.conn.execute("INSERT OR IGNORE INTO words(word,definition,example,deck,difficulty) VALUES(?,?,?,?,?)",
                    (normalized_word(row["word"]), row["definition"], row["example"], row["deck"], row.get("difficulty", "medium")))
            for row in extra:
                word, definition = normalized_word(row.get("word", "")), row.get("def", "").strip()
                if word and definition:
                    self.conn.execute("INSERT OR IGNORE INTO words(word,definition,deck) VALUES(?,?,'扩展词库')", (word, definition))
            self._set("seed_v2", True)

    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else DEFAULTS.get(key, default)

    def _set(self, key, value):
        self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, json.dumps(value, ensure_ascii=False)))

    def save_settings(self, daily_goal, deck, session_size):
        if not 1 <= int(daily_goal) <= 500 or not 1 <= int(session_size) <= 200:
            raise ValueError("每日目标应为 1–500，每轮数量应为 1–200")
        if deck not in self.decks():
            raise ValueError("请选择有效的词库")
        with self.conn:
            for key, value in {"daily_goal": int(daily_goal), "deck": deck, "session_size": int(session_size)}.items():
                self._set(key, value)

    def decks(self):
        return ["全部", "核心词库"] + [r[0] for r in self.conn.execute("SELECT DISTINCT deck FROM words WHERE deleted=0 ORDER BY deck") if r[0] not in {"全部", "核心词库"}]

    def _deck_clause(self, deck):
        if not deck or deck == "全部":
            return "", []
        if deck == "核心词库":
            return " AND w.deck IN ('TOEFL','SAT')", []
        return " AND w.deck=?", [deck]

    def get_word(self, word_id):
        row = self.conn.execute("SELECT w.*,p.due_at,p.repetitions,p.interval_days,p.lapses,p.reviews,p.correct FROM words w LEFT JOIN progress p ON p.word_id=w.id WHERE w.id=?", (word_id,)).fetchone()
        if not row:
            raise ValueError("找不到这个单词")
        return dict(row)

    def new_today(self):
        today = self.clock().date()
        return self.conn.execute("SELECT COUNT(DISTINCT word_id) FROM reviews WHERE reviewed_at>=? AND reviewed_at<? AND was_new=1",
            (today.isoformat(), (today+timedelta(days=1)).isoformat())).fetchone()[0]

    def queue(self, mode="study", deck=None, limit=None):
        now = stamp(self.clock())
        limit, deck = limit or self.get_setting("session_size"), deck or self.get_setting("deck")
        clause, args = self._deck_clause(deck)
        base = "SELECT w.* FROM words w LEFT JOIN progress p ON p.word_id=w.id WHERE w.deleted=0" + clause
        due = self.conn.execute(base + " AND p.due_at<=? ORDER BY p.due_at,w.id LIMIT ?", (*args, now, limit)).fetchall()
        if mode == "review":
            rows = due
        elif mode == "mistakes":
            rows = self.conn.execute(base + " AND EXISTS(SELECT 1 FROM reviews r WHERE r.word_id=w.id AND r.rating='again') ORDER BY p.due_at,w.id LIMIT ?", (*args, limit)).fetchall()
        elif mode == "favorites":
            rows = self.conn.execute(base + " AND w.favorite=1 ORDER BY COALESCE(p.due_at,''),w.id LIMIT ?", (*args, limit)).fetchall()
        elif mode == "spelling":
            rows = self.conn.execute(base + " AND p.word_id IS NOT NULL ORDER BY RANDOM() LIMIT ?", (*args, limit)).fetchall()
            if not rows:
                return self.queue("study", deck, limit)
        else:
            remaining = max(0, self.get_setting("daily_goal") - self.new_today())
            fresh = self.conn.execute(base + " AND p.word_id IS NULL ORDER BY CASE WHEN w.deck IN ('TOEFL','SAT') THEN 0 ELSE 1 END,w.id LIMIT ?",
                (*args, min(max(0, limit-len(due)), remaining))).fetchall()
            rows = list(due) + list(fresh)
        return [dict(row) for row in rows]

    def _write_progress(self, wid, p):
        cols = ["repetitions", "interval_days", "ease", "due_at", "last_reviewed", "lapses", "reviews", "correct"]
        self.conn.execute(f"INSERT INTO progress(word_id,{','.join(cols)}) VALUES({','.join('?' for _ in range(9))}) ON CONFLICT(word_id) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols), (wid, *(p[c] for c in cols)))

    def grade(self, word_id, rating, mode="study"):
        if rating not in RATINGS or mode not in {"study", "spelling"}:
            raise ValueError("无效的评分或练习类型")
        with self.conn:
            self.conn.execute("UPDATE words SET favorite=favorite WHERE id=?", (word_id,))
            if self.get_word(word_id)["deleted"]:
                raise ValueError("单词已归档，请重新开始这一轮")
            row = self.conn.execute("SELECT * FROM progress WHERE word_id=?", (word_id,)).fetchone()
            prev, now = dict(row) if row else None, self.clock()
            p = schedule(prev, rating, now)
            # Extra practice before the due time cannot inflate the memory interval.
            if prev and prev["due_at"] > stamp(now) and rating != "again":
                for key in ("repetitions", "interval_days", "ease", "due_at"):
                    p[key] = prev[key]
            self._write_progress(word_id, p)
            self.conn.execute("INSERT INTO reviews(word_id,reviewed_at,rating,correct,mode,was_new) VALUES(?,?,?,?,?,?)",
                (word_id, stamp(now), rating, int(rating != "again"), mode, int(prev is None)))
        return p

    @staticmethod
    def validate_word(row):
        if not isinstance(row, dict):
            raise ValueError("每条词汇必须是一个对象")
        result = {}
        for field, size in {"word": 120, "definition": 4000, "example": 8000, "deck": 60, "difficulty": 60, "note": 8000}.items():
            value = row.get(field, row.get("def", "") if field == "definition" else "")
            value = "" if value is None else value
            if not isinstance(value, str):
                raise ValueError(f"{field} 必须是文本")
            value = normalized_word(value) if field == "word" else value.strip()
            if len(value) > size or "\x00" in value:
                raise ValueError(f"{field} 超出长度限制或含无效字符")
            result[field] = value
        if not result["word"] or not result["definition"]:
            raise ValueError("单词和释义不能为空")
        result["deck"] = result["deck"] or "自定义"
        if result["deck"] in {"全部", "核心词库"}:
            raise ValueError("词库名称不能使用：全部、核心词库")
        result["difficulty"] = result["difficulty"] or "medium"
        return result

    def save_word(self, values, word_id=None):
        clean = self.validate_word(values)
        with self.conn:
            try:
                if word_id:
                    self.get_word(word_id)
                    self.conn.execute("UPDATE words SET word=?,definition=?,example=?,deck=?,difficulty=?,note=? WHERE id=?", (*clean.values(), word_id))
                else:
                    word_id = self.conn.execute("INSERT INTO words(word,definition,example,deck,difficulty,note) VALUES(?,?,?,?,?,?)", tuple(clean.values())).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError("这个单词已存在，请搜索后编辑（也请检查已归档词汇）") from exc
        return word_id

    def toggle_favorite(self, word_id):
        with self.conn:
            self.conn.execute("UPDATE words SET favorite=1-favorite WHERE id=?", (word_id,))

    def archive(self, word_id, archived=True):
        with self.conn:
            self.conn.execute("UPDATE words SET deleted=? WHERE id=?", (int(archived), word_id))

    def search(self, query="", status="全部", deck="全部", limit=1000):
        sql = "SELECT w.*,p.repetitions,p.interval_days,p.due_at,p.lapses,p.reviews,p.correct FROM words w LEFT JOIN progress p ON p.word_id=w.id WHERE w.deleted=?"
        args = [int(status == "已归档")]
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND (w.word LIKE ? ESCAPE '\\' OR w.definition LIKE ? ESCAPE '\\' OR w.note LIKE ? ESCAPE '\\')"
            args.extend([f"%{escaped}%"] * 3)
        clause, deck_args = self._deck_clause(deck)
        sql += clause
        args.extend(deck_args)
        filters = {"未学": "p.word_id IS NULL", "学习中": "p.word_id IS NOT NULL AND NOT(p.repetitions>=3 AND p.interval_days>=21)",
                   "已掌握": "p.repetitions>=3 AND p.interval_days>=21", "收藏": "w.favorite=1",
                   "错词": "EXISTS(SELECT 1 FROM reviews r WHERE r.word_id=w.id AND r.rating='again')"}
        if status in filters:
            sql += " AND " + filters[status]
        if status == "待复习":
            sql += " AND p.due_at<=?"
            args.append(stamp(self.clock()))
        return [dict(r) for r in self.conn.execute(sql+" ORDER BY w.word LIMIT ?", (*args, limit))]

    def stats(self):
        now, today = self.clock(), self.clock().date()
        active = " FROM words w LEFT JOIN progress p ON p.word_id=w.id WHERE w.deleted=0"
        def count(condition="", args=()):
            return self.conn.execute("SELECT COUNT(*)"+active+condition, args).fetchone()[0]
        rev = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(correct),0),COUNT(DISTINCT word_id) FROM reviews WHERE reviewed_at>=? AND reviewed_at<?", (today.isoformat(), (today+timedelta(days=1)).isoformat())).fetchone()
        days = {r[0] for r in self.conn.execute("SELECT DISTINCT substr(reviewed_at,1,10) FROM reviews WHERE reviewed_at<?", ((today+timedelta(days=1)).isoformat(),))}
        cursor, streak = today if today.isoformat() in days else today-timedelta(days=1), 0
        while cursor.isoformat() in days:
            streak += 1
            cursor -= timedelta(days=1)
        history, forecast = [], []
        for offset in range(13, -1, -1):
            day = today-timedelta(days=offset)
            row = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(correct),0) FROM reviews WHERE reviewed_at>=? AND reviewed_at<?", (day.isoformat(), (day+timedelta(days=1)).isoformat())).fetchone()
            history.append({"day": day.isoformat(), "total": row[0], "correct": row[1]})
        for offset in range(7):
            day = today+timedelta(days=offset)
            condition = " AND p.due_at<?" + (" AND p.due_at>=?" if offset else "")
            args = [(day+timedelta(days=1)).isoformat()] + ([day.isoformat()] if offset else [])
            forecast.append({"day": day.isoformat(), "total": count(condition, args)})
        return {"total": count(), "learned": count(" AND p.word_id IS NOT NULL"),
                "mastered": count(" AND p.repetitions>=3 AND p.interval_days>=21"),
                "due": count(" AND p.due_at<=?", (stamp(now),)), "new_today": self.new_today(),
                "today_reviews": rev[0], "today_correct": rev[1], "today_words": rev[2], "streak": streak,
                "history": history, "forecast": forecast,
                "mistakes": count(" AND EXISTS(SELECT 1 FROM reviews r WHERE r.word_id=w.id AND r.rating='again')")}

    def import_words(self, path):
        path = Path(path)
        if path.stat().st_size > 30_000_000:
            raise ValueError("词库文件不能超过 30 MB")
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        else:
            content = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(content, dict):
                rows = []
                for deck, words in content.items():
                    if not isinstance(words, list):
                        raise ValueError("分组词库的每个分组必须是数组")
                    rows.extend(dict(row, deck=deck) if isinstance(row, dict) else row for row in words)
            elif isinstance(content, list):
                rows = content
            else:
                raise ValueError("JSON 词库必须是数组或分组对象")
        if not rows or len(rows) > 100000:
            raise ValueError("词库必须包含 1–100000 条记录")
        validated = []
        for index, row in enumerate(rows, 1):
            try:
                validated.append(self.validate_word(row))
            except ValueError as exc:
                raise ValueError(f"第 {index} 条：{exc}。本次导入未写入任何数据。") from exc
        added = 0
        with self.conn:
            for row in validated:
                added += self.conn.execute("INSERT OR IGNORE INTO words(word,definition,example,deck,difficulty,note) VALUES(?,?,?,?,?,?)", tuple(row.values())).rowcount
        return added, len(validated)-added

    def export_csv(self, path, rows=None):
        rows = self.search(limit=100000) if rows is None else rows
        with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
            fields = ["word", "definition", "example", "deck", "difficulty", "note"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: "'"+str(row.get(k, "")) if str(row.get(k, "")).lstrip().startswith(("=", "+", "-", "@")) else row.get(k, "") for k in fields})

    def database_backup(self, label="automatic"):
        folder = self.path.parent / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / f"{label}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        dest = sqlite3.connect(target)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        return target

    def export_backup(self, path):
        data = {"app": "vocab-learning-assistant", "version": 2, "created_at": stamp(self.clock())}
        for table in ("words", "progress", "reviews", "settings"):
            data[table] = [dict(r) for r in self.conn.execute(f"SELECT * FROM {table}")]
        target = Path(path)
        temp = target.with_name(target.name+".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(target)

    def restore_backup(self, path):
        path = Path(path)
        if path.stat().st_size > 100_000_000:
            raise ValueError("备份不能超过 100 MB")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("app") != "vocab-learning-assistant" or data.get("version") != 2:
            raise ValueError("不是受支持的完整备份文件；普通词库请使用导入词库")
        temp = sqlite3.connect(":memory:")
        temp.execute("PRAGMA foreign_keys=ON")
        temp.executescript(SCHEMA)
        try:
            for table in ("words", "progress", "reviews", "settings"):
                rows = data.get(table)
                if not isinstance(rows, list):
                    raise ValueError(f"备份缺少 {table} 数据")
                cols = [r[1] for r in temp.execute(f"PRAGMA table_info({table})")]
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(cols):
                        raise ValueError(f"备份中的 {table} 字段不完整")
                    if table == "words":
                        self.validate_word(row)
                        integer_fields = ("id", "favorite", "deleted")
                    elif table == "progress":
                        integer_fields = ("word_id", "repetitions", "lapses", "reviews", "correct")
                    elif table == "reviews":
                        integer_fields = ("id", "word_id", "correct", "was_new")
                    else:
                        integer_fields = ()
                    if any(type(row[k]) is not int or row[k] < 0 for k in integer_fields):
                        raise ValueError(f"备份中的 {table} 包含无效整数")
                    if table in {"reviews", "progress"}:
                        for key in ("reviewed_at",) if table == "reviews" else ("due_at", "last_reviewed"):
                            parsed = datetime.fromisoformat(row[key])
                            if parsed.tzinfo or stamp(parsed) != row[key]:
                                raise ValueError("备份日期必须是本地 ISO 秒精度时间")
                        if table == "progress" and any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ("ease", "interval_days")):
                            raise ValueError("备份包含无效数值")
                    if table == "settings":
                        json.loads(row["value"])
                    temp.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", [row[c] for c in cols])
            settings = {r[0]: json.loads(r[1]) for r in temp.execute("SELECT * FROM settings")}
            for key, upper in (("daily_goal", 500), ("session_size", 200)):
                if type(settings.get(key, DEFAULTS[key])) is not int or not 1 <= settings.get(key, DEFAULTS[key]) <= upper:
                    raise ValueError("备份中的学习目标无效")
            if not isinstance(settings.get("deck", "全部"), str):
                raise ValueError("备份中的词库设置无效")
            safety = self.database_backup("before-restore")
            with self.conn:
                for table in ("reviews", "progress", "words", "settings"):
                    self.conn.execute(f"DELETE FROM {table}")
                for table in ("words", "progress", "reviews", "settings"):
                    cols = [r[1] for r in temp.execute(f"PRAGMA table_info({table})")]
                    self.conn.executemany(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", temp.execute(f"SELECT * FROM {table}").fetchall())
                self._set("seed_v2", True)
                self._set("session_v2", {})
            return safety
        except (sqlite3.Error, TypeError, KeyError, OverflowError) as exc:
            raise ValueError(f"备份数据无效：{exc}") from exc
        finally:
            temp.close()

    def import_legacy_database(self, path):
        source = Path(path).resolve()
        if source == self.path.resolve():
            raise ValueError("当前文件已经是正在使用的数据库")
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            copy_path = Path(folder) / "legacy.db"
            src = sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)
            dest = sqlite3.connect(copy_path)
            try:
                cols = {r[1] for r in src.execute("PRAGMA table_info(words)")}
                if "mastery_level" not in cols or "deck" in cols:
                    raise ValueError("请选择原版程序产生的 vocabulary.db")
                src.backup(dest)
            finally:
                src.close()
                dest.close()
            old = Store(copy_path, clock=self.clock, seed=False)
            self.database_backup("before-legacy-import")
            try:
                with self.conn:
                    for row in old.conn.execute("SELECT * FROM words"):
                        self.conn.execute("INSERT OR IGNORE INTO words(word,definition,example,deck,difficulty) VALUES(?,?,?,?,?)", (row["word"], row["definition"], row["example"], row["deck"], row["difficulty"]))
                        wid = self.conn.execute("SELECT id FROM words WHERE word=?", (row["word"],)).fetchone()[0]
                        if self.conn.execute("SELECT 1 FROM progress WHERE word_id=?", (wid,)).fetchone():
                            continue
                        p = old.conn.execute("SELECT * FROM progress WHERE word_id=?", (row["id"],)).fetchone()
                        if p:
                            self._write_progress(wid, dict(p))
                            for r in old.conn.execute("SELECT * FROM reviews WHERE word_id=?", (row["id"],)):
                                self.conn.execute("INSERT INTO reviews(word_id,reviewed_at,rating,correct,mode,was_new) VALUES(?,?,?,?,?,?)", (wid, r["reviewed_at"], r["rating"], r["correct"], r["mode"], r["was_new"]))
            finally:
                old.close()
