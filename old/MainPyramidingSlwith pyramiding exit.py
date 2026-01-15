import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import polars as pl
import polars_talib as plta
import pandas_ta as ta
import time
import traceback
import json
from pathlib import Path
import numpy as np
from scipy.stats import norm
from math import log, sqrt, exp
import csv
from py_vollib.black_scholes.implied_volatility import implied_volatility
from py_vollib.black_scholes.greeks.analytical import delta as py_vollib_delta
from zerodha_integration import (
    login,
    get_historical_data,
    get_instrument_token,
    get_instruments_by_symbol
)
from kiteconnect import KiteConnect

def delete_file_contents(file_name):
    try:
        # Open the file in write mode, which truncates it (deletes contents)
        with open(file_name, 'w') as file:
            file.truncate(0)
        print(f"Contents of {file_name} have been deleted.")
    except FileNotFoundError:
        print(f"File {file_name} not found.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")


def write_to_order_logs(message):
    """Write message to OrderLog.txt with timestamp"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        with open('OrderLog.txt', 'a', encoding='utf-8') as file:  # Open the file in append mode
            file.write(log_message + '\n')
        print(f"[OrderLog] {log_message}")
    except Exception as e:
        print(f"[OrderLog] Error writing to log: {str(e)}")


def initialize_signal_csv():
    """
    Initialize or verify signal.csv file with all required columns.
    Creates the file with headers if it doesn't exist.
    If file exists, checks and adds any missing columns.
    """
    csv_file = 'signal.csv'
    required_columns = [
        'timestamp', 'action', 'optionprice', 'optioncontract', 'futurecontract', 
        'futureprice', 'lotsize', 'Stop loss', 'Margin', 'Points Captured', 
        'Charges', 'P&L (Abs.)', 'P&L (%)'
    ]
    
    try:
        file_exists = Path(csv_file).exists()
        
        if not file_exists:
            # File doesn't exist - create it with all headers
            print(f"[CSV Init] Creating {csv_file} with headers...")
            with open(csv_file, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(required_columns)
            print(f"[CSV Init] ✓ {csv_file} created successfully with {len(required_columns)} columns")
            return
        
        # File exists - check if all columns are present
        with open(csv_file, 'r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            try:
                existing_headers = next(reader)
            except StopIteration:
                # File is empty - write headers
                print(f"[CSV Init] File {csv_file} is empty, writing headers...")
                with open(csv_file, 'w', newline='', encoding='utf-8') as write_file:
                    writer = csv.writer(write_file)
                    writer.writerow(required_columns)
                print(f"[CSV Init] ✓ Headers written to {csv_file}")
                return
        
        # Normalize headers (convert to lowercase, strip spaces)
        existing_headers_normalized = [h.strip().lower() for h in existing_headers if h.strip()]
        required_columns_normalized = [h.strip().lower() for h in required_columns]
        
        # Check for missing columns
        missing_columns = []
        for req_col in required_columns:
            req_col_normalized = req_col.strip().lower()
            if req_col_normalized not in existing_headers_normalized:
                missing_columns.append(req_col)
        
        if missing_columns:
            # Add missing columns to header
            print(f"[CSV Init] Found {len(missing_columns)} missing columns in {csv_file}")
            print(f"[CSV Init] Missing columns: {missing_columns}")
            
            # Read all existing data
            with open(csv_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.reader(file)
                rows = list(reader)
            
            if len(rows) > 0:
                # Update header row with missing columns
                updated_header = existing_headers + missing_columns
                rows[0] = updated_header
                
                # Add empty values for missing columns in data rows
                num_missing = len(missing_columns)
                for i in range(1, len(rows)):
                    rows[i].extend([''] * num_missing)
                
                # Write back to file
                with open(csv_file, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerows(rows)
                
                print(f"[CSV Init] ✓ Added {len(missing_columns)} missing columns to {csv_file}")
            else:
                # Only header row exists - just update it
                with open(csv_file, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(required_columns)
                print(f"[CSV Init] ✓ Updated headers in {csv_file}")
        else:
            print(f"[CSV Init] ✓ {csv_file} already has all required columns")
            
    except Exception as e:
        print(f"[CSV Init] Error initializing {csv_file}: {str(e)}")
        traceback.print_exc()


def write_to_signal_csv(action, option_price=None, option_contract=None, future_contract=None, future_price=None, lotsize=0, 
                        stop_loss=None, entry_future_price=None, entry_option_price=None, charges=63, position_num=None):
    """
    Write trading signal to signal.csv file in the new format matching sampleformat.csv.
    
    Args:
        action: 'Armed Buy', 'Armed Sell', 'buy', 'sell', 'pyramiding trade buy (N)', 'pyramiding trade sell (N)', 
                'buyexit', 'sellexit', 'pyramiding trade buy (N) exit', 'pyramiding trade sell (N) exit'
        option_price: Price of the option (LTP or order price) - None for armed actions, exit price for exits
        option_contract: Option symbol (e.g., 'CRUDEOIL25NOV5300CE') - None for armed actions
        future_contract: Future symbol (e.g., 'CRUDEOIL25NOVFUT')
        future_price: Future price (HA_Close or LTP) - current price
        lotsize: Quantity/lotsize for the trade
        stop_loss: Current stop loss value (None for entries, value for exits)
        entry_future_price: Entry future price (for calculating Points Captured on exits)
        entry_option_price: Entry option price (for calculating P&L on exits)
        charges: Brokerage/charges (default: 63)
        position_num: Position number for pyramiding (1, 2, 3...) - None for initial entries/exits
    """
    try:
        csv_file = 'signal.csv'
        # Format: DD-MM-YYYY HH:MM
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M")
        
        # Ensure file exists and has all columns (safety check)
        file_exists = Path(csv_file).exists()
        if not file_exists:
            # File was deleted - reinitialize it
            initialize_signal_csv()
        
        # Calculate Margin: OptionPrice × Lotsize × 100 (only for entries, not exits)
        margin = ""
        if option_price is not None and 'exit' not in action.lower():
            margin = int(option_price * lotsize * 100)
        
        # Calculate Points Captured (only for exits)
        points_captured = ""
        if entry_future_price is not None and future_price is not None and 'exit' in action.lower():
            if 'buy' in action.lower():
                # BUY: Exit - Entry
                points_captured = f"{future_price - entry_future_price:.1f}"
            elif 'sell' in action.lower():
                # SELL: Entry - Exit
                points_captured = f"{entry_future_price - future_price:.1f}"
        
        # Calculate P&L (Abs.) and P&L (%) - based on option prices (only for exits)
        pnl_abs = ""
        pnl_percent = ""
        if entry_option_price is not None and option_price is not None and 'exit' in action.lower():
            # Calculate P&L per unit
            if 'buy' in action.lower():
                # BUY: Exit - Entry (profit when exit > entry)
                pnl_per_unit = option_price - entry_option_price
            elif 'sell' in action.lower():
                # SELL: Entry - Exit (profit when entry > exit)
                pnl_per_unit = entry_option_price - option_price
            else:
                pnl_per_unit = 0
            
            # Calculate absolute P&L: (P&L per unit) × Lotsize × 100 - Charges
            pnl_abs_value = (pnl_per_unit * lotsize * 100) - charges
            pnl_abs = f"{int(pnl_abs_value)}"
            
            # Calculate P&L %: (P&L (Abs.) / Margin) × 100
            entry_margin = entry_option_price * lotsize * 100
            if entry_margin > 0:
                pnl_percent_value = (pnl_abs_value / entry_margin) * 100
                pnl_percent = f"{pnl_percent_value:.0f}%"
            else:
                pnl_percent = ""
        
        # Format option_price (1 decimal place)
        option_price_str = f"{option_price:.1f}" if option_price is not None else ""
        
        # Format future_price (2 decimal places)
        future_price_str = f"{future_price:.2f}" if future_price is not None else ""
        
        # Format stop_loss (empty for entries, value for exits)
        stop_loss_str = ""
        if stop_loss is not None and 'exit' in action.lower():
            stop_loss_str = f"{stop_loss:.2f}"
        
        # Format margin (integer, empty for exits)
        margin_str = f"{margin}" if margin != "" else ""
        
        # Format charges (integer, only for exits)
        charges_str = f"{int(charges)}" if charges and 'exit' in action.lower() else ""
        
        # Read existing headers to ensure we write data in correct order
        existing_headers = []
        if file_exists:
            try:
                with open(csv_file, 'r', newline='', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    existing_headers = next(reader)
            except (StopIteration, FileNotFoundError):
                # File is empty or was deleted - reinitialize
                initialize_signal_csv()
                existing_headers = ['timestamp', 'action', 'optionprice', 'optioncontract', 'futurecontract', 
                                   'futureprice', 'lotsize', 'Stop loss', 'Margin', 'Points Captured', 
                                   'Charges', 'P&L (Abs.)', 'P&L (%)']
        
        # Define column order (standard order)
        column_order = ['timestamp', 'action', 'optionprice', 'optioncontract', 'futurecontract', 
                       'futureprice', 'lotsize', 'Stop loss', 'Margin', 'Points Captured', 
                       'Charges', 'P&L (Abs.)', 'P&L (%)']
        
        # Create data dictionary for easy mapping
        data_dict = {
            'timestamp': timestamp,
            'action': action,
            'optionprice': option_price_str,
            'optioncontract': option_contract if option_contract else "",
            'futurecontract': future_contract if future_contract else "",
            'futureprice': future_price_str,
            'lotsize': lotsize if lotsize else "",
            'Stop loss': stop_loss_str,
            'Margin': margin_str,
            'Points Captured': points_captured,
            'Charges': charges_str,
            'P&L (Abs.)': pnl_abs,
            'P&L (%)': pnl_percent
        }
        
        # Build row in the order of existing headers (or standard order if file is new)
        if existing_headers:
            # Use existing header order (handles case-insensitive matching)
            row_data = []
            for header in existing_headers:
                header_normalized = header.strip().lower()
                # Find matching column (case-insensitive)
                matched = False
                for col_name, col_value in data_dict.items():
                    if col_name.strip().lower() == header_normalized:
                        row_data.append(col_value)
                        matched = True
                        break
                if not matched:
                    # Column exists in file but not in our data - add empty value
                    row_data.append("")
        else:
            # Use standard order
            row_data = [data_dict[col] for col in column_order]
        
        # Append data row
        with open(csv_file, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(row_data)
        
        print(f"[Signal CSV] Logged: {action} | Option: {option_contract if option_contract else 'N/A'} | Future: {future_contract if future_contract else 'N/A'} | OptionPrice: {option_price_str if option_price_str else 'N/A'} | FuturePrice: {future_price_str if future_price_str else 'N/A'} | Lotsize: {lotsize}")
    except Exception as e:
        print(f"[Signal CSV] Error writing to signal.csv: {str(e)}")
        traceback.print_exc()


def save_trading_state():
    """Save trading state to state.json file"""
    try:
        state_data = {
            'last_updated': datetime.now().isoformat(),
            'trading_states': trading_states
        }
        with open('state.json', 'w', encoding='utf-8') as f:
            json.dump(state_data, f, indent=2, default=str)
    except Exception as e:
        print(f"[State] Error saving state: {str(e)}")


def load_trading_state():
    """Load trading state from state.json file"""
    global trading_states
    try:
        state_file = Path('state.json')
        if state_file.exists():
            # Check if file is empty
            file_size = state_file.stat().st_size
            if file_size == 0:
                print("[State] state.json is empty, starting with fresh state")
                return False
            
            with open('state.json', 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    print("[State] state.json is empty, starting with fresh state")
                    return False
                
                state_data = json.loads(content)
                if 'trading_states' in state_data:
                    trading_states = state_data['trading_states']
                    print(f"[State] Loaded trading state from state.json (last updated: {state_data.get('last_updated', 'N/A')})")
                    return True
                else:
                    print("[State] state.json missing 'trading_states' key, starting fresh")
                    return False
        return False
    except json.JSONDecodeError as e:
        print(f"[State] Error parsing state.json (invalid JSON): {str(e)}. Starting with fresh state.")
        # Backup corrupted file
        try:
            backup_name = f"state.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            Path('state.json').rename(backup_name)
            print(f"[State] Backed up corrupted state.json to {backup_name}")
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[State] Error loading state: {str(e)}. Starting with fresh state.")
        return False


def get_timeframe_minutes(timeframe_str: str) -> int:
    """Convert timeframe string to minutes"""
    import re
    timeframe_lower = timeframe_str.lower().strip()
    
    if 'minute' in timeframe_lower or 'min' in timeframe_lower:
        # Extract number from strings like "5minute", "5min", "15minute", "minute"
        match = re.search(r'(\d+)', timeframe_str)
        if match:
            # Found a number, return it (e.g., "5minute" -> 5, "15minute" -> 15)
            return int(match.group(1))
        else:
            # No number found, it's just "minute" -> 1 minute
            return 1
    elif 'hour' in timeframe_lower or 'hr' in timeframe_lower:
        # Extract number from strings like "1hour", "2hr"
        match = re.search(r'(\d+)', timeframe_str)
        if match:
            return int(match.group(1)) * 60
        else:
            # No number found, default to 1 hour
            return 60
    elif 'day' in timeframe_lower:
        return 1440  # 24 hours
    return 5  # Default to 5 minutes if unrecognized


def get_next_candle_time(current_time: datetime, timeframe_minutes: int) -> datetime:
    """
    Calculate the next candle boundary time.
    Example: If current time is 14:26 and timeframe is 5 minutes,
    normalize to 14:30 (next 5-minute boundary).
    """
    # Get current minute
    current_minute = current_time.minute
    
    # Calculate how many minutes to add to reach next boundary
    minutes_to_add = timeframe_minutes - (current_minute % timeframe_minutes)
    
    # Create next candle time
    next_candle = current_time.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_add)
    
    return next_candle


def handle_too_many_requests():
    """Handle 'too many requests' error by waiting 60 seconds and re-login"""
    global kite_client
    try:
        write_to_order_logs("ERROR: Too many requests detected. Waiting 60 seconds and re-logging in...")
        print("[Main] Too many requests error. Waiting 60 seconds before re-login...")
        time.sleep(60)
        
        print("[Main] Re-logging in to Zerodha...")
        kite_client = zerodha_login()
        write_to_order_logs("Re-login successful after too many requests error")
        print("[Main] Re-login successful!")
        return True
    except Exception as e:
        error_msg = f"Failed to re-login after too many requests: {str(e)}"
        write_to_order_logs(f"ERROR: {error_msg}")
        print(f"[Main] {error_msg}")
        return False


def load_zerodha_credentials():
    """
    Load Zerodha credentials from ZerodhaCredentials.csv file.
    Returns a dictionary with credentials.
    """
    try:
        csv_path = 'ZerodhaCredentials.csv'
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        
        credentials = {}
        for index, row in df.iterrows():
            title = row['title'].strip()
            value = row['value'].strip()
            credentials[title] = value
        
        # Map to expected keys
        creds = {
            'user_id': credentials.get('ID', '').strip(),
            'password': credentials.get('pwd', '').strip(),
            'api_key': credentials.get('key', '').strip(),
            'api_secret': credentials.get('secret', '').strip(),
            'totp_secret': credentials.get('zerodha2fa', '').strip()
        }
        
        # Validate required fields
        if not all([creds['user_id'], creds['password'], creds['api_key'], creds['api_secret'], creds['totp_secret']]):
            raise ValueError("Missing required credentials in ZerodhaCredentials.csv")
        
        return creds
    except Exception as e:
        raise Exception(f"Error loading Zerodha credentials: {str(e)}")


def zerodha_login():
    """
    Perform Zerodha login using credentials from CSV file.
    Returns the KiteConnect client instance.
    """
    print("[Main] Loading Zerodha credentials...")
    creds = load_zerodha_credentials()
    
    print("[Main] Starting Zerodha login process...")
    try:
        # Check if access token exists and is valid
        access_token_file = Path("access_token.txt")
        request_token_file = Path("request_token.txt")
        
        kite = None
        access_token = None
        
        if access_token_file.exists():
            try:
                access_token = access_token_file.read_text(encoding="utf-8").strip()
                kite = KiteConnect(api_key=creds['api_key'])
                kite.set_access_token(access_token)
                # Test if token is still valid by making a simple API call
                kite.profile()
                print("[Main] Using existing access token (still valid)")
                return kite
            except Exception:
                print("[Main] Existing access token is invalid. Performing fresh login...")
                access_token_file.unlink(missing_ok=True)
        
        # Perform fresh login
        kite, access_token = login(
            api_key=creds['api_key'],
            api_secret=creds['api_secret'],
            user_id=creds['user_id'],
            password=creds['password'],
            totp_secret=creds['totp_secret'],
            headless=True
        )
        
        print("[Main] Zerodha login successful!")
        return kite
        
    except Exception as e:
        raise Exception(f"Zerodha login failed: {str(e)}")

# Global variables
kite_client = None
result_dict = {}
instrument_id_list = []
Equity_instrument_id_list = []
Future_instrument_id_list = []
FyerSymbolList = []

# Trading state management (per symbol)
trading_states = {}  # Format: {unique_key: {'position': None/'BUY'/'SELL', 'armed_buy': False, 'armed_sell': False, 'exit_on_candle': False, 'last_exit_candle_date': None}}


def get_user_settings():
    """
    Fetch user settings from TradeSettings.csv file.
    This function should be called after Zerodha login is complete.
    """
    global result_dict, instrument_id_list, Equity_instrument_id_list, Future_instrument_id_list, FyerSymbolList

    delete_file_contents("OrderLog.txt")

    try:
        csv_path = 'TradeSettings.csv'
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()

        result_dict = {}
        FyerSymbolList = []

        for index, row in df.iterrows():
            # Symbol,Expiery,Timeframe,StrikeStep,StrikeNumber,Lotsize
            symbol = row['Symbol']
            expiry = row['Expiery']  # Format: 19-11-2025
            timeframe = row['Timeframe']  # e.g., "5minute"
            StrikeStep = row['StrikeStep']
            StrikeNumber = row['StrikeNumber']
            Lotsize = row['Lotsize']
            
            # Create unique key for this symbol/expiry combination
            unique_key = f"{symbol}_{expiry}"
            
            # Construct future symbol
            future_symbol = construct_future_symbol(symbol, expiry)
            # VolumeMa	SupertrendPeriod	SupertrendMul	KC1_Length	KC1_Mul	KC1_ATR	KC2_Length	KC2_Mul	KC2_ATR
            VolumeMa = row['VolumeMa']
            SupertrendPeriod = row['SupertrendPeriod']
            SupertrendMul = row['SupertrendMul']
            KC1_Length = row['KC1_Length']
            KC1_Mul = row['KC1_Mul']
            KC1_ATR = row['KC1_ATR']
            KC2_Length = row['KC2_Length']
            KC2_Mul = row['KC2_Mul']
            KC2_ATR = row['KC2_ATR']
            PyramidingDistance = float(row['PyramidingDistance'])
            PyramidingNumber = int(row['PyramidingNumber'])
            SLATR = int(row['SLATR'])  # ATR period for initial SL calculation
            SLMULTIPLIER = float(row['SLMULTIPLIER'])  # Multiplier for ATR in initial SL calculation
            # Store settings in result_dict
            result_dict[unique_key] = {
                'Symbol': symbol,
                'Expiry': expiry,
                'FutureSymbol': future_symbol,  # Constructed future symbol
                'Timeframe': timeframe,
                'StrikeStep': StrikeStep,
                'StrikeNumber': StrikeNumber,
                'Lotsize': Lotsize,
                'VolumeMa': VolumeMa,
                'SupertrendPeriod': SupertrendPeriod,
                'SupertrendMul': SupertrendMul,
                'KC1_Length': KC1_Length,
                'KC1_Mul': KC1_Mul,
                'KC1_ATR': KC1_ATR,
                'KC2_Length': KC2_Length,
                'KC2_Mul': KC2_Mul,
                'KC2_ATR': KC2_ATR,
                'PyramidingDistance': PyramidingDistance,
                'PyramidingNumber': PyramidingNumber,
                'SLATR': SLATR,  # ATR period for initial SL calculation
                'SLMULTIPLIER': SLMULTIPLIER,  # Multiplier for ATR in initial SL calculation
                # Additional fields can be added here
                'InstrumentToken': None,  # Will be populated when instrument is found
                'Exchange': None,  # Will be populated when instrument is found
            }
            
            # Store settings (you may need to process these further based on your requirements)
            print(f"[Settings] Loaded: Symbol={symbol}, Expiry={expiry}, FutureSymbol={future_symbol}, "
                  f"Timeframe={timeframe}, StrikeStep={StrikeStep}, StrikeNumber={StrikeNumber}, Lotsize={Lotsize}")
            
    except Exception as e:
        print(f"Error happened in fetching symbol: {str(e)}")
        traceback.print_exc()





def construct_future_symbol(symbol: str, expiry: str) -> str:
    """
    Construct future symbol from base symbol and expiry date.
    
    Format: {SYMBOL}{YEAR}{MONTH}FUT
    Example: CRUDEOIL + 19-11-2025 -> CRUDEOIL25NOVFUT
    
    Args:
        symbol: Base symbol (e.g., "CRUDEOIL")
        expiry: Expiry date in format "DD-MM-YYYY" (e.g., "19-11-2025")
    
    Returns:
        Constructed future symbol string (e.g., "CRUDEOIL25NOVFUT")
    """
    try:
        # Parse expiry date (format: DD-MM-YYYY)
        expiry_parts = expiry.split('-')
        if len(expiry_parts) != 3:
            raise ValueError(f"Invalid expiry format: {expiry}. Expected DD-MM-YYYY")
        
        day = expiry_parts[0]
        month = int(expiry_parts[1])
        year = int(expiry_parts[2])
        
        # Get last 2 digits of year
        year_short = str(year)[-2:]
        
        # Month abbreviations
        month_map = {
            1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
            7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
        }
        
        if month not in month_map:
            raise ValueError(f"Invalid month: {month}")
        
        month_abbr = month_map[month]
        
        # Construct future symbol: {SYMBOL}{YEAR}{MONTH}FUT
        future_symbol = f"{symbol}{year_short}{month_abbr}FUT"
        
        print(f"[Future Symbol] Constructed: {symbol} + {expiry} -> {future_symbol}")
        return future_symbol
        
    except Exception as e:
        raise Exception(f"Error constructing future symbol: {str(e)}")


def convert_to_heikin_ashi(df: pl.DataFrame) -> pl.DataFrame:
    """
    Convert regular OHLC candlestick data to Heikin-Ashi candles.
    
    Heikin-Ashi formulas:
    - HA_Close = (Open + High + Low + Close) / 4
    - HA_Open = (Previous HA_Open + Previous HA_Close) / 2
    - HA_High = max(High, HA_Open, HA_Close)
    - HA_Low = min(Low, HA_Open, HA_Close)
    
    Args:
        df: Polars DataFrame with columns: date, open, high, low, close, volume
    
    Returns:
        Polars DataFrame with Heikin-Ashi OHLC columns
    """
    try:
        # Calculate HA_Close first
        df = df.with_columns([
            ((pl.col("open") + pl.col("high") + pl.col("low") + pl.col("close")) / 4.0).alias("ha_close")
        ])
        
        # Calculate HA_Open (rolling calculation)
        ha_open_list = []
        prev_ha_open = None
        prev_ha_close = None
        
        for i in range(len(df)):
            if i == 0:
                # First candle: HA_Open = (regular Open + regular Close) / 2
                ha_open = (df["open"][i] + df["close"][i]) / 2.0
            else:
                # Subsequent candles: HA_Open = (Previous HA_Open + Previous HA_Close) / 2
                ha_open = (prev_ha_open + prev_ha_close) / 2.0
            
            ha_open_list.append(ha_open)
            prev_ha_open = ha_open
            prev_ha_close = df["ha_close"][i]
        
        # Add HA_Open column
        df = df.with_columns([
            pl.Series("ha_open", ha_open_list)
        ])
        
        # Calculate HA_High and HA_Low
        df = df.with_columns([
            pl.max_horizontal([pl.col("high"), pl.col("ha_open"), pl.col("ha_close")]).alias("ha_high"),
            pl.min_horizontal([pl.col("low"), pl.col("ha_open"), pl.col("ha_close")]).alias("ha_low")
        ])
        
        # Rename ha_close to ha_close (already done)
        # Keep original columns and add HA columns
        return df
        
    except Exception as e:
        raise Exception(f"Error converting to Heikin-Ashi: {str(e)}")


def calculate_keltner_channel(df: pl.DataFrame, length: int, multiplier: float, atr_period: int, prefix: str = "KC") -> pl.DataFrame:
    """
    Calculate Keltner Channel on Heikin-Ashi data using pandas_ta.
    
    Keltner Channel:
    - Middle Line = EMA(HA_Close, length) - Exponential Moving Average of Heikin-Ashi Close
    - Upper Band = Middle Line + (ATR(ATR_period) * multiplier)
    - Lower Band = Middle Line - (ATR(ATR_period) * multiplier)
    
    Args:
        df: Polars DataFrame with Heikin-Ashi columns
        length: EMA period for middle line (e.g., 29, 50)
        multiplier: Multiplier for ATR (e.g., 2.75, 3.75)
        atr_period: Period for ATR calculation (e.g., 14, 12)
        prefix: Prefix for column names (e.g., "KC1", "KC2")
    
    Returns:
        Polars DataFrame with Keltner Channel columns added
    """
    try:
        # Convert Polars DataFrame to Pandas for pandas_ta
        df_pd = df.to_pandas()
        
        # Ensure we have the required Heikin-Ashi columns
        if not all(col in df_pd.columns for col in ['ha_high', 'ha_low', 'ha_close']):
            raise ValueError("DataFrame must contain ha_high, ha_low, and ha_close columns")
        
        # Calculate Keltner Channel using pandas_ta
        # pandas_ta.kc returns a DataFrame with columns:
        # - KCLe_{length}_{scalar}: Lower band
        # - KCBe_{length}_{scalar}: Base/Middle band (EMA)
        # - KCUe_{length}_{scalar}: Upper band
        try:
            # Try with atr_length parameter if supported
            kc_result = ta.kc(
                high=df_pd['ha_high'],
                low=df_pd['ha_low'],
                close=df_pd['ha_close'],
                length=length,
                scalar=multiplier,
                mamode="ema",
                atr_length=atr_period  # Use separate ATR period if supported
            )
        except TypeError:
            # Fallback: pandas_ta.kc() might not support atr_length parameter
            # In this case, it will use the same 'length' for both EMA and ATR
            kc_result = ta.kc(
                high=df_pd['ha_high'],
                low=df_pd['ha_low'],
                close=df_pd['ha_close'],
                length=length,
                scalar=multiplier,
                mamode="ema"
            )
        
        if kc_result is None or len(kc_result.columns) == 0:
            raise ValueError("pandas_ta.kc() returned None or empty result")
        
        # Build column name patterns based on length and multiplier
        # pandas_ta formats multiplier as float (e.g., "2.75"), but we'll try both formats
        col_suffix_int = f"{length}_{int(multiplier)}"
        col_suffix_float = f"{length}_{multiplier}"
        
        # Try to find columns with expected names
        kc_cols = [col for col in kc_result.columns if col.startswith('KC')]
        
        if len(kc_cols) < 3:
            raise ValueError(f"Expected at least 3 Keltner Channel columns, found {len(kc_cols)}: {kc_cols}")
        
        # Find columns by pattern (KCLe, KCBe, KCUe)
        # pandas_ta.kc() returns: KCLe_{length}_{scalar} (Lower), KCBe_{length}_{scalar} (Base/Middle), KCUe_{length}_{scalar} (Upper)
        kc_lower_col = None
        kc_middle_col = None
        kc_upper_col = None
        
        for col in kc_cols:
            if col.startswith('KCLe_'):
                kc_lower_col = col
            elif col.startswith('KCBe_'):
                kc_middle_col = col
            elif col.startswith('KCUe_'):
                kc_upper_col = col
        
        # Fallback: use sorted order if pattern matching didn't work
        # Note: When sorted, KCBe comes first, KCLe second, KCUe third
        if not all([kc_lower_col, kc_middle_col, kc_upper_col]):
            kc_cols_sorted = sorted(kc_cols)
            if len(kc_cols_sorted) >= 3:
                # Sorted order: KCBe_* (Base/Middle), KCLe_* (Lower), KCUe_* (Upper)
                kc_middle_col = kc_cols_sorted[0]  # KCBe_* (Base/Middle)
                kc_lower_col = kc_cols_sorted[1]  # KCLe_* (Lower)
                kc_upper_col = kc_cols_sorted[2]   # KCUe_* (Upper)
            else:
                raise ValueError(f"Could not identify Keltner Channel columns. Found: {kc_cols}")
        
        # Add Keltner Channel columns to the pandas DataFrame with expected names
        df_pd[f"{prefix}_lower"] = kc_result[kc_lower_col]
        df_pd[f"{prefix}_middle"] = kc_result[kc_middle_col]
        df_pd[f"{prefix}_upper"] = kc_result[kc_upper_col]
        
        # Convert back to Polars DataFrame
        df_result = pl.from_pandas(df_pd)
        
        # Ensure all required columns exist (fill with None if missing)
        required_cols = [f"{prefix}_upper", f"{prefix}_lower", f"{prefix}_middle"]
        for col in required_cols:
            if col not in df_result.columns:
                df_result = df_result.with_columns([pl.lit(None).alias(col)])
        
        return df_result
        
    except Exception as e:
        raise Exception(f"Error calculating Keltner Channel with pandas_ta: {str(e)}")


def calculate_supertrend(df: pl.DataFrame, period: int, multiplier: float) -> pl.DataFrame:
    """
    Calculate Supertrend indicator on Heikin-Ashi prices using pandas_ta.
    
    This function uses pandas_ta.supertrend() which provides a well-tested,
    accurate implementation of the SuperTrend indicator.
    
    Args:
        df: Polars DataFrame with Heikin-Ashi columns (ha_high, ha_low, ha_close)
        period: ATR period for SuperTrend calculation
        multiplier: Multiplier for ATR in SuperTrend calculation
    
    Returns:
        Polars DataFrame with SuperTrend columns added:
        - final_upper: Final upper band
        - final_lower: Final lower band
        - supertrend: SuperTrend value
        - supertrend_trend: Trend direction (1 for uptrend, -1 for downtrend)
    """
    try:
        # Convert Polars DataFrame to Pandas for pandas_ta
        df_pd = df.to_pandas()
        
        # Ensure we have the required Heikin-Ashi columns
        if not all(col in df_pd.columns for col in ['ha_high', 'ha_low', 'ha_close']):
            raise ValueError("DataFrame must contain ha_high, ha_low, and ha_close columns")
        
        # Calculate SuperTrend using pandas_ta
        # pandas_ta.supertrend returns a DataFrame with columns:
        # - SUPERT_{period}_{multiplier}: SuperTrend value
        # - SUPERTd_{period}_{multiplier}: Trend direction (1 for up, -1 for down)
        # - SUPERTl_{period}_{multiplier}: Lower band
        # - SUPERTs_{period}_{multiplier}: Upper band (s = super/upper)
        st_result = ta.supertrend(
            high=df_pd['ha_high'],
            low=df_pd['ha_low'],
            close=df_pd['ha_close'],
            length=period,
            multiplier=multiplier
        )
        
        if st_result is None or len(st_result.columns) == 0:
            raise ValueError("pandas_ta.supertrend() returned None or empty result")
        
        # Build column name patterns based on period and multiplier
        # pandas_ta formats multiplier as float (e.g., "3.0"), but we'll try both formats
        # Format: SUPERT_{period}_{multiplier} or SUPERT_{period}_{multiplier.0}
        col_suffix_int = f"{period}_{int(multiplier)}"
        col_suffix_float = f"{period}_{multiplier}"
        
        # Try to find columns with expected names
        st_cols = [col for col in st_result.columns if col.startswith('SUPERT')]
        
        if len(st_cols) < 4:
            raise ValueError(f"Expected 4 SuperTrend columns, found {len(st_cols)}: {st_cols}")
        
        # Sort columns to get consistent order: SUPERT_*, SUPERTd_*, SUPERTl_*, SUPERTs_*
        st_cols_sorted = sorted(st_cols)
        
        # Find columns by pattern
        supert_value_col = None
        supert_trend_col = None
        supert_lower_col = None
        supert_upper_col = None
        
        for col in st_cols_sorted:
            if col == f"SUPERT_{col_suffix_float}" or col == f"SUPERT_{col_suffix_int}":
                supert_value_col = col
            elif col == f"SUPERTd_{col_suffix_float}" or col == f"SUPERTd_{col_suffix_int}":
                supert_trend_col = col
            elif col == f"SUPERTl_{col_suffix_float}" or col == f"SUPERTl_{col_suffix_int}":
                supert_lower_col = col
            elif col == f"SUPERTs_{col_suffix_float}" or col == f"SUPERTs_{col_suffix_int}":
                supert_upper_col = col
        
        # Fallback: use sorted order if pattern matching didn't work
        if not all([supert_value_col, supert_trend_col, supert_lower_col, supert_upper_col]):
            supert_value_col = st_cols_sorted[0]  # SUPERT_*
            supert_trend_col = st_cols_sorted[1]  # SUPERTd_*
            supert_lower_col = st_cols_sorted[2]  # SUPERTl_*
            supert_upper_col = st_cols_sorted[3]  # SUPERTs_*
        
        # Add SuperTrend columns to the pandas DataFrame
        df_pd['supertrend'] = st_result[supert_value_col]
        df_pd['supertrend_trend'] = st_result[supert_trend_col]
        df_pd['final_lower'] = st_result[supert_lower_col]
        df_pd['final_upper'] = st_result[supert_upper_col]
        
        # Convert back to Polars DataFrame
        df_result = pl.from_pandas(df_pd)
        
        # Ensure all required columns exist (fill with None if missing)
        required_cols = ['final_upper', 'final_lower', 'supertrend', 'supertrend_trend']
        for col in required_cols:
            if col not in df_result.columns:
                df_result = df_result.with_columns([pl.lit(None).alias(col)])
        
        return df_result
        
    except Exception as e:
        raise Exception(f"Error calculating Supertrend with pandas_ta: {str(e)}")


def calculate_volume_ma(df: pl.DataFrame, period: int) -> pl.DataFrame:
    """
    Calculate Moving Average on Volume.
    
    Args:
        df: Polars DataFrame with volume column
        period: Period for moving average
    
    Returns:
        Polars DataFrame with Volume MA column added
    """
    try:
        # Calculate SMA on volume using Polars native rolling window
        df = df.with_columns([
            pl.col("volume").rolling_mean(window_size=period).alias("VolumeMA")
        ])
        
        return df
        
    except Exception as e:
        raise Exception(f"Error calculating Volume MA: {str(e)}")


def process_historical_data(
    historical_df: pd.DataFrame,
    volume_ma_period: int,
    supertrend_period: int,
    supertrend_multiplier: float,
    kc1_length: int,
    kc1_multiplier: float,
    kc1_atr: int,
    kc2_length: int,
    kc2_multiplier: float,
    kc2_atr: int
) -> pl.DataFrame:
    """
    Process historical data: Convert to Heikin-Ashi, calculate indicators, and return Polars DataFrame.
    
    Args:
        historical_df: pandas DataFrame with OHLCV data
        volume_ma_period: Period for Volume Moving Average
        supertrend_period: Period for Supertrend
        supertrend_multiplier: Multiplier for Supertrend
        kc1_length: EMA length for Keltner Channel 1
        kc1_multiplier: Multiplier for Keltner Channel 1
        kc1_atr: ATR period for Keltner Channel 1
        kc2_length: EMA length for Keltner Channel 2
        kc2_multiplier: Multiplier for Keltner Channel 2
        kc2_atr: ATR period for Keltner Channel 2
    
    Returns:
        Polars DataFrame with all calculated indicators
    """
    try:
        print("[Processing] Converting pandas DataFrame to Polars...")
        
        # Fix timezone issue: Convert date column to timezone-naive if it has timezone
        historical_df = historical_df.copy()
        if 'date' in historical_df.columns:
            # Remove timezone from date column (handle all timezone-aware cases)
            try:
                # Check if timezone-aware
                is_tz_aware = False
                if hasattr(historical_df['date'].dtype, 'tz') and historical_df['date'].dtype.tz is not None:
                    is_tz_aware = True
                elif len(historical_df) > 0:
                    try:
                        # Try to access tz attribute on first value
                        if hasattr(historical_df['date'].iloc[0], 'tz') and historical_df['date'].iloc[0].tz is not None:
                            is_tz_aware = True
                    except (AttributeError, IndexError):
                        pass
                
                if is_tz_aware:
                    print("[Processing] Removing timezone from date column...")
                    # Convert timezone-aware datetime to timezone-naive
                    # Use tz_convert to UTC first, then remove timezone
                    try:
                        historical_df['date'] = historical_df['date'].dt.tz_convert('UTC').dt.tz_localize(None)
                    except Exception:
                        # Alternative: directly convert to naive
                        historical_df['date'] = historical_df['date'].dt.tz_localize(None)
                else:
                    # Ensure it's timezone-naive datetime
                    historical_df['date'] = pd.to_datetime(historical_df['date'])
            except Exception as e:
                # Last resort: convert to string and back to datetime without timezone
                print(f"[Processing] Removing timezone from date column (fallback method): {str(e)}")
                historical_df['date'] = pd.to_datetime(historical_df['date'].astype(str))
        
        # Convert pandas to polars
        try:
            df_pl = pl.from_pandas(historical_df)
        except Exception as e:
            # Fallback: manually construct Polars DataFrame
            print(f"[Processing] Using manual conversion due to timezone issues: {str(e)}")
            # Ensure date is timezone-naive
            if 'date' in historical_df.columns:
                historical_df['date'] = pd.to_datetime(historical_df['date']).dt.tz_localize(None)
            
            # Create Polars DataFrame from dictionary
            data_dict = {}
            for col in historical_df.columns:
                if historical_df[col].dtype == 'datetime64[ns]' or 'datetime' in str(historical_df[col].dtype):
                    # Convert datetime to Polars datetime
                    data_dict[col] = pl.Series(historical_df[col].values)
                else:
                    data_dict[col] = historical_df[col].values
            df_pl = pl.DataFrame(data_dict)
        
        # Ensure column names are lowercase (Zerodha returns lowercase, but just in case)
        column_mapping = {}
        for col in df_pl.columns:
            if col.lower() != col:
                column_mapping[col] = col.lower()
        
        if column_mapping:
            df_pl = df_pl.rename(column_mapping)
        
        print("[Processing] Converting to Heikin-Ashi candles...")
        # Convert to Heikin-Ashi
        df_pl = convert_to_heikin_ashi(df_pl)
        
        print("[Processing] Calculating Volume MA...")
        # Calculate Volume MA
        df_pl = calculate_volume_ma(df_pl, volume_ma_period)
        
        print("[Processing] Calculating Supertrend...")
        # Calculate Supertrend
        df_pl = calculate_supertrend(df_pl, supertrend_period, supertrend_multiplier)
        
        print("[Processing] Calculating Keltner Channel 1...")
        # Calculate Keltner Channel 1
        df_pl = calculate_keltner_channel(df_pl, kc1_length, kc1_multiplier, kc1_atr, "KC1")
        
        print("[Processing] Calculating Keltner Channel 2...")
        # Calculate Keltner Channel 2
        df_pl = calculate_keltner_channel(df_pl, kc2_length, kc2_multiplier, kc2_atr, "KC2")
        
        print(f"[Processing] Processing complete. DataFrame shape: {df_pl.shape}")
        
        # Round all numeric columns to 2 decimal places (excluding date column)
        print("[Processing] Rounding all numeric values to 2 decimal places...")
        numeric_columns = []
        for col in df_pl.columns:
            if col != "date":  # Skip date column
                dtype = df_pl[col].dtype
                # Check if it's a numeric type
                if dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32, pl.Int16, pl.Int8]:
                    numeric_columns.append(col)
        
        # Round float columns to 2 decimal places
        for col in numeric_columns:
            dtype = df_pl[col].dtype
            if dtype in [pl.Float64, pl.Float32]:
                df_pl = df_pl.with_columns([
                    pl.col(col).round(2).alias(col)
                ])
            elif dtype in [pl.Int64, pl.Int32, pl.Int16, pl.Int8]:
                # Convert integers to float and round (in case they need decimal precision)
                df_pl = df_pl.with_columns([
                    pl.col(col).cast(pl.Float64).round(2).alias(col)
                ])
        
        return df_pl
        
    except Exception as e:
        raise Exception(f"Error processing historical data: {str(e)}")


def fetch_historical_data_for_symbol(kite: KiteConnect, symbol: str, timeframe: str, days_back: int = 10) -> pd.DataFrame:
    """
    Fetch historical data for a symbol using the timeframe from TradeSettings.
    
    Args:
        kite: KiteConnect client instance
        symbol: Trading symbol (e.g., "CRUDEOIL")
        timeframe: Timeframe from TradeSettings (e.g., "5minute")
        days_back: Number of days of historical data to fetch (default: 10)
    
    Returns:
        pandas DataFrame with historical OHLCV data
    """
    try:
        # Search for instrument across common commodity exchanges
        # For commodities like CRUDEOIL, try MCX first
        exchanges_to_try = ["MCX", "NFO", "NSE", "BSE"]
        instrument_token = None
        exchange_found = None
        
        for exchange in exchanges_to_try:
            try:
                token = get_instrument_token(kite, exchange, symbol)
                if token:
                    instrument_token = token
                    exchange_found = exchange
                    print(f"[Historical] Found {symbol} in {exchange} with token {instrument_token}")
                    break
            except Exception as e:
                error_str = str(e)
                if "Too many requests" in error_str or "too many requests" in error_str.lower():
                    # Handle too many requests error
                    print(f"[Historical] Too many requests error while fetching instrument token for {exchange}")
                    raise  # Re-raise to be handled by caller
                # Continue to next exchange for other errors
                continue
        
        if not instrument_token:
            print(f"[Historical] Could not find instrument token for {symbol}")
            return pd.DataFrame()
        
        # Calculate date range
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        
        # Fetch historical data using timeframe from TradeSettings
        df = get_historical_data(
            kite=kite,
            instrument_token=instrument_token,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            continuous=False,
            oi=False
        )
        
        return df
        
    except Exception as e:
        print(f"[Historical] Error fetching data for {symbol}: {str(e)}")
        traceback.print_exc()
        return pd.DataFrame()


def normalize_strike(ltp: float, strike_step: int) -> int:
    """
    Normalize LTP to nearest strike based on strike step.
    
    Args:
        ltp: Last Traded Price
        strike_step: Strike step (e.g., 50)
    
    Returns:
        Normalized strike price (ATM)
    
    Example:
        ltp = 5319, strike_step = 50 -> returns 5300
    """
    return int(round(ltp / strike_step) * strike_step)


def create_strike_list(atm: int, strike_step: int, strike_number: int) -> list:
    """
    Create a list of strikes around ATM.
    
    Args:
        atm: At-the-money strike
        strike_step: Strike step (e.g., 50)
        strike_number: Number of strikes on each side of ATM
    
    Returns:
        List of strike prices
    
    Example:
        atm = 5300, strike_step = 50, strike_number = 6
        -> [5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500, 5550, 5600]
    """
    strikes = []
    for i in range(-strike_number, strike_number + 1):
        strike = atm + (i * strike_step)
        strikes.append(strike)
    return strikes


def get_ltp(kite: KiteConnect, exchange: str, symbol: str) -> float:
    """
    Get Last Traded Price (LTP) for a symbol.
    
    Args:
        kite: KiteConnect client instance
        exchange: Exchange name (e.g., "MCX", "NFO")
        symbol: Trading symbol
    
    Returns:
        LTP as float, or None if not found
    """
    try:
        # Format: exchange:tradingsymbol
        instrument_id = f"{exchange}:{symbol}"
        quote_data = kite.quote(instrument_id)
        
        if instrument_id in quote_data:
            ltp = quote_data[instrument_id].get('last_price', None)
            if ltp:
                return float(ltp)
        
        # Alternative: Try ltp() method
        ltp_data = kite.ltp(instrument_id)
        if instrument_id in ltp_data:
            ltp = ltp_data[instrument_id].get('last_price', None)
            if ltp:
                return float(ltp)
        
        print(f"[LTP] Could not get LTP for {symbol} on {exchange}")
        return None
        
    except Exception as e:
        print(f"[LTP] Error getting LTP for {symbol}: {str(e)}")
        return None


def calculate_delta_black_scholes(
    S: float,  # Current stock price
    K: float,  # Strike price
    T: float,  # Time to expiration (in years)
    r: float,  # Risk-free interest rate (e.g., 0.06 for 6%)
    sigma: float,  # Volatility (implied volatility)
    option_type: str  # 'CE' for call, 'PE' for put
) -> float:
    """
    Calculate option delta using Black-Scholes model.
    
    Libraries Used:
    - scipy.stats.norm: For cumulative distribution function N(d1)
    - math.log, math.sqrt: For logarithmic and square root calculations
    
    Formula:
    - d1 = [ln(S/K) + (r + σ²/2) * T] / (σ * √T)
    - Call Delta = N(d1)
    - Put Delta = N(d1) - 1
    
    Args:
        S: Current stock price (LTP)
        K: Strike price
        T: Time to expiration in years
        r: Risk-free interest rate (default: 0.06 for 6%)
        sigma: Implied volatility (as decimal, e.g., 0.20 for 20%)
        option_type: 'CE' for Call, 'PE' for Put
    
    Returns:
        Delta value (0 to 1 for calls, -1 to 0 for puts)
    """
    try:
        if T <= 0:
            # If expired, delta is 1 for ITM calls, 0 for OTM calls
            if option_type == 'CE':
                return 1.0 if S > K else 0.0
            else:  # PE
                return -1.0 if S < K else 0.0
        
        if sigma <= 0:
            # If no volatility, use simple ITM/OTM logic
            if option_type == 'CE':
                return 1.0 if S > K else 0.0
            else:  # PE
                return -1.0 if S < K else 0.0
        
        # Calculate d1
        d1 = (log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * sqrt(T))
        
        # Calculate delta
        if option_type == 'CE':
            delta = norm.cdf(d1)  # N(d1) for calls
        else:  # PE
            delta = norm.cdf(d1) - 1  # N(d1) - 1 for puts
        
        return delta
        
    except Exception as e:
        print(f"[Delta] Error calculating delta: {str(e)}")
        # Fallback: simple ITM/OTM logic
        if option_type == 'CE':
            return 1.0 if S > K else 0.0
        else:  # PE
            return -1.0 if S < K else 0.0


def construct_option_symbol(symbol: str, expiry: str, strike: int, option_type: str) -> str:
    """
    Construct option symbol for Zerodha.
    
    Format: {SYMBOL}{YEAR}{MONTH}{STRIKE}{CE/PE}
    Example: CRUDEOIL + 19-11-2025 + 5300 + CE -> CRUDEOIL25NOV5300CE
    
    Args:
        symbol: Base symbol (e.g., "CRUDEOIL")
        expiry: Expiry date in format "DD-MM-YYYY" (e.g., "19-11-2025")
        strike: Strike price (e.g., 5300)
        option_type: 'CE' for Call, 'PE' for Put
    
    Returns:
        Option symbol string
    """
    try:
        # Parse expiry date
        expiry_parts = expiry.split('-')
        if len(expiry_parts) != 3:
            raise ValueError(f"Invalid expiry format: {expiry}. Expected DD-MM-YYYY")
        
        day = expiry_parts[0]
        month = int(expiry_parts[1])
        year = int(expiry_parts[2])
        
        # Get last 2 digits of year
        year_short = str(year)[-2:]
        
        # Month abbreviations
        month_map = {
            1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
            7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
        }
        
        if month not in month_map:
            raise ValueError(f"Invalid month: {month}")
        
        month_abbr = month_map[month]
        
        # Construct option symbol: {SYMBOL}{YEAR}{MONTH}{STRIKE}{CE/PE}
        option_symbol = f"{symbol}{year_short}{month_abbr}{strike}{option_type}"
        
        return option_symbol
        
    except Exception as e:
        raise Exception(f"Error constructing option symbol: {str(e)}")


def get_option_quote(kite: KiteConnect, exchange: str, option_symbol: str) -> dict:
    """
    Get option quote data including IV (Implied Volatility) if available.
    
    Args:
        kite: KiteConnect client instance
        exchange: Exchange name (e.g., "NFO", "MCX")
        option_symbol: Option trading symbol
    
    Returns:
        Dictionary with quote data including 'last_price', 'iv' (if available), etc.
    """
    try:
        instrument_id = f"{exchange}:{option_symbol}"
        quote_data = kite.quote(instrument_id)
        
        if instrument_id in quote_data:
            return quote_data[instrument_id]
        
        return {}
        
    except Exception as e:
        print(f"[Option Quote] Error getting quote for {option_symbol}: {str(e)}")
        return {}


def place_option_order(
    kite: KiteConnect,
    exchange: str,
    option_symbol: str,
    transaction_type: str,
    quantity: int,
    order_type: str = "LIMIT",
    product: str = "NRML",
    price: float = None
) -> dict:
    """
    Place an option order using Kite API.
    
    Args:
        kite: KiteConnect client instance
        exchange: Exchange name (e.g., "NFO", "MCX")
        option_symbol: Option trading symbol (e.g., "CRUDEOIL25NOV5300CE")
        transaction_type: "BUY" or "SELL"
        quantity: Number of lots (will be multiplied by lot size)
        order_type: Order type - "MARKET" or "LIMIT" (default: "LIMIT")
        product: Product type - "MIS" (Intraday), "NRML" (Carry forward/Positional), "CNC" (Delivery)
        price: Price for LIMIT orders (required if order_type is "LIMIT")
    
    Returns:
        Dictionary with order response from Kite API, or None if failed
        If failed, the error details are logged to OrderLog.txt
    """
    error_details = None
    try:
        # Get instrument token for the option
        instrument_token = get_instrument_token(kite, exchange, option_symbol)
        if not instrument_token:
            error_msg = f"Could not find instrument token for {option_symbol} on exchange {exchange}. Symbol may not exist or exchange may be incorrect."
            print(f"[Order] {error_msg}")
            error_details = error_msg
            write_to_order_logs(f"ORDER FAILED: {transaction_type} {option_symbol} | Exchange: {exchange} | Error: {error_msg}")
            return None
        
        # For LIMIT orders, price is required
        if order_type == "LIMIT":
            if price is None:
                error_msg = f"Price is required for LIMIT orders. Option LTP not available for {option_symbol}."
                print(f"[Order] {error_msg}")
                error_details = error_msg
                write_to_order_logs(f"ORDER FAILED: {transaction_type} {option_symbol} | Exchange: {exchange} | Error: {error_msg}")
                return None
        
        # Prepare order parameters
        order_params = {
            'variety': kite.VARIETY_REGULAR,
            'exchange': exchange,
            'tradingsymbol': option_symbol,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'product': product,
            'order_type': order_type
        }
        
        # Add price for LIMIT orders
        if order_type == "LIMIT" and price is not None:
            order_params['price'] = round(price, 2)
        
        # Place order
        order_response = kite.place_order(**order_params)
        
        # Print broker response
        price_info = f" | Price: {price:.2f}" if order_type == "LIMIT" and price is not None else ""
        broker_response_str = f"Broker Response: {order_response}"
        print(f"[Order] {transaction_type} {order_type} order placed for {option_symbol}: Order ID = {order_response.get('order_id', 'N/A')}{price_info}")
        print(f"[Order] {broker_response_str}")
        write_to_order_logs(f"BROKER RESPONSE: {transaction_type} {option_symbol} | {broker_response_str}")
        
        return order_response
        
    except Exception as e:
        error_msg = f"API Error: {str(e)}"
        print(f"[Order] Error placing {transaction_type} order for {option_symbol}: {error_msg}")
        error_details = error_msg
        price_info = f" | Price: {price:.2f}" if price is not None else ""
        write_to_order_logs(f"ORDER FAILED: {transaction_type} {option_symbol} | Exchange: {exchange} | Quantity: {quantity} | Product: {product} | OrderType: {order_type}{price_info} | Error: {error_msg}")
        traceback.print_exc()
        return None


def find_exchange_for_symbol(kite: KiteConnect, symbol: str) -> str:
    """
    Find the exchange where a symbol is traded.
    
    Args:
        kite: KiteConnect client instance
        symbol: Trading symbol
    
    Returns:
        Exchange name (e.g., "MCX", "NFO", "NSE"), or None if not found
    """
    exchanges_to_try = ["MCX", "NFO", "NSE", "BSE"]
    for exchange in exchanges_to_try:
        try:
            token = get_instrument_token(kite, exchange, symbol)
            if token:
                return exchange
        except Exception:
            continue
    return None


def find_option_with_max_delta(
    kite: KiteConnect,
    symbol: str,
    expiry: str,
    exchange: str,
    strikes: list,
    ltp: float,
    option_type: str,
    risk_free_rate: float = 0.06
) -> dict:
    """
    Find the option with maximum delta among given strikes.
    
    Args:
        kite: KiteConnect client instance
        symbol: Base symbol (e.g., "CRUDEOIL")
        expiry: Expiry date in format "DD-MM-YYYY"
        exchange: Exchange name (e.g., "NFO", "MCX")
        strikes: List of strike prices to check
        ltp: Last Traded Price of underlying
        option_type: 'CE' for Call, 'PE' for Put
        risk_free_rate: Risk-free interest rate (default: 0.06 for 6%)
    
    Returns:
        Dictionary with 'strike', 'delta', 'option_symbol', 'iv', 'ltp', etc.
        Also includes 'all_strikes_evaluated' list with all strike data for logging
    """
    try:
        # Calculate time to expiration
        expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
        current_date = datetime.now()
        time_to_expiry = (expiry_date - current_date).total_seconds() / (365.25 * 24 * 3600)  # Convert to years
        
        if time_to_expiry <= 0:
            print(f"[Max Delta] Option expired for {symbol}")
            return None
        
        # Initialize max_delta/min_delta based on option type
        # For PUT: we want LOWEST (most negative) delta, so start with 0.0 (least negative)
        # For CALL: we want HIGHEST (most positive) delta, so start with -1.0
        # Delta cap: 0.80 for CALLs, -0.80 for PUTs
        if option_type == 'PE':
            min_delta = 0.0  # Start with least negative (we want to find most negative)
        else:
            max_delta = -1.0  # Start with very negative (we want to find most positive)
        best_option = None
        
        # Store all strike deltas for printing
        all_strike_data = []
        
        print(f"\n{'='*80}")
        selection_type = "min delta (most negative)" if option_type == 'PE' else "max delta"
        print(f"[DELTA CALCULATION] Finding {option_type} option with {selection_type} (capped at {'0.80' if option_type == 'CE' else '-0.80'})")
        print(f"Underlying: {symbol} | LTP: {ltp:.2f} | ATM: {normalize_strike(ltp, 50):.0f}")
        print(f"Time to Expiry: {time_to_expiry:.4f} years | Risk-free Rate: {risk_free_rate*100:.2f}%")
        print(f"{'='*80}")
        print(f"{'Strike':<10} {'Option Symbol':<25} {'Delta':<12} {'IV':<10} {'LTP':<12} {'Status':<15}")
        print(f"{'-'*80}")
        
        for strike in strikes:
            try:
                # Construct option symbol
                option_symbol = construct_option_symbol(symbol, expiry, strike, option_type)
                
                # Get option quote
                quote = get_option_quote(kite, exchange, option_symbol)
                
                # Get option LTP (Last Traded Price)
                option_ltp_raw = quote.get('last_price', None)
                option_ltp_display = 'N/A'
                option_ltp_float = None
                
                if option_ltp_raw is not None:
                    option_ltp_float = float(option_ltp_raw)
                    option_ltp_display = f"{option_ltp_float:.2f}"
                
                # Calculate IV using py_vollib from option market price - NO DEFAULT IV
                iv = None
                iv_source = "N/A"
                
                # Must have valid option LTP to calculate IV
                if option_ltp_float is not None and option_ltp_float > 0:
                    try:
                        # Convert option_type to py_vollib format: 'c' for call, 'p' for put
                        flag = 'c' if option_type == 'CE' else 'p'
                        
                        # Calculate implied volatility from market price using py_vollib
                        iv = implied_volatility(
                            price=option_ltp_float,
                            S=ltp,
                            K=float(strike),
                            t=time_to_expiry,
                            r=risk_free_rate,
                            flag=flag
                        )
                        iv_source = "py_vollib"
                    except Exception as iv_error:
                        # If py_vollib calculation fails, try to get fresh LTP and retry once
                        error_msg = f"IV CALCULATION FAILED | Strike: {strike} | Symbol: {option_symbol} | Initial LTP: {option_ltp_float:.2f} | Error: {str(iv_error)} | Attempting fresh LTP fetch..."
                        print(f"[Max Delta] {error_msg}")
                        write_to_order_logs(error_msg)
                        try:
                            # Get fresh quote to retry with updated LTP
                            fresh_quote = get_option_quote(kite, exchange, option_symbol)
                            fresh_ltp = fresh_quote.get('last_price', None)
                            if fresh_ltp is not None:
                                fresh_ltp_float = float(fresh_ltp)
                                if fresh_ltp_float > 0:
                                    # Retry IV calculation with fresh LTP
                                    iv = implied_volatility(
                                        price=fresh_ltp_float,
                                        S=ltp,
                                        K=float(strike),
                                        t=time_to_expiry,
                                        r=risk_free_rate,
                                        flag=flag
                                    )
                                    iv_source = "py_vollib"
                                    option_ltp_float = fresh_ltp_float  # Update LTP for delta calculation
                                    option_ltp_display = f"{fresh_ltp_float:.2f}"
                                    success_msg = f"IV CALCULATION RETRY SUCCESS | Strike: {strike} | Symbol: {option_symbol} | Fresh LTP: {fresh_ltp_float:.2f} | Calculated IV: {iv*100:.2f}%"
                                    print(f"[Max Delta] {success_msg}")
                                    write_to_order_logs(success_msg)
                                else:
                                    skip_msg = f"STRIKE SKIPPED | Strike: {strike} | Symbol: {option_symbol} | Reason: Fresh LTP is zero or invalid"
                                    print(f"[Max Delta] {skip_msg}")
                                    write_to_order_logs(skip_msg)
                                    continue
                            else:
                                skip_msg = f"STRIKE SKIPPED | Strike: {strike} | Symbol: {option_symbol} | Reason: No fresh LTP available for retry"
                                print(f"[Max Delta] {skip_msg}")
                                write_to_order_logs(skip_msg)
                                continue
                        except Exception as retry_error:
                            skip_msg = f"STRIKE SKIPPED | Strike: {strike} | Symbol: {option_symbol} | Reason: IV calculation retry failed | Retry Error: {str(retry_error)}"
                            print(f"[Max Delta] {skip_msg}")
                            write_to_order_logs(skip_msg)
                            continue
                else:
                    # No LTP available - skip this strike
                    skip_msg = f"STRIKE SKIPPED | Strike: {strike} | Symbol: {option_symbol} | Reason: No option LTP available for IV calculation"
                    print(f"[Max Delta] {skip_msg}")
                    write_to_order_logs(skip_msg)
                    continue
                
                # If IV still not calculated, skip this strike
                if iv is None or iv <= 0:
                    skip_msg = f"STRIKE SKIPPED | Strike: {strike} | Symbol: {option_symbol} | Reason: IV calculation failed (IV is None or <= 0)"
                    print(f"[Max Delta] {skip_msg}")
                    write_to_order_logs(skip_msg)
                    continue
                
                # Calculate delta using py_vollib
                delta = None
                if iv is not None and iv > 0:
                    try:
                        # Convert option_type to py_vollib format
                        flag = 'c' if option_type == 'CE' else 'p'
                        
                        # Calculate delta using py_vollib
                        delta = py_vollib_delta(
                            flag=flag,
                            S=ltp,
                            K=float(strike),
                            t=time_to_expiry,
                            r=risk_free_rate,
                            sigma=iv
                        )
                    except Exception as delta_error:
                        # Fallback to manual calculation if py_vollib fails
                        print(f"[Max Delta] Warning: py_vollib delta calculation failed for {option_symbol}: {str(delta_error)}")
                        delta = calculate_delta_black_scholes(
                            S=ltp,
                            K=float(strike),
                            T=time_to_expiry,
                            r=risk_free_rate,
                            sigma=iv,
                            option_type=option_type
                        )
                else:
                    # If IV not available, use fallback calculation
                    delta = calculate_delta_black_scholes(
                        S=ltp,
                        K=float(strike),
                        T=time_to_expiry,
                        r=risk_free_rate,
                        sigma=0.20,  # Use default IV for delta calculation
                        option_type=option_type
                    )
                
                # Store strike data
                strike_data = {
                    'strike': strike,
                    'delta': delta,
                    'option_symbol': option_symbol,
                    'iv': iv,
                    'iv_source': iv_source,
                    'ltp': option_ltp_display,
                    'ltp_float': option_ltp_float,  # Store float value for order placement
                    'time_to_expiry': time_to_expiry
                }
                all_strike_data.append(strike_data)
                
                # Determine if this is currently the best
                # Cap delta selection at 0.80 (or -0.80 for PUTs)
                MAX_DELTA_CAP = 0.80
                MIN_DELTA_CAP = -0.80  # For PUTs
                
                is_best = False
                if option_type == 'PE':
                    # For puts, delta is negative
                    # Select MINIMUM delta (most negative) that is >= -0.80
                    # We want the lowest delta (most negative) that is >= -0.80
                    if delta >= MIN_DELTA_CAP:  # Only consider deltas >= -0.80
                        if delta < min_delta:  # For negative values, < means more negative (lower)
                            min_delta = delta
                            best_option = strike_data
                            is_best = True
                else:  # CE
                    # For calls, delta is positive
                    # Select maximum delta up to 0.80 (not more than 0.80)
                    if delta <= MAX_DELTA_CAP:  # Only consider deltas <= 0.80
                        if delta > max_delta:
                            max_delta = delta
                            best_option = strike_data
                            is_best = True
                
                # Print strike data with indicator if it's the best
                status = "✓ SELECTED" if is_best else ""
                print(f"{strike:<10} {option_symbol:<25} {delta:>11.4f}  {iv*100:>8.2f}% ({iv_source})  {option_ltp_display:>12}  {status:<15}")
                
            except Exception as e:
                print(f"{strike:<10} {'ERROR':<25} {'N/A':<12} {'N/A':<10} {'N/A':<12} {str(e)[:15]:<15}")
                print(f"[Max Delta] Error processing strike {strike}: {str(e)}")
                continue
        
        print(f"{'-'*80}")
        
        # Print summary
        if best_option:
            delta_cap_info = f" (Capped at {'0.80' if option_type == 'CE' else '-0.80'})"
            print(f"\n[SELECTED OPTION]")
            print(f"  Strike: {best_option['strike']}")
            print(f"  Option Symbol: {best_option['option_symbol']}")
            print(f"  Delta: {best_option['delta']:.6f}{delta_cap_info}")
            print(f"  IV: {best_option['iv']*100:.2f}% (Source: {best_option['iv_source']})")
            print(f"  Option LTP: {best_option['ltp']}")
            print(f"  Time to Expiry: {best_option['time_to_expiry']:.4f} years")
        else:
            print(f"\n[WARNING] No valid option found with max delta (within cap of {'0.80' if option_type == 'CE' else '-0.80'})")
        
        print(f"{'='*80}\n")
        
        # Add all strike data to best_option for logging purposes
        if best_option:
            best_option['all_strikes_evaluated'] = all_strike_data
            best_option['underlying_ltp'] = ltp
            # Calculate ATM strike as the strike closest to LTP
            if strikes:
                atm_strike = min(strikes, key=lambda x: abs(x - ltp))
            else:
                atm_strike = None
            best_option['atm_strike'] = atm_strike
            best_option['time_to_expiry_years'] = time_to_expiry
            best_option['risk_free_rate'] = risk_free_rate
        
        return best_option
        
    except Exception as e:
        print(f"[Max Delta] Error finding option with max delta: {str(e)}")
        traceback.print_exc()
        return None


def calculate_initial_sl(df: pl.DataFrame, position_type: str, sl_atr_period: int, sl_multiplier: float) -> float:
    """
    Calculate initial stop loss from last 5 candles with ATR adjustment.
    
    Formula:
    - BUY: Initial SL = Lowest HA_Low of last 5 candles - (ATR × SLMULTIPLIER)
    - SELL: Initial SL = Highest HA_High of last 5 candles + (ATR × SLMULTIPLIER)
    
    Args:
        df: Polars DataFrame with Heikin-Ashi data
        position_type: 'BUY' or 'SELL'
        sl_atr_period: ATR period for calculation (e.g., 14)
        sl_multiplier: Multiplier for ATR (e.g., 2.0)
    
    Returns:
        Initial SL value with ATR adjustment
    """
    try:
        # Get last 5 candles (excluding current candle) for finding lowest low/highest high
        if df.height < 6:
            # If not enough candles, use all available (excluding current)
            candles_for_sl = df.head(df.height - 1) if df.height > 1 else df
        else:
            # Get last 6 candles, exclude the last one (current), take previous 5
            candles_for_sl = df.tail(6).head(5)
        
        if candles_for_sl.height == 0:
            return None
        
        # Calculate ATR using pandas_ta on full Heikin-Ashi data (ATR needs sufficient data)
        # Convert full dataframe to pandas for ATR calculation
        df_full_pd = df.to_pandas()
        
        # Ensure we have the required Heikin-Ashi columns
        if not all(col in df_full_pd.columns for col in ['ha_high', 'ha_low', 'ha_close']):
            raise ValueError("DataFrame must contain ha_high, ha_low, and ha_close columns")
        
        # Calculate ATR using pandas_ta on Heikin-Ashi data (use full dataframe for accurate ATR)
        atr_result = ta.atr(
            high=df_full_pd['ha_high'],
            low=df_full_pd['ha_low'],
            close=df_full_pd['ha_close'],
            length=sl_atr_period
        )
        
        if atr_result is None or len(atr_result) == 0:
            print(f"[SL Calculation] Error: Could not calculate ATR. Falling back to simple lowest low/highest high.")
            # Fallback: return simple lowest low/highest high without ATR adjustment
            if position_type == 'BUY':
                lowest_low = candles_for_sl['ha_low'].min()
                return float(lowest_low)
            elif position_type == 'SELL':
                highest_high = candles_for_sl['ha_high'].max()
                return float(highest_high)
            else:
                return None
        
        # Get the last ATR value (most recent)
        # ATR is calculated on historical data, so the last value is the most recent ATR
        current_atr = float(atr_result.iloc[-1])
        
        # Calculate ATR adjustment
        atr_adjustment = current_atr * sl_multiplier
        
        if position_type == 'BUY':
            # For BUY: Lowest low of last 5 candles - (ATR × Multiplier)
            lowest_low = candles_for_sl['ha_low'].min()
            initial_sl = float(lowest_low) - atr_adjustment
            print(f"[SL Calculation] BUY Initial SL: Lowest Low ({lowest_low:.2f}) - ATR Adjustment ({atr_adjustment:.2f} = ATR {current_atr:.2f} × {sl_multiplier}) = {initial_sl:.2f}")
            return initial_sl
        elif position_type == 'SELL':
            # For SELL: Highest high of last 5 candles + (ATR × Multiplier)
            highest_high = candles_for_sl['ha_high'].max()
            initial_sl = float(highest_high) + atr_adjustment
            print(f"[SL Calculation] SELL Initial SL: Highest High ({highest_high:.2f}) + ATR Adjustment ({atr_adjustment:.2f} = ATR {current_atr:.2f} × {sl_multiplier}) = {initial_sl:.2f}")
            return initial_sl
        else:
            return None
            
    except Exception as e:
        print(f"[SL Calculation] Error calculating initial SL: {str(e)}")
        traceback.print_exc()
        # Fallback: return simple lowest low/highest high without ATR adjustment
        try:
            if df.height < 6:
                candles_for_sl = df.head(df.height - 1) if df.height > 1 else df
            else:
                candles_for_sl = df.tail(6).head(5)
            
            if candles_for_sl.height == 0:
                return None
            
            if position_type == 'BUY':
                lowest_low = candles_for_sl['ha_low'].min()
                return float(lowest_low)
            elif position_type == 'SELL':
                highest_high = candles_for_sl['ha_high'].max()
                return float(highest_high)
            else:
                return None
        except Exception as fallback_error:
            print(f"[SL Calculation] Fallback also failed: {str(fallback_error)}")
            return None


def calculate_average_entry_price(entry_prices: list) -> float:
    """
    Calculate average of all entry prices.
    
    Args:
        entry_prices: List of entry prices (HA_Close values)
    
    Returns:
        Average entry price, or None if list is empty
    """
    try:
        if not entry_prices or len(entry_prices) == 0:
            return None
        return sum(entry_prices) / len(entry_prices)
    except Exception as e:
        print(f"[SL Calculation] Error calculating average entry price: {str(e)}")
        return None


def execute_trading_strategy(df: pl.DataFrame, unique_key: str, symbol: str, future_symbol: str, trading_state: dict):
    """
    Execute trading strategy based on Heikin-Ashi candles, Keltner Channels, Supertrend, and Volume.
    
    Strategy Rules:
    Note: KC1 = Outer band, KC2 = Inner band
    
    BUY:
    1. Armed Buy: HA candle low < outer KC lower band (KC1_lower - outer band) - evaluated on candle close
    2. Buy Entry: Any candle close > inner KC lower band (KC2_lower - inner band) AND volume > VolumeMA - evaluated on candle close
    3. Buy Exit: Supertrend changes from green (trend=1) to red (trend=-1) - evaluated on candle close
    4. Armed Buy Reset: Reset when candle's high > both upper Keltner bands - evaluated on candle close
    5. After Exit: Check if armed BUY, if current close > KC2_lower AND volume > VolumeMA → take entry
    
    SELL:
    1. Armed Sell: When BUY position exists, arm SELL if HA high >= outer KC upper band (KC1_upper - outer band) - evaluated on candle close
       OR if no position, arm SELL when HA high >= outer KC upper band (KC1_upper - outer band) - evaluated on candle close
    2. Sell Entry: Once armed, when current candle close < inner KC upper band (KC2_upper - inner band) AND volume > VolumeMA - evaluated on candle close
    3. Sell Exit: Supertrend changes from red (trend=-1) to green (trend=1) - evaluated on candle close
    4. Armed Sell Reset: Reset when candle's low < both lower Keltner bands - evaluated on candle close
    5. After Exit: Check if armed SELL, if current close < KC2_upper AND volume > VolumeMA → take entry
    
    Position Management:
    - One position at a time (BUY or SELL, never both)
    - Armed states can be set even when position exists
    - Entry trades are BLOCKED if position already exists (silently skip, no log)
    - After exit, immediately check armed status and entry conditions on same candle
    - Armed state remains active after entry (allows re-entry after exit if still armed)
    - Armed state resets only when opposite condition occurs
    - All conditions evaluated on candle close
    - Entry orders: Position is set regardless of order success/failure, broker status is logged
    """
    try:
        # Get the latest candle (most recent)
        latest_candle = df.tail(1)
        
        if latest_candle.height == 0:
            return
        
        # Extract values from latest candle
        row = latest_candle.row(0, named=True)
        
        # Get required columns
        date = row.get('date', None)
        ha_close = row.get('ha_close', None)
        ha_open = row.get('ha_open', None)
        ha_high = row.get('ha_high', None)
        ha_low = row.get('ha_low', None)
        volume = row.get('volume', None)
        volume_ma = row.get('VolumeMA', None)
        supertrend_trend = row.get('supertrend_trend', None)  # 1 = uptrend (green), -1 = downtrend (red)
        kc1_upper = row.get('KC1_upper', None)
        kc1_lower = row.get('KC1_lower', None)
        kc2_upper = row.get('KC2_upper', None)
        kc2_lower = row.get('KC2_lower', None)
        supertrend = row.get('supertrend', None)
        
        # Check for None values
        if any(x is None for x in [ha_close, ha_open, ha_high, ha_low, volume, supertrend_trend, 
                                   kc1_upper, kc1_lower, kc2_upper, kc2_lower]):
            print(f"[Strategy] Missing indicator values for {symbol}, skipping strategy execution")
            return
        
        # Get previous candle for trend change detection and entry conditions
        prev_row = None
        prev_ha_close = None
        prev_ha_open = None
        if df.height >= 2:
            prev_row = df.tail(2).row(0, named=True)  # Second to last row
            prev_supertrend_trend = prev_row.get('supertrend_trend', None)
            prev_ha_close = prev_row.get('ha_close', None)
            prev_ha_open = prev_row.get('ha_open', None)
        else:
            prev_supertrend_trend = None
            prev_ha_close = None
            prev_ha_open = None
        
        # ========== EXIT CONDITIONS (Check first before entry) ==========
        current_position = trading_state.get('position', None)
        
        # Get previous candle HA_Low and HA_High for SL check
        prev_ha_low = prev_row.get('ha_low', None) if prev_row else None
        prev_ha_high = prev_row.get('ha_high', None) if prev_row else None
        
        # ========== STOP LOSS EXIT CHECK (Before Supertrend Exit) ==========
        if current_position is not None:
            current_sl = trading_state.get('current_sl', None)
            
            # BUY Position SL Exit: Previous candle HA_Low < SL
            if current_position == 'BUY' and current_sl is not None and prev_ha_low is not None:
                if prev_ha_low < current_sl:
                    # SL hit - exit all positions
                    option_symbol = trading_state.get('option_symbol', None)
                    option_exchange = trading_state.get('option_exchange', None)
                    pyramiding_positions = trading_state.get('pyramiding_positions', [])
                    pyramiding_count = trading_state.get('pyramiding_count', 0)
                    first_entry_price = trading_state.get('first_entry_price', None)
                    params = result_dict.get(unique_key, {})
                    lotsize = int(params.get('Lotsize', 1))
                    
                    # Calculate total quantity (initial + all pyramiding positions)
                    total_lotsize = lotsize * pyramiding_count if pyramiding_count > 0 else lotsize
                    
                    # Exit all positions with ONE combined order
                    combined_exit_order_id = None
                    exit_price = None
                    if option_symbol and option_exchange and kite_client:
                        try:
                            quote = get_option_quote(kite_client, option_exchange, option_symbol)
                            option_ltp = quote.get('last_price', None)
                            if option_ltp is not None:
                                option_ltp = float(option_ltp)
                                exit_price = option_ltp
                                # Place ONE combined order for all positions
                                exit_order = place_option_order(
                                    kite=kite_client,
                                    exchange=option_exchange,
                                    option_symbol=option_symbol,
                                    transaction_type="SELL",
                                    quantity=total_lotsize,  # Combined quantity
                                    order_type="LIMIT",
                                    product="NRML",
                                    price=option_ltp
                                )
                                combined_exit_order_id = exit_order.get('order_id', None) if exit_order else None
                                write_to_order_logs(f"SL EXIT ORDER PLACED: SELL {option_symbol} (All Positions Combined) | Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} | Total Quantity: {total_lotsize} | Exit Price: {exit_price:.2f} | SL: {current_sl:.2f} | Prev HA_Low: {prev_ha_low:.2f}")
                        except Exception as e:
                            print(f"[SL Exit] Error placing exit order: {str(e)}")
                            write_to_order_logs(f"SL EXIT ORDER ERROR: SELL {option_symbol} (All Positions) | Error: {str(e)}")
                            traceback.print_exc()
                    
                    # Get entry option price for initial position
                    entry_option_price_initial = trading_state.get('entry_option_price', None)
                    
                    # Calculate P&L for each position and log individual exits
                    exited_positions = []
                    
                    # Log initial position exit
                    if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                        # Log initial position exit to CSV
                        write_to_signal_csv(
                            action='buyexit',
                            option_price=exit_price,
                            option_contract=option_symbol if option_symbol else "N/A",
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=current_sl,
                            entry_future_price=first_entry_price,
                            entry_option_price=entry_option_price_initial
                        )
                    
                    # Log each pyramiding position exit
                    for idx, pos in enumerate(pyramiding_positions, start=1):
                        entry_future_price = pos.get('entry_price', None)
                        entry_option_price_pyr = pos.get('entry_option_price', None)
                        if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                            # Log pyramiding position exit to CSV
                            action_name = f'pyramiding trade buy ({idx}) exit'
                            write_to_signal_csv(
                                action=action_name,
                                option_price=exit_price,
                                option_contract=pos.get('option_symbol', option_symbol),
                                future_contract=future_symbol,
                                future_price=ha_close,
                                lotsize=lotsize,
                                stop_loss=current_sl,
                                entry_future_price=entry_future_price,
                                entry_option_price=entry_option_price_pyr
                            )
                    
                    # Detailed exit log
                    write_to_order_logs("="*80)
                    write_to_order_logs(f"STOP LOSS EXIT TRIGGERED | {current_position} Position | Symbol: {future_symbol} ({symbol})")
                    write_to_order_logs(f"Exit Reason: Previous candle HA_Low ({prev_ha_low:.2f}) < Stop Loss ({current_sl:.2f})")
                    write_to_order_logs(f"Total Positions to Exit: {pyramiding_count}")
                    write_to_order_logs("-"*80)
                    
                    # Log initial position details
                    if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                        write_to_order_logs(f"Position #1 (Initial):")
                        write_to_order_logs(f"  Option: {option_symbol}")
                        write_to_order_logs(f"  Entry Future Price: {first_entry_price:.2f}")
                        write_to_order_logs(f"  Entry Option Price: {entry_option_price_initial:.2f}")
                        write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                        write_to_order_logs(f"  Quantity: {lotsize}")
                        write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                    
                    # Log pyramiding positions details
                    for idx, pos in enumerate(pyramiding_positions, start=1):
                        entry_future_price = pos.get('entry_price', None)
                        entry_option_price_pyr = pos.get('entry_option_price', None)
                        if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                            write_to_order_logs(f"Position #{idx + 1} (Pyramiding):")
                            write_to_order_logs(f"  Option: {pos.get('option_symbol', option_symbol)}")
                            write_to_order_logs(f"  Entry Future Price: {entry_future_price:.2f}")
                            write_to_order_logs(f"  Entry Option Price: {entry_option_price_pyr:.2f}")
                            write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                            write_to_order_logs(f"  Quantity: {lotsize}")
                            write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                    
                    write_to_order_logs("-"*80)
                    write_to_order_logs(f"SL EXIT RESET CONFIRMED:")
                    write_to_order_logs(f"  pyramiding_count: {pyramiding_count} -> 0")
                    write_to_order_logs(f"  position: {current_position} -> None")
                    write_to_order_logs("="*80)
                    
                    # Reset position and SL fields
                    trading_state['position'] = None
                    trading_state['option_symbol'] = None
                    trading_state['option_exchange'] = None
                    trading_state['option_order_id'] = None
                    trading_state['pyramiding_count'] = 0
                    trading_state['first_entry_price'] = None
                    trading_state['last_pyramiding_price'] = None
                    trading_state['pyramiding_positions'] = []
                    trading_state['initial_sl'] = None
                    trading_state['current_sl'] = None
                    trading_state['entry_prices'] = []
                    trading_state['entry_option_price'] = None
                    save_trading_state()
                    
                    # Continue to check for new entry conditions on same candle (don't return)
            
            # SELL Position SL Exit: Previous candle HA_High > SL
            elif current_position == 'SELL' and current_sl is not None and prev_ha_high is not None:
                if prev_ha_high > current_sl:
                    # SL hit - exit all positions
                    option_symbol = trading_state.get('option_symbol', None)
                    option_exchange = trading_state.get('option_exchange', None)
                    pyramiding_positions = trading_state.get('pyramiding_positions', [])
                    pyramiding_count = trading_state.get('pyramiding_count', 0)
                    first_entry_price = trading_state.get('first_entry_price', None)
                    params = result_dict.get(unique_key, {})
                    lotsize = int(params.get('Lotsize', 1))
                    
                    # Calculate total quantity (initial + all pyramiding positions)
                    total_lotsize = lotsize * pyramiding_count if pyramiding_count > 0 else lotsize
                    
                    # Exit all positions with ONE combined order
                    combined_exit_order_id = None
                    exit_price = None
                    if option_symbol and option_exchange and kite_client:
                        try:
                            quote = get_option_quote(kite_client, option_exchange, option_symbol)
                            option_ltp = quote.get('last_price', None)
                            if option_ltp is not None:
                                option_ltp = float(option_ltp)
                                exit_price = option_ltp
                                # Place ONE combined order for all positions
                                exit_order = place_option_order(
                                    kite=kite_client,
                                    exchange=option_exchange,
                                    option_symbol=option_symbol,
                                    transaction_type="SELL",
                                    quantity=total_lotsize,  # Combined quantity
                                    order_type="LIMIT",
                                    product="NRML",
                                    price=option_ltp
                                )
                                combined_exit_order_id = exit_order.get('order_id', None) if exit_order else None
                                write_to_order_logs(f"SL EXIT ORDER PLACED: SELL {option_symbol} (All Positions Combined) | Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} | Total Quantity: {total_lotsize} | Exit Price: {exit_price:.2f} | SL: {current_sl:.2f} | Prev HA_High: {prev_ha_high:.2f}")
                        except Exception as e:
                            print(f"[SL Exit] Error placing exit order: {str(e)}")
                            write_to_order_logs(f"SL EXIT ORDER ERROR: SELL {option_symbol} (All Positions) | Error: {str(e)}")
                            traceback.print_exc()
                    
                    # Get entry option price for initial position
                    entry_option_price_initial = trading_state.get('entry_option_price', None)
                    
                    # Log initial position exit
                    if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                        # Log initial position exit to CSV
                        write_to_signal_csv(
                            action='sellexit',
                            option_price=exit_price,
                            option_contract=option_symbol if option_symbol else "N/A",
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=current_sl,
                            entry_future_price=first_entry_price,
                            entry_option_price=entry_option_price_initial
                        )
                    
                    # Log each pyramiding position exit
                    for idx, pos in enumerate(pyramiding_positions, start=1):
                        entry_future_price = pos.get('entry_price', None)
                        entry_option_price_pyr = pos.get('entry_option_price', None)
                        if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                            # Log pyramiding position exit to CSV
                            action_name = f'pyramiding trade sell ({idx}) exit'
                            write_to_signal_csv(
                                action=action_name,
                                option_price=exit_price,
                                option_contract=pos.get('option_symbol', option_symbol),
                                future_contract=future_symbol,
                                future_price=ha_close,
                                lotsize=lotsize,
                                stop_loss=current_sl,
                                entry_future_price=entry_future_price,
                                entry_option_price=entry_option_price_pyr
                            )
                    
                    # Detailed exit log
                    write_to_order_logs("="*80)
                    write_to_order_logs(f"STOP LOSS EXIT TRIGGERED | {current_position} Position | Symbol: {future_symbol} ({symbol})")
                    write_to_order_logs(f"Exit Reason: Previous candle HA_High ({prev_ha_high:.2f}) > Stop Loss ({current_sl:.2f})")
                    write_to_order_logs(f"Total Positions to Exit: {pyramiding_count}")
                    write_to_order_logs("-"*80)
                    
                    # Log initial position details
                    if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                        write_to_order_logs(f"Position #1 (Initial):")
                        write_to_order_logs(f"  Option: {option_symbol}")
                        write_to_order_logs(f"  Entry Future Price: {first_entry_price:.2f}")
                        write_to_order_logs(f"  Entry Option Price: {entry_option_price_initial:.2f}")
                        write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                        write_to_order_logs(f"  Quantity: {lotsize}")
                        write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                    
                    # Log pyramiding positions details
                    for idx, pos in enumerate(pyramiding_positions, start=1):
                        entry_future_price = pos.get('entry_price', None)
                        entry_option_price_pyr = pos.get('entry_option_price', None)
                        if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                            write_to_order_logs(f"Position #{idx + 1} (Pyramiding):")
                            write_to_order_logs(f"  Option: {pos.get('option_symbol', option_symbol)}")
                            write_to_order_logs(f"  Entry Future Price: {entry_future_price:.2f}")
                            write_to_order_logs(f"  Entry Option Price: {entry_option_price_pyr:.2f}")
                            write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                            write_to_order_logs(f"  Quantity: {lotsize}")
                            write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                    
                    write_to_order_logs("-"*80)
                    write_to_order_logs(f"SL EXIT RESET CONFIRMED:")
                    write_to_order_logs(f"  pyramiding_count: {pyramiding_count} -> 0")
                    write_to_order_logs(f"  position: {current_position} -> None")
                    write_to_order_logs("="*80)
                    
                    # Reset position and SL fields
                    trading_state['position'] = None
                    trading_state['option_symbol'] = None
                    trading_state['option_exchange'] = None
                    trading_state['option_order_id'] = None
                    trading_state['pyramiding_count'] = 0
                    trading_state['first_entry_price'] = None
                    trading_state['last_pyramiding_price'] = None
                    trading_state['pyramiding_positions'] = []
                    trading_state['initial_sl'] = None
                    trading_state['current_sl'] = None
                    trading_state['entry_prices'] = []
                    trading_state['entry_option_price'] = None
                    save_trading_state()
                    
                    # Continue to check for new entry conditions on same candle (don't return)
        
        # Buy Position Exit: Supertrend FLIPS from green (1) to red (-1)
        # SuperTrend is ONLY used for exit, NOT for entry decisions
        if current_position == 'BUY':
            # Exit ONLY when SuperTrend flips from GREEN (1) to RED (-1)
            if prev_supertrend_trend is not None and prev_supertrend_trend == 1 and supertrend_trend == -1:
                # Exit all pyramiding positions for BUY
                option_symbol = trading_state.get('option_symbol', None)
                option_exchange = trading_state.get('option_exchange', None)
                pyramiding_positions = trading_state.get('pyramiding_positions', [])
                pyramiding_count = trading_state.get('pyramiding_count', 0)
                first_entry_price = trading_state.get('first_entry_price', None)
                params = result_dict.get(unique_key, {})
                lotsize = int(params.get('Lotsize', 1))
                
                # Calculate total quantity (initial + all pyramiding positions)
                total_lotsize = lotsize * pyramiding_count if pyramiding_count > 0 else lotsize
                
                # Exit all positions with ONE combined order
                combined_exit_order_id = None
                exit_price = None
                if option_symbol and option_exchange and kite_client:
                    try:
                        quote = get_option_quote(kite_client, option_exchange, option_symbol)
                        option_ltp = quote.get('last_price', None)
                        if option_ltp is not None:
                            option_ltp = float(option_ltp)
                            exit_price = option_ltp
                            # Place ONE combined order for all positions
                            exit_order = place_option_order(
                                kite=kite_client,
                                exchange=option_exchange,
                                option_symbol=option_symbol,
                                transaction_type="SELL",
                                quantity=total_lotsize,  # Combined quantity
                                order_type="LIMIT",
                                product="NRML",
                                price=option_ltp
                            )
                            # Always log exit order (broker response already printed by place_option_order)
                            combined_exit_order_id = exit_order.get('order_id', None) if exit_order else None
                            write_to_order_logs(f"EXIT ORDER PLACED: SELL {option_symbol} (All Positions Combined) | Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} | Total Quantity: {total_lotsize} | Exit Price: {exit_price:.2f}")
                    except Exception as e:
                        print(f"[Buy Exit] Error placing exit order: {str(e)}")
                        write_to_order_logs(f"EXIT ORDER ERROR: SELL {option_symbol} (All Positions) | Error: {str(e)}")
                        traceback.print_exc()
                
                # Get entry option price for initial position
                entry_option_price_initial = trading_state.get('entry_option_price', None)
                current_sl = trading_state.get('current_sl', None)
                
                # Log initial position exit to CSV
                if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                    write_to_signal_csv(
                        action='buyexit',
                        option_price=exit_price,
                        option_contract=option_symbol if option_symbol else "N/A",
                        future_contract=future_symbol,
                        future_price=ha_close,
                        lotsize=lotsize,
                        stop_loss=current_sl,
                        entry_future_price=first_entry_price,
                        entry_option_price=entry_option_price_initial
                    )
                
                # Log each pyramiding position exit to CSV
                for idx, pos in enumerate(pyramiding_positions, start=1):
                    entry_future_price = pos.get('entry_price', None)
                    entry_option_price_pyr = pos.get('entry_option_price', None)
                    if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                        action_name = f'pyramiding trade buy ({idx}) exit'
                        write_to_signal_csv(
                            action=action_name,
                            option_price=exit_price,
                            option_contract=pos.get('option_symbol', option_symbol),
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=current_sl,
                            entry_future_price=entry_future_price,
                            entry_option_price=entry_option_price_pyr
                        )
                
                # Detailed exit log
                write_to_order_logs("="*80)
                write_to_order_logs(f"PYRAMIDING EXIT TRIGGERED | {current_position} Position | Symbol: {future_symbol} ({symbol})")
                write_to_order_logs(f"Exit Reason: Supertrend flipped from GREEN (1) to RED (-1)")
                write_to_order_logs(f"Total Positions to Exit: {pyramiding_count}")
                write_to_order_logs("-"*80)
                
                # Log initial position exit (P&L calculation for tracking)
                if option_symbol and exit_price is not None and first_entry_price is not None and entry_option_price_initial is not None:
                    initial_entry = first_entry_price
                    initial_pnl = exit_price - entry_option_price_initial if entry_option_price_initial > 0 else 0
                    write_to_order_logs(f"Position #1 (Initial):")
                    write_to_order_logs(f"  Option: {option_symbol}")
                    write_to_order_logs(f"  Entry Future Price: {initial_entry:.2f}")
                    write_to_order_logs(f"  Entry Option Price: {entry_option_price_initial:.2f}")
                    write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                    write_to_order_logs(f"  Quantity: {lotsize}")
                    write_to_order_logs(f"  P&L per unit: {initial_pnl:+.2f}")
                    write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                
                # Log all pyramiding positions (P&L calculation for tracking)
                for idx, pos in enumerate(pyramiding_positions, start=1):
                    entry_future_price = pos.get('entry_price', None)
                    entry_option_price_pyr = pos.get('entry_option_price', None)
                    if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                        pnl = exit_price - entry_option_price_pyr if entry_option_price_pyr > 0 else 0
                        write_to_order_logs(f"Position #{idx + 1} (Pyramiding):")
                        write_to_order_logs(f"  Option: {pos.get('option_symbol', option_symbol)}")
                        write_to_order_logs(f"  Entry Future Price: {entry_future_price:.2f}")
                        write_to_order_logs(f"  Entry Option Price: {entry_option_price_pyr:.2f}")
                        write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                        write_to_order_logs(f"  Quantity: {lotsize}")
                        write_to_order_logs(f"  P&L per unit: {pnl:+.2f}")
                        write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                
                write_to_order_logs("-"*80)
                write_to_order_logs(f"PYRAMIDING RESET CONFIRMED:")
                write_to_order_logs(f"  pyramiding_count: {pyramiding_count} -> 0")
                # Fix format string syntax - move ternary outside f-string
                first_entry_str = f"{first_entry_price:.2f}" if first_entry_price is not None else "N/A"
                write_to_order_logs(f"  first_entry_price: {first_entry_str} -> None")
                last_pyramiding_price_val = trading_state.get('last_pyramiding_price', None)
                last_pyramiding_str = f"{last_pyramiding_price_val:.2f}" if last_pyramiding_price_val is not None else "N/A"
                write_to_order_logs(f"  last_pyramiding_price: {last_pyramiding_str} -> None")
                write_to_order_logs(f"  pyramiding_positions: {len(pyramiding_positions)} positions -> []")
                write_to_order_logs(f"  position: {current_position} -> None")
                write_to_order_logs("="*80)
                
                # Exit buy position and reset pyramiding fields
                trading_state['position'] = None
                trading_state['option_symbol'] = None  # Clear option symbol
                trading_state['option_exchange'] = None  # Clear exchange
                trading_state['option_order_id'] = None  # Clear order ID
                trading_state['pyramiding_count'] = 0
                trading_state['first_entry_price'] = None
                trading_state['last_pyramiding_price'] = None
                trading_state['pyramiding_positions'] = []
                trading_state['initial_sl'] = None
                trading_state['current_sl'] = None
                trading_state['entry_prices'] = []
                save_trading_state()  # Save state after position change
                
                # Continue to check for new entry conditions on same candle (don't return)
        
        # Sell Position Exit: Supertrend FLIPS from red (-1) to green (1)
        # SuperTrend is ONLY used for exit, NOT for entry decisions
        if current_position == 'SELL':
            # Exit ONLY when SuperTrend flips from RED (-1) to GREEN (1)
            if prev_supertrend_trend is not None and prev_supertrend_trend == -1 and supertrend_trend == 1:
                # Exit all pyramiding positions for SELL
                option_symbol = trading_state.get('option_symbol', None)
                option_exchange = trading_state.get('option_exchange', None)
                pyramiding_positions = trading_state.get('pyramiding_positions', [])
                pyramiding_count = trading_state.get('pyramiding_count', 0)
                params = result_dict.get(unique_key, {})
                lotsize = int(params.get('Lotsize', 1))
                
                # Get first_entry_price before exiting
                first_entry_price = trading_state.get('first_entry_price', None)
                
                # Calculate total quantity (initial + all pyramiding positions)
                total_lotsize = lotsize * pyramiding_count if pyramiding_count > 0 else lotsize
                
                # Exit all positions with ONE combined order
                combined_exit_order_id = None
                exit_price = None
                if option_symbol and option_exchange and kite_client:
                    try:
                        quote = get_option_quote(kite_client, option_exchange, option_symbol)
                        option_ltp = quote.get('last_price', None)
                        if option_ltp is not None:
                            option_ltp = float(option_ltp)
                            exit_price = option_ltp
                            # Place ONE combined order for all positions
                            exit_order = place_option_order(
                                kite=kite_client,
                                exchange=option_exchange,
                                option_symbol=option_symbol,
                                transaction_type="SELL",
                                quantity=total_lotsize,  # Combined quantity
                                order_type="LIMIT",
                                product="NRML",
                                price=option_ltp
                            )
                            # Always log exit order (broker response already printed by place_option_order)
                            combined_exit_order_id = exit_order.get('order_id', None) if exit_order else None
                            write_to_order_logs(f"EXIT ORDER PLACED: SELL {option_symbol} (All Positions Combined) | Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} | Total Quantity: {total_lotsize} | Exit Price: {exit_price:.2f}")
                    except Exception as e:
                        print(f"[Sell Exit] Error placing exit order: {str(e)}")
                        write_to_order_logs(f"EXIT ORDER ERROR: SELL {option_symbol} (All Positions) | Error: {str(e)}")
                        traceback.print_exc()
                
                # Get entry option price for initial position
                entry_option_price_initial = trading_state.get('entry_option_price', None)
                current_sl = trading_state.get('current_sl', None)
                
                # Log initial position exit to CSV
                if first_entry_price is not None and exit_price is not None and entry_option_price_initial is not None:
                    write_to_signal_csv(
                        action='sellexit',
                        option_price=exit_price,
                        option_contract=option_symbol if option_symbol else "N/A",
                        future_contract=future_symbol,
                        future_price=ha_close,
                        lotsize=lotsize,
                        stop_loss=current_sl,
                        entry_future_price=first_entry_price,
                        entry_option_price=entry_option_price_initial
                    )
                
                # Log each pyramiding position exit to CSV
                for idx, pos in enumerate(pyramiding_positions, start=1):
                    entry_future_price = pos.get('entry_price', None)
                    entry_option_price_pyr = pos.get('entry_option_price', None)
                    if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                        action_name = f'pyramiding trade sell ({idx}) exit'
                        write_to_signal_csv(
                            action=action_name,
                            option_price=exit_price,
                            option_contract=pos.get('option_symbol', option_symbol),
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=current_sl,
                            entry_future_price=entry_future_price,
                            entry_option_price=entry_option_price_pyr
                        )
                
                # Detailed exit log
                write_to_order_logs("="*80)
                write_to_order_logs(f"PYRAMIDING EXIT TRIGGERED | {current_position} Position | Symbol: {future_symbol} ({symbol})")
                write_to_order_logs(f"Exit Reason: Supertrend flipped from RED (-1) to GREEN (1)")
                write_to_order_logs(f"Total Positions to Exit: {pyramiding_count}")
                write_to_order_logs("-"*80)
                
                # Log initial position exit (P&L calculation for tracking)
                if option_symbol and exit_price is not None and first_entry_price is not None and entry_option_price_initial is not None:
                    initial_entry = first_entry_price
                    initial_pnl = entry_option_price_initial - exit_price if entry_option_price_initial > 0 else 0  # SELL: entry - exit
                    write_to_order_logs(f"Position #1 (Initial):")
                    write_to_order_logs(f"  Option: {option_symbol}")
                    write_to_order_logs(f"  Entry Future Price: {initial_entry:.2f}")
                    write_to_order_logs(f"  Entry Option Price: {entry_option_price_initial:.2f}")
                    write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                    write_to_order_logs(f"  Quantity: {lotsize}")
                    write_to_order_logs(f"  P&L per unit: {initial_pnl:+.2f}")
                    write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                
                # Log all pyramiding positions (P&L calculation for tracking)
                for idx, pos in enumerate(pyramiding_positions, start=1):
                    entry_future_price = pos.get('entry_price', None)
                    entry_option_price_pyr = pos.get('entry_option_price', None)
                    if entry_future_price is not None and exit_price is not None and entry_option_price_pyr is not None:
                        pnl = entry_option_price_pyr - exit_price if entry_option_price_pyr > 0 else 0  # SELL: entry - exit
                        write_to_order_logs(f"Position #{idx + 1} (Pyramiding):")
                        write_to_order_logs(f"  Option: {pos.get('option_symbol', option_symbol)}")
                        write_to_order_logs(f"  Entry Future Price: {entry_future_price:.2f}")
                        write_to_order_logs(f"  Entry Option Price: {entry_option_price_pyr:.2f}")
                        write_to_order_logs(f"  Exit Option Price: {exit_price:.2f}")
                        write_to_order_logs(f"  Quantity: {lotsize}")
                        write_to_order_logs(f"  P&L per unit: {pnl:+.2f}")
                        write_to_order_logs(f"  Order ID: {combined_exit_order_id if combined_exit_order_id else 'N/A'} (Combined Order)")
                
                write_to_order_logs("-"*80)
                write_to_order_logs(f"PYRAMIDING RESET CONFIRMED:")
                write_to_order_logs(f"  pyramiding_count: {pyramiding_count} -> 0")
                # Fix format string syntax - move ternary outside f-string
                first_entry_str = f"{first_entry_price:.2f}" if first_entry_price is not None else "N/A"
                write_to_order_logs(f"  first_entry_price: {first_entry_str} -> None")
                last_pyramiding_price_val = trading_state.get('last_pyramiding_price', None)
                last_pyramiding_str = f"{last_pyramiding_price_val:.2f}" if last_pyramiding_price_val is not None else "N/A"
                write_to_order_logs(f"  last_pyramiding_price: {last_pyramiding_str} -> None")
                write_to_order_logs(f"  pyramiding_positions: {len(pyramiding_positions)} positions -> []")
                write_to_order_logs(f"  position: {current_position} -> None")
                write_to_order_logs("="*80)
                
                # Exit sell position and reset pyramiding fields
                trading_state['position'] = None
                trading_state['option_symbol'] = None  # Clear option symbol
                trading_state['option_exchange'] = None  # Clear exchange
                trading_state['option_order_id'] = None  # Clear order ID
                trading_state['pyramiding_count'] = 0
                trading_state['first_entry_price'] = None
                trading_state['last_pyramiding_price'] = None
                trading_state['pyramiding_positions'] = []
                trading_state['initial_sl'] = None
                trading_state['current_sl'] = None
                trading_state['entry_prices'] = []
                save_trading_state()  # Save state after position change
                
                # Continue to check for new entry conditions on same candle (don't return)
        
        # ========== ARMED CONDITIONS (Can be set even when position exists) ==========
        # ========== ARMED BUY CONDITION ==========
        # Armed Buy: HA candle low < outer KC lower band (KC1_lower - outer band) - evaluated on candle close
        if ha_low < kc1_lower:
            if not trading_state.get('armed_buy', False):
                trading_state['armed_buy'] = True
                log_msg = (
                    f"ARMED BUY | Symbol: {future_symbol} | "
                    f"HA_Low: {ha_low:.2f} < KC1_Lower (Outer): {kc1_lower:.2f} | "
                    f"HA_Close: {ha_close:.2f} | Volume: {volume:.0f}"
                )
                write_to_order_logs(log_msg)
                # Log to CSV
                write_to_signal_csv(
                    action='Armed Buy',
                    future_contract=future_symbol,
                    future_price=ha_close
                )
        
        # ========== ARMED SELL CONDITION ==========
        # Armed Sell: When BUY position exists, arm SELL if high >= outer KC upper band (KC1_upper - outer band) - evaluated on candle close
        if current_position == 'BUY':
            if ha_high >= kc1_upper:
                if not trading_state.get('armed_sell', False):
                    trading_state['armed_sell'] = True
                    log_msg = (
                        f"ARMED SELL | Symbol: {future_symbol} | "
                        f"HA_High: {ha_high:.2f} >= KC1_Upper (Outer): {kc1_upper:.2f} | "
                        f"HA_Close: {ha_close:.2f} | Volume: {volume:.0f} | "
                        f"Note: BUY position active, SELL entry will wait for BUY exit"
                    )
                    write_to_order_logs(log_msg)
                    # Log to CSV
                    write_to_signal_csv(
                        action='Armed Sell',
                        future_contract=future_symbol,
                        future_price=ha_close
                    )
        else:
            # If no position, arm SELL when high >= outer KC upper band (KC1_upper - outer band) - evaluated on candle close
            if ha_high >= kc1_upper:
                if not trading_state.get('armed_sell', False):
                    trading_state['armed_sell'] = True
                    log_msg = (
                        f"ARMED SELL | Symbol: {future_symbol} | "
                        f"HA_High: {ha_high:.2f} >= KC1_Upper (Outer): {kc1_upper:.2f} | "
                        f"HA_Close: {ha_close:.2f} | Volume: {volume:.0f}"
                    )
                    write_to_order_logs(log_msg)
                    # Log to CSV
                    write_to_signal_csv(
                        action='Armed Sell',
                        future_contract=future_symbol,
                        future_price=ha_close
                    )
        
        # ========== ARMED BUY RESET ==========
        # Reset Armed Buy: candle's high > both upper Keltner bands
        if ha_high > kc1_upper and ha_high > kc2_upper:
            if trading_state.get('armed_buy', False):
                trading_state['armed_buy'] = False
                log_msg = (
                    f"ARMED BUY RESET | Symbol: {future_symbol} | "
                    f"HA_High: {ha_high:.2f} > KC1_Upper: {kc1_upper:.2f} AND KC2_Upper: {kc2_upper:.2f}"
                )
                write_to_order_logs(log_msg)
        
        # ========== ARMED SELL RESET ==========
        # Reset Armed Sell: candle's low < both lower Keltner bands
        if ha_low < kc1_lower and ha_low < kc2_lower:
            if trading_state.get('armed_sell', False):
                trading_state['armed_sell'] = False
                log_msg = (
                    f"ARMED SELL RESET | Symbol: {future_symbol} | "
                    f"HA_Low: {ha_low:.2f} < KC1_Lower: {kc1_lower:.2f} AND KC2_Lower: {kc2_lower:.2f}"
                )
                write_to_order_logs(log_msg)
        
        # ========== ENTRY CONDITIONS (Only if no position) ==========
        # If position exists, silently skip entry (no log, no order)
        if current_position is None:
            
            # ========== BUY ENTRY ==========
            # Buy Entry: Armed Buy AND any candle close > inner KC lower band (KC2_lower - inner band) AND volume > VolumeMA
            # AND previous HA candle must be GREEN (prev_ha_close > prev_ha_open)
            if trading_state.get('armed_buy', False):
                if ha_close > kc2_lower:
                    if volume_ma is not None and volume > volume_ma:
                        # Check if previous HA candle is GREEN (ha_close > ha_open)
                        prev_candle_green = False
                        if prev_ha_close is not None and prev_ha_open is not None:
                            prev_candle_green = prev_ha_close > prev_ha_open
                        else:
                            # If previous candle not available, skip entry
                            print(f"[Buy Entry] Previous HA candle data not available, skipping entry")
                            return
                        
                        if not prev_candle_green:
                            print(f"[Buy Entry] Previous HA candle is RED (Close: {prev_ha_close:.2f} <= Open: {prev_ha_open:.2f}), skipping entry")
                            return
                        # Get settings for delta-based option selection
                        params = result_dict.get(unique_key, {})
                        strike_step = int(params.get('StrikeStep', 50))
                        strike_number = int(params.get('StrikeNumber', 6))
                        expiry = params.get('Expiry', '')
                        
                        # Find exchange for future symbol (same logic as historical data)
                        # Use future_symbol directly, not base symbol
                        underlying_exchange = find_exchange_for_symbol(kite_client, future_symbol)
                        
                        option_exchange = "NFO"  # Options are typically on NFO
                        if underlying_exchange == "MCX":
                            option_exchange = "MCX"  # MCX commodities have options on MCX
                        
                        # Get LTP for future symbol (same as we use for historical data)
                        ltp = None
                        if underlying_exchange:
                            ltp = get_ltp(kite_client, underlying_exchange, future_symbol)
                        
                        # If LTP not available, use ha_close as approximation
                        if not ltp:
                            ltp = ha_close
                            print(f"[Buy Entry] LTP not available for {future_symbol}, using HA_Close: {ltp:.2f}")
                        
                        # Normalize strike and create strike list
                        atm = normalize_strike(ltp, strike_step)
                        all_strikes = create_strike_list(atm, strike_step, strike_number)
                        
                        # For BUY: Find max delta CALL option from strikes below ATM (including ATM)
                        # Strikes: [5000, 5050, 5100, 5150, 5200, 5250, 5300] for ATM=5300
                        buy_strikes = [s for s in all_strikes if s <= atm]
                        
                        selected_option = None
                        if kite_client and expiry and buy_strikes:
                            try:
                                # Use 10% risk-free rate for MCX, 6% for NFO
                                risk_free_rate = 0.10 if option_exchange == "MCX" else 0.06
                                selected_option = find_option_with_max_delta(
                                    kite=kite_client,
                                    symbol=symbol,
                                    expiry=expiry,
                                    exchange=option_exchange,
                                    strikes=buy_strikes,
                                    ltp=ltp,
                                    option_type='CE',  # Call option for buy
                                    risk_free_rate=risk_free_rate
                                )
                            except Exception as e:
                                print(f"[Buy Entry] Error finding option with max delta: {str(e)}")
                                traceback.print_exc()
                        
                        # Log delta calculation details before placing order
                        if selected_option:
                            # Log comprehensive delta calculation details
                            delta_log_msg = f"DELTA CALCULATION | Option Type: CE | Underlying: {symbol} | LTP: {selected_option.get('underlying_ltp', ltp):.2f} | ATM Strike: {selected_option.get('atm_strike', 'N/A')} | Time to Expiry: {selected_option.get('time_to_expiry_years', 0):.4f} years | Risk-free Rate: {selected_option.get('risk_free_rate', 0.06)*100:.2f}%"
                            write_to_order_logs(delta_log_msg)
                            
                            # Log all strikes evaluated
                            if 'all_strikes_evaluated' in selected_option:
                                strikes_evaluated = selected_option['all_strikes_evaluated']
                                write_to_order_logs(f"STRIKES EVALUATED: {len(strikes_evaluated)} strikes | Strike List: {buy_strikes}")
                                for strike_data in strikes_evaluated:
                                    # Determine delta source (py_vollib or fallback)
                                    delta_source = "py_vollib" if strike_data.get('iv_source') == "py_vollib" else "fallback"
                                    strike_log = (
                                        f"  Strike: {strike_data['strike']} | Symbol: {strike_data['option_symbol']} | "
                                        f"Delta: {strike_data['delta']:.6f} ({delta_source}) | IV: {strike_data['iv']*100:.2f}% ({strike_data['iv_source']}) | "
                                        f"LTP: {strike_data['ltp']} | {'✓ SELECTED' if strike_data['strike'] == selected_option['strike'] else ''}"
                                    )
                                    write_to_order_logs(strike_log)
                        
                        # Place BUY order for CALL option
                        order_response = None
                        order_error = None
                        if selected_option and kite_client:
                            try:
                                lotsize = int(params.get('Lotsize', 1))
                                # Get option LTP for LIMIT order
                                option_ltp = selected_option.get('ltp_float', None)
                                if option_ltp is None:
                                    # Try to get from quote if not stored
                                    quote = get_option_quote(kite_client, option_exchange, selected_option['option_symbol'])
                                    option_ltp = quote.get('last_price', None)
                                    if option_ltp is not None:
                                        option_ltp = float(option_ltp)
                                
                                order_response = place_option_order(
                                    kite=kite_client,
                                    exchange=option_exchange,
                                    option_symbol=selected_option['option_symbol'],
                                    transaction_type="BUY",
                                    quantity=lotsize,
                                    order_type="LIMIT",
                                    product="NRML",  # Positional
                                    price=option_ltp
                                )
                                
                                # ALWAYS mark position as placed (regardless of broker response)
                                trading_state['option_symbol'] = selected_option['option_symbol']
                                trading_state['option_exchange'] = option_exchange
                                order_id = order_response.get('order_id', None) if order_response else None
                                trading_state['option_order_id'] = order_id
                                
                                if order_response:
                                    write_to_order_logs(f"ORDER PLACED: BUY {selected_option['option_symbol']} | Order ID: {order_id} | Quantity: {lotsize} | Exchange: {option_exchange}")
                                else:
                                    # Order was rejected but position is still marked
                                    order_error = "Order placement failed - check previous ORDER FAILED log for details"
                                    write_to_order_logs(f"ORDER REJECTED BUT POSITION MARKED: BUY {selected_option['option_symbol']} | Quantity: {lotsize} | Exchange: {option_exchange}")
                            except Exception as e:
                                print(f"[Buy Entry] Error placing order: {str(e)}")
                                order_error = f"Exception: {str(e)}"
                                write_to_order_logs(f"ORDER ERROR: BUY {selected_option['option_symbol']} | Exception: {str(e)}")
                                traceback.print_exc()
                        
                        # Always set position when entry conditions are met (regardless of order success)
                        trading_state['position'] = 'BUY'
                        # Store option symbol and exchange (already done above, but ensure it's set)
                        if selected_option:
                            trading_state['option_symbol'] = selected_option['option_symbol']
                            trading_state['option_exchange'] = option_exchange
                        
                        # Initialize pyramiding fields for first entry
                        trading_state['pyramiding_count'] = 1
                        trading_state['first_entry_price'] = ha_close  # Use HA close as entry price (future price)
                        trading_state['last_pyramiding_price'] = ha_close  # Initialize for pyramiding calculation
                        trading_state['pyramiding_positions'] = []  # Only actual pyramiding positions go here, NOT the initial position
                        
                        # Store entry option price for initial position
                        entry_option_price = option_ltp if option_ltp else (selected_option.get('ltp_float', None) if selected_option else None)
                        trading_state['entry_option_price'] = entry_option_price  # Store for P&L calculation
                        
                        # Calculate initial stop loss with ATR adjustment (lowest low of last 5 candles - ATR × Multiplier for BUY)
                        sl_atr_period = int(params.get('SLATR', 14))
                        sl_multiplier = float(params.get('SLMULTIPLIER', 2.0))
                        initial_sl = calculate_initial_sl(df, 'BUY', sl_atr_period, sl_multiplier)
                        if initial_sl is not None:
                            trading_state['initial_sl'] = initial_sl
                            trading_state['current_sl'] = initial_sl  # Initially, current_sl = initial_sl
                            trading_state['entry_prices'] = [ha_close]  # Track all entry prices for averaging
                            write_to_order_logs(f"INITIAL SL CALCULATED | BUY Position | Initial SL: {initial_sl:.2f} (Lowest Low of last 5 candles - ATR {sl_atr_period} × {sl_multiplier})")
                        else:
                            write_to_order_logs(f"WARNING: Could not calculate initial SL for BUY position")
                        
                        # Write to CSV for BUY entry
                        if selected_option:
                            option_price = selected_option.get('ltp_float', None)
                            if option_price is None:
                                option_price = option_ltp  # Use order price if LTP not available
                            write_to_signal_csv(
                                action='buy',
                                option_price=option_price if option_price else 0,
                                option_contract=selected_option['option_symbol'],
                                future_contract=future_symbol,
                                future_price=ha_close,
                                lotsize=lotsize,
                                stop_loss=None  # Empty for entries
                            )
                        
                        # Keep armed_buy = True to allow re-entry after exit if conditions still met
                        save_trading_state()  # Save state after position change
                        
                        # Build log message
                        log_msg = (
                            f"BUY ENTRY | Symbol: {future_symbol} | "
                            f"Price: {ha_close:.2f} | Volume: {volume:.0f} > VolumeMA: {volume_ma:.0f} | "
                            f"HA_Close: {ha_close:.2f} > KC1_Lower: {kc1_lower:.2f} AND KC2_Lower: {kc2_lower:.2f} | "
                            f"HA_High: {ha_high:.2f} | HA_Low: {ha_low:.2f} | "
                            f"KC1_Upper: {kc1_upper:.2f} | KC1_Lower: {kc1_lower:.2f} | "
                            f"KC2_Upper: {kc2_upper:.2f} | KC2_Lower: {kc2_lower:.2f} | "
                            f"Supertrend: {supertrend_trend} | Supertrend_Value: {supertrend:.2f}"
                        )
                        
                        # Add option selection details if available
                        if selected_option:
                            log_msg += (
                                f" | Selected Option: {selected_option['option_symbol']} | "
                                f"Strike: {selected_option['strike']} | Delta: {selected_option['delta']:.4f} | "
                                f"IV: {selected_option['iv']:.4f} | LTP: {selected_option.get('ltp', 'N/A')}"
                            )
                        else:
                            log_msg += " | Option Selection: Failed or not available"
                        
                        # Add order status and rejection reason if order failed
                        if order_response:
                            log_msg += f" | Order Status: PLACED | Order ID: {order_response.get('order_id', 'N/A')}"
                        else:
                            log_msg += f" | Order Status: REJECTED | Rejection Reason: {order_error if order_error else 'Order placement failed'}"
                        
                        write_to_order_logs(log_msg)
            
            # ========== SELL ENTRY ==========
            # Sell Entry: Armed Sell AND current candle close < inner KC upper band (KC2_upper - inner band) AND volume > VolumeMA
            # AND previous HA candle must be RED (prev_ha_close < prev_ha_open)
            if trading_state.get('armed_sell', False):
                # Use current candle close for SELL entry check
                if ha_close < kc2_upper:
                    if volume_ma is not None and volume > volume_ma:
                        # Check if previous HA candle is RED (ha_close < ha_open)
                        prev_candle_red = False
                        if prev_ha_close is not None and prev_ha_open is not None:
                            prev_candle_red = prev_ha_close < prev_ha_open
                        else:
                            # If previous candle not available, skip entry
                            print(f"[Sell Entry] Previous HA candle data not available, skipping entry")
                            return
                        
                        if not prev_candle_red:
                            print(f"[Sell Entry] Previous HA candle is GREEN (Close: {prev_ha_close:.2f} >= Open: {prev_ha_open:.2f}), skipping entry")
                            return
                        # Get settings for delta-based option selection
                        params = result_dict.get(unique_key, {})
                        strike_step = int(params.get('StrikeStep', 50))
                        strike_number = int(params.get('StrikeNumber', 6))
                        expiry = params.get('Expiry', '')
                        
                        # Find exchange for future symbol (same logic as historical data)
                        # Use future_symbol directly, not base symbol
                        underlying_exchange = find_exchange_for_symbol(kite_client, future_symbol)
                        
                        option_exchange = "NFO"  # Options are typically on NFO
                        if underlying_exchange == "MCX":
                            option_exchange = "MCX"  # MCX commodities have options on MCX
                        
                        # Get LTP for future symbol (same as we use for historical data)
                        ltp = None
                        if underlying_exchange:
                            ltp = get_ltp(kite_client, underlying_exchange, future_symbol)
                        
                        # If LTP not available, use ha_close as approximation
                        if not ltp:
                            ltp = ha_close
                            print(f"[Sell Entry] LTP not available for {future_symbol}, using HA_Close: {ltp:.2f}")
                        
                        # Normalize strike and create strike list
                        atm = normalize_strike(ltp, strike_step)
                        all_strikes = create_strike_list(atm, strike_step, strike_number)
                        
                        # For SELL: Find max delta PUT option from strikes above ATM (including ATM)
                        # Strikes: [5300, 5350, 5400, 5450, 5500, 5550, 5600] for ATM=5300
                        sell_strikes = [s for s in all_strikes if s >= atm]
                        
                        selected_option = None
                        if kite_client and expiry and sell_strikes:
                            try:
                                # Use 10% risk-free rate for MCX, 6% for NFO
                                risk_free_rate = 0.10 if option_exchange == "MCX" else 0.06
                                selected_option = find_option_with_max_delta(
                                    kite=kite_client,
                                    symbol=symbol,
                                    expiry=expiry,
                                    exchange=option_exchange,
                                    strikes=sell_strikes,
                                    ltp=ltp,
                                    option_type='PE',  # Put option for sell
                                    risk_free_rate=risk_free_rate
                                )
                            except Exception as e:
                                print(f"[Sell Entry] Error finding option with max delta: {str(e)}")
                                traceback.print_exc()
                        
                        # Log delta calculation details before placing order
                        if selected_option:
                            # Log comprehensive delta calculation details
                            delta_log_msg = f"DELTA CALCULATION | Option Type: PE | Underlying: {symbol} | LTP: {selected_option.get('underlying_ltp', ltp):.2f} | ATM Strike: {selected_option.get('atm_strike', 'N/A')} | Time to Expiry: {selected_option.get('time_to_expiry_years', 0):.4f} years | Risk-free Rate: {selected_option.get('risk_free_rate', 0.06)*100:.2f}%"
                            write_to_order_logs(delta_log_msg)
                            
                            # Log all strikes evaluated
                            if 'all_strikes_evaluated' in selected_option:
                                strikes_evaluated = selected_option['all_strikes_evaluated']
                                write_to_order_logs(f"STRIKES EVALUATED: {len(strikes_evaluated)} strikes | Strike List: {sell_strikes}")
                                for strike_data in strikes_evaluated:
                                    # Determine delta source (py_vollib or fallback)
                                    delta_source = "py_vollib" if strike_data.get('iv_source') == "py_vollib" else "fallback"
                                    strike_log = (
                                        f"  Strike: {strike_data['strike']} | Symbol: {strike_data['option_symbol']} | "
                                        f"Delta: {strike_data['delta']:.6f} ({delta_source}) | IV: {strike_data['iv']*100:.2f}% ({strike_data['iv_source']}) | "
                                        f"LTP: {strike_data['ltp']} | {'✓ SELECTED' if strike_data['strike'] == selected_option['strike'] else ''}"
                                    )
                                    write_to_order_logs(strike_log)
                        
                        # Place BUY order for PUT option
                        order_response = None
                        order_error = None
                        if selected_option and kite_client:
                            try:
                                lotsize = int(params.get('Lotsize', 1))
                                # Get option LTP for LIMIT order
                                option_ltp = selected_option.get('ltp_float', None)
                                if option_ltp is None:
                                    # Try to get from quote if not stored
                                    quote = get_option_quote(kite_client, option_exchange, selected_option['option_symbol'])
                                    option_ltp = quote.get('last_price', None)
                                    if option_ltp is not None:
                                        option_ltp = float(option_ltp)
                                
                                order_response = place_option_order(
                                    kite=kite_client,
                                    exchange=option_exchange,
                                    option_symbol=selected_option['option_symbol'],
                                    transaction_type="BUY",
                                    quantity=lotsize,
                                    order_type="LIMIT",
                                    product="NRML",  # Positional
                                    price=option_ltp
                                )
                                
                                if order_response:
                                    trading_state['option_symbol'] = selected_option['option_symbol']
                                    trading_state['option_exchange'] = option_exchange
                                    trading_state['option_order_id'] = order_response.get('order_id', None)
                                    write_to_order_logs(f"ORDER PLACED: BUY {selected_option['option_symbol']} | Order ID: {order_response.get('order_id', 'N/A')} | Quantity: {lotsize} | Exchange: {option_exchange}")
                                else:
                                    # Order failed - error already logged by place_option_order, but capture for entry log
                                    order_error = "Order placement failed - check previous ORDER FAILED log for details"
                            except Exception as e:
                                print(f"[Sell Entry] Error placing order: {str(e)}")
                                order_error = f"Exception: {str(e)}"
                                write_to_order_logs(f"ORDER ERROR: BUY {selected_option['option_symbol']} | Exception: {str(e)}")
                                traceback.print_exc()
                        
                        # Write to CSV for SELL entry - ALWAYS log regardless of order success/failure
                        csv_option_price = 0
                        csv_option_contract = "N/A"
                        if selected_option:
                            csv_option_contract = selected_option['option_symbol']
                            csv_option_price = selected_option.get('ltp_float', None)
                            if csv_option_price is None:
                                csv_option_price = option_ltp if option_ltp else 0
                        else:
                            # Option selection failed, but still log the entry attempt
                            csv_option_price = option_ltp if option_ltp else 0
                        
                        # Get initial SL for CSV
                        initial_sl = trading_state.get('initial_sl', None)
                        
                        write_to_signal_csv(
                            action='sell',
                            option_price=csv_option_price,
                            option_contract=csv_option_contract,
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=None  # Empty for entries
                        )
                        
                        # Always set position when entry conditions are met (regardless of order success)
                        trading_state['position'] = 'SELL'
                        # Store option symbol and exchange (already done above, but ensure it's set)
                        if selected_option:
                            trading_state['option_symbol'] = selected_option['option_symbol']
                            trading_state['option_exchange'] = option_exchange
                        
                        # Initialize pyramiding fields for first entry
                        trading_state['pyramiding_count'] = 1
                        trading_state['first_entry_price'] = ha_close  # Use HA close as entry price (future price)
                        trading_state['last_pyramiding_price'] = ha_close  # Initialize for pyramiding calculation
                        trading_state['pyramiding_positions'] = []  # Only actual pyramiding positions go here, NOT the initial position
                        
                        # Store entry option price for initial position
                        entry_option_price = option_ltp if option_ltp else (selected_option.get('ltp_float', None) if selected_option else None)
                        trading_state['entry_option_price'] = entry_option_price  # Store for P&L calculation
                        
                        # Calculate initial stop loss with ATR adjustment (highest high of last 5 candles + ATR × Multiplier for SELL)
                        sl_atr_period = int(params.get('SLATR', 14))
                        sl_multiplier = float(params.get('SLMULTIPLIER', 2.0))
                        initial_sl = calculate_initial_sl(df, 'SELL', sl_atr_period, sl_multiplier)
                        if initial_sl is not None:
                            trading_state['initial_sl'] = initial_sl
                            trading_state['current_sl'] = initial_sl  # Initially, current_sl = initial_sl
                            trading_state['entry_prices'] = [ha_close]  # Track all entry prices for averaging
                            write_to_order_logs(f"INITIAL SL CALCULATED | SELL Position | Initial SL: {initial_sl:.2f} (Highest High of last 5 candles + ATR {sl_atr_period} × {sl_multiplier})")
                        else:
                            write_to_order_logs(f"WARNING: Could not calculate initial SL for SELL position")
                        
                        # Keep armed_sell = True to allow re-entry after exit if conditions still met
                        save_trading_state()  # Save state after position change
                        
                        # Build log message
                        log_msg = (
                            f"SELL ENTRY | Symbol: {future_symbol} | "
                            f"Price: {ha_close:.2f} | Volume: {volume:.0f} > VolumeMA: {volume_ma:.0f} | "
                            f"HA_Close: {ha_close:.2f} < KC1_Upper: {kc1_upper:.2f} AND KC2_Upper: {kc2_upper:.2f} | "
                            f"HA_High: {ha_high:.2f} | HA_Low: {ha_low:.2f} | "
                            f"KC1_Upper: {kc1_upper:.2f} | KC1_Lower: {kc1_lower:.2f} | "
                            f"KC2_Upper: {kc2_upper:.2f} | KC2_Lower: {kc2_lower:.2f} | "
                            f"Supertrend: {supertrend_trend} | Supertrend_Value: {supertrend:.2f}"
                        )
                        
                        # Add option selection details if available
                        if selected_option:
                            log_msg += (
                                f" | Selected Option: {selected_option['option_symbol']} | "
                                f"Strike: {selected_option['strike']} | Delta: {selected_option['delta']:.4f} | "
                                f"IV: {selected_option['iv']:.4f} | LTP: {selected_option.get('ltp', 'N/A')}"
                            )
                        else:
                            log_msg += " | Option Selection: Failed or not available"
                        
                        # Add order status and rejection reason if order failed
                        if order_response:
                            log_msg += f" | Order Status: PLACED | Order ID: {order_response.get('order_id', 'N/A')}"
                        else:
                            log_msg += f" | Order Status: REJECTED | Rejection Reason: {order_error if order_error else 'Order placement failed'}"
                        
                        write_to_order_logs(log_msg)
        
        # ========== PYRAMIDING CHECK (When position exists) ==========
        # Check pyramiding conditions on every candle close when position exists
        current_position = trading_state.get('position', None)
        if current_position is not None:
            pyramiding_count = trading_state.get('pyramiding_count', 0)
            first_entry_price = trading_state.get('first_entry_price', None)
            pyramiding_positions = trading_state.get('pyramiding_positions', [])
            
            # Get pyramiding settings
            params = result_dict.get(unique_key, {})
            pyramiding_distance = float(params.get('PyramidingDistance', 0))
            pyramiding_number = int(params.get('PyramidingNumber', 0))
            lotsize = int(params.get('Lotsize', 1))
            
            # Only check if pyramiding is enabled and we haven't reached max positions
            if pyramiding_distance > 0 and pyramiding_number > 0 and first_entry_price is not None:
                max_positions = pyramiding_number + 1  # 1 initial + pyramiding_number additional
                
                if pyramiding_count < max_positions:
                    # Check if price has moved favorably by required distance
                    # Calculate next level from last_pyramiding_price (or first_entry_price if no pyramiding trades yet)
                    should_add_pyramiding = False
                    next_pyramiding_level = None
                    
                    # Get reference price: use last_pyramiding_price if available, otherwise first_entry_price
                    reference_price = trading_state.get('last_pyramiding_price', None)
                    if reference_price is None:
                        reference_price = first_entry_price
                    
                    if reference_price is not None:
                        if current_position == 'BUY':
                            # For BUY: Next level = reference_price + PyramidingDistance
                            next_pyramiding_level = reference_price + pyramiding_distance
                            if ha_close >= next_pyramiding_level:
                                should_add_pyramiding = True
                        elif current_position == 'SELL':
                            # For SELL: Next level = reference_price - PyramidingDistance
                            next_pyramiding_level = reference_price - pyramiding_distance
                            if ha_close <= next_pyramiding_level:
                                should_add_pyramiding = True
                    
                    if should_add_pyramiding:
                        # Get initial option symbol as fallback
                        initial_option_symbol = trading_state.get('option_symbol', None)
                        option_exchange = trading_state.get('option_exchange', None)
                        
                        # Get trading settings for strike calculation
                        strike_step = int(params.get('StrikeStep', 50))
                        strike_number = int(params.get('StrikeNumber', 6))
                        expiry = params.get('Expiry', '')  # Stored as 'Expiry' in result_dict (CSV column is 'Expiery')
                        
                        # Prepare CSV logging variables (will be used regardless of order success/failure)
                        csv_pyramiding_option_price = 0
                        csv_pyramiding_option_contract = "N/A"
                        
                        # Recalculate strike based on current LTP
                        selected_pyramiding_option = None
                        pyramiding_ltp = None
                        
                        if kite_client and option_exchange:
                            try:
                                write_to_order_logs("="*80)
                                write_to_order_logs(f"PYRAMIDING STRIKE SELECTION | {current_position} Position #{pyramiding_count + 1}")
                                write_to_order_logs(f"  Symbol: {future_symbol} ({symbol})")
                                write_to_order_logs(f"  Current HA Close: {ha_close:.2f}")
                                
                                # Find exchange for future symbol
                                underlying_exchange = find_exchange_for_symbol(kite_client, future_symbol)
                                
                                # Get fresh LTP for future symbol
                                ltp = None
                                if underlying_exchange:
                                    ltp = get_ltp(kite_client, underlying_exchange, future_symbol)
                                
                                # If LTP not available, use ha_close as approximation
                                if not ltp:
                                    ltp = ha_close
                                    write_to_order_logs(f"  WARNING: LTP not available for {future_symbol}, using HA_Close: {ltp:.2f}")
                                else:
                                    write_to_order_logs(f"  Fresh LTP: {ltp:.2f}")
                                
                                pyramiding_ltp = ltp
                                
                                # Normalize strike and create strike list
                                atm = normalize_strike(ltp, strike_step)
                                all_strikes = create_strike_list(atm, strike_step, strike_number)
                                
                                write_to_order_logs(f"  Normalized ATM: {atm}")
                                write_to_order_logs(f"  Strike List: {all_strikes}")
                                
                                # Determine option type and filter strikes
                                if current_position == 'BUY':
                                    # For BUY: Find max delta CALL option from strikes below ATM (including ATM)
                                    option_type = 'CE'
                                    filtered_strikes = [s for s in all_strikes if s <= atm]
                                else:  # SELL
                                    # For SELL: Find max delta PUT option from strikes above ATM (including ATM)
                                    option_type = 'PE'
                                    filtered_strikes = [s for s in all_strikes if s >= atm]
                                
                                write_to_order_logs(f"  Option Type: {option_type}")
                                write_to_order_logs(f"  Filtered Strikes: {filtered_strikes}")
                                
                                # Use 10% risk-free rate for MCX, 6% for NFO
                                risk_free_rate = 0.10 if option_exchange == "MCX" else 0.06
                                
                                # Find option with max delta
                                if expiry and filtered_strikes:
                                    selected_pyramiding_option = find_option_with_max_delta(
                                        kite=kite_client,
                                        symbol=symbol,
                                        expiry=expiry,
                                        exchange=option_exchange,
                                        strikes=filtered_strikes,
                                        ltp=ltp,
                                        option_type=option_type,
                                        risk_free_rate=risk_free_rate
                                    )
                                
                                if selected_pyramiding_option:
                                    csv_pyramiding_option_contract = selected_pyramiding_option['option_symbol']
                                    write_to_order_logs(f"  ✓ SELECTED STRIKE: {selected_pyramiding_option['strike']}")
                                    write_to_order_logs(f"  ✓ SELECTED OPTION: {selected_pyramiding_option['option_symbol']}")
                                    write_to_order_logs(f"  ✓ DELTA: {selected_pyramiding_option['delta']:.6f}")
                                    write_to_order_logs(f"  ✓ IV: {selected_pyramiding_option['iv']*100:.2f}% (Source: {selected_pyramiding_option['iv_source']})")
                                    write_to_order_logs(f"  ✓ OPTION LTP: {selected_pyramiding_option.get('ltp', 'N/A')}")
                                    
                                    # Log all strikes evaluated
                                    if 'all_strikes_evaluated' in selected_pyramiding_option:
                                        strikes_evaluated = selected_pyramiding_option['all_strikes_evaluated']
                                        write_to_order_logs(f"  STRIKES EVALUATED: {len(strikes_evaluated)} strikes")
                                        for strike_data in strikes_evaluated:
                                            strike_log = (
                                                f"    Strike: {strike_data['strike']} | Symbol: {strike_data['option_symbol']} | "
                                                f"Delta: {strike_data['delta']:.6f} | IV: {strike_data['iv']*100:.2f}% ({strike_data['iv_source']}) | "
                                                f"LTP: {strike_data['ltp']} | {'✓ SELECTED' if strike_data['strike'] == selected_pyramiding_option['strike'] else ''}"
                                            )
                                            write_to_order_logs(strike_log)
                                else:
                                    # Fallback to initial option symbol
                                    write_to_order_logs(f"  WARNING: Strike selection failed, falling back to initial option: {initial_option_symbol}")
                                    selected_pyramiding_option = None
                                
                                write_to_order_logs("="*80)
                                
                            except Exception as e:
                                print(f"[Pyramiding] Error in strike selection: {str(e)}")
                                write_to_order_logs(f"PYRAMIDING STRIKE SELECTION ERROR | {current_position} Position | Error: {str(e)}")
                                write_to_order_logs(f"  Falling back to initial option: {initial_option_symbol}")
                                traceback.print_exc()
                        
                        # Determine which option symbol to use (newly selected or fallback to initial)
                        final_option_symbol = None
                        if selected_pyramiding_option:
                            final_option_symbol = selected_pyramiding_option['option_symbol']
                        elif initial_option_symbol:
                            final_option_symbol = initial_option_symbol
                            write_to_order_logs(f"PYRAMIDING: Using fallback initial option symbol: {initial_option_symbol}")
                        else:
                            write_to_order_logs(f"PYRAMIDING ERROR: No option symbol available (neither selected nor initial)")
                        
                        # Prepare CSV logging
                        if final_option_symbol:
                            csv_pyramiding_option_contract = final_option_symbol
                        
                        if final_option_symbol and option_exchange and kite_client:
                            try:
                                # Get current option LTP for LIMIT order
                                quote = get_option_quote(kite_client, option_exchange, final_option_symbol)
                                option_ltp = quote.get('last_price', None)
                                if option_ltp is not None:
                                    option_ltp = float(option_ltp)
                                    csv_pyramiding_option_price = option_ltp
                                
                                # Place pyramiding order with newly selected (or fallback) option
                                transaction_type = "BUY"  # Always BUY for pyramiding (we're adding positions)
                                order_response = place_option_order(
                                    kite=kite_client,
                                    exchange=option_exchange,
                                    option_symbol=final_option_symbol,
                                    transaction_type=transaction_type,
                                    quantity=lotsize,
                                    order_type="LIMIT",
                                    product="NRML",  # Positional
                                    price=option_ltp
                                )
                                
                                # ALWAYS mark pyramiding position as placed (regardless of broker response)
                                pyramiding_count += 1
                                trading_state['pyramiding_count'] = pyramiding_count
                                trading_state['last_pyramiding_price'] = ha_close  # Update reference price for next calculation
                                
                                # Add to pyramiding_positions list (always, even if order was rejected)
                                order_id = order_response.get('order_id', None) if order_response else None
                                trading_state['pyramiding_positions'].append({
                                    'option_symbol': final_option_symbol,  # Store the actual option used (newly selected or fallback)
                                    'order_id': order_id,
                                    'entry_price': ha_close,  # Future price (HA_Close)
                                    'entry_option_price': option_ltp if option_ltp else 0  # Option price at entry
                                })
                                
                                # Update entry_prices list and recalculate SL (average of all entry prices)
                                entry_prices = trading_state.get('entry_prices', [])
                                entry_prices.append(ha_close)  # Add new entry price
                                trading_state['entry_prices'] = entry_prices
                                
                                # Calculate new SL as average of all entry prices
                                new_sl = calculate_average_entry_price(entry_prices)
                                if new_sl is not None:
                                    old_sl = trading_state.get('current_sl', None)
                                    trading_state['current_sl'] = new_sl
                                    write_to_order_logs(f"SL UPDATED AFTER PYRAMIDING | Position #{pyramiding_count} | Old SL: {old_sl:.2f if old_sl else 'N/A'} | New SL: {new_sl:.2f} (Average of {len(entry_prices)} entry prices: {entry_prices})")
                                else:
                                    write_to_order_logs(f"WARNING: Could not calculate new SL after pyramiding")
                                
                                # Calculate price movement from first entry
                                price_movement = ha_close - first_entry_price if current_position == 'BUY' else first_entry_price - ha_close
                                price_movement_pct = (price_movement / first_entry_price) * 100 if first_entry_price > 0 else 0
                                
                                # Get reference price used for calculation
                                reference_price = trading_state.get('last_pyramiding_price', first_entry_price)
                                if reference_price == ha_close:
                                    # This is the first pyramiding trade, reference was first_entry_price
                                    reference_price = first_entry_price
                                
                                # Detailed pyramiding entry log
                                write_to_order_logs("="*80)
                                write_to_order_logs(
                                    f"PYRAMIDING TRADE PLACED | {current_position} Position #{pyramiding_count} of {pyramiding_number + 1} max"
                                )
                                write_to_order_logs(f"  Symbol: {future_symbol} ({symbol})")
                                write_to_order_logs(f"  Option: {final_option_symbol}")
                                if selected_pyramiding_option:
                                    write_to_order_logs(f"  Strike Selection: NEW (Strike: {selected_pyramiding_option['strike']}, Delta: {selected_pyramiding_option['delta']:.6f})")
                                else:
                                    write_to_order_logs(f"  Strike Selection: FALLBACK (Initial Option: {initial_option_symbol})")
                                write_to_order_logs(f"  Entry Price: {ha_close:.2f}")
                                write_to_order_logs(f"  First Entry Price: {first_entry_price:.2f}")
                                write_to_order_logs(f"  Reference Price (for calculation): {reference_price:.2f}")
                                write_to_order_logs(f"  Price Movement from First Entry: {price_movement:+.2f} ({price_movement_pct:+.2f}%)")
                                write_to_order_logs(f"  Pyramiding Level: {next_pyramiding_level:.2f} (Calculated from: {reference_price:.2f} {'+' if current_position == 'BUY' else '-'} {pyramiding_distance:.2f})")
                                write_to_order_logs(f"  Pyramiding Distance: {pyramiding_distance:.2f}")
                                write_to_order_logs(f"  Order ID: {order_id if order_id else 'N/A'}")
                                write_to_order_logs(f"  Quantity: {lotsize}")
                                write_to_order_logs(f"  Total Positions Now: {pyramiding_count} / {pyramiding_number + 1}")
                                write_to_order_logs("="*80)
                                save_trading_state()  # Save state after pyramiding addition
                            except Exception as e:
                                print(f"[Pyramiding] Error adding pyramiding position: {str(e)}")
                                write_to_order_logs(
                                    f"PYRAMIDING ERROR | {current_position} Position | "
                                    f"Symbol: {future_symbol} | Error: {str(e)}"
                                )
                                traceback.print_exc()
                        
                        # Write to CSV for pyramiding entry - ALWAYS log regardless of order success/failure
                        # Position number: pyramiding_count is already the position number (1=initial, 2=first pyramiding, etc.)
                        # For action name, we want (1), (2), etc. for pyramiding positions
                        position_num = pyramiding_count  # This is the Nth position (1=initial, 2=first pyramiding, etc.)
                        action_name = f'pyramiding trade buy ({position_num - 1})' if current_position == 'BUY' else f'pyramiding trade sell ({position_num - 1})'
                        current_sl = trading_state.get('current_sl', None)
                        write_to_signal_csv(
                            action=action_name,
                            option_price=csv_pyramiding_option_price,
                            option_contract=csv_pyramiding_option_contract,
                            future_contract=future_symbol,
                            future_price=ha_close,
                            lotsize=lotsize,
                            stop_loss=None,  # Empty for entries
                            position_num=position_num - 1  # For logging: (1), (2), etc.
                        )
        
    except Exception as e:
        error_msg = f"Error in execute_trading_strategy for {symbol}: {str(e)}"
        print(f"[Strategy] {error_msg}")
        write_to_order_logs(f"ERROR: {error_msg}")
        traceback.print_exc()


def display_trading_summary(df: pl.DataFrame, symbol: str, future_symbol: str, trading_state: dict):
    """
    Display a nicely formatted summary of the latest candle data and trading status.
    """
    try:
        if df.height == 0:
            print(f"[Summary] No data available for {future_symbol}")
            return
        
        # Get the latest candle
        latest_candle = df.tail(1)
        row = latest_candle.row(0, named=True)
        
        # Extract values
        date = row.get('date', None)
        ha_close = row.get('ha_close', None)
        ha_open = row.get('ha_open', None)
        ha_high = row.get('ha_high', None)
        ha_low = row.get('ha_low', None)
        volume = row.get('volume', None)
        volume_ma = row.get('VolumeMA', None)
        supertrend = row.get('supertrend', None)
        supertrend_trend = row.get('supertrend_trend', None)
        kc1_upper = row.get('KC1_upper', None)
        kc1_lower = row.get('KC1_lower', None)
        kc1_middle = row.get('KC1_middle', None)
        kc2_upper = row.get('KC2_upper', None)
        kc2_lower = row.get('KC2_lower', None)
        kc2_middle = row.get('KC2_middle', None)
        
        # Get position status
        position = trading_state.get('position', None)
        armed_buy = trading_state.get('armed_buy', False)
        armed_sell = trading_state.get('armed_sell', False)
        
        # Format date
        if date:
            if isinstance(date, str):
                date_str = date
            else:
                date_str = str(date)
        else:
            date_str = "N/A"
        
        # Format supertrend trend
        trend_str = "GREEN (↑)" if supertrend_trend == 1 else "RED (↓)" if supertrend_trend == -1 else "N/A"
        
        # Format position status
        position_str = "BUY" if position == 'BUY' else "SELL" if position == 'SELL' else "NO POSITION"
        armed_status = []
        if armed_buy:
            armed_status.append("ARMED BUY")
        if armed_sell:
            armed_status.append("ARMED SELL")
        armed_str = " | ".join(armed_status) if armed_status else "NONE"
        
        # Print formatted summary
        print("\n" + "="*80)
        print(f"TRADING SUMMARY - {future_symbol} ({symbol})")
        print("="*80)
        print(f"Timestamp: {date_str}")
        print("-"*80)
        print("HEIKIN-ASHI CANDLE:")
        ha_close_str = f"{ha_close:.2f}" if ha_close is not None else "N/A"
        ha_open_str = f"{ha_open:.2f}" if ha_open is not None else "N/A"
        ha_high_str = f"{ha_high:.2f}" if ha_high is not None else "N/A"
        ha_low_str = f"{ha_low:.2f}" if ha_low is not None else "N/A"
        print(f"  Close:  {ha_close_str:>10}")
        print(f"  Open:   {ha_open_str:>10}")
        print(f"  High:   {ha_high_str:>10}")
        print(f"  Low:    {ha_low_str:>10}")
        print("-"*80)
        kc1_upper_str = f"{kc1_upper:.2f}" if kc1_upper is not None else "N/A"
        kc1_middle_str = f"{kc1_middle:.2f}" if kc1_middle is not None else "N/A"
        kc1_lower_str = f"{kc1_lower:.2f}" if kc1_lower is not None else "N/A"
        kc2_upper_str = f"{kc2_upper:.2f}" if kc2_upper is not None else "N/A"
        kc2_middle_str = f"{kc2_middle:.2f}" if kc2_middle is not None else "N/A"
        kc2_lower_str = f"{kc2_lower:.2f}" if kc2_lower is not None else "N/A"
        supertrend_str = f"{supertrend:.2f}" if supertrend is not None else "N/A"
        
        print("KELTNER CHANNEL 1 (KC1):")
        print(f"  Upper:  {kc1_upper_str:>10}")
        print(f"  Middle: {kc1_middle_str:>10}")
        print(f"  Lower:  {kc1_lower_str:>10}")
        print("-"*80)
        print("KELTNER CHANNEL 2 (KC2):")
        print(f"  Upper:  {kc2_upper_str:>10}")
        print(f"  Middle: {kc2_middle_str:>10}")
        print(f"  Lower:  {kc2_lower_str:>10}")
        print("-"*80)
        print("SUPERTREND:")
        print(f"  Value:  {supertrend_str:>10}")
        print(f"  Trend:  {trend_str:>10}")
        print("-"*80)
        print("VOLUME:")
        volume_str = f"{volume:.0f}" if volume is not None else "N/A"
        volume_ma_str = f"{volume_ma:.0f}" if volume_ma is not None else "N/A"
        volume_status = "ABOVE MA" if (volume is not None and volume_ma is not None and volume > volume_ma) else "BELOW MA" if (volume is not None and volume_ma is not None) else "N/A"
        print(f"  Current: {volume_str:>10}")
        print(f"  MA(29):  {volume_ma_str:>10}")
        print(f"  Status:  {volume_status:>10}")
        print("-"*80)
        print("TRADING STATUS:")
        print(f"  Position:     {position_str:>15}")
        print(f"  Armed Status: {armed_str:>15}")
        print("="*80)
        print()
        
    except Exception as e:
        print(f"[Summary] Error displaying summary: {str(e)}")
        traceback.print_exc()


def main_strategy():
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)

        start_time_str = start_date.strftime("%b %d %Y 090000")
        end_time_str = end_date.strftime("%b %d %Y 153000")

        now = datetime.now()
        now_time = now.time()
        
        if not result_dict:
            print("[Strategy] No trading symbols configured. Waiting...")
            return

        # Fetch historical data for each symbol using timeframe from TradeSettings
        for unique_key, params in result_dict.items():
            symbol = params.get('Symbol')
            future_symbol = params.get('FutureSymbol')  # Use constructed future symbol
            timeframe = params.get('Timeframe')
            
            if not future_symbol or not timeframe:
                print(f"[Strategy] Missing future_symbol or timeframe for {unique_key}")
                continue
            
            print(f"\n[Strategy] Processing {symbol} -> {future_symbol} with timeframe {timeframe}")
            
            # Fetch historical data using the constructed future symbol and timeframe from TradeSettings
            if kite_client:
                try:
                    historical_df = fetch_historical_data_for_symbol(
                        kite=kite_client,
                        symbol=future_symbol,  # Use constructed future symbol (e.g., CRUDEOIL25NOVFUT)
                        timeframe=timeframe,
                        days_back=10
                    )
                except Exception as e:
                    error_str = str(e)
                    if "Too many requests" in error_str or "too many requests" in error_str.lower():
                        # Handle too many requests
                        if handle_too_many_requests():
                            # Retry after re-login
                            try:
                                historical_df = fetch_historical_data_for_symbol(
                                    kite=kite_client,
                                    symbol=future_symbol,
                                    timeframe=timeframe,
                                    days_back=10
                                )
                            except Exception as retry_e:
                                print(f"[Strategy] Error after re-login retry: {str(retry_e)}")
                                continue
                        else:
                            print(f"[Strategy] Failed to re-login, skipping this cycle")
                            continue
                    else:
                        raise  # Re-raise other errors
                
                if not historical_df.empty:
                    print(f"[Strategy] Retrieved {len(historical_df)} candles for {future_symbol}")
                    
                    # Get indicator parameters from settings
                    volume_ma = int(params.get('VolumeMa', 20))
                    supertrend_period = int(params.get('SupertrendPeriod', 10))
                    supertrend_mul = float(params.get('SupertrendMul', 3.0))
                    kc1_length = int(params.get('KC1_Length', 20))
                    kc1_mul = float(params.get('KC1_Mul', 2.0))
                    kc1_atr = int(params.get('KC1_ATR', 10))
                    kc2_length = int(params.get('KC2_Length', 20))
                    kc2_mul = float(params.get('KC2_Mul', 2.0))
                    kc2_atr = int(params.get('KC2_ATR', 10))
                    
                    # Process historical data: Convert to Heikin-Ashi and calculate indicators
                    processed_df = process_historical_data(
                        historical_df=historical_df,
                        volume_ma_period=volume_ma,
                        supertrend_period=supertrend_period,
                        supertrend_multiplier=supertrend_mul,
                        kc1_length=kc1_length,
                        kc1_multiplier=kc1_mul,
                        kc1_atr=kc1_atr,
                        kc2_length=kc2_length,
                        kc2_multiplier=kc2_mul,
                        kc2_atr=kc2_atr
                    )
                    
                    # Save to data.csv with retry logic for file locking
                    output_file = "data.csv"
                    print(f"[Strategy] Saving processed data to {output_file}...")
                    max_retries = 3
                    retry_delay = 1
                    for attempt in range(max_retries):
                        try:
                            processed_df.write_csv(output_file)
                            print(f"[Strategy] Data saved successfully to {output_file}")
                            break
                        except OSError as e:
                            if "being used by another process" in str(e) and attempt < max_retries - 1:
                                print(f"[Strategy] File locked, retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                                time.sleep(retry_delay)
                            else:
                                print(f"[Strategy] Warning: Could not save to {output_file}: {str(e)}")
                                print(f"[Strategy] Please close the file if it's open in Excel or another program.")
                                break
                    
                    # Initialize trading state for this symbol if not exists
                    if unique_key not in trading_states:
                        trading_states[unique_key] = {
                            'position': None,  # None, 'BUY', or 'SELL'
                            'armed_buy': False,
                            'armed_sell': False,
                            'exit_on_candle': False,  # Flag to prevent entry on same candle as exit
                            'last_exit_candle_date': None,  # Track the date of the candle where exit occurred
                            'option_symbol': None,  # Store the option symbol for current position (initial entry)
                            'option_exchange': None,  # Store the exchange for current position
                            'option_order_id': None,  # Store the order ID for tracking (initial entry)
                            # Pyramiding fields
                            'pyramiding_count': 0,  # Current number of positions (0, 1, 2, 3...)
                            'first_entry_price': None,  # Price of first entry (reference for all pyramiding levels)
                            'last_pyramiding_price': None,  # Price of last pyramiding entry
                            'pyramiding_positions': [],  # List of dicts: [{'option_symbol': str, 'order_id': str, 'entry_price': float}, ...]
                            # Stop Loss fields
                            'initial_sl': None,  # Initial SL calculated at entry (lowest low/highest high of last 5 candles)
                            'current_sl': None,  # Current SL (updated after pyramiding = average of entry prices)
                            'entry_prices': [],  # List of all entry prices (HA_Close) for averaging: [100, 125, 150, ...]
                            'entry_option_price': None  # Entry option price for initial position (for P&L calculation)
                        }
                    else:
                        # Ensure new fields exist in existing state
                        if 'option_symbol' not in trading_states[unique_key]:
                            trading_states[unique_key]['option_symbol'] = None
                        if 'option_exchange' not in trading_states[unique_key]:
                            trading_states[unique_key]['option_exchange'] = None
                        if 'option_order_id' not in trading_states[unique_key]:
                            trading_states[unique_key]['option_order_id'] = None
                        # Ensure pyramiding fields exist
                        if 'pyramiding_count' not in trading_states[unique_key]:
                            trading_states[unique_key]['pyramiding_count'] = 0
                        if 'first_entry_price' not in trading_states[unique_key]:
                            trading_states[unique_key]['first_entry_price'] = None
                        if 'last_pyramiding_price' not in trading_states[unique_key]:
                            trading_states[unique_key]['last_pyramiding_price'] = None
                        if 'pyramiding_positions' not in trading_states[unique_key]:
                            trading_states[unique_key]['pyramiding_positions'] = []
                        # Ensure SL fields exist
                        if 'initial_sl' not in trading_states[unique_key]:
                            trading_states[unique_key]['initial_sl'] = None
                        if 'current_sl' not in trading_states[unique_key]:
                            trading_states[unique_key]['current_sl'] = None
                        if 'entry_prices' not in trading_states[unique_key]:
                            trading_states[unique_key]['entry_prices'] = []
                        if 'entry_option_price' not in trading_states[unique_key]:
                            trading_states[unique_key]['entry_option_price'] = None
                    
                    # Execute trading strategy on processed data
                    execute_trading_strategy(
                        df=processed_df,
                        unique_key=unique_key,
                        symbol=symbol,
                        future_symbol=future_symbol,
                        trading_state=trading_states[unique_key]
                    )
                    
                    # Display formatted summary of latest candle and trading status
                    display_trading_summary(
                        df=processed_df,
                        symbol=symbol,
                        future_symbol=future_symbol,
                        trading_state=trading_states[unique_key]
                    )
                else:
                    print(f"[Strategy] No historical data retrieved for {future_symbol}")
            else:
                print("[Strategy] Kite client not available")
            
    except Exception as e:
        print("Error in main strategy:", str(e))
        traceback.print_exc()

if __name__ == "__main__":
    try:
        # Step 1: Load trading state from previous session
        print("="*60)
        print("Starting Zerodha Trading Bot")
        print("="*60)
        load_trading_state()
        
        # Step 2: Perform Zerodha login
        kite_client = zerodha_login()
        
        # Step 3: Fetch user settings after successful login
        print("\n[Main] Fetching user settings...")
        get_user_settings()
        print("[Main] User settings loaded successfully!")
        
        # Step 3.5: Initialize/verify signal.csv file
        print("\n[Main] Initializing signal.csv file...")
        initialize_signal_csv()

        # Step 4: Get timeframe for scheduling
        if result_dict:
            # Get timeframe from first symbol (assuming all symbols use same timeframe)
            first_params = next(iter(result_dict.values()))
            timeframe_str = first_params.get('Timeframe', '5minute')
            timeframe_minutes = get_timeframe_minutes(timeframe_str)
            print(f"[Main] Timeframe: {timeframe_str} ({timeframe_minutes} minutes)")
        else:
            timeframe_minutes = 5  # Default to 5 minutes
            print("[Main] No symbols configured, using default 5-minute timeframe")

        # Step 5: Initialize Market Data API (if needed)
        print("\n[Main] Initialization complete. Starting main strategy loop...")
        print("="*60)

        # Main loop with candle-based scheduling
        while True:
            now = datetime.now()
            current_time = now.time()
            
            # Check if it's 9:00 AM (auto-login time)
            if current_time.hour == 9 and current_time.minute == 0 and current_time.second < 5:
                print("\n[Main] 9:00 AM detected - Performing auto-login...")
                kite_client = zerodha_login()
                write_to_order_logs("Auto-login performed at 9:00 AM")
                time.sleep(5)  # Wait a bit to avoid multiple logins
            
            # Calculate next candle time
            next_candle_time = get_next_candle_time(now, timeframe_minutes)
            wait_seconds = (next_candle_time - now).total_seconds()
            
            if wait_seconds > 0:
                print(f"\n[Main] Next execution scheduled at: {next_candle_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[Main] Waiting {wait_seconds:.1f} seconds until next candle...")
                
                # Sleep in small increments to allow for interruption
                sleep_increment = 1.0
                while wait_seconds > 0:
                    if wait_seconds > sleep_increment:
                        time.sleep(sleep_increment)
                        wait_seconds -= sleep_increment
                    else:
                        time.sleep(wait_seconds)
                        break
            
            # Execute strategy
            print(f"\n[Main] Executing strategy at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            main_strategy()
            
            # Save state after each execution
            save_trading_state()
            
    except KeyboardInterrupt:
        print("\n[Main] Program interrupted by user. Saving state and exiting...")
        save_trading_state()
        print("[Main] State saved. Exiting...")
    except Exception as e:
        print(f"\n[Main] Fatal error: {str(e)}")
        save_trading_state()  # Try to save state even on error
        traceback.print_exc()