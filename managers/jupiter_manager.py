"""
Jupiter DEX swap manager for Solana
"""
import json
import base64
import logging
from typing import Optional
import base58
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)


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
