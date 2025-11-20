import pandas as pd

# Read the CSV file
df = pd.read_csv('data.csv')
df['date'] = pd.to_datetime(df['date'])

# Filter out rows where supertrend_trend is NaN
df_valid = df[df['supertrend_trend'].notna()].copy()

print("=" * 80)
print("SUPERTREND TREND DETECTION VERIFICATION")
print("=" * 80)

# Check for cases where price breaks above final_upper but trend is still -1
df_valid['prev_trend'] = df_valid['supertrend_trend'].shift(1)
df_valid['should_flip_to_green'] = (df_valid['ha_close'] >= df_valid['final_upper']) & (df_valid['prev_trend'] == -1.0)
df_valid['should_flip_to_red'] = (df_valid['ha_close'] <= df_valid['final_lower']) & (df_valid['prev_trend'] == 1.0)

print("\nCases where price >= final_upper but trend should flip to GREEN:")
flip_to_green = df_valid[df_valid['should_flip_to_green']]
print(f"Found {len(flip_to_green)} cases")
if len(flip_to_green) > 0:
    print("\nFirst 20 cases:")
    for idx, row in flip_to_green.head(20).iterrows():
        print(f"{row['date']} | Close: {row['ha_close']:.2f} >= Final_Upper: {row['final_upper']:.2f} | Prev_Trend: {row['prev_trend']} | Actual_Trend: {row['supertrend_trend']}")

print("\n\nCases where price <= final_lower but trend should flip to RED:")
flip_to_red = df_valid[df_valid['should_flip_to_red']]
print(f"Found {len(flip_to_red)} cases")
if len(flip_to_red) > 0:
    print("\nFirst 20 cases:")
    for idx, row in flip_to_red.head(20).iterrows():
        print(f"{row['date']} | Close: {row['ha_close']:.2f} <= Final_Lower: {row['final_lower']:.2f} | Prev_Trend: {row['prev_trend']} | Actual_Trend: {row['supertrend_trend']}")

# Check statistics
print("\n\n" + "=" * 80)
print("STATISTICS")
print("=" * 80)
print(f"Total rows with SuperTrend: {len(df_valid)}")
print(f"Rows with trend = 1.0 (GREEN): {len(df_valid[df_valid['supertrend_trend'] == 1.0])}")
print(f"Rows with trend = -1.0 (RED): {len(df_valid[df_valid['supertrend_trend'] == -1.0])}")

# Check if price ever goes above final_upper
price_above_upper = df_valid[df_valid['ha_close'] > df_valid['final_upper']]
print(f"\nRows where ha_close > final_upper: {len(price_above_upper)}")
if len(price_above_upper) > 0:
    print("First 10 cases:")
    for idx, row in price_above_upper.head(10).iterrows():
        print(f"{row['date']} | Close: {row['ha_close']:.2f} > Final_Upper: {row['final_upper']:.2f} | Trend: {row['supertrend_trend']}")

# Check if price ever goes below final_lower
price_below_lower = df_valid[df_valid['ha_close'] < df_valid['final_lower']]
print(f"\nRows where ha_close < final_lower: {len(price_below_lower)}")
if len(price_below_lower) > 0:
    print("First 10 cases:")
    for idx, row in price_below_lower.head(10).iterrows():
        print(f"{row['date']} | Close: {row['ha_close']:.2f} < Final_Lower: {row['final_lower']:.2f} | Trend: {row['supertrend_trend']}")

# Check the range of values
print("\n\n" + "=" * 80)
print("VALUE RANGES")
print("=" * 80)
print(f"ha_close range: {df_valid['ha_close'].min():.2f} to {df_valid['ha_close'].max():.2f}")
print(f"final_upper range: {df_valid['final_upper'].min():.2f} to {df_valid['final_upper'].max():.2f}")
print(f"final_lower range: {df_valid['final_lower'].min():.2f} to {df_valid['final_lower'].max():.2f}")
