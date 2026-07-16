# vigilancia/core/scopes.py
"""
Evaluación de permisos por scopes 'recurso:accion'.

Un scope concedido puede ser:
  - "*"              → todo
  - "recurso:*"      → cualquier acción sobre ese recurso
  - "*:accion"       → esa acción en cualquier recurso (ej. "*:read")
  - "recurso:accion" → exacto (ej. "vigilancia:write")

vigilancia NO tiene scopes implícitos (a diferencia de offline_sync, donde
scanner:use implicaba off_sync:read/write). El API de cámaras se protege con
'vigilancia:read' / 'vigilancia:write' directos. El motor de captura NO pasa por
el gateway: escribe en BD como svc_vigilancia y llama a recognition con token
interno, así que no consume scopes.
"""

SCOPES_IMPLICITOS: dict[str, tuple[str, ...]] = {}


def tiene_scope(scopes_rol: list[str], requerido: str) -> bool:
    """Indica si la lista de scopes de un rol concede el scope requerido."""
    if not scopes_rol:
        return False
    if "*" in scopes_rol or requerido in scopes_rol:
        return True

    recurso, _, accion = requerido.partition(":")
    if f"{recurso}:*" in scopes_rol or f"*:{accion}" in scopes_rol:
        return True

    return any(requerido in SCOPES_IMPLICITOS.get(s, ()) for s in scopes_rol)
