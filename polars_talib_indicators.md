# Available Technical Indicators in polars_talib

**Note:** SuperTrend is NOT available in polars_talib - it must be implemented manually using ATR and custom logic.

## Overlap Studies (Moving Averages & Bands)
- `sma` - Simple Moving Average
- `ema` - Exponential Moving Average
- `dema` - Double Exponential Moving Average
- `tema` - Triple Exponential Moving Average
- `trima` - Triangular Moving Average
- `wma` - Weighted Moving Average
- `kama` - Kaufman Adaptive Moving Average
- `mama` - MESA Adaptive Moving Average
- `t3` - Triple Exponential Moving Average (T3)
- `mavp` - Moving Average with Variable Period
- `bbands` - Bollinger Bands
- `sar` - Parabolic SAR
- `sarext` - Parabolic SAR Extended
- `ht_trendline` - Hilbert Transform - Instantaneous Trendline
- `midpoint` - MidPoint over Period
- `midprice` - Midpoint Price over Period
- `ma` - Moving Average (generic)

## Momentum Indicators
- `adx` - Average Directional Movement Index
- `adxr` - Average Directional Movement Index Rating
- `apo` - Absolute Price Oscillator
- `aroon` - Aroon
- `aroonosc` - Aroon Oscillator
- `bop` - Balance Of Power
- `cci` - Commodity Channel Index
- `cmo` - Chande Momentum Oscillator
- `dx` - Directional Movement Index
- `macd` - Moving Average Convergence/Divergence
- `macdext` - MACD with Controllable MA Type
- `macdfix` - MACD Fix 12/26
- `mfi` - Money Flow Index
- `minus_di` - Minus Directional Indicator
- `minus_dm` - Minus Directional Movement
- `mom` - Momentum
- `plus_di` - Plus Directional Indicator
- `plus_dm` - Plus Directional Movement
- `ppo` - Percentage Price Oscillator
- `roc` - Rate of Change
- `rocp` - Rate of Change Percentage
- `rocr` - Rate of Change Ratio
- `rocr100` - Rate of Change Ratio 100 Scale
- `rsi` - Relative Strength Index
- `stoch` - Stochastic
- `stochf` - Stochastic Fast
- `stochrsi` - Stochastic Relative Strength Index
- `trix` - TRIX
- `ultosc` - Ultimate Oscillator
- `willr` - Williams' %R

## Volume Indicators
- `ad` - Chaikin A/D Line
- `adosc` - Chaikin A/D Oscillator
- `obv` - On Balance Volume

## Volatility Indicators
- `atr` - Average True Range
- `natr` - Normalized Average True Range
- `trange` - True Range
- `stddev` - Standard Deviation
- `var` - Variance

## Price Transform
- `avgprice` - Average Price
- `medprice` - Median Price
- `typprice` - Typical Price
- `wclprice` - Weighted Close Price

## Cycle Indicators
- `ht_dcperiod` - Hilbert Transform - Dominant Cycle Period
- `ht_dcphase` - Hilbert Transform - Dominant Cycle Phase
- `ht_phasor` - Hilbert Transform - Phasor Components
- `ht_sine` - Hilbert Transform - SineWave
- `ht_trendmode` - Hilbert Transform - Trend vs Cycle Mode

