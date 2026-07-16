# vigilancia/services/Dvr_Service.py
# Descubrimiento de canales de un DVR/NVR Hikvision por ISAPI (para configurar cámaras
# desde el front sin adivinar canales). Devuelve TODOS los canales — IP y ANALÓGICOS —
# marcando el tipo y si están activos. Digest auth con urllib (sin dependencias nuevas).
#
# Fuentes ISAPI:
#   InputProxy/channels        → cámaras IP (id 33+), con nombre + IP de la cámara.
#   System/Video/inputs/channels → canales ANALÓGICOS (id 1-32), con nombre (sin IP).
#   Streaming/channels         → cuáles tienen stream activo (para marcar `activo`).
import re
import urllib.request
import xml.etree.ElementTree as ET


def _opener(url: str, usuario: str | None, password: str | None):
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, url, usuario or "", password or "")
    return urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))


def _get(host: str, usuario: str | None, password: str | None, path: str, timeout: float) -> str:
    url = f"http://{host}{path}"
    with _opener(url, usuario, password).open(url, timeout=timeout) as r:
        # quita el namespace por defecto → findall/regex simples
        return re.sub(r'xmlns="[^"]+"', "", r.read().decode("utf-8", "ignore"))


def _fila(chan: int, tipo: str, nombre: str, ip: str, activos) -> dict:
    return {
        "canal_dvr": chan,
        "canal_rtsp": chan * 100 + 1,      # MAIN (id en camaras.canal)
        "canal_rtsp_sub": chan * 100 + 2,  # SUB (algunos DVR solo decodifican el sub)
        "tipo": tipo,                       # "ip" | "analogica"
        "nombre": nombre,
        "ip_camara": ip or None,            # solo IP; analógica = None (no tiene IP propia)
        "activo": (chan in activos) if activos is not None else None,
    }


def listar_canales(host: str, usuario: str | None, password: str | None,
                   timeout: float = 12.0) -> list[dict]:
    """Canales IP + ANALÓGICOS del DVR, con tipo, nombre, IP (si es IP) y si están activos.

    `canal_rtsp`/`canal_rtsp_sub` = valores para camaras.canal (main/sub). Las cámaras IP
    directas pueden usar su `ip_camara` (host propio); las analógicas van SIEMPRE por el DVR
    (host heredado del grupo + canal). Requiere la contraseña DEL DVR (no la de cámara).
    """
    # (1) Cámaras IP — REQUERIDO. Si esto falla (401/timeout), sube el error al router.
    ip_xml = _get(host, usuario, password, "/ISAPI/ContentMgmt/InputProxy/channels", timeout)
    ip_map: dict[int, tuple[str, str]] = {}
    for ch in ET.fromstring(ip_xml).findall(".//InputProxyChannel"):
        cid = ch.findtext("id")
        if cid and cid.isdigit():
            ip_map[int(cid)] = ((ch.findtext("name") or "").strip(),
                                (ch.findtext(".//ipAddress") or "").strip())

    # (2) Canales analógicos — OPCIONAL (un NVR puro no tiene). No romper si falta.
    analog_map: dict[int, str] = {}
    try:
        an_xml = _get(host, usuario, password, "/ISAPI/System/Video/inputs/channels", timeout)
        for ch in ET.fromstring(an_xml).findall(".//VideoInputChannel"):
            cid = ch.findtext("id")
            if cid and cid.isdigit() and int(cid) not in ip_map:   # analógica = la que no es IP
                analog_map[int(cid)] = (ch.findtext("name") or "").strip()
    except Exception:
        pass

    # (3) Cuáles tienen stream activo — OPCIONAL (para marcar `activo`).
    activos: set[int] | None
    try:
        st_xml = _get(host, usuario, password, "/ISAPI/Streaming/channels", timeout)
        activos = {int(m) // 100 for m in re.findall(r"<id>(\d+)</id>", st_xml) if m.endswith("01")}
    except Exception:
        activos = None

    filas = [_fila(c, "ip", nm, ip, activos) for c, (nm, ip) in ip_map.items()]
    filas += [_fila(c, "analogica", nm, "", activos) for c, nm in analog_map.items()]
    filas.sort(key=lambda f: f["canal_dvr"])
    return filas
