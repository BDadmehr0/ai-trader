
"""
Comprehensive Scoring System
"""
from dataclasses import dataclass
from typing import Dict

@dataclass
class AnalysisScores:
    trend_score: int
    momentum_score: int
    volume_score: int
    market_structure_score: int
    timeframe_alignment_score: int
    volatility_score: int
    support_resistance_score: int
    long_score: int
    short_score: int
    neutral_score: int
    confidence: int
    signal: str
    factors: Dict[str, str]

def _score_momentum(mom):
    score = 0
    rsi_map = {'OVERSOLD': 40, 'NEUTRAL_BEARISH': -20, 'NEUTRAL': 0, 'NEUTRAL_BULLISH': 20, 'OVERBOUGHT': -40}
    score += rsi_map.get(getattr(mom, 'rsi_state', 'NEUTRAL'), 0)
    mc = getattr(mom, 'macd_cross', 'NONE')
    if mc == 'BULLISH_CROSS': score += 30
    elif mc == 'BEARISH_CROSS': score -= 30
    ms = getattr(mom, 'macd_state', '')
    if ms == 'BULLISH': score += 10
    elif ms == 'BEARISH': score -= 10
    div = getattr(mom, 'divergence', 'NONE')
    if div == 'BULLISH_DIVERGENCE': score += 50
    elif div == 'HIDDEN_BULLISH': score += 25
    elif div == 'BEARISH_DIVERGENCE': score -= 50
    elif div == 'HIDDEN_BEARISH': score -= 25
    return max(-100, min(100, score))

def _score_volume(vol):
    score = 0
    tc = getattr(vol, 'trend_confirmation', 'NEUTRAL')
    if tc == 'BULLISH': score += 30
    elif tc == 'BEARISH': score -= 30
    bq = getattr(vol, 'breakout_quality', 'NONE')
    if bq == 'STRONG': score += 40
    elif bq == 'MODERATE': score += 20
    elif bq == 'WEAK': score -= 10
    if getattr(vol, 'unusual_volume', False): score += 10
    return max(-100, min(100, score))

def _score_tf_alignment(tf_analyses):
    if not tf_analyses: return 0
    trends = []
    for v in tf_analyses.values():
        if hasattr(v, 'trend'): trends.append(v.trend)
        elif isinstance(v, dict): trends.append(v.get('trend', 'NEUTRAL'))
    if len(trends) < 2: return 0
    b = sum(1 for t in trends if t == 'BULLISH')
    c = sum(1 for t in trends if t == 'BEARISH')
    n = sum(1 for t in trends if t == 'NEUTRAL')
    if b == len(trends): return 100
    if c == len(trends): return -100
    if b > c and b >= len(trends) - n: return 50
    if c > b and c >= len(trends) - n: return -50
    if n == len(trends): return 0
    return -20

def _score_volatility(vol):
    if vol is None: return 0
    regime = getattr(vol, 'regime', 'NORMAL')
    is_trending = getattr(vol, 'is_trending', False)
    if regime == 'EXTREME': return -80
    if regime == 'HIGH': return -30 if not is_trending else 10
    if regime == 'LOW': return -10
    return 10

def _score_sr(levels, price):
    if levels is None or price <= 0: return 0
    score = 0
    r1 = getattr(levels, 'resistance_1', 0) or 0
    s1 = getattr(levels, 'support_1', 0) or 0
    if r1 and r1 > 0:
        dtr = (r1 - price) / price * 100
        if 0 <= dtr < 0.5: score -= 50
        elif 0.5 <= dtr < 1.5: score -= 25
        elif dtr > 3: score += 15
    if s1 and s1 > 0:
        dts = (price - s1) / price * 100
        if 0 <= dts < 0.5: score += 50
        elif 0.5 <= dts < 1.5: score += 25
        elif dts > 3: score -= 15
    return max(-100, min(100, score))

def calculate_scores(trend, trend_strength, momentum_analysis, volume_analysis, ms_analysis, timeframes_analysis, vol_analysis, levels, price):
    trend_map = {('BULLISH', 'STRONG'): 100, ('BULLISH', 'MODERATE'): 70, ('BULLISH', 'WEAK'): 40, ('BEARISH', 'STRONG'): -100, ('BEARISH', 'MODERATE'): -70, ('BEARISH', 'WEAK'): -40}
    trend_score = trend_map.get((trend, trend_strength), 0)
    momentum_score = _score_momentum(momentum_analysis)
    volume_score = _score_volume(volume_analysis)
    ms_score = 0
    if ms_analysis is not None:
        ms_score = (ms_analysis.hh_count * 15 - ms_analysis.ll_count * 15 + ms_analysis.hl_count * 10 - ms_analysis.lh_count * 10)
        if ms_analysis.last_breakout_direction == 'BULLISH': ms_score += 30
        elif ms_analysis.last_breakout_direction == 'BEARISH': ms_score -= 30
        if ms_analysis.strength == 'STRONG': ms_score = int(ms_score * 1.2)
    ms_score = max(-100, min(100, ms_score))
    tf_score = _score_tf_alignment(timeframes_analysis)
    vol_score = _score_volatility(vol_analysis)
    sr_score = _score_sr(levels, price)
    weights = {'trend': 25, 'momentum': 20, 'volume': 15, 'ms': 15, 'tf': 15, 'vol': 5, 'sr': 5}
    total = sum(weights.values())
    combined = (trend_score * weights['trend'] + momentum_score * weights['momentum'] + volume_score * weights['volume'] + ms_score * weights['ms'] + tf_score * weights['tf'] + vol_score * weights['vol'] + sr_score * weights['sr']) / total
    combined = max(-100, min(100, combined))
    if combined >= 0:
        long_score = int(50 + combined * 0.5)
        short_score = int(50 - combined * 0.3)
    else:
        long_score = int(50 + combined * 0.3)
        short_score = int(50 - combined * 0.5)
    neutral_score = max(0, min(100, 100 - long_score - short_score))
    long_score = max(0, min(100, long_score))
    short_score = max(0, min(100, short_score))
    abs_c = abs(combined)
    if abs_c < 15: confidence = min(max(long_score, short_score, neutral_score), 30)
    elif abs_c < 35: confidence = int(abs_c * 1.2 + 10)
    elif abs_c < 60: confidence = int(abs_c + 20)
    else: confidence = int(abs_c + 10)
    confidence = max(0, min(100, confidence))
    if combined >= 35: signal = 'LONG'
    elif combined <= -35: signal = 'SHORT'
    elif abs_c < 10: signal = 'NO_TRADE'
    else: signal = 'WAIT'
    return AnalysisScores(trend_score=trend_score,momentum_score=momentum_score,volume_score=volume_score,market_structure_score=ms_score,timeframe_alignment_score=tf_score,volatility_score=vol_score,support_resistance_score=sr_score,long_score=long_score,short_score=short_score,neutral_score=neutral_score,confidence=confidence,signal=signal.upper(),factors={})
