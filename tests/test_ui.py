"""Real Tk integration smoke tests. Run with a desktop/display available."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from vocab.app import VocabLearner
from vocab.core import Store


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "desktop.db"
        self.store = Store(self.path)
        self.app = VocabLearner(self.store)
        self.app.root.withdraw()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_all_pages_and_library_search(self):
        for page in ("home", "library", "mistakes", "stats", "settings", "study"):
            self.app.show(page)
            self.app.root.update()
        self.app.show("library")
        self.app.query_var.set("ameliorate")
        self.app.refresh_library()
        self.assertEqual(len(self.app.tree.get_children()), 1)

    def test_reveal_required_and_duplicate_rating_guarded(self):
        self.app.start("study")
        self.app.rate("good")
        self.assertEqual(self.store.stats()["today_reviews"], 0)
        self.app.reveal()
        self.app.rate("good")
        self.app.rate("good")
        self.assertEqual(self.store.stats()["today_reviews"], 1)
        self.assertEqual(self.app.session["index"], 1)

    def test_spelling_answer_is_not_graded_twice(self):
        self.app.start("spelling")
        self.app.spelling.insert(0, self.app.word["word"].upper())
        self.app.check_spelling()
        self.assertEqual(self.store.stats()["today_reviews"], 1)
        self.assertEqual(self.app.session["index"], 1)
        self.app.check_spelling()
        self.assertEqual(self.store.stats()["today_reviews"], 1)

    def test_restart_resumes_next_unanswered_card(self):
        self.app.start("study")
        self.app.reveal()
        self.app.rate("good")
        next_id = self.app.word["id"]
        self.app.close()
        self.store = Store(self.path)
        self.app = VocabLearner(self.store)
        self.app.root.withdraw()
        self.app.show("study")
        self.assertEqual(self.app.word["id"], next_id)
        self.assertEqual(self.app.session["index"], 1)

    def test_wrong_spelling_enters_mistakes_and_hides_word_before_answer(self):
        self.app.start("spelling")
        self.assertNotIn(self.app.word["word"], self.app.word_label.cget("text"))
        self.app.spelling.insert(0, "incorrect spelling")
        self.app.check_spelling()
        self.assertEqual(self.store.stats()["today_correct"], 0)
        self.assertEqual(self.store.stats()["mistakes"], 1)

    def test_page_height_updates_after_switch_and_resize(self):
        self.app.root.deiconify()
        self.app.root.geometry("1000x720")
        self.app.show("home")
        self.app.root.update()
        self.assertGreaterEqual(self.app.content.winfo_height(), self.app.content.winfo_reqheight())
        self.app.start("study")
        self.app.root.update()
        self.assertEqual(self.app.content.winfo_height(), max(self.app.canvas.winfo_height(), self.app.content.winfo_reqheight()))
        self.app.reveal()
        self.app.root.update()
        self.assertEqual(len(self.app.rating_buttons), 4)
        self.assertTrue(all(b.winfo_ismapped() for b in self.app.rating_buttons))


if __name__ == "__main__":
    unittest.main()
