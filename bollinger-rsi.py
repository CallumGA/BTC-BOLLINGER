import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timedelta, UTC
import os
from dotenv import load_dotenv
from coinbase.rest import RESTClient

# Toggle between live trading and paper trading
PAPER_TRADING = True

load_dotenv()

# Coinbase Cloud API client
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET').replace('\\n', '\n')

client = RESTClient(api_key=api_key, api_secret=api_secret)

symbol = 'BTC-USD'
timeframe = 'FIFTEEN_MINUTE'

initial_usd = 1000
paper_balances = {'BTC': 0, 'USD': initial_usd}

trade_history = pd.DataFrame(columns=['Timestamp', 'Type', 'Price (USD)', 'Amount', 'Profit/Loss (USD)', 'USD Balance', 'BTC Balance'])

# Fetch historical candlestick data from Coinbase Cloud
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

# Determine trading action based on RSI and Bollinger Bands
def trading_logic(df):
    df['RSI'] = ta.rsi(df['close'], length=14)
    bbands = ta.bbands(df['close'], length=20, std=2.0)
    df = df.join(bbands)

    latest = df.iloc[-1]

    if latest['close'] <= latest['BBL_20_2.0'] and latest['RSI'] < 30:
        return 'buy'
    elif latest['close'] >= latest['BBU_20_2.0'] and latest['RSI'] > 70:
        return 'sell'
    else:
        return 'sell'

while True:
    df = fetch_ohlcv(symbol, timeframe)
    action = trading_logic(df)
    price = float(client.get_product(product_id=symbol)['price'])

    if PAPER_TRADING:
        btc_balance = paper_balances['BTC']
        usd_balance = paper_balances['USD']
    else:
        accounts = client.get_accounts()
        btc_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'BTC'), 0))
        usd_balance = float(next((a['available_balance']['value'] for a in accounts['accounts'] if a['currency'] == 'USD'), 0))

    print(f"Current Price: ${price:.2f}, Action: {action}")

    if action == 'buy' and usd_balance > 50:
        amount = 50 / price
        if PAPER_TRADING:
            paper_balances['BTC'] += amount
            paper_balances['USD'] -= 50
            print("Paper Bought BTC:", amount)

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
                                funds='50')
            print("Bought BTC for $50")

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
