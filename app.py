import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


# =========================================================
# CONFIGURACIÓN
# =========================================================

FLASHSCORE_URL = "https://m.flashscore.info/"

# Estas dos variables se cargarán desde Render.
TOKEN = os.getenv("TOKEN", "")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))

# Revisar cada 5 minutos.
INTERVALO_SEGUNDOS = 5 * 60

# Guarda los partidos ya enviados para no repetirlos.
ARCHIVO_AVISADOS = Path("avisados.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

PALABRAS_AMISTOSOS = (
    "friendly",
    "friendlies",
    "club friendly",
    "international friendly",
    "amistoso",
    "amistosos",
    "exhibition",
)

CODIGOS_PAISES = {
    "ARGENTINA": "AR",
    "AUSTRALIA": "AU",
    "AUSTRIA": "AT",
    "BELARUS": "BY",
    "BELGIUM": "BE",
    "BHUTAN": "BT",
    "BOLIVIA": "BO",
    "BRAZIL": "BR",
    "BULGARIA": "BG",
    "CANADA": "CA",
    "CHILE": "CL",
    "CHINA": "CN",
    "COLOMBIA": "CO",
    "COSTA RICA": "CR",
    "CROATIA": "HR",
    "CZECH REPUBLIC": "CZ",
    "DENMARK": "DK",
    "ECUADOR": "EC",
    "EGYPT": "EG",
    "EL SALVADOR": "SV",
    "ENGLAND": "GB",
    "ESTONIA": "EE",
    "FINLAND": "FI",
    "FRANCE": "FR",
    "GERMANY": "DE",
    "GREECE": "GR",
    "GUATEMALA": "GT",
    "HONDURAS": "HN",
    "HUNGARY": "HU",
    "ICELAND": "IS",
    "INDIA": "IN",
    "INDONESIA": "ID",
    "IRELAND": "IE",
    "ISRAEL": "IL",
    "ITALY": "IT",
    "JAPAN": "JP",
    "KAZAKHSTAN": "KZ",
    "LATVIA": "LV",
    "LITHUANIA": "LT",
    "MEXICO": "MX",
    "MOLDOVA": "MD",
    "MOROCCO": "MA",
    "NETHERLANDS": "NL",
    "NEW ZEALAND": "NZ",
    "NICARAGUA": "NI",
    "NORTHERN IRELAND": "GB",
    "NORWAY": "NO",
    "PANAMA": "PA",
    "PARAGUAY": "PY",
    "PERU": "PE",
    "POLAND": "PL",
    "PORTUGAL": "PT",
    "ROMANIA": "RO",
    "RUSSIA": "RU",
    "SAUDI ARABIA": "SA",
    "SCOTLAND": "GB",
    "SERBIA": "RS",
    "SLOVAKIA": "SK",
    "SLOVENIA": "SI",
    "SOUTH AFRICA": "ZA",
    "SOUTH KOREA": "KR",
    "SPAIN": "ES",
    "SWEDEN": "SE",
    "SWITZERLAND": "CH",
    "TURKEY": "TR",
    "UKRAINE": "UA",
    "UNITED ARAB EMIRATES": "AE",
    "URUGUAY": "UY",
    "USA": "US",
    "UNITED STATES": "US",
    "VENEZUELA": "VE",
    "VIETNAM": "VN",
    "WALES": "GB",
}

EMOJIS_REGIONES = {
    "AFRICA": "🌍",
    "ASIA": "🌏",
    "EUROPE": "🇪🇺",
    "WORLD": "🌍",
    "SOUTH AMERICA": "🌎",
    "NORTH & CENTRAL AMERICA": "🌎",
}


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def hora_actual() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def bandera_desde_codigo(codigo: str) -> str:
    if len(codigo) != 2:
        return "🌍"

    return "".join(
        chr(ord(letra) + 127397)
        for letra in codigo.upper()
    )


def obtener_bandera(pais: str) -> str:
    pais_mayuscula = pais.upper().strip()

    if pais_mayuscula in EMOJIS_REGIONES:
        return EMOJIS_REGIONES[pais_mayuscula]

    codigo = CODIGOS_PAISES.get(pais_mayuscula)

    if not codigo:
        return "🌍"

    return bandera_desde_codigo(codigo)


def separar_pais_y_liga(nombre_completo: str):
    if ":" not in nombre_completo:
        return "", nombre_completo.strip()

    pais, liga = nombre_completo.split(":", 1)

    return pais.strip(), liga.strip()


def es_amistoso(nombre_liga: str) -> bool:
    texto = nombre_liga.lower()

    return any(
        palabra in texto
        for palabra in PALABRAS_AMISTOSOS
    )


def limpiar_liga(h4: Tag) -> str:
    liga = h4.get_text(" ", strip=True)

    if liga.endswith(" Standings"):
        liga = liga[:-10].strip()

    return liga


def obtener_equipos(enlace_resultado: Tag):
    partes = []

    for elemento in enlace_resultado.previous_siblings:
        if isinstance(elemento, Tag) and elemento.name in ("br", "h4"):
            break

        if isinstance(elemento, Tag):
            if elemento.name in ("span", "img"):
                continue

            texto = elemento.get_text(" ", strip=True)

        elif isinstance(elemento, NavigableString):
            texto = str(elemento).strip()

        else:
            texto = ""

        if texto:
            partes.append(texto)

    texto_partido = " ".join(reversed(partes))
    texto_partido = " ".join(texto_partido.split())

    if " - " not in texto_partido:
        return None, None

    local, visitante = texto_partido.rsplit(" - ", 1)

    return local.strip(), visitante.strip()


# =========================================================
# LEER FLASHSCORE
# =========================================================

def obtener_partidos_cero_a_cero():
    respuesta = requests.get(
        FLASHSCORE_URL,
        headers=HEADERS,
        timeout=30,
    )

    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "html.parser")
    contenedor = soup.find("div", id="score-data")

    if contenedor is None:
        raise RuntimeError(
            "Flashscore respondió, pero no apareció el bloque de resultados."
        )

    partidos = []

    for liga_h4 in contenedor.find_all("h4"):
        nombre_completo_liga = limpiar_liga(liga_h4)

        if es_amistoso(nombre_completo_liga):
            continue

        pais, liga = separar_pais_y_liga(nombre_completo_liga)
        bandera = obtener_bandera(pais)

        elemento = liga_h4.find_next_sibling()

        while elemento is not None:
            if isinstance(elemento, Tag) and elemento.name == "h4":
                break

            if (
                isinstance(elemento, Tag)
                and elemento.name == "a"
                and "fin" in elemento.get("class", [])
            ):
                resultado = elemento.get_text(" ", strip=True)

                if resultado == "0-0":
                    local, visitante = obtener_equipos(elemento)

                    if local and visitante:
                        enlace = elemento.get("href", "")
                        partido_id = enlace.strip("/").split("/")[-1]

                        if partido_id:
                            partidos.append(
                                {
                                    "id": partido_id,
                                    "pais": pais,
                                    "bandera": bandera,
                                    "liga": liga,
                                    "liga_completa": nombre_completo_liga,
                                    "local": local,
                                    "visitante": visitante,
                                }
                            )

            elemento = elemento.find_next_sibling()

    return partidos


