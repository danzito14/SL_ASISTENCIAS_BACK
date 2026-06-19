# app/services/reporte_service.py
"""
Generación de reportes descargables (CSV / XLSX) de las distintas entidades.
Cada reporte se acota por la empresa del usuario (None = super-admin → todas).
"""
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Asistencia_HistorialAuditoria_Model import Asistencia
from src.models.Empresa_Model import Empresa
from src.models.Escaneo_Model import Escaneo
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _celda(v):
    """Normaliza un valor para exportar (fechas a texto, Decimal a float)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _hasta_fin_de_dia(fecha_fin: date) -> datetime:
    """Convierte una fecha 'fin' (inclusiva) al límite superior para timestamps."""
    return datetime.combine(fecha_fin + timedelta(days=1), datetime.min.time())


class ReporteService:

    # ── Exportador genérico ────────────────────────────────────────────────────
    def _exportar(
        self,
        columnas: list[tuple[str, str]],   # [(clave, "Encabezado"), ...]
        filas: list[dict],
        nombre_base: str,
        formato: str,
    ) -> StreamingResponse:
        claves = [c[0] for c in columnas]
        encabezados = [c[1] for c in columnas]

        if formato == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(encabezados)
            for f in filas:
                w.writerow([_celda(f.get(k)) for k in claves])
            # utf-8-sig (BOM) para que Excel respete acentos al abrir el CSV.
            data = buf.getvalue().encode("utf-8-sig")
            media = "text/csv; charset=utf-8"

        elif formato == "xlsx":
            try:
                from openpyxl import Workbook
            except ImportError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Falta la librería 'openpyxl' para exportar a XLSX (pip install openpyxl).",
                )
            wb = Workbook()
            ws = wb.active
            ws.title = nombre_base[:31]
            ws.append(encabezados)
            for f in filas:
                ws.append([_celda(f.get(k)) for k in claves])
            bio = io.BytesIO()
            wb.save(bio)
            data = bio.getvalue()
            media = XLSX_MEDIA

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El formato debe ser 'csv' o 'xlsx'.",
            )

        nombre = f"{nombre_base}.{formato}"
        return StreamingResponse(
            io.BytesIO(data),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    # ── Reportes ───────────────────────────────────────────────────────────────
    def asistencias(
        self, db: Session, id_empresa: int | None, fecha_inicio: date | None,
        fecha_fin: date | None, formato: str, id_trabajador: int | None = None,
    ) -> StreamingResponse:
        q = db.query(Asistencia, Trabajador).join(
            Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador
        )
        if id_empresa is not None:
            q = q.join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area).filter(
                AreaTrabajo.id_empresa == id_empresa
            )
        if id_trabajador is not None:
            q = q.filter(Asistencia.id_trabajador == id_trabajador)
        if fecha_inicio is not None:
            q = q.filter(Asistencia.fecha_hora >= fecha_inicio)
        if fecha_fin is not None:
            q = q.filter(Asistencia.fecha_hora < _hasta_fin_de_dia(fecha_fin))

        filas = [
            {
                "id": a.id_asistencia,
                "trabajador": f"{t.nombre} {t.apellido}",
                "tipo": a.tipo_registro,
                "fecha_hora": a.fecha_hora,
                "confianza": a.confianza_biometrica,
                "estado": a.estado_registro,
                "observaciones": a.observaciones,
            }
            for a, t in q.order_by(Asistencia.fecha_hora.desc()).all()
        ]
        columnas = [
            ("id", "ID"), ("trabajador", "Trabajador"), ("tipo", "Tipo"),
            ("fecha_hora", "Fecha y hora"), ("confianza", "Confianza"),
            ("estado", "Estado"), ("observaciones", "Observaciones"),
        ]
        return self._exportar(columnas, filas, "asistencias", formato)

    def incidencias(
        self, db: Session, id_empresa: int | None, fecha_inicio: date | None,
        fecha_fin: date | None, formato: str, tipo: str | None = None,
        id_trabajador: int | None = None,
    ) -> StreamingResponse:
        q = db.query(Incidencia, Trabajador).join(
            Trabajador, Trabajador.id_trabajador == Incidencia.id_trabajador
        )
        if id_empresa is not None:
            q = q.join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area).filter(
                AreaTrabajo.id_empresa == id_empresa
            )
        if tipo is not None:
            q = q.filter(Incidencia.tipo_incidencia == tipo)
        if id_trabajador is not None:
            q = q.filter(Incidencia.id_trabajador == id_trabajador)
        if fecha_inicio is not None:
            q = q.filter(Incidencia.fecha >= fecha_inicio)
        if fecha_fin is not None:
            q = q.filter(Incidencia.fecha <= fecha_fin)

        filas = [
            {
                "id": i.id_incidencia,
                "trabajador": f"{t.nombre} {t.apellido}",
                "tipo": i.tipo_incidencia,
                "fecha": i.fecha,
                "estado": i.estado,
                "descripcion": i.descripcion,
            }
            for i, t in q.order_by(Incidencia.fecha.desc(), Incidencia.id_incidencia.desc()).all()
        ]
        columnas = [
            ("id", "ID"), ("trabajador", "Trabajador"), ("tipo", "Tipo"),
            ("fecha", "Fecha"), ("estado", "Estado"), ("descripcion", "Descripción"),
        ]
        return self._exportar(columnas, filas, "incidencias", formato)

    def intentos(
        self, db: Session, id_empresa: int | None, fecha_inicio: date | None,
        fecha_fin: date | None, formato: str,
    ) -> StreamingResponse:
        q = db.query(IntentoAcceso, Trabajador).outerjoin(
            Trabajador, Trabajador.id_trabajador == IntentoAcceso.id_trabajador
        )
        if id_empresa is not None:
            q = q.filter(IntentoAcceso.id_empresa == id_empresa)
        if fecha_inicio is not None:
            q = q.filter(IntentoAcceso.fecha >= fecha_inicio)
        if fecha_fin is not None:
            q = q.filter(IntentoAcceso.fecha < _hasta_fin_de_dia(fecha_fin))

        filas = [
            {
                "id": it.id_intento,
                "tipo": it.tipo,
                "fecha": it.fecha,
                "puerta": it.id_puerta,
                "trabajador": f"{t.nombre} {t.apellido}" if t else "",
                "similitud": it.similitud,
            }
            for it, t in q.order_by(IntentoAcceso.fecha.desc()).all()
        ]
        columnas = [
            ("id", "ID"), ("tipo", "Tipo"), ("fecha", "Fecha y hora"),
            ("puerta", "Puerta"), ("trabajador", "Trabajador (si aplica)"),
            ("similitud", "Similitud"),
        ]
        return self._exportar(columnas, filas, "intentos_acceso", formato)

    def trabajadores(
        self, db: Session, id_empresa: int | None, formato: str,
    ) -> StreamingResponse:
        q = (
            db.query(Trabajador, AreaTrabajo, Empresa)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .join(Empresa, Empresa.id_empresa == AreaTrabajo.id_empresa)
        )
        if id_empresa is not None:
            q = q.filter(AreaTrabajo.id_empresa == id_empresa)

        filas = [
            {
                "id": t.id_trabajador,
                "nombre": t.nombre,
                "apellido": t.apellido,
                "area": a.nombre_area,
                "empresa": e.nombre_empresa,
                "estado": t.estado,
            }
            for t, a, e in q.order_by(Trabajador.id_trabajador).all()
        ]
        columnas = [
            ("id", "ID"), ("nombre", "Nombre"), ("apellido", "Apellido"),
            ("area", "Área"), ("empresa", "Empresa"), ("estado", "Estado"),
        ]
        return self._exportar(columnas, filas, "trabajadores", formato)


reporte_service = ReporteService()
