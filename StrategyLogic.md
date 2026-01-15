## Overview

This document describes the **end‑to‑end trading logic** of `MainPyramidingSl.py`:

- **Data & indicators**: how candles and indicators are built.
- **State model**: how positions and per‑symbol state are tracked.
- **Entry logic**: conditions for arming and taking BUY/SELL trades.
- **Stop‑loss & exits**: initial SL, SL exit rules, Supertrend exits.
- **Pyramiding**: how additional positions are added and logged.
- **Scheduling**: how and when the strategy runs.

Wherever the code differs for BUY vs SELL, both sides are documented explicitly.

---

## 1. Instruments, Settings, and Per‑Symbol State

### 1.1 Trade settings (`TradeSettings.csv` → `result_dict`)

For each row in `TradeSettings.csv`:

- **Key fields**:
  - `Symbol`: underlying base symbol (e.g. `CRUDEOIL`).
  - `Expiery`: futures/options expiry date (`DD‑MM‑YYYY`).
  - `Timeframe`: chart timeframe string (e.g. `5minute`).
  - `StrikeStep`: option strike spacing (e.g. 50).
  - `StrikeNumber`: number of strikes each side around ATM.
  - `Lotsize`: lot size per options order.
  - `VolumeMa`: period for Volume MA.
  - `SupertrendPeriod`, `SupertrendMul`: Supertrend parameters.
  - `KC1_Length`, `KC1_Mul`, `KC1_ATR`: outer Keltner parameters.
  - `KC2_Length`, `KC2_Mul`, `KC2_ATR`: inner Keltner parameters.
  - `PyramidingDistance`: price distance between pyramiding entries.
  - `PyramidingNumber`: number of pyramiding *adds* allowed (excluding initial position).
  - `SLATR`: ATR period for initial SL.
  - `SLMULTIPLIER`: ATR multiplier for initial SL.

- **Derived values**:
  - `FutureSymbol` = `{SYMBOL}{YY}{MMM}FUT` (e.g. `CRUDEOIL25NOVFUT`).
  - A **unique key** `unique_key = f"{Symbol}_{Expiery}"` indexes settings and trading state.

All of this is stored in `result_dict[unique_key]`.

### 1.2 Trading state (`trading_states[unique_key]`)

Per `unique_key`, trading state persists in memory and in `state.json`:

- **Position & arming flags**
  - `position`: `None`, `'BUY'`, or `'SELL'`.
  - `armed_buy`: `bool` – buy is “armed”.
  - `armed_sell`: `bool` – sell is “armed”.
  - `exit_on_candle`: unused in logic but reserved.
  - `last_exit_candle_date`: reserved for potential “no re‑entry same candle” logic.

- **Current option position meta**
  - `option_symbol`: option symbol used for the **initial** position.
  - `option_exchange`: exchange of the option (`NFO` or `MCX`).
  - `option_order_id`: last initial order id (if any).

- **Pyramiding**
  - `pyramiding_count`: total number of positions currently open for this symbol:
    - `0` = flat.
    - `1` = only initial position.
    - `>=2` = initial + 1+ pyramiding adds.
  - `first_entry_price`: HA close of the initial entry candle (underlying price).
  - `last_pyramiding_price`: HA close of the most recent pyramiding entry.
  - `pyramiding_positions`: list of **only** pyramiding trades (initial is not stored here):
    - Each element:
      - `option_symbol`: option used for that pyramiding add (may differ from initial).
      - `order_id`: broker order id (if any).
      - `entry_price`: HA close (underlying price) at this add.
      - `entry_option_price`: option price at this add.

- **Stop‑loss & entry prices**
  - `initial_sl`: initial stop‑loss level at first entry:
    - BUY: lowest HA low of last 5 candles − ATR × SLMULTIPLIER.
    - SELL: highest HA high of last 5 candles + ATR × SLMULTIPLIER.
  - `current_sl`: current SL level. **Important**: in current implementation, it is always equal to `initial_sl` and does **not trail** with pyramiding; it is not re‑averaged.
  - `entry_prices`: list of HA close prices for all entries (initial + pyramiding).
  - `entry_option_price`: option entry price for **initial position** (for P&L on exit).

The entire `trading_states` dict is periodically persisted via `save_trading_state()` and restored at start via `load_trading_state()`.

---

## 2. Data & Indicator Pipeline

