"""
Bot command functions
"""
import os
import json
import asyncio
import logging
from binance.exceptions import BinanceAPIException
from managers.binance_manager import BinanceManager
from managers.jupiter_manager import JupiterSwapManager
from bot.trading_bot import TradingBot
from config import TradingBotConfig
from utils.logging_setup import orders_logger, trades_logger

logger = logging.getLogger(__name__)


async def test_binance_order(symbol: str, usd_amount: float, config: TradingBotConfig):
    """Test Binance order placement and cancellation"""
    print(f"\n=== Testing Binance Order ({symbol}, ${usd_amount:.2f} USD) ===")

    binance = BinanceManager(config.binance_api_key, config.binance_api_secret)

    try:
        # Get current price
        price = binance.get_current_price(symbol)
        if not price:
            print("❌ Failed to get price")
            return

        # Place sell order at 2% above market
        test_price = price * 1.02
        order = binance.place_limit_sell_order(symbol, usd_amount, test_price, price)

        if not order:
            print("❌ Failed to place order")
            return

        order_id = order['orderId']
        print(f"✓ Order placed: {order_id}")

        # Wait a bit
        await asyncio.sleep(3)

        # Cancel order
        print(f"Cancelling order {order_id}...")
        try:
            binance.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            print(f"✓ Order cancelled successfully")
        except BinanceAPIException as e:
            print(f"❌ Error cancelling order: {e}")
            logger.error(f"Error cancelling order: {e}")
            return

        print("✓ Test completed successfully!\n")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        logger.error(f"Test failed: {e}")
        return



