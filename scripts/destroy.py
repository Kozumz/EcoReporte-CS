#!/usr/bin/env python3
"""
destroy.py — Elimina TODA la infraestructura de EcoReporte de AWS

Lee .ecoreporte_config.json para saber qué eliminar.
Pide confirmación antes de proceder.

Uso:
    python3 scripts/destroy.py
    python3 scripts/destroy.py --force   # sin confirmación
"""

import argparse
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

from dotenv import load_dotenv
load_dotenv()

DIR_BASE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(DIR_BASE, ".ecoreporte_config.json")
LAMBDAS     = ["crear_reporte", "listar_reportes", "actualizar_status"]
API_NOMBRE  = "EcoReporte API"


def _validar_credenciales() -> None:
    """Verifica que las 4 variables de AWS Academy estén presentes."""
    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan variables de entorno: {missing}")
        print("   Cópialas desde AWS Academy → AWS Details → Show")
        sys.exit(1)


def log(msg: str) -> None:
    print(msg, flush=True)


def vaciar_y_borrar_bucket(s3, nombre: str) -> None:
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=nombre):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=nombre,
                    Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                )
        s3.delete_bucket(Bucket=nombre)
        log(f"  ✅ S3 bucket eliminado: {nombre}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            log(f"  ℹ️  Bucket no encontrado (ya eliminado?): {nombre}")
        else:
            log(f"  ⚠️  Error eliminando bucket {nombre}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Eliminar infraestructura de EcoReporte")
    parser.add_argument("--force", action="store_true", help="No pedir confirmación")
    args = parser.parse_args()

    if not os.path.exists(CONFIG_FILE):
        log(f"No se encontró {CONFIG_FILE}. ¿Ya se ejecutó setup.py?")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    region     = cfg["region"]
    account_id = cfg["account_id"]

    log("\n" + "=" * 60)
    log("  EcoReporte — Teardown de infraestructura AWS")
    log("=" * 60)
    log(f"\nCuenta: {account_id} | Región: {region}")
    log(f"Se eliminarán:")
    log(f"  • DynamoDB tabla: {cfg['tabla_dynamo']}")
    log(f"  • S3 bucket fotos: {cfg['bucket_fotos']}")
    log(f"  • S3 bucket web: {cfg['bucket_web']}")
    nombres_fn = ", ".join(f"ecoreporte-{fn.replace('_', '-')}" for fn in LAMBDAS)
    log(f"  • Lambda functions: {nombres_fn}")
    log(f"  • API Gateway: {API_NOMBRE}")
    log(f"  ℹ️  IAM LabRole: NO se elimina (es compartido por AWS Academy)")

    if not args.force:
        resp = input("\n⚠️  ¿Confirmas la eliminación? Esto NO se puede deshacer. (escribe 'si'): ")
        if resp.strip().lower() != "si":
            log("Cancelado.")
            sys.exit(0)

    _validar_credenciales()

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    # ── DynamoDB ──
    log("\n[ 1/5 ] Eliminando tabla DynamoDB…")
    try:
        ddb = session.client("dynamodb", region_name=region)
        ddb.delete_table(TableName=cfg["tabla_dynamo"])
        log(f"  ✅ DynamoDB tabla eliminada")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            log("  ℹ️  Tabla no encontrada (ya eliminada?)")
        else:
            log(f"  ⚠️  Error: {e}")

    # ── S3 ──
    log("\n[ 2/5 ] Eliminando buckets S3…")
    s3 = session.client("s3", region_name=region)
    vaciar_y_borrar_bucket(s3, cfg["bucket_fotos"])
    vaciar_y_borrar_bucket(s3, cfg["bucket_web"])

    # ── Lambda ──
    log("\n[ 3/5 ] Eliminando Lambda functions…")
    lam = session.client("lambda", region_name=region)
    for fn in LAMBDAS:
        fn_name = f"ecoreporte-{fn.replace('_', '-')}"
        try:
            lam.delete_function(FunctionName=fn_name)
            log(f"  ✅ Lambda '{fn_name}' eliminada")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                log(f"  ℹ️  Lambda '{fn_name}' no encontrada")
            else:
                log(f"  ⚠️  Error eliminando {fn_name}: {e}")

    # ── IAM ──
    log("\n[ 4/5 ] IAM role…")
    log("  ℹ️  LabRole es un rol compartido de AWS Academy — no se elimina.")

    # ── API Gateway ──
    log("\n[ 5/5 ] Eliminando API Gateway…")
    apigw = session.client("apigateway", region_name=region)
    try:
        apis = apigw.get_rest_apis()["items"]
        api  = next((a for a in apis if a["name"] == API_NOMBRE), None)
        if api:
            apigw.delete_rest_api(restApiId=api["id"])
            log(f"  ✅ API Gateway '{API_NOMBRE}' eliminado")
        else:
            log("  ℹ️  API Gateway no encontrado")
    except ClientError as e:
        log(f"  ⚠️  Error eliminando API Gateway: {e}")

    # Limpiar config local
    os.remove(CONFIG_FILE)
    log(f"\n  ✅ {CONFIG_FILE} eliminado")

    log("\n" + "=" * 60)
    log("  ✅ TEARDOWN COMPLETO — infraestructura eliminada")
    log("=" * 60 + "\n")


if __name__ == "__main__":
    main()
