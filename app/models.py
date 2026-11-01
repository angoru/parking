import re
import secrets
import sqlite3
import unicodedata
from datetime import date, time

from . import calendario, db

NOMBRE_MAX = 60
NUMERO_MAX = 99999
TEXTO_MAX = 80
NUMERO_RE = re.compile(r"[0-9]{1,5}")
HORA_RE = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
HORA_APERTURA_DEFECTO = "08:00"


def _hoy() -> str:
    return calendario.hoy().isoformat()


def limpiar_texto(texto: str | None) -> str:
    """Quita caracteres de control y espacios sobrantes de un texto escrito por alguien."""
    sin_control = "".join(c for c in (texto or "") if not unicodedata.category(c).startswith("C"))
    return " ".join(sin_control.split())


def validar_nombre(nombre: str, maximo: int = NOMBRE_MAX) -> tuple[str, str | None]:
    """Devuelve el nombre limpio y un error si no es válido."""
    nombre = limpiar_texto(nombre)
    if not nombre:
        return nombre, "Indica tu nombre."
    if len(nombre) > maximo:
        return nombre, f"El nombre es demasiado largo (máximo {maximo} caracteres)."
    return nombre, None


def _bloquear_escritura(conn: sqlite3.Connection) -> None:
    """Empieza la transacción antes de comprobar nada: así comprobar y guardar es atómico
    aunque lleguen varias reservas a la vez (las demás esperan su turno)."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def get_config(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def hora_apertura(conn: sqlite3.Connection) -> time:
    """Hora a partir de la cual se puede reservar para el siguiente día laborable."""
    return time.fromisoformat(get_config(conn, "hora_apertura") or HORA_APERTURA_DEFECTO)


def guardar_hora_apertura(conn: sqlite3.Connection, hora: str) -> str | None:
    if not HORA_RE.fullmatch(hora):
        return "Escribe una hora válida, por ejemplo: 08:00."
    set_config(conn, "hora_apertura", hora)
    return None


def parse_numeros(texto: str) -> list[int] | None:
    """Convierte '12, 15, 20-23' en [12, 15, 20, 21, 22, 23]. None si el texto no es válido."""
    numeros = []
    for parte in texto.replace(";", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        desde, _, hasta = parte.partition("-")
        if not NUMERO_RE.fullmatch(desde.strip()) or (hasta and not NUMERO_RE.fullmatch(hasta.strip())):
            return None
        desde, hasta = int(desde), int(hasta or desde)
        if hasta < desde or hasta - desde > 500 or hasta > NUMERO_MAX:
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
    _bloquear_escritura(conn)
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if not 0 <= numero <= NUMERO_MAX:
        return f"El número de plaza debe estar entre 0 y {NUMERO_MAX}."
    if numero != plaza["numero"] and conn.execute(
        "SELECT 1 FROM plazas WHERE numero = ? AND id != ?", (numero, plaza_id)
    ).fetchone():
        return f"Ya existe la plaza {numero}."
    if numero != plaza["numero"] and _reservas_futuras(conn, plaza_id):
        # Quien la reservó como «la 23» iría a otra plaza
        return f"La plaza {plaza['numero']} tiene reservas futuras; no se puede cambiar su número hasta que pasen o se liberen."
    if tipo not in ("nominal", "reservable"):
        return "Tipo de plaza no válido."
    titular = limpiar_texto(titular) or None
    if titular and len(titular) > NOMBRE_MAX:
        return f"El titular es demasiado largo (máximo {NOMBRE_MAX} caracteres)."
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
    _bloquear_escritura(conn)
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


def estado_plaza(conn: sqlite3.Connection, plaza_id: int, fecha: date) -> dict | None:
    return next((p for p in estado_plazas(conn, fecha) if p["id"] == plaza_id), None)


# --- Reservas ----------------------------------------------------------------

def _nombre_ocupado(conn: sqlite3.Connection, nombre: str, fecha: date, excluir_solicitud: int | None = None) -> bool:
    """¿Tiene ya ese nombre una reserva o una solicitud pendiente ese día?"""
    params = {"nombre": nombre, "fecha": fecha.isoformat(), "excluir": excluir_solicitud or 0}
    return conn.execute(
        """SELECT 1 FROM reservas WHERE normalizar(nombre) = normalizar(:nombre) AND fecha = :fecha
           UNION ALL
           SELECT 1 FROM solicitudes WHERE normalizar(nombre) = normalizar(:nombre) AND fecha = :fecha
                  AND estado = 'pendiente' AND id != :excluir""",
        params,
    ).fetchone() is not None


def reservar(
    conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str,
    comprobar_nombre: bool = True, excluir_solicitud: int | None = None, token: str | None = None,
) -> str | None:
    """Crea una reserva. Las reglas de qué día se puede reservar se aplican en las rutas."""
    nombre, error = validar_nombre(nombre)
    if error:
        return error
    _bloquear_escritura(conn)
    if fecha < calendario.hoy():
        return "No se puede reservar en una fecha pasada."
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if not esta_libre(conn, plaza_id, fecha):
        return f"La plaza {plaza['numero']} ya está ocupada ese día."
    if comprobar_nombre and _nombre_ocupado(conn, nombre, fecha, excluir_solicitud):
        return f"{nombre} ya tiene una plaza o una solicitud ese día."
    try:
        conn.execute(
            "INSERT INTO reservas (plaza_id, fecha, nombre, token) VALUES (?, ?, ?, ?)",
            (plaza_id, fecha.isoformat(), nombre, token),
        )
    except sqlite3.IntegrityError:
        return f"La plaza {plaza['numero']} ya está ocupada ese día."
    return None


def _nuevo_token() -> str:
    return secrets.token_urlsafe(16)


def _repetida(conn: sqlite3.Connection, tabla: str, plaza_id: int, fecha: date, nombre: str) -> sqlite3.Row | None:
    """La misma persona ya tiene esa misma plaza ese día (por ejemplo, tras pulsar dos veces)."""
    extra = " AND estado = 'pendiente'" if tabla == "solicitudes" else ""
    return conn.execute(
        f"""SELECT token FROM {tabla} WHERE plaza_id = ? AND fecha = ?
            AND normalizar(nombre) = normalizar(?){extra}""",
        (plaza_id, fecha.isoformat(), nombre),
    ).fetchone()


def reservar_usuario(conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str) -> tuple[str | None, str | None, bool]:
    """Reserva desde la página pública. Devuelve (error, token, nueva). Si esa persona ya tenía
    esa plaza ese día, no es un error: se devuelve su reserva con nueva=False."""
    nombre, error = validar_nombre(nombre)
    if error:
        return error, None, False
    _bloquear_escritura(conn)
    if previa := _repetida(conn, "reservas", plaza_id, fecha, nombre):
        return None, previa["token"], False
    token = _nuevo_token()
    error = reservar(conn, plaza_id, fecha, nombre, token=token)
    return error, None if error else token, not error


# --- Solicitudes para el mismo día -------------------------------------------

def solicitar(conn: sqlite3.Connection, plaza_id: int, fecha: date, nombre: str) -> tuple[str | None, str | None, bool]:
    """Igual que reservar_usuario: devuelve (error, token, nueva)."""
    nombre, error = validar_nombre(nombre)
    if error:
        return error, None, False
    _bloquear_escritura(conn)
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe.", None, False
    if previa := _repetida(conn, "solicitudes", plaza_id, fecha, nombre):
        return None, previa["token"], False
    if not esta_libre(conn, plaza_id, fecha):
        return f"La plaza {plaza['numero']} ya está ocupada ese día.", None, False
    if _nombre_ocupado(conn, nombre, fecha):
        return f"{nombre} ya tiene una plaza o una solicitud ese día.", None, False
    token = _nuevo_token()
    conn.execute(
        "INSERT INTO solicitudes (plaza_id, fecha, nombre, token) VALUES (?, ?, ?, ?)",
        (plaza_id, fecha.isoformat(), nombre, token),
    )
    return None, token, True


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
    # Se bloquea antes de leer: si se pulsa «Aprobar» dos veces, la segunda ve que ya no está pendiente
    _bloquear_escritura(conn)
    s = _get_pendiente(conn, solicitud_id)
    if s is None:
        return "La solicitud ya no está pendiente."
    error = reservar(conn, s["plaza_id"], date.fromisoformat(s["fecha"]), s["nombre"],
                     excluir_solicitud=solicitud_id, token=s["token"])
    if error:
        conn.execute("UPDATE solicitudes SET estado = 'rechazada', motivo = ? WHERE id = ? AND estado = 'pendiente'",
                     (error, solicitud_id))
        return f"No se pudo aprobar: {error} La solicitud se ha rechazado."
    conn.execute("UPDATE solicitudes SET estado = 'aprobada' WHERE id = ? AND estado = 'pendiente'", (solicitud_id,))
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
    _bloquear_escritura(conn)
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
    _bloquear_escritura(conn)
    plaza = get_plaza(conn, plaza_id)
    if plaza is None:
        return "La plaza no existe."
    if fecha < calendario.hoy():
        return "No se puede ocupar un día pasado."
    nombre = limpiar_texto(nombre)
    if plaza["tipo"] == "nominal" and esta_libre(conn, plaza_id, fecha) and (
        not nombre or db.normalizar(nombre) == db.normalizar(plaza["titular"])
    ):
        conn.execute("DELETE FROM liberaciones WHERE plaza_id = ? AND fecha = ?", (plaza_id, fecha.isoformat()))
        return None
    return reservar(conn, plaza_id, fecha, nombre, comprobar_nombre=False)


# --- Lo reservado desde un dispositivo -------------------------------------------

def mis_reservas(conn: sqlite3.Connection, entradas: list[tuple[str, str, str]]) -> list[dict]:
    """Estado actual de las reservas y solicitudes hechas desde un dispositivo.
    entradas: (tipo 'r' o 's', fecha, token). El token no se puede adivinar."""
    resultado = []
    for tipo, fecha, token in entradas:
        reserva = conn.execute(
            """SELECT r.fecha, p.numero FROM reservas r JOIN plazas p ON p.id = r.plaza_id
               WHERE r.token = ?""", (token,)).fetchone()
        if tipo == "s":
            s = conn.execute(
                """SELECT s.fecha, s.estado, s.motivo, p.numero FROM solicitudes s
                   JOIN plazas p ON p.id = s.plaza_id WHERE s.token = ?""", (token,)).fetchone()
            if s is None:
                continue
            estado = s["estado"]
            if estado == "aprobada" and reserva is None:
                estado = "anulada"
            resultado.append({"tipo": "solicitud", "fecha": s["fecha"], "numero": s["numero"],
                              "estado": estado, "motivo": s["motivo"]})
        elif reserva:
            resultado.append({"tipo": "reserva", "fecha": reserva["fecha"], "numero": reserva["numero"],
                              "estado": "reservada", "motivo": None})
        else:
            # El admin la anuló: ya no queda nada en la base de datos salvo que existió
            resultado.append({"tipo": "reserva", "fecha": fecha, "numero": None,
                              "estado": "anulada", "motivo": None})
    return resultado


# --- Avisos al admin -----------------------------------------------------------

def avisar(conn: sqlite3.Connection, texto: str, leido: bool = False) -> None:
    """Aviso al admin. Con leido=True queda solo como historial (lo que hace el propio admin)."""
    conn.execute("INSERT INTO avisos (texto, leido) VALUES (?, ?)", (texto, int(leido)))


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
    nombre = limpiar_texto(nombre)
    if not nombre:
        return "Indica el nombre del festivo."
    if len(nombre) > TEXTO_MAX:
        return f"El nombre del festivo es demasiado largo (máximo {TEXTO_MAX} caracteres)."
    conn.execute(
        "INSERT INTO festivos (fecha, nombre) VALUES (?, ?) ON CONFLICT(fecha) DO UPDATE SET nombre = excluded.nombre",
        (fecha.isoformat(), nombre),
    )
    return None


def reservas_del_dia(conn: sqlite3.Connection, fecha: date) -> int:
    return conn.execute("SELECT COUNT(*) FROM reservas WHERE fecha = ?", (fecha.isoformat(),)).fetchone()[0]


def faltan_festivos(conn: sqlite3.Connection) -> list[int]:
    """Años sin ningún festivo cargado: el actual y, desde noviembre, el siguiente."""
    hoy = calendario.hoy()
    anios = [hoy.year] + ([hoy.year + 1] if hoy.month >= 11 else [])
    return [a for a in anios
            if not conn.execute("SELECT 1 FROM festivos WHERE fecha LIKE ?", (f"{a}-%",)).fetchone()]


def delete_festivo(conn: sqlite3.Connection, fecha: str) -> bool:
    return conn.execute("DELETE FROM festivos WHERE fecha = ?", (fecha,)).rowcount > 0
