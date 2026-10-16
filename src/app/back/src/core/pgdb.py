# app/core/database.py
from fastapi import Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from src.core.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # Reconecta si la conexión se cayó
    pool_size=5,
    max_overflow=10,
    echo=settings.DEBUG,  # Loggea SQL solo en modo DEBUG
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# ── Auditoría: quién hace el cambio ──────────────────────────────────────────
# Los triggers de historial_auditoria leen app.id_usuario / app.usuario / app.ip.
# Al iniciar cada transacción se fijan con set_config(..., true) (solo duran esa
# transacción). Solo en peticiones que escriben; en las lecturas no hace falta.
_METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}


def auditoria_desde_request(request: Request) -> dict | None:
    """Usuario (validado por el gateway) e IP de la petición, para la auditoría."""
    if request.method in _METODOS_LECTURA:
        return None
    quien = getattr(request.state, "principal", None) or getattr(request.state, "usuario", None)
    try:
        id_usuario = getattr(quien, "id_usuario", None)
        usuario = getattr(quien, "nombre_usuario", None)
    except Exception:  # noqa: BLE001 — objeto ORM desligado: se audita sin usuario
        id_usuario = usuario = None
    reenviada = request.headers.get("X-Forwarded-For", "")
    ip = (reenviada.split(",")[0].strip() or request.headers.get("X-Real-Ip")
          or (request.client.host if request.client else None))
    return {"id_usuario": id_usuario, "usuario": usuario, "ip": ip}


@event.listens_for(SessionLocal, "after_begin")
def _marcar_auditoria(session, transaction, connection) -> None:
    datos = session.info.get("auditoria")
    if callable(datos):
        datos = datos()
    if not datos:
        return
    connection.execute(
        text("SELECT set_config('app.id_usuario', :uid, true), "
             "set_config('app.usuario', :usuario, true), set_config('app.ip', :ip, true)"),
        {"uid": str(datos.get("id_usuario") or ""), "usuario": datos.get("usuario") or "",
         "ip": datos.get("ip") or ""},
    )


# Dependencia para inyectar en los endpoints de FastAPI
def get_db(request: Request):
    db = SessionLocal()
    db.info["auditoria"] = lambda: auditoria_desde_request(request)
    try:
        yield db
    finally:
        db.close()