### 2.1 Historical candles

For each symbol cycle in `main_strategy()`:

- `fetch_historical_data_for_symbol()`:
  - Finds the instrument token of `FutureSymbol` by scanning exchanges in order:
    - `["MCX", "NFO", "NSE", "BSE"]`.
  - Pulls **`days_back=10`** days of OHLCV data using `get_historical_data()` with the `Timeframe` from `TradeSettings.csv` (e.g. `5minute`).

### 2.2 Conversion to Heikin‑Ashi

`convert_to_heikin_ashi()` adds HA columns on top of the original OHLCV:

- For each candle:
  - `ha_close = (open + high + low + close) / 4`.
  - First candle:
    - `ha_open = (open + close) / 2`.
  - Subsequent candles:
    - `ha_open = (prev_ha_open + prev_ha_close) / 2`.
  - `ha_high = max(high, ha_open, ha_close)`.
  - `ha_low = min(low, ha_open, ha_close)`.

Indicators and trading logic use these HA prices.

### 2.3 Volume MA

`calculate_volume_ma()`:

- `VolumeMA = rolling_mean(volume, window = VolumeMa)` on HA candles.

Volume conditions compare `volume` vs `VolumeMA`.

### 2.4 Supertrend

`calculate_supertrend()`:

- Uses `pandas_ta.supertrend()` on `(ha_high, ha_low, ha_close)` with:
  - `length = SupertrendPeriod`.
  - `multiplier = SupertrendMul`.
- Adds:
  - `supertrend`: Supertrend line.
  - `supertrend_trend`: `1` (uptrend/green), `-1` (downtrend/red).
  - `final_lower`, `final_upper`: ST bands.

**Note**: Supertrend is **only used for exits**, not for entries.

### 2.5 Keltner Channels (KC1, KC2)

Two separate Keltner Channels are computed on HA data via `pandas_ta.kc()`:

- `KC1_*` (outer band):
  - `length = KC1_Length`.
  - `scalar = KC1_Mul`.
  - `atr_length = KC1_ATR` (if supported by library; else falls back to `length`).

- `KC2_*` (inner band):
  - `length = KC2_Length`.
  - `scalar = KC2_Mul`.
  - `atr_length = KC2_ATR`.

Per channel:

- `KCx_middle`: EMA(ha_close, length).
- `KCx_upper = middle + ATR * multiplier`.
- `KCx_lower = middle - ATR * multiplier`.

Strategy meaning:

- **KC1**: outer band for “extreme” conditions and arming/resets.
- **KC2**: inner band used for actual entries.

### 2.6 Data rounding

After all indicators:

- All numeric columns (except `date`) are rounded to 2 decimals for stability and readability.

---

## 3. Entry Logic: Arming and Execution

All checks are done on **candle close** (`execute_trading_strategy()` uses the last row of `processed_df`).

### 3.1 Arming conditions

Arming can occur **whether or not a position already exists**.

#### 3.1.1 Armed BUY

- Condition:
  - `ha_low < KC1_lower`.
- If `armed_buy` was previously `False`, set to `True` and:
  - Log `"ARMED BUY"` in `OrderLog.txt`.
  - Write a `signal.csv` row with:
    - `action = 'Armed Buy'`.
    - `future_contract = FutureSymbol`.
    - `future_price = ha_close`.

#### 3.1.2 Armed SELL

Two scenarios:

- **If a BUY position is open** (`position == 'BUY'`):
  - Condition:
    - `ha_high >= KC1_upper`.
  - If `armed_sell` was `False`, set to `True` and:
    - Log `"ARMED SELL"` with a note that BUY is active.
    - Write `action='Armed Sell'` row into `signal.csv`.

- **If no position is open** (`position is None`):
  - Condition:
    - `ha_high >= KC1_upper`.
  - Same logging and CSV behavior (`Armed Sell`).

Arming does **not** immediately open trades; it just prepares for potential entries.

### 3.2 Resetting arming

- **Reset Armed BUY** when:
  - `ha_high > KC1_upper` **and** `ha_high > KC2_upper`.
  - Result: `armed_buy = False`, log `"ARMED BUY RESET"`.

- **Reset Armed SELL** when:
  - `ha_low < KC1_lower` **and** `ha_low < KC2_lower`.
  - Result: `armed_sell = False`, log `"ARMED SELL RESET"`.

