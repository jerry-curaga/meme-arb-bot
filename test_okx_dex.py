"""
Test script for OKX DEX integration
"""
import asyncio
import logging
from config import TradingBotConfig
from managers.okx_dex_manager import OKXDexManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_bsc_quote():
    """Test getting a quote for BSC swap"""
    print("\n=== Testing BSC Quote ===")

    config = TradingBotConfig()

    okx = OKXDexManager(
        api_key=config.okx_api_key,
        secret_key=config.okx_secret_key,
        passphrase=config.okx_passphrase,
        bsc_private_key=config.bsc_private_key,
        max_slippage=1.0
    )

    # Test: USDT -> BUSD on BSC
    # USDT on BSC: 0x55d398326f99059fF775485246999027B3197955
    # BUSD on BSC: 0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56

    usdt_address = "0x55d398326f99059fF775485246999027B3197955"
    busd_address = "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"
    amount = str(1 * 10**18)  # 1 USDT (18 decimals)

    quote = await okx.get_quote('bsc', usdt_address, busd_address, amount)

    if quote:
        print(f"✓ BSC Quote successful!")
        print(f"  From: {quote.get('fromTokenAmount')} USDT")
        print(f"  To: {quote.get('toTokenAmount')} BUSD")
        print(f"  Route: {quote.get('routerResult', {}).get('dexRouterList', [])}")
    else:
        print("✗ Failed to get BSC quote")


async def test_solana_quote():
    """Test getting a quote for Solana swap"""
    print("\n=== Testing Solana Quote ===")

    config = TradingBotConfig()

    okx = OKXDexManager(
        api_key=config.okx_api_key,
        secret_key=config.okx_secret_key,
        passphrase=config.okx_passphrase,
        solana_private_key=config.solana_private_key,
        max_slippage=1.0
    )

    # Test: USDC -> SOL on Solana
    # USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    # SOL (wrapped): So11111111111111111111111111111111111111112

    usdc_address = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    sol_address = "So11111111111111111111111111111111111111112"
    amount = str(1 * 10**6)  # 1 USDC (6 decimals)

    quote = await okx.get_quote('solana', usdc_address, sol_address, amount)

    if quote:
        print(f"✓ Solana Quote successful!")
        print(f"  From: {quote.get('fromTokenAmount')} USDC")
        print(f"  To: {quote.get('toTokenAmount')} SOL")
        print(f"  Route: {quote.get('routerResult', {}).get('dexRouterList', [])}")
    else:
        print("✗ Failed to get Solana quote")


async def test_swap_data():
    """Test getting swap transaction data"""
    print("\n=== Testing Swap Data Retrieval ===")

    config = TradingBotConfig()

    okx = OKXDexManager(
        api_key=config.okx_api_key,
        secret_key=config.okx_secret_key,
        passphrase=config.okx_passphrase,
        solana_private_key=config.solana_private_key,
        max_slippage=1.0
    )

    # Small test: 0.10 USDC -> SOL
    usdc_address = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    sol_address = "So11111111111111111111111111111111111111112"
    amount = str(int(0.10 * 10**6))  # 0.10 USDC

    swap_data = await okx.get_swap_data('solana', usdc_address, sol_address, amount)

    if swap_data:
        print(f"✓ Swap data retrieved!")
        print(f"  Has transaction: {'tx' in swap_data}")
        print(f"  Router list: {swap_data.get('routerResult', {}).get('dexRouterList', [])}")
    else:
        print("✗ Failed to get swap data")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("OKX DEX Integration Test")
    print("=" * 60)

    try:
        # Test BSC quote
        await test_bsc_quote()

        # Test Solana quote
        await test_solana_quote()

        # Test swap data (doesn't execute)
        await test_swap_data()

        print("\n" + "=" * 60)
        print("Tests completed!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
