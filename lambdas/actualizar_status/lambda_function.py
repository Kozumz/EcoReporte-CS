"""
Lambda: actualizar_status
--------------------------
Actualiza el status de un reporte ambiental existente.
Útil para que autoridades municipales marquen un reporte como atendido.

Endpoint : PUT /reportes/{reporte_id}/status
Body JSON : { "status": "pendiente" | "en_proceso" | "resuelto" }
Respuesta 200: {
    "reporte_id"    : str,
    "status_anterior": str,
    "status_nuevo"  : str,
    "mensaje"       : str
}
Errores:
    400 — status inválido o body mal formado
    404 — reporte_id no existe
    503 — error de DynamoDB
"""

import json
import os
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb     = boto3.resource("dynamodb")
TABLA_NOMBRE = os.environ["DYNAMODB_TABLE"]
STATUS_VALIDOS = {"pendiente", "en_proceso", "resuelto"}


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
    Actualiza el campo 'status' de un reporte en DynamoDB.

    Usa UpdateItem con ConditionExpression para garantizar que el reporte
    existe antes de modificarlo, evitando creaciones accidentales.

    Parámetros
    ----------
    event   : dict  Evento de API Gateway con pathParameters.reporte_id
    context : LambdaContext

    Retorna
    -------
    dict  Respuesta HTTP con status anterior y nuevo
    """
    if event.get("httpMethod") == "OPTIONS":
        return _respuesta(200, {"mensaje": "ok"})

    # --- Obtener reporte_id de la ruta ---
    path_params = event.get("pathParameters") or {}
    reporte_id  = path_params.get("reporte_id", "").strip()

    if not reporte_id:
        return _respuesta(400, {"error": "reporte_id requerido en la ruta"})

    # --- Parsear body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _respuesta(400, {"error": "Body JSON inválido"})

    nuevo_status = str(body.get("status", "")).lower().strip()
    if nuevo_status not in STATUS_VALIDOS:
        return _respuesta(400, {
            "error": f"Status inválido. Opciones: {', '.join(sorted(STATUS_VALIDOS))}"
        })

    tabla = dynamodb.Table(TABLA_NOMBRE)

    # --- Leer status actual (para incluirlo en la respuesta) ---
    try:
        get_resp = tabla.get_item(Key={"reporte_id": reporte_id})
    except ClientError as e:
        logger.error(f"DynamoDB get_item error: {e}")
        return _respuesta(503, {"error": "Error al consultar la base de datos"})

    item = get_resp.get("Item")
    if not item:
        return _respuesta(404, {
            "error": f"Reporte '{reporte_id}' no encontrado"
        })

    status_anterior = item.get("status", "desconocido")

    # --- Actualizar status en DynamoDB ---
    try:
        tabla.update_item(
            Key={"reporte_id": reporte_id},
            UpdateExpression="SET #s = :nuevo_status",
            ExpressionAttributeNames={"#s": "status"},   # 'status' es palabra reservada
            ExpressionAttributeValues={":nuevo_status": nuevo_status},
            ConditionExpression="attribute_exists(reporte_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _respuesta(404, {"error": f"Reporte '{reporte_id}' no encontrado"})
        logger.error(f"DynamoDB update_item error: {e}")
        return _respuesta(503, {"error": "Error al actualizar el reporte"})

    logger.info(f"Status actualizado: {reporte_id} | {status_anterior} → {nuevo_status}")

    return _respuesta(200, {
        "reporte_id"     : reporte_id,
        "status_anterior": status_anterior,
        "status_nuevo"   : nuevo_status,
        "mensaje"        : f"Status actualizado a '{nuevo_status}'",
    })
