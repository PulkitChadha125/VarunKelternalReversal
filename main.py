import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import polars as pl
import polars_talib as plta
import time
import traceback
import json
from pathlib import Path
import numpy as np
from scipy.stats import norm
from math import log, sqrt, exp
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
            with open('state.json', 'r', encoding='utf-8') as f:
                state_data = json.load(f)
                if 'trading_states' in state_data:
                    trading_states = state_data['trading_states']
                    print(f"[State] Loaded trading state from state.json (last updated: {state_data.get('last_updated', 'N/A')})")
                    return True
        return False
    except Exception as e:
        print(f"[State] Error loading state: {str(e)}")
        return False


def get_timeframe_minutes(timeframe_str: str) -> int:
    """Convert timeframe string to minutes"""
    timeframe_lower = timeframe_str.lower()
    if 'minute' in timeframe_lower or 'min' in timeframe_lower:
        # Extract number from strings like "5minute", "5min", "15minute"
        import re
        match = re.search(r'(\d+)', timeframe_str)
        if match:
            return int(match.group(1))
    elif 'hour' in timeframe_lower or 'hr' in timeframe_lower:
        import re
        match = re.search(r'(\d+)', timeframe_str)
        if match:
            return int(match.group(1)) * 60
    elif 'day' in timeframe_lower:
        return 1440  # 24 hours
    return 5  # Default to 5 minutes


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
    Calculate Keltner Channel on Heikin-Ashi data.
    
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
        # Calculate ATR on Heikin-Ashi data using polars_talib
        # polars_talib API: pl.col("close").ta.atr(pl.col("high"), pl.col("low"), timeperiod=14)
        try:
            df = df.with_columns([
                pl.col("ha_close").ta.atr(pl.col("ha_high"), pl.col("ha_low"), timeperiod=atr_period).alias(f"ATR_{atr_period}")
            ])
        except (AttributeError, TypeError) as e:
            # Fallback: use Polars native implementation if ta.atr doesn't work
            print(f"[KC] Using fallback ATR calculation: {str(e)}")
            df = df.with_columns([
                (pl.col("ha_high") - pl.col("ha_low")).abs().alias("tr1"),
                (pl.col("ha_high") - pl.col("ha_close").shift(1)).abs().alias("tr2"),
                (pl.col("ha_low") - pl.col("ha_close").shift(1)).abs().alias("tr3")
            ])
            df = df.with_columns([
                pl.max_horizontal([pl.col("tr1"), pl.col("tr2"), pl.col("tr3")]).alias("tr")
            ])
            df = df.with_columns([
                pl.col("tr").rolling_mean(window_size=atr_period).alias(f"ATR_{atr_period}")
            ])
            df = df.drop(["tr1", "tr2", "tr3", "tr"])
        
        atr_col = f"ATR_{atr_period}"
        
        # Calculate EMA for middle line using polars_talib
        # polars_talib API: pl.col("close").ta.ema(timeperiod=30)
        try:
            df = df.with_columns([
                pl.col("ha_close").ta.ema(timeperiod=length).alias(f"EMA_{length}")
            ])
        except (AttributeError, TypeError) as e:
            # Fallback: use Polars native EMA implementation
            print(f"[KC] Using fallback EMA calculation: {str(e)}")
            alpha = 2.0 / (length + 1.0)
            df = df.with_columns([
                pl.col("ha_close").ewm_mean(alpha=alpha, adjust=False).alias(f"EMA_{length}")
            ])
        
        ema_col = f"EMA_{length}"
        
        # Calculate Keltner Channel bands
        df = df.with_columns([
            pl.col(ema_col).alias(f"{prefix}_middle"),
            (pl.col(ema_col) + (pl.col(atr_col) * multiplier)).alias(f"{prefix}_upper"),
            (pl.col(ema_col) - (pl.col(atr_col) * multiplier)).alias(f"{prefix}_lower")
        ])
        
        return df
        
    except Exception as e:
        raise Exception(f"Error calculating Keltner Channel: {str(e)}")


