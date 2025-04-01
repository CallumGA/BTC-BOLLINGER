import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timedelta, UTC
import os
from dotenv import load_dotenv
from coinbase.rest import RESTClient

CSV_PATH = os.path.abspath('trade_history.csv')
TRADING_PAIR = 'BTC-USDC'
TIMEFRAME = 'FIFTEEN_MINUTE'
ATR_PERIOD = 14
RISK_PER_TRADE_USDC = 40
MIN_TRADE_USDC = 10
PROFIT_CONVERT_THRESHOLD = 40

load_dotenv()
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET').replace('\\n', '\n')
client = RESTClient(api_key=api_key, api_secret=api_secret)

# Load trade history
if os.path.isfile(CSV_PATH):
    trade_history = pd.read_csv(CSV_PATH)
else:
    trade_history = pd.DataFrame(columns=[
        'Timestamp', 'Type', 'Price (USDC)', 'Amount',
        'Profit/Loss (USDC)', 'USDC Balance'
    ])

stop_loss_price = None
profit_accumulator = 0.0

def fetch_ohlcv(symbol, timeframe='FIFTEEN_MINUTE', limit=100):
    end = datetime.now(UTC)
    start = end - timedelta(minutes=15 * limit)

    candles = client.get_candles(
        product_id=symbol,
        granularity=timeframe,
        start=int(start.timestamp()),
        end=int(end.timestamp())
    )

    candle_data = [
        [
            candle['start'],
            candle['low'],
            candle['high'],
            candle['open'],
            candle['close'],
            candle['volume']
        ] for candle in candles['candles']
    ]

    print(f"Fetched {len(candle_data)} candles from {datetime.utcfromtimestamp(start.timestamp())} to {datetime.utcfromtimestamp(end.timestamp())}")

    df = pd.DataFrame(candle_data, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
    df = df.sort_values('time')
    df['time'] = pd.to_datetime(pd.to_numeric(df['time']), unit='s')
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

def trading_logic(df):
    global stop_loss_price

    df['RSI'] = ta.rsi(df['close'], length=14)
    bbands = ta.bbands(df['close'], length=20, std=2.0)
    atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)

    df = df.join([bbands, atr.rename('ATR')])
    latest = df.iloc[-1]

    print(f"[DEBUG] Close: {latest['close']:.2f}, BBL: {latest['BBL_20_2.0']:.2f}, BBU: {latest['BBU_20_2.0']:.2f}, RSI: {latest['RSI']:.2f}, ATR: {latest['ATR']:.2f}")

    if stop_loss_price and latest['close'] < stop_loss_price * 0.90:
        print("Stop loss triggered.")
        stop_loss_price = None
        return 'sell', latest['ATR']

    if latest['close'] <= latest['BBL_20_2.0'] * 1.01 and latest['RSI'] < 40:
        stop_loss_price = latest['close']
        return 'buy', latest['ATR']

    elif latest['close'] >= latest['BBU_20_2.0'] * 0.99 and latest['RSI'] > 60:
        stop_loss_price = None
        return 'sell', latest['ATR']

    return 'hold', latest['ATR']

def get_balances():
    accounts = client.get_accounts()
    btc_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'BTC'), 0))
    usdc_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'USDC'), 0))
    return btc_balance, usdc_balance

while True:
    try:
        df = fetch_ohlcv(TRADING_PAIR, TIMEFRAME)
        if df.isnull().values.any():
            print("⚠️ Missing values in indicators, skipping iteration.")
            time.sleep(60)
            continue

        action, current_atr = trading_logic(df)
        price = float(client.get_product(product_id=TRADING_PAIR)['price'])

    except Exception as e:
        print(f"⚠️ Error during data fetch or analysis: {e}")
        time.sleep(60)
        continue

    btc_balance, usdc_balance = get_balances()

    print(f"[DEBUG] Action: {action.upper()}, Stop Loss: {stop_loss_price}, ATR: {current_atr:.2f}")
    print(f"[DEBUG] USDC Balance: ${usdc_balance:.2f}, BTC Balance: {btc_balance:.8f}, Price: ${price:.2f}")

    if action == 'buy' and current_atr and current_atr > 0:
        stop_loss_pct = 0.05
        risk_per_unit = price * stop_loss_pct
        amount = RISK_PER_TRADE_USDC / risk_per_unit
        usdc_to_use = amount * price

        if usdc_to_use <= usdc_balance and usdc_to_use >= MIN_TRADE_USDC:
            try:
                client.create_order(
                    client_order_id=str(datetime.now().timestamp()),
                    product_id=TRADING_PAIR,
                    side='BUY',
                    order_type='MARKET',
                    funds=str(round(usdc_to_use, 2))
                )
                print(f"✅ Bought BTC worth ${round(usdc_to_use, 2)} at ${price:.2f}")
            except Exception as e:
                print(f"⚠️ Failed to execute BTC buy: {e}")

    elif action == 'sell' and btc_balance >= 0.00001:
        try:
            amount_to_sell = btc_balance
            total_usdc = amount_to_sell * price

            client.create_order(
                client_order_id=str(datetime.now().timestamp()),
                product_id=TRADING_PAIR,
                side='SELL',
                order_type='MARKET',
                size=str(amount_to_sell)
            )

            print(f"✅ Sold BTC: {amount_to_sell:.8f} for ~${total_usdc:.2f}")
            profit_accumulator += total_usdc

            new_trade = {
                'Timestamp': datetime.now(),
                'Type': 'Sell BTC',
                'Price (USDC)': price,
                'Amount': amount_to_sell,
                'Profit/Loss (USDC)': round(total_usdc, 2),
                'USDC Balance': round(usdc_balance, 2)
            }

            with open(CSV_PATH, 'a') as f:
                pd.DataFrame([new_trade]).to_csv(f, index=False, header=f.tell() == 0)

        except Exception as e:
            print(f"⚠️ Failed to execute BTC sell: {e}")

    # Profit conversion (optional future logic if needed)
    if profit_accumulator >= PROFIT_CONVERT_THRESHOLD:
        print(f"💰 Profit reached ${PROFIT_CONVERT_THRESHOLD}! Already in USDC, no further conversion needed.")
        profit_accumulator -= PROFIT_CONVERT_THRESHOLD

    print("-" * 60)
    time.sleep(900)