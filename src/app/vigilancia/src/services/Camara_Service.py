# vigilancia/services/Camara_Service.py
# CRUD de cámaras/terminales. La contraseña llega en claro (payload.credencial), se
# CIFRA (Fernet) al persistir en credencial_cifrada y NUNCA se devuelve. La lógica de
# autorización por empresa vive en el router (usuario_actual/exigir_empresa).
from sqlalchemy.orm import Session

from src.models.Camara_Model import Camara
from src.schemas.Camara_Schema import CamaraCreate, CamaraUpdate
from src.services.Cifrado_Service import cifrado_service


class CamaraService:
    def crear(self, db: Session, payload: CamaraCreate) -> Camara:
        datos = payload.model_dump(exclude={"credencial"})
        cam = Camara(**datos)
        if payload.credencial:
            cam.credencial_cifrada = cifrado_service.cifrar(payload.credencial)
        db.add(cam)
        db.commit()
        db.refresh(cam)
        return cam

    def listar(self, db: Session, id_empresa: int | None) -> list[Camara]:
        q = db.query(Camara)
        if id_empresa is not None:
            q = q.filter(Camara.id_empresa == id_empresa)
        return q.order_by(Camara.id_camara).all()

    def obtener(self, db: Session, id_camara: int) -> Camara | None:
        return db.get(Camara, id_camara)

    def actualizar(self, db: Session, cam: Camara, payload: CamaraUpdate) -> Camara:
        datos = payload.model_dump(exclude_unset=True, exclude={"credencial"})
        for campo, valor in datos.items():
            setattr(cam, campo, valor)
        if payload.credencial:  # solo si mandan una nueva (no toca la existente si viene vacía/None)
            cam.credencial_cifrada = cifrado_service.cifrar(payload.credencial)
        db.commit()
        db.refresh(cam)
        return cam

    def eliminar(self, db: Session, cam: Camara) -> None:
        db.delete(cam)
        db.commit()

    def credencial_clara(self, cam: Camara) -> str | None:
        """Descifra la credencial para pedir el snapshot. Uso interno (no exponer)."""
        return cifrado_service.descifrar(cam.credencial_cifrada)


camara_service = CamaraService()
