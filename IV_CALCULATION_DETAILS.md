# IV (Implied Volatility) Calculation Details

## Overview

This project calculates **Implied Volatility (IV)** using the **Black-Scholes inverse formula** through the `py_vollib` library. IV is calculated **real-time from the option's market price** (LTP - Last Traded Price).

## Calculation Method

### Library Used
- **`py_vollib`** - Python implementation of the Black-Scholes model
- Function: `py_vollib.black_scholes.implied_volatility.implied_volatility()`

### Formula (Black-Scholes Inverse)

The IV calculation uses the **inverse Black-Scholes formula**:

Given:
- **Option Market Price** (LTP) = Known
- **Underlying Price** (S) = Current LTP of underlying
- **Strike Price** (K) = Option strike
- **Time to Expiry** (T) = Years until expiration
- **Risk-free Rate** (r) = Interest rate
- **Option Type** = 'c' for Call, 'p' for Put

**Find:** σ (sigma) = Implied Volatility

The formula solves for σ in the Black-Scholes equation:
```
Option Price = f(S, K, T, r, σ, option_type)
```

Where:
- For **Call Options**: `C = S*N(d1) - K*e^(-r*T)*N(d2)`
- For **Put Options**: `P = K*e^(-r*T)*N(-d2) - S*N(-d1)`

And:
- `d1 = [ln(S/K) + (r + σ²/2)*T] / (σ*√T)`
- `d2 = d1 - σ*√T`
- `N(x)` = Cumulative standard normal distribution

## Implementation in Code

### Location
File: `main.py`  
Function: `find_option_with_max_delta()`  
Lines: ~1246-1313

### Step-by-Step Process

#### 1. Get Option Market Price (LTP)
```python
# Get option quote from Zerodha API
quote = get_option_quote(kite, exchange, option_symbol)
option_ltp_raw = quote.get('last_price', None)
option_ltp_float = float(option_ltp_raw)
```

#### 2. Validate LTP
```python
# Must have valid option LTP to calculate IV
if option_ltp_float is not None and option_ltp_float > 0:
    # Proceed with IV calculation
```

#### 3. Prepare Parameters
```python
# Convert option_type to py_vollib format
flag = 'c' if option_type == 'CE' else 'p'  # 'c' for call, 'p' for put

# Parameters:
# - price: option_ltp_float (option's market price)
# - S: ltp (underlying's current price)
# - K: float(strike) (strike price)
# - t: time_to_expiry (years until expiration)
# - r: risk_free_rate (interest rate: 10% for MCX, 6% for NFO)
# - flag: 'c' or 'p' (call or put)
```

#### 4. Calculate IV
```python
iv = implied_volatility(
    price=option_ltp_float,      # Option's market price (LTP)
    S=ltp,                       # Underlying's current price
    K=float(strike),             # Strike price
    t=time_to_expiry,            # Time to expiry in years
    r=risk_free_rate,            # Risk-free rate (0.10 for MCX, 0.06 for NFO)
    flag=flag                    # 'c' for call, 'p' for put
)
```

#### 5. IV Source Tracking
```python
iv_source = "py_vollib"  # Mark that IV was calculated using py_vollib
```

### Retry Logic

If IV calculation fails, the code implements a **retry mechanism**:

1. **Log the error**:
   ```python
   error_msg = f"IV CALCULATION FAILED | Strike: {strike} | Symbol: {option_symbol} | Initial LTP: {option_ltp_float:.2f} | Error: {str(iv_error)} | Attempting fresh LTP fetch..."
   ```

2. **Fetch fresh LTP**:
   ```python
   fresh_quote = get_option_quote(kite, exchange, option_symbol)
   fresh_ltp = fresh_quote.get('last_price', None)
   ```

3. **Retry IV calculation** with fresh LTP:
   ```python
   iv = implied_volatility(
       price=fresh_ltp_float,    # Use fresh LTP
       S=ltp,
       K=float(strike),
       t=time_to_expiry,
       r=risk_free_rate,
       flag=flag
   )
   ```

4. **Log success**:
   ```python
   success_msg = f"IV CALCULATION RETRY SUCCESS | Strike: {strike} | Symbol: {option_symbol} | Fresh LTP: {fresh_ltp_float:.2f} | Calculated IV: {iv*100:.2f}%"
   ```

### Error Handling

If IV calculation fails:
- **Strike is skipped** (not considered for option selection)
- **Error is logged** to `OrderLog.txt`
- **No default IV** is used (strict validation)

## Parameters Used

### Risk-Free Rates
- **MCX (Commodities)**: 10% (0.10)
- **NFO (Equity Options)**: 6% (0.06)

### Time to Expiry
Calculated as:
```python
expiry_date = datetime.strptime(expiry, "%d-%m-%Y")
current_date = datetime.now()
time_to_expiry = (expiry_date - current_date).total_seconds() / (365.25 * 24 * 3600)
```
Result is in **years** (e.g., 0.0940 years = ~34 days)

