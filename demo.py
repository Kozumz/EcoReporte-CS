#!/usr/bin/env python3
"""
demo.py — Carga datos de ejemplo en EcoReporte Ciudadano

Inserta 8 reportes realistas en Jalisco, México para poder demostrar
la aplicación sin necesidad de que el profesor ingrese datos manualmente.

Uso:
    python3 demo.py              # insertar datos demo
    python3 demo.py --cleanup   # borrar SOLO los datos demo (no la infra)
    python3 demo.py --api-url https://xxx.execute-api.us-east-1.amazonaws.com/prod
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

from dotenv import load_dotenv
load_dotenv()

DIR_BASE    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DIR_BASE, ".ecoreporte_config.json")

# Marcador para identificar items demo y poder borrarlos
DEMO_TAG = "DEMO_ECOREPORTE"

# ─────────────────────────────────────────────────────────────────────────────
# Datos de ejemplo — Jalisco, México
# ─────────────────────────────────────────────────────────────────────────────
REPORTES_DEMO = [
    {
        "categoria"    : "basura",
        "descripcion"  : "Tiradero clandestino de basura doméstica y escombros a orilla del Río San Juan de Dios. Lleva más de dos semanas acumulándose y ya hay fauna nociva.",
        "latitud"      : 20.6736,
        "longitud"     : -103.3390,
        "municipio"    : "Guadalajara",
        "reportado_por": "Vecino Colonia Analco",
        "status"       : "pendiente",
        "dias_atras"   : 3,
    },
    {
        "categoria"    : "derrame",
        "descripcion"  : "Derrame de aceite industrial en el arroyo El Ahogado, proveniente de una empresa metalmecánica. El agua tiene color oscuro y olor fuerte.",
        "latitud"      : 20.6198,
        "longitud"     : -103.3700,
        "municipio"    : "Tlaquepaque",
        "reportado_por": "Pescador local",
        "status"       : "en_proceso",
        "dias_atras"   : 7,
    },
    {
        "categoria"    : "quema",
        "descripcion"  : "Quema ilegal de llantas y residuos plásticos en predio baldío. El humo negro afecta a la colonia Jardines del Bosque. Se reporta desde las 6 AM.",
        "latitud"      : 20.6955,
        "longitud"     : -103.4080,
        "municipio"    : "Zapopan",
        "reportado_por": "Residente Jardines del Bosque",
        "status"       : "resuelto",
        "dias_atras"   : 14,
    },
    {
        "categoria"    : "tala",
        "descripcion"  : "Tala de árboles maduros (ficus de +30 años) sin permiso municipal visible. Se están construyendo bardas en lo que era área verde del fraccionamiento.",
        "latitud"      : 20.7080,
        "longitud"     : -103.3960,
        "municipio"    : "Zapopan",
        "reportado_por": "Anónimo",
        "status"       : "pendiente",
        "dias_atras"   : 1,
    },
    {
        "categoria"    : "basura",
        "descripcion"  : "Contenedores de basura desbordados en mercado municipal desde hace 5 días. Proliferan ratas y cucarachas. El olor es insoportable para los comerciantes.",
        "latitud"      : 20.6515,
        "longitud"     : -103.3254,
        "municipio"    : "Tonalá",
        "reportado_por": "Comerciante Mercado Municipal",
        "status"       : "en_proceso",
        "dias_atras"   : 5,
    },
    {
        "categoria"    : "derrame",
        "descripcion"  : "Fuga de aguas residuales en calle Hidalgo. El drenaje lleva días derramando hacia la calle, creando riesgo sanitario. Hay niños jugando cerca.",
        "latitud"      : 20.6760,
        "longitud"     : -103.4200,
        "municipio"    : "Zapopan",
        "reportado_por": "Padre de familia",
        "status"       : "pendiente",
        "dias_atras"   : 2,
    },
    {
        "categoria"    : "otro",
        "descripcion"  : "Empresa constructora tira cemento líquido directamente al suelo sin contención. Se están afectando al menos 200 m² de suelo que antes era permeable.",
        "latitud"      : 20.6320,
        "longitud"     : -103.4500,
        "municipio"    : "Tlajomulco de Zúñiga",
        "reportado_por": "Ingeniero Ambiental (vecino)",
        "status"       : "pendiente",
        "dias_atras"   : 0,
    },
    {
        "categoria"    : "quema",
        "descripcion"  : "Quema de caña en campos agrícolas. El humo está afectando visibilidad en la carretera Guadalajara-Chapala. Se detectó desde las 14:00 hrs.",
        "latitud"      : 20.4850,
        "longitud"     : -103.2100,
        "municipio"    : "El Salto",
        "reportado_por": "Conductor de transporte",
        "status"       : "resuelto",
        "dias_atras"   : 10,
    },
]


def cargar_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ No se encontró {CONFIG_FILE}.")
        print("   Ejecuta primero: python3 scripts/setup.py")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def insertar_demos(cfg: dict, session) -> list[str]:
    """Inserta los reportes demo directamente en DynamoDB."""
    tabla   = session.resource("dynamodb", region_name=cfg["region"]).Table(cfg["tabla_dynamo"])
    ahora   = datetime.now(timezone.utc)

    ids_insertados = []
    print(f"\nInsertando {len(REPORTES_DEMO)} reportes de ejemplo en DynamoDB…\n")

    for i, r in enumerate(REPORTES_DEMO, 1):
        reporte_id     = str(uuid.uuid4())
        fecha_creacion = (ahora - timedelta(days=r["dias_atras"])).isoformat()
        foto_key       = f"fotos/{reporte_id}.jpg"
        foto_url       = (f"https://{cfg['bucket_fotos']}.s3.{cfg['region']}"
                         f".amazonaws.com/{foto_key}")

        item = {
            "reporte_id"    : reporte_id,
            "fecha_creacion": fecha_creacion,
            "categoria"     : r["categoria"],
            "descripcion"   : r["descripcion"],
            "latitud"       : str(r["latitud"]),
            "longitud"      : str(r["longitud"]),
            "municipio"     : r["municipio"],
            "reportado_por" : r["reportado_por"],
            "foto_key"      : foto_key,
            "foto_url"      : foto_url,
            "status"        : r["status"],
            "es_demo"       : DEMO_TAG,  # marca para cleanup selectivo
        }

        try:
            tabla.put_item(Item=item)
            emoji = {"basura":"🗑️", "derrame":"💧", "quema":"🔥", "tala":"🌲", "otro":"❓"}
            e = emoji.get(r["categoria"], "📍")
            print(f"  ✅ [{i}/{len(REPORTES_DEMO)}] {e}  {r['categoria'].upper():<10} "
                  f"{r['municipio']:<25} status={r['status']}")
            ids_insertados.append(reporte_id)
        except ClientError as e:
            print(f"  ❌ Error insertando reporte {i}: {e}")

    return ids_insertados


def limpiar_demos(cfg: dict, session) -> None:
    """Borra solo los items con el tag DEMO_ECOREPORTE."""
    ddb     = session.resource("dynamodb", region_name=cfg["region"])
    tabla   = ddb.Table(cfg["tabla_dynamo"])

    from boto3.dynamodb.conditions import Attr
    print("\nBuscando reportes demo para eliminar…")

    resp    = tabla.scan(FilterExpression=Attr("es_demo").eq(DEMO_TAG))
    items   = resp.get("Items", [])

    if not items:
        print("  ℹ️  No se encontraron reportes demo para eliminar.")
        return

    print(f"  Encontrados {len(items)} reportes demo. Eliminando…")
    for item in items:
        tabla.delete_item(Key={"reporte_id": item["reporte_id"]})

    print(f"  ✅ {len(items)} reportes demo eliminados.")
    print("  La infraestructura (DynamoDB, S3, Lambda, API) permanece intacta.")


def _validar_credenciales() -> None:
    """Verifica que las 4 variables de AWS Academy estén presentes."""
    required = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan variables de entorno: {missing}")
        print("   Cópialas desde AWS Academy → AWS Details → Show")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Carga datos de ejemplo en EcoReporte Ciudadano"
    )
    parser.add_argument("--cleanup", action="store_true",
                        help="Borrar datos demo (no borra la infraestructura)")
    parser.add_argument("--api-url", default=None,
                        help="URL de la API (alternativa a leer el config file)")
    args = parser.parse_args()

    _validar_credenciales()

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )

    cfg = cargar_config()
    if args.api_url:
        cfg["api_url"] = args.api_url

    print("=" * 55)
    print("  EcoReporte — Datos de demostración")
    print("=" * 55)
    print(f"  Tabla DynamoDB: {cfg['tabla_dynamo']}")
    print(f"  Región: {cfg['region']}")

    if args.cleanup:
        limpiar_demos(cfg, session)
    else:
        ids = insertar_demos(cfg, session)
        print(f"\n{'=' * 55}")
        print(f"  ✅ {len(ids)} reportes demo insertados exitosamente")
        print(f"{'=' * 55}")
        print(f"\n  🌐 Abre la app para verlos en el mapa:")
        print(f"     {cfg.get('url_web', '(ver .ecoreporte_config.json)')}\n")
        print(f"  Para limpiar los datos demo: python3 demo.py --cleanup\n")


if __name__ == "__main__":
    main()
