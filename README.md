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
- **Pyramiding System**: Adds positions when price moves favorably by specified distance
- **Re-entry Logic**: Can re-enter trades after exit if armed state is still active
- **State Persistence**: Saves trading state to `state.json` for recovery after restart
- **Auto-Login**: Automatic login at 9:00 AM daily
- **Rate Limit Handling**: Automatically handles "too many requests" errors with re-login
- **Candle-Based Execution**: Runs at precise candle boundaries (e.g., 14:30, 14:35, 14:40 for 5-minute timeframe)
- **Comprehensive Logging**: All trading events logged to `OrderLog.txt` and `signal.csv`

## 📊 Trading Strategy

### Strategy Overview

The bot implements a **Keltner Channel Reversal Strategy with Pyramiding** that identifies potential reversal points when price moves outside the Keltner Channel bands and then reverses back inside. The strategy includes a pyramiding system that adds positions when price moves favorably.

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

- **One Position Type at a Time**: Only one position type (BUY or SELL) can be active at any given time
- **Multiple Positions via Pyramiding**: Can have multiple positions of the same type (BUY or SELL) through pyramiding
- **Armed States Can Be Set Anytime**: Armed states (ARMED BUY/SELL) can be set even when a position already exists
- **Entry Blocked with Existing Position**: Entry trades are **SILENTLY BLOCKED** if a position already exists - no log, no order, must exit first
- **Immediate Re-entry After Exit**: After exit, immediately check armed status and entry conditions on the **same candle** (no waiting for next candle)
- **Armed State Persistence**: Armed state remains active after entry (does not reset automatically)
- **Armed State Reset**: Armed state resets only when opposite condition occurs (not when trade is taken)
- **All Conditions on Candle Close**: All conditions (entry, exit, arm, pyramiding) are evaluated when a candle closes
- **Volume Confirmation**: Entry requires volume to be above the Volume Moving Average
- **Order Status Logging**: Position is set regardless of order success/failure, broker status (PLACED/REJECTED) is logged
- **All Positions Exit Together**: When exit signal occurs, all pyramiding positions exit together as a single unit

**Example Scenario:**
1. **BUY position is active** (CALL option bought)
2. Price goes above outer upper KC band (KC1_upper) → **ARMED SELL is set** (even though BUY position exists)
3. SELL entry conditions are met (HA close < KC2_upper, volume > MA) → **BUT NO TRADE** (silently blocked, no log)
4. BUY position exits (Supertrend changes from GREEN to RED) → **All pyramiding positions exit together**
5. **Same candle**: Check if armed SELL → If HA close < KC2_upper AND volume > MA → **SELL trade is taken** (PUT option)

### Pyramiding System

The pyramiding system allows adding positions when price moves favorably by a specified distance.

#### Pyramiding Rules

1. **Initial Entry**: First position is taken at entry signal (BUY or SELL)
   - `pyramiding_count` = 1
   - `first_entry_price` = Entry price (HA close)
   - `last_pyramiding_price` = Entry price

2. **Pyramiding Conditions** (checked on every candle close):
   - **BUY Pyramiding**: Price moves UP by `PyramidingDistance` × `pyramiding_count`
     - Level 1: `first_entry_price + (1 × PyramidingDistance)`
     - Level 2: `first_entry_price + (2 × PyramidingDistance)`
     - Level 3: `first_entry_price + (3 × PyramidingDistance)`
   - **SELL Pyramiding**: Price moves DOWN by `PyramidingDistance` × `pyramiding_count`
     - Level 1: `first_entry_price - (1 × PyramidingDistance)`
     - Level 2: `first_entry_price - (2 × PyramidingDistance)`
     - Level 3: `first_entry_price - (3 × PyramidingDistance)`

3. **Maximum Positions**: 
   - Total positions = 1 (initial) + `PyramidingNumber` (pyramiding)
   - Example: If `PyramidingNumber = 2`, maximum 3 total positions

