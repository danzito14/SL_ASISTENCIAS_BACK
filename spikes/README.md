# Spikes — APK offline de asistencias

Pruebas de concepto que **deciden la arquitectura** del APK antes de construir nada.

## `spike_paridad_onnx.py` — ¿el reconocimiento offline es viable?

El APK debe reconocer rostros **sin internet**: baja del servidor los embeddings de
referencia (generados con InsightFace **buffalo_l**) y, al fichar, genera en el
teléfono el embedding de la cara capturada y lo compara localmente (coseno).

Eso solo funciona si el embedding del teléfono cae en el **mismo espacio vectorial**
que el del servidor. Este spike lo demuestra: reimplementa **a mano** (fuera de
insightface) lo que el APK hará en ONNX Runtime —alineación `norm_crop` +
preprocesamiento ArcFace + correr `w600k_r50.onnx` pelón— y compara contra el
`normed_embedding` de insightface.

**PASA** si la paridad mínima ≥ `0.999`. Si pasa, el offline es viable y portar el
pipeline a JS/Kotlin es mecánico. Si falla, hay que corregir alineación/preproceso
antes de invertir en el APK.

### Cómo correr

Todo vive ya dentro del contenedor `sl_recognition` (insightface, onnxruntime,
opencv, scikit-image y los modelos buffalo_l descargados). No instales nada.

1. Junta **3–10 fotos** de rostros (una cara clara por foto; sirven las mismas que
   usaste para enrolar). Ponlas en una carpeta, p. ej. `./fotos_spike/`.

2. Copia el script y las fotos al contenedor:
   ```bash
   docker cp spikes/spike_paridad_onnx.py sl_recognition:/tmp/spike_paridad_onnx.py
   docker cp ./fotos_spike                sl_recognition:/tmp/fotos
   ```

3. Corre el spike:
   ```bash
   docker exec -it sl_recognition python /tmp/spike_paridad_onnx.py /tmp/fotos
   ```

4. Lee el **VEREDICTO** al final. Columnas:
   - `paridad`  → coseno pipeline-a-mano vs. buffalo_l (debe ser ≥ 0.999).
   - `tol±2px`  → coseno si otro detector mueve los kps ±2px (debe ser > 0.97;
     acota qué tan bueno debe ser el detector del APK).

### Qué NO cubre

La **detección** (SCRFD) no se reimplementa: se usan los kps de insightface. En el
APK la detección será ML Kit / MediaPipe / SCRFD-onnx; la columna `tol±2px` mide
cuánto importa esa diferencia. Si `tol` queda bajo, el APK necesita un detector
preciso (SCRFD-onnx) en vez de uno genérico.
