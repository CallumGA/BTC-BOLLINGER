import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime
import os
from dotenv import load_dotenv

# toggle between live trading and paper trading
PAPER_TRADING = True

load_dotenv()

exchange = ccxt.kucoin({
    'apiKey': os.getenv('KUCOIN_API_KEY'),
    'secret': os.getenv('KUCOIN_API_SECRET'),
    'password': os.getenv('KUCOIN_API_PASSPHRASE')
})

symbol = 'BTC/USDT'
timeframe = '15m'

initial_usdt = 1000
paper_balances = {'BTC': 0, 'USDT': initial_usdt}

trade_history = pd.DataFrame(columns=['Timestamp', 'Type', 'Price', 'Amount', 'Profit/Loss', 'USDT Balance', 'BTC Balance'])

def fetch_ohlcv(symbol, timeframe='15m', limit=100):
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    return df

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
        return 'hold'

while True:
    df = fetch_ohlcv(symbol, timeframe)
    action = trading_logic(df)
    price = exchange.fetch_ticker(symbol)['last']

    if PAPER_TRADING:
        btc_balance = paper_balances['BTC']
        usdt_balance = paper_balances['USDT']
    else:
        balance = exchange.fetch_balance()
        btc_balance = balance['BTC']['free']
        usdt_balance = balance['USDT']['free']

    print(f"Current Price: ${price:.2f}, Action: {action}")

    profit_loss = 0

    if action == 'buy' and usdt_balance > 50:
        amount = 50 / price
        if PAPER_TRADING:
            paper_balances['BTC'] += amount
            paper_balances['USDT'] -= 50
            print("Paper Bought BTC:", amount)

            new_trade = {
                'Timestamp': datetime.now(),
                'Type': 'Buy',
                'Price': price,
                'Amount': amount,
                'Profit/Loss': '-',
                'USDT Balance': paper_balances['USDT'],
                'BTC Balance': paper_balances['BTC']
            }

            trade_history = pd.concat([trade_history, pd.DataFrame([new_trade])], ignore_index=True)

    elif action == 'sell' and btc_balance > 0.001:
        total_usdt = btc_balance * price
        if PAPER_TRADING:
            profit_loss = total_usdt - (initial_usdt - paper_balances['USDT'])
            paper_balances['USDT'] += total_usdt
            print("Paper Sold BTC:", btc_balance)
            paper_balances['BTC'] = 0

            new_trade = {
                'Timestamp': datetime.now(),
                'Type': 'Sell',
                'Price': price,
                'Amount': btc_balance,
                'Profit/Loss': round(profit_loss, 2),
                'USDT Balance': paper_balances['USDT'],
                'BTC Balance': paper_balances['BTC']
            }

            trade_history = pd.concat([trade_history, pd.DataFrame([new_trade])], ignore_index=True)

    trade_history.to_csv('trade_history.csv', index=False)

    time.sleep(900)
