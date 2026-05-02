"""Tests for _md_to_html() GFM table rendering.

Run from repo root:
  python3 -m pytest plugins/export-chat-logs/scripts/tests/test_md_to_html.py -v
  python3 -m unittest discover -s plugins/export-chat-logs/scripts/tests -p "test_*.py"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from convert_to_html import _md_to_html


class TestGFMTableRendering(unittest.TestCase):

    def test_f1_basic_table(self):
        """F1: Basic 3-column table with outer pipes."""
        md = "| Name | Age | City |\n|------|-----|------|\n| Alice | 30 | NYC |"
        result = _md_to_html(md)
        self.assertIn('<table>', result)
        self.assertIn('<th', result)
        self.assertIn('Name', result)
        self.assertIn('<td', result)
        self.assertIn('Alice', result)
        self.assertIn('30', result)

    def test_f2_alignment(self):
        """F2: Three alignment types (:---, :---:, ---:)."""
        md = "| Left | Center | Right |\n|:-----|:------:|------:|\n| a | b | c |"
        result = _md_to_html(md)
        self.assertIn('text-align:left', result)
        self.assertIn('text-align:center', result)
        self.assertIn('text-align:right', result)

    def test_f3_escaped_pipe(self):
        """F3: Escaped pipe in cell should render as &#124; and not split the cell."""
        md = "| Col |\n|-----|\n| a \\| b |"
        result = _md_to_html(md)
        self.assertIn('<table>', result)
        self.assertIn('&#124;', result)

    def test_f4_no_outer_pipes(self):
        """F4: Table without outer pipes still produces a table."""
        md = "Header1 | Header2\n--- | ---\nval1 | val2"
        result = _md_to_html(md)
        self.assertIn('<table>', result)
        self.assertIn('Header1', result)
        self.assertIn('val1', result)

    def test_f5_cell_inline_markdown(self):
        """F5: Cell content with bold and inline code renders correctly."""
        md = "| Name | Note |\n|------|------|\n| **Bob** | see `docs` |"
        result = _md_to_html(md)
        self.assertIn('<strong>Bob</strong>', result)
        self.assertIn('<code>docs</code>', result)

    def test_f6_single_line_no_separator_not_table(self):
        """F6: Single line with pipes but no separator should NOT be a table."""
        md = "| not | a | table |"
        result = _md_to_html(md)
        self.assertNotIn('<table>', result)

    def test_f7_table_inside_fenced_code_not_parsed(self):
        """F7: Table syntax inside a fenced code block should NOT be parsed as a table."""
        md = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```"
        result = _md_to_html(md)
        self.assertIn('<pre>', result)
        self.assertIn('<code>', result)
        self.assertNotIn('<table>', result)

    def test_f8_blockquote_then_table(self):
        """F8: Blockquote followed by a table — both should render correctly."""
        md = "> This is a quote\n\n| Col1 | Col2 |\n|------|------|\n| val1 | val2 |"
        result = _md_to_html(md)
        self.assertIn('<blockquote>', result)
        self.assertIn('<table>', result)

    def test_f9_ragged_rows(self):
        """F9: Ragged rows — missing cells padded, extra cells truncated."""
        md = "| A | B | C |\n|---|---|---|\n| x | y |\n| 1 | 2 | 3 | 4 |"
        result = _md_to_html(md)
        self.assertIn('<table>', result)
        # Missing cell row should have td elements (with or without style attribute)
        self.assertIn('</td>', result)

    def test_f10_zero_body_rows(self):
        """F10: Table with header and separator but no body rows is valid."""
        md = "| Header1 | Header2 |\n|---------|----------|\n"
        result = _md_to_html(md)
        self.assertIn('<table>', result)
        self.assertIn('<thead>', result)

    # Regression checks

    def test_r1_fenced_code_block(self):
        """R1: Fenced code block with language tag renders correctly."""
        md = "```python\nprint('hello')\n```"
        result = _md_to_html(md)
        self.assertIn('<pre>', result)
        self.assertIn('language-python', result)
        self.assertNotIn('```', result)

    def test_r2_blockquote(self):
        """R2: Blockquote renders as <blockquote><p>...</p></blockquote>."""
        md = "> blockquote text"
        result = _md_to_html(md)
        self.assertIn('<blockquote>', result)
        self.assertIn('blockquote text', result)

    def test_r3_unordered_list(self):
        """R3: Unordered list renders as <ul><li>...</li></ul>."""
        md = "- list item one\n- list item two"
        result = _md_to_html(md)
        self.assertIn('<ul>', result)
        self.assertIn('<li>', result)
        self.assertIn('list item one', result)

    def test_r4_paragraph_separation(self):
        """R4: Two paragraphs separated by blank line each render in their own <p>."""
        md = "First paragraph text.\n\nSecond paragraph text."
        result = _md_to_html(md)
        self.assertIn('<p>', result)
        self.assertIn('First paragraph text.', result)
        self.assertIn('Second paragraph text.', result)


if __name__ == '__main__':
    unittest.main()
