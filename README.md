# Meme Arbitrage Bot

A Python bot that executes profitable arbitrage between Binance perpetual futures and Jupiter DEX (Solana) using consistent USD amounts.

## ✨ Latest Features

- **🎮 Interactive Command Interface** - Type commands directly instead of command-line arguments
- **💰 USD Amount Consistency** - Both Binance and Jupiter use the same USD amounts
- **🛠️ Management Commands** - Stop, balance checking, order management, emergency liquidation
- **📊 Comprehensive Logging** - Separate timestamped logs for orders and trades
- **📡 Real-time Monitoring** - Account balances, open orders, and position tracking
- **🛡️ Safety Controls** - Emergency stop and position liquidation commands

## How It Works

1. **Quotes on Binance Perpetuals** at 3% above market price
2. **Dynamically updates** when market moves 0.5% (to catch market orders)
3. **On fill**: Automatically executes corresponding buy on Jupiter
4. **Captures spread** for profit

Example flow:
- Market: 0.3398 PIPPIN-USDT
- Bot quotes: 0.3508 (3% markup)
- When filled at 0.3508 → instantly buys on Jupiter
- Profit from CEX/DEX spread

## Prerequisites

- Python 3.9+ (tested on 3.12.3 with pyenv)
- Active Binance account with USD-M Futures enabled
- Solana wallet with SOL for transaction fees
- Internet connection

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/jerry-curaga/meme-arb-bot.git
cd meme-arb-bot
```

### 2. Setup Python Environment

```bash
# Using pyenv (recommended)
pyenv local 3.12.3
python --version  # Verify

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies included:**
- `python-binance>=1.0.20` - Binance Futures API
- `solders==0.18.1` - Solana SDK
- `aiohttp==3.9.1` - Async HTTP
- `base58==2.1.1` - Key encoding
- `python-dotenv==1.0.0` - Environment variables

## Configuration

### 1. Get Binance API Keys

