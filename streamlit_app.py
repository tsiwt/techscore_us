# =============================================================================
# TechScore Stock Analyzer — US Market Edition (Streamlit)
# License: GPL-3.0 | For research & education only. Not investment advice.
# =============================================================================

import os
import json
import io
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf
import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TechScore US v2.0",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

MIN_BARS = 50


# =============================================================================
# US Stock Pool Helper
# =============================================================================
class USStockPool:
    FALLBACK_SP500_TOP50 = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","AVGO",
        "JPM","XOM","TSLA","UNH","V","PG","MA","COST","JNJ","HD","ABBV","WMT",
        "NFLX","MRK","BAC","KO","PEP","CVX","CRM","AMD","ORCL","TMO","LIN",
        "ADBE","ACN","MCD","CSCO","WFC","ABT","IBM","PM","TXN","GE","QCOM",
        "INTU","DHR","NOW","CAT","AMGN","ISRG",
    ]
    FALLBACK_NDX100_TOP30 = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","AVGO","TSLA","COST",
        "NFLX","AMD","ADBE","PEP","CSCO","INTC","TMUS","CMCSA","TXN","QCOM",
        "INTU","AMGN","ISRG","HON","AMAT","BKNG","LRCX","ADP","VRTX","REGN",
    ]
    FALLBACK_DOW30 = [
        "AAPL","AMGN","AMZN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW",
        "GS","HD","HON","IBM","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE",
        "NVDA","PG","SHW","TRV","UNH","V","WMT",
    ]
    TEST10 = [
        "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ",
    ]

    @classmethod
    @st.cache_data(ttl=7 * 86400, show_spinner=False)
    def _wiki_table(_cls, url, col_candidates):
        try:
            tables = pd.read_html(url)
            for t in tables:
                for col in col_candidates:
                    if col in t.columns:
                        tickers = (
                            t[col].astype(str).str.strip()
                            .str.replace(".", "-", regex=False).tolist()
                        )
                        tickers = [tk for tk in tickers if 0 < len(tk) <= 10]
                        if len(tickers) >= 10:
                            return tickers
        except Exception:
            pass
        return None

    @classmethod
    def get_sp500(cls):
        r = cls._wiki_table(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            ["Symbol"],
        )
        return r if r else cls.FALLBACK_SP500_TOP50

    @classmethod
    def get_nasdaq100(cls):
        r = cls._wiki_table(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            ["Ticker", "Symbol"],
        )
        return r if r else cls.FALLBACK_NDX100_TOP30

    @classmethod
    def get_dow30(cls):
        r = cls._wiki_table(
            "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
            ["Symbol"],
        )
        return r if r else cls.FALLBACK_DOW30


