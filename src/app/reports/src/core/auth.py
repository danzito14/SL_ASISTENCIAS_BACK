# app/core/auth.py
"""
Autorización por scopes (dependencia global), confiando en el API Gateway.

La AUTENTICACIÓN (validar la firma/expiración del JWT) está CENTRALIZADA en el
gateway (Traefik → ForwardAuth → identity `/validate`). Cuando un request llega
aquí, el gateway YA validó el token y dejó la identidad en headers `X-*`
(X-User-Id, X-Empresa, X-Scopes, X-Rol, X-Id-Rol, X-Nombre-Usuario). Este servicio
ya NO decodifica el JWT ni necesita el JWT_SECRET: solo lee esos headers y aplica
la AUTORIZACIÓN por scope (que sí es propia de cada endpoint).

Fail-closed: si en una ruta protegida no llega la identidad del gateway, se rechaza
(401). Los servicios no publican puertos al host, así que solo Traefik los alcanza;
para endurecer aún más, ver el token de gateway compartido (pendiente, en el plan).
"""
from dataclasses import dataclass, field

from fastapi import HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer

from src.core.config import settings
from src.core.scopes import tiene_scope

# Solo para que /docs muestre el botón "Authorize". El tokenUrl apunta a identity.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="usuarios/token", auto_error=False)

# Rutas públicas (sin token). El login/token vive en identity, no aquí.
RUTAS_PUBLICAS = {
    "/", "/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",
}
# Rutas que solo exigen estar autenticado (sin scope concreto). Vacío por ahora.
RUTAS_SOLO_AUTENTICADO: set[str] = set()

ACCION_POR_METODO = {
    "GET": "read", "POST": "write", "PUT": "write", "PATCH": "write", "DELETE": "delete",
}


@dataclass
class Principal:
    """Identidad del request, inyectada por el gateway en headers X-* (sin BD)."""
    id_usuario: int | None
    empresa: int | None
    scopes: list[str] = field(default_factory=list)
    rol: str | None = None
    id_rol: int | None = None
    nombre_usuario: str | None = None


def _es_publica(path: str) -> bool:
    return path in RUTAS_PUBLICAS or path.startswith("/docs")


def _scope_requerido(method: str, path: str) -> str:
    recurso = path.strip("/").split("/")[0] if path.strip("/") else ""
    if recurso == "scanner":
        return "scanner:use"
    # El dashboard (panel de inicio) tiene su PROPIO permiso otorgable: así puedes
    # dar SOLO el panel a un rol (scope "dashboard:read") sin concederle la descarga
    # de reportes. Lo cubren "*" y "*:read"; tener solo "reportes:read" NO lo concede.
    if path.rstrip("/") == "/reportes/dashboard":
        return "dashboard:read"
    accion = ACCION_POR_METODO.get(method, "write")
    return f"{recurso}:{accion}"


def _principal_desde_headers(request: Request) -> Principal:
    """Construye el Principal a partir de los headers X-* que inyecta el gateway."""
    empresa = request.headers.get("X-Empresa")
    # Fail-closed: en ruta protegida, sin identidad del gateway → no autenticado.
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Petición sin identidad del gateway (token ausente o inválido).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    uid = request.headers.get("X-User-Id")
    id_rol = request.headers.get("X-Id-Rol")
    scopes_raw = request.headers.get("X-Scopes", "")
    return Principal(
        id_usuario=int(uid) if uid else None,
        empresa=int(empresa),
        scopes=scopes_raw.split() if scopes_raw else [],
        rol=request.headers.get("X-Rol") or None,
        id_rol=int(id_rol) if id_rol else None,
        nombre_usuario=request.headers.get("X-Nombre-Usuario") or None,
    )


def _verificar_gateway(request: Request) -> None:
    """
    Si hay un token de gateway configurado, exige que el request lo traiga: prueba
    que pasó por Traefik (donde corrió el ForwardAuth y se fijaron los headers X-*)
    y NO es un acceso directo al contenedor saltándose el gateway. Traefik lo inyecta
    con customRequestHeaders, sobreescribiendo cualquier valor entrante, así que un
    cliente no puede falsificarlo. Vacío = no se exige (no rompe si aún no se cablea).
    """
    esperado = settings.GATEWAY_INTERNAL_TOKEN
    if esperado and request.headers.get("X-Gateway-Token") != esperado:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La petición no proviene del gateway.",
        )


def guard_scopes(request: Request) -> None:
    """Dependencia global: lee la identidad del gateway y valida el scope (sin BD)."""
    path = request.url.path
    if request.method == "OPTIONS" or _es_publica(path):
        return

    _verificar_gateway(request)
    principal = _principal_desde_headers(request)

    if path not in RUTAS_SOLO_AUTENTICADO:
        requerido = _scope_requerido(request.method, path)
        if not tiene_scope(principal.scopes, requerido):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol no tiene el permiso requerido: '{requerido}'.",
            )

    request.state.principal = principal


def usuario_actual(request: Request) -> Principal:
    """Dependencia para endpoints que necesitan la identidad del request."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado.")
    return principal


def es_admin(principal: Principal) -> bool:
    """True si es super-admin (empresa comodín = EMPRESA_ADMIN)."""
    return principal.empresa == settings.EMPRESA_ADMIN


def exigir_empresa(principal: Principal, id_empresa_objetivo: int | None) -> None:
    """
    Encapsulación por empresa: 403 si un usuario normal toca datos de OTRA empresa.
    El super-admin (empresa 99) pasa siempre. Si id_empresa_objetivo es None, no
    bloquea aquí (deja que la validación de existencia del servicio responda 404).
    """
    if es_admin(principal):
        return
    if id_empresa_objetivo is not None and id_empresa_objetivo != principal.empresa:
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
            f"{settings.EMPRESA_ADMIN}) puede elegir cualquiera o ver todas (sin "
            "valor). Los demás quedan fijados a su propia empresa."
        ),
    ),
) -> int | None:
    """Empresa EFECTIVA para acotar listados, según el principal del gateway."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado.")
    if principal.empresa == settings.EMPRESA_ADMIN:
        return id_empresa
    return principal.empresa
