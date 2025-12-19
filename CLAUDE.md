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

**Interactive Mode (Recommended):**
```bash
# Start interactive interface (default mode)
python bot.py

# Use commands like:
# help, start, stop, balance, orders, set symbol BTCUSDT, etc.
```

**Command-Line Mode:**
```bash
# Direct trading
python bot.py --mode trade --symbol PIPPINUSDT --usd-amount 100.0

# Test commands
python bot.py --mode test-binance --symbol PIPPINUSDT --usd-amount 10.0
python bot.py --mode test-jupiter
```

### Management Commands
```bash
# Check account balances and positions
python bot.py --mode balance --symbol PIPPINUSDT

# View open orders
python bot.py --mode orders --symbol PIPPINUSDT

# Cancel all orders (safe)
python bot.py --mode close-all --symbol PIPPINUSDT

# Emergency liquidation (⚠️ CAUTION)
python bot.py --mode liquidate --symbol PIPPINUSDT

# Stop bot gracefully
python bot.py --mode stop
```

### Testing Workflow
1. Test Binance connectivity: `python bot.py --mode test-binance`
2. Test Jupiter quotes: `python bot.py --mode test-jupiter`
3. Run with small quantity: `python bot.py --quantity 10`

## Architecture

### Project Structure

The codebase is organized into modular components:

```
meme-arb-bot/
├── bot.py                         # Main entry point (77 lines)
├── config.py                      # TradingBotConfig class
├── managers/
│   ├── binance_manager.py         # Binance Futures API manager
│   └── jupiter_manager.py         # Jupiter DEX swap manager
├── bot/
│   ├── trading_bot.py             # Main trading bot orchestrator
│   └── status_display.py          # Real-time status display
├── commands/
│   └── bot_commands.py            # All commands & interactive mode
└── utils/
    └── logging_setup.py           # Logging configuration
```

### Core Components

1. **TradingBotConfig** (`config.py`) - Configuration management and environment variable validation
2. **BinanceManager** (`managers/binance_manager.py`) - Handles Binance Futures API operations (orders, pricing, precision)
3. **JupiterSwapManager** (`managers/jupiter_manager.py`) - Manages Jupiter DEX swaps on Solana (quotes, transaction building)
4. **TradingBot** (`bot/trading_bot.py`) - Main orchestrator that coordinates CEX/DEX arbitrage logic
5. **StatusDisplay** (`bot/status_display.py`) - Real-time status monitoring (use `recent` command)

### Trading Flow

1. Monitor Binance perpetual price for target symbol
2. Place sell order at 3% markup above market
3. Update order when market moves >0.5% (configurable)
4. On order fill: immediately execute corresponding buy on Jupiter
5. Capture spread as profit

### Key Configuration

Edit in `config.py` TradingBotConfig class:
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