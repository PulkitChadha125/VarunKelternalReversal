# Zerodha Keltner Channel Reversal Trading Bot

An automated trading bot for Zerodha that implements a Keltner Channel reversal strategy using Heikin-Ashi candles, Supertrend, and Volume indicators.

## 📋 Table of Contents

- [Features](#features)
- [Trading Strategy](#trading-strategy)
- [Dependencies](#dependencies)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [File Structure](#file-structure)
- [Trading Conditions](#trading-conditions)
- [State Management](#state-management)
- [Error Handling](#error-handling)

## 🚀 Features

- **Automated Trading**: Executes trades based on Keltner Channel reversal strategy
- **Heikin-Ashi Candles**: Uses Heikin-Ashi candlestick charts for smoother trend analysis
- **Multiple Indicators**: 
  - Keltner Channel (2 sets: KC1 and KC2)
  - Supertrend indicator
  - Volume Moving Average
- **Delta-Based Option Selection**: Automatically selects options with maximum delta for optimal entry
- **Re-entry Logic**: Can re-enter trades after exit if armed state is still active
- **State Persistence**: Saves trading state to `state.json` for recovery after restart
- **Auto-Login**: Automatic login at 9:00 AM daily
- **Rate Limit Handling**: Automatically handles "too many requests" errors with re-login
- **Candle-Based Execution**: Runs at precise candle boundaries (e.g., 14:30, 14:35, 14:40 for 5-minute timeframe)
- **Comprehensive Logging**: All trading events logged to `OrderLog.txt`

## 📊 Trading Strategy

### Strategy Overview

The bot implements a **Keltner Channel Reversal Strategy** that identifies potential reversal points when price moves outside the Keltner Channel bands and then reverses back inside.

### Trading Conditions

#### BUY Conditions

1. **Armed Buy Condition**:
   - Heikin-Ashi candle low ≤ both lower Keltner bands (KC1_lower AND KC2_lower)
   - This arms the buy signal

2. **Buy Entry**:
   - Once armed, when Heikin-Ashi candle close > both lower Keltner bands (KC1_lower AND KC2_lower)
   - AND volume > VolumeMA (29-period moving average)
   - Take BUY position with CALL option (selected based on maximum delta)
   - **Armed state remains active** after entry (allows re-entry after exit)

3. **Buy Exit**:
   - Supertrend changes from GREEN (trend=1, uptrend) to RED (trend=-1, downtrend)
   - Exit the BUY position
   - If still armed, can re-enter on next candle if entry conditions are met

4. **Armed Buy Reset**:
   - Reset armed buy status **ONLY** when candle's high > both upper Keltner bands (KC1_upper AND KC2_upper)
   - Armed state does NOT reset when trade is taken

#### SELL Conditions

1. **Armed Sell Condition**:
   - Heikin-Ashi candle high ≥ both upper Keltner bands (KC1_upper AND KC2_upper)
   - This arms the sell signal

2. **Sell Entry**:
   - Once armed, when Heikin-Ashi candle close < both upper Keltner bands (KC1_upper AND KC2_upper)
   - AND volume > VolumeMA (29-period moving average)
   - Take SELL position with PUT option (selected based on maximum delta)
   - **Armed state remains active** after entry (allows re-entry after exit)

3. **Sell Exit**:
   - Supertrend changes from RED (trend=-1, downtrend) to GREEN (trend=1, uptrend)
   - Exit the SELL position
   - If still armed, can re-enter on next candle if entry conditions are met

4. **Armed Sell Reset**:
   - Reset armed sell status **ONLY** when candle's low < both lower Keltner bands (KC1_lower AND KC2_lower)
   - Armed state does NOT reset when trade is taken

### Position Management Rules

- **One Position at a Time**: Only one position (BUY or SELL) can be active at any given time
- **No Entry on Exit Candle**: Cannot enter a new position on the same candle where an exit occurred
- **Re-entry After Exit**: If armed state is still active after exit, can re-enter on next candle if entry conditions are met
- **Armed State Persistence**: Armed state remains active after entry (does not reset automatically)
- **Armed State Reset**: Armed state resets only when opposite condition occurs (not when trade is taken)
- **All Conditions on Candle Close**: All conditions are evaluated when a candle closes
- **Volume Confirmation**: Entry requires volume to be above the Volume Moving Average

### Option Selection Strategy

When a BUY or SELL signal is triggered:

1. **Strike Normalization**: 
   - Gets LTP (Last Traded Price) of underlying
   - Normalizes to nearest ATM strike based on strike step
   - Example: LTP = 5319, StrikeStep = 50 → ATM = 5300

2. **Strike List Creation**:
   - Creates list of strikes around ATM
   - Example: [5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500, 5550, 5600]

3. **Delta Calculation**:
   - For BUY: Calculates delta for CALL options from strikes ≤ ATM
   - For SELL: Calculates delta for PUT options from strikes ≥ ATM
   - Uses Black-Scholes model with Implied Volatility (IV) from option quotes

4. **Option Selection**:
   - Selects option with **maximum delta** (highest sensitivity to price movement)
   - For CALLs: Highest positive delta
   - For PUTs: Highest absolute delta (most negative)

5. **Delta Calculation Libraries**:
   - **scipy.stats.norm**: For cumulative distribution function N(d1)
   - **math**: For logarithmic and square root calculations
   - Formula: d1 = [ln(S/K) + (r + σ²/2) × T] / (σ × √T)
   - Call Delta = N(d1), Put Delta = N(d1) - 1

## 📦 Dependencies

### Python Packages

```
kiteconnect>=4.0.0
selenium>=4.0.0
pyotp>=2.9.0
pandas>=2.0.0
polars>=0.19.0
polars-talib>=0.1.0
scipy>=1.10.0
numpy>=1.24.0
pyarrow
setuptools
```

### System Requirements

- Python 3.8 or higher
- Chrome browser (for Selenium automation)
- ChromeDriver (automatically managed by Selenium)

## 🔧 Installation

1. **Clone or download the project**

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv .venv
   ```

3. **Activate the virtual environment**:
   - Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - Linux/Mac:
     ```bash
     source .venv/bin/activate
     ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure credentials** (see Configuration section below)

## ⚙️ Configuration

### 1. Zerodha Credentials (`ZerodhaCredentials.csv`)

Create a CSV file named `ZerodhaCredentials.csv` in the project root directory with the following format:

**File Format:**
```csv
title,value
ID,YOUR_USER_ID
pwd,YOUR_PASSWORD
key,YOUR_API_KEY
secret,YOUR_API_SECRET
zerodha2fa,YOUR_TOTP_SECRET
```

**Example:**
```csv
title,value
ID,TET050
pwd,MyPassword123
key,k7mxqcy39nzx4s74
secret,l1ooqrt6on6bm6cizc1ontf2kegb7m0o
zerodha2fa,J25T6D7R7RQ2CIFJZ6IGTPPVR2SHO52W
```

**Row Descriptions:**
- `ID`: Your Zerodha User ID (Kite login username)
- `pwd`: Your Zerodha account password
- `key`: Your Zerodha API Key (from Developer Apps)
- `secret`: Your Zerodha API Secret (from Developer Apps)
- `zerodha2fa`: Your TOTP secret key (from authenticator app)

**How to get Zerodha API credentials:**
1. Log in to [Zerodha Kite](https://kite.zerodha.com/)
2. Go to **Developer Apps** section (under Profile → API)
3. Create a new app to get **API Key** and **API Secret**
4. Get **TOTP secret** from your authenticator app (Google Authenticator, Authy, etc.)
   - The TOTP secret is usually a 32-character alphanumeric string
   - It's the same secret used to generate 6-digit codes for 2FA

**Important Notes:**
- Keep this file secure and never commit it to version control
- The file should be in the same directory as `main.py`
- Ensure there are no extra spaces in the CSV file
- Column names must be exactly `title` and `value` (case-sensitive)
- Row titles must match exactly: `ID`, `pwd`, `key`, `secret`, `zerodha2fa` (case-sensitive)

### 2. Trading Settings (`TradeSettings.csv`)

Configure your trading symbols and indicator parameters:

```csv
Symbol,Expiery,Timeframe,StrikeStep,StrikeNumber,Lotsize,VolumeMa,SupertrendPeriod,SupertrendMul,KC1_Length,KC1_Mul,KC1_ATR,KC2_Length,KC2_Mul,KC2_ATR
CRUDEOIL,19-11-2025,5minute,50,6,1,29,10,3.0,50,2.0,14,50,2.0,12
```

**Column Descriptions:**
- `Symbol`: Base symbol (e.g., CRUDEOIL)
- `Expiery`: Expiry date in DD-MM-YYYY format
- `Timeframe`: Candle timeframe (e.g., 5minute, 15minute, 1hour)
- `StrikeStep`: Strike step for options (e.g., 50) - used for strike normalization
- `StrikeNumber`: Number of strikes on each side of ATM (e.g., 6) - used for strike list creation
- `Lotsize`: Lot size for trading (future use)
- `VolumeMa`: Volume Moving Average period (default: 29)
- `SupertrendPeriod`: Supertrend ATR period (default: 10)
- `SupertrendMul`: Supertrend multiplier (default: 3.0)
- `KC1_Length`: Keltner Channel 1 EMA length (default: 50)
- `KC1_Mul`: Keltner Channel 1 multiplier (default: 2.0)
- `KC1_ATR`: Keltner Channel 1 ATR period (default: 14)
- `KC2_Length`: Keltner Channel 2 EMA length (default: 50)
- `KC2_Mul`: Keltner Channel 2 multiplier (default: 2.0)
- `KC2_ATR`: Keltner Channel 2 ATR period (default: 12)

## 🎯 Usage

1. **Configure your credentials and settings** (see Configuration section)

2. **Run the bot**:
   ```bash
   python main.py
   ```

3. **The bot will**:
   - Load previous trading state (if exists)
   - Login to Zerodha
   - Load trading settings
   - Calculate next candle time and wait
   - Execute strategy at each candle close
   - Display comprehensive trading summary
   - Log all events to `OrderLog.txt`
   - Save state after each execution

4. **Stop the bot**: Press `Ctrl+C` (state will be saved automatically)

## 📁 File Structure

```
.
├── main.py                      # Main trading bot script
├── zerodha_integration.py       # Zerodha API integration functions
├── requirements.txt             # Python dependencies
├── README.md                   # This file
├── ZerodhaCredentials.csv      # Zerodha API credentials (create this)
├── TradeSettings.csv           # Trading symbols and parameters
├── state.json                  # Trading state persistence (auto-generated)
├── OrderLog.txt                # Trading event logs (auto-generated)
├── data.csv                    # Processed historical data (auto-generated)
├── access_token.txt            # Zerodha access token (auto-generated)
└── request_token.txt           # Zerodha request token (auto-generated)
```

## 📈 Trading Conditions Summary

### Entry Signals

| Signal | Condition |
|--------|-----------|
| **BUY Entry** | Armed Buy + HA Close > Both Lower KC Bands + Volume > VolumeMA |
| **SELL Entry** | Armed Sell + HA Close < Both Upper KC Bands + Volume > VolumeMA |

### Exit Signals

| Signal | Condition |
|--------|-----------|
| **BUY Exit** | Supertrend: GREEN → RED |
| **SELL Exit** | Supertrend: RED → GREEN |

### Armed Conditions

| Condition | Trigger | Reset | Notes |
|-----------|---------|-------|-------|
| **Armed Buy** | HA Low ≤ Both Lower KC Bands | HA High > Both Upper KC Bands | Remains active after entry (allows re-entry) |
| **Armed Sell** | HA High ≥ Both Upper KC Bands | HA Low < Both Lower KC Bands | Remains active after entry (allows re-entry) |

**Important**: Armed state does NOT reset when a trade is taken. It only resets when the opposite condition occurs.

## 💾 State Management

The bot automatically saves trading state to `state.json` after:
- Each strategy execution
- Position entry (BUY/SELL)
- Position exit
- Program termination (Ctrl+C or error)

**State includes:**
- Current position (BUY/SELL/None) for each symbol
- Armed status (armed_buy, armed_sell) - persists after entry
- Exit flags
- Last exit candle date

**On restart**, the bot automatically loads the previous state, so it knows:
- Which positions are currently open
- Which symbols are armed (can re-enter if conditions met)
- Previous exit information

**Re-entry Behavior**:
- If a position exits via Supertrend and armed state is still active
- On the next candle (not exit candle), if entry conditions are met, will re-enter automatically
- This allows multiple entries during a strong trend while armed

## 🔄 Error Handling

### Rate Limiting

If "Too many requests" error occurs:
1. Bot waits 60 seconds
2. Automatically re-logs in
3. Retries the operation
4. Logs the event to `OrderLog.txt`

### Auto-Login

- Automatic login at **9:00 AM** every day
- Logs the event to `OrderLog.txt`
- Prevents multiple logins with cooldown

### File Locking

- Handles `data.csv` file locking (if open in Excel)
- Retries up to 3 times with 1-second delay

## 📝 Logging

All trading events are logged to `OrderLog.txt` with timestamps:

- **ARMED BUY/SELL**: When armed conditions are met
- **ARMED RESET**: When armed conditions are reset (opposite condition)
- **BUY/SELL ENTRY**: When positions are entered (includes selected option details with delta)
- **EXIT BUY/SELL**: When positions are exited
- **DELTA CALCULATION**: Detailed table showing all strike deltas and selected option
- **ERRORS**: Any errors or re-login events

**Delta Calculation Logging**:
When a signal is triggered, the bot prints a detailed table showing:
- All strikes being evaluated
- Option symbol for each strike
- Delta value for each strike
- Implied Volatility (IV) for each strike
- Option LTP (Last Traded Price)
- Which option was selected (marked with ✓ SELECTED)

## ⚠️ Important Notes

1. **Paper Trading First**: Test the bot with paper trading before using real money
2. **Market Hours**: The bot is designed to run during market hours
3. **Internet Connection**: Requires stable internet connection
4. **API Limits**: Be aware of Zerodha API rate limits
5. **Risk Management**: This is a trading bot - use at your own risk
6. **No Guarantees**: Past performance does not guarantee future results

## 🔍 Monitoring

The bot displays a comprehensive summary after each execution:

```
================================================================================
TRADING SUMMARY - CRUDEOIL25NOVFUT (CRUDEOIL)
================================================================================
Timestamp: 2025-11-17 14:35:00
--------------------------------------------------------------------------------
HEIKIN-ASHI CANDLE:
  Close:     5298.00
  Open:      5290.42
  High:      5302.00
  Low:       5290.42
--------------------------------------------------------------------------------
KELTNER CHANNEL 1 (KC1):
  Upper:     5304.59
  Middle:    5284.17
  Lower:     5263.74
--------------------------------------------------------------------------------
KELTNER CHANNEL 2 (KC2):
  Upper:     5312.56
  Middle:    5284.17
  Lower:     5255.78
--------------------------------------------------------------------------------
SUPERTREND:
  Value:     5436.63
  Trend:     RED (↓)
--------------------------------------------------------------------------------
VOLUME:
  Current:       100
  MA(29):         95
  Status:  ABOVE MA
--------------------------------------------------------------------------------
TRADING STATUS:
  Position:     NO POSITION
  Armed Status:            NONE
================================================================================
```

## 📞 Support

For issues or questions:
1. Check `OrderLog.txt` for error messages
2. Verify credentials in `ZerodhaCredentials.csv`
3. Check trading settings in `TradeSettings.csv`
4. Ensure internet connection is stable

## 📄 License

This project is for educational purposes. Use at your own risk.

---

**Disclaimer**: Trading involves risk. This bot is provided as-is without any warranties. Always test thoroughly before using with real money.

