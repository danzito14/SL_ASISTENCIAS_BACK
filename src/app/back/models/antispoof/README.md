# Modelos anti-spoofing (Silent-Face / MiniFASNet, ONNX)

Coloca aquí uno o más modelos `.onnx` de anti-spoofing. El servicio
(`src/services/antispoof_service.py`) carga **todos** los `.onnx` de esta carpeta
y promedia su softmax (ensemble estilo Silent-Face).

## Convención de nombre

El nombre debe empezar con la **escala de recorte**, igual que el proyecto original:

```
2.7_80x80_MiniFASNetV2.onnx
4_0_0_80x80_MiniFASNetV1SE.onnx
```

- `2.7` / `4` → escala con la que se expande el bounding box de la cara.
- `80x80`   → tamaño de entrada (también se lee del propio modelo).

Si pones un solo modelo, usa el `2.7_80x80_*` (el más común y robusto).

## De dónde descargarlo

Modelos ONNX ya convertidos (no requieren PyTorch):

- https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx  (MiniFASNetV2 2.7)
- https://github.com/yakhyo/face-anti-spoofing  (PyTorch + ONNX Runtime, incluye .onnx)
- https://github.com/facenox/face-antispoof-onnx  (MiniFASNetV2-SE ultraligero, ~600 KB)

Pesos originales (`.pth`) por si quieres convertirlos tú:
- https://github.com/minivision-ai/Silent-Face-Anti-Spoofing

## Preprocesamiento que aplica el servicio

Recorte de la cara con la escala del nombre → resize a 80×80 → **BGR**, `/255`,
NCHW → softmax de 3 clases. Si tu modelo usa otro orden de clases (a veces el
índice 0 es "real" en vez del 1), ajusta `ANTISPOOF_REAL_INDEX` en el `.env`.

## Activar y calibrar

En el `.env`:
```
ANTISPOOFING_ACTIVO=true
ANTISPOOF_REAL_INDEX=1     # cambia a 0 si tu modelo invierte las clases
ANTISPOOF_UMBRAL=0.0       # súbelo (p. ej. 0.6) para ser más estricto
```

Al hacer un acceso, el log imprime `Anti-spoof: probs=[...] label=... score_real=...`.
Prueba con una **cara real** y con una **foto en pantalla**: confirma qué índice
sube con la cara real y ajusta `ANTISPOOF_REAL_INDEX`/`ANTISPOOF_UMBRAL`.
