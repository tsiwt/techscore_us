# =============================================================================
# TechScore Stock Analyzer — US Market Edition
# Copyright (C) 2025  Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Version: 2.0.0
# Description:
#   A daily technical-indicator based stock scoring system for US markets.
#   Uses yfinance for historical & real-time data, calculates 10 common
#   indicators (RSI, MACD, KDJ, Bollinger Bands, MA Cross, Volume Ratio,
#   ATR, OBV Trend, Williams %R, CCI) and generates a composite score 0-100.
#
# Disclaimer:
#   This software is for research and educational purposes only.
#   It does not constitute any investment advice or recommendation.
#   All investment decisions and associated risks are solely the
#   responsibility of the user.
# =============================================================================

import sys
import os
import json
import glob
import webbrowser
import subprocess
import platform
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    print(
        "Error: missing required library.\n"
        "Run:  pip install yfinance pandas numpy PyQt5"
    )
    sys.exit(1)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar,
    QFileDialog, QMessageBox, QDialog, QCheckBox,
    QDialogButtonBox, QGroupBox, QSpinBox, QFrame,
    QAbstractItemView, QLineEdit, QRadioButton,
    QButtonGroup, QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor


# =============================================================================
# Global Configuration
# =============================================================================
SYSTEM_NAME = "TechScore_US_v2.0"
SCRIPT_DIR  = os.path.dirname(os.path.realpath(sys.argv[0]))
DATA_ROOT   = os.path.join(SCRIPT_DIR, "TechScore_Data_US")
PREDS_DIR   = os.path.join(DATA_ROOT, "Predictions")

for _d in [DATA_ROOT, PREDS_DIR]:
    if not os.path.exists(_d):
        os.makedirs(_d)

# Minimum valid bars required (MACD needs 26, plus warm-up)
MIN_BARS = 50

# Proxy hint
_proxy = os.environ.get("HTTPS_PROXY", "") or os.environ.get("HTTP_PROXY", "")
if _proxy:
    print(f"[INFO] Proxy detected: {_proxy}")
else:
    print(
        "[INFO] No proxy set. If yfinance times out in China, run:\n"
        "       export HTTPS_PROXY=http://127.0.0.1:7890"
    )


# =============================================================================
# US Stock Pool Helper
# =============================================================================
class USStockPool:
    """
    Fetches index constituents from Wikipedia with local JSON cache.
    """
    CACHE_FILE = os.path.join(DATA_ROOT, "pool_cache.json")
    CACHE_TTL  = 7  # days

    # ----- Hardcoded fallbacks (top holdings, updated 2025-Q1) -----
    FALLBACK_SP500_TOP50 = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
        "BRK-B", "LLY", "AVGO", "JPM", "XOM", "TSLA", "UNH", "V",
        "PG", "MA", "COST", "JNJ", "HD", "ABBV", "WMT", "NFLX",
        "MRK", "BAC", "KO", "PEP", "CVX", "CRM", "AMD", "ORCL",
        "TMO", "LIN", "ADBE", "ACN", "MCD", "CSCO", "WFC", "ABT",
        "IBM", "PM", "TXN", "GE", "QCOM", "INTU", "DHR", "NOW",
        "CAT", "AMGN", "ISRG",
    ]

    FALLBACK_NDX100_TOP30 = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
        "AVGO", "TSLA", "COST", "NFLX", "AMD", "ADBE", "PEP",
        "CSCO", "INTC", "TMUS", "CMCSA", "TXN", "QCOM", "INTU",
        "AMGN", "ISRG", "HON", "AMAT", "BKNG", "LRCX", "ADP",
        "VRTX", "REGN",
    ]

    FALLBACK_DOW30 = [
        "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM",
        "CSCO", "CVX", "DIS", "DOW", "GS", "HD", "HON", "IBM",
        "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT",
        "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "WMT",
    ]

    @classmethod
    def _load_cache(cls):
        if os.path.exists(cls.CACHE_FILE):
            try:
                with open(cls.CACHE_FILE, "r") as f:
                    data = json.load(f)
                ts = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
                if (datetime.now() - ts).days < cls.CACHE_TTL:
                    return data
            except Exception:
                pass
        return None

    @classmethod
    def _save_cache(cls, data):
        data["timestamp"] = datetime.now().isoformat()
        try:
            with open(cls.CACHE_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    @classmethod
    def _wiki_table(cls, url, cache_key, id_attr=None, col_candidates=None):
        """Generic Wikipedia table scraper with multiple fallbacks."""
        cache = cls._load_cache()
        if cache and cache_key in cache:
            return cache[cache_key]

        col_candidates = col_candidates or ["Symbol", "Ticker", "symbol", "ticker"]
        try:
            kwargs = {}
            if id_attr:
                kwargs["attrs"] = {"id": id_attr}
            tables = pd.read_html(url, **kwargs)
            for t in tables:
                for col in col_candidates:
                    if col in t.columns:
                        tickers = (
                            t[col]
                            .astype(str)
                            .str.strip()
                            .str.replace(".", "-", regex=False)
                            .tolist()
                        )
                        # sanity: tickers should be short uppercase strings
                        tickers = [
                            tk for tk in tickers
                            if 0 < len(tk) <= 10 and tk == tk.upper().replace("-", tk)
                                or tk.replace("-", "").isalpha()
                        ]
                        if len(tickers) >= 10:
                            cache = cls._load_cache() or {}
                            cache[cache_key] = tickers
                            cls._save_cache(cache)
                            return tickers
        except Exception:
            pass
        return None

    @classmethod
    def get_sp500(cls) -> list:
        result = cls._wiki_table(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            "sp500",
            id_attr="constituents",
            col_candidates=["Symbol"],
        )
        return result if result else cls.FALLBACK_SP500_TOP50

    @classmethod
    def get_nasdaq100(cls) -> list:
        result = cls._wiki_table(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            "nasdaq100",
            id_attr="constituents",
            col_candidates=["Ticker", "Symbol"],
        )
        return result if result else cls.FALLBACK_NDX100_TOP30

    @classmethod
    def get_dow30(cls) -> list:
        result = cls._wiki_table(
            "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
            "dow30",
            col_candidates=["Symbol"],
        )
        return result if result else cls.FALLBACK_DOW30

    @classmethod
    def get_test10(cls) -> list:
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
            "META", "TSLA", "JPM", "V", "JNJ",
        ]


