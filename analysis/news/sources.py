"""
News sources.

Only public, key-free endpoints by default (RSS feeds + Fear & Greed), with
CryptoPanic as an optional extra. Every fetcher is defensive: one dead feed
must never break the analysis, so failures are swallowed into a `notes` list
that the UI shows instead of an exception.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from utils.http import HttpError, request_json, request_text

logger = logging.getLogger(__name__)

_TAG_STRIP = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

#: how many bytes of each feed we bother to parse
MAX_ITEMS_PER_FEED = 25


@dataclass
class NewsItem:
    headline: str
    source: str
    url: str = ""
    published_at: Optional[datetime] = None
    summary: str = ""
    relevance: str = "MARKET"          # SYMBOL | MARKET
    matched: Tuple[str, ...] = ()
    score: float = 0.0
    method: str = "none"               # lexicon | llm | none
    detail: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        return f"{self.headline}. {self.summary}" if self.summary else self.headline

    def age_hours(self, now: Optional[datetime] = None) -> Optional[float]:
        if not self.published_at:
            return None
        now = now or datetime.now(timezone.utc)
        ref = self.published_at
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return max(0.0, (now - ref).total_seconds() / 3600.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "source": self.source,
            "url": self.url,
            "published": self.published_at.isoformat() if self.published_at else None,
            "age_hours": None if self.age_hours() is None else round(self.age_hours(), 1),
            "relevance": self.relevance,
            "matched": list(self.matched),
            "score": round(float(self.score), 3),
            "polarity": _polarity(self.score),
            "method": self.method,
            "detail": list(self.detail),
        }


def _polarity(score: float) -> str:
    if score >= 0.15:
        return "BULLISH"
    if score <= -0.15:
        return "BEARISH"
    return "NEUTRAL"


# =====================================================================
# symbol → keywords
# =====================================================================

ALIASES: Dict[str, Sequence[str]] = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "ether", "eth"),
    "BNB": ("bnb", "binance coin"),
    "SOL": ("solana", "sol"),
    "XRP": ("ripple", "xrp"),
    "ADA": ("cardano", "ada"),
    "DOGE": ("dogecoin", "doge"),
    "DOT": ("polkadot", "dot"),
    "LTC": ("litecoin", "ltc"),
    "LINK": ("chainlink", "link oracle"),
    "AVAX": ("avalanche", "avax"),
    "TRX": ("tron", "trx"),
    "UNI": ("uniswap", "uni"),
    "ATOM": ("cosmos", "atom"),
    "XLM": ("stellar", "xlm"),
    "ETC": ("ethereum classic", "etc"),
    "FIL": ("filecoin", "fil"),
    "NEAR": ("near protocol", "near"),
    "APT": ("aptos", "apt"),
    "SUI": ("sui network", "sui"),
    "ARB": ("arbitrum", "arb"),
    "OP": ("optimism", "op mainnet"),
    "TON": ("toncoin", "the open network", "ton"),
    "AAVE": ("aave",),
    "INJ": ("injective", "inj"),
    "SEI": ("sei network", "sei"),
    "MATIC": ("polygon", "matic"),
    "POL": ("polygon", "pol"),
    "SHIB": ("shiba inu", "shib"),
    "PEPE": ("pepe",),
    "CRV": ("curve finance", "crv"),
    "BONK": ("bonk",),
    "TIA": ("celestia", "tia"),
    "KAS": ("kaspa", "kas"),
    "WLD": ("worldcoin", "wld"),
    "LUNA": ("terra", "luna"),
    "FTM": ("fantom", "opera", "ftm"),
    "NEO": ("neo",),
    "ICP": ("internet computer", "icp"),
    "IMX": ("immutable", "imx"),
    "RNDR": ("render", "rndr"),
    "FET": ("fetch.ai", "fet"),
    "TAO": ("bittensor", "tao"),
}

#: macro terms that always matter for crypto, used when relevance-only is off
MACRO_TERMS = (
    "fed", "federal reserve", "fomc", "rate cut", "rate hike", "cpi", "inflation", "sec",
    "stablecoin", "regulation", "regulatory", "etf", "nasdaq", "s&p", "stock market",
    "treasury yield", "bankruptcy", "liquidation", "hack", "exploit", "exchange",
    "binance", "coinbase", "microstrategy", "blackrock", "tether", "gold", "dollar index",
)


def base_asset(symbol: str) -> str:
    return str(symbol or "").split("/")[0].strip().upper()


def symbol_keywords(symbol: str, extra: Optional[Any] = None) -> Set[str]:
    """Terms that mark a headline as being about *this* asset.

    ``extra`` accepts either a flat list of keywords (applies to every symbol,
    which is how the settings field is stored) or a ``{SYMBOL: [...]}`` map for
    per-coin terms.
    """
    base = base_asset(symbol)
    terms: Set[str] = {base.lower()} if base else set()
    terms.update(ALIASES.get(base, ()))

    if extra is None:
        extra = []
    if isinstance(extra, dict):
        entries = []
        for key, values in extra.items():
            if str(key).upper() not in (base, "*", "ALL"):
                continue
            entries.extend([values] if isinstance(values, str) else list(values or []))
    elif isinstance(extra, str):
        entries = [extra]
    else:
        entries = list(extra or [])

    for value in entries:
        text = str(value).strip().lower()
        if text:
            terms.add(text)
    return {t for t in terms if t}


def match_keywords(text: str, keywords: Iterable[str]) -> Tuple[str, ...]:
    # keywords are stored lower-cased, real headlines are not — "Bitcoin ETF
    # inflows" must still match "bitcoin"
    lowered = _plain(text).lower()
    return tuple(sorted({k for k in keywords if k and k in lowered}))


# =====================================================================
# parsing helpers
# =====================================================================

def _plain(text: Any, limit: int = 400) -> str:
    if text is None:
        return ""
    cleaned = html.unescape(str(text))
    cleaned = _TAG_STRIP.sub(" ", cleaned)
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned[:limit]


def _parse_date(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def parse_feed(xml_text: str, source: str, limit: int = MAX_ITEMS_PER_FEED) -> List[NewsItem]:
    """Parse RSS 2.0 / Atom into NewsItems (tolerant of odd namespaces)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Some feeds ship a stray BOM / leading junk; retry after the <?xml tag.
        start = xml_text.find("<")
        if start <= 0:
            raise
        root = ET.fromstring(xml_text[start:])

    items: List[NewsItem] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue

        fields: Dict[str, str] = {}
        link = ""
        for child in node:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "link":
                href = (child.attrib.get("href") or "").strip()
                link = link or href or text
            if text and name not in fields:
                fields[name] = text

        title = _plain(fields.get("title") or fields.get("title#text") or "", 300)
        if not title:
            continue

        published = _parse_date(
            fields.get("pubdate") or fields.get("published") or fields.get("updated")
            or fields.get("date") or fields.get("dc:date")
        )
        summary = _plain(fields.get("description") or fields.get("summary")
                         or fields.get("content#encoded") or fields.get("content") or "", 400)

        items.append(NewsItem(
            headline=title,
            source=source,
            url=link or fields.get("guid") or "",
            published_at=published,
            summary=summary if summary.lower() != title.lower() else "",
        ))
        if len(items) >= limit:
            break
    return items


