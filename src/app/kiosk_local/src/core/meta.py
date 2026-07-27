# kiosk_local/core/meta.py
# Acceso a kiosk_meta (tabla local-only, clave/valor). Guarda el estado de la estación:
#   · cloud_token → token del usuario logueado en el front (reenviado al sincronizar).
#     Rol escaneador = token SIN expiración, así el loop de subida lo reusa entre sesiones
#     y sobrevive reinicios. OJO seguridad: vive en la BD local (localhost, disco que
#     conviene cifrar). El reemplazo total del roster NO borra kiosk_meta.
#   · empresa    → empresa del último sync (la que sigue al usuario logueado). El fichaje
#     la usa para acotar el match y sellar los escaneos con la empresa correcta.
from sqlalchemy import text
from sqlalchemy.orm import Session

_ENSURE = text("""
    CREATE TABLE IF NOT EXISTS kiosk_meta (
        clave TEXT PRIMARY KEY, valor TEXT, actualizado TIMESTAMPTZ DEFAULT NOW()
    )
""")
_GET = text("SELECT valor FROM kiosk_meta WHERE clave = :clave")
_SET = text("""
    INSERT INTO kiosk_meta (clave, valor) VALUES (:clave, :valor)
    ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = NOW()
""")


def leer(db: Session, clave: str) -> str | None:
    db.execute(_ENSURE)
    row = db.execute(_GET, {"clave": clave}).first()
    return row[0] if row else None


def escribir(db: Session, clave: str, valor: str | None) -> None:
    db.execute(_ENSURE)
    db.execute(_SET, {"clave": clave, "valor": valor})


def empresa_actual(db: Session) -> int | None:
    """Empresa del último sync (la del usuario logueado). None si aún no se sincroniza."""
    v = leer(db, "empresa")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def puerta_actual(db: Session) -> int | None:
    """Puerta elegida desde el front (POST /kiosk/puerta), guardada en kiosk_meta. None si
    no se ha elegido → el fichaje cae a KIOSK_PUERTA (env) o a la 1ª puerta activa."""
    v = leer(db, "puerta")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
