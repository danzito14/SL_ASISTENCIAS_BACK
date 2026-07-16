# Plantilla: dar de alta un terminal/cámara en `vigilancia`

Guía reutilizable para conectar CUALQUIER terminal IP (Hikvision u otro con ISAPI) al
microservicio `vigilancia`. Sirve para el actual (DS-K1T502) y para modelos nuevos
(p.ej. DS-K1T342MFWX). Reemplaza los `<PLACEHOLDERS>`.

```
<IP>        = IP del terminal            (ej. 192.168.12.194)
<USER>:<PW> = credenciales admin ISAPI    (ej. admin:gembel2015*t)
<EMPRESA>   = id_empresa                  (acota el roster que reconoce el scanner)
<PUERTA>    = id_puerta                   (de dónde es la asistencia; OBLIGATORIO para fichar)
<CANAL>     = canal ISAPI                 (101 = cam1 main; 102 = sub)
```
> En PowerShell usa `curl.exe` y comillas **simples** para passwords con `!`/`*`.
> El terminal responde HTTP por LAN aunque su RTSP NO se decodifique (usamos snapshot ISAPI, no RTSP).

---

## 1. Conectividad + snapshot (¿la cámara sirve para reconocer?)
```bash
curl.exe --digest -u '<USER>:<PW>' "http://<IP>/ISAPI/Streaming/channels/<CANAL>/picture" -o test.jpg
```
Debe bajar un JPEG. Párate CERCA/de frente: la cara debe salir grande (≥~100px) y frontal.
De lejos no detecta. (El motor real mide con `motor.detectar_y_extraer`: faceW, det_score, pose.)

## 2. Capacidades del terminal (define la estrategia)
```bash
curl.exe --digest -u '<USER>:<PW>' "http://<IP>/ISAPI/AccessControl/capabilities" | findstr /I "FingerPrint FDLib FaceCompare RemoteControlDoor SupplementLight"
curl.exe --digest -u '<USER>:<PW>' "http://<IP>/ISAPI/System/capabilities"        | findstr /I "mqtt"
curl.exe --digest -u '<USER>:<PW>' "http://<IP>/ISAPI/Event/triggers"             # VMD (movimiento), etc.
```
Interpreta:
- `isSupportFDLib=true` → **terminal de CARA** (MinMoe): la gente MIRA la cámara al autenticar →
  el timing se resuelve casi solo, y el evento suele **adjuntar la foto** (`pictureURLType=binary`) →
  úsala directo. `false` → autentica por huella/tarjeta (pasa y se va) → el snapshot debe ser inmediato/ráfaga.
- `isSupportFingerPrintCfg=true` → tiene lector de huella → sus eventos `minor=38` traen `name`.
- `mqtt` presente → **la mejor opción** (tiempo real, sin replay); si no aparece, no hay MQTT.
- `isSupportRemoteControlDoor=true` → se puede abrir puerta (Fase 3).

## 3. Elegir el modo de captura
| Situación | Modo | Por qué |
|---|---|---|
| Terminal con **historial grande** de eventos ya acumulado | **POLL** (`modo_captura='evento'`) | El PUSH replica TODO el backlog FIFO y sepulta lo vivo. El poll arranca desde "ahora". |
| Terminal **NUEVO** (log vacío) + webhook siempre-arriba + IP fija + NTP | **HOOK** (push) posible | Sin backlog acumulado, el push entrega en tiempo real. Menor latencia que el poll. |
| Cámara común sin eventos de acceso | **SONDEO** (`modo_captura='sondeo'`) | Snapshot periódico + gate de movimiento. |

> Hoy el poll es el default seguro y **agnóstico al hardware**. El hook conviene solo en
> terminal nuevo con las 3 condiciones (log vacío, servicio 24/7, IP fija).

## 4. Sincronizar reloj (NTP) — OBLIGATORIO
El reloj del terminal debe estar en hora (uno traía 7.5h de atraso → rompía el filtro de frescura).
Verifica: `curl.exe --digest -u '<USER>:<PW>' "http://<IP>/ISAPI/System/time"`. Activa NTP en el equipo.

## 5. Alta de la cámara en la BD (credencial CIFRADA)
Preferido: por el API del micro `POST /vigilancia/camaras` (cifra la credencial solo). Manual:
```bash
# cifrar la password con la llave Fernet del .env (VIGILANCIA_SECRET_KEY):
HEX=$(docker run --rm -e KEY="<VIGILANCIA_SECRET_KEY>" sl-vigilancia:latest \
  python -c "import os;from cryptography.fernet import Fernet;print(Fernet(os.environ['KEY']).encrypt(b'<PW>').hex())")
docker exec fe_postgres psql -U root -d SL_ASISTENCIAS -c "
  INSERT INTO camaras (nombre,id_empresa,id_puerta,marca,host,puerto,canal,usuario,
                       credencial_cifrada,tipo_camara,tipo_registro,modo_captura,habilitada,
                       gap_muestreo_seg,umbral_movimiento,cooldown_seg,estado)
  VALUES ('Terminal <lugar>',<EMPRESA>,<PUERTA>,'hikvision','<IP>',80,<CANAL>,'<USER>',
          decode('$HEX','hex'),'asistencia','entrada','evento',true,1.0,4.0,8,'activo');"
```
Cuenta de servicio para el scanner (rol `vigilancia_edge`, una por empresa):
`./crear_vigilancia_edge.sh <EMPRESA> <usuario> [pass]`

