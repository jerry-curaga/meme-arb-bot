"""
Trading bot configuration
"""
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def load_markets(markets_file='markets.json'):
    """Load market configurations from JSON file

    Returns:
        dict: Market configurations keyed by symbol
    """
    try:
        with open(markets_file, 'r') as f:
            markets = json.load(f)
        return markets
    except FileNotFoundError:
        raise FileNotFoundError(f"Markets configuration file not found: {markets_file}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in markets file: {e}")


def get_market_config(symbol: str, markets_file='markets.json'):
    """Get market configuration for a specific symbol

    Args:
        symbol: Trading symbol (e.g., 'PIPPINUSDT')
        markets_file: Path to markets configuration file

    Returns:
        dict: Market configuration with keys: binance_symbol, input_mint, output_mint, name, description

    Raises:
        ValueError: If symbol not found in markets configuration
    """
    markets = load_markets(markets_file)
    if symbol not in markets:
        available = ', '.join(markets.keys())
        raise ValueError(f"Symbol '{symbol}' not found in markets.json. Available: {available}")
    return markets[symbol]


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
