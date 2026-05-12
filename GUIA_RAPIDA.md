# EcoReporte Ciudadano — Guía rápida de ejecución

---

## Orden de ejecución (primera vez)

```bash
# 1. Instalar dependencias Python
pip install -r requirements.txt

# 2. Configurar credenciales AWS (solo una vez)
aws configure

# 3. Desplegar toda la infraestructura
python3 scripts/setup.py

# 4. Insertar datos de demo
python3 demo.py

# 5. Abrir la app (URL impresa por setup.py)
```

---

## Comandos de uso frecuente

```bash
# Despliegue completo automatizado
python3 scripts/setup.py

# Despliegue interactivo para el profesor (con pausas y explicaciones)
python3 demo_profesor/setup_interactivo.py
python3 demo_profesor/setup_interactivo.py --no-pausas   # sin pausas

# Datos de demo
python3 demo.py              # insertar 8 reportes de ejemplo
python3 demo.py --cleanup    # borrar solo los datos demo (mantiene infra)

# Pruebas de resiliencia
python3 resiliencia.py                # todas las pruebas
python3 resiliencia.py --prueba 1    # payload inválido
python3 resiliencia.py --prueba 2    # archivo incorrecto
python3 resiliencia.py --prueba 3    # throttling API Gateway
python3 resiliencia.py --prueba 4    # falla de DynamoDB

# Teardown (borra TODO en AWS)
python3 scripts/destroy.py           # pide confirmación
python3 scripts/destroy.py --force   # sin confirmación
```

---

## Archivos importantes

```
EcoReporte_Ciudadano/
│
├── .ecoreporte_config.json   ← GENERADO por setup.py. Contiene URLs, ARNs y
│                               nombres de todos los recursos creados en AWS.
│                               Lo leen demo.py, resiliencia.py y destroy.py.
│                               NO subir a git (.gitignore).
│
├── scripts/
│   ├── setup.py              ← Crea toda la infra AWS + despliega frontend.
│   │                           Ejecutar una vez (o de nuevo para actualizar).
│   └── destroy.py            ← Elimina todo lo creado por setup.py.
│
├── demo_profesor/
│   └── setup_interactivo.py  ← Igual que setup.py pero con explicaciones
│                               y pausas entre cada paso. Para la demo.
│
├── lambdas/
│   ├── crear_reporte/
│   │   └── lambda_function.py   ← POST /reportes
│   ├── listar_reportes/
│   │   └── lambda_function.py   ← GET  /reportes
│   └── actualizar_status/
│       └── lambda_function.py   ← PUT  /reportes/{id}/status
│
├── frontend/
│   └── index.html            ← SPA completa. Contiene %%API_URL%%
│                               que setup.py reemplaza con la URL real
│                               antes de subir el archivo a S3.
│
├── demo.py                   ← 8 reportes realistas de Jalisco.
│                               Usa .ecoreporte_config.json para saber
│                               a qué tabla de DynamoDB escribir.
│
├── resiliencia.py            ← 4 pruebas de falla. Usa la API real
│                               (necesita .ecoreporte_config.json).
│
├── requirements.txt          ← boto3, botocore, requests
├── .env.example              ← Referencia de variables de entorno
├── .gitignore                ← Excluye .ecoreporte_config.json y __pycache__
│
└── docs/
    └── documentacion.md      ← Documentación completa para el PDF.
```

---

## Variables de entorno

### Las que configuras tú (una sola vez con `aws configure`)

| Variable | Dónde se usa | Descripción |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | AWS CLI / boto3 | Access key de tu usuario IAM |
| `AWS_SECRET_ACCESS_KEY` | AWS CLI / boto3 | Secret key de tu usuario IAM |
| `AWS_DEFAULT_REGION` | AWS CLI / boto3 | Región por defecto (`us-east-1`) |

### Las que `setup.py` configura automáticamente en cada Lambda

| Variable | Ejemplo | Descripción |
|---|---|---|
| `DYNAMODB_TABLE` | `ecoreporte-reportes` | Nombre de la tabla donde se guardan los reportes |
| `S3_BUCKET_FOTOS` | `ecoreporte-fotos-123456` | Bucket donde se almacenan las fotos |
| `AWS_REGION_NAME` | `us-east-1` | Región de los recursos |

> Lambda recibe estas variables como variables de entorno configuradas en la función.
> No hay que setearlas manualmente — `setup.py` las asigna al crear/actualizar cada función.

### La que el frontend necesita

| Variable | Descripción |
|---|---|
| `%%API_URL%%` | Placeholder en `frontend/index.html`. `setup.py` lo reemplaza con la URL real de API Gateway antes de subir el HTML a S3. |

> Si abres `frontend/index.html` localmente (sin deploy), el placeholder no está reemplazado
> y la app muestra: *"La API no está configurada. Ejecuta `python3 scripts/setup.py`"*.

