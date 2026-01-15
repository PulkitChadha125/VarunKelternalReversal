import pandas as pd
from datetime import datetime, timedelta
import time
import traceback
from pathlib import Path

from kiteconnect import KiteConnect

# Core strategy (pyramiding, SL, Keltner, Supertrend, CSV logging, state, etc.)
import MainPyramidingSl as strat

# Fyers data/source integration
from FyresIntegration import automated_login as fyers_automated_login
from FyresIntegration import fetchOHLC as fyers_fetch_ohlc
from FyresIntegration import get_ltp as fyers_get_ltp


# ============================================================
# 1. Fyers credentials and login
# ============================================================

def get_api_credentials_fyers() -> dict:
    """
    Load Fyers API credentials from FyersCredentials.csv.

    Expected CSV columns:
        Title, Value

    Common keys (based on your other project):
        client_id, secret_key, FY_ID, totpkey, PIN, redirect_uri,
        grant_type, response_type, state, etc.
    """
    credentials = {}
    try:
        df = pd.read_csv("FyersCredentials.csv")
        for _, row in df.iterrows():
            title = str(row["Title"]).strip()
            value = str(row["Value"]).strip()
            credentials[title] = value
    except FileNotFoundError:
        print("[Fyers] FyersCredentials.csv not found.")
    except pd.errors.EmptyDataError:
        print("[Fyers] FyersCredentials.csv is empty.")
    except Exception as e:
        print(f"[Fyers] Error reading FyersCredentials.csv: {e}")
    return credentials


def fyers_login():
    """
    Perform Fyers login using credentials from FyersCredentials.csv.

    This will:
      - Call automated_login(...) from FyresIntegration.py
      - Initialize global fyers + access_token in that module
    """
    creds = get_api_credentials_fyers()
    if not creds:
        raise RuntimeError("Fyers credentials not loaded. Check FyersCredentials.csv.")

    redirect_uri = creds.get("redirect_uri")
    client_id = creds.get("client_id")
    secret_key = creds.get("secret_key")
    grant_type = creds.get("grant_type")
    response_type = creds.get("response_type")
    state = creds.get("state")
    totp_key = creds.get("totpkey")
    fy_id = creds.get("FY_ID")
    pin = creds.get("PIN")

    if not all([redirect_uri, client_id, secret_key, totp_key, fy_id, pin]):
        raise RuntimeError("Missing required Fyers credentials in FyersCredentials.csv")

    print("[Fyers] Starting automated login...")
    # NOTE: grant_type / response_type / state are configured inside automated_login / Fyers API flow
    fyers_automated_login(
        client_id=client_id,
        redirect_uri=redirect_uri,
        secret_key=secret_key,
        FY_ID=fy_id,
        PIN=pin,
        TOTP_KEY=totp_key,
    )
    print("[Fyers] Login successful.")


# ============================================================
# 2. Override LTP source in strategy to use Fyers
# ============================================================

def get_ltp_fyers_adapter(_kite: KiteConnect, _exchange: str, symbol: str) -> float:
    """
    Adapter that replaces the strategy's Zerodha-based get_ltp with Fyers get_ltp.

    - Ignores Kite client and exchange.
    - Uses FyersIntegration.get_ltp(symbol) instead.
    - Expects symbol in base futures format, e.g. CRUDEOIL26JANFUT.
      We add the correct Fyers exchange prefix here (e.g. MCX:).
    """
    try:
        # If symbol does not have an exchange prefix, assume MCX for CRUDEOIL
        fyers_symbol = symbol
        if ":" not in fyers_symbol:
            # For now we treat all unprefixed futures as MCX; can be extended per-symbol later
            fyers_symbol = f"MCX:{fyers_symbol}"

        ltp = fyers_get_ltp(fyers_symbol)
        if ltp is None:
            print(f"[Fyers LTP] No LTP returned for {fyers_symbol}")
            return None
        return float(ltp)
    except Exception as e:
        print(f"[Fyers LTP] Error getting LTP for {symbol}: {e}")
        return None


# Monkey‑patch the strategy module's get_ltp to use Fyers instead of Zerodha.
strat.get_ltp = get_ltp_fyers_adapter


# ============================================================
# 3. Main strategy loop using Fyers for data, Zerodha for orders
# ============================================================