async def test_jupiter_swap(config: TradingBotConfig):
    """Test Jupiter swap with small amount ($0.10 USDT)"""
    print(f"\n=== Testing Jupiter Swap ($0.10 USDT) ===")

    try:
        jupiter = JupiterSwapManager(
            config.solana_private_key,
            config.jupiter_api_url,
            config.jupiter_api_key,
            config.max_slippage
        )

        # Get mints from env
        input_mint = os.getenv('BUY_INPUT_MINT')
        output_mint = os.getenv('BUY_OUTPUT_MINT')

        if not input_mint or not output_mint:
            print("❌ Missing BUY_INPUT_MINT or BUY_OUTPUT_MINT in .env")
            return

        print(f"Input mint: {input_mint}")
        print(f"Output mint: {output_mint}")

        # 0.10 USDT (6 decimals)
        amount = int(0.10 * 1e6)
        print(f"Amount: {amount} lamports")

        # Get order from Jupiter
        print("\n1. Getting order from Jupiter...")
        order = await jupiter.get_order(input_mint, output_mint, amount)

        if not order:
            print("❌ Failed to get order")
            return

        print(f"✓ Order received!")
        print(f"Transaction size: {len(order.get('transaction', ''))} chars")

        # Log order details (excluding large transaction field)
        order_info = {k: v for k, v in order.items() if k != 'transaction'}
        print(f"Order details: {json.dumps(order_info, indent=2)}")

        # Execute the swap
        print("\n2. Executing swap...")
        print("⚠️  This will actually execute the swap and cost SOL fees!")
        tx_hash = await jupiter.execute_swap(order)

        if not tx_hash:
            print("❌ Failed to execute swap")
            return

        print(f"✓ Swap executed successfully!")
        print(f"Transaction hash: {tx_hash}")
        print(f"View on Solscan: https://solscan.io/tx/{tx_hash}")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        logger.error(f"Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())



async def cmd_stop(config: TradingBotConfig):
    """Stop any running bot instances"""
    logger.info("🛑 Stop command - Bot stopping gracefully")
    # In a real implementation, this would signal running bot processes to stop
    # For now, just exit
    import sys
    sys.exit(0)



async def cmd_balance(symbol: str, config: TradingBotConfig):
    """Show balance of tokens and perpetual positions"""
    print(f"\n=== Balance Check for {symbol} ===")

    try:
        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
        jupiter = JupiterSwapManager(config.solana_private_key, config.jupiter_api_url, config.jupiter_api_key, config.max_slippage)

        # Get Binance futures account info
        try:
            account = binance.client.futures_account()
            total_balance = float(account.get('totalWalletBalance', 0))
            available_balance = float(account.get('availableBalance', 0))
            unrealized_pnl = float(account.get('totalUnrealizedProfit', 0))

            print(f"💰 Binance Futures Account:")
            print(f"   Total Balance: ${total_balance:.2f} USDT")
            print(f"   Available: ${available_balance:.2f} USDT")
            print(f"   Unrealized PnL: ${unrealized_pnl:.2f} USDT")

            # Get positions for the specific symbol
            positions = binance.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if float(pos['positionAmt']) != 0:
                    print(f"   {symbol} Position: {pos['positionAmt']} @ ${pos['entryPrice']} (PnL: ${pos['unRealizedProfit']})")
        except Exception as e:
            print(f"❌ Error getting Binance balance: {e}")
            logger.error(f"Error getting Binance balance: {e}")

        # Get Solana wallet balance
        try:
            input_mint = os.getenv('BUY_INPUT_MINT')
            output_mint = os.getenv('BUY_OUTPUT_MINT')

            print(f"🔗 Solana Wallet: {str(jupiter.keypair.pubkey())}")
            print(f"   Input Token (USDC): {input_mint}")
            print(f"   Output Token: {output_mint}")
            # Note: Getting actual token balances requires additional RPC calls
            print("   (Use Solscan to view detailed token balances)")

        except Exception as e:
            print(f"❌ Error getting Solana balance: {e}")
            logger.error(f"Error getting Solana balance: {e}")

    except Exception as e:
        print(f"❌ Balance check failed: {e}")
        logger.error(f"Balance check failed: {e}")



async def cmd_orders(symbol: str, config: TradingBotConfig):
    """Show all open orders"""
    print(f"\n=== Open Orders for {symbol} ===")

    try:
        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
        orders = binance.client.futures_get_open_orders(symbol=symbol)

        if not orders:
            print("📭 No open orders")
            return

        print(f"📋 Found {len(orders)} open order(s):")
        for order in orders:
            side = order['side']
            quantity = order['origQty']
            price = order['price']
            order_id = order['orderId']
            time_created = order['time']

            print(f"   OrderID: {order_id} | {side} {quantity} {symbol} @ ${price} | Created: {time_created}")

    except Exception as e:
        print(f"❌ Error getting orders: {e}")
        logger.error(f"Error getting orders: {e}")



async def cmd_close_all(symbol: str, config: TradingBotConfig):
    """Close all open orders"""
    print(f"\n=== Closing All Orders for {symbol} ===")

    try:
        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
        orders = binance.client.futures_get_open_orders(symbol=symbol)

        if not orders:
            print("📭 No open orders to close")
            return

        print(f"🗑️  Closing {len(orders)} order(s)...")
        for order in orders:
            try:
                result = binance.client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                print(f"   ✅ Cancelled OrderID: {order['orderId']}")
                orders_logger.info(f"ORDER_CANCELLED | Symbol: {symbol} | OrderID: {order['orderId']} | Reason: Manual_Close_All")
            except Exception as e:
                print(f"   ❌ Failed to cancel OrderID {order['orderId']}: {e}")
                logger.error(f"Failed to cancel OrderID {order['orderId']}: {e}")

    except Exception as e:
        print(f"❌ Error closing orders: {e}")
        logger.error(f"Error closing orders: {e}")



async def cmd_liquidate(symbol: str, config: TradingBotConfig):
    """Liquidate all tokens and perpetual positions"""
    print(f"\n=== Liquidating All Positions for {symbol} ===")
    print("⚠️  This will close all positions and may result in losses!")

    try:
        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)

        # Close all open orders first
        await cmd_close_all(symbol, config)

        # Get current positions
        positions = binance.client.futures_position_information(symbol=symbol)

        for pos in positions:
            position_amt = float(pos['positionAmt'])
            if position_amt != 0:
                # Close position with market order
                side = 'BUY' if position_amt < 0 else 'SELL'  # Opposite side to close
                quantity = abs(position_amt)

                try:
                    order = binance.client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type='MARKET',
                        quantity=quantity
                    )
                    print(f"   ✅ Closed position: {side} {quantity} {symbol} (OrderID: {order['orderId']})")
                    trades_logger.info(f"POSITION_CLOSED | Symbol: {symbol} | Binance_OrderID: {order['orderId']} | Side: {side} | Quantity: {quantity} | Type: MARKET | Reason: Liquidation")
                except Exception as e:
                    print(f"   ❌ Failed to close position: {e}")
                    logger.error(f"Failed to close position: {e}")

        # Note: Solana token liquidation would require additional implementation
        print("💡 Note: Solana token liquidation requires manual implementation via Jupiter")

    except Exception as e:
        print(f"❌ Liquidation failed: {e}")
        logger.error(f"Liquidation failed: {e}")



