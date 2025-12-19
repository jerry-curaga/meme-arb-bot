"""
Trading bot configuration
"""
import os
from dotenv import load_dotenv

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
