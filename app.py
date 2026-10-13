import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


# =========================================================
# CONFIGURACIÓN
# =========================================================

FLASHSCORE_URL = "https://m.flashscore.info/"

TOKEN = os.getenv("TOKEN", "")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))

# Días hacia adelante para buscar el próximo partido de la liga.
DIAS_BUSQUEDA_PROXIMO = 7

# Evita alertas viejas que Flashscore publica varias horas tarde.
# Un partido 0-0 solo genera alerta si comenzó hace menos de este límite.
MAX_HORAS_DESDE_INICIO_PARA_ALERTAR = float(
    os.getenv("MAX_HORAS_DESDE_INICIO_PARA_ALERTAR", "30")
)

# Zona horaria de Argentina.
ZONA_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")

# Ajuste manual por si Flashscore muestra horarios desplazados.
# Dejar en 0 salvo que sea necesario corregir el horario.
AJUSTE_HORAS_FLASHSCORE = int(os.getenv("AJUSTE_HORAS_FLASHSCORE", "0"))

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
    "CHINA PR": "CN",
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
    "REPUBLIC OF IRELAND": "IE",
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
    "KOREA REPUBLIC": "KR",
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

def ahora_argentina() -> datetime:
    return datetime.now(ZONA_ARGENTINA)


def hora_actual() -> str:
    return ahora_argentina().strftime("%d/%m/%Y %H:%M:%S")


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
    return any(palabra in texto for palabra in PALABRAS_AMISTOSOS)


# Se admiten todas las ligas adultas, salvo las categorías excluidas.
# Los filtros se aplican al nombre completo de la competición.
PATRONES_EXCLUIDOS = (
    r"\b(?:friendly|friendlies|amistos[oa]s?|exhibition)\b",
    r"\b(?:women|woman|womens|female|femenin[oa]s?|feminin[oa]s?|ladies|frauen|damen)\b",
    r"\b(?:u[ -]?(?:1[0-9]|2[0-3])|under[ -]?(?:1[0-9]|2[0-3])|sub[ -]?(?:1[0-9]|2[0-3]))\b",
    r"\b(?:youth|juvenil(?:es)?|junior(?:s)?|academy|academia|primavera)\b",
    r"\b(?:reserve(?:s)?|reserva(?:s)?|reserves league|segunda equipe|second team)\b",
    r"\b(?:futsal|beach soccer)\b",
)


def texto_sin_acentos(texto: str) -> str:
    return "".join(
        letra for letra in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(letra)
    )


def liga_permitida(nombre_completo: str) -> bool:
    nombre = texto_sin_acentos(nombre_completo)
    return not any(re.search(patron, nombre) for patron in PATRONES_EXCLUIDOS)


def limpiar_liga(h4: Tag) -> str:
    liga = h4.get_text(" ", strip=True)

    if liga.endswith(" Standings"):
        liga = liga[:-10].strip()

    return liga


def normalizar_liga(nombre: str) -> str:
    return " ".join(nombre.lower().replace("–", "-").split())


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


def obtener_hora_programada(enlace: Tag):
    for elemento in enlace.previous_siblings:
        if isinstance(elemento, Tag) and elemento.name in ("br", "h4"):
            break

        if isinstance(elemento, Tag) and elemento.name == "span":
            texto = elemento.get_text(" ", strip=True)
            try:
                return datetime.strptime(texto, "%H:%M").time()
            except ValueError:
                return None

    return None


def obtener_hora_partido(enlace: Tag):
    """
    Busca la hora HH:MM asociada al partido, también para partidos finalizados.
    """
    for elemento in enlace.previous_siblings:
        if isinstance(elemento, Tag) and elemento.name in ("br", "h4"):
            break

        if isinstance(elemento, Tag) and elemento.name == "span":
            texto = elemento.get_text(" ", strip=True)
            coincidencia = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", texto)

            if coincidencia:
                try:
                    return datetime.strptime(
                        coincidencia.group(0),
                        "%H:%M",
                    ).time()
                except ValueError:
                    pass

    return None


