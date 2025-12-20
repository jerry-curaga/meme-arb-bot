#!/usr/bin/env python
"""
Measure latency to Binance API and Jupiter API
"""
import asyncio
import time
import logging
from statistics import mean, median, stdev
from config import TradingBotConfig
from managers.binance_manager import BinanceManager
from managers.jupiter_manager import JupiterSwapManager

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


async def measure_binance_rest_latency(binance: BinanceManager, symbol: str, iterations: int = 10):
    """Measure REST API latency for common operations"""
    print("\n" + "="*60)
    print("📊 BINANCE REST API LATENCY")
    print("="*60)

    # Measure get_current_price
    latencies = []
    print(f"\nTesting get_current_price() - {iterations} iterations...")
    for i in range(iterations):
        start = time.perf_counter()
        binance.get_current_price(symbol)
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)
        print(f"  [{i+1}/{iterations}] {latency_ms:.2f}ms")
        await asyncio.sleep(0.1)  # Small delay between requests

    print(f"\n📈 get_current_price() Statistics:")
    print(f"   Mean:   {mean(latencies):.2f}ms")
    print(f"   Median: {median(latencies):.2f}ms")
    print(f"   Min:    {min(latencies):.2f}ms")
    print(f"   Max:    {max(latencies):.2f}ms")
    if len(latencies) > 1:
        print(f"   StdDev: {stdev(latencies):.2f}ms")

    # Measure get_open_orders
    latencies = []
    print(f"\nTesting get_open_orders() - {iterations} iterations...")
    for i in range(iterations):
        start = time.perf_counter()
        binance.get_open_orders(symbol)
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)
        print(f"  [{i+1}/{iterations}] {latency_ms:.2f}ms")
        await asyncio.sleep(0.1)

    print(f"\n📈 get_open_orders() Statistics:")
    print(f"   Mean:   {mean(latencies):.2f}ms")
    print(f"   Median: {median(latencies):.2f}ms")
    print(f"   Min:    {min(latencies):.2f}ms")
    print(f"   Max:    {max(latencies):.2f}ms")
    if len(latencies) > 1:
        print(f"   StdDev: {stdev(latencies):.2f}ms")


async def measure_binance_websocket_latency(binance: BinanceManager, duration: int = 10):
    """Measure WebSocket connection and keep-alive latency"""
    print("\n" + "="*60)
    print("📊 BINANCE WEBSOCKET LATENCY")
    print("="*60)

    print(f"\nConnecting to WebSocket and measuring for {duration} seconds...")

    connection_start = time.perf_counter()
    message_times = []

    async def message_callback(msg):
        """Track when messages arrive"""
        message_times.append(time.perf_counter())

    try:
        # Measure connection time
        await asyncio.wait_for(
            binance.start_user_stream(message_callback),
            timeout=duration
        )
    except asyncio.TimeoutError:
        connection_time = (message_times[0] - connection_start) * 1000 if message_times else 0

        print(f"\n📈 WebSocket Statistics:")
        print(f"   Connection time: {connection_time:.2f}ms")
        print(f"   Messages received: {len(message_times)}")

        if len(message_times) > 1:
            # Calculate intervals between messages
            intervals = [(message_times[i] - message_times[i-1]) * 1000
                        for i in range(1, len(message_times))]
            print(f"   Mean interval: {mean(intervals):.2f}ms")
            print(f"   Median interval: {median(intervals):.2f}ms")

        await binance.stop_user_stream()


async def measure_jupiter_latency(jupiter: JupiterSwapManager, symbol: str, iterations: int = 5):
    """Measure Jupiter API latency for quote requests"""
    print("\n" + "="*60)
    print("📊 JUPITER API LATENCY")
    print("="*60)

    # Get market config for token addresses
    from config import get_market_config
    market_config = get_market_config(symbol)

    # Test quote request (GET /order)
    latencies = []
    print(f"\nTesting get_order() - {iterations} iterations...")
    print(f"   (USDC → Output token quote)")

    for i in range(iterations):
        start = time.perf_counter()
        await jupiter.get_order(
            input_mint=market_config['input_mint'],
            output_mint=market_config['output_mint'],
            amount=10_000_000  # 10 USDC in lamports
        )
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)
        print(f"  [{i+1}/{iterations}] {latency_ms:.2f}ms")
        await asyncio.sleep(0.5)  # Delay between requests

    print(f"\n📈 get_order() Statistics:")
    print(f"   Mean:   {mean(latencies):.2f}ms")
    print(f"   Median: {median(latencies):.2f}ms")
    print(f"   Min:    {min(latencies):.2f}ms")
    print(f"   Max:    {max(latencies):.2f}ms")
    if len(latencies) > 1:
        print(f"   StdDev: {stdev(latencies):.2f}ms")


async def main():
    print("\n" + "="*60)
    print("🔍 LATENCY MEASUREMENT TOOL")
    print("="*60)
    print("\nThis tool measures network latency to:")
    print("  • Binance Futures API (REST)")
    print("  • Binance WebSocket (real-time)")
    print("  • Jupiter API (Solana DEX)")
    print("\nResults will help determine if running on a")
    print("dedicated server would improve execution speed.")

    config = TradingBotConfig()
    symbol = "PIPPINUSDT"  # Default test symbol

    # Initialize managers
    binance = BinanceManager(config.binance_api_key, config.binance_api_secret)
    jupiter = JupiterSwapManager(
        config.solana_private_key,
        config.jupiter_api_url,
        config.jupiter_api_key,
        config.max_slippage
    )

    # Run measurements
    await measure_binance_rest_latency(binance, symbol)
    await measure_jupiter_latency(jupiter, symbol)
    await measure_binance_websocket_latency(binance)

    # Summary and recommendations
    print("\n" + "="*60)
    print("💡 RECOMMENDATIONS")
    print("="*60)
    print("\nLatency benchmarks for arbitrage trading:")
    print("  • Excellent: < 50ms total")
    print("  • Good:      50-100ms")
    print("  • Acceptable: 100-200ms")
    print("  • Poor:      > 200ms")
    print("\nTypical server locations:")
    print("  • AWS Tokyo (ap-northeast-1): ~5-20ms to Binance")
    print("  • AWS Singapore (ap-southeast-1): ~10-30ms to Binance")
    print("  • AWS US-East (us-east-1): ~150-200ms to Binance")
    print("\nIf your latency is > 100ms, consider running on a")
    print("server closer to Binance's infrastructure (Asia).")


if __name__ == "__main__":
    asyncio.run(main())
