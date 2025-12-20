# MEXC Integration Guide

## Overview

The bot now supports multiple CEX providers for perpetual futures trading. You can choose between:
- **Binance Futures** (default)
- **MEXC Futures**

Both exchanges can arbitrage against Jupiter DEX on Solana.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install the `pymexc` library along with other dependencies.

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Select CEX provider
CEX_PROVIDER=mexc  # or 'binance'

# MEXC API credentials (if using MEXC)
MEXC_API_KEY=your_mexc_api_key
MEXC_API_SECRET=your_mexc_api_secret

# Binance API credentials (if using Binance)
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# Solana and Jupiter (required for both)
SOLANA_PRIVATE_KEY=your_solana_private_key
JUPITER_API_KEY=your_jupiter_api_key
```

### 3. Configure Markets

MEXC uses different symbol formats than Binance:
- **Binance:** `BTCUSDT` (no separator)
- **MEXC:** `BTC_USDT` (underscore separator)

The bot automatically converts symbols between formats.

## MEXC-Specific Considerations

### Symbol Format

MEXC perpetual contracts use underscores in symbols:
- `BTC_USDT` instead of `BTCUSDT`
- `ETH_USDT` instead of `ETHUSDT`
- `PIPPIN_USDT` instead of `PIPPINUSDT`

The `MEXCManager` automatically normalizes symbols.

### Order Parameters

MEXC uses different order parameters:
- **side:**
  - `1` = open long
  - `2` = close short
  - `3` = open short (sell)
  - `4` = close long
- **type:**
  - `1` = limit order
  - `2` = market order
- **open_type:**
  - `1` = isolated margin
  - `2` = cross margin

### API Limitations

⚠️ **Important:** MEXC's order placement API has been under maintenance. The `pymexc` library provides a bypass method, but you should verify this works with your API keys.

### WebSocket Differences

MEXC WebSocket uses different message formats:
- Order status field: `state` (instead of Binance's `X`)
- Filled state value: `2` (instead of Binance's `'FILLED'`)
- Channel: `push.personal.order`

## Usage

### Run with MEXC

```bash
# Interactive mode
CEX_PROVIDER=mexc python cex_dex_bot.py

# Or set in .env file
python cex_dex_bot.py  # Uses CEX_PROVIDER from .env
```

### Test MEXC Connection

```bash
python cex_dex_bot.py --mode test-binance --symbol PIPPINUSDT
```

Note: Despite the mode name, this will test whichever CEX provider is configured.

## Architecture

### Manager Interface

Both `BinanceManager` and `MEXCManager` implement the same interface:

```python
class CEXManager:
    def get_current_price(symbol: str) -> float
    def place_limit_sell_order(symbol: str, usd_amount: float, price: float, market_price: float) -> dict
    def cancel_order(symbol: str, order_id: str) -> bool
    def check_order_filled(symbol: str, order_id: str) -> Optional[dict]
    def should_update_order(current_price: float, threshold: float) -> bool
    def get_open_orders(symbol: str) -> list
    async def start_user_stream(on_order_update: Callable)
    async def stop_user_stream()
```

### Dynamic Manager Selection

The `TradingBot` class automatically selects the correct manager:

```python
if config.cex_provider == 'binance':
    self.cex = BinanceManager(...)
elif config.cex_provider == 'mexc':
    self.cex = MEXCManager(...)
```

## Troubleshooting

### "MEXC order API under maintenance"

If you encounter this error, verify:
1. Your API keys have futures trading permissions
2. You have sufficient balance in your MEXC futures wallet
3. The `pymexc` bypass is working (check library version)

### Symbol Format Errors

If you see "symbol not found" errors:
- Ensure you're using the correct format in `markets.json`
- The bot auto-converts, but external tools may need underscore format

### WebSocket Not Receiving Updates

MEXC WebSocket requires:
1. Valid API credentials
2. Active internet connection
3. Proper channel subscription

Check logs for `WEBSOCKET_START` and connection status.

## Performance Comparison

Based on latency measurements:

| Metric | Binance | MEXC |
|--------|---------|------|
| REST API | ~400-500ms | TBD |
| WebSocket latency | ~instant | TBD |
| Order fill confirmation | instant | instant |

Run `python measure_latency.py` to test your specific latency.

## Future Enhancements

Potential improvements:
- [ ] Support for multiple CEX sources simultaneously
- [ ] Automatic CEX selection based on best price
- [ ] MEXC-specific order history queries
- [ ] Enhanced fill price tracking for MEXC
- [ ] Support for additional exchanges (OKX, Bybit, etc.)

## Sources

- [MEXC API Documentation](https://www.mexc.com/api-docs/futures/market-endpoints)
- [pymexc GitHub](https://github.com/makarworld/pymexc)
- [MEXC Contract API](https://mexcdevelop.github.io/apidocs/contract_v1_en/)
