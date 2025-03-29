import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timedelta, UTC
import os
from dotenv import load_dotenv
from coinbase.rest import RESTClient

PAPER_TRADING = True

load_dotenv()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET').replace('\\n', '\n')

client = RESTClient(api_key=api_key, api_secret=api_secret)

symbol = 'BTC-USD'
timeframe = 'FIFTEEN_MINUTE'

initial_usd = 1000
RISK_PER_TRADE_USD = 25
ATR_PERIOD = 14
MIN_TRADE_USD = 10

paper_balances = {'BTC': 0, 'USD': initial_usd}
trade_history = pd.DataFrame(columns=['Timestamp', 'Type', 'Price (USD)', 'Amount', 'Profit/Loss (USD)', 'USD Balance', 'BTC Balance'])

stop_loss_price = None

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

    df = pd.DataFrame(candle_data, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
    df = df.sort_values('time')
    df['time'] = pd.to_datetime(pd.to_numeric(df['time']), unit='s')
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

def trading_logic(df):
    global stop_loss_price

    df['RSI'] = ta.rsi(df['close'], length=14)
    bbands = ta.bbands(df['close'], length=20, std=2.0)
    ma50 = ta.sma(df['close'], length=50)
    atr = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
    df = df.join([bbands, ma50.rename('MA50'), atr.rename('ATR')])

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    if stop_loss_price and latest['close'] < stop_loss_price * 0.95:
        print("Stop loss triggered.")
        return 'sell', latest['ATR']

    if latest['close'] <= latest['BBL_20_2.0'] and latest['RSI'] < 30 and latest['MA50'] > previous['MA50']:
        stop_loss_price = latest['close']
        return 'buy', latest['ATR']

    elif latest['close'] >= latest['BBU_20_2.0'] and latest['RSI'] > 70 and latest['MA50'] < previous['MA50']:
        stop_loss_price = None
        return 'sell', latest['ATR']

    return 'hold', latest['ATR']

while True:
    try:
        df = fetch_ohlcv(symbol, timeframe)
        action, current_atr = trading_logic(df)
        price = float(client.get_product(product_id=symbol)['price'])
    except Exception as e:
        print(f"⚠️ Error during data fetch or analysis: {e}")
        time.sleep(60)
        continue

    if PAPER_TRADING:
        btc_balance = paper_balances['BTC']
        usd_balance = paper_balances['USD']
    else:
        accounts = client.get_accounts()
        btc_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'BTC'), 0))
        usd_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'USD'), 0))

    print(f"Current Price: ${price:.2f}, Action: {action}")

    if action == 'buy' and current_atr and current_atr > 0:
        stop_loss_pct = 0.05
        risk_per_unit = price * stop_loss_pct
        max_position_size_usd = min(RISK_PER_TRADE_USD / stop_loss_pct, usd_balance)

        if max_position_size_usd >= MIN_TRADE_USD:
            amount = max_position_size_usd / price

            if PAPER_TRADING:
                paper_balances['BTC'] += amount
                paper_balances['USD'] -= max_position_size_usd
                print(f"Paper Bought BTC: {amount} for ${round(max_position_size_usd, 2)}")

                new_trade = {
                    'Timestamp': datetime.now(),
                    'Type': 'Buy',
                    'Price (USD)': price,
                    'Amount': amount,
                    'Profit/Loss (USD)': '-',
                    'USD Balance': round(paper_balances['USD'], 2),
                    'BTC Balance': round(paper_balances['BTC'], 8)
                }

                trade_history = pd.concat([trade_history, pd.DataFrame([new_trade])], ignore_index=True)
                trade_history.to_csv('trade_history.csv', index=False)
            else:
                client.create_order(client_order_id=str(datetime.now().timestamp()),
                                    product_id=symbol,
                                    side='BUY',
                                    order_type='MARKET',
                                    funds=str(round(max_position_size_usd, 2)))
                print(f"Bought BTC for ${round(max_position_size_usd, 2)}")

    elif action == 'sell' and btc_balance >= 0.00001:
        amount_to_sell = btc_balance
        total_usd = amount_to_sell * price

        if PAPER_TRADING:
            original_investment = initial_usd - paper_balances['USD']
            profit_loss_usd = total_usd - original_investment
            paper_balances['USD'] += total_usd
            paper_balances['BTC'] -= amount_to_sell
            print("Paper Sold BTC:", amount_to_sell)

            new_trade = {
                'Timestamp': datetime.now(),
                'Type': 'Sell',
                'Price (USD)': price,
                'Amount': amount_to_sell,
                'Profit/Loss (USD)': round(profit_loss_usd, 2),
                'USD Balance': round(paper_balances['USD'], 2),
                'BTC Balance': round(paper_balances['BTC'], 8)
            }

            trade_history = pd.concat([trade_history, pd.DataFrame([new_trade])], ignore_index=True)
            trade_history.to_csv('trade_history.csv', index=False)
            print("Sell trade successfully logged to CSV.")
        else:
            client.create_order(client_order_id=str(datetime.now().timestamp()),
                                product_id=symbol,
                                side='SELL',
                                order_type='MARKET',
                                size=str(amount_to_sell))
            print("Sold BTC:", amount_to_sell)

    time.sleep(900)