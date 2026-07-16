-- 2026_07_grupo_credencial_camaras.sql
-- Un grupo DVR puede necesitar DOS credenciales: la del DVR (credencial_cifrada, para
-- ISAPI/streaming VÍA el DVR) y la de las CÁMARAS (para acceder a cada cámara IP por su
-- IP DIRECTA, que suele tener otra password). Esta última es opcional. Se usa como
-- fallback del preview de canales IP cuando el DVR no entrega la imagen (RTSP corrupto).
-- Cifrada Fernet, como la otra. Idempotente.
ALTER TABLE grupos_dvr ADD COLUMN IF NOT EXISTS credencial_camaras_cifrada BYTEA;
