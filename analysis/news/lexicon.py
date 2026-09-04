"""
Offline financial lexicon.

A deterministic, dependency-free sentiment rater. It is the fallback whenever
no local model is reachable (and the default engine so the whole feature works
on a machine without Ollama). It is not magic — it is a weighted vocabulary
tuned for crypto headlines, with negation and intensifier handling.
"""

import math
import re
from typing import Dict, List, Tuple

# Crypto-specific vocabulary: (weight). Weight sign = direction.
BULLISH: Dict[str, float] = {
    "surge": 1.6, "surges": 1.6, "soar": 1.6, "soars": 1.6, "skyrocket": 1.9, "jump": 1.2,
    "jumps": 1.2, "rally": 1.5, "rallies": 1.5, "bull run": 2.0, "bullish": 1.4, "breakout": 1.4,
    "all-time high": 2.0, "ath": 1.6, "record high": 1.8, "inflow": 1.3, "inflows": 1.3,
    "approval": 1.5, "approved": 1.6, "etf": 0.5, "spot etf": 1.0, "adoption": 1.1,
    "partnership": 1.0, "integration": 0.7, "integrates": 0.8, "upgrade": 0.8, "halving": 0.7,
    "accumulate": 1.1, "accumulation": 1.1, "buy the dip": 1.0, "bought": 0.6, "buying": 0.8,
    "institutional": 0.7, "bank": 0.3, "reserve": 0.5, "treasury": 0.5, "strategic reserve": 1.7,
    "listing": 0.8, "listed": 0.7, "launch": 0.6, "launches": 0.7, "mainnet": 0.8,
    "burn": 0.5, "burning": 0.5, "deflationary": 0.8, "recovery": 1.0, "rebound": 1.1,
    "bounce": 0.9, "gain": 0.9, "gains": 1.1, "climb": 1.0, "raises": 0.6, "raise": 0.4,
    "growth": 0.9, "outperform": 1.1, "beat": 0.8, "record": 0.7, "milestone": 0.6,
    "green": 0.6, "upgrade activated": 1.0, "rate cut": 1.1, "dovish": 1.0, "stimulus": 1.0,
    "liquidity injection": 1.2, "short squeeze": 1.3, "buyback": 1.0, "settlement": 0.3,
    "clearance": 0.6, "legal clarity": 1.0, "regulatory win": 1.3, "otc": 0.4, "payments": 0.5,
    "stablecoin": 0.3, "tvl": 0.4, "volume spike": 0.9, "open interest rises": 0.7,
}

BEARISH: Dict[str, float] = {
    "crash": 2.0, "crashes": 2.0, "plunge": 1.8, "plunges": 1.8, "dump": 1.5, "dumps": 1.5,
    "sell-off": 1.5, "selloff": 1.5, "sell off": 1.4, "tumble": 1.4, "slides": 1.2, "slump": 1.4,
    "bearish": 1.4, "bear market": 1.7, "downtrend": 1.2, "correction": 0.9, "hack": 1.9,
    "hacked": 2.0, "exploit": 1.9, "exploited": 1.9, "breach": 1.5, "stolen": 1.7, "theft": 1.5,
    "rug pull": 2.0, "scam": 1.6, "fraud": 1.6, "ponzi": 1.8, "lawsuit": 1.3, "sues": 1.3,
    "sued": 1.4, "charge": 0.8, "charges": 1.2, "investigation": 0.9, "probe": 0.8,
    "sec": 0.4, "lawsuit filed": 1.5, "ban": 1.7, "banned": 1.8, "crackdown": 1.4,
    "restrict": 0.9, "restriction": 0.9, "delist": 1.6, "delisting": 1.7, "delisted": 1.6,
    "suspend": 1.3, "frozen": 1.1, "bankruptcy": 1.9, "insolvent": 1.8, "default": 1.2,
    "liquidation": 1.4, "liquidations": 1.5, "margin call": 1.3, "outflow": 1.4, "outflows": 1.4,
    "recession": 1.2, "inflation rises": 1.0, "rate hike": 1.2, "hawkish": 1.0, "tariff": 0.9,
    "fear": 0.8, "panic": 1.3, "capitulation": 1.2, "warning": 0.9, "risk": 0.4, "volatile": 0.4,
    "alert": 0.7, "downgrade": 1.3, "cut": 0.5, "layoffs": 1.0, "shutdown": 1.0, "exit": 0.6,
    "red": 0.5, "loss": 0.8, "losses": 1.0, "decline": 1.0, "drop": 1.1, "falls": 1.2,
    "sink": 1.2, "sinks": 1.2, "collapse": 1.9, "insolvency": 1.7, "manipulation": 1.2,
    "investor protection": 0.2, "halt": 1.0, "withdrawals paused": 1.8, "bank run": 1.7,
}

