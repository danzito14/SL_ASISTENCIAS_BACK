# employee_monitoring/services/ReglaClasificacion_Service.py
"""
CRUD de las reglas del clasificador del sync (tabla reglas_clasificacion) y la
lista de puestos/departamentos que llegaron sin regla.

Los cambios aplican en la SIGUIENTE corrida del sync (el clasificador relee la tabla
al empezar cada origen); los trabajadores ya registrados se reclasifican solos porque
su área/permiso entra en el hash de datos.
"""
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.FotoPendiente_Model import FotoPendiente
from src.models.ReglaClasificacion_Model import ReglaClasificacion
from src.schemas.ReglaClasificacion_Schema import (OpcionesReglas, PuestoSinRegla,
                                                   ReglaCreate, ReglaResponse, ReglaUpdate)
from src.sync.clasificador_areas import (GRUPOS, MOTIVO_SIN_REGLA, PERMISO_POR_GRUPO,
                                         normalizar)

ORIGENES = ("agricola", "agricola_com")
PERMISOS = ("campo", "administrativo", "general", "super")
NIVELES = ("oficina", "empaque", "mixto")


def _a_respuesta(r: ReglaClasificacion) -> ReglaResponse:
    """Agrega el permiso/nivel EFECTIVO (override o default del grupo; 'campo' sin nivel)."""
    permiso_def, nivel_def = PERMISO_POR_GRUPO[r.grupo]
    permiso = r.permiso_escaneo or permiso_def
    nivel = None if permiso == "campo" else (r.nivel_acceso_interno or nivel_def)
    return ReglaResponse(
        id_regla=r.id_regla, origen_nomina=r.origen_nomina, clave=r.clave, nombre=r.nombre,
        grupo=r.grupo, permiso_escaneo=r.permiso_escaneo,
        nivel_acceso_interno=r.nivel_acceso_interno, permiso_efectivo=permiso,
        nivel_efectivo=nivel, actualizado_por=r.actualizado_por,
        fecha_actualizacion=r.fecha_actualizacion,
    )


def _parsear_detalle(detalle: str | None) -> tuple[str, str]:
    """(empresa, area_nombre) del detalle que escribe el sync:
    'empresa=E area_codigo=C area_nombre=N'."""
    if not detalle or "area_nombre=" not in detalle:
        return "", ""
    resto, nombre = detalle.split("area_nombre=", 1)
    empresa = resto.split("area_codigo=", 1)[0].replace("empresa=", "", 1).strip()
    nombre = nombre.strip()
    return empresa, "" if nombre == "None" else nombre


class ReglaClasificacionService:

    def opciones(self) -> OpcionesReglas:
        return OpcionesReglas(
            origenes=list(ORIGENES), grupos=list(GRUPOS), permisos=list(PERMISOS),
            niveles=list(NIVELES),
            default_por_grupo={g: {"permiso_escaneo": p, "nivel_acceso_interno": n}
                               for g, (p, n) in PERMISO_POR_GRUPO.items()},
        )

    def listar(self, db: Session, origen: str | None, grupo: str | None,
               buscar: str | None) -> list[ReglaResponse]:
        q = db.query(ReglaClasificacion)
        if origen:
            q = q.filter(ReglaClasificacion.origen_nomina == origen)
        if grupo:
            q = q.filter(ReglaClasificacion.grupo == grupo)
        if buscar:
            q = q.filter(ReglaClasificacion.clave.contains(normalizar(buscar), autoescape=True))
        filas = q.order_by(ReglaClasificacion.origen_nomina, ReglaClasificacion.clave).all()
        return [_a_respuesta(r) for r in filas]

    def obtener(self, db: Session, id_regla: int) -> ReglaClasificacion:
        regla = db.get(ReglaClasificacion, id_regla)
        if regla is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Regla {id_regla} no encontrada.")
        return regla

    def crear(self, db: Session, datos: ReglaCreate, usuario: str | None) -> ReglaResponse:
        clave = normalizar(datos.nombre)
        if not clave:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El nombre está vacío.")
        regla = ReglaClasificacion(
            origen_nomina=datos.origen_nomina, clave=clave, nombre=datos.nombre.strip(),
            grupo=datos.grupo, permiso_escaneo=datos.permiso_escaneo,
            nivel_acceso_interno=datos.nivel_acceso_interno, actualizado_por=usuario,
        )
        db.add(regla)
        self._guardar(db, clave, datos.origen_nomina)
        db.refresh(regla)
        return _a_respuesta(regla)

    def actualizar(self, db: Session, id_regla: int, datos: ReglaUpdate,
                   usuario: str | None) -> ReglaResponse:
        regla = self.obtener(db, id_regla)
        cambios = datos.model_dump(exclude_unset=True)
        if "nombre" in cambios:
            if cambios["nombre"] is None or not normalizar(cambios["nombre"]):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El nombre está vacío.")
            regla.nombre = cambios["nombre"].strip()
            regla.clave = normalizar(cambios["nombre"])
        if "grupo" in cambios:
            if cambios["grupo"] is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El grupo es obligatorio.")
            regla.grupo = cambios["grupo"]
        if "permiso_escaneo" in cambios:
            regla.permiso_escaneo = cambios["permiso_escaneo"]
        if "nivel_acceso_interno" in cambios:
            regla.nivel_acceso_interno = cambios["nivel_acceso_interno"]
        regla.actualizado_por = usuario
        self._guardar(db, regla.clave, regla.origen_nomina)
        db.refresh(regla)
        return _a_respuesta(regla)

    def eliminar(self, db: Session, id_regla: int) -> None:
        db.delete(self.obtener(db, id_regla))
        db.commit()

    def sin_regla(self, db: Session, origen: str | None) -> list[PuestoSinRegla]:
        """Puestos/departamentos rechazados por 'sin regla' en la última corrida."""
        q = db.query(FotoPendiente.origen_nomina, FotoPendiente.detalle).filter(
            FotoPendiente.motivo == MOTIVO_SIN_REGLA, FotoPendiente.estado == "pendiente")
        if origen:
            q = q.filter(FotoPendiente.origen_nomina == origen)

        grupos: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"nombre": "", "personas": 0, "empresas": set()})
        for org, detalle in q.all():
            empresa, nombre = _parsear_detalle(detalle)
            g = grupos[(org, normalizar(nombre))]
            g["nombre"] = g["nombre"] or nombre
            g["personas"] += 1
            if empresa:
                g["empresas"].add(empresa)

        existentes = {(r.origen_nomina, r.clave)
                      for r in db.query(ReglaClasificacion.origen_nomina, ReglaClasificacion.clave)}
        salida = [
            PuestoSinRegla(
                origen_nomina=org, nombre=g["nombre"] or "(sin puesto)", clave=clave,
                personas=g["personas"], empresas=sorted(g["empresas"], key=lambda e: (len(e), e)),
                con_regla=(org, clave) in existentes,
            )
            for (org, clave), g in grupos.items()
        ]
        return sorted(salida, key=lambda p: (p.con_regla, -p.personas, p.clave))

    @staticmethod
    def _guardar(db: Session, clave: str, origen: str) -> None:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Ya existe una regla para '{clave}' en la nómina '{origen}'.",
            )


regla_service = ReglaClasificacionService()