## Pattern Recognition (Candlestick Patterns)
- `cdl2crows` - Two Crows
- `cdl3blackcrows` - Three Black Crows
- `cdl3inside` - Three Inside Up/Down
- `cdl3linestrike` - Three-Line Strike
- `cdl3outside` - Three Outside Up/Down
- `cdl3starsinsouth` - Three Stars In The South
- `cdl3whitesoldiers` - Three Advancing White Soldiers
- `cdlabandonedbaby` - Abandoned Baby
- `cdladvanceblock` - Advance Block
- `cdlbelthold` - Belt-hold
- `cdlbreakaway` - Breakaway
- `cdlclosingmarubozu` - Closing Marubozu
- `cdlconcealbabyswall` - Concealing Baby Swallow
- `cdlcounterattack` - Counterattack
- `cdldarkcloudcover` - Dark Cloud Cover
- `cdldoji` - Doji
- `cdldojistar` - Doji Star
- `cdldragonflydoji` - Dragonfly Doji
- `cdlengulfing` - Engulfing Pattern
- `cdleveningdojistar` - Evening Doji Star
- `cdleveningstar` - Evening Star
- `cdlgapsidesidewhite` - Up/Down-gap side-by-side white lines
- `cdlgravestonedoji` - Gravestone Doji
- `cdlhammer` - Hammer
- `cdlhangingman` - Hanging Man
- `cdlharami` - Harami Pattern
- `cdlharamicross` - Harami Cross Pattern
- `cdlhighwave` - High-Wave Candle
- `cdlhikkake` - Hikkake Pattern
- `cdlhikkakemod` - Modified Hikkake Pattern
- `cdlhomingpigeon` - Homing Pigeon
- `cdlidentical3crows` - Identical Three Crows
- `cdlinneck` - In-Neck Pattern
- `cdlinvertedhammer` - Inverted Hammer
- `cdlkicking` - Kicking
- `cdlkickingbylength` - Kicking - bull/bear determined by the longer marubozu
- `cdlladderbottom` - Ladder Bottom
- `cdllongleggeddoji` - Long Legged Doji
- `cdllongline` - Long Line Candle
- `cdlmarubozu` - Marubozu
- `cdlmatchinglow` - Matching Low
- `cdlmathold` - Mat Hold
- `cdlmorningdojistar` - Morning Doji Star
- `cdlmorningstar` - Morning Star
- `cdlonneck` - On-Neck Pattern
- `cdlpiercing` - Piercing Pattern
- `cdlrickshawman` - Rickshaw Man
- `cdlrisefall3methods` - Rising/Falling Three Methods
- `cdlseparatinglines` - Separating Lines
- `cdlshootingstar` - Shooting Star
- `cdlshortline` - Short Line Candle
- `cdlspinningtop` - Spinning Top
- `cdlstalledpattern` - Stalled Pattern
- `cdlsticksandwich` - Stick Sandwich
- `cdltakuri` - Takuri (Dragonfly Doji with very long lower shadow)
- `cdltasukigap` - Tasuki Gap
- `cdlthrusting` - Thrusting Pattern
- `cdltristar` - Tristar
- `cdlunique3river` - Unique 3 River
- `cdlupsidegap2crows` - Upside Gap Two Crows
- `cdlxsidegap3methods` - Upside/Downside Gap Three Methods

## Statistical Functions
- `beta` - Beta
- `correl` - Pearson's Correlation Coefficient
- `linearreg` - Linear Regression
- `linearreg_angle` - Linear Regression Angle
- `linearreg_intercept` - Linear Regression Intercept
- `linearreg_slope` - Linear Regression Slope
- `tsf` - Time Series Forecast
- `stddev` - Standard Deviation
- `var` - Variance
- `max` - Maximum value
- `min` - Minimum value
- `maxindex` - Index of maximum value
- `minindex` - Index of minimum value
- `minmax` - Minimum and Maximum values
- `minmaxindex` - Index of Minimum and Maximum values
- `sum` - Summation

## Math Functions
- `add` - Addition
- `sub` - Subtraction
- `mult` - Multiplication
- `div` - Division
- `acos` - Arc Cosine
- `asin` - Arc Sine
- `atan` - Arc Tangent
- `cos` - Cosine
- `cosh` - Hyperbolic Cosine
- `sin` - Sine
- `sinh` - Hyperbolic Sine
- `tan` - Tangent
- `tanh` - Hyperbolic Tangent
- `exp` - Exponential
- `ln` - Natural Logarithm
- `log10` - Base-10 Logarithm
- `sqrt` - Square Root
- `ceil` - Ceiling
- `floor` - Floor

## Note
**SuperTrend is NOT available in polars_talib** - it must be implemented manually using ATR and custom logic.

