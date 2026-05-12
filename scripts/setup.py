#!/usr/bin/env python3
"""
setup.py — Despliegue automatizado de EcoReporte Ciudadano en AWS

Crea TODA la infraestructura y despliega el código sin intervención manual:
  1. DynamoDB table
  2. S3 buckets (fotos + web hosting)
  3. LabRole de AWS Academy (se detecta automáticamente, IAM restringido)
  4. Lambda functions (empaqueta y despliega)
  5. API Gateway REST API + rutas + CORS
  6. Inyecta URL de API en el frontend y lo sube a S3

Uso:
    python3 scripts/setup.py
    python3 scripts/setup.py --region us-west-2

Al terminar escribe .ecoreporte_config.json con todos los ARNs y URLs.

⚠️  AWS Academy: antes de ejecutar, copia las 4 credenciales desde
    AWS Academy → AWS Details → Cloud Access → Show
    y expórtalas como variables de entorno (o usa un archivo .env).
"""

import argparse
import json
import os
import sys
import time
import zipfile
import io
import textwrap

import boto3
from botocore.exceptions import ClientError

from dotenv import load_dotenv
load_dotenv()

# ── Configuración global ───────────────────────────────────────────────────────
TABLA_DYNAMO  = "ecoreporte-reportes"
API_NOMBRE    = "EcoReporte API"
LAMBDAS       = ["crear_reporte", "listar_reportes", "actualizar_status"]
CONFIG_FILE   = ".ecoreporte_config.json"
DIR_BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg: str) -> None:
    print(msg, flush=True)


def _validar_credenciales() -> None:
    """Verifica que las 4 variables de AWS Academy estén presentes antes de continuar."""
    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan variables de entorno: {missing}")
        print("   Cópialas desde AWS Academy → AWS Details → Show")
        sys.exit(1)


def get_account_id(session) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def nombre_bucket(prefijo: str, account_id: str) -> str:
    # Sufijo de 6 dígitos del account_id para unicidad global
    return f"{prefijo}-{account_id[-6:]}"


# ─────────────────────────────────────────────────────────────────────────────
# IAM: LabRole de AWS Academy (no se crea, ya existe)
# ─────────────────────────────────────────────────────────────────────────────
def obtener_rol_lambda(session) -> str:
    """
    AWS Academy no permite iam:CreateRole.
    Detecta automáticamente el ARN del LabRole preexistente.
    Si LAB_ROLE_ARN está definido en el entorno se usa directamente.
    """
    arn = os.getenv("LAB_ROLE_ARN")
    if arn:
        log(f"  ✅ LabRole desde .env: {arn}")
        return arn
    iam = session.client("iam")
    arn = iam.get_role(RoleName="LabRole")["Role"]["Arn"]
    log(f"  ✅ LabRole detectado automáticamente: {arn}")
    return arn


# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB
# ─────────────────────────────────────────────────────────────────────────────
def crear_dynamodb(session, region: str) -> str:
    client = session.client("dynamodb", region_name=region)
    try:
        resp = client.create_table(
            TableName=TABLA_DYNAMO,
            AttributeDefinitions=[
                {"AttributeName": "reporte_id", "AttributeType": "S"},
                {"AttributeName": "categoria",  "AttributeType": "S"},
                {"AttributeName": "fecha_creacion", "AttributeType": "S"},
                {"AttributeName": "status",     "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "reporte_id", "KeyType": "HASH"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "categoria-index",
                    "KeySchema": [
                        {"AttributeName": "categoria",     "KeyType": "HASH"},
                        {"AttributeName": "fecha_creacion","KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "status",        "KeyType": "HASH"},
                        {"AttributeName": "fecha_creacion","KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",  # on-demand — no hay que aprovisionar capacidad
        )
        arn = resp["TableDescription"]["TableArn"]
        # Esperar a que la tabla esté ACTIVE
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=TABLA_DYNAMO, WaiterConfig={"Delay": 3, "MaxAttempts": 20})
        log(f"  ✅ DynamoDB tabla '{TABLA_DYNAMO}' creada: {arn}")
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            arn = client.describe_table(TableName=TABLA_DYNAMO)["Table"]["TableArn"]
            log(f"  ℹ️  DynamoDB tabla ya existe: {arn}")
            return arn
        raise


# ─────────────────────────────────────────────────────────────────────────────
# S3
# ─────────────────────────────────────────────────────────────────────────────
def crear_bucket_fotos(session, region: str, account_id: str) -> str:
    nombre  = nombre_bucket("ecoreporte-fotos", account_id)
    s3      = session.client("s3", region_name=region)
    kwargs  = {"Bucket": nombre}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    try:
        s3.create_bucket(**kwargs)
        log(f"  ✅ S3 bucket fotos: s3://{nombre}")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            log(f"  ℹ️  S3 bucket fotos ya existe: s3://{nombre}")
        else:
            raise

    # CORS: permite PUT desde cualquier origen (el frontend hace el PUT de la foto)
    s3.put_bucket_cors(
        Bucket=nombre,
        CORSConfiguration={
            "CORSRules": [{
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "PUT", "HEAD"],
                "AllowedOrigins": ["*"],
                "MaxAgeSeconds": 3600,
            }]
        },
    )

    # Política: lectura pública de fotos (para mostrarlas en el mapa)
    politica = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadFotos",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{nombre}/fotos/*",
        }]
    })
    # Desbloquear acceso público primero
    s3.delete_public_access_block(Bucket=nombre)
    s3.put_bucket_policy(Bucket=nombre, Policy=politica)
    return nombre


