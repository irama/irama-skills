import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check  # noqa: E402


def unit(uid, role="content", layout="a", text="", notes="", primary=0, hidden=False):
    return {"id": uid, "role": role, "layout": layout, "text": text, "notes": notes,
            "primary_index": primary, "hidden": hidden, "ordinal": primary + 1}


BANNED = [{"term": "\u2014", "case_sensitive": True},
          {"term": "GRADE", "case_sensitive": True},
          {"term": "call to action", "case_sensitive": False}]


class CheckTest(unittest.TestCase):
    def test_banned_terms_respect_case(self):
        units = [unit("a", text="a grade of B"), unit("b", notes="GRADE it \u2014 now"),
                 unit("c", text="Call To Action")]
        hits = check.banned_hits(units, BANNED)
        self.assertEqual([(h["id"], h["term"]) for h in hits],
                         [("b", "\u2014"), ("b", "GRADE"), ("c", "call to action")])

    def test_hook_needs_a_later_payoff(self):
        units = [unit("a", notes="[payoff:early] [hook:cat]"), unit("b", text="[payoff:cat]"),
                 unit("c", notes="[hook:dog]"), unit("d", notes="[hook:early]")]
        self.assertEqual(check.unpaid_hooks(units), [{"id": "c", "hook": "dog"},
                                                     {"id": "d", "hook": "early"}])

    def test_visual_gate_only_on_content(self):
        html = ('<deck-stage><section><p>x</p></section>'
                '<section><div><svg></svg></div></section>'
                '<section><p>no picture</p></section></deck-stage>')
        self.assertEqual(check.visual_tags(html), [set(), {"svg"}, set()])
        units = [unit("t", role="title", primary=0), unit("v", primary=1), unit("n", primary=2)]
        self.assertEqual(check.missing_visual(units, check.visual_tags(html)), ["n"])

    def test_floors_block_regression_only(self):
        floors = {"a": {"words": 40, "min_font": 20}, "b": {"words": 40, "min_font": 20}}
        now = {"a": {"words": 41, "min_font": 20}, "b": {"words": 30, "min_font": 18},
               "new": {"words": 999, "min_font": 1}}
        self.assertEqual(check.floor_breaches(now, floors),
                         [{"id": "a", "metric": "words", "floor": 40, "now": 41},
                          {"id": "b", "metric": "min_font", "floor": 20, "now": 18}])

    def test_adjacent_same_layout_warns(self):
        units = [unit("a", layout="x"), unit("b", layout="x"), unit("c", layout="y")]
        self.assertEqual(check.same_layout(units), [["a", "b"]])

    def test_flesch_orders_easy_above_hard(self):
        easy = check.flesch("The cat sat on the mat. It was warm.")
        hard = check.flesch("Institutional accountability necessitates comprehensive organisational documentation.")
        self.assertGreater(easy, hard)
        self.assertIsNone(check.flesch(""))


if __name__ == "__main__":
    unittest.main()
