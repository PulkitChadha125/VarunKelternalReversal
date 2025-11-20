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

    # Setup Chrome (visible browser for debugging)
    try:
        options = Options()
        # Always show browser so user can see what's happening
        # if headless:
        #     options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")  # Maximize window for better visibility

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

            # Wait for TOTP/PIN field to appear and enter TOTP using Selenium
            totp = pyotp.TOTP(totp_secret)
            token = str(totp.now()).zfill(6)
            print(f"[Zerodha] Ready to enter TOTP: {token}. Waiting 5s for page stability (browser is visible - you can watch)...")
            time.sleep(5)  # Longer wait so user can see what's happening
            
            # Helper function to find PIN element with retry
            def find_pin_element(max_wait=10):
                """Find TOTP/PIN input element using multiple locators"""
                pin_locators = [
                    (By.XPATH, "//input[@type='number' and @maxlength='6']"),
                    (By.XPATH, "//input[@type='text' and @maxlength='6']"),
                    (By.ID, 'pin'),
                    (By.NAME, 'pin'),
                    (By.CSS_SELECTOR, 'input#pin'),
                    (By.CSS_SELECTOR, "input[placeholder*='•••']"),
                    (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[1]/input'),
                ]
                
                for by, selector in pin_locators:
                    try:
                        element = WebDriverWait(driver, max_wait).until(
                            EC.presence_of_element_located((by, selector))
                        )
                        # Verify it's visible and not the password field
                        if element.is_displayed():
                            el_id = (element.get_attribute('id') or '').lower()
                            el_name = (element.get_attribute('name') or '').lower()
                            if el_id != 'password' and el_name != 'password':
                                return element
                    except Exception:
                        continue
                return None
            
            # Function to enter TOTP with Selenium (with retry on stale elements)
            def enter_totp_selenium(max_retries=5):
                """Enter TOTP using Selenium with retry logic"""
                for attempt in range(max_retries):
                    try:
                        # Check if we're already on the success page (redirect already happened)
                        current_url = driver.current_url
                        if "request_token=" in current_url:
                            print(f"[Zerodha] Already redirected! Found request_token in URL. Skipping TOTP entry.")
                            return True
                        
                        print(f"[Zerodha] TOTP entry attempt {attempt + 1}/{max_retries}...")
                        time.sleep(2)  # Wait between attempts
                        
                        # Check for multiple OTP input boxes first
                        try:
                            otp_inputs = WebDriverWait(driver, 5).until(
                                lambda d: [el for el in d.find_elements(By.CSS_SELECTOR, 'input[type="password"]') 
                                          if el.is_displayed() and el.is_enabled() and 
                                          el.get_attribute('id') != 'password' and 
                                          el.get_attribute('name') != 'password']
                            )
                            
                            if len(otp_inputs) >= 4 and len(token) >= 4:
                                print(f"[Zerodha] Detected {len(otp_inputs)} separate OTP input boxes")
                                for i, ch in enumerate(token[:min(len(otp_inputs), len(token))]):
                                    # Re-locate inputs fresh for each character
                                    fresh_inputs = WebDriverWait(driver, 3).until(
                                        lambda d: [el for el in d.find_elements(By.CSS_SELECTOR, 'input[type="password"]') 
                                                  if el.is_displayed() and el.is_enabled()]
                                    )
                                    if i < len(fresh_inputs):
                                        fresh_inputs[i].clear()
                                        fresh_inputs[i].send_keys(ch)
                                        time.sleep(0.3)  # Small delay between inputs
                                
                                # Press Enter on last box
                                final_inputs = WebDriverWait(driver, 3).until(
                                    lambda d: [el for el in d.find_elements(By.CSS_SELECTOR, 'input[type="password"]') 
                                              if el.is_displayed() and el.is_enabled()]
                                )
                                if final_inputs:
                                    last_idx = min(len(final_inputs)-1, len(token)-1)
                                    final_inputs[last_idx].send_keys(Keys.ENTER)
                                print("[Zerodha] TOTP entered into multiple input boxes")
                                
                                # Wait a bit and check if redirect happened
                                time.sleep(2)
                                if "request_token=" in driver.current_url:
                                    print("[Zerodha] Redirect detected after TOTP entry!")
                                    return True
                                return True
                        except Exception:
                            # Not multiple boxes, try single input
                            pass
                        
                        # Single input field approach
                        print("[Zerodha] Trying single input field for TOTP...")
                        pin_el = find_pin_element(max_wait=5)
                        
                        if pin_el is None:
                            # Check if redirect already happened while we were looking
                            if "request_token=" in driver.current_url:
                                print("[Zerodha] Redirect detected! No need to enter TOTP.")
                                return True
                            raise Exception("Could not locate TOTP/PIN input field")
                        
                        # Clear and enter TOTP
                        try:
                            pin_el.clear()
                        except Exception:
                            pass
                        
                        pin_el.send_keys(token)
                        print(f"[Zerodha] Entered TOTP: {token}")
                        time.sleep(1)
                        
                        # Press Enter
                        pin_el.send_keys(Keys.ENTER)
                        print("[Zerodha] Pressed Enter after TOTP entry")
                        
                        # Wait a bit and check if redirect happened
                        time.sleep(2)
                        if "request_token=" in driver.current_url:
                            print("[Zerodha] Redirect detected after TOTP entry!")
                            return True
                        
                        return True
                        
                    except Exception as e:
                        error_msg = str(e)
                        
                        # Check if redirect happened despite the error
                        if "request_token=" in driver.current_url:
                            print("[Zerodha] Redirect detected despite error! Continuing...")
                            return True
                        
                        if "stale element" in error_msg.lower():
                            print(f"[Zerodha] Stale element detected, will retry...")
                        else:
                            print(f"[Zerodha] Error: {error_msg[:100]}")
                        
                        if attempt < max_retries - 1:
                            print(f"[Zerodha] Retrying in 3s...")
                            time.sleep(3)
                            continue
                        else:
                            raise Exception(f"Failed after {max_retries} attempts. Last error: {error_msg}")
            
            # Enter TOTP
            try:
                enter_totp_selenium()
            except Exception as e:
                # Check if redirect happened despite the exception
                if "request_token=" in driver.current_url:
                    print("[Zerodha] Redirect detected! Continuing despite exception.")
                else:
                    print(f"[Zerodha] TOTP entry failed: {e}")
                    print("[Zerodha] Browser will remain open for 30s so you can manually enter TOTP if needed...")
                    time.sleep(30)  # Give user time to manually enter if needed
                    raise
            
            # Check if we're already on the success page
            if "request_token=" in driver.current_url:
                print("[Zerodha] Already on success page! Skipping continue button click.")
            else:
                print("[Zerodha] Entered TOTP. Waiting 2s before checking for continue button...")
                time.sleep(2)

                # If there's a submit/continue button after PIN, click it
                cont_locators = [
                    (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[2]/button'),  # explicit continue
                    (By.CSS_SELECTOR, 'button[type="submit"]'),
                    (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form//button'),
                    (By.XPATH, '//form//button[@type="submit"]'),
                ]
                clicked = False
                for by, sel in cont_locators:
                    try:
                        cont_btn = driver.find_element(by, sel)
                        cont_btn.click()
                        clicked = True
                        break
                    except Exception:
                        continue
                
                # JavaScript fallback for button click (more reliable on servers)
                if not clicked:
                    try:
                        result = driver.execute_script("""
                            var btn = document.querySelector('button[type="submit"]') || 
                                     document.querySelector('#container button') ||
                                     document.querySelector('form button');
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                                return true;
                            }
                            return false;
                        """)
                        if result:
                            clicked = True
                            print("[Zerodha] Clicked continue button via JavaScript")
                    except Exception:
                        pass
                
                if clicked:
                    print("[Zerodha] Clicked continue. Waiting 2s for redirect...")
                else:
                    print("[Zerodha] No continue button found, waiting 2s for redirect...")
                time.sleep(2)

            # Define continue button locators (used in retry section)
            cont_locators = [
                (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form/div[2]/button'),  # explicit continue
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.XPATH, '//*[@id="container"]/div[2]/div/div[2]/form//button'),
                (By.XPATH, '//form//button[@type="submit"]'),
            ]
            
            # Wait for redirect URL containing request_token (retry once if needed)
            # First check if we're already on the success page
            if "request_token=" in driver.current_url:
                print("[Zerodha] Already on success page! No need to wait for redirect.")
            else:
                try:
                    wait.until(lambda d: "request_token=" in d.current_url)
                    print("[Zerodha] Redirect detected!")
                except Exception:
                    # Check one more time before retrying
                    if "request_token=" in driver.current_url:
                        print("[Zerodha] Redirect detected on second check!")
                    else:
                        # Retry once with a fresh TOTP in case the first expired
                        print("[Zerodha] No redirect detected, retrying TOTP entry with fresh token...")
                        token = str(pyotp.TOTP(totp_secret).now()).zfill(6)
                        print(f"[Zerodha] New TOTP: {token}")
                        try:
                            # Check URL again before retrying
                            if "request_token=" in driver.current_url:
                                print("[Zerodha] Redirect detected before retry! Skipping...")
                            else:
                                # Try to find and enter TOTP using Selenium
                                pin_el = find_pin_element(max_wait=5)
                                if pin_el:
                                    try:
                                        pin_el.clear()
                                    except Exception:
                                        pass
                                    pin_el.send_keys(token)
                                    time.sleep(1)
                                    pin_el.send_keys(Keys.ENTER)
                                    print("[Zerodha] Retried TOTP entry via Selenium")
                                    
                                    # Wait and check if redirect happened
                                    time.sleep(2)
                                    if "request_token=" in driver.current_url:
                                        print("[Zerodha] Redirect detected after retry!")
                                else:
                                    print("[Zerodha] Could not find PIN field for retry")
                        except Exception as retry_e:
                            print(f"[Zerodha] TOTP retry failed: {retry_e}")
                            # Check if redirect happened despite error
                            if "request_token=" in driver.current_url:
                                print("[Zerodha] Redirect detected despite error!")
                            else:
                                print("[Zerodha] Browser will remain open for 30s so you can manually enter TOTP...")
                                time.sleep(30)
                        
                        # Click continue button if present (only if not redirected)
                        if "request_token=" not in driver.current_url:
                            clicked = False
                            for by, sel in cont_locators:
                                try:
                                    cont_btn = driver.find_element(by, sel)
                                    cont_btn.click()
                                    clicked = True
                                    break
                                except Exception:
                                    continue
                            
                            if clicked:
                                print("[Zerodha] Clicked continue button. Waiting for redirect...")
                                time.sleep(2)
                            
                            # Final check
                            if "request_token=" in driver.current_url:
                                print("[Zerodha] Redirect detected after continue button click!")
                            else:
                                print("[Zerodha] Still no redirect. Browser will remain open for 60s...")
                                time.sleep(60)  # Give more time for manual intervention

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