## 6. (Solo HOOK) configurar el push del terminal → webhook
```bash
# Host 1 → IP LAN de la máquina del webhook (FIJA) : puerto WEBHOOK_PORT (9080). Suscribe AccessControllerEvent.
curl.exe --digest -u '<USER>:<PW>' -X PUT "http://<IP>/ISAPI/Event/notification/httpHosts/1" \
  -H "Content-Type: application/xml" --data-binary "@host1_on.xml"
```
Requisitos para que el push NO se rompa (lecciones aprendidas):
- **IP fija/reserva DHCP** en la máquina del webhook (cambió `.11`→`.12` y apuntaba a IP muerta).
- En Docker Desktop/Windows verifica que el puerto responda en la **IP LAN**, no solo `localhost`:
  `curl http://<ip-lan>:9080/` debe dar 200.
- **Webhook 24/7 suscrito** para que los eventos no se acumulen y te repliquen el backlog.
- El parser del webhook acepta JSON y XML; el filtro de frescura (`WEBHOOK_EVENTO_MAX_EDAD_SEG`)
  descarta eventos viejos comparando su `dateTime` contra ahora (requiere reloj OK).

Para APAGAR el push: `PUT host1_off.xml` (ipAddress 0.0.0.0, portNo 0).

## 7. Verificar el fichaje
```bash
docker logs -f --since 1m sl_vigilancia_capture   # ver 'poller/evento nuevo ... nombre=... → captura' + 'FICHADO'
docker exec fe_postgres psql -U root -d SL_ASISTENCIAS -c \
  "SELECT fecha_hora,id_trabajador,estado_registro,round(confianza_biometrica::numeric,3) \
   FROM escaneos WHERE id_puerta=<PUERTA> ORDER BY fecha_hora DESC LIMIT 5;"
```

---

## Cómo funciona (misma tubería sea hook o poll)
`evento de identificación (name) → snapshot inmediato → POST /scanner/acceso/foto?nombre_hint=<name>
→ recognition ACOTA la búsqueda facial por nombre (unaccent, quita roles; umbral 0.40 acotado / 0.50 total)
→ match → el back registra la asistencia`. `vigilancia` es DELGADO: NO corre IA ni escribe escaneos.
El `name` del terminal es solo un INDICIO para reducir el universo; si no cuadra, cae a búsqueda total.

## Perillas (config.py / env)
| Var | Default | Para qué |
|---|---|---|
| `CAP_POLL_INTERVAL_SEG` | 2.0 | cada cuánto el poll consulta el log del terminal (bajar a ~1 = menos latencia) |
| `CAP_POLL_LOOKBACK_SEG` | 30 | ventana hacia atrás de la búsqueda de eventos |
| `WEBHOOK_TRIGGER_SUBTYPES` | 38 | subEventType(s) que disparan (38 = identificación con nombre) |
| `WEBHOOK_EVENTO_MAX_EDAD_SEG` | 120 | (hook) descarta eventos más viejos que esto = backlog |
| `SCANNER_USAR_LIVENESS` | true | multi-frame anti-spoof; en modo evento se fuerza 1 frame inmediato |
| `SIMILITUD_UMBRAL` / `_ACOTADO` | 0.50 / 0.40 | umbral coseno búsqueda total / acotada por nombre (recognition/motor.py) |

## Tropiezos conocidos (por qué está así)
1. **Backlog FIFO:** el DS-K1T502 tenía 132k eventos; el push los replica todos en orden y sepulta lo vivo.
   No hay API ISAPI para limpiar la cola → por eso el **poll** (arranca desde "ahora", dedupe por `serialNo`).
2. **IP por DHCP** cambió → el push apuntaba a IP muerta. Usa IP fija.
3. **Reloj** 7.5h atrasado → NTP.
4. **MQTT** no soportado en firmware V1.9.1 (endpoints 404).
5. El ISAPI `AcsEvent` exige `startTime/endTime` a **segundos sin microsegundos** (si no, HTTP 400).
6. `docker cp`/`exec` con rutas `/contenedor` en Git Bash: usar `MSYS_NO_PATHCONV=1`.
