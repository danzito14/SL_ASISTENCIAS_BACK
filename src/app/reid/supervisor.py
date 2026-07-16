# reid/supervisor.py — MULTI-CÁMARA. Lee grupos_dvr + camaras del config y lanza un worker
# de tracking (seguimiento.py) por cámara HABILITADA, con su RTSP (credenciales del GRUPO al
# que pertenece), su ROI y su puerto web. Reconcilia cada 15s: arranca nuevas, detiene las
# deshabilitadas, y REINICIA las que se caigan (resuelve también el stream-drop del RTSP).
#
# Config (MISMA forma, venga del archivo o del HTTP):
#   grupos_dvr: [{id, nombre, usuario, password}]   ← credenciales UNA vez por DVR
#   camaras:    [{id, nombre, grupo, host, canal, roi, min_alto, sim_umbral, habilitada}]
#               ← reusan las credenciales de su grupo (no repiten password)
#
# Fuente de la config (en orden):
#   REID_CONFIG_URL  → HTTP GET a vigilancia (GET /vigilancia/reid/config); manda
#                      X-Reid-Token=REID_INTERNAL_TOKEN. El reid NO toca BD ni la llave
#                      Fernet: vigilancia le entrega los grupos con credenciales descifradas.
#   REID_CONFIG      → archivo JSON local (default /salida/reid_config.json), fallback.
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request

CONFIG = os.getenv("REID_CONFIG", "/salida/reid_config.json")
CONFIG_URL = os.getenv("REID_CONFIG_URL", "").strip()
CONFIG_TOKEN = os.getenv("REID_INTERNAL_TOKEN", "").strip()
CONFIG_TIMEOUT = float(os.getenv("REID_CONFIG_TIMEOUT_SEG", "10"))
WEB_BASE = int(os.getenv("REID_WEB_BASE", "8600"))
PANEL_PORT = int(os.getenv("REID_PANEL_PORT", "8599"))   # vista COMBINADA (todas las cámaras)
RECONCILE = float(os.getenv("REID_RECONCILE_SEG", "15"))


# ── Vista en vivo COMBINADA (rejilla con todas las cámaras) ─────────────────────
# Una sola página que embebe el MJPEG de cada worker → ves el seguimiento ENTRE
# cámaras (la misma persona-N global saltando de una a otra) en un solo pantallazo.
# Los <img> apuntan a location.hostname:<puerto> (los puertos de los workers están
# publicados al host), así funciona desde cualquier equipo de la red.
_PANEL = {"camaras": []}   # [{id, nombre, puerto}], actualizado en cada reconcile

