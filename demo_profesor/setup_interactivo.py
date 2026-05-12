#!/usr/bin/env python3
"""
setup_interactivo.py — Despliegue pedagógico de EcoReporte Ciudadano

Este script construye TODA la infraestructura paso a paso, explicando
en cada fase qué servicio AWS se está creando y por qué se eligió.

Pensado para una demostración en vivo ante el profesor.
El script hace una pausa antes de cada fase para que el docente
pueda leer la explicación y hacer preguntas.

Uso:
    python3 demo_profesor/setup_interactivo.py
    python3 demo_profesor/setup_interactivo.py --no-pausas   # modo continuo

⚠️  AWS Academy: exporta las 4 credenciales desde AWS Details → Show antes de ejecutar.
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

# Reutilizamos la lógica del script automatizado
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.setup import (
    TABLA_DYNAMO, API_NOMBRE, LAMBDAS, CONFIG_FILE, DIR_BASE,
    _validar_credenciales, get_account_id, nombre_bucket,
    crear_dynamodb, crear_bucket_fotos, crear_bucket_web,
    obtener_rol_lambda, crear_o_actualizar_lambda,
    crear_api_gateway, subir_frontend,
)

VERDE  = "\033[92m"
AZUL   = "\033[94m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET  = "\033[0m"


def titulo(texto: str) -> None:
    print(f"\n{NEGRITA}{AZUL}{'═' * 60}{RESET}")
    print(f"{NEGRITA}{AZUL}  {texto}{RESET}")
    print(f"{NEGRITA}{AZUL}{'═' * 60}{RESET}\n")


def subtitulo(texto: str) -> None:
    print(f"\n{NEGRITA}{AMARILLO}  ▶  {texto}{RESET}\n")


def info(texto: str) -> None:
    print(f"  {texto}")


def ok(texto: str) -> None:
    print(f"  {VERDE}✅ {texto}{RESET}")


def pausa(mensaje: str = "Presiona ENTER para continuar…") -> None:
    input(f"\n  {AMARILLO}⏸  {mensaje}{RESET}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pausas", action="store_true",
                        help="Ejecutar sin pausas interactivas")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    def esperar(msg="Presiona ENTER para continuar…"):
        if not args.no_pausas:
            pausa(msg)

    # ══════════════════════════════════════════════════════════
    titulo("EcoReporte Ciudadano — Demostración de despliegue AWS")
    # ══════════════════════════════════════════════════════════

    info("Bienvenido. Este script construirá toda la infraestructura de la")
    info("aplicación EcoReporte Ciudadano directamente desde código Python")
    info("usando el SDK boto3, sin tocar la consola web de AWS.")
    info("")
    info("Servicios que crearemos:")
    info("  1. DynamoDB  — base de datos NoSQL para los reportes")
    info("  2. S3         — almacenamiento de fotos y hosting del frontend")
    info("  3. IAM Role   — permisos mínimos para las funciones Lambda")
    info("  4. Lambda     — lógica de backend (Python 3.12, sin servidor)")
    info("  5. API Gateway— endpoints REST públicos para el frontend")

    esperar("Presiona ENTER para verificar credenciales AWS y comenzar…")

    # Verificar las 4 variables de AWS Academy antes de continuar
    _validar_credenciales()

    region = args.region
    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )
    try:
        account_id = get_account_id(session)
    except Exception as e:
        print(f"\n  ❌ Error de credenciales AWS: {e}")
        print("     Copia las credenciales desde AWS Academy → AWS Details → Show")
        sys.exit(1)

    ok(f"Credenciales válidas — Cuenta: {account_id} | Región: {region}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 1 — DynamoDB: base de datos NoSQL")
    # ──────────────────────────────────────────────────────────
    info("¿Por qué DynamoDB y no RDS?")
    info("  • Los reportes ciudadanos son documentos JSON (schema flexible).")
    info("  • DynamoDB escala automáticamente: de 0 a millones de reportes sin")
    info("    provisionar servidores. Con 'PAY_PER_REQUEST' no hay costo en idle.")
    info("  • En el Free Tier: 25 GB de almacenamiento + 25 unidades de capacidad")
    info("    provisionada — más que suficiente para este proyecto.")
    info("")
    info(f"  Tabla a crear: '{TABLA_DYNAMO}'")
    info("  PK: reporte_id (UUID)  |  GSIs: por categoría y por status")

    esperar()
    tabla_arn = crear_dynamodb(session, region)
    ok(f"Tabla DynamoDB lista: {tabla_arn}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 2 — S3: almacenamiento de fotos")
    # ──────────────────────────────────────────────────────────
    info("¿Por qué S3 para las fotos?")
    info("  • S3 es object storage altamente duradero (99.999999999% durabilidad).")
    info("  • Usamos 'Presigned URLs': la Lambda genera una URL temporal y el")
    info("    navegador sube la foto DIRECTAMENTE a S3, sin pasar por Lambda.")
    info("    Esto reduce latencia, costo y el límite de 6 MB de API Gateway.")
    info("  • Las fotos son públicas (para mostrarlas en el mapa) pero solo se")
    info("    pueden subir con la URL prefirmada (seguridad por obscuridad + TTL).")

    esperar()
    bucket_fotos = crear_bucket_fotos(session, region, account_id)
    ok(f"Bucket de fotos listo: s3://{bucket_fotos}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 3 — S3: hosting del frontend estático")
    # ──────────────────────────────────────────────────────────
    info("¿Por qué S3 para el frontend y no EC2 o Elastic Beanstalk?")
    info("  • El frontend es un único archivo HTML estático (sin servidor).")
    info("  • S3 Static Website Hosting sirve el HTML directamente desde S3,")
    info("    sin instancias EC2 que administrar ni costo de cómputo 24/7.")
    info("  • Costo: ~$0.023/GB/mes — prácticamente gratis para este proyecto.")

    esperar()
    bucket_web, url_web = crear_bucket_web(session, region, account_id)
    ok(f"Bucket web listo. URL del sitio: {url_web}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 4 — IAM LabRole: rol de ejecución para Lambda")
    # ──────────────────────────────────────────────────────────
    info("AWS Academy usa un entorno IAM restringido:")
    info("  • No se permite iam:CreateRole — no podemos crear roles propios.")
    info("  • AWS Academy provee un rol preconfigurado llamado 'LabRole'")
    info("    con permisos amplios para los servicios del laboratorio.")
    info("  • El script detecta el ARN del LabRole automáticamente via iam:GetRole.")
    info("  • El ARN cambia cada sesión de AWS Academy, de ahí la detección dinámica.")

    esperar()
    rol_arn = obtener_rol_lambda(session)
    ok(f"Usando rol LabRole de AWS Academy (IAM restringido): {rol_arn}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 5 — Lambda: funciones de backend sin servidor")
    # ──────────────────────────────────────────────────────────
    info("¿Por qué Lambda y no EC2?")
    info("  • Lambda cobra SOLO por ejecución (primer millón de invocaciones/mes gratis).")
    info("  • No hay servidor que administrar, parchear ni monitorear.")
    info("  • Escala de 0 a miles de ejecuciones simultáneas automáticamente.")
    info("")
    info("  Funciones a desplegar:")
    info("  • ecoreporte-crear-reporte   → POST /reportes")
    info("  • ecoreporte-listar-reportes → GET  /reportes")
    info("  • ecoreporte-actualizar-status → PUT /reportes/{id}/status")
    info("")
    info("  El script empaqueta cada función en un ZIP en memoria y la sube")
    info("  directamente a AWS via API, sin necesidad de S3 intermedio.")

    esperar()
    lambda_arns = {}
    for fn in LAMBDAS:
        lambda_arns[fn] = crear_o_actualizar_lambda(session, fn, rol_arn, bucket_fotos, region)
    ok("Las 3 funciones Lambda están activas")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 6 — API Gateway: endpoints REST públicos")
    # ──────────────────────────────────────────────────────────
    info("¿Por qué API Gateway REST y no HTTP API o ALB?")
    info("  • API Gateway REST ofrece throttling, logging y etapas de despliegue")
    info("    sin configuración adicional de infraestructura.")
    info("  • HTTP API (v2) es más barata pero con menos features para demostrar.")
    info("  • ALB requiere VPC y grupos de seguridad — innecesario para este proyecto.")
    info("")
    info("  Rutas a crear:")
    info("  POST   /reportes              → crear reporte + presigned URL")
    info("  GET    /reportes              → listar reportes (con filtros)")
    info("  PUT    /reportes/{id}/status  → actualizar status")
    info("  OPTIONS (todas las rutas)     → CORS preflight")

    esperar()
    api_id, api_url = crear_api_gateway(session, region, account_id, lambda_arns)
    ok(f"API Gateway lista: {api_url}")

    # ──────────────────────────────────────────────────────────
    subtitulo("PASO 7 — Frontend: inyección de URL e inyección a S3")
    # ──────────────────────────────────────────────────────────
    info("El HTML contiene el placeholder '%%API_URL%%'.")
    info("El script reemplaza ese placeholder con la URL real de API Gateway")
    info("y sube el archivo a S3 — así el frontend ya sabe a dónde llamar.")

    esperar()
    subir_frontend(session, region, bucket_web, api_url)
    ok("Frontend publicado")

    # ──────────────────────────────────────────────────────────
    # Guardar config
    config = {
        "region": region, "account_id": account_id,
        "tabla_dynamo": TABLA_DYNAMO,
        "bucket_fotos": bucket_fotos, "bucket_web": bucket_web,
        "api_id": api_id, "api_url": api_url, "url_web": url_web,
        "lambda_arns": lambda_arns,
    }
    config_path = os.path.join(DIR_BASE, CONFIG_FILE)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # ══════════════════════════════════════════════════════════
    titulo("✅ DESPLIEGUE COMPLETO — RESUMEN")
    # ══════════════════════════════════════════════════════════

    print(f"""
  {'─' * 55}
  COMPONENTE          SERVICIO AWS     ESTADO
  {'─' * 55}
  Base de datos       DynamoDB         ✅ Activa
  Almacén de fotos    S3 (privado)     ✅ Activo
  Hosting web         S3 (público)     ✅ Activo
  Lógica backend      Lambda (×3)      ✅ Desplegada
  API REST            API Gateway      ✅ Desplegada
  {'─' * 55}

  🌐 Aplicación web:  {url_web}
  🔌 API endpoint:    {api_url}
  📋 Config:          {CONFIG_FILE}

  Próximos pasos:
  • Ejecuta 'python3 demo.py' para insertar datos de ejemplo
  • Abre la URL de la app en tu navegador
  • Ejecuta 'python3 resiliencia.py' para ver las pruebas de resiliencia
    """)


if __name__ == "__main__":
    main()
