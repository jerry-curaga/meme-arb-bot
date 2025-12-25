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
from managers.okx_dex_manager import OKXDexManager
from bot.trading_bot import TradingBot
from config import TradingBotConfig, get_market_config
from utils.logging_setup import orders_logger, trades_logger
from web3 import Web3

logger = logging.getLogger(__name__)


async def test_binance_order(symbol: str, usd_amount: float, config: TradingBotConfig, limit_price: float = None):
    """Place a CEX order"""
    print(f"\n=== Placing CEX Order ({symbol}, ${usd_amount:.2f} USD) ===")

    binance = BinanceManager(config.binance_api_key, config.binance_api_secret)

    try:
        # Get current price
        price = binance.get_current_price(symbol)
        if not price:
            print("❌ Failed to get price")
            return

        # Use provided limit price or default to 2% above market
        if limit_price:
            test_price = limit_price
            print(f"Using provided limit price: ${test_price:.8f}")
        else:
            test_price = price * 1.02
            print(f"Using default limit price (2% above market): ${test_price:.8f}")
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



async def test_jupiter_swap(config: TradingBotConfig, usd_amount: float = 0.10, symbol: str = 'PIPPINUSDT'):
    """Execute a DEX swap (routes to Jupiter or OKX based on market config)"""
    print(f"\n=== Executing DEX Swap (${usd_amount:.2f} USDT) for {symbol} ===")

    try:
        # Get market configuration
        try:
            market = get_market_config(symbol)
            dex_provider = market.get('dex_provider', 'jupiter')
            dex_chain = market.get('dex_chain', 'solana')
            print(f"Market: {market['name']} - {market['description']}")
            print(f"DEX Provider: {dex_provider.upper()} on {dex_chain.upper()}")
        except (ValueError, KeyError) as e:
            print(f"❌ Failed to get market configuration for {symbol}: {e}")
            return

        # Route to appropriate DEX
        if dex_provider == 'jupiter':
            await _execute_jupiter_swap_command(config, market, usd_amount)
        elif dex_provider == 'okx':
            await _execute_okx_swap_command(config, market, usd_amount, dex_chain)
        else:
            print(f"❌ Unsupported DEX provider: {dex_provider}")

    except Exception as e:
        print(f"❌ Swap failed: {e}")
        logger.error(f"Swap failed: {e}")
        import traceback
        traceback.print_exc()


async def _execute_jupiter_swap_command(config: TradingBotConfig, market: dict, usd_amount: float):
    """Execute Jupiter swap"""
    jupiter = JupiterSwapManager(
        config.solana_private_key,
        config.jupiter_api_url,
        config.jupiter_api_key,
        config.max_slippage
    )

    input_mint = market.get('input_mint')
    output_mint = market.get('output_mint')

    if not input_mint or not output_mint:
        print("❌ Missing input_mint or output_mint for Jupiter swap")
        return

    print(f"Input mint: {input_mint}")
    print(f"Output mint: {output_mint}")

    # Convert USD amount to lamports (6 decimals for USDT/USDC)
    amount = int(usd_amount * 1e6)
    print(f"Amount: {amount} lamports (${usd_amount:.2f} USD)")

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


async def _execute_okx_swap_command(config: TradingBotConfig, market: dict, usd_amount: float, dex_chain: str):
    """Execute OKX DEX swap"""
    from managers.okx_dex_manager import OKXDexManager

    okx = OKXDexManager(
        api_key=config.okx_api_key,
        secret_key=config.okx_secret_key,
        passphrase=config.okx_passphrase,
        solana_private_key=config.solana_private_key if dex_chain == 'solana' else None,
        bsc_private_key=config.bsc_private_key if dex_chain == 'bsc' else None,
        max_slippage=config.max_slippage
    )

    # Get token addresses based on chain
    if dex_chain == 'bsc':
        input_token = market.get('input_token')
        output_token = market.get('output_token')
        decimals = 18  # BSC USDT
    elif dex_chain == 'solana':
        input_token = market.get('input_mint')
        output_token = market.get('output_mint')
        decimals = 6  # Solana USDC
    else:
        print(f"❌ Unsupported chain: {dex_chain}")
        return

    if not input_token or not output_token:
        print(f"❌ Missing token addresses for {dex_chain} swap")
        return

    print(f"Input token: {input_token}")
    print(f"Output token: {output_token}")

    # Convert USD amount to token base units
    amount = str(int(usd_amount * (10 ** decimals)))
    print(f"Amount: {amount} base units (${usd_amount:.2f} USD)")

    # Execute the swap
    print("\n1. Executing OKX DEX swap...")
    print(f"⚠️  This will actually execute the swap on {dex_chain.upper()}!")

    swap_result = await okx.swap(dex_chain, input_token, output_token, amount)

    if not swap_result or not swap_result.get('success'):
        print("❌ Failed to execute swap")
        return

    # Display results based on chain
    if dex_chain == 'bsc':
        tx_hash = swap_result.get('tx_hash')
        print(f"✓ BSC Swap executed successfully!")
        print(f"Transaction hash: {tx_hash}")
        print(f"View on BSCScan: https://bscscan.com/tx/{tx_hash}")
    elif dex_chain == 'solana':
        print(f"✓ Solana Swap executed successfully!")
        print(f"Signed transaction ready")


