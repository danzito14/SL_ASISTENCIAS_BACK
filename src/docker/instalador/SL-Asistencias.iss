; SL-Asistencias.iss — Instalador VISUAL (wizard .exe) del kiosko de escritorio.
; Se compila con Inno Setup 6.x (gratis: https://jrsoftware.org/isinfo.php).
;   1) Instala Inno Setup Compiler.  2) Abre este .iss.  3) Build → genera el .exe.
;
; El wizard:
;   · Verifica Docker (NO lo instala): si falta, muestra aviso y se detiene.
;   · Pide URL de la nube + usuario/clave de kiosko + empresa (página gráfica).
;   · Empaqueta el motor (compose + instalar.ps1 + init.sql + roles) en {app}.
;   · Corre instalar.ps1 con esos datos (genera .env con secretos, baja imágenes y el
;     modelo, levanta el stack, baja el padrón).
;   · (Opcional, cuando el front esté listo) descarga/instala el Electron + autostart.

#define AppName    "SL Asistencias - Kiosko"
#define AppVersion "1.0.0"
#define Publisher  "SL Agricola"
; Namespace de las imagenes publicas en GHCR (debe coincidir con lo publicado):
#define Registry   "ghcr.io/danzito14"
; URL del instalador del FRONT (Electron, GitHub Release). Vacio = se omite el paso.
#define FrontUrl   "https://github.com/danzito14/FP_ESCANER_FRONT/releases/download/Desktop/SL-Asistencias-Estacion-0.2.4-setup.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\SL Asistencias
DefaultGroupName=SL Asistencias
OutputBaseFilename=SL-Asistencias-Instalador
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
DisableProgramGroupPage=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
; Motor del backend (se instala en {app}). init.sql/roles viven en la carpeta docker padre.
Source: "docker-compose.desktop.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "instalar.ps1";               DestDir: "{app}"; Flags: ignoreversion
Source: "..\init.sql";                DestDir: "{app}"; Flags: ignoreversion
Source: "..\roles_microservicio.sql"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  DatosPage: TInputQueryWizardPage;

// ── Detección de Docker (no instala; solo verifica que responda) ──────────────
function DockerDisponible(): Boolean;
var
  Code: Integer;
begin
  Result := Exec('cmd.exe', '/C docker info', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not DockerDisponible() then
  begin
    MsgBox('Falta Docker instalado (o no está corriendo) en tu computadora.' + #13#10 + #13#10 +
           'Instala Docker Desktop, ábrelo y espera a que diga "Running";' + #13#10 +
           'luego vuelve a ejecutar este instalador.',
           mbCriticalError, MB_OK);
    Result := False;
  end;
end;

// ── Página gráfica con los datos de la empresa ───────────────────────────────
procedure InitializeWizard();
begin
  DatosPage := CreateInputQueryPage(wpWelcome,
    'Configuración de la estación',
    'Datos de conexión (te los da tu administrador)',
    'Estos datos NO se guardan en las imágenes; quedan solo en esta PC.');
  DatosPage.Add('URL de la nube (ej. https://tu-dominio/api):', False);
  DatosPage.Add('Usuario del kiosko:', False);
  DatosPage.Add('Contraseña del kiosko:', True);
  DatosPage.Add('ID de empresa:', False);
  DatosPage.Add('Tipo (campo | oficina | empaque | mixto):', False);
  DatosPage.Values[4] := 'oficina';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DatosPage.ID then
  begin
    if (Trim(DatosPage.Values[0]) = '') or (Trim(DatosPage.Values[1]) = '') or
       (Trim(DatosPage.Values[2]) = '') or (Trim(DatosPage.Values[3]) = '') then
    begin
      MsgBox('Completa la URL, el usuario, la contraseña y la empresa.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

// ── Ejecuta el motor (instalar.ps1) tras copiar los archivos ─────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Tipo, Params: String;
begin
  if CurStep = ssPostInstall then
  begin
    // Barra indeterminada (marquee) DENTRO del wizard: el trabajo pesado (docker pull,
    // modelo, up) no reporta % fino, pero así el usuario ve actividad sin abrir terminal.
    WizardForm.ProgressGauge.Style := npbstMarquee;
    Tipo := Trim(DatosPage.Values[4]);
    if Tipo = '' then Tipo := 'oficina';
    WizardForm.StatusLabel.Caption :=
      'Configurando el backend (Docker, imágenes, modelo y arranque). Puede tardar varios minutos...';
    Params :=
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\instalar.ps1') + '"' +
      ' -CloudUrl "'      + Trim(DatosPage.Values[0]) + '"' +
      ' -KioskUser "'     + Trim(DatosPage.Values[1]) + '"' +
      ' -KioskPassword "' + DatosPage.Values[2]       + '"' +
      ' -Empresa "'       + Trim(DatosPage.Values[3]) + '"' +
      ' -Tipo "'          + Tipo                       + '"' +
      ' -Registry "{#Registry}" -Version "{#AppVersion}"';
    // SW_HIDE: sin ventana de PowerShell. El detalle queda en {app}\instalar.log.
    if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      MsgBox('No se pudo iniciar la configuración del backend (PowerShell).', mbError, MB_OK)
    else if Code <> 0 then
      MsgBox('La configuración del backend terminó con avisos (código ' + IntToStr(Code) + ').' + #13#10 +
             'Detalle en: ' + ExpandConstant('{app}\instalar.log'), mbInformation, MB_OK);

    // ── PASO DEL FRONT (Electron) — activo porque #define FrontUrl no está vacío ──
    // Descarga el instalador del front, le quita la "marca de internet" (para que
    // SmartScreen NO vuelva a preguntar al lanzarlo desde aquí) y lo ejecuta. Como este
    // instalador ya corre elevado, el del front hereda la elevación (sin 2º UAC).
    // Alternativa: incrustar el .exe con Source: en [Files] y ejecutarlo desde {app}.
#if FrontUrl != ""
    WizardForm.StatusLabel.Caption := 'Descargando e instalando la aplicación SL Asistencias...';
    try
      DownloadTemporaryFile('{#FrontUrl}', 'front-setup.exe', '', nil);
      // Unblock-File: elimina Zone.Identifier → evita el 2º aviso de SmartScreen.
      Exec('powershell.exe',
        '-NoProfile -Command "Unblock-File -LiteralPath ''' + ExpandConstant('{tmp}\front-setup.exe') + '''"',
        '', SW_HIDE, ewWaitUntilTerminated, Code);
      if not Exec(ExpandConstant('{tmp}\front-setup.exe'), '', '', SW_SHOW, ewWaitUntilTerminated, Code) then
        MsgBox('No se pudo ejecutar el instalador de la aplicación (front).', mbError, MB_OK);
    except
      MsgBox('No se pudo descargar la aplicación (front) desde el enlace.' + #13#10 +
             'Verifica tu conexión a internet e inténtalo de nuevo.', mbError, MB_OK);
    end;
#endif
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

[Icons]
; Acceso directo para reabrir/arrancar el stack (útil para soporte).
Name: "{group}\Arrancar kiosko (backend)"; Filename: "powershell.exe"; \
  Parameters: "-NoProfile -Command ""docker compose -f '{app}\docker-compose.desktop.yml' --env-file '{app}\.env' up -d"""; \
  WorkingDir: "{app}"

; TODO front + autostart (cuando esté el .exe del front):
;   Name: "{userstartup}\SL Asistencias"; Filename: "{app}\<front>.exe"