def crear_bucket_web(session, region: str, account_id: str) -> tuple[str, str]:
    nombre = nombre_bucket("ecoreporte-web", account_id)
    s3     = session.client("s3", region_name=region)
    kwargs = {"Bucket": nombre}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    try:
        s3.create_bucket(**kwargs)
        log(f"  ✅ S3 bucket web: s3://{nombre}")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            log(f"  ℹ️  S3 bucket web ya existe: s3://{nombre}")
        else:
            raise

    # Desbloquear acceso público y poner política de lectura total
    s3.delete_public_access_block(Bucket=nombre)
    politica = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadWeb",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{nombre}/*",
        }]
    })
    s3.put_bucket_policy(Bucket=nombre, Policy=politica)

    # Habilitar static website hosting
    s3.put_bucket_website(
        Bucket=nombre,
        WebsiteConfiguration={
            "IndexDocument": {"Suffix": "index.html"},
            "ErrorDocument": {"Key": "error.html"},
        },
    )

    url_web = f"http://{nombre}.s3-website-{region}.amazonaws.com"
    log(f"  ✅ Static website habilitado: {url_web}")
    return nombre, url_web


# ─────────────────────────────────────────────────────────────────────────────
# Lambda functions
# ─────────────────────────────────────────────────────────────────────────────
def empaquetar_lambda(nombre_fn: str) -> bytes:
    """Crea un ZIP en memoria con el código de la Lambda."""
    ruta = os.path.join(DIR_BASE, "lambdas", nombre_fn, "lambda_function.py")
    buf  = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ruta, "lambda_function.py")
    buf.seek(0)
    return buf.read()


def crear_o_actualizar_lambda(session, nombre_fn: str, rol_arn: str,
                              bucket_fotos: str, region: str) -> str:
    client   = session.client("lambda", region_name=region)
    fn_name  = f"ecoreporte-{nombre_fn.replace('_', '-')}"
    zip_bytes = empaquetar_lambda(nombre_fn)

    env_vars = {
        "DYNAMODB_TABLE"  : TABLA_DYNAMO,
        "S3_BUCKET_FOTOS" : bucket_fotos,
        "AWS_REGION_NAME" : region,     # evitar colisión con la var reservada AWS_REGION
    }

    try:
        resp = client.create_function(
            FunctionName=fn_name,
            Runtime="python3.12",
            Role=rol_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=30,
            MemorySize=256,
            Environment={"Variables": env_vars},
            Description=f"EcoReporte — {nombre_fn}",
        )
        arn = resp["FunctionArn"]
        log(f"  ✅ Lambda '{fn_name}' creada")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            # Ya existe — actualizar código y configuración
            client.update_function_code(FunctionName=fn_name, ZipFile=zip_bytes)
            client.update_function_configuration(
                FunctionName=fn_name,
                Environment={"Variables": env_vars},
            )
            waiter = client.get_waiter("function_updated")
            waiter.wait(FunctionName=fn_name)
            arn = client.get_function(FunctionName=fn_name)["Configuration"]["FunctionArn"]
            log(f"  ✅ Lambda '{fn_name}' actualizada")
        else:
            raise
    return arn


