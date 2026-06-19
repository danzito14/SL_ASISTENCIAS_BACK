-- ============================================================
-- Seed de roles base
-- ============================================================
-- Permisos = JSONB con la forma {"scopes": [...]}.
-- Un scope concedido puede ser:
--   "*"              -> todo (cualquier recurso y acción)
--   "recurso:*"      -> cualquier acción sobre ese recurso
--   "*:accion"       -> esa acción en cualquier recurso (read | write | delete)
--   "recurso:accion" -> exacto (ej. "trabajadores:write")
-- El scanner es un caso aparte: exige el scope especial "scanner:use".
--
-- Acciones por método HTTP: GET=read, POST/PUT/PATCH=write, DELETE=delete.
-- Recursos actuales (prefijo de cada router):
--   roles, usuarios, empresas, areas, trabajadores, puertas, dispositivos,
--   asistencias, escaneos, incidencias, embeddings, scanner
--
-- Idempotente: si el rol ya existe (nombre_rol es UNIQUE) no hace nada.
-- ============================================================

INSERT INTO roles (nombre_rol, descripcion, permisos, estado) VALUES
    (
        'consultor',
        'Solo lectura: puede consultar todos los recursos, sin crear, editar ni borrar.',
        '{"scopes": ["*:read"]}'::jsonb,
        'activo'
    ),
    (
        'operador',
        'Operador: lee y crea/edita todos los recursos y usa el scanner. No puede borrar.',
        '{"scopes": ["*:read", "*:write", "scanner:use"]}'::jsonb,
        'activo'
    ),
    (
        'administrador',
        'Administrador total: acceso completo (lectura, escritura, borrado y scanner).',
        '{"scopes": ["*"]}'::jsonb,
        'activo'
    ),
    (
        'kiosko',
        'Dispositivo/kiosko: solo scanner:use. Ese scope ya implica leer puertas y dispositivos (de su empresa) para seleccionarlos. Nada más.',
        '{"scopes": ["scanner:use"]}'::jsonb,
        'activo'
    )
ON CONFLICT (nombre_rol) DO NOTHING;


-- ============================================================
-- Roles especiales (granulares por recurso)
-- ============================================================
-- IMPORTANTE: el modelo de permisos solo distingue 3 acciones:
--   read  (GET)            -> "ver/consultar"
--   write (POST/PUT/PATCH) -> "agregar" Y "editar" (no se pueden separar)
--   delete (DELETE)        -> "borrar"
-- Por eso cada recurso tiene 3 niveles: consulta / gestion / admin.
-- Idempotente: ON CONFLICT evita duplicar si ya existen.
-- ============================================================

INSERT INTO roles (nombre_rol, descripcion, permisos, estado) VALUES
    -- ── Usuarios ──────────────────────────────────────────────────────────
    (
        'usuarios_consulta',
        'Ver usuarios (solo lectura).',
        '{"scopes": ["usuarios:read"]}'::jsonb,
        'activo'
    ),
    (
        'usuarios_gestion',
        'Agregar y editar usuarios (ver + crear/editar, sin borrar).',
        '{"scopes": ["usuarios:read", "usuarios:write"]}'::jsonb,
        'activo'
    ),
    (
        'usuarios_admin',
        'Gestión total de usuarios (ver, crear/editar y borrar).',
        '{"scopes": ["usuarios:read", "usuarios:write", "usuarios:delete"]}'::jsonb,
        'activo'
    ),

    -- ── Roles ─────────────────────────────────────────────────────────────
    (
        'roles_consulta',
        'Ver roles (solo lectura).',
        '{"scopes": ["roles:read"]}'::jsonb,
        'activo'
    ),
    (
        'roles_gestion',
        'Agregar y editar roles (ver + crear/editar, sin borrar).',
        '{"scopes": ["roles:read", "roles:write"]}'::jsonb,
        'activo'
    ),
    (
        'roles_admin',
        'Gestión total de roles (ver, crear/editar y borrar).',
        '{"scopes": ["roles:read", "roles:write", "roles:delete"]}'::jsonb,
        'activo'
    ),

    -- ── RRHH: trabajadores + rostros (embeddings) ─────────────────────────
    -- La captura de rostro vive bajo /trabajadores, por eso necesita
    -- trabajadores:write además de embeddings. areas:read para asignar área.
    (
        'rrhh',
        'Recursos Humanos: gestiona trabajadores y sus rostros (alta/edición). No borra.',
        '{"scopes": ["trabajadores:read", "trabajadores:write", "embeddings:read", "embeddings:write", "areas:read"]}'::jsonb,
        'activo'
    ),

    -- ── Supervisor: revisa asistencias e incidencias ──────────────────────
    (
        'supervisor',
        'Supervisor: consulta asistencias y revisa/justifica incidencias (sin borrar).',
        '{"scopes": ["asistencias:read", "incidencias:read", "incidencias:write", "trabajadores:read"]}'::jsonb,
        'activo'
    ),

    -- ── Configuración / infraestructura ───────────────────────────────────
    (
        'configuracion',
        'Configuración: gestiona empresas, áreas, puertas y dispositivos (sin borrar).',
        '{"scopes": ["empresas:read", "empresas:write", "areas:read", "areas:write", "puertas:read", "puertas:write", "dispositivos:read", "dispositivos:write"]}'::jsonb,
        'activo'
    ),

    -- ── Reportes: solo lectura para tableros/exportes ─────────────────────
    (
        'reportes',
        'Reportes: descarga/consulta de asistencias, incidencias, intentos, escaneos y trabajadores.',
        '{"scopes": ["reportes:read", "asistencias:read", "incidencias:read", "intentos:read", "escaneos:read", "trabajadores:read"]}'::jsonb,
        'activo'
    )
ON CONFLICT (nombre_rol) DO NOTHING;

