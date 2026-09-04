"""
Local / self-hosted AI sentiment.

Two providers are supported and neither needs a cloud account:

* **ollama** — POST {base}/api/chat with `format: json` (default model
  `llama3.1`; any pulled model works).
* **openai** — any OpenAI-compatible /v1/chat/completions endpoint: OpenAI,
  LM Studio (http://127.0.0.1:1234/v1), vLLM, llama.cpp server, OpenRouter ...

Every headline is scored once and cached on disk (sha1 of text + model), so a
restart or a second dashboard refresh costs nothing. If the model is not
reachable the engine falls back to the offline lexicon and reports why.
"""

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.news.lexicon import score_text
from utils.cache import cache_for
from utils.http import HttpError, request_json

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "llm_sentiment"
CACHE_TTL = 30 * 24 * 3600  # a headline never changes wording; keep it a month

SYSTEM_PROMPT = (
    "You are a quantitative crypto news desk. You rate the market impact of a "
    "headline for one asset (or for the whole crypto market when the asset is not "
    "named). Output strict JSON only, no prose, no markdown."
)


class LlmError(RuntimeError):
    """Raised when the configured model could not produce usable scores."""


@dataclass
class LlmConfig:
    provider: str = "ollama"          # ollama | openai
    model: str = "llama3.1"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str = ""
    timeout: float = 45.0
    temperature: float = 0.0
    max_tokens: int = 700
    batch_size: int = 12
    proxy: Optional[str] = None
    symbol: str = ""

    @property
    def tag(self) -> str:
        return f"{self.provider}:{self.model}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("api_key", None)
        return data


# =====================================================================
# prompts + parsing
# =====================================================================

def build_prompt(items: Sequence[str], symbol: str) -> str:
    asset = symbol or "the overall crypto market"
    lines = "\n".join(f"{i + 1}. {text[:240]}" for i, text in enumerate(items))
    return (
        f"Asset context: {asset}.\n"
        "Rate the sentiment / expected market impact of each headline.\n"
        "s = -1.0 (very bearish) ... 0.0 (neutral, no impact, or irrelevant) ... "
        "+1.0 (very bullish).\n"
        "Purely informational, how-to, opinion or promotional headlines are 0.0.\n"
        "t = at most 4 words of reason.\n\n"
        "Headlines:\n"
        f"{lines}\n\n"
        'Reply exactly: {"scores":[{"i":1,"s":0.0,"t":"reason"}, ...]}'
    )


