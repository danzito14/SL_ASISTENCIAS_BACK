# vigilancia/core/config.py
# Microservicio de asistencia por reconocimiento facial desde cámaras/terminales IP.
# A DIFERENCIA de offline_sync, este servicio SIEMPRE está en red (online): captura,
# reconoce y registra en tiempo real. No hay buffering/ingesta por lotes.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── PostgreSQL — vigilancia corre como svc_vigilancia ─────────────────────
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Vigilancia Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # ── Scanner del back (reusa recognition + registra asistencia) ────────────
    # vigilancia es DELGADO: manda los frames capturados al scanner del back por el
    # GATEWAY (POST /scanner/acceso/foto|liveness) y solo procesa el ScanResponse.
    # El scanner exige scanner:use → el motor de captura se loguea como cuenta de
    # servicio (rol vigilancia_edge) en identity y cachea el token (refresca en 401).
    SCANNER_BASE_URL:            str = "http://localhost:8000"  # gateway: /usuarios/login + /scanner/*
    VIGILANCIA_SERVICE_USER:     str = ""
    VIGILANCIA_SERVICE_PASSWORD: str = ""
    SCANNER_TIMEOUT:             float = 20.0
    # Multi-frame anti-spoof: true → /scanner/acceso/liveness con N frames;
    # false → /scanner/acceso/foto (1 frame).
    SCANNER_USAR_LIVENESS: bool = True
    CAP_FRAMES_LIVENESS:   int = 3     # frames por disparo cuando hay liveness (2-5)
    # Ventana ACTIVA tras detectar movimiento: sigue enviando frames al scanner
    # (aunque el sujeto se quede quieto) hasta lograr match o agotar la ventana.
    CAP_VENTANA_ACTIVA_SEG: float = 4.0
    CAP_MIN_GAP_ENVIO_SEG:  float = 3.0   # mínimo entre envíos al scanner (no saturar el terminal)
    CAP_RECONCILE_SEG:      float = 20.0  # cada cuánto el supervisor re-lee las cámaras
    CAP_SNAPSHOT_TIMEOUT:   float = 10.0  # timeout de cada snapshot ISAPI (terminales lentos)

    # ── Captura por EVENTO (webhook del terminal) ─────────────────────────────
    # El terminal (Hikvision httpHosts) POSTea sus eventos a este puerto en la LAN;
    # el webhook mapea el evento a su cámara (por IP), y en los subEventType de "cara"
    # dispara: baja snapshot → scanner → asistencia. Reemplaza el sondeo (sin timeouts).
    WEBHOOK_PORT:             int = 9080    # puerto LAN donde el terminal POSTea
    WEBHOOK_TOKEN:            str = ""      # si != "", el terminal debe POSTear a /webhook/<token>
    WEBHOOK_TRIGGER_SUBTYPES: str = "38"    # subEventType(s) que disparan el escaneo (coma). Tuneable.
    WEBHOOK_COOLDOWN_SEG:     float = 8.0   # mínimo entre escaneos por cámara (dedupe)
    # Qué desenlaces del scanner se PERSISTEN en eventos_camara (los demás solo al log).
    # Por defecto solo match/spoof: evita inundar la bitácora con no_rostro/no_match.
    CAP_EVENTOS_SCAN: str = "match,spoof"

    # ── Captura por EVENTO vía POLL del log del terminal (ISAPI AcsEvent) ──────
    # Este Hikvision, con el PUSH (httpHosts), replica TODO su historial (132k eventos)
    # en orden FIFO y SEPULTA los eventos en vivo; además el push depende de que el
    # terminal alcance nuestra IP (se rompió con DHCP) y de fechas (reloj). En su lugar
    # CONSULTAMOS su log de eventos (AcsEvent) cada CAP_POLL_INTERVAL_SEG y actuamos solo
    # sobre los NUEVOS (serialNo mayor al visto al arrancar) → inmune a backlog/IP/reloj.
    CAP_POLL_INTERVAL_SEG: float = 2.0    # cada cuánto se consulta el log de eventos
    CAP_POLL_LOOKBACK_SEG: float = 30.0   # ventana hacia atrás de la búsqueda (holgura)

    # ── Cifrado de credenciales de cámara (Fernet) ────────────────────────────
    # La contraseña de cada terminal se guarda CIFRADA en camaras.credencial_cifrada.
    # Genera la llave con:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    VIGILANCIA_SECRET_KEY: str = ""

    # ── Config interna del supervisor reid ────────────────────────────────────
    # GET /vigilancia/reid/config entrega los grupos_dvr con credenciales DESCIFRADAS
    # (para armar el RTSP) → SOLO INTERNO. Si se fija, el supervisor reid debe mandar
    # el mismo valor en X-Reid-Token. Vacío = no se exige (dev), como GATEWAY_INTERNAL_TOKEN.
    REID_INTERNAL_TOKEN: str = ""

    # ── Recognition (paso del rostro): ancla identidad a la persona del reid ───
    # /reid/identificar manda el recorte a recognition (mismo motor facial de asistencia)
    # y, si reconoce, fija reid_personas.id_trabajador. API interna con token compartido.
    RECOGNITION_URL: str = "http://recognition:8000"
    RECOGNITION_INTERNAL_TOKEN: str = ""
    RECOGNITION_TIMEOUT: float = 40.0

    # ── Auth — el gateway valida el JWT; aquí solo se leen headers X-* y scopes ─
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacío = no se exige
    # DEV/PRUEBA: si es true, guard_scopes NO exige identidad ni scopes (principal
    # super-admin). Solo para probar local sin el gateway. NUNCA en producción.
    AUTH_DISABLED: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def eventos_scan_set(self) -> set[str]:
        return {t.strip() for t in self.CAP_EVENTOS_SCAN.split(",") if t.strip()}

    @property
    def webhook_trigger_set(self) -> set[str]:
        return {t.strip() for t in self.WEBHOOK_TRIGGER_SUBTYPES.split(",") if t.strip()}

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}"
            f"/{self.DB_NAME}"
        )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
