#!/usr/bin/env python3
"""
Fetch daily closing prices for BKNG / EXPE / ABNB.

Modes:
  --full       Force full refetch from 2018-01-01 (overwrite cache)
  (default)    Incremental: only fetch dates after the last cached date

Usage:
    pip install yfinance
    python fetch_stock_prices.py            # incremental
    python fetch_stock_prices.py --full     # full refetch
"""

import json, os, sys, time, datetime, argparse, math, tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT     = os.path.join(SCRIPT_DIR, "stock_prices_副本.json")

TICKERS    = ["BKNG", "EXPE", "ABNB", "^GSPC"]
FULL_START = "2018-01-01"
MAX_RETRIES = 3
RETRY_DELAY = 10

# 2026-08-20: Custom session with proper UA to bypass Yahoo Finance rate limiting
# Also supports proxy fallback (checks system proxy via scutil)
import requests as _requests
_YF_SESSION = _requests.Session()
_YF_SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
})

def _check_proxy() -> dict | None:
    """Check if system proxy is available (Clash/V2ray/Surge)."""
    try:
        result = _requests.get("http://127.0.0.1:7892", timeout=3)
        if result.status_code < 500:
            return {"http": "http://127.0.0.1:7892", "https": "http://127.0.0.1:7892"}
    except:
        pass
    # Check common proxy ports
    for port in [7890, 7891, 7892, 7893, 1080]:
        try:
            result = _requests.get(f"http://127.0.0.1:{port}", timeout=2)
            if result.status_code < 500:
                return {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
        except:
            pass
    return None

# Auto-detect proxy at startup
_PROXY = _check_proxy()
if _PROXY:
    # yfinance >=1.4 dropped the `proxies=` kwarg; apply proxies on the session instead
    _YF_SESSION.proxies.update(_PROXY)
    print(f"[stock] Using system proxy: {_PROXY['http']}")
else:
    print("[stock] No system proxy detected, using direct connection")


def load_cache() -> dict | None:
    """Load existing cache, return None if not found or corrupt."""
    try:
        with open(OUTPUT) as f:
            data = json.load(f)
        # Validate structure
        for t in TICKERS:
            if t in data and "dates" in data[t] and "close" in data[t]:
                continue
            return None
        return data
    except:
        return None


def last_cached_date(cache: dict, ticker: str) -> str | None:
    """Return the last cached date for a ticker, or None."""
    if cache and ticker in cache and cache[ticker]["dates"]:
        return cache[ticker]["dates"][-1]
    return None


def _period_for(start_after: str | None) -> str:
    """Choose a Yahoo range that is guaranteed to include the missing window."""
    if not start_after:
        return "max"
    gap = (datetime.date.today() - datetime.date.fromisoformat(start_after)).days
    if gap <= 7:
        return "5d"
    if gap <= 31:
        return "1mo"
    if gap <= 92:
        return "3mo"
    if gap <= 366:
        return "1y"
    return "max"


def _clean_series(dates, closes, cutoff: str | None) -> dict:
    """Filter, de-duplicate and validate Yahoo observations."""
    floor = cutoff or FULL_START
    by_date = {}
    for d, c in zip(dates, closes):
        try:
            value = round(float(c), 2)
        except (TypeError, ValueError):
            continue
        outside_window = d <= cutoff if cutoff else d < floor
        if outside_window:
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        by_date[d] = value
    ordered = sorted(by_date.items())
    return {"dates": [d for d, _ in ordered], "close": [c for _, c in ordered]}


def _validate_complete_cache(data: dict) -> list[str]:
    """Return validation errors; an empty list means the cache is safe to publish."""
    errors = []
    expected_starts = {"BKNG": "2018-01-05", "EXPE": "2018-01-05", "^GSPC": "2018-01-05", "ABNB": "2020-12-15"}
    for ticker in TICKERS:
        series = data.get(ticker) or {}
        dates, closes = series.get("dates", []), series.get("close", [])
        if not dates or len(dates) != len(closes):
            errors.append(f"{ticker}: missing data or dates/close length mismatch")
            continue
        if dates != sorted(set(dates)):
            errors.append(f"{ticker}: dates are not sorted and unique")
        if dates[0] > expected_starts[ticker]:
            errors.append(f"{ticker}: history starts too late ({dates[0]})")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in closes):
            errors.append(f"{ticker}: invalid close value")
    last_dates = {data[t]["dates"][-1] for t in TICKERS if data.get(t, {}).get("dates")}
    if len(last_dates) != 1:
        errors.append(f"ticker latest dates are not aligned ({sorted(last_dates)})")
    return errors


