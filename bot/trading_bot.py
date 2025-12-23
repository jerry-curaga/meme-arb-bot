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
from managers.okx_dex_manager import OKXDexManager
from bot.status_display import StatusDisplay
from utils.logging_setup import bot_logger, trades_logger

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, symbol: str, usd_amount: float, config: TradingBotConfig, enable_status_display: bool = True):
        self.symbol = symbol
        self.usd_amount = usd_amount  # USD amount to trade
        self.config = config

        # Get market configuration
        self.market_config = get_market_config(symbol)
        cex_provider = self.market_config.get('cex_provider', 'binance')
        self.cex_symbol = self.market_config.get('symbol', symbol)

        # Create status display
        self.status_display = StatusDisplay(symbol, usd_amount) if enable_status_display else None

        # Initialize CEX manager based on provider from market config
        if cex_provider == 'binance':
            logger.info(f"Using Binance as CEX provider for {symbol}")
            self.cex = BinanceManager(config.binance_api_key, config.binance_api_secret, self.status_display)
        elif cex_provider == 'mexc':
            logger.info(f"Using MEXC as CEX provider for {symbol}")
            self.cex = MEXCManager(config.mexc_api_key, config.mexc_api_secret, self.status_display)
        else:
            raise ValueError(f"Unsupported CEX provider: {cex_provider}")

        # Initialize DEX managers based on market config
        dex_provider = self.market_config.get('dex_provider', 'jupiter')
        dex_chain = self.market_config.get('dex_chain', 'solana')

        logger.info(f"Using {dex_provider.upper()} on {dex_chain.upper()} for DEX swaps")

        self.dex_provider = dex_provider
        self.dex_chain = dex_chain

        # Initialize Jupiter (for Solana markets)
        if dex_provider == 'jupiter' or dex_chain == 'solana':
            self.jupiter = JupiterSwapManager(
                config.solana_private_key,
                config.jupiter_api_url,
                config.jupiter_api_key,
                config.max_slippage
            )
        else:
            self.jupiter = None

        # Initialize OKX DEX (for BSC or multi-chain)
        if dex_provider == 'okx':
            self.okx_dex = OKXDexManager(
                api_key=config.okx_api_key,
                secret_key=config.okx_secret_key,
                passphrase=config.okx_passphrase,
                solana_private_key=config.solana_private_key if dex_chain == 'solana' else None,
                bsc_private_key=config.bsc_private_key if dex_chain == 'bsc' else None,
                max_slippage=config.max_slippage
            )
        else:
            self.okx_dex = None

        self.running = True
        self.order_filled = False
        self.price_update_counter = 0  # Track price updates for periodic logging

    async def validate_existing_orders(self) -> bool:
        """
        Check if there are existing open orders and validate if they're still appropriate.
        Returns True if we should place a new order, False if existing order is still valid.
        """
        open_orders = self.cex.get_open_orders(self.cex_symbol)

        if not open_orders:
            logger.info("No existing orders found")
            bot_logger.info(f"STARTUP_CHECK | Symbol: {self.symbol} | No existing orders")
            return True  # No orders, should place new one

        # Get current market price
        current_price = self.cex.get_current_price(self.cex_symbol)
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
                self.cex.cancel_order(self.cex_symbol, order_id)
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
            current_price = self.cex.get_current_price(self.cex_symbol)
            if not current_price:
                logger.error("Failed to get initial price")
                bot_logger.error(f"BOT_ERROR | Failed to get initial price for {self.symbol}")
                return

            quote_price = current_price * (1 + self.config.mark_up_percent / 100)
            self.cex.place_limit_sell_order(self.cex_symbol, self.usd_amount, quote_price, current_price)

        await asyncio.gather(
            self.monitor_prices_websocket(),
            self.monitor_order_fill_websocket()
        )

        # Log bot stop
        bot_logger.info(f"BOT_STOP | Symbol: {self.symbol}")

    async def monitor_prices_websocket(self):
        """Monitor price changes via WebSocket and update orders"""
        try:
            # Check if CEX manager supports price stream
            if hasattr(self.cex, 'start_price_stream'):
                logger.info("Using WebSocket for price monitoring")
                await self.cex.start_price_stream(self.cex_symbol, self._handle_price_update)
            else:
                # Fallback to polling for CEX providers without WebSocket
                logger.info("Using REST polling for price monitoring")
                await self._monitor_prices_polling()
        except Exception as e:
            logger.error(f"WebSocket price monitoring failed: {e}")
            logger.warning("Falling back to REST polling...")
            await self._monitor_prices_polling()

    async def _handle_price_update(self, current_price: float):
        """Handle price update from WebSocket"""
        if not self.running or self.order_filled:
            return

        try:
            self.price_update_counter += 1

            # Log price update (debug for every update, info every 20 updates)
            if self.cex.market_price_at_order:
                price_change = ((current_price - self.cex.market_price_at_order) / self.cex.market_price_at_order) * 100

                # Log at INFO level every 20 updates (~1 minute if 3s intervals)
                if self.price_update_counter % 20 == 0:
                    logger.info(f"📊 Price stream active: ${current_price:.8f} ({price_change:+.2f}% from order) | Updates: {self.price_update_counter}")
                    bot_logger.info(f"PRICE_STREAM_ACTIVE | Symbol: {self.symbol} | Current: ${current_price:.8f} | Change: {price_change:+.2f}% | Updates: {self.price_update_counter}")
                else:
                    logger.debug(f"Price update: ${current_price:.8f} ({price_change:+.2f}% from order reference)")
                    bot_logger.debug(f"PRICE_UPDATE | Symbol: {self.symbol} | Current: ${current_price:.8f} | Change: {price_change:+.2f}%")

            # Check if order needs updating
            if self.cex.should_update_order(current_price, self.config.price_change_threshold):
                logger.info(f"Market moved {self.config.price_change_threshold}% from ${self.cex.market_price_at_order:.8f}, updating order")

                if self.cex.current_order_id:
                    # Use modify_order instead of cancel+create
                    new_quote_price = current_price * (1 + self.config.mark_up_percent / 100)
                    logger.info(f"Modifying order: ${self.cex.last_order_price:.8f} → ${new_quote_price:.8f}")
                    self.cex.modify_order(self.cex_symbol, self.cex.current_order_id, self.usd_amount, new_quote_price, current_price)
        except Exception as e:
            logger.error(f"Error handling price update: {e}")

    async def _monitor_prices_polling(self):
        """Fallback: Monitor price changes via REST API polling"""
        while self.running and not self.order_filled:
            try:
                current_price = self.cex.get_current_price(self.cex_symbol)

                if current_price and self.cex.should_update_order(
                    current_price,
                    self.config.price_change_threshold
                ):
                    logger.info(f"Market moved {self.config.price_change_threshold}% from {self.cex.market_price_at_order}, updating order")

                    if self.cex.current_order_id:
                        # Use modify_order instead of cancel+create
                        new_quote_price = current_price * (1 + self.config.mark_up_percent / 100)
                        self.cex.modify_order(self.cex_symbol, self.cex.current_order_id, self.usd_amount, new_quote_price, current_price)

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

            # IMPORTANT: Only set order_filled to True AFTER successful DEX swap
            # execute_dex_buy handles retries internally (3 attempts with exponential backoff)
            success = await self.execute_dex_buy(filled_order)
            if success:
                logger.info("✅ Arbitrage cycle completed successfully!")
                bot_logger.info(f"ARBITRAGE_CYCLE_COMPLETE | Symbol: {self.symbol}")

                # Reset state and place new order to continue trading
                self.order_filled = False
                self.cex.current_order_id = None
                self.cex.last_order_price = None

                # Get current price and place new order
                logger.info("📊 Placing new order to continue trading...")
                current_price = self.cex.get_current_price(self.cex_symbol)
                if current_price:
                    quote_price = current_price * (1 + self.config.mark_up_percent / 100)
                    self.cex.place_limit_sell_order(self.cex_symbol, self.usd_amount, quote_price, current_price)
                    logger.info(f"✓ New order placed at ${quote_price:.8f} | Continue trading...")
                    bot_logger.info(f"NEW_ORDER_PLACED | Symbol: {self.symbol} | Price: ${quote_price:.8f} | Continuing arbitrage")
                else:
                    logger.error("Failed to get price for new order - stopping bot")
                    self.running = False
            else:
                logger.error("❌ DEX swap FAILED after 3 attempts")
                logger.error("⚠️  Position is UNHEDGED - manual intervention required!")
                logger.error(f"   CEX: SOLD {fill_qty} tokens")
                logger.error(f"   DEX: BUY FAILED")
                bot_logger.error(f"ARBITRAGE_FAILED | Symbol: {self.symbol} | CEX filled but DEX failed | UNHEDGED_POSITION")

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
        """Execute purchase on DEX after being filled on CEX

        Routes to appropriate DEX provider based on market config.

        Returns:
            bool: True if swap succeeded, False if failed (will retry)
        """
        logger.info("Executing DEX buy to complete arbitrage...")

        # Calculate actual USD value from CEX fill
        cex_fill_price = float(filled_order.get('avgPrice', 0))
        cex_qty = float(filled_order.get('executedQty', 0))
        cex_usd_value = cex_fill_price * cex_qty

        # Log DEX swap attempt
        bot_logger.info(f"DEX_SWAP_ATTEMPT | Provider: {self.dex_provider.upper()} | Chain: {self.dex_chain.upper()} | Symbol: {self.symbol} | USD_Amount: ${cex_usd_value:.2f} (CEX_Fill: {cex_qty} @ ${cex_fill_price:.8f})")

        if self.status_display:
            self.status_display.add_action(f"🔄 Executing DEX swap on {self.dex_provider.upper()}...")

        # Get market configuration
        try:
            market = get_market_config(self.symbol)
            logger.info(f"Loaded market config: {market['name']} - {market['description']}")
        except (ValueError, KeyError) as e:
            logger.error(f"Failed to get market configuration for {self.symbol}: {e}")
            bot_logger.error(f"DEX_SWAP_FAILED | Market configuration error: {e}")
            return False

        # Route to appropriate DEX provider
        if self.dex_provider == 'jupiter':
            return await self._execute_jupiter_swap(market, cex_usd_value)
        elif self.dex_provider == 'okx':
            return await self._execute_okx_swap(market, cex_usd_value)
        else:
            logger.error(f"Unsupported DEX provider: {self.dex_provider}")
            return False

    async def _execute_jupiter_swap(self, market: dict, usd_value: float) -> bool:
        """Execute swap on Jupiter DEX (Solana)"""
        input_mint = market.get('input_mint')
        output_mint = market.get('output_mint')

        if not input_mint or not output_mint:
            logger.error("Missing input_mint or output_mint for Jupiter swap")
            return False

        # Use actual USD value from CEX fill
        amount_in_lamports = int(usd_value * 1e6)  # Convert USD to USDC lamports (6 decimals)
        logger.info(f"Jupiter swap amount: ${usd_value:.2f} USD = {amount_in_lamports} lamports")
        bot_logger.info(f"JUPITER_AMOUNT_CALC | CEX_Fill_USD: ${usd_value:.8f} | Requested_Lamports: {amount_in_lamports} | Requested_USDC: {amount_in_lamports/1e6:.6f}")

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

    async def _execute_okx_swap(self, market: dict, usd_value: float) -> bool:
        """Execute swap on OKX DEX (BSC or Solana)"""
        # Get token addresses based on chain
        if self.dex_chain == 'bsc':
            input_token = market.get('input_token')
            output_token = market.get('output_token')
            decimals = 18  # BSC USDT has 18 decimals
        elif self.dex_chain == 'solana':
            input_token = market.get('input_mint')
            output_token = market.get('output_mint')
            decimals = 6  # Solana USDC has 6 decimals
        else:
            logger.error(f"Unsupported chain for OKX: {self.dex_chain}")
            return False

        if not input_token or not output_token:
            logger.error(f"Missing token addresses for OKX {self.dex_chain} swap")
            return False

        # Convert USD to token amount (with proper decimals)
        amount = str(int(usd_value * (10 ** decimals)))
        logger.info(f"OKX swap amount: ${usd_value:.2f} USD = {amount} base units")
        bot_logger.info(f"OKX_AMOUNT_CALC | CEX_Fill_USD: ${usd_value:.8f} | Amount: {amount} | Chain: {self.dex_chain}")

        # Retry logic for OKX swap (up to 3 attempts)
        for attempt in range(1, 4):
            try:
                logger.info(f"📍 Attempt {attempt}/3: Executing OKX DEX swap...")

                swap_result = await self.okx_dex.swap(
                    self.dex_chain,
                    input_token,
                    output_token,
                    amount
                )

                if swap_result and swap_result.get('success'):
                    logger.info(f"✅ SUCCESS on attempt {attempt}/3")

                    # Extract transaction details based on chain
                    if self.dex_chain == 'bsc':
                        tx_hash = swap_result.get('tx_hash')
                        logger.info(f"OKX BSC swap executed! Tx: {tx_hash}")

                        trades_logger.info(f"DEX_SWAP | Symbol: {self.symbol} | OKX_BSC_TX: {tx_hash} | Status: Success | Input_Amount_USD: ${usd_value:.6f} | Input_Token: {input_token} | Output_Token: {output_token}")
                        bot_logger.info(f"OKX_SWAP_SUCCESS | Symbol: {self.symbol} | Chain: BSC | TX: {tx_hash} | Status: Success | Input_USD: ${usd_value:.6f}")

                        if self.status_display:
                            self.status_display.add_action(f"✅ OKX BSC SWAP COMPLETE: ${usd_value:.2f} | TX: {tx_hash[:8]}...")

                    elif self.dex_chain == 'solana':
                        signed_tx = swap_result.get('signed_transaction', 'N/A')
                        logger.info(f"OKX Solana swap executed! Signed TX ready")

                        trades_logger.info(f"DEX_SWAP | Symbol: {self.symbol} | OKX_SOL | Status: Success | Input_Amount_USD: ${usd_value:.6f} | Input_Token: {input_token} | Output_Token: {output_token}")
                        bot_logger.info(f"OKX_SWAP_SUCCESS | Symbol: {self.symbol} | Chain: Solana | Status: Success | Input_USD: ${usd_value:.6f}")

                        if self.status_display:
                            self.status_display.add_action(f"✅ OKX SOLANA SWAP COMPLETE: ${usd_value:.2f}")

                    self.running = False
                    return True

                else:
                    logger.warning(f"⚠️  Attempt {attempt}/3: OKX swap failed or no response")
                    if attempt < 3:
                        wait_time = 2 ** attempt  # 2s, 4s
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

        # All attempts failed
        logger.error("Failed to execute OKX swap after 3 attempts")
        bot_logger.error(f"OKX_SWAP_FAILED | Symbol: {self.symbol} | Chain: {self.dex_chain} | Failed after retries")

        if self.status_display:
            self.status_display.add_action("❌ Failed to execute OKX swap")

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

