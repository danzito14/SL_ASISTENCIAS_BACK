-- 2026_07_camara_tipo_conexion.sql
-- Marca CÓMO se conecta cada cámara (informativo/UX; no cambia cómo se baja el stream):
--   ip_directa → cámara IP con su propia IP (host propio).
--   ip_dvr     → cámara IP detrás de un DVR (host = IP del DVR, propio o heredado del grupo).
--   analogica  → sin IP propia, SOLO por el DVR (host heredado del grupo + canal del DVR).
-- Sirve para que el front guíe la config, para saber que la analógica es baja resolución
-- (no apta para caras → solo cuerpo/conteo) y para futuros auto-ajustes (sub-stream, defaults).
-- Idempotente.
ALTER TABLE camaras ADD COLUMN IF NOT EXISTS tipo_conexion VARCHAR(12) NOT NULL DEFAULT 'ip_directa';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_camara_tipo_conexion') THEN
        ALTER TABLE camaras ADD CONSTRAINT chk_camara_tipo_conexion
            CHECK (tipo_conexion IN ('ip_directa', 'ip_dvr', 'analogica'));
    END IF;
END $$;
