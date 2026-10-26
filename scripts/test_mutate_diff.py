"""Tests for mutate-diff's two pure functions. Run: python3 scripts/test_mutate_diff.py"""
import importlib.machinery
import importlib.util
import os
import unittest

_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mutate-diff")
_loader = importlib.machinery.SourceFileLoader("mutate_diff", _path)
_spec = importlib.util.spec_from_loader("mutate_diff", _loader)
md = importlib.util.module_from_spec(_spec)
_loader.exec_module(md)

DIFF = """\
diff --git a/src/lib/budget.ts b/src/lib/budget.ts
--- a/src/lib/budget.ts
+++ b/src/lib/budget.ts
@@ -40,0 +41,3 @@ export function a() {
@@ -70 +73 @@ export function b() {
@@ -90,2 +93,0 @@ export function c() {
--- a/src/lib/budget.test.ts
+++ b/src/lib/budget.test.ts
@@ -1 +1,4 @@
+++ b/src/app/page.tsx
@@ -1 +1,2 @@
+++ b/src/app/x/layout.tsx
@@ -1 +1,2 @@
+++ b/src/app/x/notpage.tsx
@@ -5,2 +5,2 @@
+++ b/vitest.config.ts
@@ -1 +1 @@
+++ b/src/types.d.ts
@@ -1 +1 @@
+++ b/src/a.spec.tsx
@@ -1 +1 @@
+++ b/src/app/(member)/events/[id]/actions.ts
@@ -3 +3,2 @@
@@ -9 +10 @@
+++ b/README.md
@@ -1 +1 @@
+++ /dev/null
@@ -0,0 +0,0 @@
"""


class MutateRanges(unittest.TestCase):
    def test_keeps_source_ranges_and_skips_the_rest(self):
        self.assertEqual(md.mutate_ranges(DIFF),
                         ["src/lib/budget.ts:41-43", "src/lib/budget.ts:73-73",
                          "src/app/x/notpage.tsx:5-6",
                          "src/app/?member?/events/?id?/actions.ts"])

    def test_empty_diff(self):
        self.assertEqual(md.mutate_ranges(""), [])


class Summarise(unittest.TestCase):
    def test_counts_and_survivor_order(self):
        def m(status, line, name="ConditionalExpression"):
            return {"status": status, "mutatorName": name, "replacement": "true",
                    "location": {"start": {"line": line, "column": 1}}}
        report = {"files": {
            "b.ts": {"mutants": [m("Survived", 9), m("Killed", 1), m("Timeout", 2)]},
            "a.ts": {"mutants": [m("NoCoverage", 5), m("Ignored", 6), m("Survived", 3)]},
        }}
        counts, surv = md.summarise(report)
        self.assertEqual(counts, {"mutants": 5, "killed": 2, "survived": 2, "no_coverage": 1})
        self.assertEqual([(s[0], s[1], s[4]) for s in surv],
                         [("a.ts", 3, False), ("a.ts", 5, True), ("b.ts", 9, False)])


if __name__ == "__main__":
    unittest.main()
