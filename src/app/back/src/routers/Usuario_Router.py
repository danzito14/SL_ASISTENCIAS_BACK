# app/api/v1/endpoints/usuario.py
from fastapi import APIRouter, Depends, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from src.core.auth import token_para_usuario, usuario_actual
from src.core.pgdb import get_db
from src.models.Rol_Usuario_Model import Usuario
from src.schemas.Rol_Usuario_Schema import (
    UsuarioConRol,
    UsuarioCreate,
    UsuarioResponse,
    UsuarioUpdate,
    UsuarioLogin,
    TokenResponse,
)
from src.services.Usuario_Service import usuario_service

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


@router.post(
    "",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar usuario",
    description="Crea un usuario. La contraseña se guarda hasheada; nunca se devuelve.",
)
def registrar_usuario(datos: UsuarioCreate, db: Session = Depends(get_db)):
    return usuario_service.registrar_usuario(datos=datos, db=db)


# ── Login ─────────────────────────────────────────────────────────────────────
@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Iniciar sesión",
    description="Verifica nombre_usuario + contraseña y devuelve un JWT (access_token) + el usuario. 401 si fallan.",
)
def login(datos: UsuarioLogin, db: Session = Depends(get_db)):
    usuario = usuario_service.login(datos=datos, db=db)
    token = token_para_usuario(usuario)
    return TokenResponse(access_token=token, usuario=usuario)


# ── Token OAuth2 (lo usa el botón "Authorize" de /docs) ───────────────────────
@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Token OAuth2 (para el botón Authorize de /docs)",
    description="Igual que /login pero recibe el form OAuth2 (username/password). Pensado para Swagger.",
)
def token_oauth2(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    usuario = usuario_service.login(
        datos=UsuarioLogin(nombre_usuario=form.username, contrasena=form.password),
        db=db,
    )
    token = token_para_usuario(usuario)
    return TokenResponse(access_token=token, usuario=usuario)


@router.get(
    "",
    response_model=list[UsuarioResponse],
    summary="Listar usuarios",
    description="Devuelve todos los usuarios registrados (con paginación).",
)
def listar_usuarios(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return usuario_service.listar_usuarios(db=db, skip=skip, limit=limit, nombre=nombre)


# ── Usuario actual (cualquier usuario autenticado) ────────────────────────────
# OJO: debe declararse ANTES de GET /{id_usuario}, si no "me" se intentaría
# interpretar como un id numérico y devolvería 422.
@router.get(
    "/me",
    response_model=UsuarioConRol,
    summary="Usuario actual (con su rol y permisos)",
    description=(
        "Devuelve el usuario autenticado junto con su rol y scopes. Disponible para "
        "cualquier usuario con token válido, sin necesitar el scope 'roles:read'. "
        "Pensado para que el front conozca los permisos del usuario tras el login."
    ),
)
def obtener_usuario_actual(usuario: Usuario = Depends(usuario_actual)):
    return usuario


@router.get(
    "/{id_usuario}",
    response_model=UsuarioResponse,
    summary="Obtener usuario",
    description="Devuelve un usuario por su id.",
)
def obtener_usuario(id_usuario: int, db: Session = Depends(get_db)):
    return usuario_service.obtener_usuario(id_usuario=id_usuario, db=db)


@router.put(
    "/{id_usuario}",
    response_model=UsuarioResponse,
    summary="Actualizar usuario",
    description="Actualiza los campos enviados. Si mandas 'contrasena', se re-hashea.",
)
def actualizar_usuario(id_usuario: int, datos: UsuarioUpdate, db: Session = Depends(get_db)):
    return usuario_service.actualizar_usuario(id_usuario=id_usuario, datos=datos, db=db)


@router.delete(
    "/{id_usuario}",
    response_model=UsuarioResponse,
    summary="Desactivar usuario",
    description="Baja lógica: marca el usuario como 'inactivo' (no borra la fila).",
)
def eliminar_usuario(id_usuario: int, db: Session = Depends(get_db)):
    return usuario_service.eliminar_usuario(id_usuario=id_usuario, db=db)