def datetime_inicio_partido(enlace: Tag, fecha_pagina: date):
    """
    Convierte la hora mostrada por Flashscore a hora Argentina.
    """
    hora = obtener_hora_partido(enlace)

    if hora is None:
        return None

    inicio = datetime.combine(
        fecha_pagina,
        hora,
        tzinfo=ZONA_ARGENTINA,
    ) + timedelta(hours=AJUSTE_HORAS_FLASHSCORE)

    ahora = ahora_argentina()

    if inicio > ahora + timedelta(minutes=30):
        inicio -= timedelta(days=1)

    return inicio


def es_alerta_reciente(inicio: datetime | None) -> bool:
    """
    Evita mandar partidos que Flashscore recién publica varias horas tarde.
    """
    if inicio is None:
        return False

    antiguedad = ahora_argentina() - inicio

    if antiguedad.total_seconds() < 0:
        return False

    return antiguedad <= timedelta(
        hours=MAX_HORAS_DESDE_INICIO_PARA_ALERTAR
    )


def id_desde_enlace(enlace: Tag) -> str:
    href = enlace.get("href", "")
    return href.strip("/").split("/")[-1]


def descargar_pagina(desplazamiento_dias: int = 0) -> BeautifulSoup:
    respuesta = requests.get(
        FLASHSCORE_URL,
        params={"d": desplazamiento_dias, "s": 1},
        headers=HEADERS,
        timeout=30,
    )
    respuesta.raise_for_status()
    return BeautifulSoup(respuesta.text, "html.parser")


def obtener_contenedor(soup: BeautifulSoup) -> Tag:
    contenedor = soup.find("div", id="score-data")

    if contenedor is None:
        raise RuntimeError(
            "Flashscore respondió, pero no apareció el bloque de resultados."
        )

    return contenedor


# =========================================================
# LEER LOS 0-0
# =========================================================

def obtener_partidos_cero_a_cero(
    soup: BeautifulSoup,
    fecha_pagina: date,
):
    contenedor = obtener_contenedor(soup)
    partidos = []

    for liga_h4 in contenedor.find_all("h4"):
        nombre_completo_liga = limpiar_liga(liga_h4)

        if not liga_permitida(nombre_completo_liga):
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
                    partido_id = id_desde_enlace(elemento)
                    inicio = datetime_inicio_partido(
                        elemento,
                        fecha_pagina,
                    )

                    if local and visitante and partido_id:
                        partidos.append(
                            {
                                "id": partido_id,
                                "pais": pais,
                                "bandera": bandera,
                                "liga": liga,
                                "liga_completa": nombre_completo_liga,
                                "liga_normalizada": normalizar_liga(
                                    nombre_completo_liga
                                ),
                                "local": local,
                                "visitante": visitante,
                                "inicio": inicio,
                                "reciente": es_alerta_reciente(inicio),
                            }
                        )

            elemento = elemento.find_next_sibling()

    return partidos


# =========================================================
# LEER PARTIDOS PROGRAMADOS
# =========================================================

def obtener_programados_de_pagina(
    soup: BeautifulSoup,
    fecha_pagina: date,
):
    contenedor = obtener_contenedor(soup)
    programados = []

    for liga_h4 in contenedor.find_all("h4"):
        nombre_completo_liga = limpiar_liga(liga_h4)

        if not liga_permitida(nombre_completo_liga):
            continue

        pais, liga = separar_pais_y_liga(nombre_completo_liga)
        elemento = liga_h4.find_next_sibling()

        while elemento is not None:
            if isinstance(elemento, Tag) and elemento.name == "h4":
                break

            if (
                isinstance(elemento, Tag)
                and elemento.name == "a"
                and "sched" in elemento.get("class", [])
            ):
                local, visitante = obtener_equipos(elemento)
                hora = obtener_hora_programada(elemento)
                partido_id = id_desde_enlace(elemento)

                if local and visitante and hora and partido_id:
                    kickoff = datetime.combine(
                        fecha_pagina,
                        hora,
                        tzinfo=ZONA_ARGENTINA,
                    ) + timedelta(hours=AJUSTE_HORAS_FLASHSCORE)

                    programados.append(
                        {
                            "id": partido_id,
                            "pais": pais,
                            "liga": liga,
                            "liga_completa": nombre_completo_liga,
                            "liga_normalizada": normalizar_liga(nombre_completo_liga),
                            "local": local,
                            "visitante": visitante,
                            "kickoff": kickoff,
                        }
                    )

            elemento = elemento.find_next_sibling()

    return programados


