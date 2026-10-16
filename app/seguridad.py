"""Contraseña del admin, sesiones revocables, límites de intentos y mensajes de un solo uso."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from . import models

PASSWORD_POR_DEFECTO = "admin"
PASSWORD_MINIMA = 10
SESION_DURACION = 30 * 24 * 3600


# --- Contraseña del admin ---------------------------------------------------------
# Orden de prioridad: la guardada desde la app > ADMIN_PASSWORD_FILE > ADMIN_PASSWORD
# > "admin" (obliga a cambiarla).

def _hash(password: str, sal: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=sal, n=2**14, r=8, p=1)


def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    return f"scrypt${sal.hex()}${_hash(password, sal).hex()}"


def _verificar_hash(password: str, guardado: str) -> bool:
    try:
        _, sal, valor = guardado.split("$")
        return hmac.compare_digest(_hash(password, bytes.fromhex(sal)), bytes.fromhex(valor))
    except ValueError:
        return False


def usuario_admin() -> str:
    return os.environ.get("ADMIN_USER", "admin")


def password_entorno() -> str | None:
    """Contraseña de la configuración: el archivo de ADMIN_PASSWORD_FILE (secreto del
    contenedor) o, si no hay, la variable ADMIN_PASSWORD."""
    archivo = os.environ.get("ADMIN_PASSWORD_FILE")
    if archivo:
        return Path(archivo).read_text(encoding="utf-8").rstrip("\r\n") or None
    return os.environ.get("ADMIN_PASSWORD") or None


def usa_password_por_defecto(conn: sqlite3.Connection) -> bool:
    return models.get_config(conn, "admin_password") is None and not password_entorno()


def password_correcta(conn: sqlite3.Connection, password: str) -> bool:
    guardado = models.get_config(conn, "admin_password")
    if guardado:
        return _verificar_hash(password, guardado)
    esperada = password_entorno() or PASSWORD_POR_DEFECTO
    return secrets.compare_digest(password.encode(), esperada.encode())


def credenciales_correctas(conn: sqlite3.Connection, usuario: str, password: str) -> bool:
    ok_usuario = secrets.compare_digest(usuario.encode(), usuario_admin().encode())
    # Se comprueba la contraseña siempre, para no revelar por el tiempo de respuesta si el usuario existe
    ok_password = password_correcta(conn, password)
    return ok_usuario and ok_password


def validar_password_nueva(nueva: str, repetir: str) -> str | None:
    if nueva != repetir:
        return "Las contraseñas no coinciden."
    if len(nueva) < PASSWORD_MINIMA:
        return f"La contraseña debe tener al menos {PASSWORD_MINIMA} caracteres."
    if PASSWORD_POR_DEFECTO in nueva.lower() or len(set(nueva)) < 4:
        return "Esa contraseña es demasiado fácil de adivinar."
    return None


def guardar_password(conn: sqlite3.Connection, nueva: str) -> None:
    models.set_config(conn, "admin_password", hash_password(nueva))


# --- Sesiones guardadas en la base de datos (se pueden revocar) -----------------------
# La cookie lleva un token aleatorio; en la base de datos solo se guarda su hash.

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def crear_sesion(conn: sqlite3.Connection) -> str:
    token = secrets.token_urlsafe(32)
    ahora = int(time.time())
    conn.execute("DELETE FROM sesiones WHERE expira < ?", (ahora,))
    conn.execute("INSERT INTO sesiones (token_hash, expira) VALUES (?, ?)",
                 (_hash_token(token), ahora + SESION_DURACION))
    return token


def sesion_valida(conn: sqlite3.Connection, token: str | None) -> bool:
    if not token:
        return False
    return conn.execute("SELECT 1 FROM sesiones WHERE token_hash = ? AND expira > ?",
                        (_hash_token(token), int(time.time()))).fetchone() is not None


def cerrar_sesion(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sesiones WHERE token_hash = ?", (_hash_token(token),))


def cerrar_otras_sesiones(conn: sqlite3.Connection, token_actual: str | None) -> None:
    conn.execute("DELETE FROM sesiones WHERE token_hash != ?", (_hash_token(token_actual or ""),))


# --- Límite de intentos por IP (en memoria) --------------------------------------------

class Limitador:
    """Ventana deslizante por clave. Se reinicia al reiniciar el servidor, lo que basta
    para frenar la fuerza bruta y los scripts de reservas."""

    def __init__(self):
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _limpiar(self, clave: str, ventana: int) -> deque:
        eventos = self._eventos[clave]
        limite = time.monotonic() - ventana
        while eventos and eventos[0] < limite:
            eventos.popleft()
        return eventos

    def excedido(self, clave: str, maximo: int, ventana: int) -> bool:
        with self._lock:
            return len(self._limpiar(clave, ventana)) >= maximo

    def anotar(self, clave: str) -> None:
        with self._lock:
            self._eventos[clave].append(time.monotonic())

    def olvidar(self, clave: str) -> None:
        with self._lock:
            self._eventos.pop(clave, None)

    def reset(self) -> None:
        with self._lock:
            self._eventos.clear()


limitador = Limitador()

LOGIN_MAX_FALLOS = 5
LOGIN_VENTANA = 15 * 60
RESERVAS_VENTANA = 3600


def reservas_por_hora() -> int:
    return int(os.environ.get("RESERVAS_POR_HORA", "5"))


# --- Mensajes de un solo uso ------------------------------------------------------------
# Los avisos tras una acción viajan en una cookie y no en la URL, para que nadie pueda
# fabricar enlaces que muestren textos falsos dentro de la aplicación.

FLASH_COOKIE = "parking_flash"


def codificar_flash(datos: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(datos).encode()).decode()


def leer_flash(valor: str | None) -> dict:
    if not valor:
        return {}
    try:
        datos = json.loads(base64.urlsafe_b64decode(valor.encode()))
        return datos if isinstance(datos, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}
