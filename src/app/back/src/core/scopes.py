# app/core/scopes.py
"""
Evaluación de permisos por scopes 'recurso:accion'.

Un scope concedido puede ser:
  - "*"            → todo
  - "recurso:*"    → cualquier acción sobre ese recurso
  - "*:accion"     → esa acción en cualquier recurso (ej. "*:read")
  - "recurso:accion" → exacto (ej. "trabajadores:write")

Además, algunos scopes IMPLICAN otros (ver SCOPES_IMPLICITOS): conceder el
scope clave concede también los de su lista, sin tener que añadirlos al rol.
"""

# Scopes que conceden otros de forma implícita.
# El kiosko 'scanner' (scanner:use) necesita leer puertas y dispositivos para
# poder seleccionarlos y operar; con esto NO hace falta darle puertas:read ni
# dispositivos:read por separado. Sigue acotado por empresa en esos endpoints.
SCOPES_IMPLICITOS: dict[str, tuple[str, ...]] = {
    "scanner:use": ("puertas:read", "dispositivos:read"),
}


def tiene_scope(scopes_rol: list[str], requerido: str) -> bool:
    """
    Indica si la lista de scopes de un rol concede el scope requerido.

    Args:
        scopes_rol: scopes que tiene el rol (ej. ["*:read", "escaneos:write"])
        requerido:  scope que exige el endpoint (ej. "trabajadores:write")
    """
    if not scopes_rol:
        return False
    if "*" in scopes_rol or requerido in scopes_rol:
        return True

    recurso, _, accion = requerido.partition(":")
    if f"{recurso}:*" in scopes_rol or f"*:{accion}" in scopes_rol:
        return True

    # Implicaciones: ¿algún scope del rol concede 'requerido' de forma implícita?
    return any(requerido in SCOPES_IMPLICITOS.get(s, ()) for s in scopes_rol)
