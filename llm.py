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
    def __init__(self, model="gpt-4o-mini"):
        from openai import OpenAI
        self.c, self.model = OpenAI(api_key=os.environ["OPENAI_API_KEY"]), model
    def generate(self, system, user, temperature=0.5):
        r = self.c.chat.completions.create(model=self.model, temperature=temperature,
                                           messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        self.last_tokens = r.usage.total_tokens
        return r.choices[0].message.content


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