### 3.3 General rule for entries

- If `position is not None` (already in BUY or SELL), **entry logic is skipped silently** — no new trades, no logs.
- Entries only fire if `current_position is None`.

### 3.4 BUY Entry Logic

Prerequisites:

- No open position: `position is None`.
- `armed_buy == True`.

Conditions on the **current candle**:

1. **Price confirmation**:
   - `ha_close > KC2_lower` (HA close above *inner* lower band).

2. **Volume confirmation**:
   - `volume > VolumeMA`.

3. **Previous candle color**:
   - Previous HA candle must be **GREEN**:
     - `prev_ha_close > prev_ha_open`.
   - If previous candle is missing or red, BUY entry is skipped.

If all are satisfied:

#### 3.4.1 Underlying pricing for options selection

- From `result_dict[unique_key]`, read:
  - `StrikeStep`.
  - `StrikeNumber`.
  - `Expiry`.

- Determine exchange for `FutureSymbol`:
  - `underlying_exchange = find_exchange_for_symbol(kite_client, FutureSymbol)`.
  - If `underlying_exchange == 'MCX'`, then options are also on `MCX`, otherwise `NFO`.

- Get **underlying LTP**:
  - If `underlying_exchange` found: `ltp = get_ltp(kite_client, underlying_exchange, FutureSymbol)`.
  - If LTP not available: use `ha_close` as fallback.

- Compute ATM & strike list:
  - `atm = normalize_strike(ltp, StrikeStep)`.
  - `all_strikes = create_strike_list(atm, StrikeStep, StrikeNumber)`.
  - BUY uses strikes **≤ atm**: `buy_strikes`.

#### 3.4.2 CALL selection by max delta

If `kite_client`, `Expiry`, and `buy_strikes` are available:

- `risk_free_rate`:
  - `0.10` for `MCX`.
  - `0.06` for `NFO`.

- Call `find_option_with_max_delta()` with:
  - `option_type='CE'`.

Option selection behavior:

- For each candidate strike:
  - Build option symbol `SYMBOL + YY + MMM + STRIKE + 'CE'`.
  - Pull option quote and LTP.
  - Compute IV via `py_vollib.implied_volatility` from option price and underlying LTP:
    - If fails, retry with fresh quote once.
    - If still fails or no LTP, strike is skipped.
  - Compute delta:
    - Prefer `py_vollib_delta`.
    - Fallback to manual Black‑Scholes in `calculate_delta_black_scholes` if needed.
  - Selection rule:
    - For CALLS: choose **maximum delta ≤ 0.80**.

- Logs:
  - Detailed table of strikes, deltas, IVs, LTPs.
  - Mark the selected strike with `✓ SELECTED`.

Return value:

- `selected_option` dict with:
  - `strike`, `delta`, `option_symbol`, `iv`, `ltp`, `ltp_float`,
  - `all_strikes_evaluated`, `underlying_ltp`, `atm_strike`, `time_to_expiry_years`, `risk_free_rate`.

#### 3.4.3 Placing the BUY option order

If `selected_option` exists and `kite_client` is usable:

- Lotsize from settings: `lotsize = int(Lotsize)`.
- Option price for LIMIT order:
  - Prefer `selected_option['ltp_float']`.
  - If missing, fetch fresh quote and use `last_price`.

- Call `place_option_order()`:
  - `exchange = option_exchange`.
  - `option_symbol = selected_option['option_symbol']`.
  - `transaction_type = "BUY"`.
  - `order_type = "LIMIT"`.
  - `product = "NRML"`.
  - `quantity = lotsize`.
  - `price = option_ltp`.

Important behavior:

- **Position is always marked as entered** when entry conditions are satisfied, **regardless of order success/failure**:
  - `trading_state['position'] = 'BUY'`.
  - `trading_state['option_symbol'] = selected_option['option_symbol']`.
  - `trading_state['option_exchange'] = option_exchange`.
  - `trading_state['option_order_id'] = order_id` (if any).
  - This means logical state moves to BUY even if the broker rejected the order (the OrderLog makes that visible).

#### 3.4.4 Initial SL at BUY entry

Using entire HA dataframe `df`:

- `sl_atr_period = SLATR`, `sl_multiplier = SLMULTIPLIER`.
- `calculate_initial_sl(df, 'BUY', SLATR, SLMULTIPLIER)`:
  - Take the last 5 **completed** HA candles (excluding current) when possible.
  - Compute ATR over full HA series.
  - BUY initial SL:
    - `lowest_low_of_last_5 - ATR * SL_MULTIPLIER`.

