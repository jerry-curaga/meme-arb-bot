"""
Main trading bot orchestrator
"""
import os
import asyncio
import logging
from config import TradingBotConfig
from managers.binance_manager import BinanceManager
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

        self.binance = BinanceManager(config.binance_api_key, config.binance_api_secret, self.status_display)
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
        open_orders = self.binance.get_open_orders(self.symbol)

        if not open_orders:
            logger.info("No existing orders found")
            bot_logger.info(f"STARTUP_CHECK | Symbol: {self.symbol} | No existing orders")
            return True  # No orders, should place new one

        # Get current market price
        current_price = self.binance.get_current_price(self.symbol)
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
                self.binance.cancel_order(self.symbol, order_id)
                return True  # Should place new order
            else:
                # Order is still valid, use it
                logger.info(f"Existing order {order_id} is still valid, keeping it")
                bot_logger.info(f"STARTUP_KEEP | Symbol: {self.symbol} | OrderID: {order_id} | Order still valid")
                self.binance.current_order_id = order_id
                self.binance.last_order_price = order_price
                self.binance.market_price_at_order = reference_price

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
            current_price = self.binance.get_current_price(self.symbol)
            if not current_price:
                logger.error("Failed to get initial price")
                bot_logger.error(f"BOT_ERROR | Failed to get initial price for {self.symbol}")
                return

            quote_price = current_price * (1 + self.config.mark_up_percent / 100)
            self.binance.place_limit_sell_order(self.symbol, self.usd_amount, quote_price, current_price)

        await asyncio.gather(
            self.monitor_prices(),
            self.monitor_order_fill()
        )

        # Log bot stop
        bot_logger.info(f"BOT_STOP | Symbol: {self.symbol}")
    
    async def monitor_prices(self):
        """Monitor price changes and update orders"""
        while self.running and not self.order_filled:
            try:
                current_price = self.binance.get_current_price(self.symbol)
                
                if current_price and self.binance.should_update_order(
                    current_price, 
                    self.config.price_change_threshold
                ):
                    logger.info(f"Market moved {self.config.price_change_threshold}% from {self.binance.market_price_at_order}, updating order")
                    
                    if self.binance.current_order_id:
                        self.binance.cancel_order(self.symbol, self.binance.current_order_id)
                    
                    new_quote_price = current_price * (1 + self.config.mark_up_percent / 100)
                    self.binance.place_limit_sell_order(self.symbol, self.usd_amount, new_quote_price, current_price)
                
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error in monitor_prices: {e}")
                await asyncio.sleep(5)
    
    async def monitor_order_fill(self):
        """Monitor if our limit order gets filled"""
        while self.running and not self.order_filled:
            try:
                if not self.binance.current_order_id:
                    await asyncio.sleep(5)
                    continue
                
                filled_order = self.binance.check_order_filled(
                    self.symbol,
                    self.binance.current_order_id
                )
                
                if filled_order:
                    # Log CEX transaction (order fill)
                    fill_price = float(filled_order.get('avgPrice', 0))
                    fill_qty = float(filled_order.get('executedQty', 0))
                    fill_usd_value = fill_price * fill_qty
                    trades_logger.info(f"CEX_FILL | Symbol: {self.symbol} | Binance_OrderID: {filled_order['orderId']} | Fill_Price: {fill_price} | Fill_Qty: {fill_qty} | USD_Value: ${fill_usd_value:.2f} | Side: SELL")

                    self.order_filled = True
                    await self.execute_dex_buy(filled_order)
                
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in monitor_order_fill: {e}")
                await asyncio.sleep(5)
    
    async def execute_dex_buy(self, filled_order: dict):
        """Execute purchase on Jupiter DEX after being filled on Binance"""
        logger.info("Executing DEX buy to complete arbitrage...")

        # Calculate actual USD value from Binance fill
        binance_fill_price = float(filled_order.get('avgPrice', 0))
        binance_qty = float(filled_order.get('executedQty', 0))
        binance_usd_value = binance_fill_price * binance_qty

        # Log Jupiter swap attempt
        bot_logger.info(f"JUPITER_SWAP_ATTEMPT | Symbol: {self.symbol} | USD_Amount: ${binance_usd_value:.2f} (Binance_Fill: {binance_qty} @ ${binance_fill_price:.8f})")

        if self.status_display:
            self.status_display.add_action("🔄 Executing DEX swap on Jupiter...")

        input_mint = os.getenv('BUY_INPUT_MINT')
        output_mint = os.getenv('BUY_OUTPUT_MINT')

        if not input_mint or not output_mint:
            logger.error("Missing mint configuration for DEX swap")
            bot_logger.error(f"JUPITER_SWAP_FAILED | Missing mint configuration")
            return

        # Use actual USD value from Binance fill, not config amount
        amount_in_lamports = int(binance_usd_value * 1e6)  # Convert USD to USDC lamports (6 decimals)
        logger.info(f"Jupiter swap amount: ${binance_usd_value:.2f} USD = {amount_in_lamports} lamports")

        order = await self.jupiter.get_order(input_mint, output_mint, amount_in_lamports)
        if not order:
            logger.error("Failed to get Jupiter order")
            bot_logger.error(f"JUPITER_SWAP_FAILED | Failed to get Jupiter order")
            if self.status_display:
                self.status_display.add_action("❌ Failed to get Jupiter order")
            return

        # Extract Jupiter trade details for logging
        jupiter_in_amount = float(order.get('inAmount', 0)) / 1e6  # Convert from lamports to USDC
        jupiter_out_amount = float(order.get('outAmount', 0))

        tx_hash = await self.jupiter.execute_swap(order)
        if tx_hash:
            logger.info(f"DEX swap executed! Tx: {tx_hash}")

            # Log DEX transaction separately
            trades_logger.info(f"DEX_SWAP | Symbol: {self.symbol} | Jupiter_TX: {tx_hash} | Input_Amount_USD: ${jupiter_in_amount:.2f} | Output_Amount_Tokens: {jupiter_out_amount} | Input_Mint: {input_mint} | Output_Mint: {output_mint} | Slippage_Bps: {order.get('slippageBps', 'N/A')} | Route_Plan_Steps: {len(order.get('routePlan', []))}")

            # Log to bot activity
            bot_logger.info(f"JUPITER_SWAP_SUCCESS | Symbol: {self.symbol} | TX: {tx_hash} | Input_USD: ${jupiter_in_amount:.2f} | Output_Tokens: {jupiter_out_amount}")

            if self.status_display:
                self.status_display.add_action(f"✅ DEX SWAP COMPLETE: ${jupiter_in_amount:.2f} → {jupiter_out_amount} tokens | TX: {tx_hash[:8]}...")

            self.running = False
        else:
            logger.error("Failed to execute DEX swap")
            bot_logger.error(f"JUPITER_SWAP_FAILED | Failed to execute swap transaction")
            if self.status_display:
                self.status_display.add_action("❌ Failed to execute DEX swap")

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