# =============================================================================
# Technical Indicator Engine
# =============================================================================
class TechnicalIndicatorEngine:
    """
    Calculates 10 technical indicators → composite score 0–100.

    1. RSI(14)          2. MACD(12,26,9)    3. KDJ(9,3,3)
    4. Bollinger %B(20) 5. MA Cross(5/20)   6. Volume Ratio(20)
    7. ATR%(14)         8. OBV Trend(5)     9. Williams %R(14)
    10. CCI(14)
    """

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

        vl["RSI"],                       sc["RSI"]  = self._rsi(df["close"], 14)
        vl["MACD"], vl["MACD_Signal"], vl["MACD_Hist"], sc["MACD"] = self._macd(df["close"])
        vl["K"], vl["D"], vl["J"],       sc["KDJ"]  = self._kdj(df["high"], df["low"], df["close"])
        vl["BB_pct"],                    sc["BB"]   = self._bollinger(df["close"], 20, 2)
        vl["MA5"], vl["MA20"],           sc["MA"]   = self._ma_cross(df["close"], 5, 20)
        vl["VolRatio"],                  sc["VOL"]  = self._volume_ratio(df["volume"], 20)
        vl["ATR_pct"],                   sc["ATR"]  = self._atr_pct(df["high"], df["low"], df["close"], 14)
        vl["OBV_Slope"],                 sc["OBV"]  = self._obv_trend(df["close"], df["volume"], 5)
        vl["WR"],                        sc["WR"]   = self._williams_r(df["high"], df["low"], df["close"], 14)
        vl["CCI"],                       sc["CCI"]  = self._cci(df["high"], df["low"], df["close"], 14)

        composite = round(sum(sc[k] * self.WEIGHTS[k] for k in sc) * 10, 2)
        return {"values": vl, "scores": sc, "composite": composite, "last_date": last_date}

    def _empty(self):
        return {"values": {}, "scores": {k: 0 for k in self.WEIGHTS}, "composite": 0.0, "last_date": ""}

    @staticmethod
    def _ema(s, p):
        return s.ewm(span=p, adjust=False).mean()

    # ---------- 1. RSI ----------
    def _rsi(self, close, period):
        d = close.diff()
        g = d.clip(lower=0)
        l = (-d).clip(lower=0)
        ag = g.ewm(com=period - 1, adjust=False).mean()
        al = l.ewm(com=period - 1, adjust=False).mean()
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

    # ---------- 2. MACD ----------
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

    # ---------- 3. KDJ ----------
    def _kdj(self, high, low, close):
        p = 9
        ln = low.rolling(p).min(); hn = high.rolling(p).max()
        rsv = (close - ln) / (hn - ln + 1e-9) * 100
        K = rsv.ewm(com=2, adjust=False).mean()
        D = K.ewm(com=2, adjust=False).mean()
        J = 3 * K - 2 * D
        kv, dv, jv = round(K.iloc[-1], 2), round(D.iloc[-1], 2), round(J.iloc[-1], 2)
        if   kv < 20 and dv < 20:                                                s = 9.5
        elif kv < 30 and K.iloc[-1] > K.iloc[-2] and K.iloc[-2] < D.iloc[-2]:    s = 8.5
        elif kv > 80 and dv > 80:                                                s = 1.5
        elif kv > 70 and K.iloc[-1] < K.iloc[-2] and K.iloc[-2] > D.iloc[-2]:    s = 2.0
        elif kv > dv:                                                             s = 6.5
        else:                                                                     s = 4.0
        if   jv < 0:   s = min(10, s + 1)
        elif jv > 100: s = max(0, s - 1)
        return kv, dv, jv, round(s, 2)

    # ---------- 4. Bollinger %B ----------
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

    # ---------- 5. MA Cross ----------
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

    # ---------- 6. Volume Ratio ----------
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

    # ---------- 7. ATR% ----------
    def _atr_pct(self, high, low, close, period):
        pc = close.shift(1)
        tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
        ap = tr.rolling(period).mean() / (close + 1e-9) * 100
        v = round(ap.iloc[-1], 3)
        if   1.0 <= v <= 2.0:                     s = 8.0
        elif 0.5 <= v < 1.0 or 2.0 < v <= 3.0:   s = 6.5
        elif 0.3 <= v < 0.5 or 3.0 < v <= 5.0:   s = 4.5
        elif v > 5.0:                              s = 2.0
        else:                                      s = 3.5
        return v, round(s, 2)

    # ---------- 8. OBV Trend ----------
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

    # ---------- 9. Williams %R ----------
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

    # ---------- 10. CCI ----------
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
# UI Helpers
# =============================================================================
class NumericItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.data(Qt.UserRole)) < float(other.data(Qt.UserRole))
        except Exception:
            return super().__lt__(other)


class ScopeSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update & Score Configuration")
        self.resize(440, 380)
        lay = QVBoxLayout(self)

        # --- Stock Pool ---
        g1 = QGroupBox("1. Target Stock Pool")
        v1 = QVBoxLayout()
        self.bg = QButtonGroup(self)

        self.r_pool = QRadioButton("Pool Mode")
        self.r_pool.setChecked(True)
        self.bg.addButton(self.r_pool)
        v1.addWidget(self.r_pool)

        self.f_pool = QFrame()
        lp = QVBoxLayout(self.f_pool)
        self.c_test  = QCheckBox("Test (10 stocks)")
        self.c_sp500 = QCheckBox("S&&P 500")
        self.c_ndx   = QCheckBox("NASDAQ-100")
        self.c_dow   = QCheckBox("Dow Jones 30")
        self.c_sp500.setChecked(True)
        self.all_checks = [self.c_test, self.c_sp500, self.c_ndx, self.c_dow]
        for c in self.all_checks:
            lp.addWidget(c)
        v1.addWidget(self.f_pool)

        self.r_one = QRadioButton("Single Ticker Mode")
        self.bg.addButton(self.r_one)
        v1.addWidget(self.r_one)
        self.e_code = QLineEdit("AAPL")
        self.e_code.setEnabled(False)
        v1.addWidget(self.e_code)
        g1.setLayout(v1)
        lay.addWidget(g1)

        # --- Days ---
        g2 = QGroupBox("2. History Period (calendar days; recommend >= 150)")
        h2 = QHBoxLayout()
        self.s_days = QSpinBox()
        self.s_days.setRange(80, 600)
        self.s_days.setValue(200)
        self.s_days.setSuffix(" days")
        h2.addWidget(QLabel("Download:"))
        h2.addWidget(self.s_days)
        g2.setLayout(h2)
        lay.addWidget(g2)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.r_pool.toggled.connect(lambda: (self.f_pool.setEnabled(True), self.e_code.setEnabled(False)))
        self.r_one.toggled.connect(lambda: (self.f_pool.setEnabled(False), self.e_code.setEnabled(True)))
        self.c_test.toggled.connect(self._on_test)

    def _on_test(self, chk):
        if chk:
            for c in self.all_checks:
                if c is not self.c_test:
                    c.setChecked(False); c.setEnabled(False)
        else:
            for c in self.all_checks:
                c.setEnabled(True)

    def get_data(self):
        days = self.s_days.value()
        if self.r_one.isChecked():
            return ["single:" + self.e_code.text().strip().upper()], days
        if self.c_test.isChecked():
            return ["test10"], days
        s = []
        if self.c_sp500.isChecked(): s.append("sp500")
        if self.c_ndx.isChecked():   s.append("ndx100")
        if self.c_dow.isChecked():   s.append("dow30")
        return (s if s else ["test10"]), days


# =============================================================================
# Context
# =============================================================================
class Context:
    def __init__(self, code, name=""):
        self.code         = code
        self.name         = name or code
        self.curr_price   = "-"
        self.curr_pct     = "-"
        self.score_result = {}
        self.last_date    = ""


