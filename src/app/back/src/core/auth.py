# app/core/auth.py
"""
Protección de rutas por scopes de rol (se aplica como dependencia global).

Política:
  - Rutas públicas (login, health, docs) no requieren token.
  - El resto exige 'Authorization: Bearer <jwt>'. Se carga el usuario y su rol
    EN CADA REQUEST (siempre fresco), y se valida que su rol tenga el scope que
    el endpoint necesita.
  - El scope requerido se deriva de la ruta y el método:
        recurso = primer segmento de la ruta (ej. 'trabajadores')
        acción  = read (GET) | write (POST/PUT/PATCH) | delete (DELETE)
    El scanner se trata aparte: requiere 'scanner:use'.
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

# Esquema OAuth2 (solo para que /docs muestre el botón "Authorize" con usuario/
# contraseña). auto_error=False → no bloquea por sí mismo; la validación real la
# hace guard_scopes. El tokenUrl apunta al endpoint OAuth2 de /usuarios.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="usuarios/token", auto_error=False)

# Rutas que no requieren autenticación.
RUTAS_PUBLICAS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/usuarios/login",
    "/usuarios/token",
}

# Rutas que solo exigen un token válido (cualquier usuario autenticado), SIN
# requerir un scope concreto. Pensado para que el usuario consulte sus propios
# datos: p. ej. /usuarios/me, para conocer su rol y permisos tras el login.
RUTAS_SOLO_AUTENTICADO = {
    "/usuarios/me",
}

ACCION_POR_METODO = {
    "GET": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "delete",
}


def _es_publica(path: str) -> bool:
    return path in RUTAS_PUBLICAS or path.startswith("/docs")


def _scope_requerido(method: str, path: str) -> str:
    recurso = path.strip("/").split("/")[0] if path.strip("/") else ""
    if recurso == "scanner":
        return "scanner:use"
    accion = ACCION_POR_METODO.get(method, "write")
    return f"{recurso}:{accion}"


def scopes_de_usuario(usuario: Usuario) -> list[str]:
    """Lista de scopes del rol del usuario (de permisos JSONB {"scopes": [...]})."""
    permisos = usuario.rol.permisos if (usuario.rol and usuario.rol.permisos) else {}
    return permisos.get("scopes", []) if isinstance(permisos, dict) else []


def token_para_usuario(usuario: Usuario) -> str:
    """
    Crea el JWT self-contained del usuario: además del 'sub', incrusta empresa,
    scopes, rol e id_rol para que cualquier servicio autorice sin llamar a identity
    (ver PLAN_MICROSERVICIOS §5). Centraliza la construcción del token del login.
    """
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no válido o inactivo.",
        )
    return usuario


def guard_scopes(request: Request, db: Session = Depends(get_db)) -> None:
    """Dependencia global: valida token + scope del rol para cada request protegido."""
    path = request.url.path
    if request.method == "OPTIONS" or _es_publica(path):
        return

    usuario = _usuario_desde_token(request, db)

    # Rutas que solo exigen estar autenticado (sin scope concreto): el usuario
    # consulta sus propios datos. El resto sí valida el scope del rol.
    if path not in RUTAS_SOLO_AUTENTICADO:
        # El scope se valida contra el usuario FRESCO de BD (no contra el token):
        # así una baja o un cambio de permisos surte efecto de inmediato. Los claims
        # del token (empresa/scopes) son para los servicios que NO tienen la BD.
        scopes = scopes_de_usuario(usuario)
        requerido = _scope_requerido(request.method, path)
        if not tiene_scope(scopes, requerido):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol no tiene el permiso requerido: '{requerido}'.",
            )

    # Disponible para los endpoints que quieran saber quién hace la petición.
    request.state.usuario = usuario


def usuario_actual(request: Request) -> Usuario:
    """Dependencia para endpoints que necesitan el usuario autenticado."""
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado.",
        )
    return usuario


def es_admin(usuario: Usuario) -> bool:
    """True si el usuario es super-admin (empresa comodín = EMPRESA_ADMIN)."""
    return usuario.empresa == settings.EMPRESA_ADMIN


def exigir_empresa(usuario: Usuario, id_empresa_objetivo: int | None) -> None:
    """
    Encapsulación por empresa: lanza 403 si un usuario normal intenta acceder a
    datos de OTRA empresa. El super-admin (empresa 99) pasa siempre.

    Si id_empresa_objetivo es None (no se pudo determinar la empresa del recurso,
    p. ej. porque no existe), no bloquea aquí: deja que la validación de existencia
    del servicio responda el 404 correspondiente.
    """
    if es_admin(usuario):
        return
    if id_empresa_objetivo is not None and id_empresa_objetivo != usuario.empresa:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a datos de otra empresa.",
        )


def resolver_empresa_scope(
    request: Request,
    id_empresa: int | None = Query(
        None,
        description=(
            "Empresa a consultar. Solo el super-admin (empresa "
            f"{settings.EMPRESA_ADMIN}) puede elegir cualquiera o ver todas "
            "(sin valor). Los demás usuarios quedan fijados a su propia empresa."
        ),
    ),
) -> int | None:
    """
    Resuelve la empresa EFECTIVA para acotar los listados, según el usuario:

      - Super-admin (empresa == EMPRESA_ADMIN): respeta el id_empresa pedido
        (None = todas las empresas).
      - Usuario normal: SIEMPRE su propia empresa, ignorando lo que mande el front
        (no puede consultar datos de otra empresa).

    Se apoya en request.state.usuario, que deja guard_scopes en cada request.
    """
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado.",
        )
    if usuario.empresa == settings.EMPRESA_ADMIN:
        return id_empresa
    return usuario.empresa
