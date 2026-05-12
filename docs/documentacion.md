# EcoReporte Ciudadano
## Documentación Técnica del Proyecto Final

---

**Asignatura:** Computación Sustentable  
**Objetivo de Desarrollo Sostenible:** ODS 13 — Acción por el Clima  
**Stack tecnológico:** AWS Lambda · DynamoDB · S3 · API Gateway  
**Fecha:** Mayo 2026

---

## Tabla de contenido

1. [Descripción del proyecto](#1-descripción-del-proyecto)  
2. [Alineación con ODS 13](#2-alineación-con-ods-13)  
3. [Arquitectura del sistema](#3-arquitectura-del-sistema)  
4. [Modelo de datos](#4-modelo-de-datos)  
5. [Guía de despliegue](#5-guía-de-despliegue)  
6. [Referencia de la API REST](#6-referencia-de-la-api-rest)  
7. [Justificación de decisiones técnicas](#7-justificación-de-decisiones-técnicas)  
8. [Análisis de costos](#8-análisis-de-costos)  
9. [Pruebas de resiliencia](#9-pruebas-de-resiliencia)  
10. [Reflexión sobre computación sustentable](#10-reflexión-sobre-computación-sustentable)  
11. [Limitaciones y trabajo futuro](#11-limitaciones-y-trabajo-futuro)  
12. [Conclusiones](#12-conclusiones)

---

## 1. Descripción del proyecto

**EcoReporte Ciudadano** es una aplicación web de participación cívica ambiental que permite a cualquier ciudadano documentar y geolocalizar problemas ambientales en su comunidad: tiraderos clandestinos, derrames de sustancias contaminantes, quema ilegal de residuos y tala no autorizada de árboles.

Cada reporte incluye:
- **Categoría** del problema (basura, derrame, quema, tala u otro)
- **Descripción** textual libre (hasta 280 caracteres)
- **Coordenadas GPS** detectadas automáticamente por el navegador
- **Fotografía** opcional subida directamente desde el dispositivo móvil
- **Municipio** de referencia para facilitar la atención por parte de autoridades

Todos los reportes aparecen en un **mapa público interactivo** (Leaflet.js + OpenStreetMap) donde cualquier persona puede visualizarlos, filtrarlos por categoría y seguir su evolución desde el status *pendiente* hasta *resuelto*.

La aplicación está construida íntegramente sobre **AWS serverless**, lo que elimina la necesidad de administrar servidores, reduce el costo de operación a prácticamente cero con tráfico bajo y permite escalar automáticamente si el uso crece.

### Características principales

| Funcionalidad | Descripción |
|---|---|
| Mapa público en tiempo real | Marcadores con código de color por categoría, actualización automática cada 60 s |
| Formulario de reporte | GPS automático con fallback manual, validación de foto, categorías visuales |
| Filtros interactivos | Por categoría, municipio, status y búsqueda libre de texto |
| Panel lateral | Lista de reportes recientes, cerca de mí, mis reportes (con persistencia en localStorage) |
| Diseño responsive | Funciona en escritorio y móvil; bottom sheet deslizable en pantallas pequeñas |
| API REST pública | Tres endpoints documentados, CORS habilitado, respuestas JSON estructuradas |
| Pruebas de resiliencia | Script `resiliencia.py` con 4 escenarios de falla simulados |

---

## 2. Alineación con ODS 13

El **Objetivo de Desarrollo Sostenible 13 — Acción por el Clima** establece, entre sus metas, que los países deben *"mejorar la educación, la sensibilización y la capacidad humana e institucional en relación con la mitigación del cambio climático, la adaptación a él, la reducción de sus efectos y la alerta temprana"*.

EcoReporte Ciudadano contribuye a esta meta desde tres ángulos:

**Sensibilización ciudadana.** Hacer visible un problema es el primer paso para resolverlo. Al mapear públicamente los tiraderos, derrames y quemas ilegales de una ciudad, la aplicación convierte percepciones individuales ("siempre tiran basura en esa esquina") en evidencia colectiva georreferenciada que las autoridades ambientales pueden priorizar y atender.

**Reducción de emisiones locales.** La quema de residuos sólidos urbanos y de biomasa es una fuente significativa de gases de efecto invernadero y contaminantes de corta vida (black carbon, metano). Un sistema de reporte ciudadano que reduce el tiempo de respuesta de las autoridades contribuye directamente a disminuir estos eventos.

**Capacidad institucional.** La aplicación puede ser adoptada por municipios como herramienta de gestión ambiental participativa. Al estar basada en servicios cloud de bajo costo, incluso municipios con presupuesto limitado pueden operarla.

**Indicador relevante:** La meta 13.3 del ODS 13 establece mejorar la capacidad de alerta temprana e información sobre riesgos. EcoReporte Ciudadano opera como un sistema de alerta temprana distribuido, donde miles de ciudadanos actúan como sensores humanos del estado ambiental de su ciudad.

---

## 3. Arquitectura del sistema

### 3.1 Visión general

La arquitectura sigue el patrón **Serverless Web Application** de AWS: un frontend estático servido desde S3 que se comunica con funciones Lambda a través de API Gateway, las cuales persisten datos en DynamoDB. No existe ningún servidor de aplicaciones que gestionar.

```
╔═══════════════════════════════════════════════════════════════╗
║                     INTERNET / USUARIO                        ║
╚═══════════╤═══════════════════════════════════╤═══════════════╝
            │ HTTP GET (HTML/CSS/JS)             │ PUT foto (directo)
            ▼                                   │
╔═══════════════════════╗          presigned URL │
║   S3 Static Website   ║ ◄────────────────────◄┘
║   ecoreporte-web-*    ║
║   index.html (SPA)    ║
╚═══════════════════════╝
            │
            │ fetch() AJAX
            ▼
╔═══════════════════════════════════════════════════════════════╗
║                    API GATEWAY REST                           ║
║              https://*.execute-api.us-east-1.amazonaws.com   ║
║                        /prod                                  ║
║                                                               ║
║   POST   /reportes           GET  /reportes                  ║
║   PUT    /reportes/{id}/status     OPTIONS * (CORS mock)      ║
╚═══════════════════╤═══════════════════════════════════════════╝
                    │ AWS_PROXY (Lambda Proxy Integration)
                    ▼
╔═══════════════════════════════════════════════════════════════╗
║                  AWS LAMBDA  (Python 3.12)                    ║
║                                                               ║
║  ┌─────────────────────┐  ┌─────────────────────────────┐    ║
║  │ crear_reporte       │  │ listar_reportes             │    ║
║  │ • Valida campos     │  │ • Scan DynamoDB             │    ║
║  │ • UUID → DynamoDB   │  │ • Filtros opcionales        │    ║
║  │ • Presigned URL S3  │  │ • Paginación automática     │    ║
║  └─────────────────────┘  └─────────────────────────────┘    ║
║  ┌─────────────────────┐                                      ║
║  │ actualizar_status   │                                      ║
║  │ • Verifica que      │                                      ║
║  │   exista el reporte │                                      ║
║  │ • UpdateItem cond.  │                                      ║
║  └─────────────────────┘                                      ║
╚═══════════╤═══════════════════════════════════════════════════╝
            │                          │
            ▼                          ▼
╔═══════════════════╗      ╔════════════════════════╗
║     DynamoDB      ║      ║   S3 Bucket (fotos)    ║
║  ecoreporte-      ║      ║   ecoreporte-fotos-*   ║
║    reportes       ║      ║                        ║
║  PAY_PER_REQUEST  ║      ║  /fotos/{uuid}.jpg     ║
║  2 GSI            ║      ║  Lectura pública       ║
╚═══════════════════╝      ╚════════════════════════╝
            │
            ▼
╔═══════════════════╗
║  CloudWatch Logs  ║
║  (logs Lambda)    ║
╚═══════════════════╝

────────────────────────────────────────────────────────────────
  IAM Role: ecoreporte-lambda-role
  Permisos: dynamodb:GetItem/PutItem/UpdateItem/Scan/Query
            s3:PutObject/GetObject
            logs:CreateLogGroup/CreateLogStream/PutLogEvents
────────────────────────────────────────────────────────────────
```

### 3.2 Flujo de creación de un reporte

El siguiente diagrama muestra el flujo completo cuando un ciudadano envía un reporte con foto:

```
 Navegador              API Gateway          Lambda              DynamoDB    S3
    │                       │                   │                   │         │
    │── POST /reportes ────►│                   │                   │         │
    │   {categoria,         │── invoke ────────►│                   │         │
    │    descripcion,       │                   │── Validar campos  │         │
    │    latitud,           │                   │── Generar UUID    │         │
    │    longitud}          │                   │── PutItem ───────►│         │
    │                       │                   │◄─ OK              │         │
    │                       │                   │── GeneratePresignedUrl ────►│
    │                       │                   │◄─ {url, ttl=900s}           │
    │◄── 201 Created ───────│◄─ return ─────────│                   │         │
    │   {reporte_id,        │                   │                   │         │
    │    presigned_url,     │                   │                   │         │
    │    foto_url}          │                   │                   │         │
    │                       │                   │                   │         │
    │── PUT foto ──────────────────────────────────────────────────────────►│
    │   Content-Type: image/jpeg (directo a S3, sin pasar por Lambda)       │
    │◄─ 200 OK ─────────────────────────────────────────────────────────────│
    │                       │                   │                   │         │
    │── GET /reportes ─────►│── invoke ────────►│── Scan ──────────►│         │
    │◄─ 200 [{...},...] ────│◄─ [{...},...]─────│◄─ [{...},...]─────│         │
```

### 3.3 Flujo de lectura (carga del mapa)

```
Navegador             API Gateway        Lambda             DynamoDB
   │                      │                 │                  │
   │── GET /reportes ────►│── invoke ──────►│── Scan ─────────►│
   │   ?categoria=basura  │                 │   FilterExpr.     │
   │                      │                 │◄─ Items[]         │
   │◄─ 200 OK ────────────│◄─ return ───────│                  │
   │   {reportes:[...],   │                 │                  │
   │    total: N}         │                 │                  │
   │                      │                 │                  │
   │ Leaflet pinta N      │                 │                  │
   │ markers en el mapa   │                 │                  │
```

---

## 4. Modelo de datos

### 4.1 Tabla DynamoDB: `ecoreporte-reportes`

**Clave primaria:** `reporte_id` (Partition Key, tipo String)

> Se usa UUID v4 como clave primaria para garantizar unicidad global sin coordinación. No se usa Sort Key porque cada reporte es un elemento independiente accesible por su ID.

| Atributo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `reporte_id` | String (PK) | UUID v4 generado por Lambda | `"a3f4c1b2-..."` |
| `fecha_creacion` | String | ISO 8601 en UTC | `"2026-05-11T14:23:00Z"` |
| `categoria` | String | Enum: basura, derrame, quema, tala, otro | `"basura"` |
| `descripcion` | String | Texto libre, máx. 2000 chars | `"Tiradero en Río..."` |
| `latitud` | String | Decimal degrees (guardado como String\*) | `"20.673400"` |
| `longitud` | String | Decimal degrees (guardado como String\*) | `"-103.349600"` |
| `municipio` | String | Nombre del municipio | `"Guadalajara"` |
| `reportado_por` | String | Nombre o "Anónimo" | `"Anónimo"` |
| `foto_key` | String | Clave del objeto en S3 | `"fotos/a3f4c1b2.jpg"` |
| `foto_url` | String | URL pública de la foto | `"https://s3.amazonaws.com/..."` |
| `status` | String | Enum: pendiente, en_proceso, resuelto | `"pendiente"` |

> \* DynamoDB no tiene tipo `Float` nativo; los números de punto flotante se guardan como `String` para preservar precisión. El frontend hace `parseFloat()` al leer.

### 4.2 Índices Secundarios Globales (GSI)

| Índice | Partition Key | Sort Key | Uso |
|---|---|---|---|
| `categoria-index` | `categoria` | `fecha_creacion` | Listar reportes de una categoría en orden cronológico |
| `status-index` | `status` | `fecha_creacion` | Listar reportes por status (ej. todos los pendientes) |

> En la implementación actual se usa `Scan` con `FilterExpression` por simplicidad. Los GSI están creados para que una versión futura pueda hacer `Query` y aprovechar el ordenamiento nativo de DynamoDB.

### 4.3 Capacidad de la tabla

La tabla usa **modo `PAY_PER_REQUEST` (on-demand)**. DynamoDB escala automáticamente entre 0 y millones de operaciones por segundo sin aprovisionar capacidad. Esto es ideal para una aplicación con tráfico impredecible o bajo.

---

## 5. Guía de despliegue

### 5.1 Requisitos previos

| Requisito | Versión mínima | Comando de verificación |
|---|---|---|
| Python | 3.11 | `python3 --version` |
| pip | cualquiera | `pip --version` |
| AWS CLI | 2.x | `aws --version` |
| Cuenta AWS | Free Tier activo | — |
| Git | cualquiera | `git --version` |

Las credenciales AWS deben tener permisos para: IAM, Lambda, DynamoDB, S3, API Gateway y STS. Una cuenta con `AdministratorAccess` cubre todos estos servicios.

### 5.2 Configurar credenciales AWS

```bash
aws configure
```

```
AWS Access Key ID     [None]: AKIA...
AWS Secret Access Key [None]: xxxx...
Default region name   [None]: us-east-1
Default output format [None]: json
```

Verificar que las credenciales son válidas:

```bash
aws sts get-caller-identity
```

Salida esperada:
```json
{
    "UserId": "AIDAXXXXXXXXXX",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/nombre-usuario"
}
```

### 5.3 Clonar el repositorio e instalar dependencias

```bash
git clone https://github.com/<usuario>/ecoreporte-ciudadano.git
cd ecoreporte-ciudadano
pip install -r requirements.txt
```

### 5.4 Despliegue automatizado completo

```bash
python3 scripts/setup.py
```

El script crea en este orden los siguientes recursos en AWS, sin intervención manual:

| Paso | Recurso creado | Tiempo aproximado |
|---|---|---|
| 1 | Tabla DynamoDB `ecoreporte-reportes` con 2 GSI | ~15 s |
| 2 | S3 bucket de fotos con CORS y política de lectura pública | ~5 s |
| 3 | S3 bucket web con static website hosting habilitado | ~5 s |
| 4 | IAM Role `ecoreporte-lambda-role` con política de permisos mínimos | ~15 s (propagación) |
| 5 | 3 funciones Lambda empaquetadas y desplegadas (Python 3.12, 256 MB) | ~30 s |
| 6 | API Gateway REST con 3 rutas, CORS y permisos de invocación | ~30 s |
| 6 | Frontend inyectado con la URL de la API y subido a S3 | ~5 s |

**Salida esperada al terminar:**

```
============================================================
  ✅ DESPLIEGUE COMPLETO
============================================================

🌐 App web:  http://ecoreporte-web-XXXXXX.s3-website-us-east-1.amazonaws.com
🔌 API URL:  https://XXXXXXXXXX.execute-api.us-east-1.amazonaws.com/prod
📋 Config guardada en: .ecoreporte_config.json
```

> El archivo `.ecoreporte_config.json` guarda todos los ARNs y URLs generados. Es leído por `demo.py`, `resiliencia.py` y `destroy.py`. Está en `.gitignore` porque contiene identificadores de tu cuenta AWS.

### 5.5 Cargar datos de demostración

```bash
python3 demo.py
```

Inserta 8 reportes realistas de diferentes municipios de Jalisco, México, con fechas distribuidas en los últimos 14 días y los tres posibles estados (pendiente, en_proceso, resuelto). Permite demostrar la aplicación inmediatamente sin que el profesor tenga que crear reportes.

```bash
# Para limpiar los datos demo sin borrar la infraestructura:
python3 demo.py --cleanup
```

### 5.6 Modo pedagógico para demostración

```bash
python3 demo_profesor/setup_interactivo.py
```

Este script es **funcionalmente equivalente** a `scripts/setup.py` pero añade:
- Pausas entre cada fase para dar tiempo a explicar
- Descripción de cada servicio que se crea y por qué se eligió
- Texto que justifica las decisiones de arquitectura en tiempo real
- Resumen final con tabla de todos los componentes desplegados

Para ejecutarlo sin pausas (demo continua):

```bash
python3 demo_profesor/setup_interactivo.py --no-pausas
```

### 5.7 Verificación del despliegue

Después del despliegue, verificar que cada componente responde correctamente:

```bash
# Leer la URL de la API del archivo de config
API_URL=$(python3 -c "import json; print(json.load(open('.ecoreporte_config.json'))['api_url'])")

# 1. Verificar GET /reportes
curl -s "$API_URL/reportes" | python3 -m json.tool | head -20

# 2. Verificar POST /reportes
curl -s -X POST "$API_URL/reportes" \
  -H "Content-Type: application/json" \
  -d '{"categoria":"otro","descripcion":"Prueba de verificacion","latitud":20.6597,"longitud":-103.3496}' \
  | python3 -m json.tool

# 3. Abrir la app en el navegador
python3 -c "import json,webbrowser; webbrowser.open(json.load(open('.ecoreporte_config.json'))['url_web'])"
```

### 5.8 Eliminar toda la infraestructura

```bash
python3 scripts/destroy.py
# Pide confirmación antes de proceder

# Sin confirmación (automatizado):
python3 scripts/destroy.py --force
```

El script elimina en orden: DynamoDB → S3 (vaciar y borrar) → Lambda → IAM role → API Gateway. Al terminar borra `.ecoreporte_config.json`.

---

## 6. Referencia de la API REST

**Base URL:** `https://{api_id}.execute-api.{region}.amazonaws.com/prod`

Todas las respuestas son JSON. Todos los endpoints incluyen encabezados CORS (`Access-Control-Allow-Origin: *`).

---

### 6.1 `POST /reportes` — Crear reporte

Crea un nuevo reporte ambiental y genera una URL prefirmada para subir la foto.

**Request:**

```http
POST /prod/reportes
Content-Type: application/json
```

```json
{
  "categoria"    : "basura",
  "descripcion"  : "Tiradero clandestino junto al canal pluvial.",
  "latitud"      : 20.6710,
  "longitud"     : -103.3650,
  "municipio"    : "Guadalajara",
  "reportado_por": "Anónimo"
}
```

| Campo | Tipo | Obligatorio | Restricción |
|---|---|---|---|
| `categoria` | string | ✅ | `basura`, `derrame`, `quema`, `tala`, `otro` |
| `descripcion` | string | ✅ | máx. 2000 caracteres |
| `latitud` | number | ✅ | -90 a 90 |
| `longitud` | number | ✅ | -180 a 180 |
| `municipio` | string | ❌ | máx. 100 caracteres, default: `"Desconocido"` |
| `reportado_por` | string | ❌ | máx. 100 caracteres, default: `"Anónimo"` |

**Respuesta exitosa — `201 Created`:**

```json
{
  "reporte_id"   : "a3f4c1b2-7d8e-4f2a-b1c3-9e0f1a2b3c4d",
  "presigned_url": "https://ecoreporte-fotos-123456.s3.amazonaws.com/fotos/a3f4c1b2...?X-Amz-Signature=...",
  "foto_url"     : "https://ecoreporte-fotos-123456.s3.us-east-1.amazonaws.com/fotos/a3f4c1b2-...jpg",
  "mensaje"      : "Reporte creado exitosamente"
}
```

> La `presigned_url` es válida por **15 minutos**. El cliente debe hacer un `PUT` a esa URL con `Content-Type: image/jpeg` y el contenido binario de la imagen.

**Errores:**

| Código | Causa |
|---|---|
| `400` | Campo obligatorio faltante, categoría fuera del enum, coordenadas no numéricas |
| `503` | Error temporal de DynamoDB |

---

### 6.2 `GET /reportes` — Listar reportes

Devuelve todos los reportes, opcionalmente filtrados.

**Request:**

```http
GET /prod/reportes?categoria=basura&status=pendiente&limit=50
```

| Parámetro | Tipo | Descripción | Default |
|---|---|---|---|
| `categoria` | string | Filtrar por categoría | (todos) |
| `status` | string | Filtrar por status | (todos) |
| `limit` | integer | Máximo de resultados | 500 |

**Respuesta exitosa — `200 OK`:**

```json
{
  "reportes": [
    {
      "reporte_id"    : "a3f4c1b2-...",
      "fecha_creacion": "2026-05-11T14:23:00.123456+00:00",
      "categoria"     : "basura",
      "descripcion"   : "Tiradero clandestino junto al canal pluvial.",
      "latitud"       : "20.671000",
      "longitud"      : "-103.365000",
      "municipio"     : "Guadalajara",
      "reportado_por" : "Anónimo",
      "foto_key"      : "fotos/a3f4c1b2-....jpg",
      "foto_url"      : "https://ecoreporte-fotos-123456.s3.../.jpg",
      "status"        : "pendiente"
    }
  ],
  "total": 1
}
```

Los reportes se devuelven **ordenados por `fecha_creacion` descendente** (más recientes primero).

---

### 6.3 `PUT /reportes/{reporte_id}/status` — Actualizar status

Actualiza el status de un reporte existente. Útil para que autoridades marquen un reporte como atendido.

**Request:**

```http
PUT /prod/reportes/a3f4c1b2-7d8e-4f2a-b1c3-9e0f1a2b3c4d/status
Content-Type: application/json
```

```json
{
  "status": "resuelto"
}
```

| Valor de `status` | Significado |
|---|---|
| `pendiente` | Reporte recibido, sin atender |
| `en_proceso` | Autoridad trabajando en ello |
| `resuelto` | Problema atendido y cerrado |

**Respuesta exitosa — `200 OK`:**

```json
{
  "reporte_id"     : "a3f4c1b2-...",
  "status_anterior": "en_proceso",
  "status_nuevo"   : "resuelto",
  "mensaje"        : "Status actualizado a 'resuelto'"
}
```

**Errores:**

| Código | Causa |
|---|---|
| `400` | Valor de status inválido |
| `404` | `reporte_id` no encontrado |
| `503` | Error temporal de DynamoDB |

---

### 6.4 `OPTIONS *` — CORS Preflight

Todos los recursos responden a `OPTIONS` con una integración mock que devuelve los encabezados CORS necesarios. Esto es transparente para el navegador y no requiere código especial.

```
Access-Control-Allow-Headers: Content-Type,Authorization
Access-Control-Allow-Methods: GET,POST,PUT,OPTIONS
Access-Control-Allow-Origin:  *
```

---

## 7. Justificación de decisiones técnicas

### 7.1 DynamoDB vs RDS (PostgreSQL / MySQL)

**Decisión:** DynamoDB.

Los reportes ambientales son documentos JSON autocontenidos: cada reporte tiene todos sus datos en un solo objeto, sin relaciones complejas hacia otras tablas. No se necesitan JOINs, transacciones multi-tabla ni procedimientos almacenados.

| Criterio | DynamoDB | RDS (MySQL) |
|---|---|---|
| Costo en idle | **$0.00** (on-demand, 0 ops = 0 costo) | **~$15/mes** (instancia db.t3.micro siempre activa) |
| Schema | Flexible, sin ALTER TABLE | Rígido, migraciones necesarias |
| Escalabilidad | Automática, milisegundos de latencia a cualquier escala | Requiere instancias más grandes, réplicas manuales |
| Alta disponibilidad | Multi-AZ por defecto | Opcional, costo extra |
| Administración | Cero (managed) | Patchs, backups, upgrades |
| Free Tier | 25 GB + 25 RCU/WCU **permanente** | Solo 12 meses (750 h/mes) |

Para un proyecto con tráfico variable y bajo, la diferencia de $15/mes puede significar que el proyecto deje de existir por costo. DynamoDB elimina ese riesgo.

**Limitación conocida:** DynamoDB no soporta queries complejos tipo SQL. Los GSI cubren los casos de uso más comunes (filtrar por categoría o status), y el Scan con FilterExpression es suficiente para el volumen esperado (< 10,000 reportes).

### 7.2 AWS Lambda vs EC2 / Elastic Beanstalk

**Decisión:** Lambda.

El backend de EcoReporte consiste en tres operaciones simples y bien delimitadas: crear un item, leer items, actualizar un item. Cada operación dura entre 50 y 300 ms. Este perfil de carga es exactamente el caso de uso ideal para funciones serverless.

| Criterio | Lambda | EC2 t3.micro |
|---|---|---|
| Costo base mensual | **$0** (primer millón de invocaciones gratis, permanente) | **~$8-10/mes** |
| Costo con 0 requests | **$0** | **$8-10/mes** (instancia corriendo aunque no haya tráfico) |
| Escala automática | 0 → 1,000 concurrentes sin configuración | Manual (Auto Scaling Groups, configuración extra) |
| Deploy | Subir un ZIP de ~10 KB | SSH + git pull + reiniciar servicio |
| Mantenimiento | Ninguno (AWS gestiona el OS, runtime, patches) | Parchear OS, actualizar Python, gestionar certificados |
| Tiempo de arranque | "Cold start" de ~300-800 ms (primera invocación tras idle) | Siempre activo (latencia consistente) |

El único inconveniente de Lambda es el **cold start**: si la función lleva mucho tiempo sin invocarse, la primera llamada puede tardar 300-800 ms adicionales mientras AWS inicializa el entorno. Para una aplicación de reportes ciudadanos donde la latencia de unos segundos es aceptable, esto no es un problema. Si fuera crítico, se podría configurar **Provisioned Concurrency** (mantiene instancias precalentadas).

### 7.3 S3 Static Website Hosting vs servidor web

**Decisión:** S3 Static Website Hosting.

El frontend es un único archivo `index.html` de ~100 KB. No requiere renderizado del lado del servidor (SSR), no tiene rutas dinámicas del lado del servidor, no ejecuta PHP, Node ni ningún otro runtime.

S3 sirve este archivo con:
- **Costo:** $0.023/GB transferido. Para 1,000 visitas de 100 KB = 100 MB = $0.0023
- **Latencia:** comparable a cualquier CDN (S3 tiene edge locations en múltiples regiones)
- **Disponibilidad:** SLA de 99.99% (mismo nivel que los servicios críticos de AWS)
- **Mantenimiento:** cero

Un servidor Nginx en EC2 costaría $8-10/mes corriendo 24/7 para servir el mismo archivo estático.

### 7.4 Presigned URLs para subida de fotos

**Decisión:** Presigned PUT URL generada por Lambda.

El flujo alternativo sería: usuario → API Gateway → Lambda → S3 (Lambda recibe la foto, la sube a S3). Este flujo tiene dos limitaciones críticas:

1. **API Gateway** tiene un límite de **10 MB por payload de request** (y 6 MB para Lambda con payload binario)
2. **Lambda cobra por duración** — transferir 8 MB a través de Lambda a 256 MB de memoria costaría ~2 segundos de duración, comparado con ~10 ms para solo generar la URL

La solución con Presigned URL:
1. Lambda genera una URL firmada con clave HMAC-SHA256 (TTL = 15 minutos)
2. El navegador hace el PUT **directamente a S3** — sin tocar API Gateway ni Lambda
3. Lambda nunca procesa ni un byte de la imagen

Esto también significa que una foto de 50 MB podría subirse sin ningún cambio en la arquitectura.

**Seguridad:** la URL prefirmada solo es válida para `PUT` al objeto específico `fotos/{reporte_id}.jpg`. No puede usarse para acceder a otros objetos ni para hacer operaciones diferentes.

### 7.5 API Gateway REST vs HTTP API (v2)

**Decisión:** API Gateway REST (v1).

| Característica | REST API | HTTP API |
|---|---|---|
| Precio | $3.50 / millón | $1.00 / millón |
| Throttling por stage | ✅ Configurable | ✅ Configurable |
| Usage Plans y API Keys | ✅ Sí | ❌ No |
| Custom domain con ACM | ✅ Sí | ✅ Sí |
| Transformaciones de request/response | ✅ Mapping templates | ❌ No |
| Logging por método | ✅ Sí | Solo a nivel stage |

Para el volumen de este proyecto, el costo adicional de REST vs HTTP API es despreciable (<$0.02/mes). La diferencia justificada: REST API permite demostrar **Usage Plans y throttling por clave de API**, que son features de control de acceso relevantes para una aplicación de producción.

### 7.6 Región us-east-1

**Decisión:** us-east-1 (Virginia, EE. UU.)

- **Free Tier:** los límites del Free Tier son por región. us-east-1 es donde AWS tiene el inventario de hardware más amplio y los precios más bajos
- **Disponibilidad de servicios:** us-east-1 es la primera región donde AWS lanza nuevos servicios; todos los servicios usados en este proyecto están disponibles
- **Latencia desde México:** medición empírica desde Guadalajara → us-east-1: ~40-60 ms. Desde Guadalajara → us-west-2: ~20-30 ms. La diferencia de 20 ms es imperceptible para una aplicación web

Para una aplicación de producción dirigida exclusivamente a usuarios mexicanos, `us-east-1` o `us-west-2` serían equivalentes. Con CloudFront (CDN) como capa adicional, la latencia se reduciría a < 10 ms desde cualquier punto de México, independientemente de la región origen.

---

## 8. Análisis de costos

### 8.1 Dentro del Free Tier (primeros 12 meses)

AWS Free Tier incluye una capa de uso gratuito por 12 meses desde el registro de la cuenta, más algunos beneficios permanentes.

| Servicio | Límite Free Tier | Tipo | Uso estimado este proyecto | Costo mensual |
|---|---|---|---|---|
| **Lambda** | 1,000,000 invocaciones + 400,000 GB·s | Permanente | ~2,000 invocaciones × 256 MB × 0.2 s = 102 GB·s | **$0.00** |
| **DynamoDB** | 25 GB almacenamiento + 25 WCU + 25 RCU provisionados | Permanente | < 5 MB, < 100 ops/día | **$0.00** |
| **S3 (almacenamiento)** | 5 GB | 12 meses | < 500 MB (fotos) + 1 HTML | **$0.00** |
| **S3 (requests)** | 20,000 GET + 2,000 PUT | 12 meses | < 1,000 GET, < 200 PUT | **$0.00** |
| **API Gateway** | 1,000,000 llamadas REST | 12 meses | ~2,000 llamadas | **$0.00** |
| **CloudWatch Logs** | 5 GB ingestados | 12 meses | < 50 MB | **$0.00** |
| **Total** | | | | **$0.00/mes** |

### 8.2 Fuera del Free Tier — uso bajo (año 2+)

Estimación para **500 usuarios activos/mes**, ~5,000 reportes acumulados, ~15,000 invocaciones de Lambda/mes.

**Lambda:**
- Invocaciones: 15,000 × $0.20 / 1,000,000 = **$0.003**
- Duración: 15,000 × 0.256 GB × 0.2 s = 768 GB·s × $0.0000166667 = **$0.013**
- Subtotal: **$0.016/mes**

**DynamoDB on-demand:**
- Almacenamiento: 500 MB × $0.25/GB = **$0.125**
- Write Request Units: ~500/mes × $1.25/millón = **$0.001**
- Read Request Units: ~2,000/mes × $0.25/millón = **< $0.001**
- Subtotal: **$0.126/mes**

**S3 — fotos:**
- Almacenamiento: 5 GB × $0.023 = **$0.115**
- PUTs: 200 × $0.005/1,000 = **$0.001**
- GETs: 5,000 × $0.0004/1,000 = **$0.002**
- Subtotal: **$0.118/mes**

**S3 — web:**
- Almacenamiento: < 1 MB ≈ **$0.00**
- GETs: 10,000 × $0.0004/1,000 = **$0.004**
- Subtotal: **$0.004/mes**

**API Gateway REST:**
- 15,000 llamadas × $3.50/millón = **$0.053/mes**

**CloudWatch Logs:**
- ~100 MB × $0.50/GB = **$0.05/mes**

**Total año 2+, uso bajo: ~$0.37/mes ≈ $4.44/año**

### 8.3 Proyección de crecimiento

| Escenario | Usuarios activos/mes | Invocaciones Lambda/mes | Costo mensual estimado |
|---|---|---|---|
| Proyecto universitario | 50 | 1,000 | **$0.00** (dentro de Free Tier) |
| Piloto municipal | 500 | 15,000 | **$0.37** |
| Ciudad mediana | 5,000 | 150,000 | **$3.20** |
| Estado completo | 50,000 | 1,500,000 | **$29.50** |
| Escala nacional | 500,000 | 15,000,000 | **~$280** |

> Incluso a escala nacional (500,000 usuarios activos), el costo mensual de ~$280 es notablemente bajo en comparación con una infraestructura tradicional equivalente, que requeriría múltiples servidores de aplicaciones, balanceadores de carga y una base de datos relacional con réplicas.

### 8.4 Comparativa: Serverless vs Arquitectura tradicional

| Componente | Serverless (este proyecto) | Tradicional (EC2 + RDS + Nginx) |
|---|---|---|
| Servidor web | $0 (S3 estático) | $8/mes (t3.micro + Nginx) |
| Backend | $0.016/mes (Lambda) | incluido en EC2 |
| Base de datos | $0.13/mes (DynamoDB) | $27/mes (db.t3.micro Multi-AZ) |
| Balanceador | No requerido | $16/mes (ALB) |
| Certificado SSL | $0 (ACM + API GW) | $0 (Let's Encrypt) |
| **Total mensual (año 2+)** | **~$0.37** | **~$51** |
| **Total anual** | **~$4.44** | **~$612** |
| **Costo con 0 usuarios** | **$0** | **~$51/mes** |

La diferencia más importante no es el costo bajo uso sino el **costo en idle**: la arquitectura serverless cuesta exactamente **$0 cuando no hay tráfico**. Esto es crítico para un proyecto cívico que puede tener meses de uso muy bajo entre picos de actividad.

---

## 9. Pruebas de resiliencia

Las pruebas de resiliencia documentan cómo responde el sistema ante condiciones adversas: errores de entrada, sobrecarga, fallos de servicios dependientes y archivos malformados.

Para ejecutar las pruebas:
```bash
python3 resiliencia.py           # Todas las pruebas (interactivo)
python3 resiliencia.py --prueba 1  # Solo una prueba específica (1–4)
```

---

### 9.1 Prueba 1 — Payload inválido o malformado

**Escenario:** un cliente malicioso o un bug en el frontend envía datos incorrectos a `POST /reportes`.

**Casos probados:**

| Caso | Input | Respuesta esperada |
|---|---|---|
| Body vacío `{}` | `{}` | `400 {"error": "Campos requeridos faltantes: categoria, descripcion, latitud, longitud"}` |
| Categoría inválida | `"categoria": "extraterrestre"` | `400 {"error": "Categoría inválida. Opciones: basura, derrame, quema, tala, otro"}` |
| Coordenadas no numéricas | `"latitud": "veinte punto seis"` | `400 {"error": "latitud y longitud deben ser números"}` |
| Falta descripción | sin campo `descripcion` | `400 {"error": "Campos requeridos faltantes: descripcion"}` |

**Implementación en Lambda:**
```python
campos_requeridos = ["categoria", "descripcion", "latitud", "longitud"]
faltantes = [c for c in campos_requeridos if c not in body]
if faltantes:
    return _respuesta(400, {"error": f"Campos requeridos faltantes: {', '.join(faltantes)}"})
```

**Resultado:** Lambda devuelve HTTP 400 con mensaje descriptivo. DynamoDB nunca es consultado. El frontend muestra un toast de error al usuario.

---

### 9.2 Prueba 2 — Archivo demasiado grande o de tipo incorrecto

**Escenario:** el usuario intenta subir un PDF, un ejecutable, o una imagen de 50 MB.

**Barrera 1 — Frontend (primera línea de defensa):**
El código JavaScript valida antes de iniciar la subida:
```javascript
if (!file.type.startsWith("image/")) {
    showToast("Tipo de archivo no válido", "Solo se aceptan imágenes", "error");
    return;
}
if (file.size > 10 * 1024 * 1024) {
    showToast("Foto demasiado grande", `Máximo 10 MB`, "error");
    return;
}
```

**Barrera 2 — S3 (segunda línea de defensa):**
La Presigned URL se genera con `ContentType: image/jpeg`. Si el cliente envía un `Content-Type` diferente, S3 devuelve `HTTP 403 SignatureDoesNotMatch` porque el Content-Type forma parte de la firma HMAC.

**Mejora posible:** agregar `content-length-range` en las condiciones de la presigned URL para limitar el tamaño máximo a nivel de S3, independientemente del frontend:
```python
# Requiere generate_presigned_post en lugar de generate_presigned_url
s3.generate_presigned_post(
    Bucket=BUCKET,
    Key=foto_key,
    Conditions=[
        ["content-length-range", 1, 10 * 1024 * 1024],  # 1 B a 10 MB
        ["eq", "$Content-Type", "image/jpeg"],
    ],
    ExpiresIn=900,
)
```

**Resultado:** el archivo nunca llega a S3 en condiciones normales. Incluso si alguien bypasea el frontend, S3 rechaza la subida.

---

### 9.3 Prueba 3 — Sobrecarga de la API (throttling)

**Escenario:** 50 clientes simultáneos hacen requests al mismo tiempo.

**Comportamiento de API Gateway:**
- Límite por defecto de la cuenta: **10,000 req/s**
- Burst limit: **5,000 requests adicionales**
- Cuando se excede: devuelve `HTTP 429 Too Many Requests`

**Prueba ejecutada:** 50 requests GET concurrentes con `ThreadPoolExecutor`.

**Resultados esperados:**
- Con 50 requests concurrentes, todos deberían completarse exitosamente (muy por debajo del límite de 10,000 req/s)
- Latencia promedio: 200–500 ms
- Lambda escala automáticamente hasta 1,000 ejecuciones concurrentes por defecto en us-east-1

**Manejo en el frontend:**
```javascript
if (res.status === 429) {
    showToast("Servidor ocupado", "Intenta en unos segundos", "warning");
}
```

**Mitigaciones disponibles para escenarios más extremos:**
1. **CloudFront** delante de API Gateway: cachea las respuestas de `GET /reportes` por N segundos, reduciendo el load en Lambda y DynamoDB
2. **Usage Plans** en API Gateway: limita el número de requests por API key para prevenir abuso
3. **DynamoDB Accelerator (DAX)**: caché en memoria para lecturas repetidas (no necesario para el volumen actual)

---

### 9.4 Prueba 4 — Falla simulada de DynamoDB

**Escenario:** DynamoDB no responde o devuelve un error (ej. tabla eliminada accidentalmente, permisos IAM incorrectos).

**Nota:** DynamoDB tiene un **SLA de 99.99% de disponibilidad** (≤ 52 minutos de downtime permitido por año). Una falla real de DynamoDB es extremadamente rara. Esta prueba valida el manejo de errores del código, no la infraestructura de AWS.

**Implementación del manejo de errores en cada Lambda:**

```python
try:
    resp = tabla.scan(**scan_kwargs)
except ClientError as e:
    logger.error(f"DynamoDB scan error: {e.response['Error']['Code']}: {e}")
    return _respuesta(503, {
        "error": "No se pudo obtener la lista de reportes. Intenta de nuevo más tarde.",
        "detalle": e.response["Error"]["Code"],
    })
```

**Comportamiento garantizado:**
- Lambda **nunca** lanza una excepción no capturada → API Gateway siempre recibe una respuesta estructurada
- El error queda registrado en **CloudWatch Logs** con el código de error exacto para diagnóstico
- El frontend recibe `HTTP 503` con JSON → muestra un toast de error en lugar de una pantalla rota

**Resiliencia de DynamoDB a nivel de infraestructura:**
- Replica datos en **3 Availability Zones** automáticamente
- Soporta la falla completa de un AZ sin interrupción de servicio
- **Point-in-Time Recovery (PITR)** disponible: restaura la tabla a cualquier punto de los últimos 35 días

---

### 9.5 Resumen de mitigaciones implementadas

| Escenario | Capa de protección | Respuesta al usuario |
|---|---|---|
| Payload inválido | Lambda (validación de campos) | `HTTP 400` con mensaje descriptivo |
| Categoría fuera del enum | Lambda (whitelist) | `HTTP 400 "Categoría inválida"` |
| Foto de tipo incorrecto | Frontend (JS) + S3 (Content-Type en firma) | Toast de error, no se sube |
| Foto > 10 MB | Frontend (JS) | Toast de error antes de iniciar |
| DynamoDB no responde | Lambda (try/except ClientError) | `HTTP 503` + toast de error |
| API Gateway rate limit | API Gateway (throttling default) | `HTTP 429` + toast de error |
| API no configurada | Frontend (check de placeholder) | Mensaje de configuración, no pantalla rota |
| GPS no disponible | Frontend (catch de error de geolocation) | Inputs manuales de coordenadas |
| Foto no existe en S3 | Frontend (onerror en img tag) | `display:none`, no imagen rota |

---

## 10. Reflexión sobre computación sustentable

### 10.1 Huella de carbono del modelo serverless

La computación sustentable no se refiere únicamente a las aplicaciones que resuelven problemas ambientales, sino también a **cómo se ejecuta la computación misma**. EcoReporte Ciudadano fue diseñado considerando ambas dimensiones.

**Eficiencia energética del serverless vs siempre-encendido:**

Un servidor EC2 t3.micro en ejecución 24/7 consume aproximadamente 2-4 watts de energía independientemente de la carga. Con 0 usuarios, ese consumo es puro desperdicio.

Lambda, en contraste, consume **exactamente cero watts cuando no hay invocaciones**. El hardware físico que ejecuta las funciones está compartido entre miles de clientes de AWS, y el scheduler de AWS asigna esos recursos solo cuando hay trabajo real que hacer. La tasa de utilización de servidores en centros de datos de hiperescala como AWS es **~65%**, comparada con **~15%** en centros de datos corporativos tradicionales. Esto significa que el mismo trabajo computacional requiere 4× menos hardware cuando se ejecuta en AWS que en infraestructura propia.

**Energía renovable:**

AWS se comprometió a alcanzar 100% de energía renovable para sus operaciones globales para 2025. Los centros de datos de us-east-1 (región usada en este proyecto) operan parcialmente con energía solar y eólica. Publicaciones de AWS indican que el carbon intensity de AWS es significativamente menor que la media de la red eléctrica en EE. UU.

**Comparativa de emisiones estimadas:**

| Componente | Serverless | EC2 t3.micro (24/7) |
|---|---|---|
| Consumo energético base | 0 W (sin tráfico) | ~3 W |
| Consumo mensual (sin tráfico) | 0 kWh | ~2.2 kWh |
| CO₂ equivalente/mes (sin tráfico) | ~0 g | ~880 g (factor: 0.4 kg CO₂/kWh) |
| CO₂ equivalente/año | ~0 g – 50 g | ~10.6 kg |

Proyectando sobre 12 meses con uso esporádico (~80% del tiempo sin tráfico), la arquitectura serverless emite aproximadamente **50 g de CO₂ equivalente**, comparado con **10,600 g** de un servidor EC2 siempre activo. Una reducción de **99.5%**.

### 10.2 El proyecto como herramienta de acción climática

Más allá de su propio footprint, EcoReporte Ciudadano es un **multiplicador de acción ambiental**:

- **Reducción de emisiones locales:** La quema de residuos sólidos urbanos genera CO₂, metano y partículas negras (black carbon), un contaminante de corta vida con potencial de calentamiento 3,200 veces mayor que el CO₂ en 20 años. Reducir el tiempo de respuesta de las autoridades ante estos eventos tiene impacto climático directo.

- **Economía circular de información:** La geolocalización de tiraderos clandestinos facilita operativos de recolección más eficientes (rutas optimizadas, menor combustible quemado por los camiones de basura).

- **Empoderamiento ciudadano:** Estudios de ciencia ciudadana muestran que cuando las personas tienen herramientas para documentar y compartir problemas ambientales, aumenta su sentido de agencia y su disposición a participar en otras acciones climáticas.

### 10.3 Principios de diseño sustentable aplicados

| Principio | Implementación en EcoReporte |
|---|---|
| **Eficiencia por diseño** | Frontend de un solo archivo HTML (sin framework, sin transpilación, sin npm) |
| **Computación bajo demanda** | Lambda solo ejecuta cuando hay una request real |
| **Almacenamiento eficiente** | DynamoDB cobra solo por lo que se usa; S3 cobra por GB real almacenado |
| **Sin sobreaprovisionamiento** | No hay servidores con capacidad reservada que desperdician energía |
| **Transferencia directa** | Las fotos van del navegador directamente a S3 (presigned URL), sin intermediarios innecesarios |

---

## 11. Limitaciones y trabajo futuro

### 11.1 Limitaciones actuales

**Autenticación:** la API actualmente es pública y no requiere autenticación. Cualquier persona con la URL puede crear o modificar reportes. Para una versión de producción se debería implementar **Amazon Cognito** (autenticación OAuth con Google/Facebook) o al menos una validación básica por API Key.

**Moderación de contenido:** no hay filtrado de fotos ni texto inapropiado. Se podría integrar **Amazon Rekognition** para analizar imágenes automáticamente y rechazar contenido no relacionado con problemas ambientales.

**Almacenamiento de fotos:** las fotos se almacenan indefinidamente en S3. Sin una política de ciclo de vida, los costos de almacenamiento crecen linealmente. Se debería implementar una **S3 Lifecycle Policy** que mueva fotos viejas a S3 Glacier (80% más barato) después de 6 meses.

**Sin notificaciones:** cuando el status de un reporte cambia a "resuelto", el ciudadano que lo creó no recibe ninguna notificación. Se podría integrar **Amazon SNS** para enviar notificaciones por correo o SMS.

**Geolocalización en producción:** `Nominatim` (OpenStreetMap) tiene límites de rate para reverse geocoding. En producción debería usarse **Amazon Location Service** o un proveedor más robusto.

**Sin HTTPS para el frontend:** el S3 static website hosting sirve por HTTP, no HTTPS. Para producción se requiere CloudFront con un certificado ACM, que proporciona HTTPS sin costo adicional.

### 11.2 Mejoras de arquitectura para producción

```
Actual:          Internet → API GW → Lambda → DynamoDB
                           → S3 (fotos y web)

Producción:      Internet → CloudFront (CDN + HTTPS + cache)
                               ├── /api/* → API Gateway → Lambda → DynamoDB
                               │                        → S3 (fotos)
                               └── /*    → S3 (web, cache en CF)
                                          + Cognito (auth)
                                          + SNS (notificaciones)
                                          + Rekognition (moderación)
```

Con estas mejoras, el costo adicional estimado sería < $5/mes en escenarios de tráfico bajo, y la seguridad y usabilidad mejorarían significativamente.

### 11.3 Funcionalidades deseadas

1. **Estadísticas por municipio:** dashboard con gráficas de reportes por categoría, tiempo promedio de resolución, tendencias temporales
2. **Sistema de votos:** ciudadanos pueden "confirmar" un reporte existente para darle más visibilidad
3. **Integración con SEMARNAT/PROFEPA:** envío automático de reportes de derrames industriales a las autoridades federales correspondientes
4. **App nativa (PWA completa):** agregar `manifest.json` y Service Worker para instalación en móvil y funcionamiento offline
5. **Exportación de datos:** endpoint `GET /reportes.csv` para que investigadores y periodistas descarguen el dataset

---

## 12. Conclusiones

EcoReporte Ciudadano demuestra que es posible construir una aplicación web funcional, escalable y con costos operativos prácticamente nulos usando exclusivamente servicios gestionados de AWS. Los tres principios que guiaron el diseño — **pago por uso, sin servidores, infraestructura como código** — se cumplen en su totalidad.

Desde el punto de vista del ODS 13, el proyecto aporta una herramienta concreta de participación ciudadana alineada con las metas de sensibilización, documentación y alerta temprana. Desde el punto de vista de la computación sustentable, la arquitectura serverless reduce la huella de carbono del sistema en más del 99% comparada con una infraestructura tradicional equivalente.

La decisión de automatizar **el 100% de la infraestructura mediante scripts Python** (sin ningún clic en la consola web de AWS) no solo cumple con el requisito de la rúbrica, sino que también garantiza **reproducibilidad** y **trazabilidad**: cualquier persona puede replicar el entorno completo en menos de 5 minutos con un solo comando, y cualquier cambio en la infraestructura queda registrado en el historial de Git.

El proyecto fue construido considerando que los recursos computacionales son limitados y tienen un costo ambiental real. Cada decisión de arquitectura — desde usar Lambda en lugar de EC2, hasta servir el frontend desde S3 en lugar de un servidor Nginx — minimiza el desperdicio de cómputo y contribuye a que la operación de la aplicación sea lo más ligera posible, en coherencia con el mensaje ambiental que promueve.

---

*Documento preparado para la defensa del proyecto final de Computación Sustentable*  
*Todos los scripts, funciones Lambda, el frontend y este documento están disponibles en el repositorio del proyecto*