# =============================================================================
# Technical Indicator Engine (unchanged logic)
# =============================================================================
class TechnicalIndicatorEngine:
    WEIGHTS = {
        "RSI": 0.12, "MACD": 0.15, "KDJ": 0.12, "BB": 0.10,
        "MA":  0.12, "VOL":  0.10, "ATR": 0.07, "OBV": 0.10,
        "WR":  0.06, "CCI":  0.06,
    }

    def calc(self, df: pd.DataFrame) -> dict:
        df = df.copy().reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[df["close"] > 0].copy()
        df["volume"] = df["volume"].fillna(0)
        df = df.reset_index(drop=True)
        if len(df) < MIN_BARS:
            return self._empty()

        sc, vl = {}, {}
        last_date = str(df["date"].iloc[-1]) if "date" in df.columns else ""

        vl["RSI"], sc["RSI"] = self._rsi(df["close"], 14)
        vl["MACD"], vl["MACD_Signal"], vl["MACD_Hist"], sc["MACD"] = self._macd(df["close"])
        vl["K"], vl["D"], vl["J"], sc["KDJ"] = self._kdj(df["high"], df["low"], df["close"])
        vl["BB_pct"], sc["BB"] = self._bollinger(df["close"], 20, 2)
        vl["MA5"], vl["MA20"], sc["MA"] = self._ma_cross(df["close"], 5, 20)
        vl["VolRatio"], sc["VOL"] = self._volume_ratio(df["volume"], 20)
        vl["ATR_pct"], sc["ATR"] = self._atr_pct(df["high"], df["low"], df["close"], 14)
        vl["OBV_Slope"], sc["OBV"] = self._obv_trend(df["close"], df["volume"], 5)
        vl["WR"], sc["WR"] = self._williams_r(df["high"], df["low"], df["close"], 14)
        vl["CCI"], sc["CCI"] = self._cci(df["high"], df["low"], df["close"], 14)

        composite = round(sum(sc[k] * self.WEIGHTS[k] for k in sc) * 10, 2)
        return {"values": vl, "scores": sc, "composite": composite, "last_date": last_date}

    def _empty(self):
        return {"values": {}, "scores": {k: 0 for k in self.WEIGHTS}, "composite": 0.0, "last_date": ""}

    @staticmethod
    def _ema(s, p):
        return s.ewm(span=p, adjust=False).mean()

    def _rsi(self, close, period):
        d = close.diff()
        g = d.clip(lower=0)
        l_ = (-d).clip(lower=0)
        ag = g.ewm(com=period - 1, adjust=False).mean()
        al = l_.ewm(com=period - 1, adjust=False).mean()
        rsi = 100 - 100 / (1 + ag / (al + 1e-9))
        v = round(rsi.iloc[-1], 2)
        if   v <= 20: s = 10.0
        elif v <= 30: s = 9.0
        elif v <= 40: s = 7.5
        elif v <= 50: s = 6.0
        elif v <= 60: s = 5.0
        elif v <= 70: s = 3.5
        elif v <= 80: s = 2.0
        else:         s = 1.0
        return v, s

    def _macd(self, close):
        e12 = self._ema(close, 12); e26 = self._ema(close, 26)
        macd = e12 - e26; sig = self._ema(macd, 9); hist = macd - sig
        mv, sv, hv = round(macd.iloc[-1], 4), round(sig.iloc[-1], 4), round(hist.iloc[-1], 4)
        if   mv > sv and mv > 0:  s = 9.0
        elif mv > sv and mv <= 0: s = 7.0
        elif mv <= sv and mv > 0: s = 4.0
        else:                     s = 1.5
        if len(hist) >= 2:
            s = min(10, s + 0.5) if hist.iloc[-1] > hist.iloc[-2] else max(0, s - 0.5)
        return mv, sv, hv, round(s, 2)

    def _kdj(self, high, low, close):
        p = 9
        ln = low.rolling(p).min(); hn = high.rolling(p).max()
        rsv = (close - ln) / (hn - ln + 1e-9) * 100
        K = rsv.ewm(com=2, adjust=False).mean()
        D = K.ewm(com=2, adjust=False).mean()
        J = 3 * K - 2 * D
        kv, dv, jv = round(K.iloc[-1], 2), round(D.iloc[-1], 2), round(J.iloc[-1], 2)
        if   kv < 20 and dv < 20:                                             s = 9.5
        elif kv < 30 and K.iloc[-1] > K.iloc[-2] and K.iloc[-2] < D.iloc[-2]: s = 8.5
        elif kv > 80 and dv > 80:                                             s = 1.5
        elif kv > 70 and K.iloc[-1] < K.iloc[-2] and K.iloc[-2] > D.iloc[-2]: s = 2.0
        elif kv > dv:                                                          s = 6.5
        else:                                                                  s = 4.0
        if   jv < 0:   s = min(10, s + 1)
        elif jv > 100: s = max(0, s - 1)
        return kv, dv, jv, round(s, 2)

    def _bollinger(self, close, period, mult):
        ma = close.rolling(period).mean(); sd = close.rolling(period).std()
        up = ma + mult * sd; lo = ma - mult * sd
        bw = up.iloc[-1] - lo.iloc[-1]
        bp = 0.5 if bw < 1e-9 else (close.iloc[-1] - lo.iloc[-1]) / bw
        v = round(bp, 4)
        if   v < 0:    s = 9.5
        elif v < 0.15: s = 8.5
        elif v < 0.35: s = 7.0
        elif v < 0.65: s = 5.5
        elif v < 0.85: s = 3.5
        elif v < 1.0:  s = 2.0
        else:          s = 1.0
        return v, round(s, 2)

    def _ma_cross(self, close, fast, slow):
        mf = close.rolling(fast).mean(); ms = close.rolling(slow).mean()
        m5 = round(mf.iloc[-1], 4); m20 = round(ms.iloc[-1], 4)
        pd_ = mf.iloc[-2] - ms.iloc[-2]; cd = mf.iloc[-1] - ms.iloc[-1]
        if   pd_ < 0 and cd > 0: s = 10.0
        elif pd_ > 0 and cd < 0: s = 1.0
        elif cd > 0:
            s = 6.0 if cd / (ms.iloc[-1] + 1e-9) > 0.05 else 7.5
        else: s = 3.0
        return m5, m20, round(s, 2)

    @staticmethod
    def _volume_ratio(vol, period):
        av = vol.iloc[-period - 1:-1].mean(); cv = vol.iloc[-1]
        vr = 1.0 if av < 1e-9 else cv / av; v = round(vr, 3)
        if   vr > 4.0: s = 8.5
        elif vr > 2.5: s = 9.0
        elif vr > 1.8: s = 8.0
        elif vr > 1.2: s = 6.5
        elif vr > 0.8: s = 5.0
        elif vr > 0.5: s = 3.0
        else:          s = 1.5
        return v, round(s, 2)

    def _atr_pct(self, high, low, close, period):
        pc = close.shift(1)
        tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
        ap = tr.rolling(period).mean() / (close + 1e-9) * 100
        v = round(ap.iloc[-1], 3)
        if   1.0 <= v <= 2.0:                   s = 8.0
        elif 0.5 <= v < 1.0 or 2.0 < v <= 3.0: s = 6.5
        elif 0.3 <= v < 0.5 or 3.0 < v <= 5.0: s = 4.5
        elif v > 5.0:                            s = 2.0
        else:                                    s = 3.5
        return v, round(s, 2)

    @staticmethod
    def _obv_trend(close, volume, period):
        dr = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (dr * volume).cumsum()
        r = obv.iloc[-period:].values
        if len(r) < 2: return 0.0, 5.0
        sl = np.polyfit(np.arange(len(r)), r, 1)[0]
        ns = sl / (np.mean(np.abs(r)) + 1e-9)
        if   ns > 0.05:  s = 9.0
        elif ns > 0.02:  s = 7.5
        elif ns > 0:     s = 6.0
        elif ns > -0.02: s = 4.5
        elif ns > -0.05: s = 3.0
        else:            s = 1.5
        return round(float(ns), 5), round(s, 2)

    @staticmethod
    def _williams_r(high, low, close, period):
        hn = high.rolling(period).max(); ln = low.rolling(period).min()
        wr = (hn - close) / (hn - ln + 1e-9) * (-100)
        v = round(wr.iloc[-1], 2)
        if   v <= -90: s = 9.5
        elif v <= -80: s = 8.0
        elif v <= -50: s = 5.5
        elif v <= -20: s = 3.5
        else:          s = 1.5
        return v, round(s, 2)

    @staticmethod
    def _cci(high, low, close, period):
        tp = (high + low + close) / 3
        ma = tp.rolling(period).mean()
        md = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        cci = (tp - ma) / (0.015 * md + 1e-9)
        v = round(cci.iloc[-1], 2)
        if   v < -200: s = 9.5
        elif v < -100: s = 8.0
        elif v < 0:    s = 6.0
        elif v < 100:  s = 4.5
        elif v < 200:  s = 2.5
        else:          s = 1.0
        return v, round(s, 2)


