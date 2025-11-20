# Correct SuperTrend Algorithm

## Standard SuperTrend Formula

### Step 1: Calculate Basic Bands
- **Basic Upper Band** = (High + Low) / 2 + (Multiplier × ATR)
- **Basic Lower Band** = (High + Low) / 2 - (Multiplier × ATR)

### Step 2: Calculate Final Bands
- **Final Upper Band** = 
  - If Basic Upper Band < Previous Final Upper Band: use Basic Upper Band
  - Otherwise: keep Previous Final Upper Band
  - Formula: `min(Basic Upper Band, Previous Final Upper Band)`
  
- **Final Lower Band** = 
  - If Basic Lower Band > Previous Final Lower Band: use Basic Lower Band
  - Otherwise: keep Previous Final Lower Band
  - Formula: `max(Basic Lower Band, Previous Final Lower Band)`

### Step 3: Calculate SuperTrend Value and Trend
- **If previous trend was UPTREND (1) or SuperTrend was at final_lower:**
  - If Close > Final Lower Band: 
    - SuperTrend = Final Lower Band
    - Trend = 1 (Continue Uptrend)
  - If Close <= Final Lower Band:
    - SuperTrend = Final Upper Band
    - Trend = -1 (Flip to Downtrend)

- **If previous trend was DOWNTREND (-1) or SuperTrend was at final_upper:**
  - If Close < Final Upper Band:
    - SuperTrend = Final Upper Band
    - Trend = -1 (Continue Downtrend)
  - If Close >= Final Upper Band:
    - SuperTrend = Final Lower Band
    - Trend = 1 (Flip to Uptrend)

## Key Points
1. Final Upper Band can only **decrease** (shrink downward), never increase
2. Final Lower Band can only **increase** (expand upward), never decrease
3. Trend flips occur when price crosses the opposite band
4. The algorithm uses the **previous trend** to determine the current trend

