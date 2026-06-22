# identity/core/security.py
"""
Hashing de contraseñas (PBKDF2-HMAC-SHA256) + emisión/validación de JWT.

identity es el ÚNICO servicio que EMITE tokens. El JWT es self-contained
(empresa + scopes en los claims) para que el resto de servicios autorice sin
llamar a identity.
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
    sal = secrets.token_bytes(_SAL_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, _ITERACIONES)
    return f"{_ALGORITMO}${_ITERACIONES}${sal.hex()}${dk.hex()}"


def verify_password(contrasena: str, hash_guardado: str) -> bool:
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
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(
    id_usuario: int,
    nombre_rol: str | None = None,
    empresa: int | None = None,
    scopes: list[str] | None = None,
    id_rol: int | None = None,
    nombre_usuario: str | None = None,
) -> str:
    """
    Genera un JWT de acceso SELF-CONTAINED. Claims (además de sub/iat/exp):
    empresa, scopes, rol, id_rol, nombre_usuario. Con esto cualquier servicio
    autoriza leyendo el token, sin consultar a identity.
    """
    ahora = datetime.now(timezone.utc)
    payload: dict = {"sub": str(id_usuario), "iat": ahora}
    if empresa is not None:
        payload["empresa"] = empresa
    if scopes is not None:
        payload["scopes"] = scopes
    if nombre_rol is not None:
        payload["rol"] = nombre_rol
    if id_rol is not None:
        payload["id_rol"] = id_rol
    if nombre_usuario is not None:
        payload["nombre_usuario"] = nombre_usuario

    sin_expiracion = nombre_rol is not None and nombre_rol in settings.roles_token_sin_expiracion
    if not sin_expiracion and settings.JWT_EXPIRE_MINUTES and settings.JWT_EXPIRE_MINUTES > 0:
        payload["exp"] = ahora + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
