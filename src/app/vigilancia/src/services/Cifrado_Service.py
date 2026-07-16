# vigilancia/services/Cifrado_Service.py
# Cifra/descifra la contraseña de cada terminal (camaras.credencial_cifrada, BYTEA).
# Fernet (AES-128-CBC + HMAC) con llave en VIGILANCIA_SECRET_KEY. La credencial NUNCA
# se guarda ni se devuelve en claro; solo se descifra en memoria para pedir el snapshot.
from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings


class CifradoService:
    def __init__(self) -> None:
        key = (settings.VIGILANCIA_SECRET_KEY or "").strip()
        self._fernet = Fernet(key.encode()) if key else None

    def _exigir_llave(self) -> Fernet:
        if self._fernet is None:
            raise RuntimeError(
                "VIGILANCIA_SECRET_KEY no está configurada: no se puede cifrar/descifrar "
                "la credencial. Genera una con "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        return self._fernet

    def cifrar(self, texto: str) -> bytes:
        return self._exigir_llave().encrypt(texto.encode("utf-8"))

    def descifrar(self, blob: bytes | memoryview | None) -> str | None:
        if blob is None:
            return None
        try:
            return self._exigir_llave().decrypt(bytes(blob)).decode("utf-8")
        except InvalidToken as exc:
            # Llave equivocada o dato corrupto: no revientes el flujo con el secreto.
            raise RuntimeError("No se pudo descifrar la credencial (¿llave incorrecta?).") from exc


cifrado_service = CifradoService()
