# 📋 Documentación de Rutas CRUD - FB ESCANER

> Guía completa de endpoints del backend FastAPI para integración con Angular

---

## 📑 Tabla de Contenidos

1. [Estructura General](#estructura-general)
2. [Autenticación](#autenticación)
3. [Rutas CRUD por Módulo](#rutas-crud-por-módulo)
4. [Modelos de Datos](#modelos-de-datos)
5. [Ejemplo de Consumo en Angular](#ejemplo-de-consumo-en-angular)

---

## 🏗️ Estructura General

### Base URL
```
http://localhost:8000
```

### Headers Requeridos
```json
{
  "Content-Type": "application/json",
  "Authorization": "Bearer {access_token}"
}
```

### Convenciones
- **Métodos HTTP**: POST (crear), GET (leer), PUT (actualizar), DELETE (eliminar lógica)
- **Status Codes**: 
  - `201`: Creado exitosamente
  - `200`: Operación exitosa
  - `400`: Datos inválidos
  - `401`: No autenticado
  - `403`: No autorizado (scope insuficiente)
  - `404`: Recurso no encontrado

---

## 🔐 Autenticación

### Login
```http
POST /usuarios/login
Content-Type: application/json

{
  "nombre_usuario": "admin",
  "contrasena": "password123"
}
```

**Respuesta Exitosa (200)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "usuario": {
    "id_usuario": 1,
    "nombre_usuario": "admin",
    "email": "admin@example.com",
    "activo": true
  }
}
```

### Health Check
```http
GET /health

Respuesta:
{
  "status": "ok",
  "version": "1.0.0",
  "database": "ok"
}
```

---

## 📦 Rutas CRUD por Módulo

### 1️⃣ MÓDULO: USUARIOS

**Prefijo de ruta**: `/usuarios`

#### 1.1 Registrar Usuario (CREATE)
```http
POST /usuarios
Content-Type: application/json

{
  "nombre_usuario": "nuevo_usuario",
  "email": "usuario@example.com",
  "contrasena": "segura123"
}
```

**Respuesta (201)**:
```json
{
  "id_usuario": 5,
  "nombre_usuario": "nuevo_usuario",
  "email": "usuario@example.com",
  "activo": true,
  "fecha_creacion": "2026-06-09T10:30:00Z"
}
```

#### 1.2 Listar Usuarios (READ)
```http
GET /usuarios?skip=0&limit=100
Authorization: Bearer {token}
```

**Parámetros**:
- `skip`: int (registros a saltar, default: 0)
- `limit`: int (cantidad a devolver, default: 100, máx: 500)

#### 1.3 Obtener Usuario por ID (READ)
```http
GET /usuarios/{id_usuario}
Authorization: Bearer {token}
```

#### 1.4 Actualizar Usuario (UPDATE)
```http
PUT /usuarios/{id_usuario}
Authorization: Bearer {token}
Content-Type: application/json

{
  "email": "newemail@example.com",
  "contrasena": "nuevaPassword123"
}
```

#### 1.5 Desactivar Usuario (DELETE - Baja Lógica)
```http
DELETE /usuarios/{id_usuario}
Authorization: Bearer {token}
```

---

### 2️⃣ MÓDULO: ROLES

**Prefijo de ruta**: `/roles`

#### 2.1 Registrar Rol (CREATE)
```http
POST /roles
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Supervisor",
  "descripcion": "Supervisor de acceso",
  "permisos": ["leer:usuarios", "escribir:reportes"]
}
```

#### 2.2 Listar Roles (READ)
```http
GET /roles?skip=0&limit=100
Authorization: Bearer {token}
```

#### 2.3 Obtener Rol por ID (READ)
```http
GET /roles/{id_rol}
Authorization: Bearer {token}
```

#### 2.4 Actualizar Rol (UPDATE)
```http
PUT /roles/{id_rol}
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Super Admin",
  "permisos": ["*"]
}
```

#### 2.5 Desactivar Rol (DELETE)
```http
DELETE /roles/{id_rol}
Authorization: Bearer {token}
```

---

### 3️⃣ MÓDULO: EMPRESAS

**Prefijo de ruta**: `/empresas`

#### 3.1 Registrar Empresa (CREATE)
```http
POST /empresas
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Empresa ABC",
  "razon_social": "ABC S.A.",
  "rfc": "ABC123456XYZ",
  "coordenadas": [
    [-99.1234, 19.4321],
    [-99.1235, 19.4321],
    [-99.1235, 19.4322],
    [-99.1234, 19.4322]
  ]
}
```

#### 3.2 Listar Empresas (READ)
```http
GET /empresas?skip=0&limit=100
Authorization: Bearer {token}
```

#### 3.3 Obtener Empresa por ID (READ)
```http
GET /empresas/{id_empresa}
Authorization: Bearer {token}
```

#### 3.4 Actualizar Empresa (UPDATE)
```http
PUT /empresas/{id_empresa}
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Empresa XYZ Actualizada"
}
```

#### 3.5 Desactivar Empresa (DELETE)
```http
DELETE /empresas/{id_empresa}
Authorization: Bearer {token}
```

---

### 4️⃣ MÓDULO: ÁREAS DE TRABAJO

**Prefijo de ruta**: `/areas`

#### 4.1 Registrar Área (CREATE)
```http
POST /areas
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Piso 1",
  "descripcion": "Área de oficinas",
  "id_empresa": 1,
  "coordenadas": [[...]]
}
```

#### 4.2 Listar Áreas (READ)
```http
GET /areas?skip=0&limit=100
Authorization: Bearer {token}
```

#### 4.3 Obtener Área por ID (READ)
```http
GET /areas/{id_area}
Authorization: Bearer {token}
```

#### 4.4 Actualizar Área (UPDATE)
```http
PUT /areas/{id_area}
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Recepción Principal"
}
```

#### 4.5 Desactivar Área (DELETE)
```http
DELETE /areas/{id_area}
Authorization: Bearer {token}
```

---

### 5️⃣ MÓDULO: PUERTAS DE ACCESO

**Prefijo de ruta**: `/puertas` (o similar según el router)

#### 5.1 Registrar Puerta (CREATE)
```http
POST /puertas
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Puerta Principal",
  "ubicacion": "Entrada norte",
  "id_area": 1,
  "tipo": "entrada"
}
```

#### 5.2-5.5 CRUD Estándar
Similar a módulos anteriores con patrón:
- GET `/puertas` → Listar
- GET `/puertas/{id}` → Obtener
- PUT `/puertas/{id}` → Actualizar
- DELETE `/puertas/{id}` → Desactivar

---

### 6️⃣ MÓDULO: TRABAJADORES

**Prefijo de ruta**: `/trabajadores`

#### 6.1 Registrar Trabajador (CREATE)
```http
POST /trabajadores
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Juan",
  "apellido": "Pérez",
  "numero_empleado": "EMP001",
  "email": "juan@example.com",
  "id_empresa": 1
}
```

#### 6.2-6.5 CRUD Estándar
- GET `/trabajadores` → Listar
- GET `/trabajadores/{id}` → Obtener
- PUT `/trabajadores/{id}` → Actualizar
- DELETE `/trabajadores/{id}` → Desactivar

---

### 7️⃣ MÓDULO: ASISTENCIA

**Prefijo de ruta**: `/asistencia`

#### 7.1 Registrar Asistencia (CREATE)
```http
POST /asistencia
Authorization: Bearer {token}
Content-Type: application/json

