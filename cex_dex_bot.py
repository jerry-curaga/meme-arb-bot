"""
CEX/DEX Arbitrage Trading Bot
Quotes on Binance, executes swaps on Jupiter (Solana)
"""

import os
import json
import asyncio
import logging
import base64
import argparse
from typing import Optional
from decimal import Decimal
from dotenv import load_dotenv
import aiohttp
from binance.client import Client
from binance.exceptions import BinanceAPIException
import base58
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.presigner import Presigner

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class TradingBotConfig:
    def __init__(self):
        self.binance_api_key = os.getenv('BINANCE_API_KEY')
        self.binance_api_secret = os.getenv('BINANCE_API_SECRET')
        self.solana_private_key = os.getenv('SOLANA_PRIVATE_KEY')
        self.jupiter_api_url = os.getenv('JUPITER_API_URL', 'https://api.jup.ag/ultra')
        self.jupiter_api_key = os.getenv('JUPITER_API_KEY')
        
        # Trading parameters
        self.mark_up_percent = 3.0  # 3% above market
        self.price_change_threshold = 0.5  # 0.5% for order update
        self.max_slippage = 1.0  # 1% max slippage on Jupiter
        
        self._validate()
    
    def _validate(self):
        required = ['BINANCE_API_KEY', 'BINANCE_API_SECRET', 'SOLANA_PRIVATE_KEY', 'JUPITER_API_KEY']
        missing = [var for var in required if not os.getenv(var)]
        if missing:
            raise ValueError(f"Missing environment variables: {missing}")

