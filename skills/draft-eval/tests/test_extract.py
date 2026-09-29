import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import extract  # noqa: E402


class DeckTest(unittest.TestCase):
    def test_selftest_fixture(self):
        # State grouping and notes alignment, on a synthetic deck shaped like the generator's output.
        extract.selftest()


def words(n, w="word"):
    return " ".join([w] * n)


ARTICLE = f"""---
title: ignored front matter
---
# Title

*Dek line.*

Intro paragraph.

## First

{words(250, 'a')}

{words(200, 'b')}

```
## not a heading
```

{words(100, 'c')}

## Second

Short.

---

```
References:   something
```
"""


class ArticleTest(unittest.TestCase):
    def setUp(self):
        self.doc = extract.extract_article(ARTICLE)
        self.units = self.doc["units"]

    def test_ids_and_parts(self):
        self.assertEqual([u["id"] for u in self.units], ["s0-p1", "s1-p1", "s1-p2", "s2-p1"])

    def test_parts_at_most_400_words(self):
        for u in self.units:
            self.assertLessEqual(u["words"], 400)
        self.assertEqual(self.units[2]["text"].split()[0], "b")

    def test_fence_is_not_a_heading(self):
        self.assertIn("## not a heading", self.units[2]["text"])

    def test_back_matter_is_references_not_a_unit(self):
        self.assertIn("References:", self.doc["references"])
        self.assertNotIn("References", self.units[-1]["text"])
        self.assertEqual(self.doc["title"], "Title")

    def test_stable(self):
        self.assertEqual(extract.extract_article(ARTICLE), self.doc)


class ReviewFixTest(unittest.TestCase):
    def test_long_paragraph_is_split_under_400_words(self):
        sentence = words(29, "x") + "."  # 29 words
        md = "## Long\n\n" + " ".join([sentence] * 30) + "\n\n" + words(500, "y") + "\n"
        units = extract.extract_article(md)["units"]
        self.assertGreater(len(units), 2)
        for u in units:
            self.assertLessEqual(u["words"], 400)
        self.assertEqual(sum(u["words"] for u in units), 29 * 30 + 500)
        self.assertTrue(units[0]["text"].endswith("."))  # split at a sentence end

    def test_tilde_and_nested_fences_hide_headings_and_rules(self):
        md = (
            "## One\n\nBody.\n\n"
            "~~~\n## tilde heading\n---\n~~~\n\n"
            "````\n```\n## nested heading\n```\n---\n````\n\n"
            "After.\n\n## Two\n\nEnd.\n"
        )
        doc = extract.extract_article(md)
        self.assertEqual([u["id"] for u in doc["units"]], ["s1-p1", "s2-p1"])
        self.assertIn("## nested heading", doc["units"][0]["text"])
        self.assertIn("After.", doc["units"][0]["text"])
        self.assertEqual(doc["references"], "")


if __name__ == "__main__":
    unittest.main()
