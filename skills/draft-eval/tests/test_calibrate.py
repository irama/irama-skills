import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import calibrate  # noqa: E402
import packet  # noqa: E402


def deck(n, roles=None, states=()):
    units = []
    for i in range(n):
        role = (roles or {}).get(i + 1, "content")
        units.append({"id": f"u{i + 1}", "ordinal": i + 1, "role": role, "hidden": False,
                      "layout": "meta" if i % 2 else "paper",
                      "section_indices": [i, i + 1] if i + 1 in states else [i],
                      "text": f"Slide {i + 1} has 3 cats", "notes": ""})
    return {"kind": "deck", "units": units}


def article(n):
    return {"kind": "article", "references": "## References\n\nA source.",
            "units": [{"id": f"s{i}-p1", "text": f"Section {i} words", "notes": ""} for i in range(n)]}


def shots_for(doc, d):
    d = Path(d)
    d.mkdir(exist_ok=True)
    shots = []
    for u in doc["units"]:
        f = f"{u['id']}.png"
        (d / f).write_bytes(b"png " + u["id"].encode())
        shots.append({"id": u["id"], "file": f})
    (d / "shots.json").write_text(json.dumps({"shots": shots}))
    return d / "shots.json"


class PacketSelectTest(unittest.TestCase):
    def test_selected_units_keep_their_real_previous_unit(self):
        doc = deck(6)
        with tempfile.TemporaryDirectory() as d:
            batches = packet.build(doc, Path(d) / "out", shots_for(doc, Path(d) / "s"), select={"u1", "u4"})
            self.assertEqual(batches[0]["units"], ["u1", "u4"])
            folders = sorted(p.name for p in Path(batches[0]["dir"]).iterdir())
            self.assertEqual(folders, ["01-u1", "02-u4"])
            u4 = Path(batches[0]["dir"]) / "02-u4"
            self.assertEqual((u4 / "context" / "prev.txt").read_text(), doc["units"][2]["text"])
            self.assertEqual((u4 / "context" / "prev.png").read_bytes(), b"png u3")
            self.assertFalse((Path(batches[0]["dir"]) / "01-u1" / "context" / "prev.txt").exists())
            prompt = Path(batches[0]["prompt"]).read_text()
            self.assertIn('"first_unit_of_draft": true', prompt)
            self.assertEqual(prompt.count('"first_unit_of_draft": true'), 1)


class SelectTest(unittest.TestCase):
    def test_deck_pick_caps_non_content_and_skips_states(self):
        doc = deck(20, roles={1: "title", 5: "divider", 10: "divider", 15: "evidence", 20: "close"},
                   states={3, 7})
        ids = calibrate.pick_deck(doc["units"], 6)
        self.assertEqual(len(ids), 6)
        roles = [u["role"] for u in doc["units"] if u["id"] in ids]
        self.assertLessEqual(sum(r != "content" for r in roles), 2)
        self.assertNotIn("u3", ids)
        self.assertNotIn("u7", ids)
        self.assertEqual(ids, calibrate.pick_deck(doc["units"], 6))

    def test_a_later_set_avoids_roles_an_earlier_set_covers(self):
        doc = deck(9, roles={1: "title", 4: "exercise"})
        ids = calibrate.pick_deck(doc["units"], 3, avoid_roles={"title"})
        self.assertNotIn("u1", ids)
        self.assertIn("u1", calibrate.pick_deck(doc["units"], 3))

    def test_hidden_units_are_never_picked(self):
        doc = deck(5)
        for u in doc["units"][1:]:
            u["hidden"] = True
        self.assertEqual(calibrate.pick_deck(doc["units"], 3), ["u1"])

    def test_article_pick_is_evenly_spaced(self):
        self.assertEqual(calibrate.pick_article(article(9)["units"], 6),
                         ["s0-p1", "s2-p1", "s3-p1", "s5-p1", "s6-p1", "s8-p1"])
        self.assertEqual(len(calibrate.pick_article(article(4)["units"], 6)), 4)
        self.assertEqual(calibrate.pick_article(article(4)["units"], 1), [article(4)["units"][0]["id"]])


class BuildTest(unittest.TestCase):
    def test_build_writes_packets_hashes_units_and_page(self):
        doc, art = deck(10, roles={1: "title"}), article(8)
        doc["units"][4]["text"] = "No figures here at all"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "deck.json").write_text(json.dumps(doc))
            (d / "art.json").write_text(json.dumps(art))
            shots = shots_for(doc, d / "shots")
            out = d / "cal"
            calibrate.main(["-o", str(out), "--deck", "deck-x", str(d / "deck.json"), str(shots), "5",
                            "--article", "art-y", str(d / "art.json"), "3"])
            units = json.loads((out / "units.json").read_text())
            self.assertEqual([s["name"] for s in units["sets"]], ["deck-x", "art-y"])
            self.assertEqual(sum(len(s["selected"]) for s in units["sets"]), 8)
            self.assertTrue((out / "sources" / "deck-x.units.json").exists())
            lines = (out / "packets.sha256").read_text().splitlines()
            files = sorted(str(p.relative_to(out)) for p in (out / "packets").rglob("*") if p.is_file())
            self.assertEqual(sorted(line.split("  ", 1)[1] for line in lines), files)
            html = (out / "score.html").read_text()
            self.assertNotIn("\u2014", html)
            data = calibrate.page_data(out)
            self.assertEqual(len(data["units"]), 8)
            deck_crits = {c["id"] for c in data["units"][0]["criteria"]}
            self.assertEqual(len(deck_crits), 9)
            art_unit = [u for u in data["units"] if u["set"] == "art-y"][0]
            self.assertNotIn("visual", {c["id"] for c in art_unit["criteria"]})
            first = data["units"][0]
            na = {c["id"]: c["na"] for c in first["criteria"]}
            self.assertTrue(na["flow"])      # the draft's first unit
            self.assertTrue(na["delight"])   # title role
            self.assertFalse(na["clear"])
            self.assertTrue(na["honest_numbers"])  # a number may describe the session (rubric 0.2)

    def test_a_unit_with_no_number_is_forced_to_na_on_honest_numbers(self):
        rubric = json.loads((Path(calibrate.__file__).parent / "rubric.json").read_text())
        crits = calibrate.criteria_for({"role": "content", "text": "No figures here", "notes": ""},
                                       False, "deck", rubric)
        by = {c["id"]: c for c in crits}
        self.assertTrue(by["honest_numbers"]["forced"] and by["honest_numbers"]["na"])
        self.assertFalse(by["clear"]["na"])
        self.assertTrue(by["guess_reveal"]["na"])  # reveals_nothing is always allowed
