"""
Carga la hoja "SolicitudesCitas" del Google Sheet "calificacion proveedores"
usando credenciales de una cuenta de servicio (Service Account) de Google.

Requiere la variable de entorno KEY_API_GOOGLE_SHEETS_DRIVE con el JSON
completo de la cuenta de servicio.
"""

import json
import os
import subprocess
import sys
import importlib.util

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

NOMBRE_ARCHIVO_POR_DEFECTO = "calificacion proveedores"
NOMBRE_HOJA_POR_DEFECTO = "SolicitudesCitas"
VARIABLE_ENTORNO_CREDENCIALES = "KEY_API_GOOGLE_SHEETS_DRIVE"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def _asegurar_dependencias() -> None:
    """Instala las librerías necesarias si no están disponibles."""
    paquetes = {"gspread": "gspread", "google-api-python-client": "googleapiclient"}
    for paquete, modulo in paquetes.items():
        if importlib.util.find_spec(modulo) is None:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", paquete])


def _obtener_credenciales() -> Credentials:
    """Lee y valida el JSON de la cuenta de servicio desde la variable de entorno."""
    valor = os.environ.get(VARIABLE_ENTORNO_CREDENCIALES)
    if not valor:
        raise RuntimeError(f'No se encontró la variable de entorno "{VARIABLE_ENTORNO_CREDENCIALES}".')

    try:
        info = json.loads(valor)
    except json.JSONDecodeError:
        raise RuntimeError(f'La variable "{VARIABLE_ENTORNO_CREDENCIALES}" no contiene un JSON válido.')

    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _buscar_spreadsheet_id(credentials: Credentials, nombre_archivo: str) -> str:
    """Busca en Google Drive el ID del spreadsheet más reciente que coincida con el nombre."""
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    nombre_escapado = nombre_archivo.replace("'", "\\'")
    query = (
        f"name = '{nombre_escapado}' and "
        "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    )

    resultado = drive.files().list(
        q=query,
        fields="files(id,name,modifiedTime)",
        orderBy="modifiedTime desc",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    archivos = resultado.get("files", [])
    if not archivos:
        raise FileNotFoundError(
            f'No se encontró el archivo "{nombre_archivo}" compartido con la cuenta de servicio.'
        )
    return archivos[0]["id"]


def _hoja_a_dataframe(worksheet: gspread.Worksheet) -> pd.DataFrame:
    """Convierte los valores de una hoja en un DataFrame, rellenando filas incompletas."""
    valores = worksheet.get_all_values()
    if not valores:
        return pd.DataFrame()

    ancho = max(len(fila) for fila in valores)
    encabezados = valores[0] + [f"columna_{i + 1}" for i in range(len(valores[0]), ancho)]
    filas = [fila + [None] * (ancho - len(fila)) for fila in valores[1:]]
    return pd.DataFrame(filas, columns=encabezados)


def cargar_solicitudes_citas(
    nombre_archivo: str = NOMBRE_ARCHIVO_POR_DEFECTO,
    nombre_hoja: str = NOMBRE_HOJA_POR_DEFECTO,
) -> pd.DataFrame:
    """Punto de entrada principal: devuelve la hoja indicada como DataFrame de pandas."""
    _asegurar_dependencias()
    credentials = _obtener_credenciales()
    spreadsheet_id = _buscar_spreadsheet_id(credentials, nombre_archivo)

    gc = gspread.authorize(credentials)
    worksheet = gc.open_by_key(spreadsheet_id).worksheet(nombre_hoja)
    return _hoja_a_dataframe(worksheet)


if __name__ == "__main__":
    df_solicitudes_citas = cargar_solicitudes_citas()
    print(df_solicitudes_citas)
