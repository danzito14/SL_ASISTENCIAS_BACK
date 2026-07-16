# vigilancia/services/GrupoDvr_Service.py
# CRUD de grupos_dvr (agrupan cámaras de seguimiento por DVR). La contraseña del DVR
# llega en claro (payload.credencial), se CIFRA (Fernet) al persistir en
# credencial_cifrada y NUNCA se devuelve. Espeja Camara_Service. La autorización por
# empresa vive en el router (usuario_actual/exigir_empresa).
from sqlalchemy.orm import Session

from src.models.GrupoDvr_Model import GrupoDvr
from src.schemas.GrupoDvr_Schema import GrupoDvrCreate, GrupoDvrUpdate
from src.services.Cifrado_Service import cifrado_service


class GrupoDvrService:
    def crear(self, db: Session, payload: GrupoDvrCreate) -> GrupoDvr:
        datos = payload.model_dump(exclude={"credencial", "credencial_camaras"})
        grupo = GrupoDvr(**datos)
        if payload.credencial:
            grupo.credencial_cifrada = cifrado_service.cifrar(payload.credencial)
        if payload.credencial_camaras:
            grupo.credencial_camaras_cifrada = cifrado_service.cifrar(payload.credencial_camaras)
        db.add(grupo)
        db.commit()
        db.refresh(grupo)
        return grupo

    def listar(self, db: Session, id_empresa: int | None) -> list[GrupoDvr]:
        q = db.query(GrupoDvr)
        if id_empresa is not None:
            q = q.filter(GrupoDvr.id_empresa == id_empresa)
        return q.order_by(GrupoDvr.id_grupo_dvr).all()

    def obtener(self, db: Session, id_grupo_dvr: int) -> GrupoDvr | None:
        return db.get(GrupoDvr, id_grupo_dvr)

    def actualizar(self, db: Session, grupo: GrupoDvr, payload: GrupoDvrUpdate) -> GrupoDvr:
        datos = payload.model_dump(exclude_unset=True, exclude={"credencial", "credencial_camaras"})
        for campo, valor in datos.items():
            setattr(grupo, campo, valor)
        if payload.credencial:  # solo si mandan una nueva (no toca la existente si viene vacía/None)
            grupo.credencial_cifrada = cifrado_service.cifrar(payload.credencial)
        if payload.credencial_camaras:
            grupo.credencial_camaras_cifrada = cifrado_service.cifrar(payload.credencial_camaras)
        db.commit()
        db.refresh(grupo)
        return grupo

    def eliminar(self, db: Session, grupo: GrupoDvr) -> None:
        db.delete(grupo)
        db.commit()

    def credencial_clara(self, grupo: GrupoDvr) -> str | None:
        """Descifra la credencial del DVR para armar el RTSP. Uso interno (no exponer)."""
        return cifrado_service.descifrar(grupo.credencial_cifrada)

    def credencial_camaras_clara(self, grupo: GrupoDvr) -> str | None:
        """Password de las CÁMARAS (acceso por IP directa). None si no se configuró."""
        return cifrado_service.descifrar(grupo.credencial_camaras_cifrada)


grupo_dvr_service = GrupoDvrService()