# =============================================================================
# Core Scoring Function
# =============================================================================
def build_code_list(scopes):
    codes = set()
    if "test10" in scopes:
        return USStockPool.TEST10
    if "sp500"  in scopes: codes.update(USStockPool.get_sp500())
    if "ndx100" in scopes: codes.update(USStockPool.get_nasdaq100())
    if "dow30"  in scopes: codes.update(USStockPool.get_dow30())
    return sorted(codes) if codes else USStockPool.TEST10


def run_scoring(scopes, days, single_ticker=None):
    """Download + score. Returns a DataFrame."""
    engine = TechnicalIndicatorEngine()
    end = datetime.now()
    start = end - timedelta(days=days)
    s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # Determine ticker list
    if single_ticker:
        clist = [single_ticker.strip().upper()]
    else:
        clist = build_code_list(scopes)

    total = len(clist)
    if total == 0:
        return None, "⚠️ No tickers."

    progress = st.progress(0, text=f"Downloading {total} tickers...")

    # ── Phase 1: batch download ──
    try:
        if total == 1:
            raw = yf.download(clist[0], start=s_str, end=e_str, progress=False, threads=False)
            all_data = {clist[0]: raw}
            multi = False
        else:
            raw = yf.download(
                " ".join(clist), start=s_str, end=e_str,
                group_by="ticker", threads=True, progress=False,
            )
            all_data = raw
            multi = True
    except Exception as e:
        return None, f"❌ Download failed: {e}"

    # ── Phase 2: score ──
    rows = []
    skipped = 0
    for i, ticker in enumerate(clist):
        progress.progress((i + 1) / total, text=f"[{i+1}/{total}] Scoring {ticker}")
        try:
            if multi:
                try:
                    hist = all_data[ticker].dropna(how="all")
                except (KeyError, TypeError):
                    skipped += 1; continue
            else:
                hist = all_data[ticker]

            if hist is None or len(hist) == 0:
                skipped += 1; continue

            df = pd.DataFrame({
                "date":   hist.index.strftime("%Y-%m-%d"),
                "open":   hist["Open"].values,
                "high":   hist["High"].values,
                "low":    hist["Low"].values,
                "close":  hist["Close"].values,
                "volume": hist["Volume"].values,
            })

            result = engine.calc(df)
            if result["composite"] == 0.0 and all(v == 0 for v in result["scores"].values()):
                skipped += 1; continue

            vl = result.get("values", {})
            sc = result.get("scores", {})
            rows.append({
                "Ticker":     ticker,
                "Last Date":  result.get("last_date", ""),
                "Score":      result.get("composite", 0),
                "RSI_S":  sc.get("RSI", 0),  "MACD_S": sc.get("MACD", 0),
                "KDJ_S":  sc.get("KDJ", 0),  "BB_S":   sc.get("BB", 0),
                "MA_S":   sc.get("MA", 0),    "Vol_S":  sc.get("VOL", 0),
                "ATR_S":  sc.get("ATR", 0),   "OBV_S":  sc.get("OBV", 0),
                "WR_S":   sc.get("WR", 0),    "CCI_S":  sc.get("CCI", 0),
                "RSI":        vl.get("RSI", ""),
                "MACD_Hist":  vl.get("MACD_Hist", ""),
                "K": vl.get("K",""), "D": vl.get("D",""), "J": vl.get("J",""),
                "BB%":        vl.get("BB_pct", ""),
                "MA5":        vl.get("MA5", ""),
                "MA20":       vl.get("MA20", ""),
                "VolRatio":   vl.get("VolRatio", ""),
                "ATR%":       vl.get("ATR_pct", ""),
                "OBV_Slope":  vl.get("OBV_Slope", ""),
                "WR":         vl.get("WR", ""),
                "CCI":        vl.get("CCI", ""),
            })
        except Exception:
            skipped += 1

    progress.empty()

    if not rows:
        return None, f"⚠️ No valid results (skipped {skipped})."

    out = pd.DataFrame(rows).sort_values("Score", ascending=False).reset_index(drop=True)
    out.index += 1
    out.index.name = "#"
    return out, f"✅ Scored {len(out)} stocks (skipped {skipped})"


