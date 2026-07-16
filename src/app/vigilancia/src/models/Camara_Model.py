# vigilancia/models/Camara_Model.py
# Config de cada terminal/cámara IP de captura para asistencia por reconocimiento.
# Los FK a empresas/area_trabajo/puertas_acceso/dispositivos los enforcea la BD
# (init.sql/migración); aquí las columnas cruzadas van como Integer plano para NO
# arrastrar mappers de otros dominios.
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from src.core.pgdb import Base


class Camara(Base):
    __tablename__ = "camaras"

    id_camara          = Column(Integer, primary_key=True, autoincrement=True)
    nombre             = Column(String(100), nullable=False)
    id_empresa         = Column(Integer, nullable=False)
    id_area            = Column(Integer, nullable=True)
    # Punto de fichaje: define puerta/empresa/tipo del escaneo (requerido en asistencia).
    id_puerta          = Column(Integer, nullable=True)
    id_dispositivo     = Column(Integer, nullable=True)
    # ── Conexión (captura ISAPI HTTP) ─────────────────────────────────────────
    marca              = Column(String(20), nullable=False, default="hikvision")
    # Opcional: si es NULL, la cámara HEREDA la IP de su grupo DVR (grupos_dvr.host).
    # Las cámaras IP directas ponen su propio host (gana sobre el del grupo).
    host               = Column(String(45), nullable=True)
    puerto             = Column(Integer, nullable=False, default=80)
    canal              = Column(Integer, nullable=False, default=101)
    ruta_snapshot      = Column(Text, nullable=True)
    usuario            = Column(String(60), nullable=True)
    credencial_cifrada = Column(LargeBinary, nullable=True)   # Fernet; NUNCA texto plano
    # ── Comportamiento ────────────────────────────────────────────────────────
    tipo_camara        = Column(String(20), nullable=False, default="asistencia")  # +'seguimiento' (reid)
    # Cómo se conecta: ip_directa (IP propia) | ip_dvr (IP tras DVR) | analogica (solo DVR).
    tipo_conexion      = Column(String(12), nullable=False, default="ip_directa")
    tipo_registro      = Column(String(10), nullable=False, default="entrada")
    habilitada         = Column(Boolean, nullable=False, default=True)
    modo_captura       = Column(String(10), nullable=False, default="sondeo")  # sondeo|evento
    gap_muestreo_seg   = Column(Float, nullable=False, default=0.7)
    umbral_movimiento  = Column(Float, nullable=False, default=2.5)
    cooldown_seg       = Column(Integer, nullable=False, default=90)
    # ── Seguimiento (reid) ────────────────────────────────────────────────────
    # Cámaras 'seguimiento': reusan las credenciales del grupo (DVR) → no repiten
    # password. roi_poligono = polígono del piso "x1,y1;x2,y2;..."; params_reid =
    # {min_alto, sim_umbral, ...} que el supervisor reid mapea a REID_* por cámara.
    id_grupo_dvr       = Column(Integer, nullable=True)
    roi_poligono       = Column(Text, nullable=True)
    params_reid        = Column(JSONB, nullable=True)
    # ── Estado / telemetría ───────────────────────────────────────────────────
    estado             = Column(String(15), nullable=False, default="activo")
    ultima_conexion    = Column(DateTime(timezone=True), nullable=True)
    ultimo_frame_ts    = Column(DateTime(timezone=True), nullable=True)
    fecha_creacion     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
