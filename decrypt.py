import requests
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


def decrypt_whatsapp_media(
    media_url: str,
    media_key_bytes: bytes,
    app_info: bytes = b"WhatsApp Audio Keys",
    output_filename: str = None
) -> bytes:
    """
    Decrypts encrypted WhatsApp media (audio, images, documents) fetched from CDN.

    :param media_url: Direct download URL of the encrypted (.enc) file.
    :param media_key_bytes: 32-byte media key from the WhatsApp message payload.
    :param app_info: HKDF application info string (default: b"WhatsApp Audio Keys").
    :param output_filename: Optional file path to save the decrypted audio to disk.
    :return: Raw decrypted bytes of the original file.
    """
    # 1. Expand the media key using HKDF-SHA256
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=112,
        salt=None,
        info=app_info,
        backend=default_backend()
    )
    key_stream = hkdf.derive(media_key_bytes)

    iv = key_stream[:16]
    cipher_key = key_stream[16:48]

    # 2. Download the encrypted binary payload from WhatsApp CDN
    response = requests.get(media_url)
    response.raise_for_status()
    enc_data = response.content

    # 3. Strip trailing 10-byte MAC authentication tag
    encrypted_payload = enc_data[:-10]

    # 4. Decrypt via AES-256-CBC
    cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(encrypted_payload) + decryptor.finalize()

    # 5. Remove PKCS7 padding
    padding_len = decrypted_data[-1]
    audio_bytes = decrypted_data[:-padding_len]

    # Optional: Write directly to disk
    if output_filename:
        with open(output_filename, "wb") as f:
            f.write(audio_bytes)

    return audio_bytes