{
  "id_trabajador": 15,
  "id_puerta": 8,
  "fecha_entrada": "2026-06-09T08:00:00Z",
  "tipo_acceso": "facial"
}
```

#### 7.2-7.3 READ
- GET `/asistencia` → Listar
- GET `/asistencia/{id}` → Obtener

---

### 8️⃣ MÓDULO: ESCANEO

**Prefijo de ruta**: `/escaneo`

#### 8.1 Registrar Escaneo (CREATE)
```http
POST /escaneo
Authorization: Bearer {token}
Content-Type: application/json

{
  "id_trabajador": 15,
  "id_puerta": 8,
  "imagen_base64": "iVBORw0KGgo...",
  "confianza": 0.95
}
```

#### 8.2-8.3 READ
- GET `/escaneo` → Listar
- GET `/escaneo/{id}` → Obtener

---

### 9️⃣ MÓDULO: SCANNER

**Prefijo de ruta**: `/scanner`

#### 9.1 Registrar Scanner (CREATE)
```http
POST /scanner
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Scanner 01",
  "numero_serie": "SN12345",
  "modelo": "FaceRecognizer Pro",
  "id_puerta": 8,
  "ip_address": "192.168.1.100"
}
```

#### 9.2-9.5 CRUD Estándar
- GET `/scanner` → Listar
- GET `/scanner/{id}` → Obtener
- PUT `/scanner/{id}` → Actualizar
- DELETE `/scanner/{id}` → Desactivar

---

### 🔟 MÓDULO: DISPOSITIVOS

**Prefijo de ruta**: `/dispositivos`

#### 10.1 Registrar Dispositivo (CREATE)
```http
POST /dispositivos
Authorization: Bearer {token}
Content-Type: application/json

{
  "nombre": "Cámara 01",
  "tipo": "camara",
  "id_area": 1,
  "ip_address": "192.168.1.50"
}
```

#### 10.2-10.5 CRUD Estándar
- GET `/dispositivos` → Listar
- GET `/dispositivos/{id}` → Obtener
- PUT `/dispositivos/{id}` → Actualizar
- DELETE `/dispositivos/{id}` → Desactivar

---

## 📊 Modelos TypeScript para Angular

```typescript
// ========== USUARIOS ==========
export interface Usuario {
  id_usuario: number;
  nombre_usuario: string;
  email: string;
  activo: boolean;
  fecha_creacion: string;
}

export interface UsuarioCreate {
  nombre_usuario: string;
  email: string;
  contrasena: string;
}

export interface UsuarioUpdate {
  email?: string;
  contrasena?: string;
  nombre_usuario?: string;
}