# =============================================================================
# Color formatting helpers
# =============================================================================
def color_score(val):
    """Color the composite score cell."""
    try:
        v = float(val)
    except (ValueError, TypeError):
        return ""
    if v >= 75: return "background-color: #FFCDD2; color: #B71C1C; font-weight: bold"
    if v >= 60: return "background-color: #FFE0B2; color: #E65100; font-weight: bold"
    if v < 45:  return "background-color: #E8F5E9; color: #2E7D32"
    return ""


def color_sub(val):
    try:
        v = float(val)
    except (ValueError, TypeError):
        return ""
    if v >= 8.5: return "background-color: #FFCDD2; color: #B71C1C"
    return ""


def style_df(df):
    """Apply conditional formatting to the result DataFrame."""
    sub_cols = [c for c in df.columns if c.endswith("_S")]
    styler = df.style
    if "Score" in df.columns:
        styler = styler.map(color_score, subset=["Score"])
    if sub_cols:
        styler = styler.map(color_sub, subset=sub_cols)
    styler = styler.format(precision=2, na_rep="-")
    return styler


# =============================================================================
# Indicator Help Text
# =============================================================================
INDICATOR_HELP = """
### 📐 10 Technical Indicator Scoring Guide

| # | Indicator | Weight | Scoring Logic (higher = more oversold/bullish) |
|---|-----------|--------|------------------------------------------------|
| 1 | **RSI(14)** | 12% | ≤20→10 \| ≤30→9 \| ≤40→7.5 \| ≤50→6 \| ≤60→5 \| ≤70→3.5 \| ≤80→2 \| >80→1 |
| 2 | **MACD(12,26,9)** | 15% | MACD>Sig & >0→9 \| >Sig & ≤0→7 \| ≤Sig & >0→4 \| else→1.5 |
| 3 | **KDJ(9,3,3)** | 12% | K<20&D<20→9.5 \| Golden cross→8.5 \| K>80&D>80→1.5 |
| 4 | **Bollinger %B** | 10% | <0→9.5 \| <.15→8.5 \| <.35→7 \| <.65→5.5 \| <.85→3.5 \| <1→2 \| ≥1→1 |
| 5 | **MA Cross(5/20)** | 12% | Golden cross→10 \| Death cross→1 \| MA5>MA20→7.5 \| MA5<MA20→3 |
| 6 | **Volume Ratio** | 10% | 2.5~4→9 \| >4→8.5 \| 1.8~2.5→8 \| 1.2~1.8→6.5 \| 0.8~1.2→5 |
| 7 | **ATR%(14)** | 7% | 1~2%→8 \| 0.5~1% / 2~3%→6.5 \| >5%→2 |
| 8 | **OBV Trend** | 10% | slope>.05→9 \| >.02→7.5 \| >0→6 \| >-.02→4.5 \| ≤-.05→1.5 |
| 9 | **Williams %R** | 6% | ≤-90→9.5 \| ≤-80→8 \| ≤-50→5.5 \| ≤-20→3.5 \| >-20→1.5 |
| 10 | **CCI(14)** | 6% | <-200→9.5 \| <-100→8 \| <0→6 \| <100→4.5 \| <200→2.5 \| ≥200→1 |

> **Higher composite score = more oversold / bullish signals (contrarian model)**
"""


