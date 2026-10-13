import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


BOT_NAME = os.getenv("TRADER_BOT_NAME", "Launchpad")
TELEGRAM_TOKEN = os.getenv("TRADER_TELEGRAM_TOKEN") or os.getenv("TELEGRAM_TOKEN")

# Fernet key used to encrypt wallet secret keys at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
WALLET_ENCRYPTION_KEY = os.getenv("WALLET_ENCRYPTION_KEY")

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DB_PATH = os.getenv("TRADER_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "trader.db"))

PUMPPORTAL_TRADE_URL = os.getenv("PUMPPORTAL_TRADE_URL", "https://pumpportal.fun/api/trade-local")
PUMP_IPFS_URL = os.getenv("PUMP_IPFS_URL", "https://pump.fun/api/ipfs")
PUMP_COINS_URL = os.getenv("PUMP_COINS_URL", "https://frontend-api-v3.pump.fun/coins")
JUPITER_PRICE_URL = os.getenv("JUPITER_PRICE_URL", "https://lite-api.jup.ag/price/v3")
EXPLORER_TX_URL = os.getenv("EXPLORER_TX_URL", "https://solscan.io/tx/{}")
EXPLORER_TOKEN_URL = os.getenv("EXPLORER_TOKEN_URL", "https://pump.fun/coin/{}")

# Defaults for new users; each user can change them under Settings.
DEFAULT_SLIPPAGE = _float("DEFAULT_SLIPPAGE", 15)
DEFAULT_PRIORITY_FEE = _float("DEFAULT_PRIORITY_FEE", 0.0005)

MAX_WALLETS_PER_USER = int(os.getenv("MAX_WALLETS_PER_USER", "10"))

# When set, only users listed in verified_users.json (written by bot.py) can use the bot.
REQUIRE_VERIFIED = os.getenv("TRADER_REQUIRE_VERIFIED", "0") == "1"
VERIFIED_USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "verified_users.json")