4. **Same Option Strike**: All pyramiding positions use the same option strike as the initial entry

5. **Exit Together**: When exit signal occurs, all positions (initial + pyramiding) exit together

#### Pyramiding Example

**Configuration:**
- `PyramidingDistance = 50`
- `PyramidingNumber = 2`
- `Lotsize = 1`

**BUY Position Pyramiding:**
1. **Initial Entry** at price 100:
   - Position #1: BUY CALL option at 100
   - `pyramiding_count = 1`
   - `first_entry_price = 100`

2. **Price moves to 150** (100 + 1×50):
   - Pyramiding Level 1 triggered
   - Position #2: BUY same CALL option at 150
   - `pyramiding_count = 2`

3. **Price moves to 200** (100 + 2×50):
   - Pyramiding Level 2 triggered
   - Position #3: BUY same CALL option at 200
   - `pyramiding_count = 3` (maximum reached)

4. **Exit Signal** (Supertrend GREEN → RED):
   - All 3 positions exit together
   - Total quantity: 3 lots
   - `pyramiding_count` reset to 0

**SELL Position Pyramiding:**
1. **Initial Entry** at price 100:
   - Position #1: BUY PUT option at 100
   - `pyramiding_count = 1`
   - `first_entry_price = 100`

2. **Price moves to 50** (100 - 1×50):
   - Pyramiding Level 1 triggered
   - Position #2: BUY same PUT option at 50
   - `pyramiding_count = 2`

3. **Price moves to 0** (100 - 2×50):
   - Pyramiding Level 2 triggered
   - Position #3: BUY same PUT option at 0
   - `pyramiding_count = 3` (maximum reached)

4. **Exit Signal** (Supertrend RED → GREEN):
   - All 3 positions exit together
   - Total quantity: 3 lots
   - `pyramiding_count` reset to 0

#### Pyramiding State Tracking

