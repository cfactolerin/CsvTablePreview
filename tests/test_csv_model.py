import csv
import io
import unittest

import csv_model as model


class ParseTests(unittest.TestCase):
    def parse(self, text, filename="example.csv", **settings):
        return model.parse_csv(text, filename, settings)

    def test_quoted_delimiters_and_escaped_quotes(self):
        text = 'Name,Note\r\nAlice,"a,b"\r\nBob,"say ""hello"""\r\n'
        parsed = self.parse(text)
        self.assertEqual(parsed["rows"], [["Name", "Note"], ["Alice", "a,b"], ["Bob", 'say "hello"']])
        self.assertEqual([text[start:end] for start, end in parsed["spans"][2]],
                         ["Bob", '"say ""hello"""'])

    def test_multiline_regions(self):
        text = '\ufeffName,Note\nAlice,"one\r\ntwo\nthree"\nBob,end'
        parsed = self.parse(text)
        self.assertEqual(parsed["rows"][1][1], "one\r\ntwo\nthree")
        self.assertEqual([text[a:b] for a, b in parsed["spans"][1]],
                         ["Alice", '"one\r\ntwo\nthree"'])
        self.assertEqual(parsed["spans"][0][0][0], 1)
        self.assertEqual([text[a:b] for a, b in parsed["spans"][2]], ["Bob", "end"])

    def test_empty_fields_blank_records_and_ragged_rows(self):
        text = 'a,b,\n\nx\n,,\n'
        parsed = self.parse(text, delimiter=",")
        self.assertEqual(parsed["rows"], [["a", "b", ""], [], ["x"], ["", "", ""]])
        self.assertEqual(parsed["spans"][1], [])
        self.assertEqual(len(parsed["spans"][3]), 3)

    def test_empty(self):
        self.assertEqual(self.parse("")["rows"], [])
        self.assertEqual(self.parse("\ufeff")["columns"], 0)

    def test_line_endings(self):
        for ending in ("\n", "\r\n", "\r"):
            text = 'a,b' + ending + 'c,d'
            parsed = self.parse(text)
            self.assertEqual(parsed["rows"], [["a", "b"], ["c", "d"]])
            self.assertEqual([text[a:b] for a, b in parsed["spans"][1]], ["c", "d"])

    def test_unicode_line_separators_are_cell_content(self):
        text = "a,b\nx,one\u2028two\ny,z"
        parsed = self.parse(text)
        self.assertEqual(parsed["rows"][1][1], "one\u2028two")
        self.assertEqual([text[a:b] for a, b in parsed["spans"][2]], ["y", "z"])

    def test_delimiters(self):
        self.assertEqual(self.parse("a\tb\nc\td", "test.tsv")["delimiter"], "\t")
        self.assertEqual(self.parse("a\tb\nc\td", "test.tab")["delimiter"], "\t")
        self.assertEqual(self.parse("a;b\nc;d")["delimiter"], ";")
        self.assertEqual(self.parse("a|b\nc|d", delimiter="|")["rows"][1], ["c", "d"])

    def test_limits_are_explicit(self):
        parsed = self.parse("a,b,c\n1,2,3\n4,5,6", max_rows=2, max_columns=2)
        self.assertTrue(parsed["truncated_rows"])
        self.assertTrue(parsed["truncated_columns"])
        self.assertEqual(parsed["rows"], [["a", "b"], ["1", "2"]])

    def test_no_data_type_conversion(self):
        values = ["0001", "12345678901234567890", "2026-11-11", "=SUM(A1)"]
        self.assertEqual(self.parse(",".join(values))["rows"][0], values)

    def test_malformed_csv(self):
        for text in ('a,"open', 'a,"closed"garbage'):
            with self.assertRaises(csv.Error):
                self.parse(text)

    def test_invalid_delimiters(self):
        for delimiter in ("", "ab", "\n", "\r", '"', 2):
            with self.assertRaises(ValueError):
                self.parse("a,b", delimiter=delimiter)


