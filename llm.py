"""LLM client interface, a deterministic MockLLM for tests, and thin adapters for real providers.
The adapters import their SDKs lazily; fill in API keys through environment variables."""
import json
import os
import random


class LLMClient:
    last_tokens = 0
    def generate(self, system, user, temperature=0.5):   # -> str
        raise NotImplementedError


class OpenAIClient(LLMClient):
    """Also serves every OpenAI-compatible endpoint (Groq, OpenRouter, Ollama, ...): pass base_url and api_key_env."""
    def __init__(self, model="gpt-4o-mini", base_url=None, api_key_env="OPENAI_API_KEY", extra=None):
        from openai import OpenAI
        key = os.environ.get(api_key_env, "ollama" if base_url and "localhost" in base_url else None)
        if key is None:
            raise KeyError(f"environment variable {api_key_env} is not set")
        self.c, self.model, self.extra = OpenAI(api_key=key, base_url=base_url), model, dict(extra or {})
    def generate(self, system, user, temperature=0.5):
        r = self.c.chat.completions.create(model=self.model, temperature=temperature, **self.extra,
                                           messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        self.last_tokens = r.usage.total_tokens
        self.last_reply = r.choices[0].message.content or ""
        return self.last_reply


class AnthropicClient(LLMClient):
    def __init__(self, model):
        import anthropic
        self.c, self.model = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]), model
    def generate(self, system, user, temperature=0.5):
        r = self.c.messages.create(model=self.model, max_tokens=4096, temperature=temperature, system=system,
                                   messages=[{"role": "user", "content": user}])
        self.last_tokens = r.usage.input_tokens + r.usage.output_tokens
        return r.content[0].text


class GeminiClient(LLMClient):
    def __init__(self, model="gemini-2.5-flash"):
        from google import genai
        self.c, self.model = genai.Client(api_key=os.environ["GEMINI_API_KEY"]), model
    def generate(self, system, user, temperature=0.5):
        from google.genai import types
        r = self.c.models.generate_content(model=self.model, contents=user,
                                           config=types.GenerateContentConfig(system_instruction=system, temperature=temperature))
        self.last_tokens = getattr(r.usage_metadata, "total_token_count", 0)
        return r.text


class RetryingLLM(LLMClient):
    """Wraps a client: waits `min_interval` seconds between calls (free-tier rate limits) and retries transient
    errors (429 / 5xx / timeouts) with exponential back-off. A daily quota error is raised after `retries` tries."""
    def __init__(self, inner, min_interval=0.0, retries=6):
        self.inner, self.min_interval, self.retries, self._t = inner, min_interval, retries, 0.0
        self.last_tokens = 0
    def generate(self, system, user, temperature=0.5):
        import time
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.time() - self._t)
            if wait > 0:
                time.sleep(wait)
            try:
                out = self.inner.generate(system, user, temperature)
                self._t = time.time()
                self.last_tokens = getattr(self.inner, "last_tokens", 0)
                self.last_reply = out
                return out
            except Exception as e:                                   # noqa: BLE001
                self._t = time.time()
                if attempt == self.retries:
                    raise
                time.sleep(min(60, 2 ** (attempt + 1)))


class MockLLM(LLMClient):
    """TEST DOUBLE ONLY. Never use its output as experimental data.
    Fixes a problem only if the checker's feedback mentions it, with probability `skill`."""
    def __init__(self, skill=1.0, seed=0):
        self.skill, self.rng = skill, random.Random(seed)
    def generate(self, system, user, temperature=0.5):
        start = user.index("Current model:\n") + 15
        end = user.index("\n\nProblems found") if "Problems found" in user else len(user)
        model = json.loads(user[start:end])
        text = user[user.index("Problems found:"):] if "Problems found" in user else ""   # self-refine: no feedback
        if "(G6_PUBLIC_ATTR)" in text and self.rng.random() < self.skill:
            for c in model["classes"]:
                for a in c.get("attributes", []):
                    a["visibility"] = "-"
        if "(G3_DUP_INHERIT)" in text and self.rng.random() < self.skill:
            seen, keep = set(), []
            for r in model["relationships"]:
                k = (r["type"], r["source"], r["target"])
                if r["type"] in ("inheritance", "realization") and k in seen:
                    continue
                seen.add(k); keep.append(r)
            model["relationships"] = keep
        if "(G10_UNUSED_POLYMORPHIC_TYPE)" in text and self.rng.random() < self.skill:
            import re
            for iface in re.findall(r"\(G10_UNUSED_POLYMORPHIC_TYPE\) (\w+):", text):
                ctx = iface + "Context"
                if ctx not in {c["name"] for c in model["classes"]}:
                    model["classes"].append({"name": ctx, "attributes": [], "operations": []})
                    model["relationships"].append({"type": "aggregation", "source": ctx, "target": iface,
                                                   "multiplicity_source": "1", "multiplicity_target": "1", "label": "uses"})
        self.last_tokens = 100
        return json.dumps(model)
