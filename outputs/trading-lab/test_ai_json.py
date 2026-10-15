"""Tests for tolerant JSON recovery from model output.

Weaker models add prose around JSON even when told not to. These cases must be
recovered rather than discarding usable analysis.
"""
import json
import unittest

import llm_research as lr


class ParseModelJsonTest(unittest.TestCase):
    def test_clean_object(self):
        self.assertEqual(lr._parse_model_json('{"a": 1}'), {"a": 1})

    def test_fenced_block(self):
        raw = '```json\n{"research": "ok", "concerns": []}\n```'
        self.assertEqual(lr._parse_model_json(raw)["research"], "ok")

    def test_fenced_without_language_tag(self):
        raw = '```\n{"research": "ok"}\n```'
        self.assertEqual(lr._parse_model_json(raw)["research"], "ok")

    def test_preamble_before_json(self):
        raw = ('Here is my analysis of the observed prices.\n\n'
               '{"research": "EUR/USD is flat", "concerns": []}\n\n'
               'Let me know if you need more detail.')
        out = lr._parse_model_json(raw)
        self.assertEqual(out["research"], "EUR/USD is flat")

    def test_trailing_prose_only(self):
        raw = '{"critique": "weak data"}\n\nHope this helps!'
        self.assertEqual(lr._parse_model_json(raw)["critique"], "weak data")

    def test_braces_inside_strings_do_not_break_scanning(self):
        raw = ('Sure thing: {"research": "the {brace} is literal", '
               '"concerns": []} done')
        out = lr._parse_model_json(raw)
        self.assertEqual(out["research"], "the {brace} is literal")

    def test_escaped_quote_inside_string(self):
        raw = r'{"research": "a \"quoted\" word", "concerns": ["a, b"]}'
        out = lr._parse_model_json(raw)
        self.assertEqual(out["concerns"], ["a, b"])

    def test_nested_object_kept_whole(self):
        raw = 'x {"research": "r", "meta": {"a": {"b": 1}}, "concerns": []} y'
        self.assertEqual(lr._parse_model_json(raw)["meta"], {"a": {"b": 1}})

    def test_multiple_objects_takes_the_first(self):
        raw = '{"research": "first", "concerns": []}\n{"research": "second"}'
        self.assertEqual(lr._parse_model_json(raw)["research"], "first")

    def test_prose_with_no_object_still_fails(self):
        with self.assertRaises(ValueError):
            lr._parse_model_json("I cannot produce JSON for this request.")

    def test_truncated_object_still_fails_cleanly(self):
        with self.assertRaises(ValueError):
            lr._parse_model_json('{"research": "unterminated')

    def test_array_wrapper_yields_the_inner_object(self):
        # Wrapping the object in a list is a recoverable formatting slip, and the
        # field check downstream still rejects a genuinely wrong shape.
        out = lr._parse_model_json('[{"research": "x"}]')
        self.assertEqual(out["research"], "x")

    def test_object_without_required_field_is_rejected_downstream(self):
        # Recovery must not smuggle a wrong shape past validation.
        payload = lr._parse_model_json('{"summary": "wrong shape"}')
        with self.assertRaises(lr.ModelError):
            lr._validate(payload, "research")


if __name__ == "__main__":
    unittest.main()