The bot tracks pyramiding state in `trading_states`:
- `pyramiding_count`: Current number of positions (1, 2, 3...)
- `first_entry_price`: Price of first entry (reference for all pyramiding levels)
- `last_pyramiding_price`: Price of last pyramiding entry
- `pyramiding_positions`: List of all pyramiding positions with order IDs and entry prices

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
Symbol,Expiery,Timeframe,StrikeStep,StrikeNumber,Lotsize,VolumeMa,SupertrendPeriod,SupertrendMul,KC1_Length,KC1_Mul,KC1_ATR,KC2_Length,KC2_Mul,KC2_ATR,PyramidingDistance,PyramidingNumber
CRUDEOIL,25-12-2025,minute,50,6,1,29,10,3,50,3.75,12,50,2.75,14,50,2
```

**Column Descriptions:**
- `Symbol`: Base symbol (e.g., CRUDEOIL)
- `Expiery`: Expiry date in DD-MM-YYYY format
- `Timeframe`: Candle timeframe (e.g., 5minute, 15minute, 1hour)
- `StrikeStep`: Strike step for options (e.g., 50) - used for strike normalization
- `StrikeNumber`: Number of strikes on each side of ATM (e.g., 6) - used for strike list creation
- `Lotsize`: Lot size for trading (quantity per position)
- `VolumeMa`: Volume Moving Average period (default: 29)
- `SupertrendPeriod`: Supertrend ATR period (default: 10)
- `SupertrendMul`: Supertrend multiplier (default: 3.0)
- `KC1_Length`: Keltner Channel 1 EMA length (default: 50)
- `KC1_Mul`: Keltner Channel 1 multiplier (default: 2.0)
- `KC1_ATR`: Keltner Channel 1 ATR period (default: 14)
- `KC2_Length`: Keltner Channel 2 EMA length (default: 50)
- `KC2_Mul`: Keltner Channel 2 multiplier (default: 2.0)
- `KC2_ATR`: Keltner Channel 2 ATR period (default: 12)
- `PyramidingDistance`: Price movement required to add pyramiding position (e.g., 50)
- `PyramidingNumber`: Maximum number of additional pyramiding positions (e.g., 2 = max 3 total positions: 1 initial + 2 pyramiding)

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
├── signal.csv                  # ⚠️ CSV trade signals log (auto-generated - DON'T UPLOAD)
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

### OrderLog.txt

All trading events are logged to `OrderLog.txt` with timestamps:

- **ARMED BUY/SELL**: When armed conditions are met
- **ARMED RESET**: When armed conditions are reset (opposite condition)
- **BUY/SELL ENTRY**: When positions are entered (includes selected option details with delta)
- **PYRAMIDING TRADE OPENED**: When pyramiding position is added (includes position number, price movement, pyramiding level)
- **PYRAMIDING ORDER FAILED**: When pyramiding order fails
- **PYRAMIDING EXIT TRIGGERED**: When exit signal occurs (includes all positions being exited)
- **PYRAMIDING RESET CONFIRMED**: When pyramiding state is reset after exit
- **EXIT BUY/SELL**: When positions are exited (includes P&L for each position)
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

**Pyramiding Logging**:
- Each pyramiding position addition is logged with:
  - Position number (e.g., Position #2 of 3 max)
  - Entry price and first entry price
  - Price movement and percentage
  - Pyramiding level and distance
  - Order ID and quantity
  - Total positions count
- Exit logs show all positions being exited with individual P&L

**Entry Blocked Behavior**:
- When entry conditions are met but a position already exists, the bot **silently skips** (no log, no order)
- This prevents conflicting trades and ensures one position type at a time

### signal.csv

All trade signals are logged to `signal.csv` in structured format for easy analysis:

**CSV Columns:**
- `timestamp`: Date and time of the trade signal
- `Action`: Trade action type:
  - `buy`: Initial BUY entry
  - `sell`: Initial SELL entry
  - `pyramiding trade buy`: Pyramiding BUY position addition
  - `pyramiding trade sell`: Pyramiding SELL position addition
  - `buyexit`: BUY position exit (all positions together)
  - `sellexit`: SELL position exit (all positions together)
- `OptionPrice`: Option price at entry/exit
- `OptionContract`: Option symbol (e.g., CRUDEOIL25DEC5100CE)
- `FutureContract`: Future symbol (e.g., CRUDEOIL25DECFUT)
- `Future price`: Future price (HA close) at entry/exit
- `Lotsize`: Quantity (for exits, this is total quantity of all positions)

**CSV Logging Behavior**:
- **Always logs**: CSV logging occurs regardless of order success/failure
- **Missing data**: If option symbol or price is unavailable, logs "N/A" or 0
- **Pyramiding entries**: Each pyramiding position is logged separately
- **Exits**: Single log entry for all positions exiting together (total lotsize shown)

**Example CSV Entries:**
```csv
timestamp,Action,OptionPrice,OptionContract,FutureContract,Future price,Lotsize
2025-11-28 19:39:13,buy,266.00,CRUDEOIL25DEC5100CE,CRUDEOIL25DECFUT,5281.00,1
2025-11-28 19:44:13,pyramiding trade buy,280.00,CRUDEOIL25DEC5100CE,CRUDEOIL25DECFUT,5331.00,1
2025-11-28 19:49:13,pyramiding trade buy,295.00,CRUDEOIL25DEC5100CE,CRUDEOIL25DECFUT,5381.00,1
2025-11-28 19:54:13,buyexit,310.00,CRUDEOIL25DEC5100CE,CRUDEOIL25DECFUT,5431.00,3
```

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

## 📚 Complete Trading Logic Explanation

### 1. Entry Logic

#### BUY Entry Flow:
1. **Armed Condition**: HA candle low < KC1_lower (outer lower band)
   - Sets `armed_buy = True`
   - Can be set even if position exists
   - Remains active until reset

2. **Entry Condition**: Once armed, when:
   - HA candle close > KC2_lower (inner lower band)
   - AND volume > VolumeMA
   - AND no existing position
   - Evaluated on candle close

3. **Option Selection**:
   - Gets underlying LTP
   - Normalizes to ATM strike
   - Creates strike list around ATM
   - Calculates IV for each strike (py_vollib → API → Default)
   - Calculates delta for CALL options (strikes ≤ ATM)
   - Selects strike with maximum delta (capped at 0.80)

4. **Order Placement**:
   - Places LIMIT order at current option LTP
   - Sets `position = 'BUY'` regardless of order success/failure
   - Initializes pyramiding fields:
     - `pyramiding_count = 1`
     - `first_entry_price = ha_close`
     - `last_pyramiding_price = ha_close`
     - `pyramiding_positions = []`

5. **Logging**:
   - Logs to `OrderLog.txt` with order status
   - Logs to `signal.csv` with action='buy'

#### SELL Entry Flow:
1. **Armed Condition**: HA candle high ≥ KC1_upper (outer upper band)
   - Sets `armed_sell = True`
   - Can be set even if BUY position exists
   - Remains active until reset

2. **Entry Condition**: Once armed, when:
   - HA candle close < KC2_upper (inner upper band)
   - AND volume > VolumeMA
   - AND previous HA candle is RED (prev_ha_close < prev_ha_open)
   - AND no existing position
   - Evaluated on candle close

3. **Option Selection**:
   - Gets underlying LTP
   - Normalizes to ATM strike
   - Creates strike list around ATM
   - Calculates IV for each strike
   - Calculates delta for PUT options (strikes ≥ ATM)
   - Selects strike with maximum absolute delta (capped at -0.80)

4. **Order Placement**:
   - Places LIMIT order at current option LTP
   - Sets `position = 'SELL'` regardless of order success/failure
   - Initializes pyramiding fields (same as BUY)

5. **Logging**:
   - Logs to `OrderLog.txt` with order status
   - Logs to `signal.csv` with action='sell'

### 2. Exit Logic

#### BUY Exit Flow:
1. **Exit Condition**: Supertrend changes from GREEN (trend=1) to RED (trend=-1)
   - Evaluated on candle close
   - Checks previous candle's supertrend trend

2. **Exit Execution**:
   - Gets all pyramiding positions from `pyramiding_positions`
   - Places SELL order for initial position
   - Places SELL order for each pyramiding position
   - Calculates P&L for each position
   - Logs detailed exit information

3. **State Reset**:
   - `position = None`
   - `pyramiding_count = 0`
   - `first_entry_price = None`
   - `last_pyramiding_price = None`
   - `pyramiding_positions = []`
   - Clears option symbol, exchange, order ID

4. **CSV Logging**:
   - Single log entry with total lotsize (all positions)
   - Action: 'buyexit'

5. **Re-entry Check**:
   - Immediately checks armed status on same candle
   - If armed SELL and entry conditions met → SELL entry

#### SELL Exit Flow:
1. **Exit Condition**: Supertrend changes from RED (trend=-1) to GREEN (trend=1)
   - Evaluated on candle close
   - Checks previous candle's supertrend trend

2. **Exit Execution**: Same as BUY exit (but SELL positions)

3. **State Reset**: Same as BUY exit

4. **CSV Logging**: Action: 'sellexit'

5. **Re-entry Check**: Same as BUY exit

### 3. Pyramiding Logic

#### Pyramiding Check (on every candle close):
1. **Pre-conditions**:
   - Position exists (BUY or SELL)
   - `pyramiding_count > 0` (has initial entry)
   - `PyramidingDistance > 0` and `PyramidingNumber > 0`
   - `pyramiding_count < (PyramidingNumber + 1)` (not at max)

2. **BUY Pyramiding**:
   - Calculates next level: `first_entry_price + (pyramiding_count × PyramidingDistance)`
   - If `ha_close >= next_level`:
     - Places BUY order for same CALL option
     - Increments `pyramiding_count`
     - Updates `last_pyramiding_price = ha_close`
     - Adds to `pyramiding_positions` list
     - Logs to `OrderLog.txt` and `signal.csv` (action='pyramiding trade buy')

3. **SELL Pyramiding**:
   - Calculates next level: `first_entry_price - (pyramiding_count × PyramidingDistance)`
   - If `ha_close <= next_level`:
     - Places BUY order for same PUT option
     - Increments `pyramiding_count`
     - Updates `last_pyramiding_price = ha_close`
     - Adds to `pyramiding_positions` list
     - Logs to `OrderLog.txt` and `signal.csv` (action='pyramiding trade sell')

4. **CSV Logging**:
   - Always logs pyramiding attempts (even if order fails)
   - Uses "N/A" or 0 if option data unavailable

### 4. Armed State Management

#### Armed BUY:
- **Set**: HA low < KC1_lower
- **Reset**: HA high > KC1_upper AND HA high > KC2_upper
- **Persistence**: Remains active after entry (allows re-entry after exit)

#### Armed SELL:
- **Set**: HA high ≥ KC1_upper
- **Reset**: HA low < KC1_lower AND HA low < KC2_lower
- **Persistence**: Remains active after entry (allows re-entry after exit)

### 5. Position Management

#### Rules:
- **One Position Type**: Only BUY or SELL can be active (not both)
- **Multiple Positions**: Can have multiple positions of same type via pyramiding
- **Entry Blocking**: Entry blocked if position exists (silently skipped)
- **Exit Together**: All pyramiding positions exit together
- **State Persistence**: Position state saved to `state.json` after each change

### 6. Option Selection Logic

#### Strike Normalization:
1. Get underlying LTP
2. Round to nearest strike based on `StrikeStep`
   - Example: LTP=5319, StrikeStep=50 → ATM=5300

#### Strike List Creation:
- Creates list: `[ATM - (StrikeNumber×StrikeStep), ..., ATM, ..., ATM + (StrikeNumber×StrikeStep)]`
- Example: ATM=5300, StrikeNumber=6, StrikeStep=50
  - List: [5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500, 5550, 5600]

#### IV Calculation:
1. **Primary**: Calculate from option LTP using py_vollib (Black-Scholes inverse)
2. **Fallback 1**: Use API IV if available
3. **Fallback 2**: Use default 20% if calculation fails
4. Log IV source: "py_vollib", "API", or "Default"

#### Delta Calculation:
1. **For BUY (CALL)**: Calculate delta for strikes ≤ ATM
2. **For SELL (PUT)**: Calculate delta for strikes ≥ ATM
3. **Primary**: Use py_vollib
4. **Fallback**: Manual Black-Scholes calculation
5. **Risk-free rates**: 10% for MCX, 6% for NFO

#### Option Selection:
- Selects strike with **maximum delta**
- **Caps**: CALL delta ≤ 0.80, PUT delta ≥ -0.80
- Logs all strikes evaluated with delta, IV, LTP

### 7. Order Management

#### Order Types:
- **LIMIT Orders**: Used for all entries (required for MCX commodities)
- **Price**: Current option LTP (Last Traded Price)
- **Product**: NRML (Positional)

#### Order Status Handling:
- **Success**: Logs Order ID, updates state
- **Failure**: Logs rejection reason, still sets position
- **Position State**: Always set regardless of order success/failure
- **CSV Logging**: Always logs regardless of order success/failure

### 8. State Persistence

#### Saved to `state.json`:
- Position (BUY/SELL/None)
- Armed states (armed_buy, armed_sell)
- Option symbol, exchange, order ID
- Pyramiding fields:
  - pyramiding_count
  - first_entry_price
  - last_pyramiding_price
  - pyramiding_positions (list of all positions)

#### Saved After:
- Each strategy execution
- Position entry
- Position exit
- Pyramiding addition
- Program termination

## 📄 License

This project is for educational purposes. Use at your own risk.

---

**Disclaimer**: Trading involves risk. This bot is provided as-is without any warranties. Always test thoroughly before using with real money.

