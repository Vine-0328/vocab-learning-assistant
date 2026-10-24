import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from vocab.core import Store, normalized_word, schedule


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.now = datetime(2026, 10, 24, 23, 55)
        self.store = Store(self.folder / "test.db", clock=lambda: self.now, seed=False)
        self.ids = [self.store.save_word({"word": w, "definition": "释义："+w, "deck": "TOEFL"}) for w in ("alpha", "beta", "gamma", "delta")]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def json_file(self, content, name="input.json"):
        p = self.folder / name
        p.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return p

    def test_restart_preserves_progress_and_settings(self):
        self.store.grade(self.ids[0], "good")
        self.store.save_settings(3, "TOEFL", 2)
        self.store.close()
        self.store = Store(self.folder / "test.db", clock=lambda: self.now, seed=False)
        self.assertEqual(self.store.new_today(), 1)
        self.assertEqual(self.store.get_setting("daily_goal"), 3)
        self.assertNotIn(self.ids[0], [w["id"] for w in self.store.queue()])

    def test_new_word_goal_and_due_reviews_are_separate(self):
        self.store.save_settings(1, "全部", 20)
        self.store.grade(self.ids[0], "again")
        self.assertEqual(self.store.queue(), [])
        self.now += timedelta(minutes=11)
        # Local midnight resets the daily new-word counter, but the failed card is due first.
        self.assertEqual(self.store.new_today(), 0)
        self.assertEqual(self.store.queue()[0]["id"], self.ids[0])
        self.assertEqual(len(self.store.queue()), 2)

    def test_same_day_goal_counts_distinct_new_words(self):
        self.store.save_settings(1, "全部", 20)
        self.store.grade(self.ids[0], "good")
        self.store.grade(self.ids[0], "good")
        self.assertEqual(self.store.new_today(), 1)
        self.assertEqual(self.store.queue(), [])
        self.assertEqual(self.store.stats()["today_reviews"], 2)

    def test_again_is_due_in_ten_minutes(self):
        p = self.store.grade(self.ids[0], "again")
        self.assertEqual(datetime.fromisoformat(p["due_at"]), self.now+timedelta(minutes=10))
        self.assertFalse(self.store.queue("review"))
        self.now += timedelta(minutes=10)
        self.assertEqual(len(self.store.queue("review")), 1)

    def test_early_practice_cannot_inflate_interval(self):
        first = self.store.grade(self.ids[0], "easy")
        for _ in range(5):
            result = self.store.grade(self.ids[0], "easy", "spelling")
        self.assertEqual(result["due_at"], first["due_at"])
        self.assertEqual(result["repetitions"], 1)
        self.assertEqual(result["reviews"], 6)

    def test_forgetting_resets_mastery_and_appears_in_mistakes(self):
        self.store.grade(self.ids[0], "easy")
        p = self.store.grade(self.ids[0], "again", "spelling")
        self.assertEqual(p["repetitions"], 0)
        self.assertEqual(p["lapses"], 1)
        self.assertEqual(len(self.store.search(status="错词")), 1)
        self.assertEqual(self.store.stats()["today_correct"], 1)

    def test_long_term_mastery_requires_real_due_reviews(self):
        for _ in range(4):
            p = self.store.grade(self.ids[0], "easy")
            self.now = datetime.fromisoformat(p["due_at"])
        self.assertEqual(self.store.stats()["mastered"], 1)
        self.assertEqual(self.store.search(status="已掌握")[0]["word"], "alpha")

    def test_deck_filter_and_due_priority(self):
        other = self.store.save_word({"word": "extra", "definition": "扩展", "deck": "扩展词库"})
        self.store.grade(other, "again")
        self.now += timedelta(minutes=11)
        self.assertNotIn(other, [r["id"] for r in self.store.queue(deck="核心词库")])
        self.assertEqual(self.store.queue(deck="全部")[0]["id"], other)

    def test_archive_can_be_reversed_without_losing_history(self):
        self.store.grade(self.ids[0], "again")
        self.store.archive(self.ids[0])
        self.assertEqual(self.store.stats()["total"], 3)
        self.assertEqual(len(self.store.search(status="已归档")), 1)
        with self.assertRaises(ValueError):
            self.store.grade(self.ids[0], "good")
        self.store.archive(self.ids[0], False)
        self.assertEqual(self.store.get_word(self.ids[0])["lapses"], 1)

    def test_favorites_and_notes(self):
        self.store.toggle_favorite(self.ids[1])
        row = self.store.get_word(self.ids[1])
        row["note"] = "我的联想笔记"
        self.store.save_word(row, self.ids[1])
        self.assertEqual(self.store.search("联想")[0]["word"], "beta")
        self.assertEqual(self.store.queue("favorites")[0]["word"], "beta")

    def test_import_normalizes_and_skips_duplicates(self):
        path = self.json_file([{"word": " ALPHA ", "definition": "重复"}, {"word": "ＥＰＳＩＬＯＮ", "def": "第五"}])
        self.assertEqual(self.store.import_words(path), (1, 1))
        self.assertEqual(self.store.search("epsilon")[0]["definition"], "第五")

    def test_grouped_json_and_original_def_format(self):
        p = self.json_file({"SAT": [{"word": "epsilon", "def": "第五"}]})
        self.store.import_words(p)
        self.assertEqual(self.store.search(deck="SAT")[0]["word"], "epsilon")

    def test_invalid_import_is_atomic(self):
        path = self.json_file([{"word": "epsilon", "definition": "第五"}, {"word": "broken"}])
        with self.assertRaises(ValueError):
            self.store.import_words(path)
        self.assertEqual(len(self.store.search()), 4)

    def test_csv_chinese_multiline_round_trip(self):
        self.store.save_word({"word": "epsilon", "definition": "第五，希腊字母", "example": 'A "quoted", example.\n第二行', "note": "中文笔记"})
        p = self.folder / "words.csv"
        self.store.export_csv(p)
        other = Store(self.folder / "other.db", seed=False)
        try:
            self.assertEqual(other.import_words(p), (5, 0))
            self.assertIn("第二行", other.search("epsilon")[0]["example"])
        finally:
            other.close()

    def test_csv_formula_is_neutralized(self):
        self.store.save_word({"word": "=formula", "definition": "+command"})
        p = self.folder / "export.csv"
        self.store.export_csv(p)
        self.assertIn("'=formula", p.read_text(encoding="utf-8-sig"))

    def test_search_percent_underscore_and_quotes_are_literal(self):
        self.assertFalse(self.store.search("%"))
        self.assertFalse(self.store.search("_"))
        self.assertFalse(self.store.search("' OR 1=1 --"))

    def test_backup_restore_round_trip(self):
        self.store.grade(self.ids[0], "again")
        self.store.toggle_favorite(self.ids[1])
        self.store.save_settings(5, "TOEFL", 3)
        p = self.folder / "backup.json"
        self.store.export_backup(p)
        self.store.archive(self.ids[0])
        self.store.save_word({"word": "newword", "definition": "新词"})
        safety = self.store.restore_backup(p)
        self.assertTrue(safety.exists())
        self.assertEqual(self.store.stats()["total"], 4)
        self.assertEqual(self.store.stats()["today_reviews"], 1)
        self.assertEqual(self.store.get_setting("daily_goal"), 5)
        self.assertTrue(self.store.get_word(self.ids[1])["favorite"])

    def test_corrupt_backup_cannot_replace_live_data(self):
        p = self.folder / "backup.json"
        self.store.export_backup(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["reviews"] = [{"id": 1, "word_id": 9999, "reviewed_at": "2026-10-24T12:00:00", "rating": "good", "correct": 1, "mode": "study", "was_new": 1}]
        self.json_file(data, "backup.json")
        with self.assertRaises(ValueError):
            self.store.restore_backup(p)
        self.assertEqual(self.store.stats()["total"], 4)

    def test_invalid_backup_settings_rejected(self):
        p = self.folder / "backup.json"
        self.store.export_backup(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["settings"].append({"key": "daily_goal", "value": "0"})
        self.json_file(data, "backup.json")
        with self.assertRaises(ValueError):
            self.store.restore_backup(p)
        self.assertEqual(self.store.get_setting("daily_goal"), 70)

    def test_text_in_numeric_backup_field_rejected(self):
        self.store.grade(self.ids[0], "good")
        p = self.folder / "backup.json"
        self.store.export_backup(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["progress"][0]["repetitions"] = "broken"
        self.json_file(data, "backup.json")
        with self.assertRaises(ValueError):
            self.store.restore_backup(p)
        self.assertEqual(self.store.get_word(self.ids[0])["repetitions"], 1)

    def test_local_streak_and_forecast(self):
        self.now = datetime(2026, 10, 23, 23, 59)
        self.store.grade(self.ids[0], "good")
        self.now += timedelta(minutes=2)
        self.assertEqual(self.store.stats()["streak"], 1)
        self.store.grade(self.ids[1], "good")
        s = self.store.stats()
        self.assertEqual(s["streak"], 2)
        self.assertEqual(s["history"][-1]["total"], 1)
        self.assertEqual(s["forecast"][0]["total"], 1)
        self.assertEqual(s["forecast"][1]["total"], 1)

    def test_legacy_import_is_idempotent_and_preserves_original(self):
        old_path = self.folder / "old.db"
        conn = sqlite3.connect(old_path)
        conn.executescript("CREATE TABLE words(id INTEGER PRIMARY KEY,word TEXT,definition TEXT,example TEXT,difficulty TEXT,last_reviewed DATE,mastery_level INTEGER); CREATE TABLE learning_history(id INTEGER PRIMARY KEY,word_id INTEGER,review_date DATE,correct BOOLEAN);")
        conn.execute("INSERT INTO words VALUES(1,'alpha','旧释义','Example','TOEFL',NULL,0)")
        conn.execute("INSERT INTO learning_history VALUES(1,1,'2026-10-23',1)")
        conn.commit()
        conn.close()
        original = old_path.read_bytes()
        self.store.import_legacy_database(old_path)
        self.store.import_legacy_database(old_path)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 1)
        self.assertEqual(old_path.read_bytes(), original)

    def test_invalid_settings_do_not_mutate(self):
        for goal, deck, size in [(0, "全部", 20), (10, "missing", 20), (10, "全部", 0)]:
            with self.assertRaises(ValueError):
                self.store.save_settings(goal, deck, size)
        self.assertEqual(self.store.get_setting("daily_goal"), 70)


class BundledDataTests(unittest.TestCase):
    def test_bundled_vocabulary_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            s = Store(Path(folder) / "words.db")
            self.assertEqual(s.stats()["total"], 6014)
            self.assertEqual(len(s.search(deck="核心词库")), 100)
            self.assertTrue(all(w["example"] for w in s.search(deck="核心词库")))
            s.close()
            s = Store(Path(folder) / "words.db")
            self.assertEqual(s.stats()["total"], 6014)
            self.assertEqual(s.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            s.close()


if __name__ == "__main__":
    unittest.main()
