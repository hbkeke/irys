
# mimic_encrypted_data.py
# pip install cryptography

import json, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
import os

# Входные данные (те же, что вы предоставили)
payload_fields = {
    "captchaOutput": "fmb4mAPhV3eAw2Kdv5uGtDxCpTrHqxl1mCOVxiOKksI0kBflEhTHQ0VNrqA8hZ4utGFhpIE4OJEEYq9zGe64FQcjeQed/3HahMXtRbLBBaC2XQXIKo+5xA/cWbenw4jNq8+TbDEpyVp5QAiC8ztAHSN3K8AfFjQD6+YjniKrs4g1n4ZP9+STDziyENBK8AXW+bpk5nWVm21SsJHEgwlsVMfErrGBbwIzsORZCmgI42D7L1nMX0nbMJu9YvpI7XkeIung1pFgYzBKnbBp5Dd+NGl5w7aaYCb169vFpPyDZWrmnnpaR4iV/Da1+x4=",
    "genTime": "1758976948",
    "lotNumber": "8766c33f08f2a973cd145567fcfb33bc65faa00f73ecf11cb0e7eae3a96a5298",
    "passToken": "e85b455c5fbd3c5b02b770483cd6e6440388170e5dfa16524a94c739857db882"
}

def make_encrypted_data(payload_fields, rsa_pub_pem=None):
    # 1) Сериализация — часто используют compact JSON без пробелов
    payload_json = json.dumps(payload_fields, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # 2) AES-GCM шифрование (симметричный ключ)
    aes_key = AESGCM.generate_key(bit_length=256)  # 32 bytes
    aesgcm = AESGCM(aes_key)
    iv = os.urandom(12)  # 96-bit nonce — обычно для GCM
    ciphertext = aesgcm.encrypt(iv, payload_json, associated_data=None)  # GCM комбинирует тэг в конец

    # 3) RSA-шифрование AES-ключа (если есть публичный ключ). Если нет — просто вернём AES шифр в одном бандле.
    if rsa_pub_pem is None:
        # Без RSA — просто упакуем ключ в base64 (демонстрация)
        key_blob = base64.b64encode(aes_key).decode()
        rsa_encrypted_key_b64 = None
    else:
        pub = serialization.load_pem_public_key(rsa_pub_pem.encode(), backend=default_backend())
        rsa_encrypted_key = pub.encrypt(
            aes_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        )
        rsa_encrypted_key_b64 = base64.b64encode(rsa_encrypted_key).decode()

    # 4) Упаковка. Формат может быть произвольный — используем JSON с полями: iv, ct, key (rsa)
    packet = {
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode()
    }
    if rsa_encrypted_key_b64:
        packet["encrypted_key"] = rsa_encrypted_key_b64
    else:
        packet["raw_key_b64"] = base64.b64encode(aes_key).decode()

    # 5) Итог: base64 от сериализованного packet (можно менять — у wasm мог быть другой порядок)
    packet_json = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    result_b64 = base64.b64encode(packet_json).decode()
    return result_b64, packet, payload_json

if __name__ == "__main__":
    # Пример: без публичного ключа
    result_b64, packet, payload_json = make_encrypted_data(payload_fields, rsa_pub_pem=None)
    print("Simulated encryptedData (base64 of JSON packet):\n", result_b64)
    print("\nPacket structure:\n", json.dumps(packet, indent=2))
    print("\nOriginal payload JSON:\n", payload_json.decode())