If successful:

- `trading_state['initial_sl'] = initial_sl`.
- `trading_state['current_sl'] = initial_sl`.
- `trading_state['entry_prices'] = [ha_close]` (for tracking).

This SL is used for **all exit decisions** and does **not** trail in current code.

#### 3.4.5 State and logging at BUY entry

State:

- `pyramiding_count = 1` (initial position).
- `first_entry_price = ha_close`.
- `last_pyramiding_price = ha_close`.
- `pyramiding_positions = []` (no pyramiding yet).
- `entry_option_price = option_ltp` (initial option price).

CSV:

- `write_to_signal_csv()` with:
  - `action = 'buy'`.
  - `option_price = option LTP` (chosen as above).
  - `optioncontract = selected_option['option_symbol']`.
  - `futurecontract = FutureSymbol`.
  - `futureprice = ha_close`.
  - `lotsize = Lotsize`.
  - `stop_loss = None` (SL empty at entry).

OrderLog:

- Detailed “BUY ENTRY” line including:
  - Price, volume, Keltner levels, Supertrend, selected option symbol, strike, delta, IV, LTP.
  - Order status:
    - `"PLACED"` with `order_id` if success.
    - `"REJECTED"` with captured `order_error` otherwise.

`armed_buy` remains `True` (design decision: allows re‑entry after exit if conditions still fit).

### 3.5 SELL Entry Logic

Mirror of BUY with PUT selection and inverted conditions.

Prerequisites:

- No open position: `position is None`.
- `armed_sell == True`.

Conditions on current candle:

1. **Price confirmation**:
   - `ha_close < KC2_upper` (close below **inner** upper band).

2. **Volume confirmation**:
   - `volume > VolumeMA`.

3. **Previous candle color**:
   - Previous HA candle must be **RED**:
     - `prev_ha_close < prev_ha_open`.

If all are satisfied:

#### 3.5.1 Underlying pricing & PUT selection

Analogous to BUY:

- Determine exchange for `FutureSymbol`, compute `ltp`, `atm`, `all_strikes`.
- SELL uses `sell_strikes = [s for s in all_strikes if s >= atm]`.
- Use `find_option_with_max_delta(..., option_type='PE')`:
  - For PUTS, choose **most negative delta** (minimum) but constrained to `delta ≥ -0.80`.

Logging is analogous to the BUY side.

#### 3.5.2 Placing the PUT BUY order

If `selected_option` and `kite_client` present:

- Place `BUY` order for PUT with:
  - `exchange = option_exchange`.
  - `option_symbol = selected_option['option_symbol']`.
  - `type = LIMIT`, `product = NRML`.
  - `quantity = Lotsize`.
  - `price = option_ltp`.

State:

- Regardless of order success:
  - `position = 'SELL'`.
  - `option_symbol`, `option_exchange`, and `option_order_id` set.
  - `pyramiding_count = 1`.
  - `first_entry_price = ha_close`.
  - `last_pyramiding_price = ha_close`.
  - `pyramiding_positions = []`.
  - `entry_option_price = option_ltp` (initial PUT price).

#### 3.5.3 Initial SL at SELL entry

`calculate_initial_sl(df, 'SELL', SLATR, SLMULTIPLIER)`:

- SELL initial SL:
  - `highest_high_of_last_5 + ATR * SLMULTIPLIER`.

If successful:

- `initial_sl = current_sl = this level`.
- `entry_prices = [ha_close]`.

#### 3.5.4 CSV & logs at SELL entry

CSV:

- `action = 'sell'`.
- `option_price = PUT LTP`.
- `optioncontract = selected_option['option_symbol']` (if any).
- `futurecontract = FutureSymbol`.
- `futureprice = ha_close`.
- `lotsize = Lotsize`.
- `stop_loss = None` (entry).

Logs:

- Symmetric to BUY: “SELL ENTRY” line with Keltner, Supertrend, option delta/IV, and order status.

---

## 4. Stop‑Loss (SL), Exits, and Trailing

### 4.1 High‑level behavior

For each new candle, **exit conditions are always checked before any new entry logic**:

