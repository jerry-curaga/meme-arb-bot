"""
CEX/DEX Arbitrage Trading Bot
Quotes on Binance, executes swaps on Jupiter (Solana)
"""
import logging
import argparse
import asyncio

# Setup console logging - only show warnings/errors
logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Import modules
from config import TradingBotConfig
from bot.trading_bot import TradingBot
from commands.bot_commands import (
    test_binance_order,
    test_jupiter_swap,
    cmd_stop,
    cmd_balance,
    cmd_orders,
    cmd_close_all,
    cmd_liquidate,
    interactive_mode
)


async def main():
    parser = argparse.ArgumentParser(description='CEX/DEX Arbitrage Trading Bot')
    parser.add_argument('--mode', default='interactive',
                       choices=['interactive', 'trade', 'test-binance', 'test-jupiter', 'stop', 'balance', 'orders', 'close-all', 'liquidate'],
                       help='Operation mode (default: interactive)')
    parser.add_argument('--symbol', default='PIPPINUSDT',
                       help='Trading symbol (e.g., PIPPINUSDT)')
    parser.add_argument('--usd-amount', type=float, default=100.0,
                       help='USD amount to trade')

    args = parser.parse_args()

    config = TradingBotConfig()

    # Default to interactive mode
    if args.mode == 'interactive':
        await interactive_mode(config)

    elif args.mode == 'trade':
        logger.info(f"Starting arbitrage bot: {args.symbol} ${args.usd_amount:.2f} USD")
        bot = TradingBot(args.symbol, args.usd_amount, config)
        await bot.start()

    elif args.mode == 'test-binance':
        await test_binance_order(args.symbol, args.usd_amount, config)

    elif args.mode == 'test-jupiter':
        await test_jupiter_swap(config)

    elif args.mode == 'stop':
        await cmd_stop(config)

    elif args.mode == 'balance':
        await cmd_balance(args.symbol, config)

    elif args.mode == 'orders':
        await cmd_orders(args.symbol, config)

    elif args.mode == 'close-all':
        await cmd_close_all(args.symbol, config)

    elif args.mode == 'liquidate':
        await cmd_liquidate(args.symbol, config)


if __name__ == "__main__":
    asyncio.run(main())
