# employee_monitoring/sync/hashing.py
"""
Hashes ESTABLES para la detección de cambios (full-scan idempotente).

- hash_datos: sobre los campos del trabajador que, si cambian en la nómina, deben
  reescribir la fila local. Serialización determinista (claves ordenadas) → SHA-256.
- hash_foto: SHA-256 del binario de la foto. El mtime/size remoto (SFTP) se usa
  como pre-filtro barato antes de descargar; este hash confirma el cambio real.
"""
import hashlib
import json

# Campos que entran al hash de datos. Si cambia alguno en la nómina → 'modificado'.
# (NO incluir timestamps ni id_trabajador local: solo el contenido de negocio.)
CAMPOS_HASH_DATOS = (
    "nombre", "apellido", "id_area", "id_empresa",
    "permiso_escaneo", "nivel_acceso_interno", "estado",
)


def hash_datos(valores: dict) -> str:
    """SHA-256 estable de los CAMPOS_HASH_DATOS de un trabajador mapeado."""
    proyeccion = {campo: valores.get(campo) for campo in CAMPOS_HASH_DATOS}
    serializado = json.dumps(proyeccion, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def hash_foto(foto_bytes: bytes) -> str:
    """SHA-256 del binario de la foto."""
    return hashlib.sha256(foto_bytes).hexdigest()
