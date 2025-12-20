#!/usr/bin/env python
"""
Measure complete Jupiter swap flow timing
"""
import asyncio
import time
from config import TradingBotConfig, get_market_config
from managers.jupiter_manager import JupiterSwapManager


async def measure_complete_flow():
    """Measure timing of each step in Jupiter swap flow"""
    print("\n" + "="*60)
    print("⏱️  JUPITER COMPLETE FLOW TIMING")
    print("="*60)

    config = TradingBotConfig()
    market_config = get_market_config("PIPPINUSDT")

    jupiter = JupiterSwapManager(
        config.solana_private_key,
        config.jupiter_api_url,
        config.jupiter_api_key,
        config.max_slippage
    )

    print("\n📊 Testing with 10 USDC swap (USDC → PIPPIN)")
    print("="*60)

    # Measure get_order
    print("\n[Step 1] Getting quote from Jupiter...")
    start_get = time.perf_counter()
    order = await jupiter.get_order(
        input_mint=market_config['input_mint'],
        output_mint=market_config['output_mint'],
        amount=10_000_000  # 10 USDC
    )
    end_get = time.perf_counter()
    get_time_ms = (end_get - start_get) * 1000

    if not order:
        print("❌ Failed to get order")
        return

    print(f"✅ Quote received: {get_time_ms:.2f}ms")
    print(f"   Request ID: {order.get('requestId', 'N/A')}")

    # Note: We'll measure execute_swap but NOT actually submit it
    # to avoid real transaction. Just measure signing time.
    print("\n[Step 2] Signing transaction locally...")
    start_sign = time.perf_counter()

    # Simulate signing without executing
    import base64
    from solders.transaction import VersionedTransaction

    tx_base64 = order.get('transaction')
    tx_bytes = base64.b64decode(tx_base64)
    tx = VersionedTransaction.from_bytes(tx_bytes)
    message = tx.message
    tx_signed = VersionedTransaction(message, [jupiter.keypair])
    signed_tx_bytes = bytes(tx_signed)
    signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode()

    end_sign = time.perf_counter()
    sign_time_ms = (end_sign - start_sign) * 1000

    print(f"✅ Transaction signed: {sign_time_ms:.2f}ms")
    print(f"   Signed tx size: {len(signed_tx_base64)} chars")

    # Summary
    print("\n" + "="*60)
    print("📈 TIMING BREAKDOWN")
    print("="*60)
    print(f"  1. Get quote (API call):     {get_time_ms:>8.2f}ms")
    print(f"  2. Sign transaction (local): {sign_time_ms:>8.2f}ms")
    print(f"  3. Submit + confirm (API):   ~1000-2000ms (estimated)")
    print(f"     " + "-"*40)
    print(f"  Total (estimated):           ~{get_time_ms + sign_time_ms + 1500:.0f}ms")
    print()
    print(f"⚠️  The 2.4s for step 1 is concerning.")
    print(f"    This is just a GET request for a quote.")
    print(f"    Possible causes:")
    print(f"      • Network latency to Jupiter API")
    print(f"      • Jupiter route computation time")
    print(f"      • API rate limiting / queueing")
    print()
    print(f"💡 For comparison:")
    print(f"    • Good Jupiter quote time: 100-500ms")
    print(f"    • Your quote time: {get_time_ms:.0f}ms")
    print(f"    • Ratio: {get_time_ms/300:.1f}x slower than expected")


if __name__ == "__main__":
    asyncio.run(measure_complete_flow())