def obtener_todos_los_programados():
    hoy = ahora_argentina().date()
    programados = []

    for desplazamiento in range(DIAS_BUSQUEDA_PROXIMO + 1):
        soup = descargar_pagina(desplazamiento)
        fecha_pagina = hoy + timedelta(days=desplazamiento)

        programados.extend(
            obtener_programados_de_pagina(
                soup=soup,
                fecha_pagina=fecha_pagina,
            )
        )

        time.sleep(0.4)

    return programados


def buscar_proximo_partido(partido_00: dict, programados: list[dict]):
    ahora = ahora_argentina()
    liga_objetivo = partido_00["liga_normalizada"]

    candidatos = [
        partido
        for partido in programados
        if (
            partido["liga_normalizada"] == liga_objetivo
            and partido["kickoff"] > ahora
        )
    ]

    if not candidatos:
        return None

    return min(candidatos, key=lambda partido: partido["kickoff"])


# =========================================================
# MEMORIA
# =========================================================

def cargar_json_lista(ruta: Path) -> list:
    if not ruta.exists():
        return []

    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def guardar_json_lista(ruta: Path, datos: list) -> None:
    ruta.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cargar_avisados() -> set[str]:
    return set(str(item) for item in cargar_json_lista(ARCHIVO_AVISADOS))


def guardar_avisados(avisados: set[str]) -> None:
    guardar_json_lista(ARCHIVO_AVISADOS, sorted(avisados))


# =========================================================
# TELEGRAM
# =========================================================

def enviar_mensaje_telegram(mensaje: str) -> None:
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


