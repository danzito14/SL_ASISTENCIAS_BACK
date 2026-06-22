# identity/core/scopes.py
"""
Evaluación de permisos por scopes 'recurso:accion'.
  - "*"              → todo
  - "recurso:*"      → cualquier acción sobre ese recurso
  - "*:accion"       → esa acción en cualquier recurso
  - "recurso:accion" → exacto
Algunos scopes implican otros (SCOPES_IMPLICITOS).
"""

SCOPES_IMPLICITOS: dict[str, tuple[str, ...]] = {
    "scanner:use": ("puertas:read", "dispositivos:read"),
}


def tiene_scope(scopes_rol: list[str], requerido: str) -> bool:
    if not scopes_rol:
        return False
    if "*" in scopes_rol or requerido in scopes_rol:
        return True

    recurso, _, accion = requerido.partition(":")
    if f"{recurso}:*" in scopes_rol or f"*:{accion}" in scopes_rol:
        return True

    return any(requerido in SCOPES_IMPLICITOS.get(s, ()) for s in scopes_rol)
