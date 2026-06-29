# offline_sync/core/scopes.py
"""
Evaluación de permisos por scopes 'recurso:accion'.

Un scope concedido puede ser:
  - "*"              → todo
  - "recurso:*"      → cualquier acción sobre ese recurso
  - "*:accion"       → esa acción en cualquier recurso (ej. "*:read")
  - "recurso:accion" → exacto (ej. "sync:write")

Algunos scopes IMPLICAN otros (ver SCOPES_IMPLICITOS): conceder el scope clave
concede también los de su lista, sin añadirlos al rol en identity.
"""

# El kiosko (rol con scanner:use) baja el roster y sube sus lotes por /off_sync.
# Con esta implicación NO hace falta otorgarle off_sync:read/off_sync:write por
# separado en identity. Sigue acotado por empresa en cada endpoint.
SCOPES_IMPLICITOS: dict[str, tuple[str, ...]] = {
    "scanner:use": ("off_sync:read", "off_sync:write"),
}


def tiene_scope(scopes_rol: list[str], requerido: str) -> bool:
    """Indica si la lista de scopes de un rol concede el scope requerido."""
    if not scopes_rol:
        return False
    if "*" in scopes_rol or requerido in scopes_rol:
        return True

    recurso, _, accion = requerido.partition(":")
    if f"{recurso}:*" in scopes_rol or f"*:{accion}" in scopes_rol:
        return True

    # Implicaciones: ¿algún scope del rol concede 'requerido' de forma implícita?
    return any(requerido in SCOPES_IMPLICITOS.get(s, ()) for s in scopes_rol)