def construir_alerta_00(partido: dict, proximo: dict | None) -> str:
    if partido["pais"]:
        linea_pais = f"{partido['bandera']} {partido['pais'].title()}"
    else:
        linea_pais = f"{partido['bandera']} Competición internacional"

    lineas = [
        "🚨 ALERTA 0-0",
        "",
        linea_pais,
        f"🏆 {partido['liga']}",
        "",
        f"⚽ {partido['local']} 0-0 {partido['visitante']}",
        "",
        "⏱ Partido finalizado",
    ]

    if proximo:
        faltan = proximo["kickoff"] - ahora_argentina()
        minutos = max(0, int(faltan.total_seconds() // 60))
        horas, mins = divmod(minutos, 60)

        if horas:
            texto_falta = f"{horas} h {mins} min"
        else:
            texto_falta = f"{mins} min"

        lineas.extend(
            [
                "",
                "━━━━━━━━━━━━━━",
                "",
                "🎯 PRÓXIMO PARTIDO DE LA LIGA",
                f"⚽ {proximo['local']} vs {proximo['visitante']}",
                (
                    "🕒 "
                    f"{proximo['kickoff'].strftime('%d/%m/%Y %H:%M')} "
                    "(hora Argentina)"
                ),
                f"⏳ Faltan aproximadamente {texto_falta}",
                "",
                "📌 Seguimiento: más de 0,5 gol en el primer tiempo",
            ]
        )
    else:
        lineas.extend(
            [
                "",
                "ℹ️ No encontré otro partido programado de esta liga "
                f"en los próximos {DIAS_BUSQUEDA_PROXIMO} días.",
            ]
        )

    return "\n".join(lineas)


# =========================================================
# REVISIÓN DE 0-0
# =========================================================

def revisar_partidos() -> None:
    print(f"\n[{hora_actual()}] Consultando Flashscore...")

    avisados = cargar_avisados()
    fecha_hoy = ahora_argentina().date()
    partidos = []
    # Revisar hoy y ayer para cubrir cruces de medianoche y retrasos.
    for desplazamiento in (-1, 0):
        fecha_pagina = fecha_hoy + timedelta(days=desplazamiento)
        soup = descargar_pagina(desplazamiento)
        encontrados = obtener_partidos_cero_a_cero(soup, fecha_pagina)
        print(f"{fecha_pagina}: {len(encontrados)} partidos 0-0 admitidos")
        partidos.extend(encontrados)

    print(
        f"Partidos finalizados 0-0 encontrados: {len(partidos)}"
    )

    # Evitar duplicados si Flashscore presenta un partido en ambas páginas.
    por_id = {partido["id"]: partido for partido in partidos}
    desconocidos = [
        partido for partido in por_id.values()
        if partido["id"] not in avisados
    ]

    if not desconocidos:
        print("No hay nuevos 0-0 para avisar (después de filtros y memoria).")
        return

    nuevos_partidos = []
    descartados_tarde = 0
    descartados_sin_hora = 0

    for partido in desconocidos:
        if partido["inicio"] is None:
            descartados_sin_hora += 1
            print(
                "Descartado 0-0 sin hora legible: "
                f"{partido['local']} vs {partido['visitante']} "
                f"({partido['liga_completa']})"
            )
            continue

        if not partido["reciente"]:
            descartados_tarde += 1
            antiguedad = ahora_argentina() - partido["inicio"]
            minutos = max(
                0,
                int(antiguedad.total_seconds() // 60),
            )
            print(
                "Descartada alerta vieja: "
                f"{partido['local']} 0-0 {partido['visitante']} — "
                f"inicio {partido['inicio'].strftime('%d/%m %H:%M')} — "
                f"hace aprox. {minutos} min"
            )
            continue

        nuevos_partidos.append(partido)

    if descartados_tarde:
        print(f"Alertas viejas descartadas: {descartados_tarde}")

    if descartados_sin_hora:
        print(
            "0-0 descartados porque Flashscore no mostró una hora "
            f"legible: {descartados_sin_hora}"
        )

    if not nuevos_partidos:
        print("No hay 0-0 recientes para avisar en esta revisión.")
        return

    print(
        "Buscando próximos partidos para "
        f"{len(nuevos_partidos)} nueva(s) alerta(s) reciente(s)..."
    )

    try:
        programados = obtener_todos_los_programados()
        print(f"Partidos programados encontrados: {len(programados)}")
    except Exception as error:
        print(f"No pude obtener los programados: {error}")
        programados = []

    enviados = 0

    for partido in nuevos_partidos:
        proximo = buscar_proximo_partido(partido, programados)

        mensaje = construir_alerta_00(partido, proximo)
        enviar_mensaje_telegram(mensaje)

        avisados.add(partido["id"])
        guardar_avisados(avisados)

        enviados += 1

        print(
            "Alerta enviada EN TIEMPO: "
            f"{partido['local']} 0-0 {partido['visitante']} "
            f"({partido['liga_completa']}) — "
            f"inicio {partido['inicio'].strftime('%H:%M')}"
        )

        if proximo:
            print(
                "Próximo partido guardado: "
                f"{proximo['local']} vs {proximo['visitante']} — "
                f"{proximo['kickoff'].strftime('%d/%m/%Y %H:%M')}"
            )
        else:
            print("No encontré próximo partido para esta liga.")

        time.sleep(1)

    print(f"Nuevas alertas enviadas: {enviados}")


# =========================================================
# PROGRAMA PRINCIPAL
# =========================================================

def main() -> None:
    if not TOKEN or CHAT_ID == 0:
        raise RuntimeError("Faltan TOKEN o CHAT_ID en los secretos de GitHub")
    print(f"[{hora_actual()}] Revisión única de Flashscore (GitHub Actions)")
    revisar_partidos()
    print("Revisión terminada")


if __name__ == "__main__":
    main()
