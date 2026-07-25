# kiosk_local/services/Roster_Loader.py
# Toma el roster que devuelve la nube (offline_sync) y lo UPSERTea en el postgres LOCAL
# (mismo esquema init.sql, con pgvector). Inserta en orden de FKs: empresa → áreas →
# puertas → trabajadores → embeddings. Idempotente (ON CONFLICT). Tras esto, el kiosko
# reconoce OFFLINE con el mismo motor/consulta pgvector que prod.
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings

logger = logging.getLogger(__name__)

# Tabla local-only para guardar la versión del roster y la última sync.
_META = text("""
    CREATE TABLE IF NOT EXISTS kiosk_meta (
        clave TEXT PRIMARY KEY, valor TEXT, actualizado TIMESTAMPTZ DEFAULT NOW()
    )
""")

# Reemplazo TOTAL del padrón local: vacía trabajadores + embeddings antes de recargar,
# para que la estación quede SOLO con la empresa/tipo que se baja ahora. Objetivo del
# local-first: pocos rostros que buscar = búsqueda pgvector más rápida y precisa. Al
# cambiar de empresa (fin de temporada, etc.) NO deben quedar rostros residuales.
# SEGURO para la cola de subida: 'escaneos.id_trabajador' es enlace SUAVE (sin FK) y NO
# se tocan 'puertas' (que sí referencian escaneos), así que los fichajes pendientes de
# subir se conservan. Se borra embeddings primero (hijo de trabajadores por FK).
_WIPE_EMB = text("DELETE FROM embeddings")
_WIPE_TRAB = text("DELETE FROM trabajadores")
_SET_META = text("""
    INSERT INTO kiosk_meta (clave, valor) VALUES (:clave, :valor)
    ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = NOW()
""")

# La empresa no viene en el roster; se crea mínima (nombre_empresa + zona_horaria NOT NULL).
_UP_EMPRESA = text("""
    INSERT INTO empresas (id_empresa, nombre_empresa, zona_horaria)
    VALUES (:id, :nombre, :tz)
    ON CONFLICT (id_empresa) DO NOTHING
""")
_UP_AREA = text("""
    INSERT INTO area_trabajo (id_area, nombre_area, tipo_area, id_empresa, ubicacion)
    VALUES (:id, :nombre, :tipo, :empresa,
            CASE WHEN :geojson IS NULL THEN NULL
                 ELSE CAST(ST_GeomFromGeoJSON(:geojson) AS geography) END)
    ON CONFLICT (id_area) DO UPDATE SET
        nombre_area = EXCLUDED.nombre_area, tipo_area = EXCLUDED.tipo_area,
        id_empresa = EXCLUDED.id_empresa, ubicacion = EXCLUDED.ubicacion
""")
_UP_PUERTA = text("""
    INSERT INTO puertas_acceso (id_puerta, nombre_puerta, tipo_puerta, id_area, id_empresa, funcion_puerta)
    VALUES (:id, :nombre, CAST(:tipo AS tipo_puerta), :area, :empresa, 'asistencia')
    ON CONFLICT (id_puerta) DO UPDATE SET
        nombre_puerta = EXCLUDED.nombre_puerta, tipo_puerta = EXCLUDED.tipo_puerta,
        id_area = EXCLUDED.id_area, id_empresa = EXCLUDED.id_empresa
""")
_UP_TRAB = text("""
    INSERT INTO trabajadores (id_trabajador, id_emp, origen_nomina, nombre, apellido,
                              id_area, id_empresa, permiso_escaneo, estado)
    VALUES (:id, :id_emp, :origen, :nombre, :apellido, :area, :empresa,
            CAST(:permiso AS permiso_escaneo), 'activo')
    ON CONFLICT (id_trabajador) DO UPDATE SET
        id_emp = EXCLUDED.id_emp, origen_nomina = EXCLUDED.origen_nomina,
        nombre = EXCLUDED.nombre, apellido = EXCLUDED.apellido, id_area = EXCLUDED.id_area,
        id_empresa = EXCLUDED.id_empresa, permiso_escaneo = EXCLUDED.permiso_escaneo,
        estado = 'activo', fecha_actualizacion = NOW()
""")
_UP_EMB = text("""
    INSERT INTO embeddings (id_trabajador, vector_embedding, tipo_embedding, calidad_embedding, modelo_ia, estado)
    VALUES (:trab, CAST(:vec AS vector), 'facial', :calidad, :modelo, 'activo')
    ON CONFLICT (id_trabajador) DO UPDATE SET
        vector_embedding = EXCLUDED.vector_embedding, calidad_embedding = EXCLUDED.calidad_embedding,
        modelo_ia = EXCLUDED.modelo_ia, estado = 'activo', fecha_captura = NOW()
""")


class RosterLoader:

    def cargar(self, db: Session, roster: dict, reemplazar: bool = True) -> dict:
        empresa = roster["empresa"]
        db.execute(_META)
        # Reemplazo total (default): vacía el padrón local antes de recargar, para que
        # quede SOLO la empresa/tipo que se baja ahora (sin rostros residuales de otras
        # empresas que ensucien/ralenticen la lectura). Todo en la MISMA transacción: si
        # la carga falla, el rollback deja el padrón anterior intacto. La cola de escaneos
        # NO se toca (enlace suave + no se borran puertas). reemplazar=False = merge (UPSERT).
        if reemplazar:
            db.execute(_WIPE_EMB)
            db.execute(_WIPE_TRAB)
        db.execute(_UP_EMPRESA, {"id": empresa, "nombre": f"Empresa {empresa}", "tz": settings.KIOSK_TZ})

        for a in roster.get("areas", []):
            db.execute(_UP_AREA, {"id": a["id_area"], "nombre": a["nombre_area"],
                                  "tipo": a.get("tipo_area"), "empresa": empresa,
                                  "geojson": a.get("poligono_geojson")})
        for p in roster.get("puertas", []):
            db.execute(_UP_PUERTA, {"id": p["id_puerta"], "nombre": p["nombre_puerta"],
                                    "tipo": p.get("tipo_puerta") or "campo",
                                    "area": p.get("id_area"), "empresa": empresa})

        n_trab = n_emb = 0
        for t in roster.get("trabajadores", []):
            db.execute(_UP_TRAB, {
                "id": t["id_trabajador"], "id_emp": t.get("id_emp"), "origen": t.get("origen_nomina"),
                "nombre": t["nombre"], "apellido": t["apellido"], "area": t["id_area"],
                "empresa": empresa, "permiso": t.get("permiso_escaneo") or "campo",
            })
            n_trab += 1
            emb = t.get("embedding") or []
            if len(emb) == settings.EMBEDDING_DIM:
                vec = "[" + ",".join(repr(float(x)) for x in emb) + "]"
                db.execute(_UP_EMB, {"trab": t["id_trabajador"], "vec": vec,
                                     "calidad": t.get("calidad"), "modelo": t.get("modelo_ia")})
                n_emb += 1

        db.execute(_SET_META, {"clave": "roster_version", "valor": roster.get("roster_version")})
        db.execute(_SET_META, {"clave": "empresa", "valor": str(empresa)})
        db.execute(_SET_META, {"clave": "tipo", "valor": roster.get("tipo")})
        db.commit()

        res = {"empresa": empresa, "tipo": roster.get("tipo"),
               "roster_version": roster.get("roster_version"),
               "trabajadores": n_trab, "embeddings": n_emb,
               "areas": len(roster.get("areas", [])), "puertas": len(roster.get("puertas", []))}
        logger.info("roster cargado en BD local: %s", res)
        return res


roster_loader = RosterLoader()
