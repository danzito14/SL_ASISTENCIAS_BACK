# identity/schemas/rol_usuario.py
from pydantic import BaseModel, Field
from datetime import datetime


class RolPermisos(BaseModel):
    """Permisos como lista de scopes 'recurso:accion'. Comodines: '*', 'recurso:*', '*:accion'."""
    scopes: list[str] = Field(default_factory=list)


class RolBase(BaseModel):
    nombre_rol:  str
    descripcion: str | None = None
    permisos:    RolPermisos = Field(default_factory=RolPermisos)
    estado:      str = "activo"


class RolCreate(RolBase):
    pass


class RolUpdate(BaseModel):
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
    empresa: int = 1  # 99 (EMPRESA_ADMIN) = acceso a todas.


class UsuarioCreate(UsuarioBase):
    contrasena: str


class UsuarioUpdate(BaseModel):
    nombre_usuario: str | None = None
    id_rol:         int | None = None
    estado:         str | None = None
    empresa:        int | None = None
    contrasena:     str | None = None


class UsuarioLogin(BaseModel):
    nombre_usuario: str
    contrasena:     str


class UsuarioResponse(UsuarioBase):
    id_usuario: int
    fecha_creacion: datetime
    fecha_actualizacion: datetime

    model_config = {"from_attributes": True}


class UsuarioConRol(UsuarioResponse):
    """Usuario + su rol y scopes (lo usa /usuarios/me para que el front sepa qué puede hacer)."""
    rol: RolResponse | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    usuario:      UsuarioResponse