---

## Estructura de `.ecoreporte_config.json`

Este archivo se genera automáticamente al terminar `setup.py`. Ejemplo de contenido:

```json
{
  "region"       : "us-east-1",
  "account_id"   : "123456789012",
  "tabla_dynamo" : "ecoreporte-reportes",
  "bucket_fotos" : "ecoreporte-fotos-789012",
  "bucket_web"   : "ecoreporte-web-789012",
  "api_id"       : "abc1def2gh",
  "api_url"      : "https://abc1def2gh.execute-api.us-east-1.amazonaws.com/prod",
  "url_web"      : "http://ecoreporte-web-789012.s3-website-us-east-1.amazonaws.com",
  "lambda_arns"  : {
    "crear_reporte"    : "arn:aws:lambda:us-east-1:123456789012:function:ecoreporte-crear-reporte",
    "listar_reportes"  : "arn:aws:lambda:us-east-1:123456789012:function:ecoreporte-listar-reportes",
    "actualizar_status": "arn:aws:lambda:us-east-1:123456789012:function:ecoreporte-actualizar-status"
  }
}
```

---

## API endpoints

| Método | Ruta | Lambda | Descripción |
|---|---|---|---|
| `GET` | `/reportes` | `listar_reportes` | Lista todos los reportes |
| `GET` | `/reportes?categoria=basura` | `listar_reportes` | Filtra por categoría |
| `GET` | `/reportes?status=pendiente` | `listar_reportes` | Filtra por status |
| `POST` | `/reportes` | `crear_reporte` | Crea un reporte + devuelve presigned URL para foto |
| `PUT` | `/reportes/{id}/status` | `actualizar_status` | Cambia el status de un reporte |

### Prueba rápida de los endpoints (bash)

```bash
# Leer la URL del config
API=$(python3 -c "import json; print(json.load(open('.ecoreporte_config.json'))['api_url'])")

# Listar reportes
curl -s "$API/reportes" | python3 -m json.tool

# Crear un reporte
curl -s -X POST "$API/reportes" \
  -H "Content-Type: application/json" \
  -d '{"categoria":"basura","descripcion":"Prueba desde terminal","latitud":20.6597,"longitud":-103.3496,"municipio":"Guadalajara"}' \
  | python3 -m json.tool

# Actualizar status (reemplaza <ID> con un reporte_id real)
curl -s -X PUT "$API/reportes/<ID>/status" \
  -H "Content-Type: application/json" \
  -d '{"status":"resuelto"}' \
  | python3 -m json.tool
```

---

## Recursos creados en AWS

| Recurso | Nombre | Servicio |
|---|---|---|
| Tabla de reportes | `ecoreporte-reportes` | DynamoDB |
| Bucket de fotos | `ecoreporte-fotos-{últimos 6 del account_id}` | S3 |
| Bucket del sitio | `ecoreporte-web-{últimos 6 del account_id}` | S3 |
| Rol de ejecución | `ecoreporte-lambda-role` | IAM |
| Función crear | `ecoreporte-crear-reporte` | Lambda |
| Función listar | `ecoreporte-listar-reportes` | Lambda |
| Función actualizar | `ecoreporte-actualizar-status` | Lambda |
| API REST | `EcoReporte API` | API Gateway |

> El sufijo numérico de los buckets S3 es necesario porque los nombres de buckets son
> **globalmente únicos** en toda AWS. Se usa la segunda mitad del Account ID.

---

## Solución a problemas comunes

| Problema | Causa probable | Solución |
|---|---|---|
| `NoCredentialsError` al correr setup.py | AWS no está configurado | `aws configure` |
| `AccessDeniedException` | El usuario IAM no tiene permisos suficientes | Asignar `AdministratorAccess` al usuario |
| Bucket ya existe con error | El nombre está tomado por otra cuenta | Esto no debería pasar (se usa account_id como sufijo) |
| Lambda `ResourceConflictException` | La función ya existe | setup.py la actualiza automáticamente, no es un error fatal |
| API Gateway devuelve 500 | Error en el código Lambda | Revisar CloudWatch Logs: `aws logs tail /aws/lambda/ecoreporte-crear-reporte --follow` |
| Frontend muestra "API no configurada" | Se abrió `index.html` local en lugar de la URL de S3 | Usar la URL impresa por setup.py (`url_web`) |
| Foto no aparece en el mapa | La presigned URL expiró o el PUT falló | El reporte sí se creó; la foto es opcional |

### Ver logs de una Lambda en tiempo real

```bash
aws logs tail /aws/lambda/ecoreporte-crear-reporte    --follow
aws logs tail /aws/lambda/ecoreporte-listar-reportes  --follow
aws logs tail /aws/lambda/ecoreporte-actualizar-status --follow
```
