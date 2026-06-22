# identity/core/auth.py
"""
Auth de identity. Como identity ES dueño de la tabla 'usuarios', su guard carga
el usuario FRESCO de la BD en cada request (una baja o cambio de permisos surte
efecto al instante para SUS endpoints). El resto de servicios, en cambio, autoriza
de forma stateless leyendo los claims del JWT que identity emite.
"""
import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.pgdb import get_db
from src.core.security import create_access_token, decode_access_token
from src.core.scopes import tiene_scope
from src.models.Rol_Usuario_Model import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="usuarios/token", auto_error=False)

RUTAS_PUBLICAS = {
    "/", "/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",
    "/usuarios/login", "/usuarios/token",
    # /validate lo llama el ForwardAuth del gateway: hace su propia validación del
    # token (no pasa por este guard, que haría un scope inexistente 'validate:*').
    "/validate",
}
RUTAS_SOLO_AUTENTICADO = {"/usuarios/me"}

ACCION_POR_METODO = {"GET": "read", "POST": "write", "PUT": "write", "PATCH": "write", "DELETE": "delete"}


def _es_publica(path: str) -> bool:
    return path in RUTAS_PUBLICAS or path.startswith("/docs")


def _scope_requerido(method: str, path: str) -> str:
    recurso = path.strip("/").split("/")[0] if path.strip("/") else ""
    accion = ACCION_POR_METODO.get(method, "write")
    return f"{recurso}:{accion}"


def scopes_de_usuario(usuario: Usuario) -> list[str]:
    permisos = usuario.rol.permisos if (usuario.rol and usuario.rol.permisos) else {}
    return permisos.get("scopes", []) if isinstance(permisos, dict) else []


def token_para_usuario(usuario: Usuario) -> str:
    """JWT self-contained: sub + empresa + scopes + rol + id_rol + nombre_usuario."""
    return create_access_token(
        id_usuario=usuario.id_usuario,
        nombre_rol=usuario.rol.nombre_rol if usuario.rol else None,
        empresa=usuario.empresa,
        scopes=scopes_de_usuario(usuario),
        id_rol=usuario.id_rol,
        nombre_usuario=usuario.nombre_usuario,
    )


def _usuario_desde_token(request: Request, db: Session) -> Usuario:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autenticación (Authorization: Bearer ...).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")

    sub = payload.get("sub")
    usuario = (
        db.query(Usuario).filter(Usuario.id_usuario == int(sub)).first()
        if sub is not None else None
    )
    if usuario is None or usuario.estado != "activo":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no válido o inactivo.")
    return usuario


def guard_scopes(request: Request, db: Session = Depends(get_db)) -> None:
    path = request.url.path
    if request.method == "OPTIONS" or _es_publica(path):
        return

    usuario = _usuario_desde_token(request, db)

    if path not in RUTAS_SOLO_AUTENTICADO:
        scopes = scopes_de_usuario(usuario)
        requerido = _scope_requerido(request.method, path)
        if not tiene_scope(scopes, requerido):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol no tiene el permiso requerido: '{requerido}'.",
            )

    request.state.usuario = usuario


def usuario_actual(request: Request) -> Usuario:
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado.")
    return usuario


def es_admin(usuario: Usuario) -> bool:
    return usuario.empresa == settings.EMPRESA_ADMIN


def exigir_empresa(usuario: Usuario, id_empresa_objetivo: int | None) -> None:
    if es_admin(usuario):
        return
    if id_empresa_objetivo is not None and id_empresa_objetivo != usuario.empresa:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a datos de otra empresa.",
        )
