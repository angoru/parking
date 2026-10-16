import os
import secrets
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plazas (
    id      INTEGER PRIMARY KEY,
    numero  INTEGER NOT NULL UNIQUE,
    tipo    TEXT NOT NULL DEFAULT 'reservable' CHECK (tipo IN ('nominal', 'reservable')),
    titular TEXT
);
CREATE TABLE IF NOT EXISTS reservas (
    id        INTEGER PRIMARY KEY,
    plaza_id  INTEGER NOT NULL REFERENCES plazas(id) ON DELETE CASCADE,
    fecha     TEXT NOT NULL,
    nombre    TEXT NOT NULL,
    creada_en TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (plaza_id, fecha)
);
-- Días en que una plaza nominal queda libre para cualquiera
CREATE TABLE IF NOT EXISTS liberaciones (
    plaza_id INTEGER NOT NULL REFERENCES plazas(id) ON DELETE CASCADE,
    fecha    TEXT NOT NULL,
    PRIMARY KEY (plaza_id, fecha)
);
-- Peticiones para el mismo día, que el admin aprueba o rechaza
CREATE TABLE IF NOT EXISTS solicitudes (
    id        INTEGER PRIMARY KEY,
    plaza_id  INTEGER NOT NULL REFERENCES plazas(id) ON DELETE CASCADE,
    fecha     TEXT NOT NULL,
    nombre    TEXT NOT NULL,
    estado    TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
    motivo    TEXT,
    creada_en TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Días no laborables, además de sábados y domingos
CREATE TABLE IF NOT EXISTS festivos (
    fecha  TEXT PRIMARY KEY,
    nombre TEXT NOT NULL
);
-- Avisos al admin de lo que hacen quienes reservan
CREATE TABLE IF NOT EXISTS avisos (
    id        INTEGER PRIMARY KEY,
    texto     TEXT NOT NULL,
    leido     INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def db_path() -> str:
    return os.environ.get("PARKING_DB", "parking.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Crea las tablas y, la primera vez, las plazas, los festivos y la clave de sesión."""
    from . import calendario, models

    with connect() as conn:
        conn.executescript(SCHEMA)
        # Solo la primera vez: plazas 1..N. Después el admin las numera como quiera
        if models.get_config(conn, "plazas_creadas") is None:
            if models.contar_plazas(conn) == 0:
                models.crear_plazas(conn, f"1-{int(os.environ.get('PARKING_TOTAL', '10'))}")
            models.set_config(conn, "plazas_creadas", "1")
        # Solo se cargan una vez, para no recuperar los que el admin haya borrado
        if models.get_config(conn, "festivos_cargados") is None:
            conn.executemany("INSERT OR IGNORE INTO festivos (fecha, nombre) VALUES (?, ?)",
                             calendario.FESTIVOS_MADRID.items())
            models.set_config(conn, "festivos_cargados", "1")
        if models.get_config(conn, "secret") is None:
            models.set_config(conn, "secret", secrets.token_hex(32))
