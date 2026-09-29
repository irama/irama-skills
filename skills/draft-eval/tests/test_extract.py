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


if __name__ == "__main__":
    unittest.main()
