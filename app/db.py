import os
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
-- Sesiones del admin: solo el hash del token, para poder cerrarlas desde el servidor
CREATE TABLE IF NOT EXISTS sesiones (
    token_hash TEXT PRIMARY KEY,
    expira     INTEGER NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("PARKING_DB", "parking.db")


def connect() -> sqlite3.Connection:
    # Cada petición abre su propia conexión, pero FastAPI puede crearla en un hilo y usarla
    # en otro: sin check_same_thread=False la transacción queda a medias y bloquea la base de datos.
    # timeout: si otra petición está escribiendo, se espera en vez de fallar.
    conn = sqlite3.connect(db_path(), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db() -> None:
    """Crea las tablas y, la primera vez, las plazas y los festivos."""
    from . import calendario, models

    conn = connect()
    try:
        # WAL: las lecturas no esperan a las escrituras (el modo queda guardado en el fichero)
        conn.execute("PRAGMA journal_mode = WAL")
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
        conn.commit()
    finally:
        conn.close()
