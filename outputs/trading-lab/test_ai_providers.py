"""Provider-specific tests for the advisory AI research layer.

Each provider has a different request shape and a different response shape, so
both the outbound call and the text extraction are checked per style.
"""
import json
import unittest
import urllib.error

import key_store as ks
import llm_research as lr


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self, *_a):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def payload_for(style, text):
    """A realistic success body for each provider style."""
    if style == "responses":
        return {"output_text": text}
    if style == "chat":
        return {"choices": [{"message": {"role": "assistant", "content": text}}]}
    if style == "anthropic":
        return {"content": [{"type": "text", "text": text}]}
    if style == "gemini":
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if style == "ollama":
        return {"message": {"role": "assistant", "content": text}}
    raise AssertionError(style)


def good_answer(field):
    return json.dumps({field: "analysis text", "concerns": ["thin sample"]})


def base_for(provider):
    """The generic gateway provider ships with no default endpoint by design,
    so tests must supply one."""
    spec = ks.PROVIDER_SPECS[provider]
    return spec["base_url"] or "https://gateway.example.invalid/v1"


def make_store(provider, base_url="", model="test-model", key="sk-test"):
    store = ks.KeyStore(max_calls=50, max_spend=1, cost_per_call=0.001)
    store.store(key, provider=provider, base_url=base_url, model=model)
    return store


class ProviderRoutingTest(unittest.TestCase):
    def test_every_provider_has_a_distinct_endpoint(self):
        seen = {}
        for name, spec in ks.PROVIDER_SPECS.items():
            url, _ = lr._endpoint_and_headers(
                make_store(name, base_for(name)), spec)
            self.assertTrue(url.startswith("http"), name)
            self.assertNotIn(url, seen, "duplicate endpoint for " + name)
            seen[url] = name
        self.assertEqual(len(seen), len(ks.PROVIDER_SPECS))

    def test_custom_requires_base_url(self):
        spec = ks.PROVIDER_SPECS["custom"]
        store = make_store("custom", "")
        with self.assertRaises(lr.ModelError) as ctx:
            lr._endpoint_and_headers(store, spec)
        self.assertIn("base URL", str(ctx.exception))

    def test_ollama_needs_no_key(self):
        store = ks.KeyStore()
        store.store("", provider="ollama", model="llama3.1")
        self.assertFalse(store.requires_key())
        self.assertTrue(store.has_key())

    def test_gemini_without_key_is_refused(self):
        store = ks.KeyStore()
        store.store("", provider="google", model="gemini-2.0-flash")
        spec = ks.PROVIDER_SPECS["google"]
        with self.assertRaises(lr.ModelError):
            lr._endpoint_and_headers(store, spec)

    def test_unknown_provider_is_rejected(self):
        store = ks.KeyStore()
        store.store("k", provider="not-a-provider", model="m")
        with self.assertRaises(lr.ModelError):
            lr._spec(store)


class TextExtractionTest(unittest.TestCase):
    def test_each_style_extracts_text(self):
        for name, spec in ks.PROVIDER_SPECS.items():
            raw = payload_for(spec["style"], "hello from " + name)
            self.assertEqual(lr._extract_text(spec["style"], raw),
                             "hello from " + name, name)

    def test_responses_falls_back_to_output_blocks(self):
        raw = {"output": [{"content": [{"type": "output_text", "text": "a"},
                                       {"type": "output_text", "text": "b"}]}]}
        self.assertEqual(lr._extract_text("responses", raw), "ab")

    def test_unknown_shape_returns_empty_not_a_crash(self):
        for style in ("responses", "chat", "anthropic", "gemini", "ollama"):
            self.assertEqual(lr._extract_text(style, {"unexpected": 1}), "")


class ProviderRoundTripTest(unittest.TestCase):
    def _run_all_stages(self, provider, base_url=""):
        spec = ks.PROVIDER_SPECS[provider]
        fields = ["research", "macro_view", "strategy", "critique"]
        sent = []

        def opener(req, timeout=None):
            field = fields[len(sent)]
            sent.append(req)
            return FakeResponse(
                payload_for(spec["style"], good_answer(field)))

        store = make_store(provider, base_url, "test-model")
        layer = lr.ResearchLayer(store, opener=opener)
        result = layer.run(
            {"pairs": {"EUR/USD": {"price": 1.12, "bid": 1.1199,
                                   "ask": 1.1201, "observed": 1.0}}},
            {"equity": 10000.0, "positions": []},
            {"max_positions": 3}, {"EUR/USD": [(1.0, 1.11)]}, [])
        return result, sent, spec

    def test_all_providers_complete_all_four_stages(self):
        for name in ks.PROVIDER_SPECS:
            result, sent, _ = self._run_all_stages(name, base_for(name))
            self.assertTrue(result["ok"], name)
            self.assertEqual(len(result["stages"]), 4, name)
            for stage in result["stages"]:
                self.assertTrue(stage["ok"], name)
                self.assertFalse(stage["affects_execution"], name)
                self.assertEqual(stage["concerns"], ["thin sample"], name)
            self.assertEqual(len(sent), 4, name)

    def test_auth_header_matches_provider(self):
        checks = {
            "openai": ("Authorization", "Bearer sk-test"),
            "custom": ("Authorization", "Bearer sk-test"),
            "anthropic": ("x-api-key", "sk-test"),
            "ollama": ("Authorization", "Bearer sk-test"),
        }
        for name, (header, expected) in checks.items():
            _, sent, _ = self._run_all_stages(name, base_for(name))
            # urllib normalises header casing on store, so compare insensitively.
            stored = {k.lower(): v for k, v in sent[0].headers.items()}
            self.assertEqual(stored.get(header.lower()), expected, name)

    def test_gemini_key_travels_in_url(self):
        _, sent, _ = self._run_all_stages("google", base_for("google"))
        self.assertIn("key=sk-test", sent[0].full_url)

    def test_custom_base_url_is_used_verbatim(self):
        store = make_store("custom", "https://openrouter.ai/api/v1", "x/y")
        spec = ks.PROVIDER_SPECS["custom"]
        url, _ = lr._endpoint_and_headers(store, spec)
        self.assertEqual(url,
                         "https://openrouter.ai/api/v1/chat/completions")

    def test_json_mode_toggles_structured_output(self):
        store = make_store("custom", "https://openrouter.ai/api/v1", "x/y")
        on = lr._build_body("chat", "x/y", "p", json_mode=True)
        off = lr._build_body("chat", "x/y", "p", json_mode=False)
        self.assertEqual(on.get("response_format"), {"type": "json_object"})
        self.assertNotIn("response_format", off)
        # Structured mode must not leak into other wire formats.
        for style in ("responses", "anthropic", "gemini", "ollama"):
            self.assertNotIn(
                "response_format",
                lr._build_body(style, "m", "p", json_mode=True), style)

    def test_json_mode_round_trips_through_the_store(self):
        store = make_store("custom", "https://openrouter.ai/api/v1", "x/y")
        self.assertTrue(store.json_mode)
        store.set_json_mode(False)
        self.assertFalse(store.json_mode)
        self.assertFalse(store.status()["json_mode"])

    def test_provider_http_error_reaches_the_user(self):
        def opener(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {}, None)

        store = make_store("openai")
        layer = lr.ResearchLayer(store, opener=opener)
        result = layer.run({"pairs": {}}, {}, {}, {}, [])
        self.assertFalse(result["ok"])
        self.assertTrue(any("HTTP 429" in c
                            for s in result["stages"] for c in s["concerns"]))


if __name__ == "__main__":
    unittest.main()