def main_strategy_fyers_zerodha():
    """
    Main strategy loop for one 'cycle':

    - For each symbol in TradeSettings (strat.result_dict):
        - Use Fyers to fetch historical futures OHLCV.
        - Use existing strategy code to:
            - Build Heikin-Ashi, Keltner, Supertrend, VolumeMA.
            - Run pyramiding, SL, and entry/exit logic.
        - Orders are still placed via Zerodha (inside strat.execute_trading_strategy).
    """
    try:
        if not strat.result_dict:
            print("[Strategy Fyers/Zerodha] No trading symbols configured. Waiting...")
            return

        for unique_key, params in strat.result_dict.items():
            symbol = params.get("Symbol")
            future_symbol = params.get("FutureSymbol")  # e.g. CRUDEOIL25NOVFUT, BANKNIFTY26JANFUT
            timeframe = params.get("Timeframe")

            if not future_symbol or not timeframe:
                print(f"[Strategy Fyers/Zerodha] Missing FutureSymbol or Timeframe for {unique_key}")
                continue

            print(f"\n[Strategy Fyers/Zerodha] Processing {symbol} -> {future_symbol} with timeframe {timeframe}")

            # ---------------------------------------------
            # 3.1 Fetch historical futures data from Fyers
            # ---------------------------------------------
            # Map timeframe string like "5minute" to minutes (5) and then to Fyers resolution ("5")
            timeframe_minutes = strat.get_timeframe_minutes(timeframe)
            fyers_resolution = str(timeframe_minutes)

            try:
                # Fyers fetchOHLC expects symbol and resolution string
                # For CRUDEOIL futures, use MCX prefix as per your format: MCX:CRUDEOIL26JANFUT
                fyers_symbol = future_symbol
                if ":" not in fyers_symbol:
                    fyers_symbol = f"MCX:{fyers_symbol}"

                print(f"symbol: {fyers_symbol}")
                historical_df = fyers_fetch_ohlc(fyers_symbol, fyers_resolution)
            except Exception as e:
                print(f"[Strategy Fyers/Zerodha] Error fetching Fyers data for {future_symbol}: {e}")
                traceback.print_exc()
                continue

            if historical_df is None or historical_df.empty:
                print(f"[Strategy Fyers/Zerodha] No historical data retrieved from Fyers for {future_symbol}")
                continue

            print(f"[Strategy Fyers/Zerodha] Retrieved {len(historical_df)} candles from Fyers for {future_symbol}")

            # ---------------------------------------------
            # 3.2 Indicator parameters from TradeSettings
            # ---------------------------------------------
            try:
                volume_ma = int(params.get("VolumeMa", 20))
                supertrend_period = int(params.get("SupertrendPeriod", 10))
                supertrend_mul = float(params.get("SupertrendMul", 3.0))
                kc1_length = int(params.get("KC1_Length", 20))
                kc1_mul = float(params.get("KC1_Mul", 2.0))
                kc1_atr = int(params.get("KC1_ATR", 10))
                kc2_length = int(params.get("KC2_Length", 20))
                kc2_mul = float(params.get("KC2_Mul", 2.0))
                kc2_atr = int(params.get("KC2_ATR", 10))
            except Exception as e:
                print(f"[Strategy Fyers/Zerodha] Error reading indicator params for {unique_key}: {e}")
                continue

            # ---------------------------------------------
            # 3.3 Process historical data (HA, KC, ST, VolumeMA)
            # ---------------------------------------------
            try:
                processed_df = strat.process_historical_data(
                    historical_df=historical_df,
                    volume_ma_period=volume_ma,
                    supertrend_period=supertrend_period,
                    supertrend_multiplier=supertrend_mul,
                    kc1_length=kc1_length,
                    kc1_multiplier=kc1_mul,
                    kc1_atr=kc1_atr,
                    kc2_length=kc2_length,
                    kc2_multiplier=kc2_mul,
                    kc2_atr=kc2_atr,
                )
            except Exception as e:
                print(f"[Strategy Fyers/Zerodha] Error processing historical data for {future_symbol}: {e}")
                traceback.print_exc()
                continue

            # Optionally save to CSV for inspection (same as original strategy)
            try:
                output_file = "data.csv"
                print(f"[Strategy Fyers/Zerodha] Saving processed data to {output_file}...")
                max_retries = 3
                retry_delay = 1
                for attempt in range(max_retries):
                    try:
                        processed_df.write_csv(output_file)
                        print(f"[Strategy Fyers/Zerodha] Data saved successfully to {output_file}")
                        break
                    except OSError as e:
                        if "being used by another process" in str(e) and attempt < max_retries - 1:
                            print(
                                f"[Strategy Fyers/Zerodha] File locked, retrying in {retry_delay} seconds... "
                                f"(Attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(retry_delay)
                        else:
                            print(f"[Strategy Fyers/Zerodha] Warning: Could not save to {output_file}: {e}")
                            print(
                                "[Strategy Fyers/Zerodha] Please close the file if it's open in Excel or another program."
                            )
                            break
            except Exception:
                # Non‑critical, ignore CSV save errors
                pass

            # ---------------------------------------------
            # 3.4 Initialize / ensure trading state structure
            # ---------------------------------------------
            if unique_key not in strat.trading_states:
                strat.trading_states[unique_key] = {
                    "position": None,  # None, 'BUY', or 'SELL'
                    "armed_buy": False,
                    "armed_sell": False,
                    "exit_on_candle": False,
                    "last_exit_candle_date": None,
                    "option_symbol": None,
                    "option_exchange": None,
                    "option_order_id": None,
                    # Pyramiding fields
                    "pyramiding_count": 0,
                    "first_entry_price": None,
                    "last_pyramiding_price": None,
                    "pyramiding_positions": [],
                    # Stop Loss fields
                    "initial_sl": None,
                    "current_sl": None,
                    "entry_prices": [],
                    "entry_option_price": None,
                }
            else:
                # Ensure newer fields exist for older state files
                state = strat.trading_states[unique_key]
                state.setdefault("option_symbol", None)
                state.setdefault("option_exchange", None)
                state.setdefault("option_order_id", None)
                state.setdefault("pyramiding_count", 0)
                state.setdefault("first_entry_price", None)
                state.setdefault("last_pyramiding_price", None)
                state.setdefault("pyramiding_positions", [])
                state.setdefault("initial_sl", None)
                state.setdefault("current_sl", None)
                state.setdefault("entry_prices", [])
                state.setdefault("entry_option_price", None)

            # ---------------------------------------------
            # 3.5 Execute trading logic (pyramiding + SL) and summary
            # ---------------------------------------------
            try:
                strat.execute_trading_strategy(
                    df=processed_df,
                    unique_key=unique_key,
                    symbol=symbol,
                    future_symbol=future_symbol,
                    trading_state=strat.trading_states[unique_key],
                )

                strat.display_trading_summary(
                    df=processed_df,
                    symbol=symbol,
                    future_symbol=future_symbol,
                    trading_state=strat.trading_states[unique_key],
                )
            except Exception as e:
                print(f"[Strategy Fyers/Zerodha] Error running strategy for {future_symbol}: {e}")
                traceback.print_exc()

    except Exception as e:
        print("[Strategy Fyers/Zerodha] Fatal error in main strategy:", str(e))
        traceback.print_exc()


# ============================================================
# 4. Entry point: Fyers data + Zerodha orders
# ============================================================

if __name__ == "__main__":
    try:
        print("=" * 60)
        print("Starting Fyers‑data / Zerodha‑orders Pyramiding Bot")
        print("=" * 60)

        # 4.1 Load previous trading state (from MainPyramidingSl's state.json)
        strat.load_trading_state()

        # 4.2 Login to Fyers (data) and Zerodha (execution)
        fyers_login()
        strat.kite_client = strat.zerodha_login()

        # 4.3 Load user settings (symbols, expiries, timeframes, indicator params, pyramiding settings)
        print("\n[Main Fyers/Zerodha] Fetching user settings from TradeSettings.csv...")
        strat.get_user_settings()
        print("[Main Fyers/Zerodha] User settings loaded successfully!")

        # 4.4 Initialize / verify signal.csv (same as original strategy)
        print("\n[Main Fyers/Zerodha] Initializing signal.csv file...")
        strat.initialize_signal_csv()

        # 4.5 Determine timeframe for scheduling (use first symbol's timeframe)
        if strat.result_dict:
            first_params = next(iter(strat.result_dict.values()))
            timeframe_str = first_params.get("Timeframe", "5minute")
            timeframe_minutes = strat.get_timeframe_minutes(timeframe_str)
            print(f"[Main Fyers/Zerodha] Timeframe: {timeframe_str} ({timeframe_minutes} minutes)")
        else:
            timeframe_minutes = 5
            print("[Main Fyers/Zerodha] No symbols configured, using default 5‑minute timeframe")

        print("\n[Main Fyers/Zerodha] Initialization complete. Starting main strategy loop...")
        print("=" * 60)

        # 4.6 Main candle‑based scheduling loop
        while True:
            now = datetime.now()
            current_time = now.time()

            # Optional: keep Zerodha session fresh at 9:00 AM (as in original)
            if current_time.hour == 9 and current_time.minute == 0 and current_time.second < 5:
                print("\n[Main Fyers/Zerodha] 9:00 AM detected - Performing Zerodha auto‑login...")
                strat.kite_client = strat.zerodha_login()
                strat.write_to_order_logs("Zerodha auto‑login performed at 9:00 AM")
                time.sleep(5)

            # Compute next candle time based on timeframe_minutes
            next_candle_time = strat.get_next_candle_time(now, timeframe_minutes)
            wait_seconds = (next_candle_time - now).total_seconds()

            if wait_seconds > 0:
                print(
                    f"\n[Main Fyers/Zerodha] Next execution scheduled at: "
                    f"{next_candle_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(
                    f"[Main Fyers/Zerodha] Waiting {wait_seconds:.1f} seconds until next candle..."
                )

                sleep_increment = 1.0
                while wait_seconds > 0:
                    if wait_seconds > sleep_increment:
                        time.sleep(sleep_increment)
                        wait_seconds -= sleep_increment
                    else:
                        time.sleep(wait_seconds)
                        break

            # Execute one full strategy cycle using Fyers data + Zerodha orders
            print(
                f"\n[Main Fyers/Zerodha] Executing strategy at "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            main_strategy_fyers_zerodha()

            # Save trading state after each cycle
            strat.save_trading_state()

    except KeyboardInterrupt:
        print("\n[Main Fyers/Zerodha] Program interrupted by user. Saving state and exiting...")
        strat.save_trading_state()
        print("[Main Fyers/Zerodha] State saved. Exiting...")
    except Exception as e:
        print(f"\n[Main Fyers/Zerodha] Fatal error: {str(e)}")
        strat.save_trading_state()
        traceback.print_exc()

