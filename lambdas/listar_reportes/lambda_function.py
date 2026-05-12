"""
Lambda: listar_reportes
------------------------
Devuelve todos los reportes ambientales almacenados en DynamoDB,
con filtros opcionales por categoría y/o status.

Endpoint : GET /reportes
Params   : ?categoria=basura  (opcional)
           ?status=pendiente  (opcional)
           ?limit=100         (opcional, default 500)
Respuesta 200: {
    "reportes": [ {reporte_id, fecha_creacion, categoria, descripcion,
                   latitud, longitud, municipio, foto_url, status, ...}, ... ],
    "total"   : int
}
"""

import json
import os
import logging

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb   = boto3.resource("dynamodb")
TABLA_NOMBRE = os.environ["DYNAMODB_TABLE"]
LIMIT_MAX    = 500


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
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def lambda_handler(event, context):
    """
    Lista reportes con filtros opcionales.

    Usa Scan de DynamoDB con FilterExpression cuando se reciben filtros.
    Para producción real se usaría Query sobre un GSI; Scan es aceptable
    para el volumen esperado en este proyecto (< 10 000 items).

    Parámetros
    ----------
    event   : dict  Evento de API Gateway
    context : LambdaContext

    Retorna
    -------
    dict  Respuesta HTTP con lista de reportes
    """
    if event.get("httpMethod") == "OPTIONS":
        return _respuesta(200, {"mensaje": "ok"})

    params = event.get("queryStringParameters") or {}
    categoria_filtro = params.get("categoria", "").lower().strip()
    status_filtro    = params.get("status", "").lower().strip()

    try:
        limit = min(int(params.get("limit", LIMIT_MAX)), LIMIT_MAX)
    except (ValueError, TypeError):
        limit = LIMIT_MAX

    tabla = dynamodb.Table(TABLA_NOMBRE)

    # Construir filtros opcionales para el Scan
    filtros = []
    if categoria_filtro:
        filtros.append(Attr("categoria").eq(categoria_filtro))
    if status_filtro:
        filtros.append(Attr("status").eq(status_filtro))

    scan_kwargs = {"Limit": limit}
    if filtros:
        expr = filtros[0]
        for f in filtros[1:]:
            expr = expr & f
        scan_kwargs["FilterExpression"] = expr

    # DynamoDB Scan puede requerir múltiples páginas (paginación automática)
    reportes = []
    try:
        while True:
            resp = tabla.scan(**scan_kwargs)
            reportes.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp or len(reportes) >= limit:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except ClientError as e:
        logger.error(f"DynamoDB scan error: {e}")
        return _respuesta(503, {
            "error": "No se pudo obtener la lista de reportes. Intenta de nuevo.",
            "detalle": str(e.response["Error"]["Code"]),
        })

    # Ordenar por fecha_creacion descendente (más recientes primero)
    reportes.sort(key=lambda r: r.get("fecha_creacion", ""), reverse=True)

    logger.info(f"Reportes devueltos: {len(reportes)} | filtros: {scan_kwargs.get('FilterExpression', 'ninguno')}")

    return _respuesta(200, {
        "reportes": reportes[:limit],
        "total"   : len(reportes),
    })