class BinanceManager:
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key=api_key, api_secret=api_secret)
        self.current_price = None
        self.current_order_id = None
        self.last_order_price = None
        self.market_price_at_order = None
        self.symbol_precision = {}
    
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
            logger.info(f"Order placed: {order['orderId']} - Sell ${usd_amount:.2f} USD ({formatted_qty} {symbol}) at {formatted_price}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Error placing order: {e}")
            return None

    
    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Cancel existing order"""
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order {order_id} cancelled")
            self.current_order_id = None
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

class JupiterSwapManager:
    def __init__(self, solana_private_key: str, jupiter_api_url: str, jupiter_api_key: str, max_slippage: float):
        self.private_key = solana_private_key
        self.jupiter_api_url = jupiter_api_url
        self.jupiter_api_key = jupiter_api_key
        self.max_slippage = max_slippage
        self.keypair = self._load_keypair(solana_private_key)
    
    def _load_keypair(self, private_key_str: str) -> Keypair:
        """Load keypair from private key string (base58 or JSON array)"""
        private_key_str = private_key_str.strip()
        
        logger.info(f"Loading keypair from {len(private_key_str)} char key: {private_key_str[:20]}...")
        
        try:
            secret_bytes = base58.b58decode(private_key_str)
            logger.debug(f"Base58 decoded to {len(secret_bytes)} bytes")
            
            if len(secret_bytes) == 64:
                seed = secret_bytes[:32]
                kp = Keypair.from_seed(seed)
                logger.info(f"✓ Loaded keypair from base58 format (64 bytes)")
                return kp
            elif len(secret_bytes) == 32:
                kp = Keypair.from_seed(secret_bytes)
                logger.info(f"✓ Loaded keypair from base58 format (32 bytes)")
                return kp
            else:
                logger.error(f"Invalid decoded length: {len(secret_bytes)}, expected 32 or 64")
                raise ValueError(f"Invalid key length: {len(secret_bytes)} bytes")
        except Exception as e:
            logger.debug(f"Base58 decode failed: {e}")
        
        try:
            json_cleaned = private_key_str.replace('\n', '').replace('\r', '').replace(' ', '')
            secret_array = json.loads(json_cleaned)
            if isinstance(secret_array, list):
                secret_bytes = bytes(secret_array)
                if len(secret_bytes) == 64:
                    seed = secret_bytes[:32]
                    kp = Keypair.from_seed(seed)
                    logger.info(f"✓ Loaded keypair from JSON array format (64 bytes)")
                    return kp
                elif len(secret_bytes) == 32:
                    kp = Keypair.from_seed(secret_bytes)
                    logger.info(f"✓ Loaded keypair from JSON array format (32 bytes)")
                    return kp
        except Exception as e:
            logger.debug(f"JSON array parse failed: {e}")
        
        logger.error(f"Private key (first 50 chars): {private_key_str[:50]}")
        raise ValueError(
            f"Invalid private key format. Expected:\n"
            f"  - Base58 encoded string (88 chars = 64 bytes), or\n"
            f"  - JSON array: [1,2,3,...]\n"
            f"Got length: {len(private_key_str)}, starts with: {private_key_str[:50]}"
        )
    
    async def get_order(self, input_mint: str, output_mint: str, amount: int) -> dict:
        """Get swap order from Jupiter Ultra API (GET request with query params)"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.jupiter_api_url}/order"
                params = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount,
                    "taker": str(self.keypair.pubkey())
                }
                headers = {
                    "x-api-key": self.jupiter_api_key
                }
                
                async with session.get(url, params=params, headers=headers) as resp:
                    result = await resp.json()
                    if resp.status == 200 and 'transaction' in result:
                        logger.info(f"Order received")
                        return result
                    else:
                        logger.error(f"Error getting order (status {resp.status}): {result}")
                        return None
        except Exception as e:
            logger.error(f"Error getting Jupiter order: {e}")
            return None
    
    async def execute_swap(self, order: dict) -> Optional[str]:
        """Execute swap by submitting signed transaction to Jupiter's /execute endpoint"""
        try:
            # Extract transaction and requestId from order response
            tx_base64 = order.get('transaction')
            request_id = order.get('requestId')
            
            if not tx_base64:
                logger.error("No transaction in order response")
                return None
            
            if not request_id:
                logger.error("No requestId in order response")
                return None
            
            logger.info(f"Request ID: {request_id}")
            
            # Deserialize VersionedTransaction from base64
            tx_bytes = base64.b64decode(tx_base64)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            
            logger.debug(f"Transaction deserialized")
            logger.debug(f"Number of signature slots: {len(tx.signatures)}")
            
            # Get the message from the transaction
            message = tx.message
            message_bytes = bytes(message)
            logger.debug(f"Message size: {len(message_bytes)} bytes")
            
            # Create a new VersionedTransaction with the presigner
            tx_signed = VersionedTransaction(message, [self.keypair])
            
            logger.info("✓ Transaction signed and reconstructed with Presigner")
            
            # Serialize signed transaction back to base64
            signed_tx_bytes = bytes(tx_signed)
            signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode()
            
            logger.debug(f"Signed transaction size: {len(signed_tx_base64)} chars")
            
            # Submit to Jupiter's /execute endpoint
            async with aiohttp.ClientSession() as session:
                url = f"{self.jupiter_api_url}/execute"
                headers = {
                    "x-api-key": self.jupiter_api_key,
                    "Content-Type": "application/json"
                }
                payload = {
                    "signedTransaction": signed_tx_base64,
                    "requestId": request_id
                }
                
                logger.debug(f"POST to {url}")
                logger.info("Submitting signed transaction to Jupiter /execute...")
                async with session.post(url, json=payload, headers=headers) as resp:
                    result = await resp.json()
                    logger.debug(f"Response status: {resp.status}")
                    logger.debug(f"Response body: {result}")
                    
                    if resp.status == 200 and 'txid' in result:
                        tx_hash = result['txid']
                        logger.info(f"✓ Transaction executed: {tx_hash}")
                        return tx_hash
                    elif 'signature' in result:
                        tx_hash = result['signature']
                        logger.info(f"✓ Transaction executed: {tx_hash}")
                        return tx_hash
                    else:
                        logger.error(f"Unexpected response: {result}")
                        return None
        except Exception as e:
            logger.error(f"Error executing swap: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

class TradingBot:
    def __init__(self, symbol: str, usd_amount: float, config: TradingBotConfig):
        self.symbol = symbol
        self.usd_amount = usd_amount  # USD amount to trade
        self.config = config
        
        self.binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
        self.jupiter = JupiterSwapManager(
            config.solana_private_key,
            config.jupiter_api_url,
            config.jupiter_api_key,
            config.max_slippage
        )
        
        self.running = True
        self.order_filled = False
    
    async def start(self):
        """Start the trading bot"""
        logger.info(f"Starting bot for {self.symbol}, USD amount: ${self.usd_amount:.2f}")
        
        current_price = self.binance.get_current_price(self.symbol)
        if not current_price:
            logger.error("Failed to get initial price")
            return
        
        quote_price = current_price * (1 + self.config.mark_up_percent / 100)
        self.binance.place_limit_sell_order(self.symbol, self.usd_amount, quote_price, current_price)
        
        await asyncio.gather(
            self.monitor_prices(),
            self.monitor_order_fill()
        )
    
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
                    self.order_filled = True
                    await self.execute_dex_buy()
                
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in monitor_order_fill: {e}")
                await asyncio.sleep(5)
    
    async def execute_dex_buy(self):
        """Execute purchase on Jupiter DEX after being filled on Binance"""
        logger.info("Executing DEX buy to complete arbitrage...")
        
        input_mint = os.getenv('BUY_INPUT_MINT')
        output_mint = os.getenv('BUY_OUTPUT_MINT')
        
        if not input_mint or not output_mint:
            logger.error("Missing mint configuration for DEX swap")
            return
        
        amount_in_lamports = int(self.usd_amount * 1e6)  # Convert USD to USDC lamports (6 decimals)
        
        order = await self.jupiter.get_order(input_mint, output_mint, amount_in_lamports)
        if not order:
            logger.error("Failed to get Jupiter order")
            return
        
        tx_hash = await self.jupiter.execute_swap(order)
        if tx_hash:
            logger.info(f"DEX swap executed! Tx: {tx_hash}")
            self.running = False
        else:
            logger.error("Failed to execute DEX swap")

async def test_binance_order(symbol: str, usd_amount: float, config: TradingBotConfig):
    """Test Binance order placement and cancellation"""
    logger.info(f"\n=== Testing Binance Order ({symbol}, ${usd_amount:.2f} USD) ===")
    
    binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
    
    try:
        # Get current price
        price = binance.get_current_price(symbol)
        if not price:
            logger.error("Failed to get price")
            return
        
        # Place sell order at 2% above market
        test_price = price * 1.02
        order = binance.place_limit_sell_order(symbol, usd_amount, test_price, price)
        
        if not order:
            logger.error("Failed to place order")
            return
        
        order_id = order['orderId']
        logger.info(f"✓ Order placed: {order_id}")
        
        # Wait a bit
        await asyncio.sleep(3)
        
        # Cancel order
        logger.info(f"Cancelling order {order_id}...")
        try:
            binance.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"✓ Order cancelled successfully")
        except BinanceAPIException as e:
            logger.error(f"Error cancelling order: {e}")
            return
        
        logger.info("✓ Test completed successfully!\n")
    
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return

