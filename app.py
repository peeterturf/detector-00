import json
import os
import time
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

# Flashscore se consulta cada 5 minutos.
INTERVALO_CONSULTA_SEGUNDOS = 5 * 60

# Los recordatorios se revisan internamente cada 15 segundos.
# Esta revisión NO consulta Flashscore y no consume API.
INTERVALO_RECORDATORIOS_SEGUNDOS = 15

# Días hacia adelante para buscar el próximo partido de la liga.
DIAS_BUSQUEDA_PROXIMO = 7

# Zona horaria de Argentina.
ZONA_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")

# Ajuste manual por si Flashscore muestra horarios desplazados.
# Primero dejalo en 0. Si el horario aparece corrido, después lo ajustamos en Render.
AJUSTE_HORAS_FLASHSCORE = int(os.getenv("AJUSTE_HORAS_FLASHSCORE", "0"))

ARCHIVO_AVISADOS = Path("avisados.json")
ARCHIVO_SEGUIMIENTOS = Path("seguimientos.json")

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

def obtener_partidos_cero_a_cero(soup: BeautifulSoup):
    contenedor = obtener_contenedor(soup)
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
                    partido_id = id_desde_enlace(elemento)

                    if local and visitante and partido_id:
                        partidos.append(
                            {
                                "id": partido_id,
                                "pais": pais,
                                "bandera": bandera,
                                "liga": liga,
                                "liga_completa": nombre_completo_liga,
                                "liga_normalizada": normalizar_liga(nombre_completo_liga),
                                "local": local,
                                "visitante": visitante,
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

        if es_amistoso(nombre_completo_liga):
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


def cargar_seguimientos() -> list[dict]:
    seguimientos = cargar_json_lista(ARCHIVO_SEGUIMIENTOS)

    for seguimiento in seguimientos:
        if seguimiento.get("kickoff"):
            seguimiento["kickoff_dt"] = datetime.fromisoformat(
                seguimiento["kickoff"]
            )

    return seguimientos


def guardar_seguimientos(seguimientos: list[dict]) -> None:
    salida = []

    for seguimiento in seguimientos:
        copia = dict(seguimiento)
        copia.pop("kickoff_dt", None)
        salida.append(copia)

    guardar_json_lista(ARCHIVO_SEGUIMIENTOS, salida)


def agregar_seguimiento(proximo: dict) -> bool:
    seguimientos = cargar_seguimientos()

    if any(
        seguimiento.get("partido_id") == proximo["id"]
        for seguimiento in seguimientos
    ):
        return False

    seguimientos.append(
        {
            "partido_id": proximo["id"],
            "pais": proximo["pais"],
            "liga": proximo["liga"],
            "local": proximo["local"],
            "visitante": proximo["visitante"],
            "kickoff": proximo["kickoff"].isoformat(),
            "recordatorio_enviado": False,
        }
    )

    guardar_seguimientos(seguimientos)
    return True


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


def enviar_recordatorio(seguimiento: dict) -> None:
    kickoff = seguimiento["kickoff_dt"]

    mensaje = "\n".join(
        [
            "⏰ RECORDATORIO — EMPIEZA EN 1 MINUTO",
            "",
            f"🏆 {seguimiento['liga']}",
            (
                f"⚽ {seguimiento['local']} "
                f"vs {seguimiento['visitante']}"
            ),
            (
                "🕒 "
                f"{kickoff.strftime('%d/%m/%Y %H:%M')} "
                "(hora Argentina)"
            ),
            "",
            "🎯 Seguimiento: más de 0,5 gol en el primer tiempo",
        ]
    )

    enviar_mensaje_telegram(mensaje)


# =========================================================
# REVISIÓN DE 0-0
# =========================================================

def revisar_partidos() -> None:
    print(f"\n[{hora_actual()}] Consultando Flashscore...")

    avisados = cargar_avisados()
    soup_hoy = descargar_pagina(0)
    partidos = obtener_partidos_cero_a_cero(soup_hoy)

    print(
        f"Partidos finalizados 0-0 encontrados: {len(partidos)}"
    )

    nuevos_partidos = [
        partido
        for partido in partidos
        if partido["id"] not in avisados
    ]

    if not nuevos_partidos:
        print("No hay nuevos 0-0 para avisar.")
        return

    print(
        "Buscando próximos partidos para "
        f"{len(nuevos_partidos)} nueva(s) alerta(s)..."
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

        if proximo:
            agregar_seguimiento(proximo)

        mensaje = construir_alerta_00(partido, proximo)
        enviar_mensaje_telegram(mensaje)

        avisados.add(partido["id"])
        guardar_avisados(avisados)

        enviados += 1

        print(
            "Alerta enviada: "
            f"{partido['local']} 0-0 {partido['visitante']} "
            f"({partido['liga_completa']})"
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
# REVISIÓN DE RECORDATORIOS
# =========================================================

def revisar_recordatorios() -> None:
    seguimientos = cargar_seguimientos()

    if not seguimientos:
        return

    ahora = ahora_argentina()
    hubo_cambios = False
    seguimientos_vigentes = []

    for seguimiento in seguimientos:
        kickoff = seguimiento["kickoff_dt"]

        # Borra seguimientos viejos después de seis horas.
        if ahora > kickoff + timedelta(hours=6):
            hubo_cambios = True
            continue

        if not seguimiento.get("recordatorio_enviado", False):
            inicio_ventana = kickoff - timedelta(seconds=90)
            fin_ventana = kickoff + timedelta(minutes=2)

            if inicio_ventana <= ahora <= fin_ventana:
                enviar_recordatorio(seguimiento)
                seguimiento["recordatorio_enviado"] = True
                hubo_cambios = True

                print(
                    "Recordatorio enviado: "
                    f"{seguimiento['local']} vs "
                    f"{seguimiento['visitante']}"
                )

        seguimientos_vigentes.append(seguimiento)

    if hubo_cambios:
        guardar_seguimientos(seguimientos_vigentes)


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
    print("Consulta Flashscore cada 5 minutos")
    print("Recordatorios revisados cada 15 segundos")
    print("Próximo partido activado")
    print("Aviso 1 minuto antes activado")
    print("Amistosos excluidos")
    print("Banderas activadas")
    print(
        "Ajuste horario Flashscore: "
        f"{AJUSTE_HORAS_FLASHSCORE:+d} horas"
    )
    print("============================================")

    proxima_consulta = 0.0

    while True:
        ahora_monotonic = time.monotonic()

        try:
            revisar_recordatorios()

            if ahora_monotonic >= proxima_consulta:
                revisar_partidos()
                proxima_consulta = (
                    time.monotonic()
                    + INTERVALO_CONSULTA_SEGUNDOS
                )

        except requests.RequestException as error:
            print(f"[{hora_actual()}] Error de conexión: {error}")

        except Exception as error:
            print(f"[{hora_actual()}] Error inesperado: {error}")

        time.sleep(INTERVALO_RECORDATORIOS_SEGUNDOS)


if __name__ == "__main__":
    main()