# =============================================================================
# Data Manager
# =============================================================================
class DataManager:
    def __init__(self):
        self.engine   = TechnicalIndicatorEngine()
        self.ctxs     = []

    # ------------------------------------------------------------------
    def _build_code_list(self, scopes):
        codes = set()
        if scopes[0].startswith("single:"):
            codes.add(scopes[0].split(":")[1])
            return sorted(codes)
        if "test10" in scopes:
            return USStockPool.get_test10()
        if "sp500"  in scopes: codes.update(USStockPool.get_sp500())
        if "ndx100" in scopes: codes.update(USStockPool.get_nasdaq100())
        if "dow30"  in scopes: codes.update(USStockPool.get_dow30())
        return sorted(codes)

    # ------------------------------------------------------------------
    def run_update_and_score(self, scopes, days, cb):
        end   = datetime.now()
        start = end - timedelta(days=days)
        s_str = start.strftime("%Y-%m-%d")
        e_str = end.strftime("%Y-%m-%d")

        clist = self._build_code_list(scopes)
        total = len(clist)
        if total == 0:
            return "⚠️ No tickers found. Check your network or pool config."

        # -------- Phase 1: Batch download --------
        if cb:
            cb(0, total, f"Batch downloading {total} tickers from Yahoo Finance...")

        try:
            if total == 1:
                raw = yf.download(
                    clist[0], start=s_str, end=e_str,
                    progress=False, threads=False
                )
                # Wrap in dict-like for uniform handling
                all_data = {clist[0]: raw}
                multi = False
            else:
                joined = " ".join(clist)
                raw = yf.download(
                    joined, start=s_str, end=e_str,
                    group_by="ticker", threads=True, progress=False
                )
                all_data = raw
                multi = True
        except Exception as e:
            return (
                f"❌ yfinance download failed: {e}\n\n"
                f"If you are in China, make sure your proxy is set:\n"
                f"  export HTTPS_PROXY=http://127.0.0.1:7890"
            )

        # -------- Phase 2: Score each ticker --------
        self.ctxs = []
        skipped   = 0

        for i, ticker in enumerate(clist):
            if cb:
                cb(i, total, f"[{i + 1}/{total}] Scoring: {ticker}")
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

                result = self.engine.calc(df)
                if result["composite"] == 0.0 and all(v == 0 for v in result["scores"].values()):
                    skipped += 1; continue

                ctx              = Context(ticker, ticker)
                ctx.score_result = result
                ctx.last_date    = result.get("last_date", "")
                self.ctxs.append(ctx)
            except Exception:
                skipped += 1

        # -------- Phase 3: Fill company names --------
        if cb:
            cb(total - 1, total, "Looking up company names...")
        self._fill_names(cb, total)

        if not self.ctxs:
            return (
                f"⚠️ No valid data (skipped {skipped} tickers).\n"
                f"All tickers had fewer than {MIN_BARS} valid bars.\n"
                f"Try increasing the history period to 200+ days."
            )

        saved = self._save_csv()
        return (
            f"✅ Done: scored {len(self.ctxs)} stocks "
            f"(skipped {skipped}).\n"
            f"Results saved to: {saved}"
        )

    # ------------------------------------------------------------------
    def _fill_names(self, cb=None, total=0):
        """Best-effort ticker → company name lookup."""
        for i, ctx in enumerate(self.ctxs):
            if cb and total:
                cb(min(i, total - 1), total, f"Name lookup: {ctx.code}")
            try:
                info = yf.Ticker(ctx.code).info
                ctx.name = (
                    info.get("shortName", "")
                    or info.get("longName", "")
                    or ctx.code
                )
            except Exception:
                ctx.name = ctx.code

    # ------------------------------------------------------------------
    def _save_csv(self) -> str:
        ts   = datetime.now().strftime("%Y-%m-%d_%H%M")
        rows = []
        for ctx in self.ctxs:
            r  = ctx.score_result
            vl = r.get("values", {})
            sc = r.get("scores", {})
            rows.append({
                "ticker":      ctx.code,
                "name":        ctx.name,
                "last_date":   ctx.last_date,
                "composite":   r.get("composite", 0),
                "RSI":         vl.get("RSI",        ""),
                "MACD":        vl.get("MACD",        ""),
                "MACD_Signal": vl.get("MACD_Signal", ""),
                "MACD_Hist":   vl.get("MACD_Hist",   ""),
                "K":           vl.get("K",           ""),
                "D":           vl.get("D",           ""),
                "J":           vl.get("J",           ""),
                "BB_pct":      vl.get("BB_pct",      ""),
                "MA5":         vl.get("MA5",         ""),
                "MA20":        vl.get("MA20",        ""),
                "VolRatio":    vl.get("VolRatio",    ""),
                "ATR_pct":     vl.get("ATR_pct",     ""),
                "OBV_Slope":   vl.get("OBV_Slope",   ""),
                "WR":          vl.get("WR",          ""),
                "CCI":         vl.get("CCI",         ""),
                "Score_RSI":   sc.get("RSI",  0),
                "Score_MACD":  sc.get("MACD", 0),
                "Score_KDJ":   sc.get("KDJ",  0),
                "Score_BB":    sc.get("BB",   0),
                "Score_MA":    sc.get("MA",   0),
                "Score_VOL":   sc.get("VOL",  0),
                "Score_ATR":   sc.get("ATR",  0),
                "Score_OBV":   sc.get("OBV",  0),
                "Score_WR":    sc.get("WR",   0),
                "Score_CCI":   sc.get("CCI",  0),
            })
        df  = pd.DataFrame(rows).sort_values("composite", ascending=False)
        out = os.path.join(PREDS_DIR, f"TechScore_US_{ts}.csv")
        df.to_csv(out, index=False, encoding="utf-8-sig")
        return out

    # ------------------------------------------------------------------
    def save_csv_manual(self) -> str:
        if not self.ctxs:
            return "⚠️ No data. Run 'Update & Score' first."
        p = self._save_csv()
        return f"✅ Saved: {p}  ({len(self.ctxs)} stocks)"

    # ------------------------------------------------------------------
    def load_from_csv(self, path: str) -> str:
        try:
            df = pd.read_csv(path)
            self.ctxs = []
            for _, row in df.iterrows():
                ctx = Context(
                    str(row.get("ticker", row.get("code", ""))),
                    str(row.get("name", ""))
                )
                ctx.last_date = str(row.get("last_date", ""))
                ctx.score_result = {
                    "composite": float(row.get("composite", 0)),
                    "last_date": ctx.last_date,
                    "scores": {
                        "RSI":  float(row.get("Score_RSI",  0)),
                        "MACD": float(row.get("Score_MACD", 0)),
                        "KDJ":  float(row.get("Score_KDJ",  0)),
                        "BB":   float(row.get("Score_BB",   0)),
                        "MA":   float(row.get("Score_MA",   0)),
                        "VOL":  float(row.get("Score_VOL",  0)),
                        "ATR":  float(row.get("Score_ATR",  0)),
                        "OBV":  float(row.get("Score_OBV",  0)),
                        "WR":   float(row.get("Score_WR",   0)),
                        "CCI":  float(row.get("Score_CCI",  0)),
                    },
                    "values": {
                        "RSI":       row.get("RSI",        ""),
                        "MACD_Hist": row.get("MACD_Hist",  ""),
                        "K":         row.get("K",          ""),
                        "D":         row.get("D",          ""),
                        "J":         row.get("J",          ""),
                        "BB_pct":    row.get("BB_pct",     ""),
                        "MA5":       row.get("MA5",        ""),
                        "MA20":      row.get("MA20",       ""),
                        "VolRatio":  row.get("VolRatio",   ""),
                        "ATR_pct":   row.get("ATR_pct",    ""),
                        "OBV_Slope": row.get("OBV_Slope",  ""),
                        "WR":        row.get("WR",         ""),
                        "CCI":       row.get("CCI",        ""),
                    },
                }
                self.ctxs.append(ctx)
            return f"✅ Loaded {len(self.ctxs)} stocks. Click 'Refresh Quotes' for latest prices."
        except Exception as e:
            return f"❌ Load failed: {e}"

    # ------------------------------------------------------------------
    def refresh_quotes(self, cb=None):
        """Refresh real-time quotes via yfinance batch download."""
        if not self.ctxs:
            return
        tickers = [ctx.code for ctx in self.ctxs]
        tmap    = {ctx.code: ctx for ctx in self.ctxs}

        try:
            batch_sz = 200
            for i in range(0, len(tickers), batch_sz):
                batch  = tickers[i:i + batch_sz]
                joined = " ".join(batch)

                if cb:
                    cb(i, len(tickers), f"Fetching quotes {i+1}~{min(i+batch_sz, len(tickers))}...")

                data = yf.download(
                    joined, period="5d", progress=False,
                    group_by="ticker", threads=True
                )

                if len(batch) == 1:
                    tk = batch[0]
                    if tk in tmap and data is not None and len(data) >= 1:
                        ctx = tmap[tk]
                        clean = data.dropna()
                        if len(clean) >= 2:
                            pc = float(clean["Close"].iloc[-2])
                            cc = float(clean["Close"].iloc[-1])
                        elif len(clean) == 1:
                            pc = cc = float(clean["Close"].iloc[-1])
                        else:
                            continue
                        ctx.curr_price = cc
                        ctx.curr_pct   = (cc - pc) / pc * 100 if pc > 0 else 0
                else:
                    for tk in batch:
                        if tk not in tmap:
                            continue
                        try:
                            sub = data[tk].dropna(how="all")
                            if sub is None or len(sub) == 0:
                                continue
                            clean = sub.dropna()
                            if len(clean) >= 2:
                                pc = float(clean["Close"].iloc[-2])
                                cc = float(clean["Close"].iloc[-1])
                            elif len(clean) == 1:
                                pc = cc = float(clean["Close"].iloc[-1])
                            else:
                                continue
                            ctx = tmap[tk]
                            ctx.curr_price = cc
                            ctx.curr_pct   = (cc - pc) / pc * 100 if pc > 0 else 0
                        except Exception:
                            pass
        except Exception:
            pass