# =========================================================
# MEMORIA: EVITAR AVISOS REPETIDOS
# =========================================================

def cargar_avisados() -> set[str]:
    if not ARCHIVO_AVISADOS.exists():
        return set()

    try:
        contenido = ARCHIVO_AVISADOS.read_text(encoding="utf-8")
        datos = json.loads(contenido)

        if isinstance(datos, list):
            return set(str(item) for item in datos)

    except (OSError, json.JSONDecodeError):
        pass

    return set()


def guardar_avisados(avisados: set[str]) -> None:
    ARCHIVO_AVISADOS.write_text(
        json.dumps(
            sorted(avisados),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# =========================================================
# TELEGRAM
# =========================================================

def enviar_telegram(partido: dict) -> None:
    if partido["pais"]:
        linea_pais = f"{partido['bandera']} {partido['pais'].title()}"
    else:
        linea_pais = f"{partido['bandera']} Competición internacional"

    mensaje = (
        "🚨 ALERTA 0-0\n\n"
        f"{linea_pais}\n"
        f"🏆 {partido['liga']}\n\n"
        f"⚽ {partido['local']} 0-0 {partido['visitante']}\n\n"
        "⏱ Partido finalizado"
    )

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    respuesta = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": mensaje,
        },
        timeout=30,
    )

    respuesta.raise_for_status()

    datos = respuesta.json()

    if not datos.get("ok"):
        raise RuntimeError(
            f"Telegram respondió con un error: {datos}"
        )


# =========================================================
# REVISIÓN
# =========================================================

def revisar_partidos() -> None:
    print(f"\n[{hora_actual()}] Consultando Flashscore...")

    avisados = cargar_avisados()
    partidos = obtener_partidos_cero_a_cero()

    print(
        f"Partidos finalizados 0-0 encontrados: {len(partidos)}"
    )

    nuevos = 0

    for partido in partidos:
        partido_id = partido["id"]

        if partido_id in avisados:
            continue

        enviar_telegram(partido)

        avisados.add(partido_id)
        guardar_avisados(avisados)

        nuevos += 1

        print(
            "Alerta enviada: "
            f"{partido['local']} 0-0 {partido['visitante']} "
            f"({partido['liga_completa']})"
        )

        time.sleep(1)

    if nuevos == 0:
        print("No hay nuevos 0-0 para avisar.")
    else:
        print(f"Nuevas alertas enviadas: {nuevos}")


# =========================================================
# PROGRAMA PRINCIPAL
# =========================================================

def main() -> None:
    if not TOKEN:
        print("ERROR: falta la variable de entorno TOKEN.")
        return

    if CHAT_ID == 0:
        print("ERROR: falta la variable de entorno CHAT_ID.")
        return

    print("============================================")
    print("Detector Flashscore 0-0 iniciado")
    print("Revisión automática cada 5 minutos")
    print("Amistosos excluidos")
    print("Banderas activadas")
    print("============================================")

    while True:
        try:
            revisar_partidos()

        except requests.RequestException as error:
            print(f"[{hora_actual()}] Error de conexión: {error}")

        except Exception as error:
            print(f"[{hora_actual()}] Error inesperado: {error}")

        print(f"[{hora_actual()}] Próxima revisión en 5 minutos.")
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    main()