def calculate_supertrend(df: pl.DataFrame, period: int, multiplier: float) -> pl.DataFrame:
    """
    Calculate Supertrend indicator on Heikin-Ashi close price.
    
    Supertrend:
    - Basic Upper Band = (HA_High + HA_Low) / 2 + (multiplier * ATR(period))
    - Basic Lower Band = (HA_High + HA_Low) / 2 - (multiplier * ATR(period))
    - Final Upper Band = Basic Upper Band (if current close > previous Final Upper Band, else previous Final Upper Band)
    - Final Lower Band = Basic Lower Band (if current close < previous Final Lower Band, else previous Final Lower Band)
    - Supertrend = Final Upper Band if close < Final Upper Band, else Final Lower Band
    - Trend = 1 (uptrend) if close > Supertrend, else -1 (downtrend)
    
    Args:
        df: Polars DataFrame with Heikin-Ashi columns
        period: ATR period
        multiplier: Multiplier for ATR
    
    Returns:
        Polars DataFrame with Supertrend columns added
    """
    try:
        # Calculate ATR using polars_talib
        # polars_talib API: pl.col("close").ta.atr(pl.col("high"), pl.col("low"), timeperiod=14)
        try:
            df = df.with_columns([
                pl.col("ha_close").ta.atr(pl.col("ha_high"), pl.col("ha_low"), timeperiod=period).alias(f"ATR_{period}")
            ])
        except (AttributeError, TypeError) as e:
            # Fallback: use Polars native implementation
            print(f"[Supertrend] Using fallback ATR calculation: {str(e)}")
            df = df.with_columns([
                (pl.col("ha_high") - pl.col("ha_low")).abs().alias("tr1"),
                (pl.col("ha_high") - pl.col("ha_close").shift(1)).abs().alias("tr2"),
                (pl.col("ha_low") - pl.col("ha_close").shift(1)).abs().alias("tr3")
            ])
            df = df.with_columns([
                pl.max_horizontal([pl.col("tr1"), pl.col("tr2"), pl.col("tr3")]).alias("tr")
            ])
            df = df.with_columns([
                pl.col("tr").rolling_mean(window_size=period).alias(f"ATR_{period}")
            ])
            df = df.drop(["tr1", "tr2", "tr3", "tr"])
        
        atr_col = f"ATR_{period}"
        
        # Calculate basic bands
        # hl_avg = (High + Low) / 2 (average of high and low prices)
        # basic_upper = hl_avg + (ATR * multiplier) - Upper band based on ATR
        # basic_lower = hl_avg - (ATR * multiplier) - Lower band based on ATR
        hl_avg = (pl.col("ha_high") + pl.col("ha_low")) / 2.0
        df = df.with_columns([
            hl_avg.alias("hl_avg"),  # Average of High and Low
            (hl_avg + (pl.col(atr_col) * multiplier)).alias("basic_upper"),  # Upper band: HL_Avg + (ATR × Multiplier)
            (hl_avg - (pl.col(atr_col) * multiplier)).alias("basic_lower")   # Lower band: HL_Avg - (ATR × Multiplier)
        ])
        
        # Calculate final bands and supertrend using Polars expressions
        # Convert to pandas temporarily for iterative calculation (Supertrend requires previous values)
        # 
        # FINAL BANDS EXPLANATION:
        # - final_upper: The actual upper band used for Supertrend calculation
        #   * If current close > previous final_upper: use basic_upper (band expands)
        #   * Otherwise: keep previous final_upper (band doesn't shrink)
        # - final_lower: The actual lower band used for Supertrend calculation
        #   * If current close < previous final_lower: use basic_lower (band expands)
        #   * Otherwise: keep previous final_lower (band doesn't shrink)
        # 
        # This creates "sticky" bands that only expand, not contract, providing trend continuity
        df_pd = df.to_pandas()
        
        final_upper_list = []
        final_lower_list = []
        supertrend_list = []
        trend_list = []
        
        prev_final_upper = None
        prev_final_lower = None
        
        for i in range(len(df_pd)):
            basic_upper = df_pd["basic_upper"].iloc[i]
            basic_lower = df_pd["basic_lower"].iloc[i]
            ha_close = df_pd["ha_close"].iloc[i]
            
            # Handle None values
            if pd.isna(basic_upper) or pd.isna(basic_lower) or pd.isna(ha_close):
                final_upper_list.append(None)
                final_lower_list.append(None)
                supertrend_list.append(None)
                trend_list.append(None)
                continue
            
            if i == 0:
                # First candle: final bands = basic bands
                final_upper = basic_upper
                final_lower = basic_lower
            else:
                # Final Upper Band: Only expands (increases), never shrinks
                if prev_final_upper is not None and ha_close > prev_final_upper:
                    final_upper = basic_upper  # Price broke above, use new basic_upper
                elif prev_final_upper is not None:
                    final_upper = prev_final_upper  # Keep previous (band doesn't shrink)
                else:
                    final_upper = basic_upper
                
                # Final Lower Band: Only expands (decreases), never shrinks
                if prev_final_lower is not None and ha_close < prev_final_lower:
                    final_lower = basic_lower  # Price broke below, use new basic_lower
                elif prev_final_lower is not None:
                    final_lower = prev_final_lower  # Keep previous (band doesn't shrink)
                else:
                    final_lower = basic_lower
            
            # Supertrend Calculation:
            # - If close < final_upper: Supertrend = final_upper (downtrend, price below upper band)
            # - If close >= final_upper: Supertrend = final_lower (uptrend, price above upper band)
            if final_upper is not None and final_lower is not None:
                if ha_close < final_upper:
                    supertrend = final_upper
                    trend = -1  # Downtrend
                else:
                    supertrend = final_lower
                    trend = 1  # Uptrend
            else:
                supertrend = None
                trend = None
            
            final_upper_list.append(final_upper)
            final_lower_list.append(final_lower)
            supertrend_list.append(supertrend)
            trend_list.append(trend)
            
            prev_final_upper = final_upper
            prev_final_lower = final_lower
        
        # Convert back to Polars and add columns
        df = pl.from_pandas(df_pd)
        df = df.with_columns([
            pl.Series("final_upper", final_upper_list),
            pl.Series("final_lower", final_lower_list),
            pl.Series("supertrend", supertrend_list),
            pl.Series("supertrend_trend", trend_list)
        ])
        
        return df
        
    except Exception as e:
        raise Exception(f"Error calculating Supertrend: {str(e)}")


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
    """
    try:
        # Calculate time to expiration
        expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
        current_date = datetime.now()
        time_to_expiry = (expiry_date - current_date).total_seconds() / (365.25 * 24 * 3600)  # Convert to years
        
        if time_to_expiry <= 0:
            print(f"[Max Delta] Option expired for {symbol}")
            return None
        
        max_delta = -float('inf') if option_type == 'PE' else -1.0
        best_option = None
        
        # Store all strike deltas for printing
        all_strike_data = []
        
        print(f"\n{'='*80}")
        print(f"[DELTA CALCULATION] Finding {option_type} option with max delta")
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
                
                # Get IV from quote (if available)
                iv = quote.get('iv', None)
                iv_source = "API"
                if iv is None:
                    # If IV not available, try to estimate from historical volatility
                    # For now, use a default IV of 20% if not available
                    iv = 0.20
                    iv_source = "Default"
                else:
                    # Convert IV from percentage to decimal if needed
                    if iv > 1:
                        iv = iv / 100.0
                
                # Calculate delta using Black-Scholes model
                # Libraries used: scipy.stats.norm for N(d1), math for log/sqrt
                delta = calculate_delta_black_scholes(
                    S=ltp,
                    K=float(strike),
                    T=time_to_expiry,
                    r=risk_free_rate,
                    sigma=iv,
                    option_type=option_type
                )
                
                option_ltp = quote.get('last_price', 'N/A')
                if option_ltp != 'N/A':
                    option_ltp = f"{option_ltp:.2f}"
                
                # Store strike data
                strike_data = {
                    'strike': strike,
                    'delta': delta,
                    'option_symbol': option_symbol,
                    'iv': iv,
                    'iv_source': iv_source,
                    'ltp': option_ltp,
                    'time_to_expiry': time_to_expiry
                }
                all_strike_data.append(strike_data)
                
                # Determine if this is currently the best
                is_best = False
                if option_type == 'PE':
                    # For puts, delta is negative, so we compare absolute values
                    if abs(delta) > abs(max_delta):
                        max_delta = delta
                        best_option = strike_data
                        is_best = True
                else:  # CE
                    if delta > max_delta:
                        max_delta = delta
                        best_option = strike_data
                        is_best = True
                
                # Print strike data with indicator if it's the best
                status = "✓ SELECTED" if is_best else ""
                print(f"{strike:<10} {option_symbol:<25} {delta:>11.4f}  {iv*100:>8.2f}%  {option_ltp:>12}  {status:<15}")
                
            except Exception as e:
                print(f"{strike:<10} {'ERROR':<25} {'N/A':<12} {'N/A':<10} {'N/A':<12} {str(e)[:15]:<15}")
                print(f"[Max Delta] Error processing strike {strike}: {str(e)}")
                continue
        
        print(f"{'-'*80}")
        
        # Print summary
        if best_option:
            print(f"\n[SELECTED OPTION]")
            print(f"  Strike: {best_option['strike']}")
            print(f"  Option Symbol: {best_option['option_symbol']}")
            print(f"  Delta: {best_option['delta']:.6f} ({'Highest' if option_type == 'CE' else 'Highest Absolute'})")
            print(f"  IV: {best_option['iv']*100:.2f}% (Source: {best_option['iv_source']})")
            print(f"  Option LTP: {best_option['ltp']}")
            print(f"  Time to Expiry: {best_option['time_to_expiry']:.4f} years")
        else:
            print(f"\n[WARNING] No valid option found with max delta")
        
        print(f"{'='*80}\n")
        
        return best_option
        
    except Exception as e:
        print(f"[Max Delta] Error finding option with max delta: {str(e)}")
        traceback.print_exc()
        return None


def execute_trading_strategy(df: pl.DataFrame, unique_key: str, symbol: str, future_symbol: str, trading_state: dict):
    """
    Execute trading strategy based on Heikin-Ashi candles, Keltner Channels, Supertrend, and Volume.
    
    Strategy Rules:
    BUY:
    1. Armed Buy: HA candle low <= both lower Keltner bands (KC1_lower AND KC2_lower)
    2. Buy Entry: Once armed, when HA candle close > both lower Keltner bands AND volume > VolumeMA
    3. Buy Exit: Supertrend changes from green (trend=1) to red (trend=-1)
    4. Armed Buy Reset: Reset ONLY when candle's high > both upper Keltner bands
    5. Re-entry: After exit, if still armed AND entry conditions met, can re-enter immediately
    
    SELL:
    1. Armed Sell: HA candle high >= both upper Keltner bands (KC1_upper AND KC2_upper)
    2. Sell Entry: Once armed, when HA candle close < both upper Keltner bands AND volume > VolumeMA
    3. Sell Exit: Supertrend changes from red (trend=-1) to green (trend=1)
    4. Armed Sell Reset: Reset ONLY when candle's low < both lower Keltner bands
    5. Re-entry: After exit, if still armed AND entry conditions met, can re-enter immediately
    
    Position Management:
    - One position at a time
    - No entry on same candle as exit (prevents immediate re-entry on exit candle)
    - Armed state remains active after entry (allows re-entry after exit if still armed)
    - Armed state resets only when opposite condition occurs
    - All conditions evaluated on candle close
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
        
        # Get previous candle for trend change detection
        if df.height >= 2:
            prev_row = df.tail(2).row(0, named=True)  # Second to last row
            prev_supertrend_trend = prev_row.get('supertrend_trend', None)
        else:
            prev_supertrend_trend = None
        
        # Reset exit_on_candle flag if we're on a new candle (not the exit candle anymore)
        last_exit_candle_date = trading_state.get('last_exit_candle_date', None)
        current_candle_date = date
        
        if trading_state.get('exit_on_candle', False):
            # Check if this is a different candle (compare dates)
            if last_exit_candle_date is not None and current_candle_date is not None:
                if current_candle_date != last_exit_candle_date:
                    # We're on a new candle, reset the flag
                    trading_state['exit_on_candle'] = False
                    trading_state['last_exit_candle_date'] = None
            else:
                # If dates are not available, reset after one execution
                trading_state['exit_on_candle'] = False
        
        # ========== EXIT CONDITIONS (Check first before entry) ==========
        current_position = trading_state.get('position', None)
        
        # Buy Position Exit: Supertrend changes from green (1) to red (-1)
        if current_position == 'BUY':
            if prev_supertrend_trend is not None and prev_supertrend_trend == 1 and supertrend_trend == -1:
                # Exit buy position
                trading_state['position'] = None
                trading_state['exit_on_candle'] = True  # Prevent entry on this candle
                trading_state['last_exit_candle_date'] = current_candle_date  # Track which candle we exited on
                save_trading_state()  # Save state after position change
                
                log_msg = (
                    f"EXIT BUY | Symbol: {future_symbol} | "
                    f"Price: {ha_close:.2f} | Volume: {volume:.0f} | "
                    f"Supertrend: {prev_supertrend_trend} -> {supertrend_trend} | "
                    f"HA_Close: {ha_close:.2f} | HA_High: {ha_high:.2f} | HA_Low: {ha_low:.2f} | "
                    f"KC1_Upper: {kc1_upper:.2f} | KC1_Lower: {kc1_lower:.2f} | "
                    f"KC2_Upper: {kc2_upper:.2f} | KC2_Lower: {kc2_lower:.2f} | "
                    f"Supertrend_Value: {supertrend:.2f}"
                )
                write_to_order_logs(log_msg)
                return  # Exit early, no entry on exit candle
        
        # Sell Position Exit: Supertrend changes from red (-1) to green (1)
        if current_position == 'SELL':
            if prev_supertrend_trend is not None and prev_supertrend_trend == -1 and supertrend_trend == 1:
                # Exit sell position
                trading_state['position'] = None
                trading_state['exit_on_candle'] = True  # Prevent entry on this candle
                trading_state['last_exit_candle_date'] = current_candle_date  # Track which candle we exited on
                save_trading_state()  # Save state after position change
                
                log_msg = (
                    f"EXIT SELL | Symbol: {future_symbol} | "
                    f"Price: {ha_close:.2f} | Volume: {volume:.0f} | "
                    f"Supertrend: {prev_supertrend_trend} -> {supertrend_trend} | "
                    f"HA_Close: {ha_close:.2f} | HA_High: {ha_high:.2f} | HA_Low: {ha_low:.2f} | "
                    f"KC1_Upper: {kc1_upper:.2f} | KC1_Lower: {kc1_lower:.2f} | "
                    f"KC2_Upper: {kc2_upper:.2f} | KC2_Lower: {kc2_lower:.2f} | "
                    f"Supertrend_Value: {supertrend:.2f}"
                )
                write_to_order_logs(log_msg)
                return  # Exit early, no entry on exit candle
        
        # ========== ENTRY CONDITIONS (Only if no position and not on exit candle) ==========
        if current_position is None and not trading_state.get('exit_on_candle', False):
            
            # ========== ARMED BUY CONDITION ==========
            # Armed Buy: HA candle low <= both lower Keltner bands
            if ha_low <= kc1_lower and ha_low <= kc2_lower:
                if not trading_state.get('armed_buy', False):
                    trading_state['armed_buy'] = True
                    log_msg = (
                        f"ARMED BUY | Symbol: {future_symbol} | "
                        f"HA_Low: {ha_low:.2f} <= KC1_Lower: {kc1_lower:.2f} AND KC2_Lower: {kc2_lower:.2f} | "
                        f"HA_Close: {ha_close:.2f} | Volume: {volume:.0f}"
                    )
                    write_to_order_logs(log_msg)
            
            # ========== ARMED SELL CONDITION ==========
            # Armed Sell: HA candle high >= both upper Keltner bands
            if ha_high >= kc1_upper and ha_high >= kc2_upper:
                if not trading_state.get('armed_sell', False):
                    trading_state['armed_sell'] = True
                    log_msg = (
                        f"ARMED SELL | Symbol: {future_symbol} | "
                        f"HA_High: {ha_high:.2f} >= KC1_Upper: {kc1_upper:.2f} AND KC2_Upper: {kc2_upper:.2f} | "
                        f"HA_Close: {ha_close:.2f} | Volume: {volume:.0f}"
                    )
                    write_to_order_logs(log_msg)
            
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
            
            # ========== BUY ENTRY ==========
            # Buy Entry: Armed Buy AND HA close > both lower Keltner bands AND volume > VolumeMA
            if trading_state.get('armed_buy', False):
                if ha_close > kc1_lower and ha_close > kc2_lower:
                    if volume_ma is not None and volume > volume_ma:
                        # Get settings for delta-based option selection
                        params = result_dict.get(unique_key, {})
                        strike_step = int(params.get('StrikeStep', 50))
                        strike_number = int(params.get('StrikeNumber', 6))
                        expiry = params.get('Expiry', '')
                        
                        # Find exchange and get LTP for underlying
                        underlying_exchange = find_exchange_for_symbol(kite_client, symbol)
                        if not underlying_exchange:
                            # Try future symbol
                            underlying_exchange = find_exchange_for_symbol(kite_client, future_symbol)
                        
                        option_exchange = "NFO"  # Options are typically on NFO
                        if underlying_exchange == "MCX":
                            option_exchange = "MCX"  # MCX commodities have options on MCX
                        
                        # Get LTP for underlying
                        ltp = None
                        if underlying_exchange:
                            ltp = get_ltp(kite_client, underlying_exchange, symbol)
                            if not ltp:
                                ltp = get_ltp(kite_client, underlying_exchange, future_symbol)
                        
                        # If LTP not available, use ha_close as approximation
                        if not ltp:
                            ltp = ha_close
                            print(f"[Buy Entry] LTP not available, using HA_Close: {ltp:.2f}")
                        
                        # Normalize strike and create strike list
                        atm = normalize_strike(ltp, strike_step)
                        all_strikes = create_strike_list(atm, strike_step, strike_number)
                        
                        # For BUY: Find max delta CALL option from strikes below ATM (including ATM)
                        # Strikes: [5000, 5050, 5100, 5150, 5200, 5250, 5300] for ATM=5300
                        buy_strikes = [s for s in all_strikes if s <= atm]
                        
                        selected_option = None
                        if kite_client and expiry and buy_strikes:
                            try:
                                selected_option = find_option_with_max_delta(
                                    kite=kite_client,
                                    symbol=symbol,
                                    expiry=expiry,
                                    exchange=option_exchange,
                                    strikes=buy_strikes,
                                    ltp=ltp,
                                    option_type='CE',  # Call option for buy
                                    risk_free_rate=0.06
                                )
                            except Exception as e:
                                print(f"[Buy Entry] Error finding option with max delta: {str(e)}")
                                traceback.print_exc()
                        
                        # Take buy position
                        trading_state['position'] = 'BUY'
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
                        
                        write_to_order_logs(log_msg)
            
            # ========== SELL ENTRY ==========
            # Sell Entry: Armed Sell AND HA close < both upper Keltner bands AND volume > VolumeMA
            if trading_state.get('armed_sell', False):
                if ha_close < kc1_upper and ha_close < kc2_upper:
                    if volume_ma is not None and volume > volume_ma:
                        # Get settings for delta-based option selection
                        params = result_dict.get(unique_key, {})
                        strike_step = int(params.get('StrikeStep', 50))
                        strike_number = int(params.get('StrikeNumber', 6))
                        expiry = params.get('Expiry', '')
                        
                        # Find exchange and get LTP for underlying
                        underlying_exchange = find_exchange_for_symbol(kite_client, symbol)
                        if not underlying_exchange:
                            # Try future symbol
                            underlying_exchange = find_exchange_for_symbol(kite_client, future_symbol)
                        
                        option_exchange = "NFO"  # Options are typically on NFO
                        if underlying_exchange == "MCX":
                            option_exchange = "MCX"  # MCX commodities have options on MCX
                        
                        # Get LTP for underlying
                        ltp = None
                        if underlying_exchange:
                            ltp = get_ltp(kite_client, underlying_exchange, symbol)
                            if not ltp:
                                ltp = get_ltp(kite_client, underlying_exchange, future_symbol)
                        
                        # If LTP not available, use ha_close as approximation
                        if not ltp:
                            ltp = ha_close
                            print(f"[Sell Entry] LTP not available, using HA_Close: {ltp:.2f}")
                        
                        # Normalize strike and create strike list
                        atm = normalize_strike(ltp, strike_step)
                        all_strikes = create_strike_list(atm, strike_step, strike_number)
                        
                        # For SELL: Find max delta PUT option from strikes above ATM (including ATM)
                        # Strikes: [5300, 5350, 5400, 5450, 5500, 5550, 5600] for ATM=5300
                        sell_strikes = [s for s in all_strikes if s >= atm]
                        
                        selected_option = None
                        if kite_client and expiry and sell_strikes:
                            try:
                                selected_option = find_option_with_max_delta(
                                    kite=kite_client,
                                    symbol=symbol,
                                    expiry=expiry,
                                    exchange=option_exchange,
                                    strikes=sell_strikes,
                                    ltp=ltp,
                                    option_type='PE',  # Put option for sell
                                    risk_free_rate=0.06
                                )
                            except Exception as e:
                                print(f"[Sell Entry] Error finding option with max delta: {str(e)}")
                                traceback.print_exc()
                        
                        # Take sell position
                        trading_state['position'] = 'SELL'
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
                        
                        write_to_order_logs(log_msg)
        
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
                            'last_exit_candle_date': None  # Track the date of the candle where exit occurred
                        }
                    
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