async def cmd_approve_token(symbol: str, config: TradingBotConfig, amount: float = None):
    """Approve token for DEX trading

    Args:
        symbol: Trading symbol (e.g., BEATUSDT)
        config: Bot configuration
        amount: Amount to approve (None = unlimited)
    """
    print(f"\n=== Approving Token for {symbol} ===")

    try:
        # Get market configuration
        market = get_market_config(symbol)
        dex_provider = market.get('dex_provider', 'jupiter')
        dex_chain = market.get('dex_chain', 'solana')

        print(f"Market: {market['name']}")
        print(f"DEX Provider: {dex_provider.upper()} on {dex_chain.upper()}")

        # Only EVM chains need approval
        if dex_chain != 'bsc':
            print(f"⚠️  Token approval not needed for {dex_chain.upper()}")
            print(f"   Solana uses different mechanism (no approval required)")
            return

        # BSC token approval
        if dex_chain == 'bsc':
            await _approve_bsc_token(config, market, amount)
        else:
            print(f"❌ Unsupported chain: {dex_chain}")

    except Exception as e:
        print(f"❌ Approval failed: {e}")
        logger.error(f"Approval failed: {e}")
        import traceback
        traceback.print_exc()


async def _approve_bsc_token(config: TradingBotConfig, market: dict, amount: float = None):
    """Approve BSC token for OKX DEX router"""

    # Get token address
    token_address = market.get('input_token')
    if not token_address:
        print("❌ Missing input_token address")
        return

    print(f"\nToken to approve: {token_address}")

    # Initialize Web3
    rpc_url = 'https://bsc-dataseed1.binance.org'
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not config.bsc_private_key:
        print("❌ BSC_PRIVATE_KEY not configured in .env")
        return

    account = w3.eth.account.from_key(config.bsc_private_key)
    print(f"Wallet: {account.address}")

    # OKX DEX router address (from failed transaction)
    spender = '0x3156020dfF8D99af1dDC523ebDfb1ad2018554a0'
    print(f"Spender (OKX Router): {spender}")

    # ERC20 ABI (approve function)
    erc20_abi = [
        {
            "constant": False,
            "inputs": [
                {"name": "_spender", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [
                {"name": "_owner", "type": "address"},
                {"name": "_spender", "type": "address"}
            ],
            "name": "allowance",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function"
        }
    ]

    # Create token contract instance
    token_contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=erc20_abi
    )

    # Check current allowance
    try:
        current_allowance = token_contract.functions.allowance(
            account.address,
            Web3.to_checksum_address(spender)
        ).call()
        print(f"\nCurrent allowance: {current_allowance / 1e18:.6f} tokens")
    except Exception as e:
        print(f"⚠️  Could not check allowance: {e}")
        current_allowance = 0

    # Determine approval amount
    if amount is None:
        # Unlimited approval (max uint256)
        approve_amount = 2**256 - 1
        print(f"Approval amount: UNLIMITED (max uint256)")
    else:
        # Get token decimals
        try:
            decimals = token_contract.functions.decimals().call()
        except:
            decimals = 18  # Default to 18
        approve_amount = int(amount * (10 ** decimals))
        print(f"Approval amount: {amount} tokens ({approve_amount} base units)")

    # Build approval transaction
    print("\n📝 Building approval transaction...")

    try:
        nonce = w3.eth.get_transaction_count(account.address)
        gas_price = w3.eth.gas_price

        approve_txn = token_contract.functions.approve(
            Web3.to_checksum_address(spender),
            approve_amount
        ).build_transaction({
            'from': account.address,
            'gas': 100000,  # Standard approval gas limit
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': 56  # BSC mainnet
        })

        print(f"Gas Price: {gas_price / 1e9:.2f} Gwei")
        print(f"Estimated Cost: ~{(100000 * gas_price) / 1e18:.6f} BNB")

        # Sign transaction
        print("\n✍️  Signing transaction...")
        signed_txn = account.sign_transaction(approve_txn)

        # Send transaction
        print("📤 Sending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = tx_hash.hex()

        print(f"✓ Transaction sent: {tx_hash_hex}")
        print(f"View on BSCScan: https://bscscan.com/tx/{tx_hash_hex}")

        # Wait for confirmation
        print("\n⏳ Waiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] == 1:
            print(f"✅ Token approved successfully!")
            print(f"Gas used: {receipt['gasUsed']:,}")

            # Check new allowance
            new_allowance = token_contract.functions.allowance(
                account.address,
                Web3.to_checksum_address(spender)
            ).call()
            print(f"New allowance: {new_allowance / 1e18:.6f} tokens")
        else:
            print(f"❌ Transaction failed!")
            print(f"Receipt: {receipt}")

    except Exception as e:
        print(f"❌ Error during approval: {e}")
        import traceback
        traceback.print_exc()


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
            # Get market configuration
            try:
                market = get_market_config(symbol)
                input_mint = market['input_mint']
                output_mint = market['output_mint']
            except (ValueError, KeyError) as e:
                print(f"⚠️  Could not load market config for {symbol}: {e}")
                input_mint = "N/A"
                output_mint = "N/A"

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
    current_no_hedge = config.no_hedge_mode
    running_bot = None

    hedge_status = "OFF (CEX-only)" if current_no_hedge else "ON (full arbitrage)"
    print(f"""
╔══════════════════════════════════════╗
║        Meme Arbitrage Bot v2.0       ║
║     Interactive Command Interface    ║
╚══════════════════════════════════════╝

Current Settings:
  Symbol: {current_symbol} | USD: ${current_amount:.2f} | Markup: {current_markup:.4f}% | Threshold: {current_threshold:.4f}% | Slippage: {current_slippage:.4f}%
  Hedging: {hedge_status}

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
  cex-order <amt> [price] - Place CEX order (e.g., cex-order 10 or cex-order 10 0.42)
  dex-swap <amt>   - Execute DEX swap (e.g., dex-swap 10)

⚙️  SETTINGS:
  set symbol <SYM> - Change trading symbol (e.g., set symbol PIPPINUSDT)
  set amount <USD> - Change USD amount for both CEX and DEX (e.g., set amount 50.0)
  set markup <PCT> - Change perp order markup % above market (e.g., set markup 4.0)
  set threshold <PCT> - Change price change threshold % for order updates (e.g., set threshold 0.3)
  set slippage <PCT> - Change max slippage % for Jupiter swaps (e.g., set slippage 1.5)
  set nohedge <on/off> - Toggle no-hedge mode (CEX-only, skip DEX hedging)
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
                    if running_bot and running_bot.cex.current_price:
                        # Use cached price from running bot
                        price = running_bot.cex.current_price
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
                hedge_status = "OFF (CEX-only)" if current_no_hedge else "ON (full arbitrage)"
                print(f"""
Current Settings:
  Symbol: {current_symbol}
  USD Amount: ${current_amount:.2f} (used for both Binance perps and Jupiter DEX)
  Markup: {current_markup:.4f}% (perp order above market price)
  Threshold: {current_threshold:.4f}% (price change to update orders)
  Slippage: {current_slippage:.4f}% (max slippage for Jupiter swaps)
  Hedging: {hedge_status}
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
                            print(f"✅ Markup changed to {current_markup:.4f}%")
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
                            print(f"✅ Max slippage changed to {current_slippage:.4f}%")
                    except ValueError:
                        print("❌ Invalid slippage. Use decimal format (e.g., 1.5)")

                elif parts[1] == 'nohedge':
                    if parts[2] in ['on', 'true', '1', 'yes']:
                        if running_bot:
                            print("⚠️  Cannot change hedge mode while bot is running. Use 'stop' first.")
                        else:
                            current_no_hedge = True
                            config.no_hedge_mode = True
                            print("✅ No-hedge mode ENABLED: Bot will place CEX orders but skip DEX hedging")
                    elif parts[2] in ['off', 'false', '0', 'no']:
                        if running_bot:
                            print("⚠️  Cannot change hedge mode while bot is running. Use 'stop' first.")
                        else:
                            current_no_hedge = False
                            config.no_hedge_mode = False
                            print("✅ No-hedge mode DISABLED: Bot will execute full arbitrage (CEX + DEX)")
                    else:
                        print("❌ Invalid value. Use: on/off, true/false, yes/no, 1/0")

                else:
                    print("❌ Unknown setting. Use: set symbol|amount|markup|threshold|slippage|nohedge <value>")

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

            elif cmd == 'cex-order':
                # Parse amount and optional price
                if len(parts) < 2:
                    print("❌ Usage: cex-order <amount> [price]")
                    continue
                try:
                    amount = float(parts[1])
                    price = float(parts[2]) if len(parts) >= 3 else None
                    await test_binance_order(current_symbol, amount, config, price)
                except ValueError:
                    print("❌ Invalid amount or price. Usage: cex-order <amount> [price]")

            elif cmd == 'dex-swap':
                # Parse amount
                if len(parts) < 2:
                    print("❌ Usage: dex-swap <amount>")
                    continue
                try:
                    amount = float(parts[1])
                    await test_jupiter_swap(config, amount, current_symbol)
                except ValueError:
                    print("❌ Invalid amount. Usage: dex-swap <amount>")

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



