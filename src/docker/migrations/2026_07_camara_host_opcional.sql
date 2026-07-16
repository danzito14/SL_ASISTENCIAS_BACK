-- 2026_07_camara_host_opcional.sql
-- El GRUPO DVR carga la IP (grupos_dvr.host); una cámara que deje camaras.host en NULL
-- HEREDA la IP de su grupo (+ su canal). Así las cámaras detrás de un DVR solo ponen su
-- canal y el grupo aporta la IP+credenciales; mover una cámara de grupo la reapunta al DVR.
-- Las cámaras IP directas siguen poniendo su propio host (que gana sobre el del grupo).
-- Idempotente (DROP NOT NULL no falla si ya es nullable).
ALTER TABLE camaras ALTER COLUMN host DROP NOT NULL;