async def test_jupiter_swap(config: TradingBotConfig):
    """Test Jupiter swap with small amount ($0.10 USDT)"""
    logger.info(f"\n=== Testing Jupiter Swap ($0.10 USDT) ===")
    
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
            logger.error("Missing BUY_INPUT_MINT or BUY_OUTPUT_MINT in .env")
            return
        
        logger.info(f"Input mint: {input_mint}")
        logger.info(f"Output mint: {output_mint}")
        
        # 0.10 USDT (6 decimals)
        amount = int(0.10 * 1e6)
        logger.info(f"Amount: {amount} lamports")
        
        # Get order from Jupiter
        logger.info("\n1. Getting order from Jupiter...")
        order = await jupiter.get_order(input_mint, output_mint, amount)
        
        if not order:
            logger.error("Failed to get order")
            return
        
        logger.info(f"✓ Order received!")
        logger.info(f"Transaction size: {len(order.get('transaction', ''))} chars")
        
        # Log order details (excluding large transaction field)
        order_info = {k: v for k, v in order.items() if k != 'transaction'}
        logger.info(f"Order details: {json.dumps(order_info, indent=2)}")
        
        # Execute the swap
        logger.info("\n2. Executing swap...")
        logger.warning("⚠️  This will actually execute the swap and cost SOL fees!")
        tx_hash = await jupiter.execute_swap(order)
        
        if not tx_hash:
            logger.error("Failed to execute swap")
            return
        
        logger.info(f"✓ Swap executed successfully!")
        logger.info(f"Transaction hash: {tx_hash}")
        logger.info(f"View on Solscan: https://solscan.io/tx/{tx_hash}")
    
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

async def main():
    parser = argparse.ArgumentParser(description='CEX/DEX Arbitrage Trading Bot')
    parser.add_argument('--mode', default='trade', 
                       choices=['trade', 'test-binance', 'test-jupiter'],
                       help='Operation mode')
    parser.add_argument('--symbol', default='PIPPINUSDT',
                       help='Trading symbol (e.g., PIPPINUSDT)')
    parser.add_argument('--usd-amount', type=float, default=100.0,
                       help='USD amount to trade')
    
    args = parser.parse_args()
    
    config = TradingBotConfig()
    
    if args.mode == 'trade':
        logger.info(f"Starting arbitrage bot: {args.symbol} ${args.usd_amount:.2f} USD")
        bot = TradingBot(args.symbol, args.usd_amount, config)
        await bot.start()
    
    elif args.mode == 'test-binance':
        await test_binance_order(args.symbol, args.usd_amount, config)
    
    elif args.mode == 'test-jupiter':
        await test_jupiter_swap(config)

if __name__ == "__main__":
    asyncio.run(main())