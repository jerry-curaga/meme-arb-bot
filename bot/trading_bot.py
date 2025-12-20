"""
Main trading bot orchestrator
"""
import os
import asyncio
import logging
from config import TradingBotConfig, get_market_config
from managers.binance_manager import BinanceManager
from managers.mexc_manager import MEXCManager
from managers.jupiter_manager import JupiterSwapManager
from bot.status_display import StatusDisplay
from utils.logging_setup import bot_logger, trades_logger

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, symbol: str, usd_amount: float, config: TradingBotConfig, enable_status_display: bool = True):
        self.symbol = symbol
        self.usd_amount = usd_amount  # USD amount to trade
        self.config = config

        # Create status display
        self.status_display = StatusDisplay(symbol, usd_amount) if enable_status_display else None

        # Initialize CEX manager based on provider
        if config.cex_provider == 'binance':
            logger.info(f"Using Binance as CEX provider")
            self.cex = BinanceManager(config.binance_api_key, config.binance_api_secret, self.status_display)
        elif config.cex_provider == 'mexc':
            logger.info(f"Using MEXC as CEX provider")
            self.cex = MEXCManager(config.mexc_api_key, config.mexc_api_secret, self.status_display)
        else:
            raise ValueError(f"Unsupported CEX provider: {config.cex_provider}")

        # Initialize Jupiter manager
        self.jupiter = JupiterSwapManager(
            config.solana_private_key,
            config.jupiter_api_url,
            config.jupiter_api_key,
            config.max_slippage
        )

        self.running = True
        self.order_filled = False

    async def validate_existing_orders(self) -> bool:
        """
        Check if there are existing open orders and validate if they're still appropriate.
        Returns True if we should place a new order, False if existing order is still valid.
        """
        open_orders = self.cex.get_open_orders(self.symbol)

        if not open_orders:
            logger.info("No existing orders found")
            bot_logger.info(f"STARTUP_CHECK | Symbol: {self.symbol} | No existing orders")
            return True  # No orders, should place new one

        # Get current market price
        current_price = self.cex.get_current_price(self.symbol)
        if not current_price:
            logger.error("Failed to get current price for order validation")
            return True  # If we can't get price, place new order anyway

        # Check each open order (should typically only be one for our bot)
        for order in open_orders:
            order_id = order['orderId']
            order_price = float(order['price'])
            order_side = order['side']
            order_qty = float(order['origQty'])

            # Calculate the reference price (market price when order was placed)
            # order_price = reference_price * (1 + markup/100)
            # reference_price = order_price / (1 + markup/100)
            reference_price = order_price / (1 + self.config.mark_up_percent / 100)

            logger.info(f"Found existing order {order_id}: {order_side} {order_qty} @ ${order_price:.8f} (ref price: ${reference_price:.8f})")
            bot_logger.info(f"STARTUP_CHECK | Symbol: {self.symbol} | Found order {order_id} | Order_Price: ${order_price:.8f} | Reference_Price: ${reference_price:.8f} | Current_Price: ${current_price:.8f}")

            # Calculate price change from reference
            price_change_pct = abs(current_price - reference_price) / reference_price * 100

            # Decide if we should cancel and replace
            should_cancel = False
            cancel_reason = ""

            # Case 1: Market moved significantly from reference price
            if price_change_pct >= self.config.price_change_threshold:
                should_cancel = True
                cancel_reason = f"Market moved {price_change_pct:.2f}% from reference (threshold: {self.config.price_change_threshold}%)"

            # Case 2: Current price is at or above our sell limit (order might fill soon at bad price)
            elif current_price >= order_price:
                should_cancel = True
                cancel_reason = f"Current price ${current_price:.8f} >= order price ${order_price:.8f}"

            # Case 3: Current price is very close to order price (within markup range)
            expected_order_price = current_price * (1 + self.config.mark_up_percent / 100)
            price_diff_pct = abs(expected_order_price - order_price) / order_price * 100
            if price_diff_pct > 1.0:  # If expected order price differs by more than 1%
                should_cancel = True
                cancel_reason = f"Order price ${order_price:.8f} differs {price_diff_pct:.2f}% from expected ${expected_order_price:.8f}"

            if should_cancel:
                logger.info(f"Cancelling existing order {order_id}: {cancel_reason}")
                bot_logger.info(f"STARTUP_CANCEL | Symbol: {self.symbol} | OrderID: {order_id} | Reason: {cancel_reason}")
                self.cex.cancel_order(self.symbol, order_id)
                return True  # Should place new order
            else:
                # Order is still valid, use it
                logger.info(f"Existing order {order_id} is still valid, keeping it")
                bot_logger.info(f"STARTUP_KEEP | Symbol: {self.symbol} | OrderID: {order_id} | Order still valid")
                self.cex.current_order_id = order_id
                self.cex.last_order_price = order_price
                self.cex.market_price_at_order = reference_price

                # Update status display
                if self.status_display:
                    self.status_display.set_order(order_id, order_price, order_qty)
                    self.status_display.add_action(f"📋 Kept existing order: ID={order_id} | ${order_price:.6f}")

                return False  # Don't place new order

        return True  # Default: place new order

    async def start(self):
        """Start the trading bot"""
        logger.info(f"Starting bot for {self.symbol}, USD amount: ${self.usd_amount:.2f}")

        # Log bot start
        bot_logger.info(f"BOT_START | Symbol: {self.symbol} | USD_Amount: ${self.usd_amount:.2f} | Markup: {self.config.mark_up_percent}% | Threshold: {self.config.price_change_threshold}% | Slippage: {self.config.max_slippage}%")

        # Initialize status display
        if self.status_display:
            self.status_display.start()
            self.status_display.add_action(f"🚀 Bot started: {self.symbol} | ${self.usd_amount:.2f} USD")

        # Check and validate existing orders
        should_place_new_order = await self.validate_existing_orders()

        if should_place_new_order:
            current_price = self.cex.get_current_price(self.symbol)
            if not current_price:
                logger.error("Failed to get initial price")
                bot_logger.error(f"BOT_ERROR | Failed to get initial price for {self.symbol}")
                return

            quote_price = current_price * (1 + self.config.mark_up_percent / 100)
            self.cex.place_limit_sell_order(self.symbol, self.usd_amount, quote_price, current_price)

        await asyncio.gather(
            self.monitor_prices(),
            self.monitor_order_fill_websocket()
        )

        # Log bot stop
        bot_logger.info(f"BOT_STOP | Symbol: {self.symbol}")
    
    async def monitor_prices(self):
        """Monitor price changes and update orders"""
        while self.running and not self.order_filled:
            try:
                current_price = self.cex.get_current_price(self.symbol)
                
                if current_price and self.cex.should_update_order(
                    current_price, 
                    self.config.price_change_threshold
                ):
                    logger.info(f"Market moved {self.config.price_change_threshold}% from {self.cex.market_price_at_order}, updating order")
                    
                    if self.cex.current_order_id:
                        self.cex.cancel_order(self.symbol, self.cex.current_order_id)
                    
                    new_quote_price = current_price * (1 + self.config.mark_up_percent / 100)
                    self.cex.place_limit_sell_order(self.symbol, self.usd_amount, new_quote_price, current_price)
                
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error in monitor_prices: {e}")
                await asyncio.sleep(5)
    
    async def monitor_order_fill_websocket(self):
        """Monitor order fills via WebSocket for instant notifications"""
        try:
            logger.info("Using WebSocket for real-time order fill monitoring")
            await self.cex.start_user_stream(self._handle_order_fill)
        except Exception as e:
            logger.error(f"WebSocket monitoring failed: {e}")
            logger.warning("Falling back to polling mode...")
            await self.monitor_order_fill()

    async def _handle_order_fill(self, filled_order: dict):
        """Handle order fill event from WebSocket

        Args:
            filled_order: Order data from Binance API
        """
        try:
            # Log CEX transaction (order fill)
            fill_price = float(filled_order.get('avgPrice', 0))
            fill_qty = float(filled_order.get('executedQty', 0))
            fill_usd_value = fill_price * fill_qty

            # Log with detailed precision to catch any calculation issues
            logger.info(f"Order filled: Price={fill_price:.8f}, Qty={fill_qty:.8f}, USD={fill_usd_value:.8f}")
            trades_logger.info(f"CEX_FILL | Symbol: {self.symbol} | Binance_OrderID: {filled_order['orderId']} | Fill_Price: {fill_price:.8f} | Fill_Qty: {fill_qty:.8f} | USD_Value: ${fill_usd_value:.6f} | Side: SELL")
            bot_logger.info(f"ORDER_FILLED | Symbol: {self.symbol} | OrderID: {filled_order['orderId']} | Fill_Price: ${fill_price:.8f} | Qty: {fill_qty:.8f} | USD_Value: ${fill_usd_value:.6f}")

            # IMPORTANT: Only set order_filled to True AFTER successful Jupiter swap
            # execute_dex_buy handles retries internally (3 attempts with exponential backoff)
            success = await self.execute_dex_buy(filled_order)
            if success:
                self.order_filled = True
                logger.info("✅ Arbitrage completed successfully!")
                # Stop the bot
                self.running = False
            else:
                logger.error("❌ Jupiter swap FAILED after 3 attempts")
                logger.error("⚠️  Position is UNHEDGED - manual intervention required!")
                logger.error(f"   Binance: SOLD {fill_qty} tokens")
                logger.error(f"   Jupiter: BUY FAILED")
                bot_logger.error(f"ARBITRAGE_FAILED | Symbol: {self.symbol} | Binance filled but Jupiter failed | UNHEDGED_POSITION")

                # Stop the bot - position needs manual handling
                self.running = False

        except Exception as e:
            logger.error(f"Error handling order fill: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def monitor_order_fill(self):
        """Monitor if our limit order gets filled (POLLING FALLBACK)

        This is the fallback method using REST API polling.
        WebSocket monitoring is preferred for instant notifications.
        """
        logger.info("Using polling mode for order fill monitoring (1s interval)")
        while self.running and not self.order_filled:
            try:
                if not self.cex.current_order_id:
                    await asyncio.sleep(5)
                    continue

                filled_order = self.cex.check_order_filled(
                    self.symbol,
                    self.cex.current_order_id
                )

                if filled_order:
                    await self._handle_order_fill(filled_order)

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in monitor_order_fill: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
    
    async def execute_dex_buy(self, filled_order: dict) -> bool:
        """Execute purchase on Jupiter DEX after being filled on Binance

        Returns:
            bool: True if swap succeeded, False if failed (will retry)
        """
        logger.info("Executing DEX buy to complete arbitrage...")

        # Calculate actual USD value from Binance fill
        binance_fill_price = float(filled_order.get('avgPrice', 0))
        binance_qty = float(filled_order.get('executedQty', 0))
        binance_usd_value = binance_fill_price * binance_qty

        # Log Jupiter swap attempt
        bot_logger.info(f"JUPITER_SWAP_ATTEMPT | Symbol: {self.symbol} | USD_Amount: ${binance_usd_value:.2f} (Binance_Fill: {binance_qty} @ ${binance_fill_price:.8f})")

        if self.status_display:
            self.status_display.add_action("🔄 Executing DEX swap on Jupiter...")

        # Get market configuration for mint addresses
        try:
            market = get_market_config(self.symbol)
            input_mint = market['input_mint']
            output_mint = market['output_mint']
            logger.info(f"Loaded market config: {market['name']} - {market['description']}")
        except (ValueError, KeyError) as e:
            logger.error(f"Failed to get market configuration for {self.symbol}: {e}")
            bot_logger.error(f"JUPITER_SWAP_FAILED | Market configuration error: {e}")
            return False

        # Use actual USD value from Binance fill, not config amount
        amount_in_lamports = int(binance_usd_value * 1e6)  # Convert USD to USDC lamports (6 decimals)
        logger.info(f"Jupiter swap amount: ${binance_usd_value:.2f} USD = {amount_in_lamports} lamports")
        bot_logger.info(f"JUPITER_AMOUNT_CALC | Binance_Fill_USD: ${binance_usd_value:.8f} | Requested_Lamports: {amount_in_lamports} | Requested_USDC: {amount_in_lamports/1e6:.6f}")

        # Retry logic for getting Jupiter order (up to 3 attempts with exponential backoff)
        order = None
        for attempt in range(1, 4):
            try:
                logger.info(f"Attempting to get Jupiter order (attempt {attempt}/3)...")
                order = await self.jupiter.get_order(input_mint, output_mint, amount_in_lamports)
                if order:
                    logger.info(f"✓ Successfully got Jupiter order on attempt {attempt}")
                    break
                else:
                    logger.warning(f"Jupiter order returned None on attempt {attempt}")
                    if attempt < 3:
                        wait_time = 2 ** attempt  # Exponential backoff: 2s, 4s
                        logger.info(f"Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Exception getting Jupiter order (attempt {attempt}): {e}")
                if attempt < 3:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

        if not order:
            logger.error("Failed to get Jupiter order after 3 attempts")
            bot_logger.error(f"JUPITER_SWAP_FAILED | Failed to get Jupiter order after retries")
            if self.status_display:
                self.status_display.add_action("❌ Failed to get Jupiter order")
            return False

        # Extract Jupiter trade details for logging
        jupiter_in_amount_lamports = float(order.get('inAmount', 0))
        jupiter_in_amount = jupiter_in_amount_lamports / 1e6  # Convert from lamports to USDC
        jupiter_out_amount = float(order.get('outAmount', 0))

        # Validate Jupiter returned the amount we requested
        amount_discrepancy_pct = abs(jupiter_in_amount_lamports - amount_in_lamports) / amount_in_lamports * 100 if amount_in_lamports > 0 else 0
        if amount_discrepancy_pct > 5.0:  # More than 5% difference
            logger.warning(f"⚠️  Jupiter amount mismatch! Requested: {amount_in_lamports} lamports (${amount_in_lamports/1e6:.6f}), Got: {int(jupiter_in_amount_lamports)} lamports (${jupiter_in_amount:.6f}) - {amount_discrepancy_pct:.1f}% difference")
            bot_logger.warning(f"JUPITER_AMOUNT_MISMATCH | Requested_Lamports: {amount_in_lamports} | Received_Lamports: {int(jupiter_in_amount_lamports)} | Discrepancy_Pct: {amount_discrepancy_pct:.2f}%")

        # Retry logic for executing Jupiter swap (up to 3 attempts with exponential backoff)
        swap_result = None
        logger.info("🔄 Starting Jupiter swap execution (max 3 attempts)...")

        for attempt in range(1, 4):
            try:
                logger.info(f"📍 Attempt {attempt}/3: Submitting transaction to Jupiter...")
                swap_result = await self.jupiter.execute_swap(order)

                if swap_result and swap_result.get('success'):
                    logger.info(f"✅ SUCCESS on attempt {attempt}/3")
                    break
                elif swap_result and not swap_result.get('success'):
                    # Jupiter reported failure
                    error = swap_result.get('error', 'Unknown error')
                    tx_sig = swap_result.get('signature', 'N/A')
                    logger.error(f"❌ FAILED on attempt {attempt}/3")
                    logger.error(f"   Jupiter status: Failed")
                    logger.error(f"   Error: {error}")
                    logger.error(f"   TX: {tx_sig}")

                    if attempt < 3:
                        wait_time = 2 ** attempt  # 2s, 4s
                        logger.warning(f"⏳ Retrying in {wait_time}s... ({3 - attempt} attempts remaining)")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"❌ All 3 attempts exhausted")
                else:
                    logger.warning(f"⚠️  Attempt {attempt}/3: No response from Jupiter")
                    if attempt < 3:
                        wait_time = 2 ** attempt
                        logger.warning(f"⏳ Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error(f"❌ Exception on attempt {attempt}/3: {e}")
                import traceback
                logger.error(traceback.format_exc())
                if attempt < 3:
                    wait_time = 2 ** attempt
                    logger.warning(f"⏳ Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

        if swap_result and swap_result.get('success'):
            tx_hash = swap_result['signature']
            logger.info(f"DEX swap executed! Tx: {tx_hash}")

            # Log DEX transaction separately with precise amounts
            trades_logger.info(f"DEX_SWAP | Symbol: {self.symbol} | Jupiter_TX: {tx_hash} | Status: Success | Input_Amount_USD: ${jupiter_in_amount:.6f} | Input_Lamports: {int(jupiter_in_amount_lamports)} | Output_Amount_Tokens: {jupiter_out_amount} | Input_Mint: {input_mint} | Output_Mint: {output_mint} | Slippage_Bps: {order.get('slippageBps', 'N/A')} | Route_Plan_Steps: {len(order.get('routePlan', []))}")

            # Log to bot activity
            bot_logger.info(f"JUPITER_SWAP_SUCCESS | Symbol: {self.symbol} | TX: {tx_hash} | Status: Success | Input_USD: ${jupiter_in_amount:.6f} | Input_Lamports: {int(jupiter_in_amount_lamports)} | Output_Tokens: {jupiter_out_amount}")

            if self.status_display:
                self.status_display.add_action(f"✅ DEX SWAP COMPLETE: ${jupiter_in_amount:.2f} → {jupiter_out_amount} tokens | TX: {tx_hash[:8]}...")

            self.running = False
            return True
        else:
            # Jupiter swap failed after retries
            if swap_result and not swap_result.get('success'):
                # Got a failure response from Jupiter
                tx_hash = swap_result.get('signature', 'unknown')
                error = swap_result.get('error', 'Unknown error')
                logger.error(f"Jupiter swap FAILED: {error}")
                logger.error(f"Transaction: {tx_hash}")
                logger.error(f"View on Solscan: https://solscan.io/tx/{tx_hash}")

                trades_logger.error(f"DEX_SWAP_FAILED | Symbol: {self.symbol} | Jupiter_TX: {tx_hash} | Status: Failed | Error: {error} | Solscan: https://solscan.io/tx/{tx_hash}")
                bot_logger.error(f"JUPITER_SWAP_FAILED | Symbol: {self.symbol} | TX: {tx_hash} | Status: Failed | Error: {error}")
            else:
                # No response or unknown error
                logger.error("Failed to execute DEX swap after 3 attempts")
                bot_logger.error(f"JUPITER_SWAP_FAILED | Failed to execute swap transaction after retries")

            if self.status_display:
                self.status_display.add_action("❌ Failed to execute DEX swap")
            return False

    async def display_status_loop(self):
        """Periodically display status updates"""
        if not self.status_display:
            return

        while self.running and not self.order_filled:
            try:
                self.status_display.display()
                await asyncio.sleep(5)  # Update every 5 seconds
            except Exception as e:
                logger.error(f"Error in display_status_loop: {e}")
                await asyncio.sleep(5)

        # Display final status when done
        if self.status_display:
            self.status_display.display()

