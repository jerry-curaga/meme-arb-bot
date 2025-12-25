"""
Test OKX DEX swap on Solana for PIPPIN
"""
import asyncio
from config import TradingBotConfig
from managers.okx_dex_manager import OKXDexManager

async def main():
    config = TradingBotConfig()

    # PIPPIN on Solana
    input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
    output_mint = "Dfh5DzRgSvvCFDoYc2ciTkMrbDfRKybA4SoFbPmApump"  # PIPPIN
    amount_usd = 0.10

    print(f"🧪 Testing OKX DEX Swap on Solana")
    print(f"   Amount: ${amount_usd} USD")
    print(f"   From: USDC ({input_mint})")
    print(f"   To: PIPPIN ({output_mint})")
    print()

    # Initialize OKX DEX manager
    okx = OKXDexManager(
        api_key=config.okx_api_key,
        secret_key=config.okx_secret_key,
        passphrase=config.okx_passphrase,
        solana_private_key=config.solana_private_key,
        max_slippage=0.5
    )

    # Convert USD to lamports (USDC has 6 decimals)
    amount = str(int(amount_usd * 1e6))
    print(f"💰 Amount in lamports: {amount}")
    print()

    # Get swap data first to see what we're working with
    print("🔄 Getting swap data...")
    swap_data = await okx.get_swap_data(
        chain='solana',
        from_token_address=input_mint,
        to_token_address=output_mint,
        amount=amount
    )

    if swap_data:
        print(f"✓ Swap data received:")
        print(f"   To token amount: {swap_data.get('routerResult', {}).get('toTokenAmount', 'N/A')}")
        print(f"   TX data present: {'tx' in swap_data}")
        if 'tx' in swap_data:
            tx_info = swap_data['tx']
            print(f"   TX keys: {list(tx_info.keys())}")
            print(f"   'data' field (first 200 chars): {str(tx_info.get('data', ''))[:200]}")
            print(f"   'signatureData' present: {'signatureData' in tx_info}")
            if 'signatureData' in tx_info:
                sig_data = tx_info['signatureData']
                print(f"   signatureData type: {type(sig_data)}")
                if isinstance(sig_data, list) and sig_data:
                    print(f"   signatureData[0] (first 100 chars): {str(sig_data[0])[:100]}")
        print()
        print(f"Full swap_data: {swap_data}")
        print()
    else:
        print("❌ Failed to get swap data")
        return

    # Execute swap
    print("🔄 Executing swap...")
    result = await okx.execute_swap_solana(swap_data)

    if result and result.get('success'):
        print("✅ Swap successful!")
        print(f"   Signed TX: {result.get('signed_transaction', 'N/A')[:100]}...")
    else:
        print("❌ Swap failed!")
        print(f"   Error: {result}")

if __name__ == "__main__":
    asyncio.run(main())
