"""
Lambda: crear_reporte
---------------------
Crea un nuevo reporte ambiental ciudadano en DynamoDB y genera una
URL prefirmada para que el frontend suba la foto directamente a S3.

Endpoint : POST /reportes
Body JSON : {
    "categoria"     : "basura" | "derrame" | "quema" | "tala" | "otro",
    "descripcion"   : str,
    "latitud"       : float,
    "longitud"      : float,
    "municipio"     : str  (opcional),
    "reportado_por" : str  (opcional, default "Anónimo")
}
Respuesta 201: {
    "reporte_id"   : str (UUID),
    "presigned_url": str (PUT URL válida 15 min para subir la foto),
    "foto_url"     : str (URL pública final de la foto en S3),
    "mensaje"      : str
}
"""

import json
import uuid
import os
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

TABLA_NOMBRE  = os.environ["DYNAMODB_TABLE"]
BUCKET_FOTOS  = os.environ["S3_BUCKET_FOTOS"]
REGION        = os.environ.get("AWS_REGION", "us-east-1")
URL_EXPIRA_SEG = 900  # 15 minutos

CATEGORIAS_VALIDAS = {"basura", "derrame", "quema", "tala", "otro"}


def _cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET,PUT",
    }


def _respuesta(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event, context):
    """
    Punto de entrada principal de la Lambda.

    Parámetros
    ----------
    event   : dict  Evento de API Gateway (proxy integration)
    context : LambdaContext

    Retorna
    -------
    dict  Respuesta HTTP con statusCode, headers y body JSON
    """
    # --- Preflight CORS ---
    if event.get("httpMethod") == "OPTIONS":
        return _respuesta(200, {"mensaje": "ok"})

    # --- Parsear body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _respuesta(400, {"error": "Body JSON inválido"})

    # --- Validar campos requeridos ---
    campos_requeridos = ["categoria", "descripcion", "latitud", "longitud"]
    faltantes = [c for c in campos_requeridos if c not in body]
    if faltantes:
        return _respuesta(400, {
            "error": f"Campos requeridos faltantes: {', '.join(faltantes)}"
        })

    categoria = body["categoria"].lower().strip()
    if categoria not in CATEGORIAS_VALIDAS:
        return _respuesta(400, {
            "error": f"Categoría inválida. Opciones: {', '.join(CATEGORIAS_VALIDAS)}"
        })

    try:
        latitud  = float(body["latitud"])
        longitud = float(body["longitud"])
    except (TypeError, ValueError):
        return _respuesta(400, {"error": "latitud y longitud deben ser números"})

    # --- Construir el item ---
    reporte_id     = str(uuid.uuid4())
    fecha_creacion = datetime.now(timezone.utc).isoformat()
    foto_key       = f"fotos/{reporte_id}.jpg"
    # URL pública de la foto (existirá una vez que el frontend haga el PUT)
    foto_url       = f"https://{BUCKET_FOTOS}.s3.{REGION}.amazonaws.com/{foto_key}"

    item = {
        "reporte_id"    : reporte_id,
        "fecha_creacion": fecha_creacion,
        "categoria"     : categoria,
        "descripcion"   : str(body["descripcion"])[:2000],
        "latitud"       : str(latitud),   # DynamoDB no soporta float nativo → guardamos como string
        "longitud"      : str(longitud),
        "municipio"     : str(body.get("municipio", "Desconocido"))[:100],
        "reportado_por" : str(body.get("reportado_por", "Anónimo"))[:100],
        "foto_key"      : foto_key,
        "foto_url"      : foto_url,
        "status"        : "pendiente",    # pendiente | en_proceso | resuelto
    }

    # --- Guardar en DynamoDB ---
    try:
        tabla = dynamodb.Table(TABLA_NOMBRE)
        tabla.put_item(Item=item)
        logger.info(f"Reporte creado: {reporte_id} | {categoria} | {item['municipio']}")
    except ClientError as e:
        logger.error(f"DynamoDB error: {e}")
        return _respuesta(503, {
            "error": "No se pudo guardar el reporte. Intenta de nuevo más tarde.",
            "detalle": str(e.response["Error"]["Code"]),
        })

    # --- Generar presigned URL para subir la foto ---
    try:
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket"     : BUCKET_FOTOS,
                "Key"        : foto_key,
                "ContentType": "image/jpeg",
            },
            ExpiresIn=URL_EXPIRA_SEG,
        )
    except ClientError as e:
        logger.warning(f"No se pudo generar presigned URL: {e}")
        # El reporte ya está guardado; la foto es opcional
        presigned_url = None

    return _respuesta(201, {
        "reporte_id"   : reporte_id,
        "presigned_url": presigned_url,
        "foto_url"     : foto_url,
        "mensaje"      : "Reporte creado exitosamente",
    })