### Underlying Price (S)
- Fetched from Zerodha API using `get_ltp()`
- Uses the **future symbol's LTP** (not spot)
- Example: For CRUDEOIL, uses `CRUDEOIL25DECFUT` LTP

### Strike Price (K)
- Directly from the strike list
- Example: 5300, 5350, 5400, etc.

### Option Price
- **Real-time market price** (LTP) from Zerodha API
- Retrieved via `get_option_quote()` function
- Must be > 0 for calculation to proceed

## IV Output Format

- **IV is stored as decimal**: e.g., 0.3218 = 32.18%
- **Displayed as percentage**: e.g., "32.18%"
- **Logged with source**: e.g., "IV: 32.18% (py_vollib)"

## Example Calculation

### Input Parameters:
```
Option Symbol: CRUDEOIL25DEC5350PE
Option LTP: 196.30
Underlying LTP: 5326.00
Strike: 5350
Time to Expiry: 0.0940 years (34 days)
Risk-free Rate: 10% (0.10) for MCX
Option Type: Put ('p')
```

### Calculation:
```python
iv = implied_volatility(
    price=196.30,        # Option market price
    S=5326.00,           # Underlying price
    K=5350.00,           # Strike price
    t=0.0940,            # Time to expiry (years)
    r=0.10,              # Risk-free rate (10%)
    flag='p'             # Put option
)
```

### Result:
```
IV = 0.3218 = 32.18%
```

## Important Notes

1. **No Default IV**: The code does NOT use default IV values. If calculation fails, the strike is skipped.

2. **Real-time Calculation**: IV is calculated from **current market prices**, not historical data.

3. **Strict Validation**: 
   - Option LTP must be > 0
   - IV must be > 0 after calculation
   - If validation fails, strike is skipped

4. **Retry Mechanism**: If initial calculation fails, the code:
   - Fetches fresh LTP from API
   - Retries calculation once
   - Logs both failure and success

5. **IV Source Tracking**: All IV values are tagged with source:
   - `"py_vollib"` - Calculated using py_vollib library
   - `"N/A"` - Not calculated (strike skipped)

6. **No API IV Fallback**: The code does NOT use Zerodha API's IV even if available. It always calculates from market price.

## Logging

IV calculations are logged to `OrderLog.txt`:

**Success:**
```
[2025-11-20 15:55:06] DELTA CALCULATION | Option Type: PE | Underlying: CRUDEOIL | LTP: 5326.00 | ATM Strike: 5350 | Time to Expiry: 0.0940 years | Risk-free Rate: 10.00%
[2025-11-20 15:55:06]   Strike: 5350 | Symbol: CRUDEOIL25DEC5350PE | Delta: -0.460552 (py_vollib) | IV: 32.18% (py_vollib) | LTP: 196.30 | ✓ SELECTED
```

**Failure with Retry:**
```
[2025-11-20 15:55:04] IV CALCULATION FAILED | Strike: 5350 | Symbol: CRUDEOIL25DEC5350PE | Initial LTP: 196.30 | Error: [Errno 2] No such file or directory: '...' | Attempting fresh LTP fetch...
[2025-11-20 15:55:05] IV CALCULATION RETRY SUCCESS | Strike: 5350 | Symbol: CRUDEOIL25DEC5350PE | Fresh LTP: 196.30 | Calculated IV: 32.18%
```

## Mathematical Background

The Black-Scholes model assumes:
- **Log-normal distribution** of stock prices
- **Constant volatility** (σ)
- **No dividends** (for simplicity)
- **Risk-free rate** is constant
- **No transaction costs**

The **implied volatility** is the value of σ that makes the Black-Scholes formula match the observed market price.

## Advantages of This Approach

1. **Real-time Accuracy**: Uses current market prices
2. **No Assumptions**: Doesn't rely on historical volatility
3. **Market-Driven**: Reflects current market sentiment
4. **Standard Method**: Uses industry-standard Black-Scholes model
5. **Transparent**: All calculations are logged

## Limitations

1. **Requires Valid LTP**: If option has no trades, IV cannot be calculated
2. **Model Assumptions**: Black-Scholes assumptions may not always hold
3. **Single Calculation**: No averaging or smoothing of IV
4. **No Volatility Smile**: Doesn't account for volatility skew

## Summary

**IV Calculation Flow:**
```
Get Option LTP (Market Price)
    ↓
Validate LTP > 0
    ↓
Calculate IV using py_vollib (Black-Scholes inverse)
    ↓
If fails → Fetch fresh LTP → Retry once
    ↓
If still fails → Skip strike
    ↓
If success → Use IV for delta calculation
```

**Key Points:**
- ✅ Uses **real-time market prices**
- ✅ Calculates using **Black-Scholes inverse formula**
- ✅ **No default IV** - strict validation
- ✅ **Retry mechanism** for reliability
- ✅ **Comprehensive logging** for debugging

