# vigilancia/services/Reid_Service.py
# SEGUIMIENTO CORPORAL cross-cámara (reid), PASO 1: galería de apariencia COMPARTIDA en
# pgvector. El motor (seguimiento.py) manda la firma OSNet (512-D) de una detección nueva
# y aquí se resuelve su id de persona GLOBAL: se busca el vecino más cercano en reid_firmas
# (coseno, acotado por empresa) → si supera el umbral es la MISMA persona (reaparece, incl.
# en OTRA cámara), si no se crea una persona nueva. Siempre se registra el avistamiento.
#
# Raw SQL con pgvector (como recognition/motor.py): `1 - (embedding <=> CAST(:v AS vector))`
# = similitud coseno. Sin dependencias nuevas (el vector viaja como texto '[..]' y se castea).
from sqlalchemy import text
from sqlalchemy.orm import Session

UMBRAL_DEFAULT = 0.75   # coseno OSNet-AIN para considerar "misma persona" (igual que el motor)


def _vector_str(embedding) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"


class ReidService:
    def empresa_de_camara(self, db: Session, id_camara: int) -> tuple[int | None, str | None]:
        """(id_empresa, tipo_camara) de la cámara, o (None, None) si no existe."""
        row = db.execute(
            text("SELECT id_empresa, tipo_camara FROM camaras WHERE id_camara = :c"),
            {"c": id_camara},
        ).fetchone()
        return (row.id_empresa, row.tipo_camara) if row else (None, None)

    def procesar_avistamiento(self, db: Session, *, id_empresa: int | None, id_camara: int,
                              embedding: list[float], bbox: str | None = None,
                              ruta_crop: str | None = None, umbral: float = UMBRAL_DEFAULT,
                              enriquecer: bool = False) -> dict:
        """Resuelve el id de persona GLOBAL para una firma y registra el avistamiento.

        enriquecer=True agrega también una firma cuando REAPARECE (más vistas por persona
        → mejor re-emparejado, a costa de más filas). Por defecto solo guarda 1 firma por
        persona (al crearla) = "vestimenta registrada".
        """
        vector_str = _vector_str(embedding)

        # 1) Vecino más cercano en la galería COMPARTIDA (toda la empresa, cualquier cámara).
        row = db.execute(
            text("""
                SELECT f.id_persona, 1 - (f.embedding <=> CAST(:v AS vector)) AS sim
                FROM reid_firmas f
                WHERE (:emp IS NULL OR f.id_empresa = :emp)
                ORDER BY f.embedding <=> CAST(:v AS vector)
                LIMIT 1
            """),
            {"v": vector_str, "emp": id_empresa},
        ).fetchone()

        if row is not None and float(row.sim) >= umbral:
            # REAPARECE: misma persona (posiblemente en otra cámara) → id global conservado.
            id_persona = int(row.id_persona)
            sim = float(row.sim)
            evento, es_nueva = "reaparece", False
            db.execute(
                text("UPDATE reid_personas SET ultima_vez = NOW(), "
                     "n_avistamientos = n_avistamientos + 1 WHERE id_persona = :p"),
                {"p": id_persona},
            )
            if enriquecer:
                self._insertar_firma(db, id_persona, id_camara, id_empresa, vector_str, ruta_crop)
        else:
            # NUEVA persona anónima → persona-N (N = su id). Registra su vestimenta (1 firma).
            id_persona = int(db.execute(
                text("INSERT INTO reid_personas (id_empresa, n_avistamientos) "
                     "VALUES (:emp, 1) RETURNING id_persona"),
                {"emp": id_empresa},
            ).scalar())
            db.execute(
                text("UPDATE reid_personas SET etiqueta = :et WHERE id_persona = :p"),
                {"et": f"persona-{id_persona}", "p": id_persona},
            )
            self._insertar_firma(db, id_persona, id_camara, id_empresa, vector_str, ruta_crop)
            sim = float(row.sim) if row is not None else 0.0
            evento, es_nueva = "nueva", True

        # 2) Log del avistamiento (siempre).
        db.execute(
            text("""INSERT INTO reid_avistamientos
                        (id_persona, id_camara, id_empresa, similitud, evento, bbox)
                    VALUES (:p, :cam, :emp, :sim, :ev, :bbox)"""),
            {"p": id_persona, "cam": id_camara, "emp": id_empresa,
             "sim": sim, "ev": evento, "bbox": bbox},
        )
        db.commit()
        return {"id_persona": id_persona, "etiqueta": f"persona-{id_persona}",
                "es_nueva": es_nueva, "evento": evento, "similitud": round(sim, 4)}

    def _insertar_firma(self, db: Session, id_persona: int, id_camara: int,
                        id_empresa: int | None, vector_str: str, ruta_crop: str | None) -> None:
        db.execute(
            text("""INSERT INTO reid_firmas (id_persona, id_camara, id_empresa, embedding, ruta_crop)
                    VALUES (:p, :cam, :emp, CAST(:v AS vector), :crop)"""),
            {"p": id_persona, "cam": id_camara, "emp": id_empresa, "v": vector_str, "crop": ruta_crop},
        )

    def obtener_persona(self, db: Session, id_persona: int) -> dict | None:
        """Fila de la persona (empresa + identidad actual) para el paso del rostro."""
        row = db.execute(
            text("SELECT id_persona, id_empresa, id_trabajador, etiqueta "
                 "FROM reid_personas WHERE id_persona = :p"),
            {"p": id_persona},
        ).mappings().first()
        return dict(row) if row else None

    def anclar_identidad(self, db: Session, id_persona: int, id_trabajador: int, etiqueta: str) -> None:
        """Liga la persona (cluster de apariencia) a un trabajador reconocido por rostro.
        A partir de aquí sus avistamientos (por cuerpo, en cualquier cámara) tienen NOMBRE."""
        db.execute(
            text("UPDATE reid_personas SET id_trabajador = :t, etiqueta = :e WHERE id_persona = :p"),
            {"t": id_trabajador, "e": etiqueta, "p": id_persona},
        )
        db.commit()

    def listar_personas(self, db: Session, id_empresa: int | None) -> list[dict]:
        rows = db.execute(
            text("""SELECT id_persona, id_empresa, id_trabajador, etiqueta, n_avistamientos,
                           primera_vez, ultima_vez, estado
                    FROM reid_personas
                    WHERE (:emp IS NULL OR id_empresa = :emp)
                    ORDER BY ultima_vez DESC"""),
            {"emp": id_empresa},
        ).mappings().all()
        return [dict(r) for r in rows]

    def listar_avistamientos(self, db: Session, id_empresa: int | None, *,
                             id_persona: int | None = None, desde: str | None = None,
                             hasta: str | None = None, limite: int = 500) -> list[dict]:
        rows = db.execute(
            text("""SELECT a.id_avistamiento, a.id_persona, a.id_camara, c.nombre AS camara,
                           a.fecha_hora, a.similitud, a.evento, a.bbox
                    FROM reid_avistamientos a
                    LEFT JOIN camaras c ON c.id_camara = a.id_camara
                    WHERE (:emp IS NULL OR a.id_empresa = :emp)
                      AND (:persona IS NULL OR a.id_persona = :persona)
                      AND (:desde IS NULL OR a.fecha_hora >= CAST(:desde AS timestamptz))
                      AND (:hasta IS NULL OR a.fecha_hora <  CAST(:hasta AS timestamptz))
                    ORDER BY a.fecha_hora DESC
                    LIMIT :lim"""),
            {"emp": id_empresa, "persona": id_persona, "desde": desde, "hasta": hasta, "lim": limite},
        ).mappings().all()
        return [dict(r) for r in rows]


reid_service = ReidService()