def dedupe(items: Sequence[NewsItem]) -> List[NewsItem]:
    seen: Set[str] = set()
    out: List[NewsItem] = []
    for item in items:
        key = re.sub(r"[^a-z0-9]", "", item.headline.lower())[:70]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# =====================================================================
# fetchers
# =====================================================================

def fetch_rss(feeds: Sequence[str], timeout: float = 8.0, proxy: Optional[str] = None
              ) -> Tuple[List[NewsItem], List[str]]:
    items: List[NewsItem] = []
    notes: List[str] = []

    for url in feeds:
        url = str(url).strip()
        if not url:
            continue
        label = re.sub(r"^https?://", "", url).split("/")[0]
        try:
            text = request_text(url, timeout=timeout, proxy=proxy,
                                headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
            parsed = parse_feed(text, label)
            if not parsed:
                notes.append(f"{label}: feed reachable but no parsable items")
            items.extend(parsed)
        except HttpError as exc:
            notes.append(f"{label}: {exc}")
        except ET.ParseError as exc:
            notes.append(f"{label}: malformed xml ({exc})")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{label}: {exc.__class__.__name__}: {exc}")

    return items, notes


def fetch_cryptopanic(token: str, currencies: Sequence[str], timeout: float = 8.0,
                      proxy: Optional[str] = None) -> Tuple[List[NewsItem], List[str]]:
    notes: List[str] = []
    if not token:
        return [], ["cryptopanic: no token configured"]

    params = {"auth_token": token, "public": "true", "kind": "news", "limit": "40"}
    if currencies:
        params["currencies"] = ",".join(currencies)

    try:
        payload = request_json("https://cryptopanic.com/api/v1/posts/", params=params,
                               timeout=timeout, proxy=proxy)
    except HttpError as exc:
        return [], [f"cryptopanic: {exc}"]

    items: List[NewsItem] = []
    for post in (payload or {}).get("results", []) or []:
        title = _plain(post.get("title"), 300)
        if not title:
            continue
        coins = tuple(sorted({str(c.get('code', '')).upper() for c in post.get('currencies') or [] if c}))
        items.append(NewsItem(
            headline=title,
            source=f"cryptopanic:{'/'.join(coins[:3])}" if coins else "cryptopanic",
            url=post.get("url") or "",
            published_at=_parse_date(post.get("created_at") or post.get("published_at")),
            summary=_plain(post.get("story_summary") or "", 300),
        ))
    return items, notes


def fetch_fear_greed(limit: int = 5, timeout: float = 8.0, proxy: Optional[str] = None,
                     url: str = "https://api.alternative.me/fng/") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Alternative.me Crypto Fear & Greed index (0 = fear, 100 = greed)."""
    try:
        payload = request_json(url, params={"limit": max(1, int(limit))}, timeout=timeout, proxy=proxy)
    except HttpError as exc:
        return None, f"fear & greed: {exc}"

    rows = (payload or {}).get("data") or []
    if not rows:
        return None, "fear & greed: empty response"

    current = rows[0]
    history = []
    for row in rows:
        try:
            history.append({
                "value": float(row.get("value")),
                "label": row.get("value_classification") or "",
                "timestamp": row.get("timestamp"),
            })
        except (TypeError, ValueError):
            continue

    value = float(current.get("value") or 50)
    sentiment = max(-1.0, min(1.0, (value - 50.0) / 50.0))
    return {
        "value": value,
        "label": current.get("value_classification") or "",
        "sentiment": round(sentiment, 3),
        "history": history,
        "trend": _fg_trend(history),
        "updated": _parse_date(current.get("time_updated")) or datetime.now(timezone.utc),
    }, None


def _fg_trend(history: List[Dict[str, Any]]) -> str:
    if len(history) < 3:
        return "FLAT"
    newest = history[0]["value"]
    oldest = history[-1]["value"]
    delta = newest - oldest
    if delta >= 8:
        return "RISING"
    if delta <= -8:
        return "FALLING"
    return "FLAT"


def sort_by_recency(items: Iterable[NewsItem]) -> List[NewsItem]:
    far_future = datetime(2100, 1, 1, tzinfo=timezone.utc)
    return sorted(
        items,
        key=lambda it: it.published_at or far_future,
        reverse=True,
    )


def apply_relevance(items: List[NewsItem], keywords: Set[str]) -> List[NewsItem]:
    for item in items:
        hits = match_keywords(item.text, keywords)
        if hits:
            item.relevance = "SYMBOL"
            item.matched = hits
        else:
            macro_hits = match_keywords(item.text, MACRO_TERMS)
            item.relevance = "MARKET"
            item.matched = macro_hits[:3]
    return items