_PANEL_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Seguimiento reid — vista en vivo</title>
<style>body{margin:0;background:#111;color:#ccc;font-family:sans-serif}
h1{font-size:15px;padding:8px 12px;margin:0;border-bottom:1px solid #333}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:6px;padding:6px}
figure{margin:0;background:#000;border:1px solid #333;position:relative}
figcaption{position:absolute;top:0;left:0;background:rgba(0,0,0,.6);padding:2px 8px;font-size:13px}
img{width:100%;display:block}.vacio{padding:24px;color:#888}</style></head>
<body><h1>Seguimiento reid — __N__ cámara(s) en vivo</h1><div class="grid" id="g"></div>
<script>
const cams = __CAMS__;
const g = document.getElementById('g');
if(!cams.length){g.innerHTML='<div class=vacio>Sin cámaras activas todavía.</div>';}
for (const c of cams){
  const fig=document.createElement('figure');
  const cap=document.createElement('figcaption');cap.textContent=c.nombre+' (cam '+c.id+')';
  const img=document.createElement('img');
  img.src='http://'+location.hostname+':'+c.puerto+'/stream';
  img.onerror=function(){this.alt='cam '+c.id+' sin señal';};
  fig.appendChild(img);fig.appendChild(cap);g.appendChild(fig);
}
</script></body></html>"""


class _PanelHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cams = list(_PANEL["camaras"])
        html = (_PANEL_HTML.replace("__CAMS__", json.dumps(cams))
                           .replace("__N__", str(len(cams)))).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *a):
        pass


class _PanelServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _correr_panel(port: int) -> None:
    try:
        _PanelServer(("0.0.0.0", port), _PanelHandler).serve_forever()
    except Exception as exc:
        print(f"WARN: no se pudo abrir la vista combinada en :{port} ({exc})", flush=True)


def _leer_config():
    if CONFIG_URL:
        req = urllib.request.Request(CONFIG_URL)
        if CONFIG_TOKEN:
            req.add_header("X-Reid-Token", CONFIG_TOKEN)
        with urllib.request.urlopen(req, timeout=CONFIG_TIMEOUT) as r:
            return json.load(r)
    with open(CONFIG) as f:
        return json.load(f)


def _cargar():
    c = _leer_config()
    grupos = {g["id"]: g for g in c.get("grupos_dvr", [])}
    cams = [cam for cam in c.get("camaras", []) if cam.get("habilitada", True)]
    return grupos, cams


def _rtsp(cam, grupo):
    u, p = grupo.get("usuario", ""), grupo.get("password", "")
    return f"rtsp://{u}:{p}@{cam['host']}:554/Streaming/Channels/{cam.get('canal', 101)}"


def _env(cam, grupo, puerto):
    e = dict(os.environ)   # hereda REID_CONFIG_URL / REID_INTERNAL_TOKEN → galería compartida
    # RTSP sobre TCP como env REAL del worker (además de lo que fija seguimiento.py):
    # este Hikvision/DVR da H.265 y por UDP se corrompe ('PPS id out of range').
    e.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    e["REID_FUENTE"] = _rtsp(cam, grupo)
    e["REID_ROI"] = cam.get("roi", "")
    e["REID_OUT"] = f"/salida/{cam['id']}"
    e["REID_WEB_PORT"] = str(puerto)
    e["REID_MIN_ALTO"] = str(cam.get("min_alto", 180))
    e["REID_SIM_UMBRAL"] = str(cam.get("sim_umbral", 0.75))
    e["REID_CAMARA_ID"] = str(cam["id"])   # identifica la cámara ante el endpoint reid (id global)
    os.makedirs(f"/salida/{cam['id']}/ref", exist_ok=True)
    return e


def main():
    procs = {}       # cam_id -> Popen
    puertos = {}     # cam_id -> puerto web estable
    print("supervisor reid: arrancando (multi-cámara).", flush=True)
    threading.Thread(target=_correr_panel, args=(PANEL_PORT,), daemon=True).start()
    print(f"vista COMBINADA en http://<IP-de-la-maquina>:{PANEL_PORT}/", flush=True)
    while True:
        try:
            grupos, cams = _cargar()
        except Exception as exc:
            print(f"supervisor: config ilegible ({exc}); reintento en 10s.", flush=True)
            time.sleep(10)
            continue
        activas = {c["id"] for c in cams}

        for cam in cams:
            cid = cam["id"]
            if cam["grupo"] not in grupos:
                print(f"supervisor: cámara {cid} con grupo '{cam['grupo']}' inexistente; se omite.", flush=True)
                continue
            grupo = grupos[cam["grupo"]]
            puertos.setdefault(cid, WEB_BASE + len(puertos))
            vivo = cid in procs and procs[cid].poll() is None
            if not vivo:
                if cid in procs:
                    print(f"supervisor: cámara {cid} cayó (code {procs[cid].returncode}); reiniciando.", flush=True)
                procs[cid] = subprocess.Popen([sys.executable, "seguimiento.py"], env=_env(cam, grupo, puertos[cid]))
                print(f"supervisor: cámara {cid} ({cam['nombre']}) grupo={cam['grupo']} → web :{puertos[cid]}", flush=True)

        for cid in list(procs):
            if cid not in activas:
                print(f"supervisor: cámara {cid} deshabilitada/borrada; deteniendo.", flush=True)
                procs[cid].terminate()
                procs.pop(cid, None)

        # Refresca la lista de la vista combinada (nombre + puerto por cámara viva).
        nombres = {c["id"]: c["nombre"] for c in cams}
        _PANEL["camaras"] = [
            {"id": cid, "nombre": nombres.get(cid, str(cid)), "puerto": puertos[cid]}
            for cid in procs if cid in puertos
        ]

        time.sleep(RECONCILE)


if __name__ == "__main__":
    main()