class RenderTests(unittest.TestCase):
    def render(self, text, **kwargs):
        parsed = model.parse_csv(text, "example.csv", {})
        return model.render_preview(parsed, "example.csv", {}, model.DARK_PALETTE,
                                    "#002b36", "#839496", **kwargs)

    def test_uses_rendered_cells_not_ascii_borders(self):
        content, start, end = self.render("a,b\nx,y")
        self.assertIn('class="cell"', content)
        self.assertIn("background-color:", content)
        self.assertNotIn("┌", content)
        self.assertEqual((start, end), (0, 2))
        self.assertIn('href="select-copy"', content)

    def test_source_and_preview_palette_agree(self):
        content, _, _ = self.render("a,b\nx,y")
        for color in model.DARK_PALETTE[:2]:
            self.assertIn("color:{};".format(color), content)

    def test_html_is_escaped_and_no_external_resources(self):
        content, _, _ = self.render('<img src=x>,"<a href=""file:///secret"">"')
        self.assertNotIn("<img", content)
        self.assertNotIn('href="file:', content)
        self.assertIn("&lt;img", content)
        self.assertNotIn("<script", content)

    def test_paging_fits_small_panes(self):
        content, start, end = self.render("a,b,c,d,e\n1,2,3,4,5", available_chars=28)
        self.assertEqual(start, 0)
        self.assertLess(end, 5)
        self.assertIn('href="columns:{}"'.format(end), content)
        next_content, next_start, _ = self.render("a,b,c,d,e\n1,2,3,4,5", start=end, available_chars=28)
        self.assertEqual(next_start, end)
        self.assertIn("Previous", next_content)

    def test_empty_render(self):
        self.assertIn("No data", self.render("")[0])

    def test_clipping_and_multiline(self):
        self.assertEqual(model.clip_cell("1234567890", 8), "1234567…")
        self.assertEqual(model.clip_cell("a\nb", 8), "a ↵ b")
        self.assertEqual(model.display_width("日本"), 4)
        self.assertEqual(model.display_width("e\u0301"), 1)

    def test_palette_and_tints(self):
        self.assertEqual(model.palette_for("#002b36"), model.DARK_PALETTE)
        self.assertEqual(model.palette_for("#ffffff"), model.LIGHT_PALETTE)
        self.assertEqual(model.mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(model.mix("#000000", "#ffffff", 1), "#ffffff")

    def test_configuration_bounds(self):
        self.assertEqual(model.bounded_int({"value": "bad"}, "value", 10, 1, 20), 10)
        self.assertEqual(model.bounded_int({"value": 200}, "value", 10, 1, 20), 20)
        self.assertEqual(model.bounded_int({"value": True}, "value", 10, 1, 20), 10)

    def test_syntax_contains_all_column_states(self):
        syntax = model.make_syntax(",")
        for index in range(10):
            for context in ("field", "quoted", "unquoted", "after"):
                self.assertIn("  {}{}:".format(context, index), syntax)
            self.assertIn("meta_scope: csvpreview.column{}".format(index), syntax)
        self.assertIn('    - match: \'""\'', syntax)
        self.assertIn('      set: field0', syntax)

    def test_syntax_escapes_tabs_and_newlines(self):
        syntax = model.make_syntax("\t")
        self.assertIn('    - match: "\\\\t"', syntax)
        self.assertNotIn("\r", syntax)
        self.assertNotIn("\t", syntax)


class CopyTests(unittest.TestCase):
    def test_copy_contains_data_only(self):
        parsed = model.parse_csv("a,b\n1,2", "example.csv", {})
        self.assertEqual(model.copy_text(parsed), "a\tb\n1\t2\n")

    def test_copy_keeps_values_beyond_rendered_width(self):
        value = "0000" + "1234567890" * 100
        parsed = model.parse_csv("id,note\n" + value + ",hello", "example.csv", {})
        self.assertIn(value, model.copy_text(parsed))
        self.assertNotIn("…", model.copy_text(parsed))

    def test_copy_roundtrips_tabs_quotes_and_line_endings(self):
        rows = [["name", "note"], ["Alice", 'tab\there, "quoted"'],
                ["Bob", "first\r\nsecond\nthird\rfourth"]]
        text = model.copy_text({"rows": rows})
        actual = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))
        self.assertEqual(actual, rows)

    def test_copy_preserves_empty_and_ragged_rows(self):
        rows = [["", ""], [], ["a"], ["b", "c", ""]]
        text = model.copy_text({"rows": rows})
        actual = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))
        self.assertEqual(actual, rows)

    def test_empty_copy(self):
        self.assertEqual(model.copy_text({"rows": []}), "")


if __name__ == "__main__":
    unittest.main()
