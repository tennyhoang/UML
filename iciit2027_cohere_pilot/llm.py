"""LLM client interface, a deterministic MockLLM for tests, and thin adapters for real providers.
The adapters import their SDKs lazily; fill in API keys through environment variables."""
import json
import os
import random


class LLMClient:
    last_tokens = 0
    last_model = None          # exact model id reported by the provider for the last call (log it!)
    def generate(self, system, user, temperature=0.5):   # -> str
        raise NotImplementedError


class RetryingLLM(LLMClient):
    """Wrap a real client: retry transient API errors (rate limits, timeouts) with exponential backoff, so that
    an API hiccup is not recorded as a failed run. After `tries` attempts the exception is raised."""
    def __init__(self, inner, tries=4, base_delay=2.0, sleep=None):
        import time
        self.inner, self.tries, self.base_delay = inner, tries, base_delay
        self.sleep = sleep or time.sleep
    def generate(self, system, user, temperature=0.5):
        for attempt in range(self.tries):
            try:
                out = self.inner.generate(system, user, temperature)
                self.last_tokens = getattr(self.inner, "last_tokens", 0)
                self.last_model = getattr(self.inner, "last_model", None)
                return out
            except Exception as e:
                # Check if it's a rate limit error that needs longer delay
                error_str = str(e)
                is_rate_limit = "rate_limit" in error_str.lower() or "429" in error_str
                
                if attempt == self.tries - 1:
                    raise
                
                # Use longer delay for rate limits
                delay = self.base_delay * 2 ** attempt
                if is_rate_limit:
                    delay = max(delay, 60.0)  # At least 60s for rate limits
                
                self.sleep(delay)


class OpenAIClient(LLMClient):
    def __init__(self, model="gpt-4o-mini"):
        from openai import OpenAI
        self.c, self.model = OpenAI(api_key=os.environ["OPENAI_API_KEY"]), model
    def generate(self, system, user, temperature=0.5):
        r = self.c.chat.completions.create(model=self.model, temperature=temperature,
                                           messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        self.last_tokens, self.last_model = r.usage.total_tokens, getattr(r, "model", None)
        return r.choices[0].message.content


class AnthropicClient(LLMClient):
    def __init__(self, model):
        import anthropic
        self.c, self.model = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]), model
    def generate(self, system, user, temperature=0.5):
        kwargs = {"model": self.model, "max_tokens": 4096, "temperature": temperature, "messages": [{"role": "user", "content": user}]}
        if system:  # Only include system if not empty
            kwargs["system"] = system
        r = self.c.messages.create(**kwargs)
        self.last_tokens, self.last_model = r.usage.input_tokens + r.usage.output_tokens, getattr(r, "model", None)
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
        self.last_model = getattr(r, "model_version", None)
        return r.text


class GroqClient(LLMClient):
    """Groq API client using OpenAI-compatible SDK with base_url override."""
    def __init__(self, model="llama-3.3-70b-versatile", max_tokens=1500):
        from openai import OpenAI
        self.c = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1"
        )
        self.model = model
        self.max_tokens = max_tokens
    def generate(self, system, user, temperature=0.5):
        r = self.c.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        self.last_tokens = r.usage.total_tokens if r.usage else 0
        self.last_model = getattr(r, "model", None)
        return r.choices[0].message.content


class CohereClient(LLMClient):
    """Cohere API client for command models."""
    def __init__(self, model="command-a-03-2025"):
        import cohere
        self.c = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
        self.model = model
    def generate(self, system, user, temperature=0.5):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        
        r = self.c.chat(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=4000
        )
        # Cohere V2 API has usage.tokens structure
        if r.usage and r.usage.tokens:
            self.last_tokens = (r.usage.tokens.input_tokens or 0) + (r.usage.tokens.output_tokens or 0)
        else:
            self.last_tokens = 0
        self.last_model = self.model
        return r.message.content[0].text


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
