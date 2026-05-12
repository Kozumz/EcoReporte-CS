# 🌿 EcoReporte Ciudadano

App web (PWA-friendly) para reportar problemas ambientales locales con foto, ubicación GPS y categoría. Los reportes aparecen en un mapa público. Alineado con el **ODS 13 — Acción Climática**.

---

> ⚠️ **AWS Academy**
>
> Antes de correr cualquier script, copia las 4 credenciales desde:
> **AWS Academy → AWS Details → Cloud Access → Show**
>
> ```bash
> export AWS_ACCESS_KEY_ID=...
> export AWS_SECRET_ACCESS_KEY=...
> export AWS_SESSION_TOKEN=...
> export AWS_DEFAULT_REGION=us-east-1
> ```
>
> El `SESSION_TOKEN` es obligatorio y cambia cada sesión.
> El `LAB_ROLE_ARN` se detecta automáticamente — no necesitas configurarlo.

---

## Arquitectura

```
Navegador
  │
  ├──GET/POST/PUT──► API Gateway (REST)
  │                       │
  │                  ┌────▼────────────────────────────────┐
  │                  │ Lambda Functions (Python 3.12)       │
  │                  │  • crear_reporte   (POST /reportes) │
  │                  │  • listar_reportes (GET  /reportes) │
  │                  │  • actualizar_status (PUT /…/status)│
  │                  └────┬──────────────┬─────────────────┘
  │                       │              │
  │                  ┌────▼────┐   ┌────▼────────┐
  │                  │DynamoDB │   │  S3 (fotos) │
  │                  │reportes │   │  privado    │
  │                  └─────────┘   └────┬────────┘
  │                                     │ presigned PUT URL
  └──PUT foto directo──────────────────►│
  
  Frontend: S3 Static Website Hosting (ecoreporte-web-XXXXXX)
```

## Stack AWS

| Servicio | Uso | Por qué |
|---|---|---|
| DynamoDB | Tabla de reportes | NoSQL flexible, serverless, Free Tier generoso |
| S3 (fotos) | Almacenamiento de imágenes | Durabilidad 11 nines, presigned URLs |
| S3 (web) | Hosting del frontend | Sin servidor, ~$0 para tráfico bajo |
| Lambda | Backend sin servidor | Pago por invocación, escala a 0 |
| API Gateway | REST API pública | Throttling integrado, CORS, SSL |

## Requisitos previos

```bash
# Python 3.11+
python3 --version

# AWS CLI configurado con credenciales válidas
aws configure
aws sts get-caller-identity   # verificar credenciales

# Instalar dependencias Python
pip install -r requirements.txt
```

## Despliegue rápido (automatizado)

```bash
# 1. Clonar repositorio
git clone <url-del-repo>
cd EcoReporte_Ciudadano

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Desplegar toda la infraestructura en AWS
python3 scripts/setup.py

# 4. Cargar datos de ejemplo
python3 demo.py

# 5. Abrir la URL que imprime el script en el navegador
```

## Despliegue pedagógico (para demostración)

```bash
# Script interactivo con explicaciones en cada paso
python3 demo_profesor/setup_interactivo.py

# Para ejecutar sin pausas
python3 demo_profesor/setup_interactivo.py --no-pausas
```

## Estructura del proyecto

```
EcoReporte_Ciudadano/
├── lambdas/
│   ├── crear_reporte/
│   │   └── lambda_function.py     # POST /reportes
│   ├── listar_reportes/
│   │   └── lambda_function.py     # GET  /reportes
│   └── actualizar_status/
│       └── lambda_function.py     # PUT  /reportes/{id}/status
├── frontend/
│   └── index.html                 # SPA con Leaflet.js
├── scripts/
│   ├── setup.py                   # Despliegue automatizado
│   └── destroy.py                 # Teardown completo
├── demo_profesor/
│   └── setup_interactivo.py       # Versión pedagógica del setup
├── demo.py                        # 8 reportes de ejemplo en Jalisco
├── resiliencia.py                 # Pruebas de resiliencia
├── requirements.txt
└── .env.example
```

## API Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/reportes` | Listar todos los reportes |
| `GET` | `/reportes?categoria=basura` | Filtrar por categoría |
| `GET` | `/reportes?status=pendiente` | Filtrar por status |
| `POST` | `/reportes` | Crear nuevo reporte |
| `PUT` | `/reportes/{id}/status` | Actualizar status |

