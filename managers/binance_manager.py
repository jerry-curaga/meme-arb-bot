"""
Binance Futures API manager
"""
import logging
import asyncio
from typing import Optional, Callable
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance import AsyncClient, BinanceSocketManager

from utils.logging_setup import bot_logger

logger = logging.getLogger(__name__)


class BinanceManager:
    def __init__(self, api_key: str, api_secret: str, status_display: Optional['StatusDisplay'] = None):
        self.client = Client(api_key=api_key, api_secret=api_secret)
        self.api_key = api_key
        self.api_secret = api_secret
        self.current_price = None
        self.current_order_id = None
        self.last_order_price = None
        self.market_price_at_order = None
        self.symbol_precision = {}
        self.status_display = status_display

        # WebSocket related
        self.async_client = None
        self.bsm = None
        self.user_socket = None
        self.price_socket = None
        self.price_callback = None

    def _get_symbol_precision(self, symbol: str) -> dict:
        """Get quantity and price precision for a symbol"""
        if symbol in self.symbol_precision:
            return self.symbol_precision[symbol]

        try:
            exchange_info = self.client.futures_exchange_info()
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    filters = {f['filterType']: f for f in s['filters']}

                    price_filter = filters.get('PRICE_FILTER', {})
                    lot_size_filter = filters.get('LOT_SIZE', {})

                    precision = {
                        'qty_decimals': s['quantityPrecision'],
                        'price_decimals': s['pricePrecision'],
                        'min_qty': float(lot_size_filter.get('minQty', 0)),
                        'qty_step': float(lot_size_filter.get('stepSize', 0)),
                        'min_price': float(price_filter.get('minPrice', 0)),
                        'price_step': float(price_filter.get('tickSize', 0)),
                        'min_notional': float(filters.get('MIN_NOTIONAL', {}).get('notional', 0))
                    }
                    self.symbol_precision[symbol] = precision
                    logger.info(f"Symbol {symbol}: qty_step={precision['qty_step']}, price_step={precision['price_step']}")
                    return precision
            logger.error(f"Symbol {symbol} not found in exchange info")
            return None
        except Exception as e:
            logger.error(f"Error getting symbol precision: {e}")
            return None

    def _format_quantity(self, symbol: str, quantity: float) -> float:
        """Format quantity to match symbol's step size"""
        precision = self._get_symbol_precision(symbol)
        if not precision or precision['qty_step'] == 0:
            return round(quantity, precision['qty_decimals'] if precision else 2)

        qty_step = precision['qty_step']
        formatted = round(quantity / qty_step) * qty_step

        if formatted < precision['min_qty']:
            logger.warning(f"Quantity {formatted} below minimum {precision['min_qty']}")

        return formatted

    def _format_price(self, symbol: str, price: float) -> float:
        """Format price to match symbol's tick size"""
        precision = self._get_symbol_precision(symbol)
        if not precision or precision['price_step'] == 0:
            return round(price, precision['price_decimals'] if precision else 2)

        price_step = precision['price_step']
        formatted = round(price / price_step) * price_step

        decimals = precision['price_decimals']
        return round(formatted, decimals)

    def get_current_price(self, symbol: str) -> float:
        """Get current market price from Binance perpetual futures"""
        try:
            ticker = self.client.futures_mark_price(symbol=symbol)
            price = float(ticker['markPrice'])
            self.current_price = price
            logger.info(f"Current {symbol} price: {price}")

            # Log to bot activity
            bot_logger.info(f"PRICE_UPDATE | Symbol: {symbol} | Price: ${price:.8f}")

            # Update status display
            if self.status_display:
                self.status_display.update_price(price)

            return price
        except BinanceAPIException as e:
            logger.error(f"Error fetching price: {e}")
            return None

    def place_limit_sell_order(self, symbol: str, usd_amount: float, price: float, market_price: float) -> dict:
        """Place a limit sell order on Binance perpetual using USD amount"""
        try:
            # Calculate token quantity from USD amount and price
            token_quantity = usd_amount / price
            formatted_qty = self._format_quantity(symbol, token_quantity)
            formatted_price = self._format_price(symbol, price)

            logger.info(f"Placing order: ${usd_amount:.2f} USD ({formatted_qty} {symbol}) at {formatted_price} (market: {market_price})")

            order = self.client.futures_create_order(
                symbol=symbol,
                side='SELL',
                type='LIMIT',
                timeInForce='GTC',
                quantity=formatted_qty,
                price=formatted_price
            )
            self.current_order_id = order['orderId']
            self.last_order_price = formatted_price
            self.market_price_at_order = market_price

            # Log order details to separate file
            from utils.logging_setup import orders_logger
            orders_logger.info(f"ORDER_PLACED | Symbol: {symbol} | OrderID: {order['orderId']} | Side: SELL | USD_Amount: ${usd_amount:.2f} | Quantity: {formatted_qty} | Price: {formatted_price} | Market_Price: {market_price}")

            # Log to bot activity
            bot_logger.info(f"ORDER_CREATED | Symbol: {symbol} | OrderID: {order['orderId']} | Side: SELL | USD: ${usd_amount:.2f} | Qty: {formatted_qty} | Price: ${formatted_price:.8f} | Market: ${market_price:.8f}")

            logger.info(f"Order placed: {order['orderId']} - Sell ${usd_amount:.2f} USD ({formatted_qty} {symbol}) at {formatted_price}")

            # Update status display
            if self.status_display:
                self.status_display.set_order(order['orderId'], formatted_price, formatted_qty)
                self.status_display.add_action(f"✅ ORDER PLACED: ID={order['orderId']} | ${formatted_price:.6f} | Qty={formatted_qty:.4f}")

            return order
        except BinanceAPIException as e:
            logger.error(f"Error placing order: {e}")
            return None

    def modify_order(self, symbol: str, order_id: int, usd_amount: float, new_price: float, market_price: float) -> dict:
        """Modify existing order price and quantity

        Args:
            symbol: Trading symbol
            order_id: Existing order ID to modify
            usd_amount: New USD amount for the order
            new_price: New limit price
            market_price: Current market price (for logging)

        Returns:
            Modified order dict or None on failure
        """
        try:
            # Calculate new quantity from USD amount
            new_quantity = usd_amount / new_price
            formatted_qty = self._format_quantity(symbol, new_quantity)
            formatted_price = self._format_price(symbol, new_price)

            logger.info(f"Modifying order {order_id}: ${usd_amount:.2f} USD ({formatted_qty} {symbol}) at {formatted_price} (market: {market_price})")

            # Binance futures_modify_order
            modified_order = self.client.futures_modify_order(
                symbol=symbol,
                orderId=order_id,
                quantity=formatted_qty,
                price=formatted_price
            )

            self.last_order_price = formatted_price
            self.market_price_at_order = market_price

            # Log order modification to separate file
            from utils.logging_setup import orders_logger
            orders_logger.info(f"ORDER_MODIFIED | Symbol: {symbol} | OrderID: {order_id} | New_Price: {formatted_price} | New_Quantity: {formatted_qty} | USD_Amount: ${usd_amount:.2f} | Market_Price: {market_price}")

            # Log to bot activity
            bot_logger.info(f"ORDER_MODIFIED | Symbol: {symbol} | OrderID: {order_id} | USD: ${usd_amount:.2f} | Qty: {formatted_qty} | Price: ${formatted_price:.8f} | Market: ${market_price:.8f}")

            logger.info(f"Order {order_id} modified successfully")

            # Update status display
            if self.status_display:
                self.status_display.set_order(order_id, formatted_price, formatted_qty)
                self.status_display.add_action(f"✏️  ORDER MODIFIED: ID={order_id} | ${formatted_price:.6f} | Qty={formatted_qty:.4f}")

            return modified_order
        except BinanceAPIException as e:
            logger.error(f"Error modifying order: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel existing order"""
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order {order_id} cancelled")
            self.current_order_id = None

            # Log to bot activity
            bot_logger.info(f"ORDER_CANCELLED | Symbol: {symbol} | OrderID: {order_id}")

            # Update status display
            if self.status_display:
                self.status_display.clear_order()
                self.status_display.add_action(f"🗑️  ORDER CANCELLED: ID={order_id}")

            return True
        except BinanceAPIException as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    def check_order_filled(self, symbol: str, order_id: int) -> Optional[dict]:
        """Check if order has been filled"""
        try:
            order = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            if order['status'] == 'FILLED':
                logger.info(f"Order {order_id} FILLED!")

                fill_price = float(order.get('avgPrice', 0))
                fill_qty = float(order.get('executedQty', 0))
                fill_usd = fill_price * fill_qty

                # Log to bot activity
                bot_logger.info(f"ORDER_FILLED | Symbol: {symbol} | OrderID: {order_id} | Fill_Price: ${fill_price:.8f} | Qty: {fill_qty} | USD_Value: ${fill_usd:.2f}")

                # Update status display
                if self.status_display:
                    self.status_display.clear_order()
                    self.status_display.add_action(f"💰 ORDER FILLED: ID={order_id} | ${fill_price:.6f} | Qty={fill_qty:.4f}")

                return order
            return None
        except BinanceAPIException as e:
            logger.error(f"Error checking order: {e}")
            return None

    def should_update_order(self, current_price: float, threshold: float) -> bool:
        """Check if market price has changed by threshold percent since order was placed"""
        if self.market_price_at_order is None:
            return False

        price_change = abs(current_price - self.market_price_at_order) / self.market_price_at_order * 100
        return price_change >= threshold

    def get_open_orders(self, symbol: str) -> list:
        """Get all open orders for a symbol"""
        try:
            orders = self.client.futures_get_open_orders(symbol=symbol)
            return orders
        except BinanceAPIException as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    async def start_user_stream(self, on_order_update: Callable):
        """Start WebSocket user data stream for real-time order updates

        Args:
            on_order_update: Async callback function to handle order updates
                            Called with (order_data: dict) when order status changes
        """
        try:
            # Create async client
            self.async_client = await AsyncClient.create(self.api_key, self.api_secret)
            self.bsm = BinanceSocketManager(self.async_client)

            # Start futures user data stream
            self.user_socket = self.bsm.futures_user_socket()

            logger.info("🔌 Starting Binance WebSocket user data stream...")
            bot_logger.info("WEBSOCKET_START | Starting user data stream for real-time order updates")

            async with self.user_socket as stream:
                while True:
                    msg = await stream.recv()

                    # Handle different event types
                    if msg['e'] == 'ORDER_TRADE_UPDATE':
                        order_update = msg['o']
                        order_id = order_update['i']
                        order_status = order_update['X']
                        symbol = order_update['s']

                        logger.debug(f"WebSocket: Order {order_id} status: {order_status}")

                        # Only trigger callback for FILLED orders
                        if order_status == 'FILLED' and order_id == self.current_order_id:
                            logger.info(f"🔔 WebSocket: Order {order_id} FILLED!")
                            bot_logger.info(f"WEBSOCKET_ORDER_FILL | OrderID: {order_id} | Symbol: {symbol}")

                            # Get full order details from REST API (WebSocket doesn't have all fields)
                            filled_order = self.client.futures_get_order(symbol=symbol, orderId=order_id)

                            # Call the callback
                            await on_order_update(filled_order)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            bot_logger.error(f"WEBSOCKET_ERROR | {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            await self.stop_user_stream()

    async def stop_user_stream(self):
        """Stop WebSocket user data stream"""
        try:
            if self.user_socket:
                logger.info("🔌 Stopping WebSocket user data stream...")
                # Socket is closed when exiting async context manager
                self.user_socket = None

            if self.price_socket:
                logger.info("🔌 Stopping WebSocket price stream...")
                self.price_socket = None

            if self.async_client:
                await self.async_client.close_connection()
                self.async_client = None
                self.bsm = None

            bot_logger.info("WEBSOCKET_STOP | User data stream stopped")
        except Exception as e:
            logger.error(f"Error stopping WebSocket: {e}")

    async def start_price_stream(self, symbol: str, on_price_update: Callable):
        """Start WebSocket mark price stream for real-time price monitoring

        Args:
            symbol: Trading symbol to monitor
            on_price_update: Async callback function to handle price updates
                           Called with (price: float) when price changes
        """
        try:
            # Create async client if not already created
            if not self.async_client:
                self.async_client = await AsyncClient.create(self.api_key, self.api_secret)
                self.bsm = BinanceSocketManager(self.async_client)

            # Start futures mark price stream
            self.price_socket = self.bsm.symbol_mark_price_socket(symbol)

            logger.info(f"🔌 Starting Binance WebSocket price stream for {symbol}...")
            bot_logger.info(f"WEBSOCKET_PRICE_START | Starting mark price stream for {symbol}")

            async with self.price_socket as stream:
                while True:
                    msg = await stream.recv()

                    # Mark price updates every 3 seconds
                    if 'p' in msg:  # 'p' is the mark price field
                        mark_price = float(msg['p'])
                        self.current_price = mark_price

                        # Update status display
                        if self.status_display:
                            self.status_display.update_price(mark_price)

                        # Call the callback
                        await on_price_update(mark_price)

        except Exception as e:
            logger.error(f"Price WebSocket error: {e}")
            bot_logger.error(f"WEBSOCKET_PRICE_ERROR | {e}")
            import traceback
            logger.error(traceback.format_exc())