# ─────────────────────────────────────────────────────────────────────────────
# API Gateway
# ─────────────────────────────────────────────────────────────────────────────
def _agregar_cors_options(apigw, rest_api_id: str, resource_id: str) -> None:
    """Agrega método OPTIONS con respuesta mock para CORS preflight."""
    try:
        apigw.put_method(
            restApiId=rest_api_id,
            resourceId=resource_id,
            httpMethod="OPTIONS",
            authorizationType="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise

    apigw.put_method_response(
        restApiId=rest_api_id, resourceId=resource_id, httpMethod="OPTIONS",
        statusCode="200",
        responseParameters={
            "method.response.header.Access-Control-Allow-Headers": False,
            "method.response.header.Access-Control-Allow-Methods": False,
            "method.response.header.Access-Control-Allow-Origin" : False,
        },
    )
    apigw.put_integration(
        restApiId=rest_api_id, resourceId=resource_id, httpMethod="OPTIONS",
        type="MOCK",
        requestTemplates={"application/json": '{"statusCode": 200}'},
    )
    apigw.put_integration_response(
        restApiId=rest_api_id, resourceId=resource_id, httpMethod="OPTIONS",
        statusCode="200",
        responseParameters={
            "method.response.header.Access-Control-Allow-Headers": "'Content-Type,Authorization'",
            "method.response.header.Access-Control-Allow-Methods": "'GET,POST,PUT,OPTIONS'",
            "method.response.header.Access-Control-Allow-Origin" : "'*'",
        },
    )


def _agregar_metodo_lambda(apigw, rest_api_id: str, resource_id: str,
                           http_method: str, lambda_arn: str, region: str, account_id: str) -> None:
    """Agrega un método HTTP con integración Lambda proxy."""
    try:
        apigw.put_method(
            restApiId=rest_api_id, resourceId=resource_id,
            httpMethod=http_method, authorizationType="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise

    # URI de invocación de Lambda
    uri = (f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions"
           f"/{lambda_arn}/invocations")

    apigw.put_integration(
        restApiId=rest_api_id, resourceId=resource_id,
        httpMethod=http_method,
        type="AWS_PROXY",
        integrationHttpMethod="POST",
        uri=uri,
    )


def crear_api_gateway(session, region: str, account_id: str,
                      lambda_arns: dict[str, str]) -> tuple[str, str]:
    """
    Crea el REST API con las siguientes rutas:
      POST   /reportes
      GET    /reportes
      PUT    /reportes/{reporte_id}/status

    Retorna (api_id, invoke_url)
    """
    apigw = session.client("apigateway", region_name=region)
    lam   = session.client("lambda",     region_name=region)

    # ── Crear o reusar API ──
    apis = apigw.get_rest_apis()["items"]
    api  = next((a for a in apis if a["name"] == API_NOMBRE), None)
    if api:
        api_id    = api["id"]
        root_id   = next(r["id"] for r in apigw.get_resources(restApiId=api_id)["items"]
                         if r["path"] == "/")
        log(f"  ℹ️  API Gateway ya existe: {api_id}")
    else:
        resp      = apigw.create_rest_api(
            name=API_NOMBRE,
            description="API REST para EcoReporte Ciudadano",
            endpointConfiguration={"types": ["REGIONAL"]},
        )
        api_id    = resp["id"]
        root_id   = apigw.get_resources(restApiId=api_id)["items"][0]["id"]
        log(f"  ✅ API Gateway creado: {api_id}")

    # ── /reportes ──
    recursos = {r["path"]: r["id"]
                for r in apigw.get_resources(restApiId=api_id)["items"]}

    if "/reportes" not in recursos:
        rec_reportes = apigw.create_resource(
            restApiId=api_id, parentId=root_id, pathPart="reportes"
        )["id"]
    else:
        rec_reportes = recursos["/reportes"]

    # POST /reportes → crear_reporte
    _agregar_metodo_lambda(apigw, api_id, rec_reportes, "POST",
                           lambda_arns["crear_reporte"], region, account_id)
    # GET  /reportes → listar_reportes
    _agregar_metodo_lambda(apigw, api_id, rec_reportes, "GET",
                           lambda_arns["listar_reportes"], region, account_id)
    # OPTIONS /reportes
    _agregar_cors_options(apigw, api_id, rec_reportes)

    # ── /reportes/{reporte_id} ──
    path_rid = "/reportes/{reporte_id}"
    if path_rid not in recursos:
        rec_rid = apigw.create_resource(
            restApiId=api_id, parentId=rec_reportes, pathPart="{reporte_id}"
        )["id"]
    else:
        rec_rid = recursos[path_rid]

    # ── /reportes/{reporte_id}/status ──
    path_status = "/reportes/{reporte_id}/status"
    if path_status not in recursos:
        rec_status = apigw.create_resource(
            restApiId=api_id, parentId=rec_rid, pathPart="status"
        )["id"]
    else:
        rec_status = recursos[path_status]

    # PUT /reportes/{reporte_id}/status → actualizar_status
    _agregar_metodo_lambda(apigw, api_id, rec_status, "PUT",
                           lambda_arns["actualizar_status"], region, account_id)
    _agregar_cors_options(apigw, api_id, rec_status)

    # ── Permisos: API Gateway puede invocar cada Lambda ──
    for nombre_fn, arn in lambda_arns.items():
        fn_name = f"ecoreporte-{nombre_fn.replace('_', '-')}"
        stmt_id = f"apigateway-invoke-{nombre_fn.replace('_', '-')}"
        try:
            lam.add_permission(
                FunctionName=fn_name,
                StatementId=stmt_id,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/*",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceConflictException":
                raise

    # ── Desplegar API ──
    apigw.create_deployment(
        restApiId=api_id,
        stageName="prod",
        stageDescription="Producción",
    )

    invoke_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/prod"
    log(f"  ✅ API Gateway desplegada: {invoke_url}")
    return api_id, invoke_url


# ─────────────────────────────────────────────────────────────────────────────
# Frontend
# ─────────────────────────────────────────────────────────────────────────────
def subir_frontend(session, region: str, bucket_web: str, api_url: str) -> None:
    """Inyecta la URL de la API en el HTML y lo sube a S3."""
    s3 = session.client("s3", region_name=region)

    html_path = os.path.join(DIR_BASE, "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Reemplazar el placeholder con la URL real de API Gateway
    html = html.replace("%%API_URL%%", api_url)

    s3.put_object(
        Bucket=bucket_web,
        Key="index.html",
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300",
    )

    # Página de error simple
    error_html = textwrap.dedent("""\
        <!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
        <title>Error — EcoReporte</title></head>
        <body style="font-family:sans-serif;text-align:center;padding:3rem">
        <h1>🌿 EcoReporte</h1><p>Página no encontrada.</p>
        <a href="/">Ir al inicio</a></body></html>
    """)
    s3.put_object(
        Bucket=bucket_web, Key="error.html",
        Body=error_html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
    )

    log(f"  ✅ Frontend subido a s3://{bucket_web}/index.html")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Despliegue de EcoReporte en AWS")
    parser.add_argument("--region", default="us-east-1", help="Región AWS (default: us-east-1)")
    args = parser.parse_args()
    region = args.region

    log("=" * 60)
    log("  EcoReporte Ciudadano — Setup automatizado")
    log("=" * 60)

    # Verificar que las credenciales de AWS Academy estén presentes
    _validar_credenciales()

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    account_id = get_account_id(session)
    log(f"\nCuenta AWS: {account_id} | Región: {region}\n")

    # 1. DynamoDB
    log("[ 1/6 ] Creando tabla DynamoDB…")
    tabla_arn = crear_dynamodb(session, region)

    # 2. S3 fotos
    log("\n[ 2/6 ] Creando bucket S3 para fotos…")
    bucket_fotos = crear_bucket_fotos(session, region, account_id)

    # 3. S3 web
    log("\n[ 3/6 ] Creando bucket S3 para frontend…")
    bucket_web, url_web = crear_bucket_web(session, region, account_id)

    # 4. LabRole (AWS Academy — IAM restringido, el rol ya existe)
    log("\n[ 4/6 ] Obteniendo rol de ejecución para Lambda…")
    rol_arn = obtener_rol_lambda(session)
    log("  ✅ Usando rol LabRole de AWS Academy (IAM restringido)")

    # 5. Lambdas
    log("\n[ 5/6 ] Empaquetando y desplegando Lambda functions…")
    lambda_arns = {}
    for fn in LAMBDAS:
        lambda_arns[fn] = crear_o_actualizar_lambda(session, fn, rol_arn, bucket_fotos, region)

    # 6. API Gateway + Frontend
    log("\n[ 6/6 ] Creando API Gateway y subiendo frontend…")
    api_id, api_url = crear_api_gateway(session, region, account_id, lambda_arns)
    subir_frontend(session, region, bucket_web, api_url)

    # ── Guardar config ──
    config = {
        "region"       : region,
        "account_id"   : account_id,
        "tabla_dynamo" : TABLA_DYNAMO,
        "bucket_fotos" : bucket_fotos,
        "bucket_web"   : bucket_web,
        "api_id"       : api_id,
        "api_url"      : api_url,
        "url_web"      : url_web,
        "lambda_arns"  : lambda_arns,
    }
    config_path = os.path.join(DIR_BASE, CONFIG_FILE)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    log("\n" + "=" * 60)
    log("  ✅ DESPLIEGUE COMPLETO")
    log("=" * 60)
    log(f"\n🌐 App web:  {url_web}")
    log(f"🔌 API URL:  {api_url}")
    log(f"📋 Config guardada en: {CONFIG_FILE}\n")

import re
with open("frontend/index.html", "r") as f:
    html = f.read()
html = html.replace("PLACEHOLDER_API_URL", api_gateway_url)
with open("frontend/index.html", "w") as f:
    f.write(html)
# Volver a subir a S3
s3.upload_file("frontend/index.html", bucket_web, "index.html",
    ExtraArgs={"ContentType": "text/html"})
print("  ✅ Frontend actualizado con URL del API")


if __name__ == "__main__":
    main()