1. **Hard SL exits**, based on the **previous candle’s** HA extreme vs `current_sl`.
2. **Supertrend exits**, based on **trend flips**.
3. Only **after exits** are processed, entry logic can potentially fire again on the **same candle**.

### 4.2 Stop‑loss exit rules

SL is stored in `trading_state['current_sl']`. In current implementation:

- `current_sl` is set at initial entry using ATR logic.
- It is **not adjusted** when adding pyramiding trades.
- There is no dynamic/trailing SL logic; SL is **fixed** per position lifecycle.

#### 4.2.1 BUY SL exit

Conditions:

- A BUY position is active: `position == 'BUY'`.
- `current_sl` is not `None`.
- Previous candle `prev_ha_low` is not `None`.
- If `prev_ha_low < current_sl`:
  - Trigger **SL exit** for **all** positions (initial + pyramiding).

Behavior:

- For the **initial position**:
  - Get option LTP from quote (using `option_symbol`, `option_exchange`).
  - Place a **separate SELL LIMIT** order with this LTP and `Lotsize`.
  - Log order and store `initial_exit_price`.

- For **each pyramiding position** in `pyramiding_positions`:
  - Use its own `option_symbol` (or fall back to initial option).
  - Get LTP, place a **separate SELL LIMIT** order per pyramiding position with `Lotsize`.
  - Log each order, store `exit_price` for that pyramiding leg.

- CSV exits:
  - Initial:
    - `action = 'buyexit'`.
    - `option_price = initial_exit_price`.
    - `optioncontract = option_symbol`.
    - `futurecontract = FutureSymbol`.
    - `futureprice = ha_close` (current HA close).
    - `lotsize = Lotsize`.
    - `stop_loss = current_sl`.
    - `entry_future_price = first_entry_price`.
    - `entry_option_price = entry_option_price_initial`.
  - Each pyramiding leg `idx`:
    - `action = f'pyramiding trade buy ({idx}) exit'`.
    - `option_price = exit_price` for that leg.
    - `optioncontract = pyr_option_symbol`.
    - `futurecontract = FutureSymbol`.
    - `futureprice = ha_close`.
    - `lotsize = Lotsize`.
    - `stop_loss = current_sl`.
    - `entry_future_price = that leg's entry_price`.
    - `entry_option_price = that leg's entry_option_price`.

- Internal state after SL exit:
  - `position = None`.
  - `option_symbol = None`, `option_exchange = None`, `option_order_id = None`.
  - `pyramiding_count = 0`.
  - `first_entry_price = None`.
  - `last_pyramiding_price = None`.
  - `pyramiding_positions = []`.
  - `initial_sl = None`, `current_sl = None`.
  - `entry_prices = []`, `entry_option_price = None`.
  - State is saved (`save_trading_state()`).

#### 4.2.2 SELL SL exit

Mirror of BUY SL but using previous candle **high**:

- Conditions:
  - `position == 'SELL'`.
  - `current_sl` not `None`.
  - `prev_ha_high > current_sl`.

Behavior:

- Exit initial and all pyramiding positions with **SELL** orders (closing long PUTs).
- CSV actions:
  - Initial: `sellexit`.
  - Pyramiding legs: `pyramiding trade sell (idx) exit`.
- P&L calculation uses option entry/exit prices with correct sign for short‑delta structure (code uses entry − exit for SELL).
- Reset state fields identical to BUY SL exit.

### 4.3 Supertrend exits (trend flip exits)

Supertrend is used only for **trend‑flip exits**; it does **not** participate in entries.

#### 4.3.1 BUY Supertrend exit

Conditions:

- Active BUY position: `position == 'BUY'`.
- Previous candle `prev_supertrend_trend == 1` (green/up).
- Current candle `supertrend_trend == -1` (red/down).

Behavior:

- Exactly same exit workflow as BUY SL exit:
  - Separate SELL orders for initial and all pyramiding positions.
  - CSV logs: `buyexit` + `pyramiding trade buy (idx) exit`.
  - State reset to flat.

#### 4.3.2 SELL Supertrend exit

Conditions:

- Active SELL position: `position == 'SELL'`.
- Previous candle `prev_supertrend_trend == -1` (red).
- Current candle `supertrend_trend == 1` (green).

Behavior:

- Same as SELL SL exit:
  - Close all positions with SELL orders (since options are always bought on entry).
  - CSV logs: `sellexit` + `pyramiding trade sell (idx) exit`.
  - State reset.

