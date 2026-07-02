# offline_sync/services/Enrolamiento_Service.py
"""
Enrolamiento desde el APK, en DOS modos por item (ver Enrolamiento_Schema):

  • ASIGNAR a existente (item.id_trabajador presente): le pone (o reemplaza) el
    rostro a un trabajador que YA existe (p.ej. uno de SYS21 sin rostro). Solo hace
    upsert del embedding por id_trabajador; NO toca sus datos. Valida que el
    trabajador exista y sea de la empresa del usuario.

  • WALK-IN (sin id_trabajador): crea/actualiza un trabajador con id_emp=id_local y
    origen 'apk' (para gente que NO está en la nómina) + su embedding. Idempotente
    por el índice único parcial (id_emp, origen_nomina).

Cada item va en su SAVEPOINT: uno inválido se rechaza sin abortar el resto.
"""
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.auth import Principal, es_admin
from src.core.config import settings
from src.schemas.Enrolamiento_Schema import (EnrolamientoResponse, ItemEnrolado,
                                             ItemRechazado)

logger = logging.getLogger(__name__)

_SQL_TRABAJADOR = text("""
    INSERT INTO trabajadores (id_emp, origen_nomina, nombre, apellido, id_area,
                              id_empresa, permiso_escaneo, estado)
    VALUES (:id_emp, :origen, :nombre, :apellido, :id_area, :id_empresa, :permiso, 'activo')
    ON CONFLICT (id_emp, origen_nomina) WHERE id_emp IS NOT NULL
    DO UPDATE SET nombre = EXCLUDED.nombre, apellido = EXCLUDED.apellido,
                  id_area = EXCLUDED.id_area, id_empresa = EXCLUDED.id_empresa,
                  permiso_escaneo = EXCLUDED.permiso_escaneo, estado = 'activo',
                  fecha_actualizacion = NOW()
    RETURNING id_trabajador, (xmax::text::bigint = 0) AS insertado
""")
# (xmax = 0) distingue INSERT de UPDATE en el upsert; ::text::bigint evita el error
# 'operator does not exist: xid = integer' que ocurre en algunas versiones de PostgreSQL.

_SQL_EMBEDDING = text("""
    INSERT INTO embeddings (id_trabajador, vector_embedding, tipo_embedding,
                            calidad_embedding, modelo_ia, estado)
    VALUES (:id_trab, CAST(:vec AS vector), 'facial', :calidad, :modelo, 'activo')
    ON CONFLICT (id_trabajador) DO UPDATE SET
        vector_embedding = EXCLUDED.vector_embedding,
        calidad_embedding = EXCLUDED.calidad_embedding,
        modelo_ia = EXCLUDED.modelo_ia, fecha_captura = NOW(), estado = 'activo'
""")

_SQL_EMPRESA_DE_TRAB = text(
    "SELECT id_empresa FROM trabajadores WHERE id_trabajador = :idt AND estado = 'activo'"
)


def _vector(embedding) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


class EnrolamientoService:

    def enrolar(self, db: Session, items, principal: Principal) -> EnrolamientoResponse:
        creados = actualizados = asignados = 0
        enrolados: list[ItemEnrolado] = []
        rechazados: list[ItemRechazado] = []
        for idx, it in enumerate(items):
            motivo = self._validar(it, principal)
            if motivo:
                rechazados.append(self._rechazo(idx, it, motivo))
                continue
            try:
                with db.begin_nested():
                    if it.id_trabajador is not None:
                        self._asignar_rostro(db, it, principal)
                        asignados += 1
                        enrolados.append(ItemEnrolado(
                            indice=idx, id_trabajador=it.id_trabajador, modo="asignado"))
                    else:
                        id_trab, insertado = self._enrolar_walkin(db, it)
                        if insertado:
                            creados += 1
                        else:
                            actualizados += 1
                        enrolados.append(ItemEnrolado(
                            indice=idx, id_local=it.id_local, id_trabajador=id_trab,
                            modo="walkin", creado=insertado))
            except ValueError as e:  # rechazo de negocio (trabajador/empresa)
                rechazados.append(self._rechazo(idx, it, str(e)))
            except Exception as exc:  # error de BD (FK, etc.)
                logger.warning("Enrolamiento item %d rechazado: %s", idx, exc)
                rechazados.append(self._rechazo(idx, it, str(getattr(exc, "orig", exc)).splitlines()[0][:200]))
        db.commit()
        return EnrolamientoResponse(creados=creados, actualizados=actualizados,
                                    asignados=asignados, enrolados=enrolados,
                                    rechazados=rechazados)

    # ── Validación previa (sin BD) ─────────────────────────────────────────────
    def _validar(self, it, principal: Principal) -> str | None:
        if len(it.embedding) != settings.EMBEDDING_DIM:
            return f"embedding_dim_invalida ({len(it.embedding)}!={settings.EMBEDDING_DIM})"
        if it.id_trabajador is None:  # walk-in: exige datos + empresa
            if not (it.id_local and it.nombre and it.apellido and it.id_area is not None):
                return "faltan_datos_walkin (id_local, nombre, apellido, id_area)"
            if not es_admin(principal) and it.id_empresa != principal.empresa:
                return "empresa_no_permitida"
        # Modo asignar: la empresa del trabajador se valida en _asignar_rostro (necesita BD).
        return None

    # ── Modo ASIGNAR rostro a un trabajador existente ──────────────────────────
    def _asignar_rostro(self, db: Session, it, principal: Principal) -> None:
        fila = db.execute(_SQL_EMPRESA_DE_TRAB, {"idt": it.id_trabajador}).first()
        if fila is None:
            raise ValueError(f"trabajador_no_encontrado ({it.id_trabajador})")
        if not es_admin(principal) and fila.id_empresa != principal.empresa:
            raise ValueError("empresa_no_permitida")
        db.execute(_SQL_EMBEDDING, {
            "id_trab": it.id_trabajador, "vec": _vector(it.embedding),
            "calidad": it.calidad, "modelo": it.modelo_ia or settings.ENROL_MODELO_IA,
        })

    # ── Modo WALK-IN (alta nueva). Devuelve (id_trabajador, insertado) ─────────
    def _enrolar_walkin(self, db: Session, it) -> tuple[int, bool]:
        row = db.execute(_SQL_TRABAJADOR, {
            "id_emp": it.id_local, "origen": settings.ENROL_ORIGEN,
            "nombre": it.nombre, "apellido": it.apellido, "id_area": it.id_area,
            "id_empresa": it.id_empresa, "permiso": it.permiso_escaneo,
        }).first()
        db.execute(_SQL_EMBEDDING, {
            "id_trab": row.id_trabajador, "vec": _vector(it.embedding),
            "calidad": it.calidad, "modelo": it.modelo_ia or settings.ENROL_MODELO_IA,
        })
        return row.id_trabajador, bool(row.insertado)

    def _rechazo(self, idx, it, motivo) -> ItemRechazado:
        return ItemRechazado(indice=idx, id_local=it.id_local,
                             id_trabajador=it.id_trabajador, motivo=motivo)


enrolamiento_service = EnrolamientoService()
