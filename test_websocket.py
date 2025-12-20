#!/usr/bin/env python
"""
Quick test to verify WebSocket connection to Binance
"""
import asyncio
import logging
from config import TradingBotConfig
from managers.binance_manager import BinanceManager

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_callback(order_data):
    """Test callback function"""
    print(f"✅ Received order update: {order_data.get('orderId', 'unknown')}")
    print(f"   Status: {order_data.get('status', 'unknown')}")
    print(f"   Symbol: {order_data.get('symbol', 'unknown')}")


async def main():
    print("=" * 60)
    print("WebSocket Connection Test")
    print("=" * 60)

    try:
        config = TradingBotConfig()
        print("✅ Config loaded")

        binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
        print("✅ BinanceManager created")

        print("\n🔌 Connecting to Binance WebSocket...")
        print("   (This will listen for order updates for 10 seconds)")
        print("   If you have an active order that fills, you'll see it here\n")

        # Run WebSocket for 10 seconds
        try:
            await asyncio.wait_for(
                binance.start_user_stream(test_callback),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            print("\n✅ WebSocket test completed (10s timeout)")
            print("   Connection was successful!")
            await binance.stop_user_stream()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