# =============================================================================
# Streamlit UI
# =============================================================================
def main():
    st.title("📈 TechScore US v2.0")
    st.caption("10-Indicator Composite Scoring System for US Stocks  ·  Data: Yahoo Finance  ·  GPL-3.0")

    # ── Sidebar ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Configuration")

        mode = st.radio("Mode", ["Stock Pool", "Single Ticker"], horizontal=True)

        if mode == "Single Ticker":
            single = st.text_input("Ticker", value="AAPL", max_chars=10).upper()
            scopes = []
        else:
            single = None
            st.markdown("**Select pool(s):**")
            use_test  = st.checkbox("Test (10 stocks)", value=False)
            use_sp500 = st.checkbox("S&P 500", value=True, disabled=use_test)
            use_ndx   = st.checkbox("NASDAQ-100", value=False, disabled=use_test)
            use_dow   = st.checkbox("Dow Jones 30", value=False, disabled=use_test)
            scopes = []
            if use_test:
                scopes = ["test10"]
            else:
                if use_sp500: scopes.append("sp500")
                if use_ndx:   scopes.append("ndx100")
                if use_dow:   scopes.append("dow30")
            if not scopes and not single:
                scopes = ["test10"]

        days = st.slider("History (calendar days)", 80, 600, 200, step=10,
                         help="Recommend ≥ 150 for reliable MACD/MA signals")

        run_btn = st.button("🚀 Run Scoring", type="primary", use_container_width=True)

        st.divider()
        with st.expander("📖 Indicator Guide"):
            st.markdown(INDICATOR_HELP)

        st.divider()
        st.markdown(
            "<small>⚠️ For research & education only.<br>"
            "Not investment advice. Use at your own risk.</small>",
            unsafe_allow_html=True,
        )

    # ── Main Area ────────────────────────────────────────────────────────
    if run_btn:
        with st.spinner("Working..."):
            result_df, msg = run_scoring(scopes, days, single_ticker=single)
        if result_df is not None:
            st.session_state["result_df"] = result_df
            st.session_state["result_msg"] = msg
        else:
            st.error(msg)

    # ── Display results ──────────────────────────────────────────────────
    if "result_df" in st.session_state:
        df = st.session_state["result_df"]
        msg = st.session_state.get("result_msg", "")
        st.success(msg)

        # Quick stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stocks Scored", len(df))
        c2.metric("Avg Score", f"{df['Score'].mean():.1f}")
        c3.metric("Max Score", f"{df['Score'].max():.1f}")
        c4.metric("Min Score", f"{df['Score'].min():.1f}")

        # Score distribution
        with st.expander("📊 Score Distribution", expanded=False):
            bins = [0, 30, 45, 60, 75, 100]
            labels = ["0-30 (Strong Bear)", "30-45 (Weak Bear)",
                      "45-60 (Neutral)", "60-75 (Bullish)", "75-100 (Strong Bull)"]
            dist = pd.cut(df["Score"], bins=bins, labels=labels, right=True).value_counts().sort_index()
            st.bar_chart(dist)

        # Filterable table
        st.subheader("📋 Full Results")
        score_range = st.slider(
            "Filter by Score", 0.0, 100.0, (0.0, 100.0), step=1.0
        )
        filtered = df[(df["Score"] >= score_range[0]) & (df["Score"] <= score_range[1])]
        st.caption(f"Showing {len(filtered)} of {len(df)} stocks  ·  Click column headers to sort")
        st.dataframe(
            style_df(filtered),
            use_container_width=True,
            height=min(36 * len(filtered) + 38, 800),
        )

        # Yahoo Finance link
        st.caption("💡 Click a ticker below to open Yahoo Finance:")
        ticker_links = " · ".join(
            f"[{t}](https://finance.yahoo.com/quote/{t})"
            for t in filtered["Ticker"].tolist()[:50]
        )
        st.markdown(ticker_links)

        # Download button
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=True)
        st.download_button(
            "⬇️ Download CSV",
            data=csv_buf.getvalue(),
            file_name=f"TechScore_US_{datetime.now():%Y%m%d_%H%M}.csv",
            mime="text/csv",
        )

    # ── Upload previous CSV ──────────────────────────────────────────────
    with st.expander("📂 Load Previous CSV"):
        uploaded = st.file_uploader("Upload a TechScore CSV", type="csv")
        if uploaded:
            try:
                loaded = pd.read_csv(uploaded)
                if "composite" in loaded.columns:
                    loaded = loaded.rename(columns={"composite": "Score", "ticker": "Ticker",
                                                    "name": "Name", "last_date": "Last Date"})
                loaded = loaded.sort_values("Score", ascending=False).reset_index(drop=True)
                loaded.index += 1
                loaded.index.name = "#"
                st.session_state["result_df"] = loaded
                st.session_state["result_msg"] = f"✅ Loaded {len(loaded)} stocks from CSV"
                st.rerun()
            except Exception as e:
                st.error(f"Load failed: {e}")


if __name__ == "__main__":
    main()

