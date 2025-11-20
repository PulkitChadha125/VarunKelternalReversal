# Zerodha Keltner Channel Reversal Trading Bot

An automated trading bot for Zerodha that implements a Keltner Channel reversal strategy using Heikin-Ashi candles, Supertrend, and Volume indicators.

## 📋 Table of Contents

- [Features](#features)
- [Quick Start - Server Deployment](#quick-start---server-deployment)
- [Trading Strategy](#trading-strategy)
- [Dependencies](#dependencies)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [File Structure](#file-structure)
- [Trading Conditions](#trading-conditions)
- [State Management](#state-management)
- [Error Handling](#error-handling)

## 🚀 Quick Start - Server Deployment

### Files to Upload to Server

**Essential Files (Upload These):**
- ✅ `main.py` - Main trading bot
- ✅ `zerodha_integration.py` - Zerodha API integration
- ✅ `requirements.txt` - Python dependencies
- ✅ `ZerodhaCredentials.csv` - Your credentials (create this)
- ✅ `TradeSettings.csv` - Trading settings

**Do NOT Upload (Auto-generated):**
- ❌ `state.json`, `OrderLog.txt`, `data.csv`
- ❌ `access_token.txt`, `request_token.txt`
- ❌ `__pycache__/`, `chromedriver.exe`

### Quick Server Setup

```bash
# 1. Upload files to server (use SCP/FTP)
# 2. SSH into server
ssh user@server
cd /path/to/bot

# 3. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Install Chrome (if not installed)
sudo apt-get install -y chromium-browser

# 6. Run bot in background (using screen)
screen -S trading_bot
python3 main.py
# Press Ctrl+A then D to detach
```

**See [Server Deployment](#server-deployment) section below for detailed instructions.**

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

**Important Note**: 
- **KC1 = Outer Band** (wider channel)
- **KC2 = Inner Band** (narrower channel)

### Trading Conditions

#### BUY Conditions

1. **Armed Buy Condition**:
   - Heikin-Ashi candle low < **outer KC lower band (KC1_lower)**
   - Evaluated on candle close
   - This arms the buy signal

2. **Buy Entry**:
   - Once armed, when Heikin-Ashi candle close > **inner KC lower band (KC2_lower)**
   - AND volume > VolumeMA (29-period moving average)
   - Evaluated on candle close
   - Take BUY position with CALL option (selected based on maximum delta)
   - **Armed state remains active** after entry (allows re-entry after exit)

3. **Buy Exit**:
   - Supertrend changes from GREEN (trend=1, uptrend) to RED (trend=-1, downtrend)
   - Evaluated on candle close
   - Exit the BUY position
   - After exit, immediately check if armed SELL and entry conditions on same candle

4. **Armed Buy Reset**:
   - Reset armed buy status when candle's high > both upper Keltner bands (KC1_upper AND KC2_upper)
   - Evaluated on candle close
   - Armed state does NOT reset when trade is taken

#### SELL Conditions

1. **Armed Sell Condition**:
   - When **BUY position exists**: Heikin-Ashi candle high ≥ **outer KC upper band (KC1_upper)**
   - OR when **no position**: Heikin-Ashi candle high ≥ **outer KC upper band (KC1_upper)**
   - Evaluated on candle close
   - This arms the sell signal
   - **Note**: If BUY position exists, SELL entry is blocked until BUY exits

2. **Sell Entry**:
   - Once armed, when Heikin-Ashi candle close < **inner KC upper band (KC2_upper)**
   - AND volume > VolumeMA (29-period moving average)
   - Evaluated on candle close
   - Take SELL position with PUT option (selected based on maximum delta)
   - **Armed state remains active** after entry (allows re-entry after exit)

3. **Sell Exit**:
   - Supertrend changes from RED (trend=-1, downtrend) to GREEN (trend=1, uptrend)
   - Evaluated on candle close
   - Exit the SELL position
   - After exit, immediately check if armed BUY/SELL and entry conditions on same candle

4. **Armed Sell Reset**:
   - Reset armed sell status when candle's low < both lower Keltner bands (KC1_lower AND KC2_lower)
   - Evaluated on candle close
   - Armed state does NOT reset when trade is taken

### Position Management Rules

- **One Position at a Time**: Only one position (BUY or SELL) can be active at any given time
- **Armed States Can Be Set Anytime**: Armed states (ARMED BUY/SELL) can be set even when a position already exists
- **Entry Blocked with Existing Position**: Entry trades are **SILENTLY BLOCKED** if a position already exists - no log, no order, must exit first
- **Immediate Re-entry After Exit**: After exit, immediately check armed status and entry conditions on the **same candle** (no waiting for next candle)
- **Armed State Persistence**: Armed state remains active after entry (does not reset automatically)
- **Armed State Reset**: Armed state resets only when opposite condition occurs (not when trade is taken)
- **All Conditions on Candle Close**: All conditions (entry, exit, arm) are evaluated when a candle closes
- **Volume Confirmation**: Entry requires volume to be above the Volume Moving Average
- **Order Status Logging**: Position is set regardless of order success/failure, broker status (PLACED/REJECTED) is logged

**Example Scenario:**
1. **BUY position is active** (CALL option bought)
2. Price goes above outer upper KC band (KC1_upper) → **ARMED SELL is set** (even though BUY position exists)
3. SELL entry conditions are met (HA close < KC2_upper, volume > MA) → **BUT NO TRADE** (silently blocked, no log)
4. BUY position exits (Supertrend changes from GREEN to RED)
5. **Same candle**: Check if armed SELL → If HA close < KC2_upper AND volume > MA → **SELL trade is taken** (PUT option)

### Option Selection Strategy

When a BUY or SELL signal is triggered:

1. **Strike Normalization**: 
   - Gets LTP (Last Traded Price) of underlying
   - Normalizes to nearest ATM strike based on strike step
   - Example: LTP = 5319, StrikeStep = 50 → ATM = 5300

2. **Strike List Creation**:
   - Creates list of strikes around ATM
   - Example: [5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500, 5550, 5600]

3. **Implied Volatility (IV) Calculation**:
   - **Real-time IV calculation** using `py_vollib` library
   - Calculates IV from option's market price (LTP) using Black-Scholes inverse formula
   - Falls back to API IV if available, then to default 20% if calculation fails
   - IV source is logged: "py_vollib", "API", or "Default"

4. **Delta Calculation**:
   - For BUY: Calculates delta for CALL options from strikes ≤ ATM
   - For SELL: Calculates delta for PUT options from strikes ≥ ATM
   - Uses `py_vollib` library for accurate delta calculation
   - Falls back to manual Black-Scholes if py_vollib fails
   - **Risk-free rates**: 10% for MCX commodities, 6% for NFO equity options

5. **Option Selection**:
   - Selects option with **maximum delta** (highest sensitivity to price movement)
   - For CALLs: Highest positive delta
   - For PUTs: Highest absolute delta (most negative)

6. **Order Placement**:
   - Uses **LIMIT orders** with current option LTP (Last Traded Price)
   - MARKET orders are blocked for commodity options on MCX
   - Order price is set to the option's current market price for better execution

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
py_vollib>=1.0.1
pyarrow
setuptools
```

### System Requirements

- Python 3.8 or higher
- Chrome browser (for Selenium automation)
- ChromeDriver (automatically managed by Selenium)

## 🔧 Installation

### Local Installation

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

### Server Deployment

#### Files to Upload to Server

Upload the following **essential files** to your server:

**Required Files:**
```
✅ main.py                      # Main trading bot script
✅ zerodha_integration.py       # Zerodha API integration
✅ requirements.txt             # Python dependencies
✅ ZerodhaCredentials.csv       # Your Zerodha credentials (create this)
✅ TradeSettings.csv            # Trading symbols and parameters
✅ README.md                    # Documentation (optional but recommended)
```

**Files NOT to Upload (auto-generated):**
```
❌ state.json                   # Will be created automatically
❌ OrderLog.txt                 # Will be created automatically
❌ data.csv                     # Will be created automatically
❌ access_token.txt             # Will be created automatically
❌ request_token.txt            # Will be created automatically
❌ __pycache__/                 # Python cache (not needed)
❌ chromedriver.exe             # Selenium will auto-download
```

**Optional Files (for reference):**
```
📄 notes.txt                    # Documentation notes
📄 verify_supertrend.py         # Testing scripts (if needed)
```

#### Server Setup Steps

1. **Upload files to server**:
   ```bash
   # Using SCP (Linux/Mac)
   scp main.py zerodha_integration.py requirements.txt ZerodhaCredentials.csv TradeSettings.csv user@server:/path/to/bot/
   
   # Or use FTP/SFTP client like FileZilla, WinSCP, etc.
   ```

2. **SSH into your server**:
   ```bash
   ssh user@server
   cd /path/to/bot
   ```

3. **Create virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Verify Chrome/Chromium is installed** (required for Selenium):
   ```bash
   # For Ubuntu/Debian
   sudo apt-get update
   sudo apt-get install -y chromium-browser chromium-chromedriver
   
   # Or install Google Chrome
   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   sudo dpkg -i google-chrome-stable_current_amd64.deb
   sudo apt-get install -f
   ```

6. **Install display server** (for headless browser - if needed):
   ```bash
   # For Ubuntu/Debian
   sudo apt-get install -y xvfb
   ```

7. **Test the bot**:
   ```bash
   python3 main.py
   ```

8. **Run as background service** (using screen or tmux):
   ```bash
   # Using screen
   screen -S trading_bot
   python3 main.py
   # Press Ctrl+A then D to detach
   
   # To reattach later
   screen -r trading_bot
   
   # Or using tmux
   tmux new -s trading_bot
   python3 main.py
   # Press Ctrl+B then D to detach
   
   # To reattach later
   tmux attach -t trading_bot
   ```

9. **Run as systemd service** (optional, for auto-start):
   Create `/etc/systemd/system/trading-bot.service`:
   ```ini
   [Unit]
   Description=Zerodha Trading Bot
   After=network.target

   [Service]
   Type=simple
   User=your_username
   WorkingDirectory=/path/to/bot
   Environment="PATH=/path/to/bot/.venv/bin"
   ExecStart=/path/to/bot/.venv/bin/python3 /path/to/bot/main.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
   
   Then enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable trading-bot
   sudo systemctl start trading-bot
   sudo systemctl status trading-bot
   ```

#### Server Requirements

- **Python 3.8+** installed
- **Chrome/Chromium** browser installed (for Selenium)
- **Stable internet connection**
- **Sufficient disk space** for logs and data files
- **Screen/Tmux** or systemd for running in background

#### Important Server Notes

1. **Browser Visibility**: The bot runs with visible browser by default (for debugging). On server, you can modify `zerodha_integration.py` to use headless mode if needed.

2. **File Permissions**: Ensure the bot has write permissions for:
   - `state.json`
   - `OrderLog.txt`
   - `data.csv`
   - `access_token.txt`
   - `request_token.txt`

3. **Timezone**: Ensure server timezone matches your trading timezone (IST for Indian markets).

4. **Firewall**: Ensure ports are open for Zerodha API connections.

5. **Monitoring**: Check `OrderLog.txt` regularly for errors and trading activity.

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

## 🔄 Application Flow

### 1. Initialization Phase

```
Start Application
    ↓
Load Trading State (state.json)
    ↓
Zerodha Login (zerodha_login())
    ↓
Load Trading Settings (TradeSettings.csv)
    ↓
Calculate Timeframe (from settings)
    ↓
Enter Main Loop
```

### 2. Main Execution Loop

```
Main Loop (Continuous)
    ↓
Check Time:
    - If 9:00 AM → Auto-login
    - Calculate next candle time
    ↓
Wait Until Next Candle Close
    ↓
Execute Strategy (main_strategy())
    ↓
Save Trading State
    ↓
Repeat
```

### 3. Strategy Execution Flow (Per Symbol)

```
For Each Symbol in TradeSettings:
    ↓
Fetch Historical Data (last 10 days)
    ↓
Calculate Indicators:
    - Heikin-Ashi Candles
    - Keltner Channel 1 (Outer) - KC1
    - Keltner Channel 2 (Inner) - KC2
    - Supertrend
    - Volume Moving Average
    ↓
Execute Trading Strategy (execute_trading_strategy())
    ↓
Check Exit Conditions First:
    - BUY Exit: Supertrend GREEN → RED
    - SELL Exit: Supertrend RED → GREEN
    ↓
Check Armed Conditions:
    - BUY Armed: HA Low < KC1_Lower (Outer)
    - SELL Armed: HA High ≥ KC1_Upper (Outer)
    ↓
Check Entry Conditions (if no position):
    - BUY Entry: Armed + HA Close > KC2_Lower (Inner) + Volume > MA
    - SELL Entry: Armed + HA Close < KC2_Upper (Inner) + Volume > MA
    ↓
After Exit: Check Armed Status & Entry Conditions (same candle)
    ↓
Display Trading Summary
```

### 4. Order Placement Flow

```
Entry Signal Triggered
    ↓
Select Option with Max Delta:
    - Get Underlying LTP
    - Normalize to ATM Strike
    - Create Strike List
    - Calculate IV (py_vollib) for each strike
    - Calculate Delta (py_vollib) for each strike
    - Select strike with maximum delta
    ↓
Place LIMIT Order:
    - Order Type: LIMIT
    - Price: Current Option LTP
    - Quantity: From TradeSettings
    ↓
Log Order Status:
    - PLACED: Order ID logged
    - REJECTED: Rejection reason logged
    ↓
Set Position (regardless of order success/failure)
    ↓
Save Trading State
```

### 5. Position Management Flow

```
Position = None
    ↓
Armed BUY = True (HA Low < KC1_Lower)
    ↓
Entry Condition Met (HA Close > KC2_Lower + Volume > MA)
    ↓
Place BUY Order → Position = 'BUY'
    ↓
[While BUY Position Active]
    ↓
Armed SELL = True (HA High ≥ KC1_Upper) [Can be set while BUY active]
    ↓
SELL Entry Condition Met → BLOCKED (silently skip, no log)
    ↓
BUY Exit (Supertrend GREEN → RED)
    ↓
Position = None (same candle)
    ↓
Check Armed SELL → If entry conditions met → SELL Entry (same candle)
```

## 📁 File Structure

```
.
├── main.py                      # ✅ Main trading bot script (UPLOAD TO SERVER)
├── zerodha_integration.py       # ✅ Zerodha API integration (UPLOAD TO SERVER)
├── requirements.txt             # ✅ Python dependencies (UPLOAD TO SERVER)
├── README.md                   # 📄 Documentation (optional)
├── ZerodhaCredentials.csv      # ✅ Zerodha API credentials (UPLOAD TO SERVER - create this)
├── TradeSettings.csv           # ✅ Trading symbols and parameters (UPLOAD TO SERVER)
├── state.json                  # ⚠️ Trading state persistence (auto-generated - DON'T UPLOAD)
├── OrderLog.txt                # ⚠️ Trading event logs (auto-generated - DON'T UPLOAD)
├── data.csv                    # ⚠️ Processed historical data (auto-generated - DON'T UPLOAD)
├── access_token.txt            # ⚠️ Zerodha access token (auto-generated - DON'T UPLOAD)
└── request_token.txt           # ⚠️ Zerodha request token (auto-generated - DON'T UPLOAD)
```

**Legend:**
- ✅ **Upload to Server**: Essential files needed for the bot to run
- ⚠️ **Auto-generated**: Created automatically, don't upload (will be generated on server)
- 📄 **Optional**: Nice to have but not required

## 📈 Trading Conditions Summary

### Entry Signals

| Signal | Condition |
|--------|-----------|
| **BUY Entry** | Armed Buy + HA Close > KC2_Lower (Inner) + Volume > VolumeMA |
| **SELL Entry** | Armed Sell + HA Close < KC2_Upper (Inner) + Volume > VolumeMA |

### Exit Signals

| Signal | Condition |
|--------|-----------|
| **BUY Exit** | Supertrend: GREEN → RED |
| **SELL Exit** | Supertrend: RED → GREEN |

### Armed Conditions

| Condition | Trigger | Reset | Notes |
|-----------|---------|-------|-------|
| **Armed Buy** | HA Low < KC1_Lower (Outer) | HA High > Both Upper KC Bands | Remains active after entry (allows re-entry) |
| **Armed Sell** | HA High ≥ KC1_Upper (Outer) | HA Low < Both Lower KC Bands | Can be set while BUY position exists |

**Important**: 
- **KC1 = Outer Band** (wider), **KC2 = Inner Band** (narrower)
- Armed state does NOT reset when a trade is taken. It only resets when the opposite condition occurs.
- Armed states can be set even when a position exists, but entry trades are silently blocked until the existing position is exited.
- After exit, entry conditions are checked immediately on the same candle.

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
- **DELTA CALCULATION**: Detailed table showing all strike deltas, IV (with source), and selected option
- **BUY/SELL ENTRY BLOCKED**: When entry conditions are met but blocked due to existing position
- **ERRORS**: Any errors or re-login events

**Delta Calculation Logging**:
When a signal is triggered, the bot prints a detailed table showing:
- All strikes being evaluated
- Option symbol for each strike
- Delta value for each strike (calculated using py_vollib)
- Implied Volatility (IV) for each strike with source (py_vollib/API/Default)
- Option LTP (Last Traded Price)
- Which option was selected (marked with ✓ SELECTED)
- Risk-free rate used (10% for MCX, 6% for NFO)

**Order Status Logging**:
- Entry orders log: `Order Status: PLACED` with Order ID, or `Order Status: REJECTED` with rejection reason
- Position is set regardless of order success/failure
- Broker response (success/failure) is always logged

**Entry Blocked Behavior**:
- When entry conditions are met but a position already exists, the bot **silently skips** (no log, no order)
- This prevents conflicting trades and ensures one position at a time

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

