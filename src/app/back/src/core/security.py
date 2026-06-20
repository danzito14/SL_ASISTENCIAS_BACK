# app/core/security.py
"""
Hashing de contraseñas con la librería estándar (sin dependencias externas).

Usa PBKDF2-HMAC-SHA256 con sal aleatoria. El hash se guarda en un solo campo
con formato:  pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from src.core.config import settings

_ALGORITMO = "pbkdf2_sha256"
_ITERACIONES = 240_000
_SAL_BYTES = 16


def hash_password(contrasena: str) -> str:
    """Devuelve el hash codificado de una contraseña en texto plano."""
    sal = secrets.token_bytes(_SAL_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, _ITERACIONES)
    return f"{_ALGORITMO}${_ITERACIONES}${sal.hex()}${dk.hex()}"


def verify_password(contrasena: str, hash_guardado: str) -> bool:
    """Verifica una contraseña en texto plano contra el hash almacenado."""
    try:
        algoritmo, iteraciones, sal_hex, hash_hex = hash_guardado.split("$")
        if algoritmo != _ALGORITMO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            contrasena.encode("utf-8"),
            bytes.fromhex(sal_hex),
            int(iteraciones),
        )
        # Comparación en tiempo constante para no filtrar info por timing.
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(id_usuario: int, nombre_rol: str | None = None) -> str:
    """
    Genera un JWT de acceso cuyo 'sub' es el id del usuario.

    La expiración depende del rol:
      - Si el rol está en settings.roles_token_sin_expiracion (p. ej. 'scanner'),
        el token se emite SIN claim 'exp' (no expira), aunque JWT_EXPIRE_MINUTES > 0.
      - En otro caso se usa JWT_EXPIRE_MINUTES (0 o negativo = no expira).
    """
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(id_usuario),
        "iat": ahora,
    }
    sin_expiracion = nombre_rol is not None and nombre_rol in settings.roles_token_sin_expiracion
    if not sin_expiracion and settings.JWT_EXPIRE_MINUTES and settings.JWT_EXPIRE_MINUTES > 0:
        payload["exp"] = ahora + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decodifica y valida un JWT (firma + expiración). Lanza jwt.ExpiredSignatureError
    o jwt.InvalidTokenError si no es válido.
    """
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
