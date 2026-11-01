"""Días laborables: fines de semana y festivos no cuentan para reservar."""
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

# Festivos de la ciudad de Madrid (nacionales, autonómicos y locales).
# Fuentes: Decreto 75/2025 y Decreto 82/2026 de la Comunidad de Madrid (BOCM)
# y acuerdos del Pleno del Ayuntamiento de Madrid para San Isidro y la Almudena.
FESTIVOS_MADRID = {
    "2026-01-01": "Año Nuevo",
    "2026-01-06": "Epifanía del Señor",
    "2026-04-02": "Jueves Santo",
    "2026-04-03": "Viernes Santo",
    "2026-05-01": "Fiesta del Trabajo",
    "2026-05-02": "Fiesta de la Comunidad de Madrid",
    "2026-05-15": "San Isidro Labrador",
    "2026-08-15": "Asunción de la Virgen",
    "2026-10-12": "Fiesta Nacional de España",
    "2026-11-02": "Día de Todos los Santos (trasladado)",
    "2026-11-09": "Nuestra Señora de la Almudena",
    "2026-12-07": "Día de la Constitución (trasladado)",
    "2026-12-08": "Inmaculada Concepción",
    "2026-12-25": "Natividad del Señor",
    "2027-01-01": "Año Nuevo",
    "2027-01-06": "Epifanía del Señor",
    "2027-03-19": "San José",
    "2027-03-25": "Jueves Santo",
    "2027-03-26": "Viernes Santo",
    "2027-05-01": "Fiesta del Trabajo",
    "2027-05-15": "San Isidro Labrador",
    "2027-08-16": "Asunción de la Virgen (trasladado)",
    "2027-10-12": "Fiesta Nacional de España",
    "2027-11-01": "Día de Todos los Santos",
    "2027-11-09": "Nuestra Señora de la Almudena",
    "2027-12-06": "Día de la Constitución Española",
    "2027-12-08": "Inmaculada Concepción",
    "2027-12-25": "Natividad del Señor",
}


def hoy() -> date:
    """Fecha actual. Los tests la sustituyen para fijar el día."""
    return datetime.now(MADRID).date()


def hora_actual() -> time:
    """Hora actual en Madrid. Los tests la sustituyen, igual que hoy()."""
    return datetime.now(MADRID).time()


def festivo(conn: sqlite3.Connection, d: date) -> str | None:
    """Nombre del festivo de ese día, o None si no lo es."""
    row = conn.execute("SELECT nombre FROM festivos WHERE fecha = ?", (d.isoformat(),)).fetchone()
    return row["nombre"] if row else None


def es_laborable(conn: sqlite3.Connection, d: date) -> bool:
    return d.weekday() < 5 and festivo(conn, d) is None


def siguiente_laborable(conn: sqlite3.Connection, d: date) -> date:
    """Primer día laborable después de d: el viernes se reserva para el lunes,
    y la víspera de un festivo, para el día siguiente al festivo."""
    siguiente = d + timedelta(days=1)
    while not es_laborable(conn, siguiente):
        siguiente += timedelta(days=1)
    return siguiente
