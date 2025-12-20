"""
MEXC Futures API manager
"""
import logging
import asyncio
import time
import hmac
import hashlib
from typing import Optional, Callable
import requests

from utils.logging_setup import bot_logger

logger = logging.getLogger(__name__)


class MEXCManager:
    BASE_URL = "https://contract.mexc.com"

    def __init__(self, api_key: str, api_secret: str, status_display: Optional['StatusDisplay'] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.current_price = None
        self.current_order_id = None
        self.last_order_price = None
        self.market_price_at_order = None
        self.symbol_precision = {}
        self.status_display = status_display

        # WebSocket related
        self.ws_client = None
        self.ws_running = False

    def _generate_signature(self, params: dict) -> str:
        """Generate HMAC SHA256 signature for MEXC API"""
        # Sort parameters alphabetically
        sorted_params = sorted(params.items())
        query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])

        # Create signature: accessKey + timestamp + request parameters
        sign_str = f"{self.api_key}{params.get('timestamp', '')}{query_string}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return signature

    def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """Make HTTP request to MEXC API"""
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            'Content-Type': 'application/json',
            'ApiKey': self.api_key
        }

        if params is None:
            params = {}

        if signed:
            # Add timestamp for signed requests
            params['timestamp'] = int(time.time() * 1000)
            headers['Request-Time'] = str(params['timestamp'])
            headers['Signature'] = self._generate_signature(params)

        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif method == 'POST':
                response = requests.post(url, json=params, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, params=params, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"MEXC API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None

    def _normalize_symbol(self, symbol: str) -> str:
        """Convert Binance-style symbol to MEXC format

        MEXC uses underscore: BTC_USDT instead of BTCUSDT
        """
        if '_' in symbol:
            return symbol
        # Convert BTCUSDT -> BTC_USDT
        if symbol.endswith('USDT'):
            base = symbol[:-4]
            return f"{base}_USDT"
        return symbol

    def _get_symbol_precision(self, symbol: str) -> dict:
        """Get quantity and price precision for a symbol"""
        mexc_symbol = self._normalize_symbol(symbol)

        if mexc_symbol in self.symbol_precision:
            return self.symbol_precision[mexc_symbol]

        try:
            # Get contract details
            detail = self._request('GET', '/api/v1/contract/detail', {'symbol': mexc_symbol})

            if detail and 'data' in detail:
                data = detail['data']
                precision = {
                    'qty_decimals': data.get('volumeScale', 2),
                    'price_decimals': data.get('priceScale', 2),
                    'min_qty': float(data.get('minVol', 0)),
                    'qty_step': float(data.get('volScale', 0.01)),
                    'min_price': 0,  # MEXC doesn't provide this
                    'price_step': float(data.get('priceUnit', 0.01)),
                    'min_notional': 0  # MEXC doesn't provide this
                }
                self.symbol_precision[mexc_symbol] = precision
                logger.info(f"Symbol {mexc_symbol}: qty_step={precision['qty_step']}, price_step={precision['price_step']}")
                return precision

            logger.error(f"Symbol {mexc_symbol} not found in contract details")
            return None
        except Exception as e:
            logger.error(f"Error getting symbol precision: {e}")
            return None

    def _format_quantity(self, symbol: str, quantity: float) -> float:
        """Format quantity to match symbol's step size"""
        mexc_symbol = self._normalize_symbol(symbol)
        precision = self._get_symbol_precision(mexc_symbol)

        if not precision or precision['qty_step'] == 0:
            return round(quantity, precision['qty_decimals'] if precision else 2)

        qty_step = precision['qty_step']
        formatted = round(quantity / qty_step) * qty_step

        if precision['min_qty'] > 0 and formatted < precision['min_qty']:
            logger.warning(f"Quantity {formatted} below minimum {precision['min_qty']}")

        return formatted

    def _format_price(self, symbol: str, price: float) -> float:
        """Format price to match symbol's tick size"""
        mexc_symbol = self._normalize_symbol(symbol)
        precision = self._get_symbol_precision(mexc_symbol)

        if not precision or precision['price_step'] == 0:
            return round(price, precision['price_decimals'] if precision else 2)

        price_step = precision['price_step']
        formatted = round(price / price_step) * price_step

        decimals = precision['price_decimals']
        return round(formatted, decimals)

    def get_current_price(self, symbol: str) -> float:
        """Get current market price from MEXC perpetual futures"""
        mexc_symbol = self._normalize_symbol(symbol)

        try:
            ticker = self._request('GET', '/api/v1/contract/ticker', {'symbol': mexc_symbol})

            if ticker and 'data' in ticker:
                price = float(ticker['data']['lastPrice'])
                self.current_price = price
                logger.info(f"Current {mexc_symbol} price: {price}")

                # Log to bot activity
                bot_logger.info(f"PRICE_UPDATE | Symbol: {mexc_symbol} | Price: ${price:.8f}")

                # Update status display
                if self.status_display:
                    self.status_display.update_price(price)

                return price

            logger.error(f"Invalid ticker response for {mexc_symbol}")
            return None
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return None

    def place_limit_sell_order(self, symbol: str, usd_amount: float, price: float, market_price: float) -> dict:
        """Place a limit sell order on MEXC perpetual using USD amount

        Note: MEXC's order API may be under maintenance. This uses the pymexc bypass.
        """
        mexc_symbol = self._normalize_symbol(symbol)

        try:
            # Calculate token quantity from USD amount and price
            token_quantity = usd_amount / price
            formatted_qty = self._format_quantity(mexc_symbol, token_quantity)
            formatted_price = self._format_price(mexc_symbol, price)

            logger.info(f"Placing order: ${usd_amount:.2f} USD ({formatted_qty} {mexc_symbol}) at {formatted_price} (market: {market_price})")

            # MEXC order parameters:
            # side: 3 = open short (sell)
            # type: 1 = limit order
            # open_type: 1 = isolated, 2 = cross
            # leverage: can be set (default 10)
            params = {
                'symbol': mexc_symbol,
                'price': formatted_price,
                'vol': formatted_qty,
                'side': 3,  # 3 = open short (sell)
                'type': 1,  # 1 = limit order
                'openType': 1,  # isolated margin
                'leverage': 10  # default leverage
            }

            order = self._request('POST', '/api/v1/private/order/submit', params, signed=True)

            if order and 'data' in order:
                order_id = order['data']
                self.current_order_id = order_id
                self.last_order_price = formatted_price
                self.market_price_at_order = market_price

                # Log order details
                from utils.logging_setup import orders_logger
                orders_logger.info(f"ORDER_PLACED | Symbol: {mexc_symbol} | OrderID: {order_id} | Side: SELL | USD_Amount: ${usd_amount:.2f} | Quantity: {formatted_qty} | Price: {formatted_price} | Market_Price: {market_price}")

                # Log to bot activity
                bot_logger.info(f"ORDER_CREATED | Symbol: {mexc_symbol} | OrderID: {order_id} | Side: SELL | USD: ${usd_amount:.2f} | Qty: {formatted_qty} | Price: ${formatted_price:.8f} | Market: ${market_price:.8f}")

                logger.info(f"Order placed: {order_id} - Sell ${usd_amount:.2f} USD ({formatted_qty} {mexc_symbol}) at {formatted_price}")

                # Update status display
                if self.status_display:
                    self.status_display.set_order(order_id, formatted_price, formatted_qty)
                    self.status_display.add_action(f"✅ ORDER PLACED: ID={order_id} | ${formatted_price:.6f} | Qty={formatted_qty:.4f}")

                return {'orderId': order_id, 'symbol': mexc_symbol, 'price': formatted_price, 'quantity': formatted_qty}

            logger.error(f"Failed to place order: {order}")
            return None
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel existing order"""
        mexc_symbol = self._normalize_symbol(symbol)

        try:
            params = {'orderIds': [order_id]}
            result = self._request('POST', '/api/v1/private/order/cancel', params, signed=True)
            logger.info(f"Order {order_id} cancellation result: {result}")
            self.current_order_id = None

            # Log to bot activity
            bot_logger.info(f"ORDER_CANCELLED | Symbol: {mexc_symbol} | OrderID: {order_id}")

            # Update status display
            if self.status_display:
                self.status_display.clear_order()
                self.status_display.add_action(f"🗑️  ORDER CANCELLED: ID={order_id}")

            return True
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    def check_order_filled(self, symbol: str, order_id: str) -> Optional[dict]:
        """Check if order has been filled"""
        mexc_symbol = self._normalize_symbol(symbol)

        try:
            # Get open orders - if order is not in list, it's filled
            open_orders = self.get_open_orders(mexc_symbol)

            # Check if order_id is in open orders
            order_still_open = any(str(o.get('orderId')) == str(order_id) for o in open_orders)

            if not order_still_open:
                # Order is not open anymore - assume it's filled
                # TODO: Query order history to get fill details
                logger.info(f"Order {order_id} appears to be FILLED (not in open orders)")

                # For now, return a basic filled order structure
                # In production, you'd want to query order history for actual fill details
                filled_order = {
                    'orderId': order_id,
                    'symbol': mexc_symbol,
                    'status': 'FILLED',
                    'avgPrice': self.last_order_price,  # Best guess
                    'executedQty': 0,  # Unknown without history query
                }

                # Log to bot activity
                bot_logger.info(f"ORDER_FILLED | Symbol: {mexc_symbol} | OrderID: {order_id}")

                # Update status display
                if self.status_display:
                    self.status_display.clear_order()
                    self.status_display.add_action(f"💰 ORDER FILLED: ID={order_id}")

                return filled_order

            return None
        except Exception as e:
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
        mexc_symbol = self._normalize_symbol(symbol)

        try:
            result = self._request('GET', f'/api/v1/private/order/list/open_orders/{mexc_symbol}', signed=True)

            if result and 'data' in result:
                return result['data']

            return []
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    async def start_user_stream(self, on_order_update: Callable):
        """Start order monitoring (uses polling instead of WebSocket due to pymexc issues)

        Args:
            on_order_update: Async callback function to handle order updates
                            Called with (order_data: dict) when order status changes
        """
        try:
            self.ws_running = True

            logger.info("📊 Starting MEXC order monitoring (polling mode)...")
            bot_logger.info("POLLING_START | Using polling for order updates (MEXC WebSocket unavailable)")

            last_check_order_id = self.current_order_id

            # Poll for order updates every second
            while self.ws_running:
                try:
                    if self.current_order_id and str(self.current_order_id) == str(last_check_order_id):
                        # Get order details
                        open_orders = self.get_open_orders(self.current_order_id)

                        # If order is not in open orders, it's been filled
                        order_still_open = any(str(o.get('orderId')) == str(self.current_order_id) for o in open_orders)

                        if not order_still_open:
                            logger.info(f"📊 Polling: Order {self.current_order_id} FILLED!")
                            bot_logger.info(f"POLLING_ORDER_FILL | OrderID: {self.current_order_id}")

                            # Build filled order structure
                            filled_order = {
                                'orderId': self.current_order_id,
                                'status': 'FILLED',
                                'avgPrice': self.last_order_price,  # Best guess
                                'executedQty': 0,  # Unknown without history query
                            }

                            # Call the callback
                            await on_order_update(filled_order)
                            break

                except Exception as e:
                    logger.error(f"Error checking order status: {e}")

                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            bot_logger.error(f"POLLING_ERROR | {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            await self.stop_user_stream()

    async def stop_user_stream(self):
        """Stop WebSocket user data stream"""
        try:
            self.ws_running = False

            if self.ws_client:
                logger.info("🔌 Stopping WebSocket user data stream...")
                # WebSocket cleanup
                self.ws_client = None

            bot_logger.info("WEBSOCKET_STOP | User data stream stopped")
        except Exception as e:
            logger.error(f"Error stopping WebSocket: {e}")