### POST /reportes — Body

```json
{
  "categoria"    : "basura | derrame | quema | tala | otro",
  "descripcion"  : "Descripción del problema",
  "latitud"      : 20.6597,
  "longitud"     : -103.3496,
  "municipio"    : "Guadalajara",
  "reportado_por": "Anónimo"
}
```

### POST /reportes — Respuesta 201

```json
{
  "reporte_id"   : "uuid-v4",
  "presigned_url": "https://s3.amazonaws.com/...",
  "foto_url"     : "https://s3.amazonaws.com/ecoreporte-fotos-XXXX/fotos/uuid.jpg",
  "mensaje"      : "Reporte creado exitosamente"
}
```

## Flujo de subida de foto

```
Frontend
  1. POST /reportes (datos del reporte, sin foto)
  2. Recibe presigned_url de la respuesta
  3. PUT directo a presigned_url (foto JPEG, máx 10 MB)
  4. La foto ya es pública en S3 y aparece en el mapa
```

## Demo de datos de ejemplo

```bash
# Insertar 8 reportes realistas de Jalisco
python3 demo.py

# Limpiar los datos demo sin borrar la infraestructura
python3 demo.py --cleanup
```

## Pruebas de Resiliencia

```bash
# Todas las pruebas
python3 resiliencia.py

# Prueba específica
python3 resiliencia.py --prueba 1   # Payload inválido
python3 resiliencia.py --prueba 2   # Archivo incorrecto
python3 resiliencia.py --prueba 3   # Throttling API Gateway
python3 resiliencia.py --prueba 4   # Falla de DynamoDB
```

| Escenario | Comportamiento | Mitigación |
|---|---|---|
| DynamoDB no responde | Lambda devuelve HTTP 503 con JSON de error | Try/except ClientError, mensaje amigable |
| Archivo > 10 MB o no JPEG | S3 rechaza con 403 (ContentType mismatch) | Validación en frontend + Conditions en presigned URL |
| API Gateway throttled | HTTP 429 Too Many Requests | Retry exponencial en frontend |
| Payload inválido | HTTP 400 con campo `error` descriptivo | Validación de campos en Lambda antes de DynamoDB |

## Teardown (eliminar infraestructura)

```bash
python3 scripts/destroy.py          # pide confirmación
python3 scripts/destroy.py --force  # sin confirmación
```

## Variables de entorno de las Lambdas

Las Lambdas se configuran automáticamente por `setup.py`. Para referencia:

| Variable | Ejemplo |
|---|---|
| `DYNAMODB_TABLE` | `ecoreporte-reportes` |
| `S3_BUCKET_FOTOS` | `ecoreporte-fotos-123456` |
| `AWS_REGION_NAME` | `us-east-1` |

## Análisis de costos

### Free Tier (12 meses)

| Servicio | Free Tier | Uso estimado | Costo |
|---|---|---|---|
| Lambda | 1M invocaciones/mes | ~1,000 req/mes | **$0** |
| DynamoDB | 25 GB + 25 RCU/WCU | < 1 MB | **$0** |
| S3 | 5 GB + 20K GET + 2K PUT | < 1 GB | **$0** |
| API Gateway | 1M llamadas/mes (REST) | ~1,000/mes | **$0** |
| **Total Free Tier** | | | **$0/mes** |

### Fuera del Free Tier (año 2+)

| Servicio | Precio | Uso estimado/mes | Costo/mes |
|---|---|---|---|
| Lambda | $0.20/M invocaciones | 10,000 req | ~$0.002 |
| DynamoDB | $0.25/GB-mes | 100 MB | ~$0.025 |
| S3 | $0.023/GB-mes | 5 GB fotos | ~$0.115 |
| API Gateway | $3.50/M llamadas | 10,000 req | ~$0.035 |
| **Total año 2+** | | | **~$0.18/mes** |

> La aplicación está diseñada para ser prácticamente gratuita en el Free Tier
> y de muy bajo costo en producción real.

---

Proyecto final — Computación Sustentable | ODS 13 Acción Climática
# EcoReporte-CS
# EcoReporte-CS
# EcoReporte-CS
