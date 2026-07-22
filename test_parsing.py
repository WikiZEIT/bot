#!/usr/bin/env python
# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# This file is part of WikiZEIT Bot.
#
# Licensed under the GNU AGPL v3 or later. See LICENSE.

"""Tests for `parsing.py` — verifies that `find_template_in_text` and
`parse_params` correctly handle nested `{{...}}` and `[[...]]` inside
parameter values (notably the `etykieta` param from the Fotografia template).

Run: `python -m unittest test_parsing.py`  (or `python test_parsing.py`).
"""

import unittest

from parsing import (
    build_template_start_regex,
    find_template_in_text,
    parse_params,
)


TEMPLATE_NAMES = ['Fotografia', 'Podopieczni', 'Wikipedysta:WikiZEITBot/szablon']
TEMPLATE_RE = build_template_start_regex(TEMPLATE_NAMES)


def find_template(text, start_pos=0):
    return find_template_in_text(TEMPLATE_RE, text, start_pos)


class FindTemplateTests(unittest.TestCase):
    def test_bare_template(self):
        name, params_text, start, end = find_template("{{Fotografia}}")
        self.assertEqual(name, "Fotografia")
        self.assertEqual(params_text, "")
        self.assertEqual(start, 0)
        self.assertEqual(end, len("{{Fotografia}}"))

    def test_template_with_params(self):
        result = find_template("{{Fotografia|limit=10}}")
        self.assertIsNotNone(result)
        name, params_text, _, _ = result
        self.assertEqual(name, "Fotografia")
        self.assertEqual(params_text, "limit=10")

    def test_template_with_spaces(self):
        result = find_template("{{Fotografia | limit = 10 }}")
        name, params_text, _, _ = result
        self.assertEqual(name, "Fotografia")
        # find_template returns raw params_text; parse_params trims keys/values.
        self.assertEqual(params_text, " limit = 10 ")

    def test_nested_single_template_in_param(self):
        text = "{{Fotografia|etykieta={{plik}}}}"
        result = find_template(text)
        self.assertIsNotNone(result, "should still find outer template despite nested {{plik}}")
        name, params_text, start, end = result
        self.assertEqual(name, "Fotografia")
        self.assertEqual(params_text, "etykieta={{plik}}")
        self.assertEqual(text[start:end], text)

    def test_multiple_nested_templates_in_param(self):
        etykieta = "<center>[[:commons:File:{{plik}}|{{data}}]]</center>"
        text = "{{Fotografia|etykieta=" + etykieta + "}}"
        result = find_template(text)
        self.assertIsNotNone(result)
        name, params_text, _, end = result
        self.assertEqual(name, "Fotografia")
        self.assertEqual(params_text, f"etykieta={etykieta}")
        self.assertEqual(end, len(text))

    def test_unterminated_template_returns_none(self):
        # Opens but never closes — should not raise, just return None.
        self.assertIsNone(find_template("{{Fotografia|x={{y"))

    def test_template_inside_prose(self):
        text = "before text\n\n{{Fotografia|limit=5}}\n\nafter text"
        name, params_text, start, end = find_template(text)
        self.assertEqual(name, "Fotografia")
        self.assertEqual(text[start:end], "{{Fotografia|limit=5}}")

    def test_no_known_template(self):
        # Random template name not in TEMPLATE_NAMES shouldn't match.
        self.assertIsNone(find_template("{{NieIstniejący|foo=bar}}"))

    def test_full_realistic_invocation(self):
        # The exact shape from the user's mime+etykieta example.
        etykieta = "<center>[[:commons:File:{{plik}}|{{data}}]]</center>"
        text = "{{Fotografia |mime = image/jpeg |limit = 20 |etykieta = " + etykieta + "}}"
        name, params_text, start, end = find_template(text)
        self.assertEqual(name, "Fotografia")
        # Make sure the closing }} is the outermost one — i.e. the entire
        # template invocation is consumed.
        self.assertEqual(text[start:end], text)


class ParseParamsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_params(""), {})

    def test_single_param(self):
        self.assertEqual(parse_params("limit=10"), {"limit": "10"})

    def test_multiple_params(self):
        self.assertEqual(
            parse_params("limit=10|fotograf=jcubic"),
            {"limit": "10", "fotograf": "jcubic"},
        )

    def test_whitespace_around_separators(self):
        self.assertEqual(
            parse_params(" limit = 10 | fotograf = jcubic "),
            {"limit": "10", "fotograf": "jcubic"},
        )

    def test_polish_param_name(self):
        self.assertEqual(parse_params("próg dni=180"), {"próg dni": "180"})

    def test_pipe_inside_link_is_not_separator(self):
        # The `|` between `Foo` and `Bar` is inside `[[ ]]`; should NOT split.
        text = "etykieta=[[Foo|Bar]]"
        self.assertEqual(parse_params(text), {"etykieta": "[[Foo|Bar]]"})

    def test_pipe_inside_nested_template_is_not_separator(self):
        text = "etykieta={{plik|coś}}"
        self.assertEqual(parse_params(text), {"etykieta": "{{plik|coś}}"})

    def test_etykieta_with_nested_templates_and_link_pipe(self):
        # The "real" user example — both nested templates and a pipe in [[...]].
        etykieta = "<center>[[:commons:File:{{plik}}|{{data}}]]</center>"
        text = f"mime=image/jpeg|limit=20|etykieta={etykieta}"
        result = parse_params(text)
        self.assertEqual(result, {
            "mime": "image/jpeg",
            "limit": "20",
            "etykieta": etykieta,
        })

    def test_equals_inside_value_kept(self):
        # Only the FIRST `=` separates key from value.
        self.assertEqual(parse_params("etykieta=k=v"), {"etykieta": "k=v"})

    def test_segment_without_equals_ignored(self):
        # A pipe-separated chunk with no `=` is silently dropped.
        self.assertEqual(parse_params("k=v|orphan|x=y"), {"k": "v", "x": "y"})

    def test_escape_equals(self):
        self.assertEqual(
            parse_params("attrybuty=mode{{=}}packed"),
            {"attrybuty": "mode=packed"},
        )

    def test_escape_pipe(self):
        self.assertEqual(
            parse_params("etykieta=before{{!}}after"),
            {"etykieta": "before|after"},
        )

    def test_escape_both_combined(self):
        self.assertEqual(
            parse_params("attrybuty=mode{{=}}packed{{!}}widths{{=}}200px"),
            {"attrybuty": "mode=packed|widths=200px"},
        )

    def test_escape_does_not_split_on_inner_equals(self):
        # The `=` inside `{{=}}` must NOT be treated as the key/value separator.
        # If it were, key would be "attrybuty=mode{{" and value "}}packed".
        result = parse_params("attrybuty=mode{{=}}packed")
        self.assertIn("attrybuty", result)
        self.assertNotIn("attrybuty=mode{{", result)

    def test_escape_alongside_other_params(self):
        text = "limit=10|attrybuty=mode{{=}}packed|fotograf=jcubic"
        self.assertEqual(parse_params(text), {
            "limit": "10",
            "attrybuty": "mode=packed",
            "fotograf": "jcubic",
        })

    def test_full_round_trip_with_find_template(self):
        # End-to-end: locate the template invocation, parse its params, and
        # confirm the etykieta value comes back intact.
        etykieta = "<center>[[:commons:File:{{plik}}|{{data}}]]</center>"
        text = "Before\n{{Fotografia|mime=image/jpeg|limit=20|etykieta=" + etykieta + "}}\nAfter"
        _, params_text, _, _ = find_template(text)
        params = parse_params(params_text)
        self.assertEqual(params["mime"], "image/jpeg")
        self.assertEqual(params["limit"], "20")
        self.assertEqual(params["etykieta"], etykieta)


if __name__ == "__main__":
    unittest.main()