Go to [Binance Account Settings](https://www.binance.com/en/my/settings/api-management):
1. Create new API key (with **Futures API** enabled)
2. Enable **Futures API** permission
3. Set IP whitelist (or disable for local testing)
4. Copy API Key and Secret

### 2. Enable USD-M Futures

Go to [Binance Account](https://www.binance.com/en/account):
1. Click **USD-M Futures** in sidebar
2. Click **Enable USD-M Futures**
3. Complete agreement and verification

### 3. Fund Futures Wallet

1. Go to [Binance Futures](https://www.binance.com/en/futures/usdt)
2. Click **Wallet** → **Transfer**
3. Transfer USDT from Spot to USD-M Futures
4. Start with 10-100 USDT for testing

### 4. Get Solana Private Key

```bash
# Export from Solana CLI
solana-keygen to-base58 ~/.config/solana/id.json
```

Or from Phantom wallet:
1. Settings → Security & Privacy
2. Export Private Key (in base58 format)

### 5. Create `.env` File

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in your values:

```
# Binance API
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Solana
SOLANA_PRIVATE_KEY=your_base58_private_key_here

# Jupiter
JUPITER_API_URL=https://api.jup.ag/ultra

# Token Mints (Solana)
# USDT on Solana: Es9vMFrzaCERmJfqV7eSsayRsZKvCDoVVQHnGeEsNVzJ
# Find mints at: https://solscan.io/
BUY_INPUT_MINT=Es9vMFrzaCERmJfqV7eSsayRsZKvCDoVVQHnGeEsNVzJ
BUY_OUTPUT_MINT=PippinMintAddressHere
```

**Finding token mints:**
- Go to [Solscan.io](https://solscan.io/)
- Search token symbol (e.g., "PIPPIN")
- Copy mint address from Token Info

## Usage

### 🎮 Interactive Mode (Recommended)

Simply run the bot to enter interactive mode:

```bash
python cex_dex_bot.py
```

**Interactive Interface:**
```
╔══════════════════════════════════════╗
║        Meme Arbitrage Bot v2.0       ║
║     Interactive Command Interface    ║
╚══════════════════════════════════════╝

Current Settings:
  Symbol: PIPPINUSDT
  USD Amount: $100.00

Type 'help' for available commands or 'quit' to exit.

[PIPPINUSDT] $ help

📊 MONITORING:
  balance          - Show account balances and positions
  orders           - List all open orders
  status           - Show current bot status

🤖 TRADING:
  start            - Start arbitrage bot with current settings
  stop             - Stop running arbitrage bot
  test-binance     - Test Binance orders (safe)
  test-jupiter     - Test Jupiter swaps (safe)

⚙️ SETTINGS:
  set symbol <SYM> - Change trading symbol (e.g., set symbol BTCUSDT)
  set amount <USD> - Change USD amount (e.g., set amount 50.0)
  show             - Show current settings

🛡️ RISK MANAGEMENT:
  close-all        - Cancel all open orders
  liquidate        - Emergency: close all positions (⚠️ CAUTION)

[PIPPINUSDT] $ set symbol SOLUSDT
✅ Symbol changed to SOLUSDT

[SOLUSDT] $ set amount 25.0
✅ USD amount changed to $25.00

[SOLUSDT] $ start
🚀 Starting arbitrage bot: SOLUSDT $25.00 USD
✅ Bot started in background! Use 'stop' to halt trading.
```

### 📋 Command-Line Mode (Legacy)

You can still use direct commands:

```bash
# Start trading directly
python cex_dex_bot.py --mode trade --symbol BTCUSDT --usd-amount 50.0

# Test commands
python cex_dex_bot.py --mode test-binance --symbol PIPPINUSDT --usd-amount 10.0
python cex_dex_bot.py --mode balance --symbol PIPPINUSDT
```


## Bot Management Commands

The bot includes comprehensive management commands for controlling operations:

### Check Account Status

```bash
# View balances and positions
python cex_dex_bot.py --mode balance --symbol PIPPINUSDT

# Check open orders
python cex_dex_bot.py --mode orders --symbol PIPPINUSDT
```

### Risk Management

```bash
# Cancel all open orders (safe)
python cex_dex_bot.py --mode close-all --symbol PIPPINUSDT

# Emergency liquidation (⚠️ CAUTION: closes all positions)
python cex_dex_bot.py --mode liquidate --symbol PIPPINUSDT

# Stop bot gracefully
python cex_dex_bot.py --mode stop
```

### Management Features

- **Real-time balance checking** - Binance Futures + Solana wallet info
- **Order monitoring** - List all open orders with details
- **Emergency controls** - Quickly close orders and positions
- **Comprehensive logging** - All actions logged with timestamps
- **Safety warnings** - Alerts for destructive operations

**Log Files:**
- `orders.log` - Order placements, fills, and cancellations
- `trades.log` - CEX fills, DEX swaps, and liquidations

See `COMMANDS.md` for complete command reference.

## Configuration & Tuning

Edit in `cex_dex_bot.py`:

```python
# In TradingBotConfig class:
self.mark_up_percent = 3.0          # Markup above market (adjust for profitability)
self.price_change_threshold = 0.5   # Update order if market moves this % (lower = more updates)
self.max_slippage = 1.0             # Max slippage on Jupiter swap (lower = stricter)
```

**Recommended adjustments:**
- **High volatility**: Increase `mark_up_percent` to 4-5%
- **Fast market**: Decrease `price_change_threshold` to 0.3%
- **Low liquidity**: Increase `max_slippage` to 2-3%

## Troubleshooting

### "Invalid API-key, IP, or permissions"

- Verify API key has **Futures API** enabled on Binance
- Check IP whitelist (disable for testing, or add your IP)
- Regenerate API key if permission changes aren't taking effect

### "Insufficient margin"

- Need more USDT in Futures wallet
- Transfer USDT from Spot to USD-M Futures
- Start with smaller amount (e.g., $10 USD)

### "Invalid symbol"

- Symbol doesn't exist on Binance Perpetuals
- Check: [Binance Futures](https://www.binance.com/en/futures/BTCUSDT)
- Use format: `SYMBOLUSDT` (e.g., `BTCUSDT`, `SOLUSDT`)

### "Price not increased by tick size"

- Bot not formatting prices correctly (should be fixed now)
- Try: `python cex_dex_bot.py --mode test-binance`

### "Slippage exceeded" on Jupiter

- Token has low liquidity on DEX
- Increase `max_slippage` in config
- Check Jupiter: https://jup.ag/

### RPC/Network errors

- Verify internet connection
- Check if Jupiter API is up: `curl https://api.jup.ag/ultra`

## Testing Workflow

Before running the live bot:

1. **Test Binance** (no risk):
   ```bash
   python cex_dex_bot.py --mode test-binance --usd-amount 10.0
   ```

2. **Test Jupiter** (small amount):
   ```bash
   python cex_dex_bot.py --mode test-jupiter
   ```

3. **Run with small amount** (real money):
   ```bash
   python cex_dex_bot.py --usd-amount 10.0
   ```

4. **Monitor logs** for fills and swaps

5. **Scale up** once you verify end-to-end

## Risk Management

- **Start small**: Test with $10-100 USD first
- **Monitor slippage**: Adjust based on token liquidity
- **Keep SOL funded**: Need for Solana transaction fees (~0.0003 SOL per swap)
- **Watch fees**:
  - Binance: ~0.02% (maker/taker)
  - Jupiter: ~0.25% average
  - Solana: ~0.0003 SOL (~$0.01)

**Break-even spread**: Need at least 0.5-1% to cover all fees

## Security Best Practices

- ✓ Never commit `.env` to git (add to `.gitignore`)
- ✓ Use environment variables in production
- ✓ Rotate API keys monthly
- ✓ Use IP whitelist on Binance
- ✓ Keep Solana wallet separate from main funds
- ✓ Monitor account for unauthorized access

## Advanced Usage

### Run Multiple Pairs Simultaneously

Create separate scripts or modify `main()`:

```python
# Run two bots concurrently
async def main():
    config = TradingBotConfig()
    
    bot1 = TradingBot('PIPPINUSDT', 100, config)
    bot2 = TradingBot('BTCUSDT', 0.001, config)
    
    await asyncio.gather(
        bot1.start(),
        bot2.start()
    )
```

### Add Telegram Notifications

```python
async def notify(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    await aiohttp.ClientSession().post(url, json={
        "chat_id": chat_id,
        "text": message
    })
```

### Database Logging

```python
import sqlite3

def log_trade(symbol, order_id, fill_price, swap_tx):
    conn = sqlite3.connect('trades.db')
    conn.execute('''
        INSERT INTO trades (symbol, order_id, fill_price, swap_tx, timestamp)
        VALUES (?, ?, ?, ?, datetime('now'))
    ''', (symbol, order_id, fill_price, swap_tx))
    conn.commit()
```

## Production Checklist

- [ ] Test Binance orders with `--mode test-binance`
- [ ] Test Jupiter with `--mode test-jupiter`
- [ ] Run with small amount ($10-20 USD) for 30+ minutes
- [ ] Monitor logs for errors
- [ ] Verify first successful fill + swap
- [ ] Document expected spread for your pair
- [ ] Set up log rotation if running 24/7
- [ ] Keep backups of `.env`
- [ ] Monitor account balance

## Troubleshooting Tips

**Check logs in real-time:**
```bash
python cex_dex_bot.py 2>&1 | grep -i "error\|order\|swap"
```

**Test connectivity:**
```bash
# Binance
curl https://api.binance.com/api/v3/ping

# Jupiter
curl https://api.jup.ag/ultra/orders

# Solana
curl https://api.mainnet-beta.solana.com -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash","params":[]}'
```

**Verify private key format:**
```python
import base58
key = "YOUR_KEY"
decoded = base58.b58decode(key)
print(f"Length: {len(decoded)}")  # Should be 64
```

## Support & Questions

- **Binance Docs**: https://binance-docs.github.io/apidocs/futures/en
- **Jupiter Docs**: https://dev.jup.ag/
- **Solana Docs**: https://docs.solana.com/
- **Solders (SDK)**: https://github.com/kevinheavey/solders

## License

MIT