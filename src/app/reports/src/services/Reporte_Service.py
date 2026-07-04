# app/services/reporte_service.py
"""
Generación de reportes descargables (CSV / XLSX) de las distintas entidades.
Cada reporte se acota por la empresa del usuario (None = super-admin → todas).
"""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Asistencia_HistorialAuditoria_Model import Asistencia
from src.models.Empresa_Model import Empresa
from src.models.Incidencia_Model import Incidencia
from src.models.IntentoAcceso_Model import IntentoAcceso

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _celda(v):
    """Normaliza un valor para exportar (fechas a texto, Decimal a float, UUID a texto)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):   # openpyxl no acepta objetos UUID; las PKs ahora son UUID
        return str(v)
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
            q = q.filter(Asistencia.id_empresa == id_empresa)  # denormalizado (access)
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
            q = q.filter(Incidencia.id_empresa == id_empresa)  # denormalizado (access)
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
                # Escaneo que originó la incidencia → el front puede pedir
                # GET /escaneos/{id} para la info completa. NULL si no aplica.
                "escaneo_ref": i.id_escaneo_ref,
            }
            for i, t in q.order_by(Incidencia.fecha.desc(), Incidencia.id_incidencia.desc()).all()
        ]
        columnas = [
            ("id", "ID"), ("trabajador", "Trabajador"), ("tipo", "Tipo"),
            ("fecha", "Fecha"), ("estado", "Estado"), ("descripcion", "Descripción"),
            ("escaneo_ref", "Escaneo (ID)"),
        ]
        return self._exportar(columnas, filas, "incidencias", formato)

    def retardos(
        self, db: Session, id_empresa: int | None, fecha_inicio: date | None,
        fecha_fin: date | None, formato: str, id_trabajador: int | None = None,
        tolerancia_min: int = 0,
    ) -> StreamingResponse:
        """
        Reporte CALCULADO de retardos: entradas cuya hora LOCAL supera la hora_entrada
        del área del trabajador (más una tolerancia opcional en minutos), con los
        minutos de retraso. Solo considera áreas con hora_entrada definida.

        La hora se compara en la zona horaria de la empresa (fecha_hora es UTC).
        """
        q = (
            db.query(Asistencia, Trabajador, AreaTrabajo, Empresa)
            .join(Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .join(Empresa, Empresa.id_empresa == Asistencia.id_empresa)
            .filter(Asistencia.tipo_registro == "entrada")
            .filter(AreaTrabajo.hora_entrada.isnot(None))
        )
        if id_empresa is not None:
            q = q.filter(Asistencia.id_empresa == id_empresa)
        if id_trabajador is not None:
            q = q.filter(Asistencia.id_trabajador == id_trabajador)
        if fecha_inicio is not None:
            q = q.filter(Asistencia.fecha_hora >= fecha_inicio)
        if fecha_fin is not None:
            q = q.filter(Asistencia.fecha_hora < _hasta_fin_de_dia(fecha_fin))

        # ASC: la primera fila por (trabajador, día local) es su entrada más temprana;
        # así se cuenta UNA sola vez al día (la hora real de llegada).
        vistos: set = set()
        filas = []
        for a, t, ar, e in q.order_by(Asistencia.fecha_hora.asc()).all():
            try:
                tz = ZoneInfo(e.zona_horaria) if e.zona_horaria else timezone.utc
            except Exception:
                tz = timezone.utc
            # fecha_hora es timestamptz (aware); si viniera naive, se asume UTC.
            dt = a.fecha_hora if a.fecha_hora.tzinfo else a.fecha_hora.replace(tzinfo=timezone.utc)
            local = dt.astimezone(tz)
            clave = (t.id_trabajador, local.date())
            if clave in vistos:
                continue
            vistos.add(clave)
            esperada = ar.hora_entrada
            retraso = (local.hour * 60 + local.minute) - (esperada.hour * 60 + esperada.minute)
            if retraso <= tolerancia_min:
                continue  # a tiempo (o dentro de la tolerancia)
            filas.append({
                "id_trabajador": t.id_trabajador,
                "id_emp": t.id_emp,
                "trabajador": f"{t.nombre} {t.apellido}",
                "area": ar.nombre_area,
                "empresa": e.nombre_empresa,
                "fecha": local.date(),
                "hora_esperada": esperada.strftime("%H:%M"),
                "hora_real": local.strftime("%H:%M"),
                "minutos_retardo": retraso,
            })
        # Más recientes primero para el archivo.
        filas.sort(key=lambda r: (r["fecha"], r["minutos_retardo"]), reverse=True)
        columnas = [
            ("id_trabajador", "ID trabajador"), ("id_emp", "N° empleado"),
            ("trabajador", "Trabajador"), ("area", "Área"), ("empresa", "Empresa"),
            ("fecha", "Fecha"), ("hora_esperada", "Hora esperada"),
            ("hora_real", "Hora real"), ("minutos_retardo", "Minutos de retardo"),
        ]
        return self._exportar(columnas, filas, "retardos", formato)

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
        # Los joins a área/empresa se conservan: el reporte muestra sus NOMBRES.
        # El filtro por empresa sí usa el id_empresa denormalizado del trabajador.
        q = (
            db.query(Trabajador, AreaTrabajo, Empresa)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .join(Empresa, Empresa.id_empresa == AreaTrabajo.id_empresa)
        )
        if id_empresa is not None:
            q = q.filter(Trabajador.id_empresa == id_empresa)

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

    # ── Dashboard (JSON, no archivo) ───────────────────────────────────────────
    def _tz_empresa(self, db: Session, id_empresa: int | None) -> ZoneInfo:
        if id_empresa is not None:
            fila = db.query(Empresa.zona_horaria).filter(Empresa.id_empresa == id_empresa).first()
            if fila and fila[0]:
                try:
                    return ZoneInfo(fila[0])
                except Exception:
                    pass
        return ZoneInfo("America/Mazatlan")

    def dashboard(self, db: Session, id_empresa: int | None, fecha: date | None = None) -> dict:
        """
        Números del día para el panel: presentes/total (global y por tipo de área),
        ausentes, retardos, intentos, incidencias pendientes, y padrón con/sin rostro.
        'presente' = tiene al menos una ENTRADA en el día (zona horaria de la empresa).
        """
        tz = self._tz_empresa(db, id_empresa)
        dia = fecha or datetime.now(tz).date()
        ini = datetime.combine(dia, time.min, tzinfo=tz).astimezone(timezone.utc)
        fin = ini + timedelta(days=1)

        def _emp(q, col):
            return q.filter(col == id_empresa) if id_empresa is not None else q

        # Total de trabajadores activos por tipo de área.
        q_tot = (
            db.query(AreaTrabajo.tipo_area, func.count(Trabajador.id_trabajador))
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .filter(Trabajador.estado == "activo")
        )
        q_tot = _emp(q_tot, Trabajador.id_empresa)
        total_por_tipo = {(t or "sin_tipo"): n for t, n in q_tot.group_by(AreaTrabajo.tipo_area).all()}

        # Presentes hoy (trabajadores DISTINTOS con entrada) por tipo de área.
        q_pre = (
            db.query(AreaTrabajo.tipo_area, func.count(func.distinct(Asistencia.id_trabajador)))
            .join(Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .filter(Asistencia.tipo_registro == "entrada",
                    Asistencia.fecha_hora >= ini, Asistencia.fecha_hora < fin)
        )
        q_pre = _emp(q_pre, Asistencia.id_empresa)
        pres_por_tipo = {(t or "sin_tipo"): n for t, n in q_pre.group_by(AreaTrabajo.tipo_area).all()}

        tipos = set(total_por_tipo) | set(pres_por_tipo)
        por_tipo = {
            t: {"total": total_por_tipo.get(t, 0), "presentes": pres_por_tipo.get(t, 0)}
            for t in sorted(tipos)
        }
        total = sum(total_por_tipo.values())
        presentes = sum(pres_por_tipo.values())

        # Retardos de hoy: 1ª entrada del día por trabajador vs hora_entrada del área.
        q_ret = (
            db.query(Asistencia.id_trabajador, Asistencia.fecha_hora, AreaTrabajo.hora_entrada)
            .join(Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador)
            .join(AreaTrabajo, AreaTrabajo.id_area == Trabajador.id_area)
            .filter(Asistencia.tipo_registro == "entrada", AreaTrabajo.hora_entrada.isnot(None),
                    Asistencia.fecha_hora >= ini, Asistencia.fecha_hora < fin)
        )
        q_ret = _emp(q_ret, Asistencia.id_empresa)
        primeras: dict[int, tuple] = {}
        for id_t, fh, he in q_ret.order_by(Asistencia.fecha_hora.asc()).all():
            if id_t not in primeras:
                primeras[id_t] = (fh, he)
        retardos = 0
        for fh, he in primeras.values():
            local = (fh if fh.tzinfo else fh.replace(tzinfo=timezone.utc)).astimezone(tz)
            if (local.hour * 60 + local.minute) > (he.hour * 60 + he.minute):
                retardos += 1

        # Intentos de hoy.
        q_int = db.query(func.count(IntentoAcceso.id_intento)).filter(
            IntentoAcceso.fecha >= ini, IntentoAcceso.fecha < fin)
        q_int = _emp(q_int, IntentoAcceso.id_empresa)
        intentos = q_int.scalar() or 0

        # Incidencias PENDIENTES (todas las abiertas, no solo hoy).
        q_inc = db.query(func.count(Incidencia.id_incidencia)).filter(Incidencia.estado == "pendiente")
        q_inc = _emp(q_inc, Incidencia.id_empresa)
        incidencias_pend = q_inc.scalar() or 0

        # Padrón con/sin rostro (embeddings; reports no tiene modelo Embedding → SQL crudo).
        con_rostro = db.execute(text(
            "SELECT count(DISTINCT e.id_trabajador) FROM embeddings e "
            "JOIN trabajadores t ON t.id_trabajador = e.id_trabajador "
            "WHERE t.estado='activo' AND (:emp IS NULL OR t.id_empresa = :emp)"
        ), {"emp": id_empresa}).scalar() or 0

        return {
            "fecha": dia.isoformat(),
            "empresa": id_empresa,
            "trabajadores": {"total": total, "con_rostro": con_rostro, "sin_rostro": max(0, total - con_rostro)},
            "asistencia": {
                "presentes": presentes,
                "ausentes": max(0, total - presentes),
                "por_tipo": por_tipo,          # {oficina:{total,presentes}, empaque:..., campo:...}
            },
            "retardos_hoy": retardos,
            "intentos_hoy": intentos,
            "incidencias_pendientes": incidencias_pend,
        }


reporte_service = ReporteService()