def _atomic_save(data: dict) -> None:
    """Never leave a truncated JSON cache behind."""
    fd, tmp_path = tempfile.mkstemp(prefix="stock_prices_", suffix=".json", dir=SCRIPT_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, OUTPUT)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def fetch_incremental(ticker: str, start_after: str | None) -> dict | None:
    """Fetch data with exponential backoff + fallback strategies.
    
    2026-08-20: Updated with:
      - Exponential backoff (10s, 30s, 60s) for rate limiting
      - Primary: period-based fetch with a range large enough for the cache gap
      - Auto-detect system proxy for fallback
      - Final fallback: direct Yahoo chart API
    """
    global _PROXY  # must be declared before any use of _PROXY in this function
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed. Run: pip install yfinance")
        return None

    delays = [10, 30, 60]  # Exponential backoff for retries
    last_error = None
    
    # Determine period
    period = _period_for(start_after)
    cutoff = start_after

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            fetch_label = f"{cutoff} → today" if cutoff else "full history"
            print(f"  {ticker}: attempt {attempt}/{MAX_RETRIES} (period={period}, {fetch_label}) ...", end=" ", flush=True)
            
            # Proxy (if any) is already configured on _YF_SESSION above
            tk = yf.Ticker(ticker, session=_YF_SESSION)
            
            # Primary: period-based fetch (more reliable than start=)
            hist = tk.history(period=period)

            if not hist.empty:
                cleaned = _clean_series(
                    [d.strftime("%Y-%m-%d") for d in hist.index],
                    hist["Close"].tolist(), cutoff)
                dates, closes = cleaned["dates"], cleaned["close"]

                if cutoff:
                    if dates:
                        print(f"OK  {len(dates)} new days  ({dates[0]} → {dates[-1]})")
                        return {"dates": dates, "close": closes}
                    else:
                        print("no valid new close; trying fallback")
                        break
                
                # Full mode - return all observations from FULL_START
                print(f"OK  {len(dates)} days  ({dates[0]} → {dates[-1]})")
                return {"dates": dates, "close": closes}

            # An empty yfinance result is also how DNS/rate-limit failures are
            # sometimes reported. Continue to the direct API before declaring
            # that the market had no new session.
            print("empty result; trying fallback")
            break

        except Exception as e:
            last_error = e
            err_str = str(e)
            print(f"failed — {err_str[:80]}")

            # If rate limited, use longer backoff
            if "429" in err_str or "RateLimit" in err_str or "Too Many Requests" in err_str:
                wait = delays[attempt - 1] if attempt <= len(delays) else 120
                print(f"    rate-limited, waiting {wait}s ...")
                time.sleep(wait)
                
                # On retry, try with proxy if available
                if not _PROXY and attempt == 2:
                    _PROXY = _check_proxy()
                    if _PROXY:
                        print(f"    detected system proxy on retry: {_PROXY['http']}")
            elif attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    # ── Fallback 1: Try with explicit proxy ──
    if _PROXY:
        print(f"  {ticker}: trying with proxy ...", end=" ", flush=True)
        try:
            tk = yf.Ticker(ticker, session=_YF_SESSION)
            hist2 = tk.history(period=period)
            if not hist2.empty:
                cleaned = _clean_series(
                    [d.strftime("%Y-%m-%d") for d in hist2.index],
                    hist2["Close"].tolist(), cutoff)
                dates, closes = cleaned["dates"], cleaned["close"]
                if cutoff:
                    filtered = [(d, c) for d, c in zip(dates, closes) if d > cutoff]
                    if filtered:
                        dates = [f[0] for f in filtered]
                        closes = [f[1] for f in filtered]
                        print(f"OK proxy  {len(dates)} new days")
                        return {"dates": dates, "close": closes}
                print(f"OK proxy  {len(dates)} days")
                return {"dates": dates, "close": closes}
        except Exception as e2:
            print(f"proxy failed — {e2}")

    # ── Fallback 2: Direct Yahoo Finance chart API (bypass yfinance rate limiting) ──
    print(f"  {ticker}: trying direct Yahoo API fallback ...", end=" ", flush=True)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
        resp = _YF_SESSION.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        
        result = raw.get('chart', {}).get('result', [{}])[0]
        timestamps = result.get('timestamp', [])
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        closes_raw = list(quote.get('close', []))

        # Yahoo occasionally publishes the completed session timestamp/OHLC
        # before populating the final item in quote.close. Once the exchange's
        # local clock is past 16:00, regularMarketPrice is the official close
        # for that same session and is safe to use for the trailing null only.
        meta = result.get('meta', {})
        market_ts = meta.get('regularMarketTime')
        market_price = meta.get('regularMarketPrice')
        if timestamps and closes_raw and closes_raw[-1] is None and market_ts and market_price is not None:
            from zoneinfo import ZoneInfo
            market_utc = datetime.datetime.fromtimestamp(market_ts, tz=datetime.timezone.utc)
            market_local = market_utc.astimezone(ZoneInfo(meta.get('exchangeTimezoneName', 'America/New_York')))
            row_date = datetime.datetime.fromtimestamp(timestamps[-1], tz=datetime.timezone.utc).date()
            if market_local.hour >= 16 and market_local.date() == row_date:
                closes_raw[-1] = market_price
                print(f"filled finalized trailing close {market_price} for {row_date}; ", end="")
        
        if timestamps and closes_raw:
            from datetime import datetime as _dt, timezone as _tz
            cleaned = _clean_series(
                [_dt.fromtimestamp(t, tz=_tz.utc).strftime('%Y-%m-%d') for t in timestamps],
                closes_raw, cutoff)
            dates, closes = cleaned["dates"], cleaned["close"]
            
            if cutoff:
                filtered = [(d, c) for d, c in zip(dates, closes) if d > cutoff]
                if filtered:
                    dates = [f[0] for f in filtered]
                    closes = [f[1] for f in filtered]
                    print(f"OK  directAPI  {len(dates)} new days ({dates[0]} → {dates[-1]})")
                    return {"dates": dates, "close": closes}
                print("directAPI: no new data after cutoff")
                return {"dates": [], "close": []}
            if dates:
                print(f"OK  directAPI  {len(dates)} days ({dates[0]} → {dates[-1]})")
                return {"dates": dates, "close": closes}
        print("directAPI: no data returned")
    except Exception as e_api:
        print(f"directAPI failed — {str(e_api)[:60]}")

    print(f"  {ticker}: FAILED all strategies. Last error: {last_error}")
    return None


