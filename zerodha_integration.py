from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pyotp
import pandas as pd


def login(
    api_key: str,
    api_secret: str,
    request_token: Optional[str] = None,
    user_id: Optional[str] = None,
    password: Optional[str] = None,
    totp_secret: Optional[str] = None,
    chromedriver_path: Optional[str] = None,
    headless: bool = True,
) -> Tuple[KiteConnect, str]:
    """
    Complete the Zerodha login by exchanging the request token for an access token.

    Returns a tuple of (KiteConnect client, access_token).

    Usage flow (outside this function):
      1) Direct user to `kite.login_url()` to obtain a request_token via redirect
      2) Call this function with the `request_token`

    Raises an Exception with the underlying SDK error message if the exchange fails.
    """
    if not api_key or not api_secret:
        raise ValueError("api_key and api_secret are required")

    kite = KiteConnect(api_key=api_key)

    # If a request_token is already available, use it directly
    if request_token:
        try:
            print("[Zerodha] Using existing request_token. Exchanging for access_token in 2s...")
            time.sleep(2)
            session_data: Dict[str, str] = kite.generate_session(request_token, api_secret=api_secret)
            access_token: str = session_data["access_token"]
            kite.set_access_token(access_token)
            print("[Zerodha] Access token set. Proceeding in 2s...")
            time.sleep(2)
            return kite, access_token
        except Exception as exc:
            raise Exception(f"Zerodha login failed: {exc}") from exc

    # Otherwise, attempt auto-login via Selenium using credentials and TOTP
    if not (user_id and password and totp_secret):
        raise ValueError(
            "request_token not provided. To auto-login, provide user_id, password, and totp_secret."
        )

    # Setup headless Chrome (prefer Selenium Manager if no path provided)
    try:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # Create driver and open login page
        if chromedriver_path:
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            # Use Selenium Manager to auto-download/manage the correct driver
            driver = webdriver.Chrome(options=options)
        try:
            print("[Zerodha] Opening login page. Waiting 2s...")
            driver.get(kite.login_url())
            time.sleep(2)
            wait = WebDriverWait(driver, 30)

            # Enter user id
            try:
                username_el = wait.until(EC.presence_of_element_located((By.ID, 'userid')))
            except Exception:
                username_el = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="userid"]')))
            username_el.send_keys(user_id)
            print("[Zerodha] Entered user ID. Waiting 2s before entering password...")
            time.sleep(2)

            # Enter password
            try:
                password_el = driver.find_element(By.ID, 'password')
            except Exception:
                password_el = driver.find_element(By.XPATH, '//*[@id="password"]')
            print("password: ",password)
            password_el.send_keys(password)
            print("[Zerodha] Entered password. Waiting 2s before clicking login...")
            time.sleep(2)

            # Click login button
            try:
                login_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            except Exception:
                login_btn = driver.find_element(By.XPATH, '//*[@id="container"]/div/div/div[2]/form/div[4]/button')
            login_btn.click()
            print("[Zerodha] Clicked login. Waiting 2s for 2FA screen...")
            time.sleep(2)

            # Wait and enter TOTP/PIN - target numeric 6-digit field; avoid selecting the password field
            pin_el = None
            last_err = None
            try:
                # Most reliable: 6-digit numeric field
                pin_el = WebDriverWait(driver, 20).until(
                    EC.visibility_of_element_located((By.XPATH, "//input[@type='number' and @maxlength='6']"))
                )
            except Exception as e:
                last_err = e
                # exhaustive fallbacks (explicit 2FA container path first)
                pin_locators = [
                    (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[1]/input'),
                    (By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/div[2]/div/div[2]/form/div[1]/input'),
                    (By.ID, 'pin'),
                    (By.NAME, 'pin'),
                    (By.CSS_SELECTOR, 'input#pin'),
                    (By.CSS_SELECTOR, "input[placeholder='••••••']"),
                ]
                for by, sel in pin_locators:
                    try:
                        candidate = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((by, sel)))
                        # Avoid password field
                        cid = (candidate.get_attribute('id') or '').lower()
                        cname = (candidate.get_attribute('name') or '').lower()
                        itype = (candidate.get_attribute('type') or '').lower()
                        if cid == 'password' or cname == 'password':
                            continue
                        pin_el = candidate
                        if pin_el:
                            break
                    except Exception as e2:
                        last_err = e2
                        continue
            if pin_el is None:
                try:
                    driver.save_screenshot("zerodha_login_no_pin.png")
                    Path("zerodha_login_no_pin.html").write_text(driver.page_source or "", encoding="utf-8")
                except Exception:
                    pass
                raise Exception(f"Unable to locate TOTP/PIN field. Last error: {last_err}")
            # Some UIs have 1 input; others split into 6 boxes. Handle both.
            totp = pyotp.TOTP(totp_secret)
            token = totp.now()
            print("[Zerodha] Ready to enter TOTP. Waiting 2s so you can observe...")
            time.sleep(2)
            try:
                # Try multiple inputs first
                # Focus the element first (helps some numeric inputs)
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pin_el)
                    pin_el.click()
                except Exception:
                    pass

                otp_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
                otp_inputs = [el for el in otp_inputs if el.is_displayed() and el.is_enabled()]
                if len(otp_inputs) >= 4 and len(token) >= 4:
                    for i, ch in enumerate(token[:len(otp_inputs)]):
                        otp_inputs[i].clear()
                        otp_inputs[i].send_keys(ch)
                    # Press Enter on last box
                    otp_inputs[min(len(otp_inputs)-1, len(token)-1)].send_keys(Keys.ENTER)
                else:
                    try:
                        pin_el.clear()
                    except Exception:
                        pass
                    pin_el.send_keys(token)
                    pin_el.send_keys(Keys.ENTER)
            except Exception:
                try:
                    pin_el.clear()
                except Exception:
                    pass
                pin_el.send_keys(token)
                pin_el.send_keys(Keys.ENTER)
            print("[Zerodha] Entered TOTP. Waiting 2s before continuing...")
            time.sleep(2)

            # If there's a submit/continue button after PIN, click it
            cont_locators = [
                (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[2]/button'),  # explicit continue
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form//button'),
                (By.XPATH, '//form//button[@type="submit"]'),
            ]
            for by, sel in cont_locators:
                try:
                    cont_btn = driver.find_element(by, sel)
                    cont_btn.click()
                    break
                except Exception:
                    continue
            print("[Zerodha] Clicked continue. Waiting 2s for redirect...")
            time.sleep(2)

            # Wait for redirect URL containing request_token (retry once if needed)
            try:
                wait.until(lambda d: "request_token=" in d.current_url)
            except Exception:
                # Retry once with a fresh TOTP in case the first expired
                try:
                    pin_el.clear()
                except Exception:
                    pass
                # Re-locate pin field if needed (prefer numeric 6-digit field; avoid password)
                try:
                    pin_el = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.XPATH, "//input[@type='number' and @maxlength='6']"))
                    )
                except Exception:
                    try:
                        pin_el = WebDriverWait(driver, 10).until(
                            EC.visibility_of_element_located((By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[1]/input'))
                        )
                    except Exception:
                        try:
                            pin_el = driver.find_element(By.ID, 'pin')
                        except Exception:
                            try:
                                pin_el = driver.find_element(By.CSS_SELECTOR, "input[placeholder='••••••']")
                            except Exception:
                                pin_el = driver.find_element(By.XPATH, "//input[@type='password']")
                token = pyotp.TOTP(totp_secret).now()
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pin_el)
                    pin_el.click()
                except Exception:
                    pass
                pin_el.send_keys(token)
                for by, sel in cont_locators:
                    try:
                        cont_btn = driver.find_element(by, sel)
                        cont_btn.click()
                        break
                    except Exception:
                        continue
                wait.until(lambda d: "request_token=" in d.current_url)
                print("[Zerodha] Retried TOTP. Waiting 2s for redirect...")
                time.sleep(2)

            url = driver.current_url
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            req_token = (query_params.get("request_token") or [None])[0]
            if not req_token:
                # Persist debug artifacts for diagnosis
                try:
                    driver.save_screenshot("zerodha_login_debug.png")
                    Path("zerodha_login_debug.html").write_text(driver.page_source or "", encoding="utf-8")
                except Exception:
                    pass
                raise Exception("Failed to obtain request_token from redirected URL")

            # Save request_token
            Path("request_token.txt").write_text(req_token, encoding="utf-8")
            print("[Zerodha] Captured request_token. Waiting 2s before closing browser...")
            time.sleep(2)

        finally:
            try:
                driver.quit()
            except Exception:
                pass

        # Exchange request_token for access_token
        try:
            print("[Zerodha] Exchanging request_token for access_token in 2s...")
            time.sleep(2)
            session_data: Dict[str, str] = kite.generate_session(req_token, api_secret=api_secret)
            access_token: str = session_data["access_token"]
            kite.set_access_token(access_token)

            # Persist access token
            Path("access_token.txt").write_text(access_token, encoding="utf-8")
            print("[Zerodha] Access token saved. Waiting 2s before returning...")
            time.sleep(2)

            return kite, access_token
        except Exception as exc:
            raise Exception(f"Zerodha login (session exchange) failed: {exc}") from exc
    finally:
        pass


def fetch_completed_orders(kite: KiteConnect) -> List[Dict]:
    """
    Fetch and return all orders with status marked as completed.

    The Zerodha API uses status value 'COMPLETE' for fully executed orders.
    Returns a list of order dictionaries as provided by the SDK.
    """
    if kite is None:
        raise ValueError("kite client is required")

    try:
        all_orders: List[Dict] = kite.orders()
    except Exception as exc:
        raise Exception(f"Failed to fetch orders: {exc}") from exc

    completed = [order for order in all_orders if str(order.get("status", "")).upper() == "COMPLETE"]
    return completed


def normalize_timeframe(timeframe: str) -> str:
    """
    Normalize timeframe string to Zerodha API format.
    
    Zerodha supports: minute, 3minute, 5minute, 15minute, 30minute, 60minute, day, week, month
    
    Args:
        timeframe: Timeframe string (e.g., "5minute", "5min", "5m", "day", "1day", etc.)
    
    Returns:
        Normalized timeframe string for Zerodha API
    """
    timeframe_lower = timeframe.lower().strip()
    
    # Mapping common variations to Zerodha format
    timeframe_map = {
        '1minute': 'minute',
        '1min': 'minute',
        '1m': 'minute',
        'minute': 'minute',
        'min': 'minute',
        'm': 'minute',
        
        '3minute': '3minute',
        '3min': '3minute',
        '3m': '3minute',
        
        '5minute': '5minute',
        '5min': '5minute',
        '5m': '5minute',
        
        '15minute': '15minute',
        '15min': '15minute',
        '15m': '15minute',
        
        '30minute': '30minute',
        '30min': '30minute',
        '30m': '30minute',
        
        '60minute': '60minute',
        '60min': '60minute',
        '60m': '60minute',
        '1hour': '60minute',
        '1h': '60minute',
        'hour': '60minute',
        'h': '60minute',
        
        '1day': 'day',
        'day': 'day',
        'd': 'day',
        'daily': 'day',
        
        'week': 'week',
        'w': 'week',
        'weekly': 'week',
        
        'month': 'month',
        'mo': 'month',
        'monthly': 'month',
    }
    
    # Check if exact match exists
    if timeframe_lower in timeframe_map:
        return timeframe_map[timeframe_lower]
    
    # If already in correct format, return as is
    valid_formats = ['minute', '3minute', '5minute', '15minute', '30minute', '60minute', 'day', 'week', 'month']
    if timeframe_lower in valid_formats:
        return timeframe_lower
    
    # Default to minute if not recognized
    print(f"[Warning] Unrecognized timeframe '{timeframe}', defaulting to 'minute'")
    return 'minute'


def get_historical_data(
    kite: KiteConnect,
    instrument_token: int,
    timeframe: str,
    from_date: datetime,
    to_date: datetime,
    continuous: bool = False,
    oi: bool = False
) -> pd.DataFrame:
    """
    Fetch historical data from Zerodha Kite API.
    
    Args:
        kite: KiteConnect client instance
        instrument_token: Instrument token (integer) for the trading symbol
        timeframe: Timeframe string (e.g., "5minute", "day", "15minute")
                   Will be normalized to Zerodha format
        from_date: Start date (datetime object)
        to_date: End date (datetime object)
        continuous: Boolean flag for continuous futures data (default: False)
        oi: Boolean flag to include OI (Open Interest) data (default: False)
    
    Returns:
        pandas DataFrame with columns: date, open, high, low, close, volume, oi (if oi=True)
    
    Raises:
        Exception: If API call fails or invalid parameters provided
    """
    if kite is None:
        raise ValueError("kite client is required")
    
    if instrument_token is None or not isinstance(instrument_token, int):
        raise ValueError("instrument_token must be a valid integer")
    
    if from_date >= to_date:
        raise ValueError("from_date must be before to_date")
    
    # Normalize timeframe
    normalized_timeframe = normalize_timeframe(timeframe)
    
    try:
        print(f"[Historical Data] Fetching data for instrument {instrument_token}, "
              f"timeframe: {normalized_timeframe}, from {from_date.date()} to {to_date.date()}")
        
        # Convert datetime to date for API call
        from_date_str = from_date.date()
        to_date_str = to_date.date()
        
        # Fetch historical data
        historical_data = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date_str,
            to_date=to_date_str,
            interval=normalized_timeframe,
            continuous=continuous,
            oi=oi
        )
        
        if not historical_data:
            print(f"[Historical Data] No data returned for instrument {instrument_token}")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(historical_data)
        
        # Rename columns to standard format (Zerodha returns: date, open, high, low, close, volume, oi)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            # Remove timezone if present to avoid Polars parsing issues
            if df['date'].dtype.tz is not None:
                df['date'] = df['date'].dt.tz_localize(None)
            df = df.sort_values('date').reset_index(drop=True)
        
        print(f"[Historical Data] Retrieved {len(df)} candles")
        return df
        
    except Exception as exc:
        raise Exception(f"Failed to fetch historical data: {exc}") from exc


