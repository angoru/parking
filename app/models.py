import sqlite3
from datetime import date

from . import calendario


def _hoy() -> str:
    return calendario.hoy().isoformat()


def get_config(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def parse_numeros(texto: str) -> list[int] | None:
    """Convierte '12, 15, 20-23' en [12, 15, 20, 21, 22, 23]. None si el texto no es válido."""
    numeros = []
    for parte in texto.replace(";", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        desde, _, hasta = parte.partition("-")
        if not desde.strip().isdigit() or (hasta and not hasta.strip().isdigit()):
            return None
        desde, hasta = int(desde), int(hasta or desde)
        if hasta < desde or hasta - desde > 500:
            return None
        numeros.extend(range(desde, hasta + 1))
    return numeros or None


def crear_plazas(conn: sqlite3.Connection, texto: str) -> tuple[list[int], str | None]:
    """Crea plazas reservables con los números indicados. Devuelve los creados y un error si lo hubo."""
    numeros = parse_numeros(texto)
    if numeros is None:
        return [], "Escribe números de plaza, por ejemplo: 12, 15, 20-25."
    existentes = {r["numero"] for r in conn.execute("SELECT numero FROM plazas")}
    repetidos = sorted(set(numeros) & existentes)
    nuevos = sorted(set(numeros) - existentes)
    conn.executemany("INSERT INTO plazas (numero) VALUES (?)", [(n,) for n in nuevos])
    error = f"Ya existían: {', '.join(map(str, repetidos))}." if repetidos else None
    return nuevos, error


def contar_plazas(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM plazas").fetchone()[0]


def list_plazas(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM plazas ORDER BY numero").fetchall()


def get_plaza(conn: sqlite3.Connection, plaza_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM plazas WHERE id = ?", (plaza_id,)).fetchone()


def _reservas_futuras(conn: sqlite3.Connection, plaza_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM reservas WHERE plaza_id = ? AND fecha >= ?", (plaza_id, _hoy())
    ).fetchone() is not None


def update_plaza(conn: sqlite3.Connection, plaza_id: int, numero: int, tipo: str, titular: str | None) -> str | None:
    """Cambia número, tipo y titular. Las reservas siguen asociadas a la plaza aunque cambie su número."""
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if numero < 0:
        return "El número de plaza no puede ser negativo."
    if numero != plaza["numero"] and conn.execute(
        "SELECT 1 FROM plazas WHERE numero = ? AND id != ?", (numero, plaza_id)
    ).fetchone():
        return f"Ya existe la plaza {numero}."
    if tipo not in ("nominal", "reservable"):
        return "Tipo de plaza no válido."
    titular = (titular or "").strip() or None
    if tipo == "nominal":
        if not titular:
            return "Una plaza fija necesita titular."
        if plaza["tipo"] != "nominal" and _reservas_futuras(conn, plaza_id):
            return "La plaza tiene reservas futuras; cancélalas antes de hacerla fija."
    else:
        titular = None
        conn.execute("DELETE FROM liberaciones WHERE plaza_id = ?", (plaza_id,))
    conn.execute("UPDATE plazas SET numero = ?, tipo = ?, titular = ? WHERE id = ?",
                 (numero, tipo, titular, plaza_id))
    return None


def borrar_plaza(conn: sqlite3.Connection, plaza_id: int) -> str | None:
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if _reservas_futuras(conn, plaza_id):
        return f"La plaza {plaza['numero']} tiene reservas futuras; libéralas antes de eliminarla."
    conn.execute("DELETE FROM plazas WHERE id = ?", (plaza_id,))
    return None


# --- Estado de las plazas ----------------------------------------------------

_LIBRE_SQL = """
    (p.tipo = 'reservable'
     OR EXISTS (SELECT 1 FROM liberaciones l WHERE l.plaza_id = p.id AND l.fecha = :fecha))
    AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.plaza_id = p.id AND r.fecha = :fecha)
"""


def plazas_libres(conn: sqlite3.Connection, fecha: date) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT p.* FROM plazas p WHERE {_LIBRE_SQL} ORDER BY p.numero",
        {"fecha": fecha.isoformat()},
    ).fetchall()


def esta_libre(conn: sqlite3.Connection, plaza_id: int, fecha: date) -> bool:
    return conn.execute(
        f"SELECT 1 FROM plazas p WHERE p.id = :id AND {_LIBRE_SQL}",
        {"id": plaza_id, "fecha": fecha.isoformat()},
    ).fetchone() is not None


def estado_plazas(conn: sqlite3.Connection, fecha: date) -> list[dict]:
    """Todas las plazas con su estado ese día: libre, reservada, nominal o nominal_liberada."""
    filas = conn.execute(
        """SELECT p.*, r.id AS reserva_id, r.nombre AS reservada_por,
                  EXISTS (SELECT 1 FROM liberaciones l WHERE l.plaza_id = p.id AND l.fecha = :fecha) AS liberada
           FROM plazas p LEFT JOIN reservas r ON r.plaza_id = p.id AND r.fecha = :fecha
           ORDER BY p.numero""",
        {"fecha": fecha.isoformat()},
    ).fetchall()
    resultado = []
    for f in filas:
        if f["reserva_id"]:
            estado = "reservada"
        elif f["tipo"] == "nominal":
            estado = "nominal_liberada" if f["liberada"] else "nominal"
        else:
            estado = "libre"
        resultado.append({**dict(f), "estado": estado})
    return resultado


# --- Reservas ----------------------------------------------------------------

def _nombre_ocupado(conn: sqlite3.Connection, nombre: str, fecha: date, excluir_solicitud: int | None = None) -> bool:
    """¿Tiene ya ese nombre una reserva o una solicitud pendiente ese día?"""
    params = {"nombre": nombre, "fecha": fecha.isoformat(), "excluir": excluir_solicitud or 0}
    return conn.execute(
        """SELECT 1 FROM reservas WHERE lower(nombre) = lower(:nombre) AND fecha = :fecha
           UNION ALL
           SELECT 1 FROM solicitudes WHERE lower(nombre) = lower(:nombre) AND fecha = :fecha
                  AND estado = 'pendiente' AND id != :excluir""",
        params,
    ).fetchone() is not None


def reservar(
    conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str,
    comprobar_nombre: bool = True, excluir_solicitud: int | None = None,
) -> str | None:
    """Crea una reserva. Las reglas de qué día se puede reservar se aplican en las rutas."""
    nombre = nombre.strip()
    if not nombre:
        return "Indica tu nombre."
    if fecha < calendario.hoy():
        return "No se puede reservar en una fecha pasada."
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if not esta_libre(conn, plaza_id, fecha):
        return f"La plaza {plaza['numero']} ya está ocupada ese día."
    if comprobar_nombre and _nombre_ocupado(conn, nombre, fecha, excluir_solicitud):
        return f"{nombre} ya tiene una plaza o una solicitud ese día."
    conn.execute(
        "INSERT INTO reservas (plaza_id, fecha, nombre) VALUES (?, ?, ?)",
        (plaza_id, fecha.isoformat(), nombre),
    )
    return None


# --- Solicitudes para el mismo día -------------------------------------------

def solicitar(conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str) -> str | None:
    nombre = nombre.strip()
    if not nombre:
        return "Indica tu nombre."
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if not esta_libre(conn, plaza_id, fecha):
        return f"La plaza {plaza['numero']} ya está ocupada ese día."
    if _nombre_ocupado(conn, nombre, fecha):
        return f"{nombre} ya tiene una plaza o una solicitud ese día."
    conn.execute(
        "INSERT INTO solicitudes (plaza_id, fecha, nombre) VALUES (?, ?, ?)",
        (plaza_id, fecha.isoformat(), nombre),
    )
    return None


def solicitudes_pendientes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.*, p.numero FROM solicitudes s JOIN plazas p ON p.id = s.plaza_id
           WHERE s.estado = 'pendiente' AND s.fecha >= ? ORDER BY s.fecha, s.creada_en""",
        (_hoy(),),
    ).fetchall()


def contar_pendientes(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM solicitudes WHERE estado = 'pendiente' AND fecha >= ?", (_hoy(),)
    ).fetchone()[0]


def _get_pendiente(conn: sqlite3.Connection, solicitud_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM solicitudes WHERE id = ? AND estado = 'pendiente'", (solicitud_id,)
    ).fetchone()


def aprobar(conn: sqlite3.Connection, solicitud_id: int) -> str | None:
    """Convierte la solicitud en reserva. Si ya no es posible, la rechaza y devuelve el motivo."""
    s = _get_pendiente(conn, solicitud_id)
    if s is None:
        return "La solicitud ya no está pendiente."
    error = reservar(conn, s["plaza_id"], date.fromisoformat(s["fecha"]), s["nombre"],
                     excluir_solicitud=solicitud_id)
    if error:
        conn.execute("UPDATE solicitudes SET estado = 'rechazada', motivo = ? WHERE id = ?",
                     (error, solicitud_id))
        return f"No se pudo aprobar: {error} La solicitud se ha rechazado."
    conn.execute("UPDATE solicitudes SET estado = 'aprobada' WHERE id = ?", (solicitud_id,))
    return None


def rechazar(conn: sqlite3.Connection, solicitud_id: int) -> bool:
    cur = conn.execute(
        "UPDATE solicitudes SET estado = 'rechazada' WHERE id = ? AND estado = 'pendiente'",
        (solicitud_id,),
    )
    return cur.rowcount > 0


# --- Acciones del admin sobre cualquier plaza ---------------------------------

def liberar(conn: sqlite3.Connection, plaza_id: int, fecha: date) -> str | None:
    """Deja libre la plaza solo ese día: anula su reserva y, si es fija, la cede para esa fecha.
    Al día siguiente la plaza fija vuelve a estar cerrada sin hacer nada."""
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if fecha < calendario.hoy():
        return "No se puede liberar un día pasado."
    if esta_libre(conn, plaza_id, fecha):
        return f"La plaza {plaza['numero']} ya estaba libre."
    conn.execute("DELETE FROM reservas WHERE plaza_id = ? AND fecha = ?", (plaza_id, fecha.isoformat()))
    if plaza["tipo"] == "nominal":
        conn.execute(
            "INSERT OR IGNORE INTO liberaciones (plaza_id, fecha) VALUES (?, ?)",
            (plaza_id, fecha.isoformat()),
        )
    return None


def ocupar(conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str) -> str | None:
    """Ocupa una plaza ese día. En una nominal liberada, sin nombre (o con el del titular)
    se devuelve al titular; con otro nombre se reserva para esa persona."""
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    nombre = nombre.strip()
    if plaza["tipo"] == "nominal" and esta_libre(conn, plaza_id, fecha) and (
        not nombre or nombre.lower() == plaza["titular"].lower()
    ):
        conn.execute("DELETE FROM liberaciones WHERE plaza_id = ? AND fecha = ?", (plaza_id, fecha.isoformat()))
        return None
    return reservar(conn, plaza_id, fecha, nombre, comprobar_nombre=False)


# --- Avisos al admin -----------------------------------------------------------

def avisar(conn: sqlite3.Connection, texto: str) -> None:
    conn.execute("INSERT INTO avisos (texto) VALUES (?)", (texto,))


def avisos_recientes(conn: sqlite3.Connection, limite: int = 50) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM avisos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()


def contar_no_leidos(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM avisos WHERE leido = 0").fetchone()[0]


def marcar_leidos(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE avisos SET leido = 1 WHERE leido = 0")


# --- Festivos ------------------------------------------------------------------

def festivos_futuros(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM festivos WHERE fecha >= ? ORDER BY fecha", (_hoy(),)).fetchall()


def add_festivo(conn: sqlite3.Connection, fecha: date, nombre: str) -> str | None:
    nombre = nombre.strip()
    if not nombre:
        return "Indica el nombre del festivo."
    conn.execute(
        "INSERT INTO festivos (fecha, nombre) VALUES (?, ?) ON CONFLICT(fecha) DO UPDATE SET nombre = excluded.nombre",
        (fecha.isoformat(), nombre),
    )
    return None


def delete_festivo(conn: sqlite3.Connection, fecha: str) -> bool:
    return conn.execute("DELETE FROM festivos WHERE fecha = ?", (fecha,)).rowcount > 0