def main():
    parser = argparse.ArgumentParser(description="Fetch BKNG/EXPE/ABNB daily close prices")
    parser.add_argument("--full", action="store_true", help="Force full refetch from 2018")
    args = parser.parse_args()

    cache = None if args.full else load_cache()
    mode = "FULL" if args.full else "INCREMENTAL"
    print(f"Mode: {mode}")
    if cache and not args.full:
        for t in TICKERS:
            ld = last_cached_date(cache, t)
            print(f"  Cache {t}: {len(cache[t]['dates'])} days, last = {ld}")
    print()

    result = cache if (cache and not args.full) else {}

    any_new = False
    failed = []
    today = datetime.date.today().isoformat()
    for t in TICKERS:
        last_date = last_cached_date(result, t) if not args.full else None

        if not args.full and last_date:
            # Check if we already have data through today
            if last_date >= today:
                print(f"  {t}: already up to date ({last_date})")
                continue
            # If next fetch date is today, check if US market has closed
            # (market closes 4 PM ET = ~5 AM Beijing next day; we run at 5:30 AM Beijing)
            next_date = (datetime.date.fromisoformat(last_date) + datetime.timedelta(days=1)).isoformat()
            if next_date > today:
                print(f"  {t}: last cached {last_date}, nothing to fetch yet")
                continue
            if next_date == today:
                # Check current UTC hour — US market closes at ~20:00-21:00 UTC
                utc_now = datetime.datetime.now(datetime.timezone.utc)
                if utc_now.hour < 21:
                    print(f"  {t}: last cached {last_date}, US market hasn't closed yet (UTC {utc_now.hour}:00) — skipping")
                    continue

        new_data = fetch_incremental(t, last_date if not args.full else None)
        if new_data is None:
            print(f"  {t}: FAILED after {MAX_RETRIES} attempts")
            failed.append(t)
            continue

        if new_data["dates"]:
            any_new = True
            if not args.full and t in result and result[t]["dates"]:
                # Append new data to existing cache
                result[t]["dates"].extend(new_data["dates"])
                result[t]["close"].extend(new_data["close"])
            else:
                result[t] = new_data
        else:
            print(f"  {t}: no new trading days since {last_date}")

        time.sleep(2)

    if failed:
        print(f"\nFAILED: refusing to publish a partial cache; failed tickers: {', '.join(failed)}")
        sys.exit(1)

    if not any_new and not args.full:
        print("\nAll tickers up to date. No changes.")
        return

    if not result:
        print("\n" + "="*60)
        print("FAILED: Could not fetch any stock data.")
        print("You may need a VPN if Yahoo Finance is blocking your IP.")
        print("="*60)
        sys.exit(1)

    errors = _validate_complete_cache(result)
    if errors:
        print("\nFAILED: refusing to publish an incomplete/invalid stock cache:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    output = dict(result)
    output["last_updated"] = datetime.datetime.now().isoformat()
    _atomic_save(output)

    print(f"\nSaved → {OUTPUT}")
    for t in TICKERS:
        if t in result:
            d = result[t]
            print(f"  {t}: {len(d['dates'])} days, ${d['close'][0]} → ${d['close'][-1]}  ({d['dates'][0]} → {d['dates'][-1]})")
    print("\nNow run:  python generate_副本.py   to rebuild the dashboard.")


if __name__ == "__main__":
    main()