### 4.4 Trailing stop‑loss

**Current implementation:**

- SL is **not** trailed dynamically:
  - `current_sl` is set at initial entry and never adjusted when further pyramiding trades are added.
  - Comments mention “SL updated after pyramiding = average of entry prices” but actual code does not implement that; `current_sl` remains anchored to the initial ATR‑based level.

If you want a true trailing SL (e.g. tightening as price moves favorably), that would require:

- A new rule that, on each candle (or when pyramiding), recalculates `current_sl` from new highs/lows or an ATR band and only moves it in the direction of risk reduction (never loosening).

---

## 5. Pyramiding Logic

### 5.1 When pyramiding is allowed

Pyramiding is checked **every candle close** when a position is open:

- `current_position != None`.
- From settings:
  - `PyramidingDistance > 0`.
  - `PyramidingNumber > 0`.
- `first_entry_price` is known.

Maximum positions:

- `max_positions = 1 + PyramidingNumber`.
- New pyramiding entries are allowed only if:
  - `pyramiding_count < max_positions`.

### 5.2 Pyramiding trigger levels

Reference price:

- `reference_price = last_pyramiding_price` if set, else `first_entry_price`.

Next level:

- **BUY position**:
  - `next_pyramiding_level = reference_price + PyramidingDistance`.
  - Trigger if `ha_close >= next_pyramiding_level`.

- **SELL position**:
  - `next_pyramiding_level = reference_price - PyramidingDistance`.
  - Trigger if `ha_close <= next_pyramiding_level`.

Once triggered, a new pyramiding position is considered.

### 5.3 Option selection for pyramiding

Steps:

1. Get `initial_option_symbol` (from the first entry) and `option_exchange`.
2. Retrieve settings (`StrikeStep`, `StrikeNumber`, `Expiry`).
3. Determine fresh underlying LTP for `FutureSymbol`:
   - Via `find_exchange_for_symbol` + `get_ltp`.
   - Fallback to `ha_close` if LTP missing.
4. Compute `atm` and `all_strikes` as before.
5. Filter strikes:
   - For BUY: `filtered_strikes = strikes ≤ atm`, option type `CE`.
   - For SELL: `filtered_strikes = strikes ≥ atm`, option type `PE`.
6. Use `find_option_with_max_delta` again to pick best option around this new LTP.

If successful:

- Use the newly selected option symbol.

If selection fails:

- Fallback to using `initial_option_symbol` for pyramiding.

### 5.4 Placing pyramiding orders

If `final_option_symbol` and `option_exchange` / `kite_client` ready:

- Get current option LTP via `get_option_quote`.
- Place a **BUY LIMIT** order:
  - `exchange = option_exchange`.
  - `option_symbol = final_option_symbol`.
  - `transaction_type = "BUY"`.
  - `quantity = Lotsize`.
  - `order_type = "LIMIT"`.
  - `product = "NRML"`.
  - `price = option_ltp`.

State updates (always, regardless of order success):

- `pyramiding_count += 1` (this counts initial + all adds).
- `last_pyramiding_price = ha_close`.
- Append to `pyramiding_positions`:
  - `option_symbol = final_option_symbol`.
  - `order_id = order_response.order_id` (if any).
  - `entry_price = ha_close`.
  - `entry_option_price = option_ltp` or `0`.
- Append `ha_close` to `entry_prices` (for reference only).
- **SL is not changed**:
  - `current_sl` stays equal to initial ATR‑based SL and is not recomputed from average of entries.

Logging:

- Very detailed “PYRAMIDING TRADE PLACED” log:
  - Position number (`#pyramiding_count` of `max_positions`).
  - Symbol, option, whether strike was NEW or FALLBACK.
  - Entry price, first entry price, reference price.
  - Price movement from first entry (absolute and %).
  - Pyramiding level and distance.
  - Order id, lots, total positions count.

### 5.5 CSV logging for pyramiding entries

After each pyramiding add:

- Compute position number:
  - `position_num = pyramiding_count` (1=initial, 2=first pyramiding, etc.).
- `action` string:
  - For BUY: `pyramiding trade buy (position_num - 1)`.
  - For SELL: `pyramiding trade sell (position_num - 1)`.
