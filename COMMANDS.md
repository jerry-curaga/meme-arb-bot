# Bot Management Commands

The meme arbitrage bot now supports management commands for controlling operations:

## Trading Commands

### Start Arbitrage Bot
```bash
python cex_dex_bot.py --mode trade --symbol PIPPINUSDT --usd-amount 100.0
```

### Test Commands
```bash
# Test Binance orders (safe)
python cex_dex_bot.py --mode test-binance --symbol PIPPINUSDT --usd-amount 10.0

# Test Jupiter swaps ($0.10 test)
python cex_dex_bot.py --mode test-jupiter
```

## Management Commands

### Stop Bot
```bash
python cex_dex_bot.py --mode stop
```
Gracefully stops any running bot instances.

### Check Balances
```bash
python cex_dex_bot.py --mode balance --symbol PIPPINUSDT
```
Shows:
- Binance Futures account balance and PnL
- Current perpetual positions
- Solana wallet address and token info

### View Open Orders
```bash
python cex_dex_bot.py --mode orders --symbol PIPPINUSDT
```
Lists all open orders with OrderID, side, quantity, price, and creation time.

### Close All Orders
```bash
python cex_dex_bot.py --mode close-all --symbol PIPPINUSDT
```
Cancels all open orders for the specified symbol. Logs each cancellation.

### Liquidate All Positions
```bash
python cex_dex_bot.py --mode liquidate --symbol PIPPINUSDT
```
⚠️ **WARNING**: This will:
1. Cancel all open orders
2. Close all perpetual positions with market orders
3. May result in losses due to market orders

## Logging

All management actions are logged to:
- `orders.log` - Order placements and cancellations
- `trades.log` - Position closures and liquidations

## Examples

```bash
# Check what's currently open
python cex_dex_bot.py --mode balance --symbol PIPPINUSDT
python cex_dex_bot.py --mode orders --symbol PIPPINUSDT

# Emergency stop everything
python cex_dex_bot.py --mode close-all --symbol PIPPINUSDT

# Complete liquidation (use with caution)
python cex_dex_bot.py --mode liquidate --symbol PIPPINUSDT
```