async def interactive_mode(config: TradingBotConfig):
    """Interactive command mode - wait for user commands"""
    current_symbol = 'PIPPINUSDT'
    current_amount = 100.0
    current_markup = config.mark_up_percent
    current_threshold = config.price_change_threshold
    current_slippage = config.max_slippage
    running_bot = None

    print(f"""
╔══════════════════════════════════════╗
║        Meme Arbitrage Bot v2.0       ║
║     Interactive Command Interface    ║
╚══════════════════════════════════════╝

Current Settings:
  Symbol: {current_symbol} | USD: ${current_amount:.2f} | Markup: {current_markup:.1f}% | Threshold: {current_threshold:.1f}% | Slippage: {current_slippage:.1f}%

Type 'help' for available commands or 'quit' to exit.
""")

    while True:
        try:
            # Use async input to allow bot tasks to run concurrently
            loop = asyncio.get_event_loop()
            command = await loop.run_in_executor(None, input, f"[{current_symbol}] $ ")
            command = command.strip().lower()

            if not command:
                continue

            parts = command.split()
            cmd = parts[0]

            if cmd in ['quit', 'exit', 'q']:
                if running_bot:
                    print("⚠️  Bot is still running. Use 'stop' command first.")
                    continue

                # Check for open orders before quitting
                try:
                    binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
                    open_orders = binance.get_open_orders(current_symbol)

                    if open_orders:
                        print(f"\n⚠️  You have {len(open_orders)} open order(s) for {current_symbol}:")
                        for order in open_orders:
                            print(f"   OrderID: {order['orderId']} | {order['side']} {order['origQty']} @ ${order['price']}")

                        close_orders = await loop.run_in_executor(None, input, "\n🗑️  Close all orders before exit? (yes/no): ")
                        if close_orders.lower() in ['yes', 'y']:
                            await cmd_close_all(current_symbol, config)
                            print("✅ All orders closed")
                        else:
                            print("ℹ️  Orders left open")
                except Exception as e:
                    logger.error(f"Error checking orders on exit: {e}")

                print("👋 Goodbye!")
                break

            elif cmd == 'help':
                print("""
Available Commands:

📊 MONITORING:
  balance          - Show account balances and positions
  orders           - List all open orders
  status           - Show current bot status
  recent           - Show last 10 bot actions and current state
  price            - Get current market price

🤖 TRADING:
  start            - Start arbitrage bot with current settings
  stop             - Stop running arbitrage bot
  test-binance     - Test Binance orders (safe)
  test-jupiter     - Test Jupiter swaps (safe)

⚙️  SETTINGS:
  set symbol <SYM> - Change trading symbol (e.g., set symbol PIPPINUSDT)
  set amount <USD> - Change USD amount for both CEX and DEX (e.g., set amount 50.0)
  set markup <PCT> - Change perp order markup % above market (e.g., set markup 4.0)
  set threshold <PCT> - Change price change threshold % for order updates (e.g., set threshold 0.3)
  set slippage <PCT> - Change max slippage % for Jupiter swaps (e.g., set slippage 1.5)
  show             - Show current settings

🛡️  RISK MANAGEMENT:
  close-all        - Cancel all open orders
  liquidate        - Emergency: close all positions (⚠️ CAUTION)

💡 EXAMPLES:
  price            - Check current market price
  start            - Start bot with current settings
  recent           - View last 10 bot actions
  set symbol SOLUSDT - Change to SOLUSDT
  set amount 25.0  - Trade with $25 USD
  set markup 5.0   - 5% markup for volatile tokens
  set threshold 0.2 - Update orders on 0.2% price moves
  set slippage 2.0 - Allow 2% slippage for low liquidity
  balance          - Check account status
  stop             - Stop the bot
""")

            elif cmd == 'status':
                if running_bot:
                    print(f"🟢 Bot is RUNNING - {current_symbol} ${current_amount:.2f} USD")
                else:
                    print(f"🔴 Bot is STOPPED - Settings: {current_symbol} ${current_amount:.2f} USD")

            elif cmd == 'recent':
                if running_bot and running_bot.status_display:
                    running_bot.status_display.display()
                else:
                    print("ℹ️  Bot is not running. No recent actions to display.")

            elif cmd == 'price':
                try:
                    if running_bot and running_bot.binance.current_price:
                        # Use cached price from running bot
                        price = running_bot.binance.current_price
                        print(f"💰 Current {current_symbol} price: ${price:.8f}")
                    else:
                        # Fetch fresh price
                        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
                        price = binance.get_current_price(current_symbol)
                        if price:
                            print(f"💰 Current {current_symbol} price: ${price:.8f}")
                        else:
                            print(f"❌ Failed to get price for {current_symbol}")
                except Exception as e:
                    print(f"❌ Error getting price: {e}")

            elif cmd == 'show':
                print(f"""
Current Settings:
  Symbol: {current_symbol}
  USD Amount: ${current_amount:.2f} (used for both Binance perps and Jupiter DEX)
  Markup: {current_markup:.1f}% (perp order above market price)
  Threshold: {current_threshold:.1f}% (price change to update orders)
  Slippage: {current_slippage:.1f}% (max slippage for Jupiter swaps)
  Bot Status: {'🟢 RUNNING' if running_bot else '🔴 STOPPED'}
""")

            elif cmd == 'set' and len(parts) >= 3:
                if parts[1] == 'symbol':
                    new_symbol = parts[2].upper()
                    if running_bot:
                        print("⚠️  Cannot change symbol while bot is running. Use 'stop' first.")
                    else:
                        current_symbol = new_symbol
                        print(f"✅ Symbol changed to {current_symbol}")

                elif parts[1] == 'amount':
                    try:
                        new_amount = float(parts[2])
                        if new_amount <= 0:
                            print("❌ Amount must be positive")
                            continue
                        if running_bot:
                            print("⚠️  Cannot change amount while bot is running. Use 'stop' first.")
                        else:
                            current_amount = new_amount
                            print(f"✅ USD amount changed to ${current_amount:.2f}")
                    except ValueError:
                        print("❌ Invalid amount. Use decimal format (e.g., 25.0)")

                elif parts[1] == 'markup':
                    try:
                        new_markup = float(parts[2])
                        if new_markup <= 0 or new_markup > 50:
                            print("❌ Markup must be between 0.1% and 50%")
                            continue
                        if running_bot:
                            print("⚠️  Cannot change markup while bot is running. Use 'stop' first.")
                        else:
                            current_markup = new_markup
                            config.mark_up_percent = new_markup
                            print(f"✅ Markup changed to {current_markup:.1f}%")
                    except ValueError:
                        print("❌ Invalid markup. Use decimal format (e.g., 3.5)")

                elif parts[1] == 'threshold':
                    try:
                        new_threshold = float(parts[2])
                        if new_threshold <= 0 or new_threshold > 10:
                            print("❌ Threshold must be between 0.1% and 10%")
                            continue
                        if running_bot:
                            print("⚠️  Cannot change threshold while bot is running. Use 'stop' first.")
                        else:
                            current_threshold = new_threshold
                            config.price_change_threshold = new_threshold
                            print(f"✅ Price change threshold changed to {current_threshold:.1f}%")
                    except ValueError:
                        print("❌ Invalid threshold. Use decimal format (e.g., 0.5)")

                elif parts[1] == 'slippage':
                    try:
                        new_slippage = float(parts[2])
                        if new_slippage <= 0 or new_slippage > 20:
                            print("❌ Slippage must be between 0.1% and 20%")
                            continue
                        if running_bot:
                            print("⚠️  Cannot change slippage while bot is running. Use 'stop' first.")
                        else:
                            current_slippage = new_slippage
                            config.max_slippage = new_slippage
                            print(f"✅ Max slippage changed to {current_slippage:.1f}%")
                    except ValueError:
                        print("❌ Invalid slippage. Use decimal format (e.g., 1.5)")

                else:
                    print("❌ Unknown setting. Use: set symbol|amount|markup|threshold|slippage <value>")

            elif cmd == 'start':
                if running_bot:
                    print("⚠️  Bot is already running. Use 'stop' first to restart.")
                else:
                    print(f"🚀 Starting arbitrage bot: {current_symbol} ${current_amount:.2f} USD")
                    running_bot = TradingBot(current_symbol, current_amount, config)
                    # Start bot in background task
                    asyncio.create_task(running_bot.start())
                    print("✅ Bot started in background! Use 'stop' to halt trading.")

            elif cmd == 'stop':
                if running_bot:
                    running_bot.running = False
                    running_bot = None
                    print("🛑 Bot stopped successfully")
                else:
                    print("ℹ️  Bot is not running")

            elif cmd == 'balance':
                await cmd_balance(current_symbol, config)

            elif cmd == 'orders':
                await cmd_orders(current_symbol, config)

            elif cmd == 'close-all':
                await cmd_close_all(current_symbol, config)

            elif cmd == 'liquidate':
                confirm = await loop.run_in_executor(None, input, "⚠️  WARNING: This will close all positions! Type 'YES' to confirm: ")
                if confirm == 'YES':
                    await cmd_liquidate(current_symbol, config)
                else:
                    print("❌ Liquidation cancelled")

            elif cmd == 'test-binance':
                await test_binance_order(current_symbol, current_amount, config)

            elif cmd == 'test-jupiter':
                await test_jupiter_swap(config)

            else:
                print(f"❌ Unknown command '{cmd}'. Type 'help' for available commands.")

        except KeyboardInterrupt:
            if running_bot:
                print("\n⚠️  Bot is still running. Use 'stop' command first.")
                continue
            print("\n👋 Goodbye!")
            break
        except EOFError:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")



