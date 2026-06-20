# app/schemas/rol.py
from pydantic import BaseModel, Field
from datetime import datetime


class RolPermisos(BaseModel):
    """
    Permisos de un rol como lista de scopes 'recurso:accion'.
    Comodines admitidos: '*' (todo), 'recurso:*' (todo sobre el recurso),
    '*:accion' (esa acción en cualquier recurso).
    Ej: ["*"], ["*:read"], ["escaneos:write", "scanner:use"].
    """
    scopes: list[str] = Field(default_factory=list)


class RolBase(BaseModel):
    nombre_rol:  str
    descripcion: str | None = None
    permisos:    RolPermisos = Field(default_factory=RolPermisos)
    estado:      str = "activo"


class RolCreate(RolBase):
    pass


class RolUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_rol:  str | None = None
    descripcion: str | None = None
    permisos:    RolPermisos | None = None
    estado:      str | None = None


class RolResponse(RolBase):
    id_rol:        int
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


class UsuarioBase(BaseModel):
    nombre_usuario: str
    id_rol: int
    estado: str = "activo"
    empresa: int = 1  # Empresa del usuario; 99 (EMPRESA_ADMIN) = acceso a todas.


class UsuarioCreate(UsuarioBase):
    contrasena: str  # Se recibe en texto plano, se hashea en el servicio


class UsuarioUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_usuario: str | None = None
    id_rol:         int | None = None
    estado:         str | None = None
    empresa:        int | None = None
    contrasena:     str | None = None  # Si se envía, se re-hashea


class UsuarioLogin(BaseModel):
    nombre_usuario: str
    contrasena:     str


class UsuarioResponse(UsuarioBase):
    id_usuario: int
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}


class UsuarioConRol(UsuarioResponse):
    """Usuario autenticado junto con su rol y permisos (scopes). Lo usa /usuarios/me
    para que el front conozca qué puede hacer sin tener que leer la tabla de roles."""
    rol: RolResponse | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    usuario:      UsuarioResponse