_JSON_BLOCK = re.compile(r"(\{.*\}|\[.*\])", re.S)
_LINE = re.compile(r"^\s*[\[{\"']*(?:i|idx|id|index)[\"']*\s*[:=]\s*(\d+)\s*,\s*"
                   r"[\"']*(?:s|score|sentiment)[\"']*\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.M | re.I)
_PAIR = re.compile(r"^\s*(\d+)\s*[:=)\]]\s*(-?\d*\.\d+|-?\d)\b", re.M)


def _clamp(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 < abs(number) <= 100.0:               # models often answer -100..100
        number = number / 100.0
    return max(-1.0, min(1.0, number))


def parse_scores(text: str, count: int) -> Dict[int, Tuple[float, str]]:
    """Extract {index: (score, reason)} from a model reply. Tolerant on purpose."""
    out: Dict[int, Tuple[float, str]] = {}
    if not text:
        return out

    raw = text.strip()
    candidates: List[Any] = []

    for fence in re.findall(r"```(?:json)?\s*(.*?)```", raw, re.S):
        candidates.append(fence)
    block = _JSON_BLOCK.search(raw)
    if block:
        candidates.append(block.group(1))
    candidates.append(raw)

    for chunk in candidates:
        try:
            data = json.loads(chunk.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            for key in ("scores", "results", "items", "sentiment", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                # {"1": -0.4, "2": 0.1}
                pairs = {}
                for key, value in data.items():
                    try:
                        idx = int(re.sub(r"\D", "", str(key)))
                    except ValueError:
                        continue
                    score = _clamp(value if not isinstance(value, dict) else value.get("s"))
                    if idx and score is not None:
                        pairs[idx] = (score, str(value.get("t", "")) if isinstance(value, dict) else "")
                if pairs:
                    return pairs
        if isinstance(data, list):
            for position, entry in enumerate(data[:count], start=1):
                score = None
                reason = ""
                if isinstance(entry, dict):
                    idx = entry.get("i", entry.get("idx", entry.get("id", entry.get("index", position))))
                    try:
                        position = int(idx)
                    except (TypeError, ValueError):
                        position = idx if isinstance(idx, int) else position
                    raw_score = entry.get("s", entry.get("score", entry.get("sentiment")))
                    if raw_score is None and isinstance(entry.get("label"), str):
                        label = entry["label"].lower()
                        raw_score = {"bullish": 0.5, "bearish": -0.5, "neutral": 0.0}.get(label)
                    score = _clamp(raw_score)
                    reason = str(entry.get("t") or entry.get("reason") or "")[:60]
                elif isinstance(entry, (int, float)):
                    score = _clamp(entry)
                if score is not None and isinstance(position, int) and 1 <= position <= count:
                    out[position] = (score, reason)
            if out:
                return out

    if out:
        return out

    # Last resort: "1: -0.4" style lines.
    for pattern in (_LINE, _PAIR):
        for match in pattern.finditer(text):
            idx = int(match.group(1))
            score = _clamp(match.group(2))
            if score is not None and 1 <= idx <= count:
                out.setdefault(idx, (score, ""))
        if out:
            break
    return out


# =====================================================================
# transports
# =====================================================================

def _chat_ollama(cfg: LlmConfig, prompt: str) -> str:
    payload = {
        "model": cfg.model,
        "stream": False,
        "format": "json",
        "options": {"temperature": cfg.temperature, "num_predict": cfg.max_tokens},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    data = request_json(f"{cfg.base_url.rstrip('/')}/api/chat", method="POST", payload=payload,
                        timeout=cfg.timeout, proxy=cfg.proxy)
    if isinstance(data, dict):
        return str(data.get("response") or (data.get("message") or {}).get("content") or "")
    return ""


def _chat_openai(cfg: LlmConfig, prompt: str) -> str:
    url = cfg.base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"

    payload = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    try:
        data = request_json(url, method="POST", payload={**payload, "response_format": {"type": "json_object"}},
                            headers=headers, timeout=cfg.timeout, proxy=cfg.proxy)
    except HttpError as exc:
        # Some local servers reject response_format; retry once without it.
        logger.debug("openai-compatible retry without response_format: %s", exc)
        data = request_json(url, method="POST", payload=payload, headers=headers,
                            timeout=cfg.timeout, proxy=cfg.proxy)

    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"unexpected response shape from {cfg.base_url}") from exc


def _chat(cfg: LlmConfig, prompt: str) -> str:
    if cfg.provider == "ollama":
        return _chat_ollama(cfg, prompt)
    if cfg.provider == "openai":
        return _chat_openai(cfg, prompt)
    raise LlmError(f"unsupported provider '{cfg.provider}'")


def ping(cfg: LlmConfig) -> Dict[str, Any]:
    """Cheap availability probe used by the settings page."""
    started = time.time()
    try:
        if cfg.provider == "ollama":
            data = request_json(f"{cfg.base_url.rstrip('/')}/api/tags", timeout=min(8.0, cfg.timeout),
                                proxy=cfg.proxy)
            models = [m.get("name", "") for m in (data or {}).get("models", [])]
            found = any(m == cfg.model or m.split(":")[0] == cfg.model for m in models)
            return {
                "ok": True,
                "reachable": True,
                "model_found": found,
                "models": models[:20],
                "latency_ms": int((time.time() - started) * 1000),
                "detail": ("model available" if found
                           else f"ollama is up but '{cfg.model}' is not pulled "
                                f"(try: ollama pull {cfg.model})"),
            }

        probe = LlmConfig(**{**cfg.__dict__, "batch_size": 1, "max_tokens": 32, "timeout": min(20.0, cfg.timeout)})
        reply = _chat(probe, 'Reply exactly {"ok":1}')
        return {
            "ok": True,
            "reachable": True,
            "model_found": True,
            "latency_ms": int((time.time() - started) * 1000),
            "detail": f"echo: {reply[:60]!r}",
        }
    except (HttpError, LlmError, OSError) as exc:
        return {
            "ok": False,
            "reachable": False,
            "model_found": False,
            "latency_ms": int((time.time() - started) * 1000),
            "detail": str(exc)[:220],
        }


# =====================================================================
# public API
# =====================================================================

def score_headlines(texts: Sequence[str], cfg: LlmConfig) -> Tuple[List[Tuple[float, str, str]], Dict[str, Any]]:
    """Score headlines with the configured model.

    Returns one (score, reason, method) per input headline plus a stats dict.
    Cache hits skip the model entirely; anything the model fails to answer is
    filled in by the offline lexicon and flagged in `stats["fallbacks"]`.
    """
    cache = cache_for(CACHE_NAMESPACE)
    results: List[Optional[Tuple[float, str, str]]] = [None] * len(texts)
    stats = {"cached": 0, "requested": 0, "batches": 0, "fallbacks": 0, "llm_ms": 0,
             "provider": cfg.provider, "model": cfg.model}

    pending: List[int] = []
    for index, text in enumerate(texts):
        key = f"{cfg.tag}:{text.strip().lower()[:300]}"
        hit = cache.read_fresh(key, CACHE_TTL)
        if isinstance(hit, dict) and "s" in hit:
            results[index] = (float(hit["s"]), str(hit.get("t", "")), "llm")
            stats["cached"] += 1
        else:
            pending.append(index)

    if pending:
        batch_size = max(1, int(cfg.batch_size))
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            stats["batches"] += 1
            stats["requested"] += len(batch)
            prompt = build_prompt([texts[i] for i in batch], cfg.symbol)

            started = time.time()
            try:
                reply = _chat(cfg, prompt)
            except (HttpError, LlmError, OSError) as exc:
                if start == 0:
                    raise LlmError(str(exc)) from exc
                stats["error"] = str(exc)[:200]
                break
            stats["llm_ms"] += int((time.time() - started) * 1000)

            parsed = parse_scores(reply, len(batch))
            if not parsed:
                logger.info("llm returned no parsable scores; using lexicon for this batch")
                stats["unparsed"] = stats.get("unparsed", 0) + 1
                if start == 0 and not any(done is not None for done in results):
                    # nothing at all came back — tell the caller, so the UI can
                    # show "model answered nothing" instead of a silent fallback
                    raise LlmError(f"{cfg.tag} returned no usable scores "
                                   f"({reply[:80].strip()!r})")
                continue

            for position, (score, reason) in parsed.items():
                if 1 <= position <= len(batch):
                    index = batch[position - 1]
                    results[index] = (round(score, 3), reason, "llm")
                    cache.write(f"{cfg.tag}:{texts[index].strip().lower()[:300]}",
                                {"s": round(score, 3), "t": reason, "at": int(time.time())})

    for index, text in enumerate(texts):
        if results[index] is None:
            score, hits, _ = score_text(text)
            results[index] = (score, ", ".join(hits[:2]), "lexicon")
            stats["fallbacks"] += 1

    stats["llm_only"] = stats["fallbacks"] == 0 and stats["requested"] > 0
    llm_hits = stats["cached"] + sum(1 for r in results if r and r[2] == "llm")
    if llm_hits == 0:
        stats["scoring"] = "lexicon"          # the model answered nothing
    elif stats["fallbacks"] == 0:
        stats["scoring"] = "llm"
    else:
        stats["scoring"] = "mixed"
    stats.setdefault("engine", cfg.provider)
    return [r for r in results if r is not None], stats
