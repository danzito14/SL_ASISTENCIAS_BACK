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
; Version del INSTALADOR: subela en CADA build (aunque solo cambie el compose o el .ps1).
; Va en el nombre del .exe, asi distingues que build tiene cada estacion.
#define AppVersion "1.1.2"
; Tag de las IMAGENES en GHCR: subelo SOLO cuando republiques imagenes con
; publicar-imagenes.ps1 -Version <tag>. Si pones un tag no publicado, el pull falla.
; Va aparte de AppVersion a proposito: cambios de compose/instalador NO tocan imagenes.
#define ImgVersion "1.0.2"
#define Publisher  "SL Agricola"
; Namespace de las imagenes publicas en GHCR (debe coincidir con lo publicado):
#define Registry   "ghcr.io/danzito14"
; URL del instalador del FRONT (Electron, GitHub Release). Vacio = se omite el paso.
#define FrontUrl   "https://github.com/danzito14/FP_ESCANER_FRONT/releases/download/0.2.6/SL-Asistencias-Estacion-0.2.6-setup.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\SL Asistencias
DefaultGroupName=SL Asistencias
OutputBaseFilename=SL-Asistencias-Instalador-{#AppVersion}
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
  LogMemo: TNewMemo;

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

  // Cuadro de LOGS bajo la barra de progreso (se llena en vivo durante la instalación).
  LogMemo := TNewMemo.Create(WizardForm);
  LogMemo.Parent := WizardForm.InstallingPage;
  LogMemo.Left := WizardForm.ProgressGauge.Left;
  LogMemo.Top := WizardForm.ProgressGauge.Top + WizardForm.ProgressGauge.Height + ScaleY(8);
  LogMemo.Width := WizardForm.ProgressGauge.Width;
  LogMemo.Height := ScaleY(170);
  LogMemo.ScrollBars := ssVertical;
  LogMemo.ReadOnly := True;
  LogMemo.Font.Name := 'Consolas';
  LogMemo.Visible := False;
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
  Code, Tries: Integer;
  Tipo, Params: String;
  MarkerText: AnsiString;
begin
  if CurStep = ssPostInstall then
  begin
    // Barra indeterminada (marquee) DENTRO del wizard: el trabajo pesado (docker pull,
    // modelo, up) no reporta % fino, pero así el usuario ve actividad sin abrir terminal.
    WizardForm.ProgressGauge.Style := npbstMarquee;
    Tipo := Trim(DatosPage.Values[4]);
    if Tipo = '' then Tipo := 'oficina';
    WizardForm.StatusLabel.Caption :=
      'Configurando el backend (Docker, imágenes, modelo). Puede tardar varios minutos...';
    LogMemo.Visible := True;
    LogMemo.Text := '';
    DeleteFile(ExpandConstant('{app}\instalar.done'));
    Params :=
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\instalar.ps1') + '"' +
      ' -CloudUrl "'      + Trim(DatosPage.Values[0]) + '"' +
      ' -KioskUser "'     + Trim(DatosPage.Values[1]) + '"' +
      ' -KioskPassword "' + DatosPage.Values[2]       + '"' +
      ' -Empresa "'       + Trim(DatosPage.Values[3]) + '"' +
      ' -Tipo "'          + Tipo                       + '"' +
      ' -Registry "{#Registry}" -Version "{#ImgVersion}"';
    // ewNoWait: corre OCULTO y SIN bloquear, para volcar el log en el memo mientras avanza.
    if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_HIDE, ewNoWait, Code) then
      MsgBox('No se pudo iniciar la configuración del backend (PowerShell).', mbError, MB_OK)
    else
    begin
      Tries := 0;
      // Sondea el marcador de fin; entretanto refresca el log bajo la barra (~cada 0.5 s).
      while (not FileExists(ExpandConstant('{app}\instalar.done'))) and (Tries < 3600) do
      begin
        Sleep(500);
        Tries := Tries + 1;
        if FileExists(ExpandConstant('{app}\instalar.log')) then
          try
            LogMemo.Lines.LoadFromFile(ExpandConstant('{app}\instalar.log'));
            LogMemo.Update;
          except
          end;
      end;
      try LogMemo.Lines.LoadFromFile(ExpandConstant('{app}\instalar.log')); except end;
      MarkerText := '';
      LoadStringFromFile(ExpandConstant('{app}\instalar.done'), MarkerText);
      if Pos('ERROR', MarkerText) = 1 then
        MsgBox('La configuración del backend falló:' + #13#10 + String(MarkerText) + #13#10 + #13#10 +
               'Detalle en: ' + ExpandConstant('{app}\instalar.log'), mbError, MB_OK);
    end;

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