- `write_to_signal_csv()` with:
  - `optionprice = option LTP used (or 0)`.
  - `optioncontract = final_option_symbol`.
  - `futurecontract = FutureSymbol`.
  - `futureprice = ha_close`.
  - `lotsize = Lotsize`.
  - `stop_loss = None` (entries).
  - `position_num = position_num - 1` for logging label `(1), (2), ...`.

Again, this is logged even if broker order was rejected.

---

## 6. Reporting and Logging

### 6.1 `OrderLog.txt`

All significant events are logged with timestamps:

- Arming / reset of BUY and SELL.
- Entries (BUY/SELL, pyramiding).
- SL exits and ST exits (detailed breakdown per leg).
- Option selection details (deltas, IVs, strikes).
- Broker responses and errors (including from Fyers integration, if used elsewhere).

### 6.2 `signal.csv`

Headers (ensured via `initialize_signal_csv()`):

- `timestamp`, `action`, `optionprice`, `optioncontract`, `futurecontract`,
  `futureprice`, `lotsize`, `Stop loss`, `Margin`, `Points Captured`,
  `Charges`, `P&L (Abs.)`, `P&L (%)`.

Key behaviors:

- On **entries**:
  - `Stop loss` is left empty.
  - `Margin = optionprice × lotsize × 100` (for entries).
  - `Charges` empty.

- On **exits**:
  - `Points Captured` = difference between exit/entry future prices:
    - BUY: `exit_future - entry_future`.
    - SELL: `entry_future - exit_future`.
  - `P&L (Abs.)` and `P&L (%)` computed based on option entry/exit prices, lotsize, and default `charges=63`.

Actions written:

- `Armed Buy`, `Armed Sell`.
- `buy`, `sell`.
- `pyramiding trade buy (N)`, `pyramiding trade sell (N)`.
- `buyexit`, `sellexit`.
- `pyramiding trade buy (N) exit`, `pyramiding trade sell (N) exit`.

### 6.3 `data.csv`

On each strategy cycle, the latest `processed_df` (with HA and indicators) is written to `data.csv`:

- Uses a small retry loop in case the file is locked (e.g. open in Excel).
- Useful for external inspection / backtesting.

---

## 7. Scheduling & Looping

### 7.1 Timeframe resolution

- From the first configured symbol’s `Timeframe`, `get_timeframe_minutes()` computes candle duration in minutes.

### 7.2 Main loop

In `__main__`:

1. Print “Starting Zerodha Trading Bot”.
2. Load existing state (`load_trading_state()`).
3. Login to Zerodha (`zerodha_login()`).
4. Load trade settings (`get_user_settings()`).
5. Initialize `signal.csv` (`initialize_signal_csv()`).
6. Derive `timeframe_minutes`.
7. Enter infinite loop:
   - At **approximately 9:00 AM**:
     - Auto‑login: call `zerodha_login()` again, log event.
   - Compute `next_candle_time` using `get_next_candle_time(now, timeframe_minutes)`.
   - Sleep up to that time in 1‑second increments.
   - At each scheduled run:
     - Call `main_strategy()`:
       - Fetch historical candles for each symbol.
       - Recompute indicators.
       - Execute strategy for last candle (entries, pyramiding, exits).
       - Print a human‑readable summary (`display_trading_summary()`).
     - Save trading state (`save_trading_state()`).

Graceful shutdown:

- `KeyboardInterrupt`:
  - Save state and exit.
- Any fatal exception:
  - Attempt to save state and print traceback.

---

## 8. Current Behavior vs. Potential Enhancements

To clarify the **current** behavior vs. intended ideas mentioned in comments:

- **Single SL per direction**:
  - Only one `current_sl` is used per symbol/position (applies to initial + all pyramiding legs).
  - It is computed once at initial entry from ATR on the last 5 candles.

- **No implemented trailing SL**:
  - Despite some comments suggesting “updated after pyramiding = average of entry prices”, code does **not** move `current_sl` after initial entry.

- **State vs. broker reality**:
  - The strategy **marks positions and pyramiding trades as active** based purely on logical conditions, even if the broker rejects orders.
  - This makes paper/backtest logic consistent but can cause divergence from real broker positions if orders fail.

These gaps are the natural places to plug in your future requirements:

- Add a proper **trailing SL** mechanism.
- Synchronize **state with actual broker positions** if desired.
- Adjust **pyramiding rules** (number of adds, spacing, when to stop adding).