// ========== ROLES ==========
export interface Rol {
  id_rol: number;
  nombre: string;
  descripcion?: string;
  permisos: string[];
  activo: boolean;
}

// ========== EMPRESAS ==========
export interface Empresa {
  id_empresa: number;
  nombre: string;
  razon_social?: string;
  rfc?: string;
  coordenadas?: Array<[number, number]>;
  activo: boolean;
}

// ========== ÁREAS ==========
export interface AreaTrabajo {
  id_area: number;
  nombre: string;
  descripcion?: string;
  id_empresa: number;
  coordenadas?: Array<[number, number]>;
  activo: boolean;
}

// ========== TRABAJADORES ==========
export interface Trabajador {
  id_trabajador: number;
  nombre: string;
  apellido: string;
  numero_empleado: string;
  email?: string;
  numero_telefono?: string;
  id_empresa: number;
  activo: boolean;
  fecha_creacion: string;
}

// ========== PUERTAS ==========
export interface PuertaAcceso {
  id_puerta: number;
  nombre: string;
  ubicacion?: string;
  id_area: number;
  tipo?: string;
  activa: boolean;
}

// ========== SCANNER ==========
export interface Scanner {
  id_scanner: number;
  nombre: string;
  numero_serie: string;
  modelo?: string;
  id_puerta: number;
  ip_address?: string;
  puerto?: number;
  activo: boolean;
}

// ========== DISPOSITIVOS ==========
export interface Dispositivo {
  id_dispositivo: number;
  nombre: string;
  tipo?: string;
  id_area: number;
  ip_address?: string;
  numero_serie?: string;
  activo: boolean;
}

// ========== ASISTENCIA ==========
export interface Asistencia {
  id_asistencia: number;
  id_trabajador: number;
  id_puerta: number;
  fecha_entrada: string;
  fecha_salida?: string;
  tipo_acceso?: string;
}

// ========== ESCANEO ==========
export interface Escaneo {
  id_escaneo: number;
  id_trabajador: number;
  id_puerta: number;
  fecha_escaneo: string;
  confianza?: number;
  resultado?: string;
}
```

---

## 🅰️ Servicios Angular Base

```typescript
// generic-crud.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable()
export class GenericCrudService<T> {
  constructor(protected http: HttpClient, protected apiUrl: string) {}

  create(data: any): Observable<T> {
    return this.http.post<T>(this.apiUrl, data);
  }

  list(skip: number = 0, limit: number = 100): Observable<T[]> {
    const params = new HttpParams()
      .set('skip', skip.toString())
      .set('limit', limit.toString());
    return this.http.get<T[]>(this.apiUrl, { params });
  }

  getById(id: number): Observable<T> {
    return this.http.get<T>(`${this.apiUrl}/${id}`);
  }

  update(id: number, data: any): Observable<T> {
    return this.http.put<T>(`${this.apiUrl}/${id}`, data);
  }

  delete(id: number): Observable<T> {
    return this.http.delete<T>(`${this.apiUrl}/${id}`);
  }
}

// usuario.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { GenericCrudService } from './generic-crud.service';
import { Usuario } from '../models/usuario.model';

@Injectable({
  providedIn: 'root'
})
export class UsuarioService extends GenericCrudService<Usuario> {
  constructor(http: HttpClient) {
    super(http, 'http://localhost:8000/usuarios');
  }

  login(username: string, password: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/login`, {
      nombre_usuario: username,
      contrasena: password
    });
  }
}

// Similar para otros servicios (RolService, EmpresaService, etc.)
```

---

## 💡 Interceptor JWT para Angular

```typescript
import { Injectable } from '@angular/core';
import { HttpInterceptor, HttpRequest, HttpHandler, HttpEvent } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AuthService } from '../services/auth.service';

@Injectable()
export class JwtInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    const token = localStorage.getItem('access_token');
    if (token) {
      request = request.clone({
        setHeaders: {
          Authorization: `Bearer ${token}`
        }
      });
    }
    return next.handle(request);
  }
}
```

---

## 🎯 Patrones de Uso

| Operación | Método | Endpoint | Status |
|-----------|--------|----------|--------|
| Crear | POST | `/recurso` | 201 |
| Listar | GET | `/recurso?skip=0&limit=100` | 200 |
| Obtener | GET | `/recurso/{id}` | 200 |
| Actualizar | PUT | `/recurso/{id}` | 200 |
| Eliminar (Lógica) | DELETE | `/recurso/{id}` | 200 |

---

## ⚠️ Consideraciones Importantes

1. **Autenticación**: Token JWT requerido en todos los endpoints excepto login
2. **Baja Lógica**: DELETE no elimina, solo desactiva (marca `activo = false`)
3. **Paginación**: Usar `skip` y `limit` para grandes volúmenes
4. **Coordenadas**: Formato GeoJSON `[longitud, latitud]`
5. **Errores**: Revisar `response.detail` para mensajes de error
6. **CORS**: Verificar configuración en backend FastAPI
7. **Timeouts**: Ajustar según las necesidades en production

---

**Documentación Actualizada**: 2026-06-09  
**Versión API**: 1.0.0
