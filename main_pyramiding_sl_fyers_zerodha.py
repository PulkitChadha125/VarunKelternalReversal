import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import time
import traceback
from pathlib import Path
import os

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
      We add the correct Fyers exchange prefix from TradeSettings (PREFIX column).
    
    Note: This is called from within execute_trading_strategy, so we need to find
    the prefix from the current symbol's settings. We'll search result_dict to find
    the matching symbol and get its prefix.
    """
    try:
        # If symbol already has exchange prefix, use it
        if ":" in symbol:
            fyers_symbol = symbol
        else:
            # Try to find prefix from TradeSettings by matching the symbol
            prefix_found = None
            for unique_key, params in strat.result_dict.items():
                # Check if this symbol matches (could be future_symbol or base symbol)
                future_sym = params.get("FutureSymbol", "")
                base_sym = params.get("Symbol", "")
                
                if symbol == future_sym or symbol.startswith(base_sym):
                    prefix_found = params.get("Prefix", None)
                    if prefix_found:
                        break
            
            if prefix_found:
                # Use prefix from TradeSettings.csv
                prefix_upper = str(prefix_found).strip().upper()
                fyers_symbol = f"{prefix_upper}:{symbol}"
            else:
                # Fallback: auto-detect prefix (backward compatibility)
                # Extract base symbol from future symbol
                base_symbol = symbol
                if symbol.endswith("FUT"):
                    for known_symbol in ["CRUDEOIL", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", 
                                        "GOLD", "SILVER", "NATURALGAS", "COPPER"]:
                        if symbol.startswith(known_symbol):
                            base_symbol = known_symbol
                            break
                    else:
                        import re
                        match = re.match(r"^([A-Z]+)", symbol)
                        if match:
                            base_symbol = match.group(1)
                
                exchange_prefix = get_fyers_exchange_prefix(base_symbol)
                fyers_symbol = f"{exchange_prefix}{symbol}"

        ltp = fyers_get_ltp(fyers_symbol)
        if ltp is None:
            print(f"[Fyers LTP] No LTP returned for {fyers_symbol}")
            return None
        return float(ltp)
    except Exception as e:
        print(f"[Fyers LTP] Error getting LTP for {symbol}: {e}")
        return None


# ============================================================
# Helper: Determine Fyers exchange prefix based on symbol
# ============================================================

def get_fyers_exchange_prefix(symbol: str) -> str:
    """
    Determine the correct Fyers exchange prefix for a symbol.
    
    Rules:
    - CRUDEOIL and other commodities → "MCX:"
    - NIFTY, BANKNIFTY and other indices → "NSE:" (futures) or "NFO:" (options)
    - Default: "MCX:" if unknown
    
    Args:
        symbol: Base symbol (e.g., "CRUDEOIL", "NIFTY", "BANKNIFTY")
    
    Returns:
        Exchange prefix string (e.g., "MCX:", "NSE:")
    """
    symbol_upper = symbol.upper()
    
    # NSE/NFO symbols (indices)
    if symbol_upper in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
        # For futures, use NSE:; for options, would be NFO: but we're dealing with futures here
        return "NSE:"
    
    # MCX symbols (commodities)
    if symbol_upper in ["CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NICKEL"]:
        return "MCX:"
    
    # Default to MCX for unknown symbols (safer for commodities)
    print(f"[Fyers Exchange] Unknown symbol '{symbol}', defaulting to MCX:")
    return "MCX:"


# Monkey‑patch the strategy module's get_ltp to use Fyers instead of Zerodha.
strat.get_ltp = get_ltp_fyers_adapter


# ============================================================
# Per-symbol trading hours validation
# ============================================================

def parse_time_string(time_str):
    """
    Parse time string in formats: "HH:MM" or "HH:MM:SS"
    
    Args:
        time_str: Time string (e.g., "9:00", "9:15:15", "15:30", "23:30:00")
    
    Returns:
        datetime.time object, or None if invalid
    """
    if not time_str or pd.isna(time_str) or str(time_str).strip() == '':
        return None
    
    try:
        time_str = str(time_str).strip()
        parts = time_str.split(':')
        
        if len(parts) == 2:
            # Format: "HH:MM"
            hour = int(parts[0])
            minute = int(parts[1])
            return dt_time(hour, minute)
        elif len(parts) == 3:
            # Format: "HH:MM:SS"
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2])
            return dt_time(hour, minute, second)
        else:
            print(f"[Time Parse] Invalid time format: {time_str}")
            return None
    except (ValueError, IndexError) as e:
        print(f"[Time Parse] Error parsing time '{time_str}': {e}")
        return None


def is_symbol_trading_hours(starttime_str, stoptime_str) -> bool:
    """
    Check if current time is within symbol-specific trading hours.
    
    Args:
        starttime_str: Start time string from TradeSettings (e.g., "9:00", "9:15:15")
        stoptime_str: Stop time string from TradeSettings (e.g., "15:30", "23:30")
    
    Returns:
        True if within trading hours, False otherwise
        If times are not provided, returns True (no restriction)
    """
    now = datetime.now()
    current_time = now.time()
    
    # Parse start and stop times
    start_time = parse_time_string(starttime_str)
    stop_time = parse_time_string(stoptime_str)
    
    # If no times provided, allow trading (backward compatibility)
    if start_time is None and stop_time is None:
        return True
    
    # If only one time provided, use default for the other
    if start_time is None:
        start_time = dt_time(9, 0)  # Default: 9:00 AM
    if stop_time is None:
        stop_time = dt_time(23, 30)  # Default: 11:30 PM
    
    # Check if current time is within range
    # Handle case where stop time is before start time (e.g., overnight trading)
    if stop_time >= start_time:
        # Normal case: start_time <= current_time <= stop_time
        return start_time <= current_time <= stop_time
    else:
        # Overnight case: start_time <= current_time OR current_time <= stop_time
        # Example: 23:30 to 9:00 (overnight)
        return current_time >= start_time or current_time <= stop_time


# ============================================================
# Trading hours configuration (global - for backward compatibility)
# ============================================================

# ===== CONFIGURATION: Adjust these times as needed =====
# Market open time (24-hour format: hour, minute)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 0  # 9:00 AM

# Market close time (24-hour format: hour, minute)
# Options:
#   - For NSE/NFO only: 15, 30  (3:30 PM)
#   - For MCX commodities: 23, 30  (11:30 PM)
#   - For both (current): 23, 30  (11:30 PM)
MARKET_CLOSE_HOUR = 23
MARKET_CLOSE_MINUTE = 30  # 11:30 PM (change to 15, 30 for 3:30 PM NSE hours)
# ============================================================

def is_trading_hours() -> bool:
    """
    Check if current time is within trading hours.
    
    Trading hours are configured via MARKET_OPEN_* and MARKET_CLOSE_* constants above.
    
    Default:
    - Market Open: 9:00 AM IST
    - Market Close: 11:30 PM IST (for MCX commodities)
    
    To change to NSE hours only (3:30 PM), set:
    - MARKET_CLOSE_HOUR = 15
    - MARKET_CLOSE_MINUTE = 30
    
    Returns:
        True if within trading hours, False otherwise
    """
    now = datetime.now()
    current_time = now.time()
    
    market_open = dt_time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = dt_time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    
    return market_open <= current_time <= market_close


def should_skip_trading() -> bool:
    """
    Determine if trading should be skipped (outside market hours or weekends).
    
    Returns:
        True if should skip trading, False if should proceed
    """
    now = datetime.now()
    weekday = now.weekday()  # 0 = Monday, 6 = Sunday
    
    # Skip weekends (Saturday = 5, Sunday = 6)
    if weekday >= 5:
        return True
    
    # Check trading hours
    if not is_trading_hours():
        return True
    
    return False


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
            
            # Get symbol-specific trading hours
            starttime = params.get("StartTime", None)
            stoptime = params.get("StopTime", None)

            if not future_symbol or not timeframe:
                print(f"[Strategy Fyers/Zerodha] Missing FutureSymbol or Timeframe for {unique_key}")
                continue

            # Check if current time is within symbol's trading hours
            if not is_symbol_trading_hours(starttime, stoptime):
                current_time_str = datetime.now().strftime("%H:%M:%S")
                start_str = starttime if starttime else "N/A"
                stop_str = stoptime if stoptime else "N/A"
                print(f"[Strategy Fyers/Zerodha] Skipping {symbol} - Outside trading hours. Current: {current_time_str}, Trading Hours: {start_str} - {stop_str}")
                continue

            print(f"\n[Strategy Fyers/Zerodha] Processing {symbol} -> {future_symbol} with timeframe {timeframe}")
            if starttime or stoptime:
                print(f"[Strategy Fyers/Zerodha] Symbol trading hours: {starttime or 'N/A'} - {stoptime or 'N/A'}")

            # ---------------------------------------------
            # 3.1 Fetch historical futures data from Fyers
            # ---------------------------------------------
            # Map timeframe string like "5minute" to minutes (5) and then to Fyers resolution ("5")
            timeframe_minutes = strat.get_timeframe_minutes(timeframe)
            fyers_resolution = str(timeframe_minutes)

            # ---------------------------------------------
            # 3.1 Fetch historical futures data from Fyers (with retry logic)
            # ---------------------------------------------
            historical_df = None
            max_fyers_retries = 3
            fyers_retry_delay = 2
            
            for retry_attempt in range(max_fyers_retries):
                try:
                    # Get Fyers exchange prefix from TradeSettings (PREFIX column)
                    # If prefix is provided in CSV, use it; otherwise fall back to auto-detection
                    prefix_from_csv = params.get("Prefix", None)
                    
                    if ":" in future_symbol:
                        # Already has prefix, use as-is
                        fyers_symbol = future_symbol
                    elif prefix_from_csv:
                        # Use prefix from TradeSettings.csv (e.g., "MCX" -> "MCX:")
                        prefix_upper = str(prefix_from_csv).strip().upper()
                        fyers_symbol = f"{prefix_upper}:{future_symbol}"
                        print(f"[Strategy Fyers/Zerodha] Using prefix from TradeSettings: {prefix_upper}")
                    else:
                        # Fallback: auto-detect prefix based on symbol (backward compatibility)
                        base_symbol = symbol
                        exchange_prefix = get_fyers_exchange_prefix(base_symbol)
                        fyers_symbol = f"{exchange_prefix}{future_symbol}"
                        print(f"[Strategy Fyers/Zerodha] Auto-detected prefix: {exchange_prefix}")

                    print(f"[Strategy Fyers/Zerodha] Fetching data for {fyers_symbol} (attempt {retry_attempt + 1}/{max_fyers_retries})")
                    historical_df = fyers_fetch_ohlc(fyers_symbol, fyers_resolution)
                    
                    # Validate data quality
                    if historical_df is not None and not historical_df.empty:
                        # Check minimum required candles (at least 100 for indicator calculations)
                        min_required_candles = 100
                        if len(historical_df) < min_required_candles:
                            print(f"[Strategy Fyers/Zerodha] WARNING: Only {len(historical_df)} candles retrieved, minimum {min_required_candles} required for reliable indicators")
                            # Continue anyway but log warning
                        else:
                            print(f"[Strategy Fyers/Zerodha] Retrieved {len(historical_df)} candles from Fyers for {future_symbol}")
                            break  # Success, exit retry loop
                    else:
                        if retry_attempt < max_fyers_retries - 1:
                            print(f"[Strategy Fyers/Zerodha] Empty data returned, retrying in {fyers_retry_delay} seconds...")
                            time.sleep(fyers_retry_delay)
                        else:
                            print(f"[Strategy Fyers/Zerodha] No historical data retrieved from Fyers for {future_symbol} after {max_fyers_retries} attempts")
                            continue  # Skip to next symbol
                            
                except Exception as e:
                    error_msg = str(e)
                    print(f"[Strategy Fyers/Zerodha] Error fetching Fyers data for {future_symbol} (attempt {retry_attempt + 1}/{max_fyers_retries}): {e}")
                    
                    # Check for session/auth errors
                    if "token" in error_msg.lower() or "auth" in error_msg.lower() or "session" in error_msg.lower():
                        print(f"[Strategy Fyers/Zerodha] Possible Fyers session expired, attempting re-login...")
                        try:
                            fyers_login()
                            print(f"[Strategy Fyers/Zerodha] Fyers re-login successful, retrying data fetch...")
                        except Exception as login_error:
                            print(f"[Strategy Fyers/Zerodha] Fyers re-login failed: {login_error}")
                            strat.write_to_order_logs(f"ERROR: Fyers re-login failed during data fetch: {login_error}")
                    
                    if retry_attempt < max_fyers_retries - 1:
                        print(f"[Strategy Fyers/Zerodha] Retrying in {fyers_retry_delay} seconds...")
                        time.sleep(fyers_retry_delay)
                    else:
                        print(f"[Strategy Fyers/Zerodha] Failed to fetch data after {max_fyers_retries} attempts")
                        traceback.print_exc()
                        continue  # Skip to next symbol
            
            # Final validation before processing
            if historical_df is None or historical_df.empty:
                print(f"[Strategy Fyers/Zerodha] Skipping {future_symbol} - no valid data retrieved")
                continue

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

            # Save processed data to symbol-specific file in data folder
            try:
                # Create data folder if it doesn't exist
                data_folder = Path("data")
                data_folder.mkdir(exist_ok=True)
                
                # Create filename based on symbol and expiry
                # Format: data/{SYMBOL}_{EXPIRY}.csv
                # Example: data/CRUDEOIL_26-01-2026.csv
                expiry = params.get("Expiry", "")
                if expiry:
                    # Clean expiry for filename (replace / with -)
                    expiry_clean = expiry.replace("/", "-")
                    filename = f"{symbol}_{expiry_clean}.csv"
                else:
                    # Fallback to unique_key if expiry not available
                    filename = f"{unique_key.replace('_', '-')}.csv"
                
                output_file = data_folder / filename
                
                print(f"[Strategy Fyers/Zerodha] Saving processed data to {output_file}...")
                max_retries = 3
                retry_delay = 1
                for attempt in range(max_retries):
                    try:
                        processed_df.write_csv(str(output_file))
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
            except Exception as e:
                print(f"[Strategy Fyers/Zerodha] Error saving data file: {e}")
                traceback.print_exc()
                # Non‑critical, continue even if save fails

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
        print("\n[Main Fyers/Zerodha] Logging in to brokers...")
        try:
            fyers_login()
            print("[Main Fyers/Zerodha] Fyers login successful")
        except Exception as e:
            print(f"[Main Fyers/Zerodha] CRITICAL: Fyers login failed: {e}")
            strat.write_to_order_logs(f"CRITICAL ERROR: Fyers login failed at startup: {e}")
            raise  # Cannot proceed without Fyers data
        
        try:
            strat.kite_client = strat.zerodha_login()
            print("[Main Fyers/Zerodha] Zerodha login successful")
        except Exception as e:
            print(f"[Main Fyers/Zerodha] CRITICAL: Zerodha login failed: {e}")
            strat.write_to_order_logs(f"CRITICAL ERROR: Zerodha login failed at startup: {e}")
            raise  # Cannot proceed without Zerodha for orders

        # 4.3 Load user settings (symbols, expiries, timeframes, indicator params, pyramiding settings)
        print("\n[Main Fyers/Zerodha] Fetching user settings from TradeSettings.csv...")
        strat.get_user_settings()
        print("[Main Fyers/Zerodha] User settings loaded successfully!")

        # 4.4 Initialize per-symbol signal CSV files (e.g. crudeoilsignal.csv, bankniftysignal.csv)
        print("\n[Main Fyers/Zerodha] Initializing per-symbol signal CSV files...")
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

        # Track last auto-login date to avoid multiple logins per day
        last_auto_login_date = None

        # 4.6 Main candle‑based scheduling loop
        while True:
            now = datetime.now()
            current_time = now.time()
            current_date = now.date()

            # Check if we should skip trading (outside market hours or weekends)
            if should_skip_trading():
                weekday = now.weekday()
                if weekday >= 5:
                    print(f"[Main Fyers/Zerodha] Weekend detected ({now.strftime('%A')}). Waiting until Monday...")
                    # Wait until Monday 9:00 AM
                    days_until_monday = (7 - weekday) % 7
                    if days_until_monday == 0:
                        days_until_monday = 7  # If it's Sunday, wait until next Monday
                    next_monday = now + timedelta(days=days_until_monday)
                    next_monday = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
                    wait_seconds = (next_monday - now).total_seconds()
                    print(f"[Main Fyers/Zerodha] Waiting {wait_seconds/3600:.1f} hours until {next_monday.strftime('%Y-%m-%d %H:%M:%S')}")
                    time.sleep(min(wait_seconds, 3600))  # Sleep in 1-hour chunks
                    continue
                else:
                    # Outside trading hours on weekday
                    market_close_time = dt_time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
                    market_open_time = dt_time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
                    print(f"[Main Fyers/Zerodha] Outside trading hours ({current_time.strftime('%H:%M:%S')}). Market hours: {MARKET_OPEN_HOUR:02d}:{MARKET_OPEN_MINUTE:02d} - {MARKET_CLOSE_HOUR:02d}:{MARKET_CLOSE_MINUTE:02d} IST")
                    # Wait until market opens (next day if after market close, or today if before market open)
                    if current_time > market_close_time:
                        # After market close, wait until market open next day
                        next_day = now + timedelta(days=1)
                        next_open = next_day.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
                    else:
                        # Before market open, wait until market open today
                        next_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
                        if next_open <= now:
                            # Already past market open today, wait until next day
                            next_open = (now + timedelta(days=1)).replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
                    
                    wait_seconds = (next_open - now).total_seconds()
                    print(f"[Main Fyers/Zerodha] Waiting {wait_seconds/3600:.1f} hours until market opens at {next_open.strftime('%Y-%m-%d %H:%M:%S')}")
                    time.sleep(min(wait_seconds, 3600))  # Sleep in 1-hour chunks
                    continue

            # Auto-login both Fyers and Zerodha at 9:00 AM (keep sessions fresh daily)
            # Also check if we just started and it's after 9 AM - do initial login check
            should_auto_login = False
            if current_time.hour == 9 and current_time.minute == 0 and current_time.second < 5:
                # Standard 9:00 AM auto-login
                should_auto_login = True
            elif current_time.hour >= 9 and last_auto_login_date != current_date:
                # First run after 9 AM today - do initial login
                should_auto_login = True
            
            if should_auto_login:
                print("\n[Main Fyers/Zerodha] 9:00 AM detected - Performing auto‑login for both brokers...")
                
                # Auto-login to Fyers (data provider)
                try:
                    print("[Main Fyers/Zerodha] Performing Fyers auto‑login...")
                    fyers_login()
                    strat.write_to_order_logs("Fyers auto‑login performed at 9:00 AM")
                except Exception as e:
                    print(f"[Main Fyers/Zerodha] Error during Fyers auto‑login: {e}")
                    strat.write_to_order_logs(f"ERROR: Fyers auto‑login failed at 9:00 AM: {e}")
                
                # Auto-login to Zerodha (order execution)
                try:
                    print("[Main Fyers/Zerodha] Performing Zerodha auto‑login...")
                    strat.kite_client = strat.zerodha_login()
                    strat.write_to_order_logs("Zerodha auto‑login performed at 9:00 AM")
                except Exception as e:
                    print(f"[Main Fyers/Zerodha] Error during Zerodha auto‑login: {e}")
                    strat.write_to_order_logs(f"ERROR: Zerodha auto‑login failed at 9:00 AM: {e}")
                
                time.sleep(5)  # Wait to avoid multiple logins
                # Mark that we've done auto-login today
                last_auto_login_date = current_date

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
            try:
                main_strategy_fyers_zerodha()
            except Exception as strategy_error:
                print(f"[Main Fyers/Zerodha] Error in strategy execution: {strategy_error}")
                strat.write_to_order_logs(f"ERROR: Strategy execution failed: {strategy_error}")
                traceback.print_exc()
            finally:
                # Always save trading state, even if strategy execution failed
                try:
                    strat.save_trading_state()
                except Exception as save_error:
                    print(f"[Main Fyers/Zerodha] CRITICAL: Failed to save trading state: {save_error}")
                    strat.write_to_order_logs(f"CRITICAL ERROR: Failed to save trading state: {save_error}")

    except KeyboardInterrupt:
        print("\n[Main Fyers/Zerodha] Program interrupted by user. Saving state and exiting...")
        strat.save_trading_state()
        print("[Main Fyers/Zerodha] State saved. Exiting...")
    except Exception as e:
        print(f"\n[Main Fyers/Zerodha] Fatal error: {str(e)}")
        strat.save_trading_state()
        traceback.print_exc()

