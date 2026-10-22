"""Hybrid RSA-OAEP/AES encryption with HMAC; private key never leaves destination."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def openssl(*args, data):
    return subprocess.run(["openssl", *args], input=data, capture_output=True, check=True).stdout


def encrypt(payload, public_key):
    secret = os.urandom(64)
    iv = os.urandom(16)
    cipher = openssl("enc", "-aes-256-cbc", "-K", secret[:32].hex(), "-iv", iv.hex(), data=payload)
    wrapped = openssl("pkeyutl", "-encrypt", "-pubin", "-inkey", str(public_key),
                      "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256", data=secret)
    return {"version": 1, "key": base64.b64encode(wrapped).decode(),
            "iv": iv.hex(), "cipher": base64.b64encode(cipher).decode(),
            "mac": hmac.new(secret[32:], iv + cipher, hashlib.sha256).hexdigest()}


def decrypt(envelope, private_key):
    if envelope["version"] != 1:
        raise ValueError("Unknown envelope version")
    secret = openssl("pkeyutl", "-decrypt", "-inkey", str(private_key), "-pkeyopt",
                     "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                     data=base64.b64decode(envelope["key"], validate=True))
    iv = bytes.fromhex(envelope["iv"])
    cipher = base64.b64decode(envelope["cipher"], validate=True)
    if not hmac.compare_digest(envelope["mac"], hmac.new(secret[32:], iv + cipher, hashlib.sha256).hexdigest()):
        raise ValueError("Envelope authentication failed")
    return openssl("enc", "-d", "-aes-256-cbc", "-K", secret[:32].hex(), "-iv", iv.hex(), data=cipher)


def env_text(payload):
    names = ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    lines = []
    for name in names:
        value = payload[name]
        if not value or any(char in value for char in "\r\n\0"):
            raise ValueError("Missing or unsafe credential")
        lines.append(name + '="' + value.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    mode, key, target = sys.argv[1:]
    os.umask(0o077)
    if mode == "encrypt":
        payload = {name: os.environ[name] for name in ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
        env_text(payload)
        Path(target).write_text(json.dumps(encrypt(json.dumps(payload).encode(), key)))
        print("Encrypted stock credentials; no plaintext artifact created.")
    elif mode == "decrypt":
        payload = json.loads(decrypt(json.loads(Path(target).read_text()), key))
        destination = Path("/etc/stock-signals/telegram.env")
        if destination.exists():
            raise SystemExit("Refusing to overwrite existing credentials")
        with destination.open("x", encoding="utf-8") as output:
            output.write(env_text(payload))
            output.flush()
            os.fsync(output.fileno())
        print("Stock credentials installed privately; values not displayed.")
    else:
        raise SystemExit("Unknown envelope operation")
