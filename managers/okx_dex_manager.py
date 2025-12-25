"""
OKX DEX swap manager for multi-chain (BSC + Solana)
"""
import json
import base64
import logging
import time
import hmac
import hashlib
from typing import Optional, Literal
import base58
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from web3 import Web3

logger = logging.getLogger(__name__)

ChainType = Literal['bsc', 'solana']


class OKXDexManager:
    """
    OKX DEX aggregator supporting both BSC (EVM) and Solana chains
    """

    # Chain configurations
    CHAINS = {
        'bsc': {
            'chainId': '56',
            'type': 'evm',
            'name': 'Binance Smart Chain',
            'rpc_url': 'https://bsc-dataseed1.binance.org'
        },
        'solana': {
            'chainId': '501',
            'type': 'solana',
            'name': 'Solana Mainnet'
        }
    }

    BASE_URL = "https://www.okx.com"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        solana_private_key: Optional[str] = None,
        bsc_private_key: Optional[str] = None,
        max_slippage: float = 1.0
    ):
        """
        Initialize OKX DEX manager

        Args:
            api_key: OKX API key
            secret_key: OKX API secret
            passphrase: OKX API passphrase
            solana_private_key: Solana wallet private key (base58 or JSON)
            bsc_private_key: BSC wallet private key (hex format)
            max_slippage: Maximum slippage tolerance (default 1.0%)
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.max_slippage = max_slippage

        # Solana wallet
        self.solana_keypair = None
        if solana_private_key:
            self.solana_keypair = self._load_solana_keypair(solana_private_key)
            logger.info(f"Solana wallet loaded: {self.solana_keypair.pubkey()}")

        # BSC wallet (Web3)
        self.bsc_account = None
        self.bsc_web3 = None
        if bsc_private_key:
            self.bsc_web3 = Web3(Web3.HTTPProvider(self.CHAINS['bsc']['rpc_url']))
            self.bsc_account = self.bsc_web3.eth.account.from_key(bsc_private_key)
            logger.info(f"BSC wallet loaded: {self.bsc_account.address}")

    def _load_solana_keypair(self, private_key_str: str) -> Keypair:
        """Load Solana keypair from private key string (base58 or JSON array)"""
        private_key_str = private_key_str.strip()

        logger.info(f"Loading Solana keypair from {len(private_key_str)} char key")

        # Try base58 format
        try:
            secret_bytes = base58.b58decode(private_key_str)
            if len(secret_bytes) == 64:
                seed = secret_bytes[:32]
                kp = Keypair.from_seed(seed)
                logger.info(f"✓ Loaded keypair from base58 format (64 bytes)")
                return kp
            elif len(secret_bytes) == 32:
                kp = Keypair.from_seed(secret_bytes)
                logger.info(f"✓ Loaded keypair from base58 format (32 bytes)")
                return kp
        except Exception as e:
            logger.debug(f"Base58 decode failed: {e}")

        # Try JSON array format
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

        raise ValueError(
            f"Invalid Solana private key format. Expected base58 or JSON array, "
            f"got length: {len(private_key_str)}"
        )

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = '') -> str:
        """
        Generate HMAC SHA256 signature for OKX API authentication

        Args:
            timestamp: ISO timestamp string
            method: HTTP method (GET, POST)
            request_path: API endpoint path
            body: Request body (empty for GET)

        Returns:
            Base64-encoded signature
        """
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf-8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str, body: str = '') -> dict:
        """
        Generate authentication headers for OKX API
        """
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
        signature = self._generate_signature(timestamp, method, request_path, body)

        return {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }

    async def get_quote(
        self,
        chain: ChainType,
        from_token_address: str,
        to_token_address: str,
        amount: str,
        slippage: Optional[float] = None
    ) -> Optional[dict]:
        """
        Get swap quote from OKX DEX

        Args:
            chain: 'bsc' or 'solana'
            from_token_address: Input token address
            to_token_address: Output token address
            amount: Amount in base units (e.g., lamports for SOL)
            slippage: Slippage tolerance (default: self.max_slippage)

        Returns:
            Quote response dict or None if failed
        """
        try:
            if chain not in self.CHAINS:
                raise ValueError(f"Unsupported chain: {chain}")

            chain_id = self.CHAINS[chain]['chainId']
            slippage_value = slippage if slippage is not None else self.max_slippage

            # Build request
            request_path = '/api/v5/dex/aggregator/quote'
            params = {
                'chainId': chain_id,
                'fromTokenAddress': from_token_address,
                'toTokenAddress': to_token_address,
                'amount': str(amount),
                'slippage': str(slippage_value / 100)  # Convert % to decimal (1% -> 0.01)
            }

            # Build query string
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_path = f"{request_path}?{query_string}"

            headers = self._get_headers('GET', full_path)
            url = f"{self.BASE_URL}{full_path}"

            logger.info(f"Getting quote for {chain}: {from_token_address} -> {to_token_address}")
            logger.debug(f"Quote URL: {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get('code') == '0':
                        quote_data = result.get('data', [{}])[0]
                        logger.info(f"✓ Quote received: {quote_data.get('toTokenAmount', 'N/A')} output")
                        return quote_data
                    else:
                        logger.error(f"Quote failed (status {resp.status}): {result}")
                        return None

        except Exception as e:
            logger.error(f"Error getting OKX DEX quote: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def get_swap_data(
        self,
        chain: ChainType,
        from_token_address: str,
        to_token_address: str,
        amount: str,
        slippage: Optional[float] = None,
        user_wallet_address: Optional[str] = None
    ) -> Optional[dict]:
        """
        Get swap transaction data from OKX DEX

        Args:
            chain: 'bsc' or 'solana'
            from_token_address: Input token address
            to_token_address: Output token address
            amount: Amount in base units
            slippage: Slippage tolerance
            user_wallet_address: User's wallet address (auto-detected if not provided)

        Returns:
            Swap data response or None if failed
        """
        try:
            if chain not in self.CHAINS:
                raise ValueError(f"Unsupported chain: {chain}")

            chain_id = self.CHAINS[chain]['chainId']
            slippage_value = slippage if slippage is not None else self.max_slippage

            # Auto-detect wallet address
            if not user_wallet_address:
                if chain == 'solana' and self.solana_keypair:
                    user_wallet_address = str(self.solana_keypair.pubkey())
                elif chain == 'bsc' and self.bsc_account:
                    user_wallet_address = self.bsc_account.address
                else:
                    raise ValueError(f"No wallet configured for {chain}")

            # Build request
            request_path = '/api/v5/dex/aggregator/swap'
            params = {
                'chainId': chain_id,
                'fromTokenAddress': from_token_address,
                'toTokenAddress': to_token_address,
                'amount': str(amount),
                'slippage': str(slippage_value / 100),
                'userWalletAddress': user_wallet_address
            }

            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_path = f"{request_path}?{query_string}"

            headers = self._get_headers('GET', full_path)
            url = f"{self.BASE_URL}{full_path}"

            logger.info(f"Getting swap data for {chain}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get('code') == '0':
                        swap_data = result.get('data', [{}])[0]
                        logger.info(f"✓ Swap data received")
                        return swap_data
                    else:
                        logger.error(f"Swap data failed (status {resp.status}): {result}")
                        return None

        except Exception as e:
            logger.error(f"Error getting swap data: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def execute_swap_solana(self, swap_data: dict) -> Optional[dict]:
        """
        Execute swap on Solana using swap instructions

        Args:
            swap_data: Swap data from get_swap_data()

        Returns:
            Result dict with success status and transaction signature
        """
        try:
            if not self.solana_keypair:
                raise ValueError("Solana wallet not configured")

            # Extract transaction from swap data
            tx_data = swap_data.get('tx')
            if not tx_data:
                logger.error("No transaction data in swap response")
                return None

            # OKX returns different formats, check for 'data' field
            tx_base64 = tx_data.get('data') or tx_data.get('transaction')

            if not tx_base64:
                logger.error(f"No transaction in swap data: {tx_data}")
                return None

            logger.info("Signing and executing Solana transaction...")

            # Deserialize transaction (try base58 first, then base64)
            try:
                # Try base58 format (OKX returns base58)
                tx_bytes = base58.b58decode(tx_base64)
                tx = VersionedTransaction.from_bytes(tx_bytes)
                logger.info("✓ Decoded transaction from base58 format")
            except Exception as e:
                logger.debug(f"Base58 decode failed: {e}, trying base64...")
                # Fallback to base64
                tx_bytes = base64.b64decode(tx_base64)
                tx = VersionedTransaction.from_bytes(tx_bytes)
                logger.info("✓ Decoded transaction from base64 format")

            # Sign transaction
            message = tx.message
            tx_signed = VersionedTransaction(message, [self.solana_keypair])

            logger.info("✓ Transaction signed")

            # Serialize signed transaction
            signed_tx_bytes = bytes(tx_signed)
            signed_tx_base64 = base64.b64encode(signed_tx_bytes).decode()

            # Submit transaction to Solana RPC
            logger.info("📡 Broadcasting transaction to Solana...")

            rpc_url = "https://api.mainnet-beta.solana.com"
            async with aiohttp.ClientSession() as session:
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        signed_tx_base64,
                        {
                            "encoding": "base64",
                            "skipPreflight": False,
                            "preflightCommitment": "confirmed",
                            "maxRetries": 3
                        }
                    ]
                }

                async with session.post(rpc_url, json=rpc_payload) as resp:
                    result = await resp.json()

                    if 'result' in result:
                        tx_signature = result['result']
                        logger.info(f"✅ Transaction broadcast successful!")
                        logger.info(f"   Signature: {tx_signature}")
                        logger.info(f"   Solscan: https://solscan.io/tx/{tx_signature}")

                        return {
                            'success': True,
                            'signature': tx_signature,
                            'signed_transaction': signed_tx_base64,
                            'solscan_url': f"https://solscan.io/tx/{tx_signature}"
                        }
                    else:
                        error = result.get('error', {})
                        logger.error(f"❌ Transaction broadcast failed: {error}")
                        return {
                            'success': False,
                            'error': error,
                            'signed_transaction': signed_tx_base64
                        }

        except Exception as e:
            logger.error(f"Error executing Solana swap: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def execute_swap_bsc(self, swap_data: dict) -> Optional[dict]:
        """
        Execute swap on BSC (EVM chain)

        Args:
            swap_data: Swap data from get_swap_data()

        Returns:
            Result dict with success status and transaction hash
        """
        try:
            if not self.bsc_account or not self.bsc_web3:
                raise ValueError("BSC wallet not configured")

            # Extract transaction data
            tx_data = swap_data.get('tx')
            if not tx_data:
                logger.error("No transaction data in swap response")
                return None

            logger.info("Preparing BSC transaction...")

            # Build transaction dict
            transaction = {
                'from': self.bsc_account.address,
                'to': Web3.to_checksum_address(tx_data['to']),
                'value': int(tx_data.get('value', 0)),
                'data': tx_data['data'],
                'gas': int(tx_data.get('gas', 300000)),
                'gasPrice': self.bsc_web3.eth.gas_price,
                'nonce': self.bsc_web3.eth.get_transaction_count(self.bsc_account.address),
                'chainId': 56
            }

            logger.info(f"Transaction: {transaction['from']} -> {transaction['to']}")
            logger.info(f"Value: {transaction['value']} wei")
            logger.info(f"Gas: {transaction['gas']}")

            # Sign transaction
            signed_tx = self.bsc_web3.eth.account.sign_transaction(transaction, self.bsc_account.key)

            logger.info("✓ Transaction signed")

            # Send transaction
            tx_hash = self.bsc_web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash_hex = tx_hash.hex()

            logger.info(f"✓ Transaction sent: {tx_hash_hex}")

            # Wait for receipt (optional, can be async)
            logger.info("Waiting for transaction confirmation...")
            receipt = self.bsc_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt['status'] == 1:
                logger.info(f"✓ BSC swap successful!")
                return {
                    'success': True,
                    'tx_hash': tx_hash_hex,
                    'receipt': dict(receipt)
                }
            else:
                logger.error(f"✗ Transaction failed: {receipt}")
                return {
                    'success': False,
                    'tx_hash': tx_hash_hex,
                    'receipt': dict(receipt)
                }

        except Exception as e:
            logger.error(f"Error executing BSC swap: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def swap(
        self,
        chain: ChainType,
        from_token_address: str,
        to_token_address: str,
        amount: str,
        slippage: Optional[float] = None
    ) -> Optional[dict]:
        """
        Complete swap operation: quote + execute

        Args:
            chain: 'bsc' or 'solana'
            from_token_address: Input token address
            to_token_address: Output token address
            amount: Amount in base units
            slippage: Slippage tolerance

        Returns:
            Result dict with success status and transaction info
        """
        try:
            logger.info(f"=== Starting {chain.upper()} swap ===")

            # Get swap data
            swap_data = await self.get_swap_data(
                chain, from_token_address, to_token_address, amount, slippage
            )

            if not swap_data:
                logger.error("Failed to get swap data")
                return None

            # Execute based on chain type
            if chain == 'solana':
                return await self.execute_swap_solana(swap_data)
            elif chain == 'bsc':
                return await self.execute_swap_bsc(swap_data)
            else:
                raise ValueError(f"Unsupported chain: {chain}")

        except Exception as e:
            logger.error(f"Error in swap operation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
