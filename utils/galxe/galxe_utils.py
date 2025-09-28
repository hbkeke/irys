from typing import Optional
import hashlib
import time
import random
from eth_hash.auto import keccak  # eth-hash

GA_MAX_AGE = 60 * 60 * 24 * 365 * 2

def _rand10() -> int:
    return random.randint(10**9, 10**10 - 1)

def generate_ga_client_id(rand: int | None = None, first_ts: int | None = None) -> str:
    r = int(rand) if rand is not None else _rand10()
    ts = int(first_ts) if first_ts is not None else int(time.time())
    return f"{r}.{ts}"

def generate_ga_cookie_value(
    rand: int | None = None,
    first_ts: int | None = None,
) -> str:
    cid = generate_ga_client_id(rand=rand, first_ts=first_ts)
    return cid

def _keccak256_hex(data: bytes) -> str:
    return keccak(data).hex()

def make_x_unique_link_id(galxe_id: Optional[str], suffix: str = "") -> str:
    base = "null" if galxe_id is None else str(galxe_id)
    raw = (base + (suffix)).encode("utf-8")
    return _keccak256_hex(raw)

# def make_x_unique_link_id(galxe_id: Optional[str], wallet_method: Optional[str] = None) -> str:
#     """
#     Генерирует x-unique-link-id как в JS.
#     - galxe_id: Из localStorage['galxe-id'], если None — пустая строка.
#     - wallet_method: Тип кошелька (из window._gwallet.method), определяет suffix.
#       Примеры: 'Backpack' -> '_solana_bp', 'Trust' -> '_evm_trustwallet', None -> ''.
#     """
#     base = "" if galxe_id is None else str(galxe_id)
#     
#     # Определяем suffix на основе wallet_method (как в JS)
#     suffix_map = {
#         'Backpack': '_solana_bp',
#         'Trust': '_evm_trustwallet',
#         'Jambo': '_jambo_wallet',
#         'PhantomSui': '_sui_phantom',
#         'OkxSui': '_sui_okx',
#         'PhantomEVM': '_evm_phantom',
#         'Okx': '_evm_okx',
#     }
#     # suffix = suffix_map.get(wallet_method, '')  # Если неизвестный или None — ''
#     suffix = ""
#     
#     raw_str = base + suffix
#     return hashlib.md5(raw_str.encode('utf-8')).hexdigest()
