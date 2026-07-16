# vigilancia/services/Evento_Service.py
# Inserta filas en eventos_camara (bitácora de lo que vio cada cámara). Traduce el
# ScanResponse del back a un tipo_evento y guarda los enlaces SUAVES (id_escaneo/
# id_trabajador) que devolvió el scanner.
from sqlalchemy.orm import Session

from src.models.EventoCamara_Model import EventoCamara


def tipo_desde_scan(resp: dict) -> str:
    """Mapea el ScanResponse a un tipo_evento_camara."""
    if resp.get("acceso"):
        return "match"
    estado = (resp.get("estado_registro") or "").lower()
    mensaje = (resp.get("mensaje") or "").lower()
    texto = f"{estado} {mensaje}"
    if "spoof" in texto:
        return "spoof"
    if "no se detect" in texto or "no_rostro" in texto or "sin rostro" in texto:
        return "no_rostro"
    return "no_match"


def registrar(db: Session, *, id_camara: int, id_empresa: int | None, id_puerta: int | None,
              tipo_evento: str, mensaje: str | None = None, id_escaneo=None,
              id_trabajador: int | None = None, confianza: float | None = None,
              face_px: int | None = None) -> EventoCamara:
    ev = EventoCamara(
        id_camara=id_camara, id_empresa=id_empresa, id_puerta=id_puerta,
        tipo_evento=tipo_evento, mensaje=mensaje, id_escaneo=id_escaneo,
        id_trabajador=id_trabajador, confianza=confianza, face_px=face_px,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