NEGATIONS = {"not", "no", "never", "without", "fails", "failed", "isn't", "aren't", "won't",
             "doesn't", "don't", "cannot", "hardly", "barely", "denies", "denied", "despite"}

INTENSIFIERS = {"massive": 1.5, "huge": 1.4, "major": 1.3, "sharp": 1.3, "surges": 1.0,
                "plunges": 1.0, "record": 1.3, "critical": 1.3, "brutal": 1.4, "slight": 0.6,
                "slightly": 0.6, "modest": 0.7, "mild": 0.7, "tiny": 0.5, "extreme": 1.5,
                "official": 1.2, "confirmed": 1.3, "breaking": 1.3, "urgent": 1.2}

# Phrases that flip a headline into "noise" for our purpose.
NEUTRAL_PATTERNS = (
    r"\bweekly (?:digest|roundup|recap)\b",
    r"\bhow to\b",
    r"\bbest wallet",
    r"\bpredictions? for 20\d\d\b",
    r"\bprice prediction\b",
    r"\bwhat is\b",
    r"\bgiveaway\b",
    r"\bsponsored\b",
)

_TOKEN = re.compile(r"[a-z0-9$%][a-z0-9'’\-\$%\.]*")
_NORM = re.compile(r"[^a-z0-9\s'\-$%\.]+")


def normalize(text: str) -> str:
    text = str(text or "").lower().replace("\u2019", "'")
    text = _NORM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_text(text: str) -> Tuple[float, List[str], str]:
    """Return (score in [-1, 1], matched terms, polarity label)."""
    raw = str(text or "")
    if not raw.strip():
        return 0.0, [], "NEUTRAL"

    lowered = normalize(raw)

    for pattern in NEUTRAL_PATTERNS:
        if re.search(pattern, lowered):
            return 0.0, [], "NOISE"

    words = lowered.split()
    total = 0.0
    hits: List[str] = []

    phrases = []
    for vocab, sign in ((BULLISH, 1.0), (BEARISH, -1.0)):
        for phrase in vocab:
            if " " in phrase and phrase in lowered:
                phrases.append((phrase, vocab[phrase] * sign))

    matched_phrases = {p for p, _ in phrases}
    for phrase, weight in phrases:
        total += weight
        hits.append(phrase)

    for idx, word in enumerate(words):
        for phrase in matched_phrases:
            if word in phrase.split():
                break
        else:
            weight = 0.0
            sign = 0
            if word in BULLISH:
                weight, sign = BULLISH[word], 1
            elif word in BEARISH:
                weight, sign = BEARISH[word], -1
            if sign == 0:
                continue

            window = words[max(0, idx - 3):idx]
            multiplier = 1.0
            negated = any(w in NEGATIONS for w in window)
            for prev in reversed(window):
                if prev in INTENSIFIERS:
                    multiplier = INTENSIFIERS[prev]
                    break
            contribution = weight * sign * multiplier
            if negated:
                contribution *= -0.6
            total += contribution
            hits.append(("~" if negated else "") + word)

    if abs(total) < 1e-9:
        return 0.0, hits, "NEUTRAL"

    # Squash into [-1, 1]; ~3.0 of raw weight lands near ±0.95.
    score = math.tanh(total / 2.2)
    label = "BULLISH" if score > 0.12 else "BEARISH" if score < -0.12 else "NEUTRAL"
    return round(score, 3), hits[:8], label


def lexicon_strength(score: float) -> str:
    magnitude = abs(score)
    if magnitude >= 0.6:
        return "STRONG"
    if magnitude >= 0.35:
        return "MODERATE"
    if magnitude >= 0.12:
        return "WEAK"
    return "NONE"


def explain(text: str) -> str:
    score, hits, label = score_text(text)
    if not hits:
        return f"{label}: no keyword match"
    return f"{label} ({score:+.2f}) via {', '.join(hits[:4])}"