def get_instrument_token(kite: KiteConnect, exchange: str, symbol: str) -> Optional[int]:
    """
    Get instrument token for a given exchange and symbol.
    
    Args:
        kite: KiteConnect client instance
        exchange: Exchange name (e.g., "NSE", "BSE", "NFO", "MCX", "CDS", "BFO")
        symbol: Trading symbol (e.g., "RELIANCE", "NIFTY", "CRUDEOIL")
    
    Returns:
        Instrument token (integer) if found, None otherwise
    """
    if kite is None:
        raise ValueError("kite client is required")
    
    try:
        # Get all instruments
        instruments = kite.instruments(exchange)
        
        # Search for matching symbol
        for instrument in instruments:
            if instrument.get('tradingsymbol') == symbol.upper():
                return instrument.get('instrument_token')
        
        print(f"[Instrument] Symbol '{symbol}' not found in exchange '{exchange}'")
        return None
        
    except Exception as exc:
        raise Exception(f"Failed to get instrument token: {exc}") from exc


def get_instruments_by_symbol(kite: KiteConnect, symbol: str, exchange: Optional[str] = None) -> List[Dict]:
    """
    Get all instruments matching a symbol across exchanges or in a specific exchange.
    
    Args:
        kite: KiteConnect client instance
        symbol: Trading symbol to search for
        exchange: Optional exchange name to limit search (e.g., "NSE", "MCX")
    
    Returns:
        List of instrument dictionaries matching the symbol
    """
    if kite is None:
        raise ValueError("kite client is required")
    
    try:
        if exchange:
            instruments = kite.instruments(exchange)
        else:
            # Search across common exchanges
            exchanges = ["NSE", "BSE", "NFO", "MCX", "CDS", "BFO"]
            instruments = []
            for exch in exchanges:
                try:
                    exch_instruments = kite.instruments(exch)
                    instruments.extend(exch_instruments)
                except Exception:
                    continue
        
        # Filter by symbol
        matching = [inst for inst in instruments if inst.get('tradingsymbol', '').upper() == symbol.upper()]
        
        return matching
        
    except Exception as exc:
        raise Exception(f"Failed to search instruments: {exc}") from exc