# =============================================================================
# Worker Thread
# =============================================================================
class Worker(QThread):
    prog = pyqtSignal(int, int, str)
    done = pyqtSignal(str)

    def __init__(self, func, *args):
        super().__init__()
        self.f = func
        self.a = args

    def run(self):
        self.done.emit(self.f(*self.a, self.prog.emit))


# =============================================================================
# Main Window
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{SYSTEM_NAME} — Technical Indicator Scoring System (US Market)")
        self.resize(1800, 900)
        self.dm = DataManager()

        w = QWidget(); self.setCentralWidget(w)
        lay = QVBoxLayout(w)

        # Menu
        menu = self.menuBar().addMenu("System")
        menu.addAction("About", self.show_about)

        # Status
        self.lbl_mode = QLabel(
            "Ready  |  Click '① Update & Score' to download bars, "
            "calculate indicators, and auto-save results"
        )
        self.lbl_mode.setStyleSheet("color:#1565C0; font-weight:bold; font-size:13px;")
        lay.addWidget(self.lbl_mode)

        # Row 1
        h1 = QHBoxLayout()
        b1 = QPushButton("① Update && Score")
        b1.setToolTip("Download historical bars → compute 10 indicators → auto-save CSV")
        b1.clicked.connect(self.do_update)
        b2 = QPushButton("② Refresh Quotes")
        b2.setToolTip("Fetch current price & change % from Yahoo Finance")
        b2.clicked.connect(self.do_quote)
        b3 = QPushButton("③ Save CSV")
        b3.setToolTip("Manually save current results as a timestamped CSV")
        b3.clicked.connect(self.do_save_csv)
        h1.addWidget(b1); h1.addWidget(b2); h1.addWidget(b3); h1.addStretch()
        lay.addLayout(h1)

        # Row 2
        h2 = QHBoxLayout()
        b4 = QPushButton("④ Load History")
        b4.setToolTip("Load a previously saved CSV file")
        b4.clicked.connect(self.do_load_csv)
        b5 = QPushButton("⑤ Open Results Dir")
        b5.setToolTip(f"Open: {PREDS_DIR}")
        b5.clicked.connect(self.do_open_dir)
        b6 = QPushButton("⑥ Indicator Guide")
        b6.clicked.connect(self.show_indicator_help)
        h2.addWidget(b4); h2.addWidget(b5); h2.addWidget(b6); h2.addStretch()
        lay.addLayout(h2)

        # Status + Progress
        self.stat = QLabel("Ready")
        lay.addWidget(self.stat)
        self.pb = QProgressBar()
        lay.addWidget(self.pb)

        # Table
        self.tab = QTableWidget()
        self.tab.verticalHeader().setVisible(False)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tab.doubleClicked.connect(self.on_double_click)
        lay.addWidget(self.tab)

        self._try_auto_load_latest()

    # ------------------------------------------------------------------
    def _try_auto_load_latest(self):
        files = sorted(glob.glob(os.path.join(PREDS_DIR, "TechScore_US_*.csv")))
        if files:
            latest = files[-1]
            msg = self.dm.load_from_csv(latest)
            self.lbl_mode.setText(
                f"Auto-loaded: {os.path.basename(latest)}  |  "
                f"Refresh quotes or re-run scoring"
            )
            self.stat.setText(msg)
            self.refresh_table()

    def on_double_click(self, index):
        row = index.row()
        it  = self.tab.item(row, 1)
        if it:
            webbrowser.open(f"https://finance.yahoo.com/quote/{it.text()}")

    # ------------------------------------------------------------------
    def do_update(self):
        d = ScopeSelectionDialog(self)
        if d.exec_():
            scopes, days = d.get_data()
            self.lbl_mode.setText("Downloading & computing, please wait…")
            self.start_work(self.dm.run_update_and_score, scopes, days)

    def do_quote(self):
        if not self.dm.ctxs:
            QMessageBox.information(self, "Info", "Run '① Update & Score' or '④ Load History' first.")
            return
        self.stat.setText("Refreshing quotes…")
        QApplication.processEvents()
        self.dm.refresh_quotes()
        self.refresh_table()
        self.stat.setText("✅ Quotes refreshed")

    def do_save_csv(self):
        msg = self.dm.save_csv_manual()
        self.stat.setText(msg)
        QMessageBox.information(self, "Save", msg)

    def do_load_csv(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load CSV", PREDS_DIR, "*.csv")
        if p:
            msg = self.dm.load_from_csv(p)
            self.stat.setText(msg)
            self.lbl_mode.setText(
                f"Loaded: {os.path.basename(p)}  |  Click '② Refresh Quotes'"
            )
            self.refresh_table()

    def do_open_dir(self):
        if platform.system() == "Windows":   os.startfile(PREDS_DIR)
        elif platform.system() == "Darwin":  subprocess.Popen(["open", PREDS_DIR])
        else:                                subprocess.Popen(["xdg-open", PREDS_DIR])

    def show_about(self):
        QMessageBox.about(self, f"About {SYSTEM_NAME}",
            "<b>TechScore Stock Analyzer v2.0 — US Market</b><br>"
            "10-indicator composite scoring system for US stocks<br><br>"
            "Data: Yahoo Finance (yfinance)<br>"
            "License: GNU General Public License v3<br><br>"
            "<i>For research and educational purposes only.<br>"
            "Not investment advice. Use at your own risk.</i>"
        )

    def show_indicator_help(self):
        txt = (
            "<b>10 Technical Indicator Scoring Guide</b><br>"
            "<small>Sub-score: 0~10 each | Composite: 0~100</small><br><br>"

            "<b>1. RSI(14)</b> — Relative Strength Index<br>"
            "≤20→10 | ≤30→9 | ≤40→7.5 | ≤50→6 | ≤60→5 | ≤70→3.5 | ≤80→2 | &gt;80→1<br><br>"

            "<b>2. MACD(12,26,9)</b><br>"
            "MACD&gt;Sig &amp; &gt;0→9 | &gt;Sig &amp; ≤0→7 | ≤Sig &amp; &gt;0→4 | else→1.5<br>"
            "Histogram expanding +0.5 / contracting -0.5<br><br>"

            "<b>3. KDJ(9,3,3)</b> — Stochastic<br>"
            "K&lt;20&amp;D&lt;20→9.5 | K crosses up D→8.5 | K&gt;80&amp;D&gt;80→1.5<br>"
            "K crosses down D→2 | K&gt;D→6.5 | K≤D→4 | J&lt;0:+1 | J&gt;100:-1<br><br>"

            "<b>4. Bollinger %B(20,2σ)</b><br>"
            "&lt;0→9.5 | &lt;.15→8.5 | &lt;.35→7 | &lt;.65→5.5 | &lt;.85→3.5 | &lt;1→2 | ≥1→1<br><br>"

            "<b>5. MA Cross(5/20)</b><br>"
            "Golden cross→10 | Death cross→1 | MA5&gt;MA20(≤5%)→7.5 | (&gt;5%)→6 | MA5&lt;MA20→3<br><br>"

            "<b>6. Volume Ratio(20d)</b><br>"
            "2.5~4→9 | &gt;4→8.5 | 1.8~2.5→8 | 1.2~1.8→6.5 | 0.8~1.2→5 | 0.5~0.8→3 | &lt;0.5→1.5<br><br>"

            "<b>7. ATR%(14)</b><br>"
            "1~2%→8 | 0.5~1%/2~3%→6.5 | 0.3~0.5%/3~5%→4.5 | &lt;0.3%→3.5 | &gt;5%→2<br><br>"

            "<b>8. OBV Trend(5d slope)</b><br>"
            "&gt;.05→9 | &gt;.02→7.5 | &gt;0→6 | &gt;-.02→4.5 | &gt;-.05→3 | ≤-.05→1.5<br><br>"

            "<b>9. Williams %R(14)</b><br>"
            "≤-90→9.5 | ≤-80→8 | ≤-50→5.5 | ≤-20→3.5 | &gt;-20→1.5<br><br>"

            "<b>10. CCI(14)</b><br>"
            "&lt;-200→9.5 | &lt;-100→8 | &lt;0→6 | &lt;100→4.5 | &lt;200→2.5 | ≥200→1<br><br>"

            "<b>Weights:</b> MACD 15% | RSI/KDJ/MA 12% | BB/VOL/OBV 10% | ATR 7% | WR/CCI 6%<br><br>"
            "<b>Higher score = more oversold/bullish signals (contrarian model)</b>"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Indicator Scoring Guide")
        dlg.resize(640, 700)
        la = QVBoxLayout(dlg)
        lbl = QLabel(txt); lbl.setWordWrap(True); lbl.setTextFormat(Qt.RichText)
        sc = QScrollArea(); sc.setWidget(lbl); sc.setWidgetResizable(True)
        la.addWidget(sc)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject); la.addWidget(bb)
        dlg.exec_()

    # ------------------------------------------------------------------
    def start_work(self, func, *args):
        self.tab.setSortingEnabled(False)
        self.worker = Worker(func, *args)
        self.worker.prog.connect(
            lambda c, t, s: (
                self.pb.setMaximum(max(t, 1)),
                self.pb.setValue(c),
                self.stat.setText(s),
            )
        )
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_done(self, msg):
        self.stat.setText(msg)
        self.pb.setValue(self.pb.maximum())
        self.lbl_mode.setText("Scoring complete, auto-saved  |  Click '② Refresh Quotes' for live prices")
        self.refresh_table()

    # ------------------------------------------------------------------
    def refresh_table(self):
        self.tab.setSortingEnabled(False)
        self.tab.clear()
        self._build_view()
        self.tab.resizeColumnsToContents()
        self.tab.setSortingEnabled(True)

    def _build_view(self):
        if not self.dm.ctxs:
            self.tab.setColumnCount(1)
            self.tab.setHorizontalHeaderLabels(["Info"])
            self.tab.setRowCount(1)
            self._si(0, 0, "No data. Click '① Update & Score' (recommend 200+ calendar days)")
            return

        hdr = [
            "#", "Ticker", "Name", "Data Thru",
            "Price", "Chg%", "Score(0~100)",
            "RSI_S", "MACD_S", "KDJ_S", "BB_S", "MA_S",
            "Vol_S", "ATR_S", "OBV_S", "WR_S", "CCI_S",
            "RSI", "MACD_H", "K", "D", "J",
            "BB%", "MA5", "MA20", "VolR", "ATR%",
            "OBV_Sl", "WR", "CCI",
        ]
        self.tab.setColumnCount(len(hdr))
        self.tab.setHorizontalHeaderLabels(hdr)
        self.tab.setRowCount(len(self.dm.ctxs))

        for i, ctx in enumerate(self.dm.ctxs):
            self._si(i, 0, str(i + 1), i + 1)
            self._si(i, 1, ctx.code)
            self._si(i, 2, ctx.name)
            self._si(i, 3, ctx.last_date or "-")

            # Price / Change
            p = pct = 0.0
            try:
                pr = ctx.curr_price
                if str(pr) not in ("-", "", "0", "0.0"): p = float(pr)
            except Exception: pass
            try:
                pr = ctx.curr_pct
                if str(pr) not in ("-", ""): pct = float(pr)
            except Exception: pass

            self._si(i, 4, f"{p:.2f}" if p else "-", p)
            fg_p = QColor("red") if pct > 0 else QColor("green") if pct < 0 else None
            self._si(i, 5, f"{pct:+.2f}%" if p else "-", pct, fg=fg_p)

            # Composite
            res  = ctx.score_result
            comp = res.get("composite", 0)
            sc   = res.get("scores", {})
            vl   = res.get("values", {})

            if   comp >= 75: bg_c, fg_c = QColor("#FFCDD2"), QColor("#B71C1C")
            elif comp >= 60: bg_c, fg_c = QColor("#FFE0B2"), QColor("#E65100")
            elif comp >= 45: bg_c = fg_c = None
            else:            bg_c, fg_c = QColor("#E8F5E9"), QColor("#2E7D32")
            self._si(i, 6, f"{comp:.1f}", comp, bg=bg_c, fg=fg_c)

            # Sub-scores (col 7~16)
            for j, k in enumerate(["RSI","MACD","KDJ","BB","MA","VOL","ATR","OBV","WR","CCI"]):
                sv = float(sc.get(k, 0))
                bg_s = QColor("#FFCDD2") if sv >= 8.5 else None
                fg_s = QColor("#B71C1C") if sv >= 8.5 else None
                self._si(i, 7 + j, f"{sv:.1f}", sv, bg=bg_s, fg=fg_s)

            # Raw values (col 17~29)
            vmap = [
                ("RSI",".2f"),("MACD_Hist",".4f"),("K",".2f"),("D",".2f"),("J",".2f"),
                ("BB_pct",".3f"),("MA5",".2f"),("MA20",".2f"),("VolRatio",".2f"),
                ("ATR_pct",".3f"),("OBV_Slope",".5f"),("WR",".2f"),("CCI",".2f"),
            ]
            for j, (vk, fmt) in enumerate(vmap):
                v = vl.get(vk, "")
                try:
                    fv = float(v)
                    self._si(i, 17 + j, f"{fv:{fmt}}", fv)
                except Exception:
                    self._si(i, 17 + j, "-", 0)

    def _si(self, r, c, txt, sort_val=None, bg=None, fg=None):
        it = NumericItem(str(txt))
        if sort_val is not None: it.setData(Qt.UserRole, sort_val)
        if bg: it.setBackground(bg)
        if fg: it.setForeground(fg)
        it.setTextAlignment(Qt.AlignCenter)
        self.tab.setItem(r, c, it)


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = MainWindow()
    w.show()
    sys.exit(app.exec_())

