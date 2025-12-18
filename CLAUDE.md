# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a CEX/DEX arbitrage trading bot that executes profitable arbitrage between Binance perpetual futures and Jupiter DEX (Solana). The bot quotes on Binance at markup above market price and automatically executes corresponding buys on Jupiter when filled.

## Development Commands

### Setup
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env.example .env
```

### Running the Bot
```bash
# Run main arbitrage bot (default: PIPPINUSDT, qty 100)
python cex_dex_bot.py

# Custom symbol and quantity
python cex_dex_bot.py --symbol BTCUSDT --quantity 0.001
python cex_dex_bot.py --symbol SOLUSDT --quantity 10

# Test Binance orders (safe - places and cancels orders)
python cex_dex_bot.py --mode test-binance --symbol PIPPINUSDT --quantity 100

# Test Jupiter swap (safe - quote only, no execution)
python cex_dex_bot.py --mode test-jupiter
```

### Testing Workflow
1. Test Binance connectivity: `python cex_dex_bot.py --mode test-binance`
2. Test Jupiter quotes: `python cex_dex_bot.py --mode test-jupiter`
3. Run with small quantity: `python cex_dex_bot.py --quantity 10`

## Architecture

### Core Components

The bot consists of 4 main classes in `cex_dex_bot.py`:

1. **TradingBotConfig** - Configuration management and environment variable validation
2. **BinanceManager** - Handles Binance Futures API operations (orders, pricing, precision)
3. **JupiterSwapManager** - Manages Jupiter DEX swaps on Solana (quotes, transaction building)
4. **TradingBot** - Main orchestrator that coordinates CEX/DEX arbitrage logic

### Trading Flow

1. Monitor Binance perpetual price for target symbol
2. Place sell order at 3% markup above market
3. Update order when market moves >0.5% (configurable)
4. On order fill: immediately execute corresponding buy on Jupiter
5. Capture spread as profit

### Key Configuration

Edit in `TradingBotConfig` class:
- `mark_up_percent` (default: 3.0) - Markup above market price
- `price_change_threshold` (default: 0.5) - % change to trigger order update
- `max_slippage` (default: 1.0) - Max slippage for Jupiter swaps

## Environment Variables

Required variables in `.env`:
- `BINANCE_API_KEY`, `BINANCE_API_SECRET` - Binance Futures API credentials
- `SOLANA_PRIVATE_KEY` - Solana wallet private key (base58 format)
- `JUPITER_API_KEY` - Jupiter Ultra API key
- `BUY_INPUT_MINT`, `BUY_OUTPUT_MINT` - Solana token mint addresses

## Dependencies

- **python-binance** - Binance API client
- **solders** - Solana SDK for transaction building
- **aiohttp** - Async HTTP for Jupiter API calls
- **base58** - Key encoding for Solana
- **python-dotenv** - Environment variable management

## Important Notes

- Bot requires Binance Futures API enabled and funded USD-M Futures wallet
- Solana wallet needs SOL for transaction fees (~0.0003 SOL per swap)
- Start testing with small amounts (10-100 USDT) before scaling
- Monitor logs for fills, swaps, and any errors
- Break-even spread is ~0.5-1% after all fees (Binance ~0.02%, Jupiter ~0.25%)