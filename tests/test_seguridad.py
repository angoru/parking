"""Pruebas de los hallazgos del análisis de seguridad."""
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import calendario, seguridad
from app.main import app

RAIZ = Path(__file__).resolve().parent.parent
CLAVE = "clave-de-prueba-123"
MIERCOLES = date(2026, 10, 14)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PARKING_TOTAL", "5")
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setattr(calendario, "hoy", lambda: MIERCOLES)
    seguridad.limitador.reset()
    return monkeypatch


@pytest.fixture
def client(entorno):
    with TestClient(app) as c:
        yield c


def login(c, password, usuario="admin"):
    return c.post("/admin/login", data={"usuario": usuario, "password": password})


def cambiar_password(c, actual, nueva, repetir=None):
    return c.post("/admin/password", data={"actual": actual, "nueva": nueva, "repetir": repetir or nueva})


# --- 1. Contraseña por defecto ---------------------------------------------------

def test_password_por_defecto_obliga_a_cambiarla(client):
    r = login(client, "admin")
    assert r.url.path == "/admin/password"
    for path in ("/admin", "/admin/ajustes", "/admin/solicitudes"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/password"
    r = cambiar_password(client, "admin", CLAVE)
    assert r.url.path == "/admin" and r.status_code == 200
    client.post("/admin/logout")
    assert "incorrectos" in login(client, "admin").text
    assert login(client, CLAVE).url.path == "/admin"


@pytest.mark.parametrize("nueva, repetir, mensaje", [
    ("corta", None, "al menos 10 caracteres"),
    ("adminadmin", None, "demasiado fácil"),
    ("una-clave-larga", "otra-clave-larga", "no coinciden"),
])
def test_password_nueva_validada(client, nueva, repetir, mensaje):
    login(client, "admin")
    assert mensaje in cambiar_password(client, "admin", nueva, repetir).text


def test_cambiar_password_exige_la_actual(client):
    login(client, "admin")
    assert "contraseña actual no es correcta" in cambiar_password(client, "mal", CLAVE).text


def test_password_de_entorno_no_obliga_a_cambiarla(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as c:
        assert login(c, CLAVE).url.path == "/admin"
        assert "incorrectos" in login(c, "admin").text


# --- 2. Concurrencia con SQLite --------------------------------------------------

def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(entorno):
    """Servidor real (uvicorn con varios hilos), como en producción."""
    puerto = _puerto_libre()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error"))
    hilo = threading.Thread(target=server.run, daemon=True)
    hilo.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{puerto}"
    server.should_exit = True
    hilo.join(5)


def test_reservas_simultaneas_sin_errores_ni_bloqueos(servidor):
    seguridad.limitador.reset()
    with ThreadPoolExecutor(10) as pool:
        respuestas = list(pool.map(
            lambda i: httpx.post(f"{servidor}/reservar/1", data={"nombre": f"Persona {i}"}, timeout=30),
            range(10)))
    assert [r.status_code for r in respuestas] == [303] * 10
    assert sum(r.headers["location"] == "/confirmacion" for r in respuestas) == 1
    # La base de datos no se queda bloqueada: la siguiente reserva entra al momento
    inicio = time.monotonic()
    r = httpx.post(f"{servidor}/reservar/2", data={"nombre": "Después"}, timeout=30)
    assert r.headers["location"] == "/confirmacion"
    assert time.monotonic() - inicio < 2


# --- 3. Intentos de login ----------------------------------------------------------

def test_login_bloqueado_tras_cinco_fallos(client):
    for i in range(5):
        assert "incorrectos" in login(client, f"mala-{i}").text
    r = login(client, "admin")
    assert r.status_code == 429 and "Demasiados intentos" in r.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_login_correcto_reinicia_el_contador(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as c:
        for _ in range(4):
            login(c, "mala")
        assert login(c, CLAVE).url.path == "/admin"
        for _ in range(4):
            login(c, "mala")
        assert login(c, CLAVE).url.path == "/admin"


# --- 4. Abuso de reservas anónimas ---------------------------------------------------

def test_nombre_demasiado_largo(client):
    r = client.post("/reservar/1", data={"nombre": "A" * 61})
    assert "demasiado largo" in r.text
    assert "Has reservado" in client.post("/reservar/1", data={"nombre": "A" * 60}).text


def test_nombre_sin_caracteres_de_control(client, entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    client.post("/reservar/1", data={"nombre": "  Ana\x00\x1b[31m   López \n"})
    login(client, CLAVE)
    html = client.get("/admin", params={"fecha": "2026-10-15"}).text
    assert "Ana[31m López" in html and "\x1b" not in html


def test_limite_de_reservas_por_ip(client):
    for i in range(1, 6):
        assert "Has" in client.post(f"/reservar/{i}" if i % 2 else f"/solicitar/{i}", data={"nombre": f"P{i}"}).text
    client.post("/admin/plazas", data={"numeros": "6"})  # sin sesión: no hace nada
    r = client.post("/solicitar/1", data={"nombre": "Otra"})
    assert r.status_code == 429 and "Demasiadas reservas" in r.text


# --- 5. HTTPS: cookies seguras cuando la conexión lo es --------------------------------

def test_cookie_secure_y_hsts_en_https(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/admin/login", data={"usuario": "admin", "password": CLAVE}, follow_redirects=False)
        assert "Secure" in r.headers["set-cookie"]
        assert "max-age" in c.get("/").headers["strict-transport-security"]


def test_cookie_secure_forzada_por_entorno(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    entorno.setenv("COOKIE_SECURE", "1")
    with TestClient(app) as c:
        r = c.post("/admin/login", data={"usuario": "admin", "password": CLAVE}, follow_redirects=False)
        assert "Secure" in r.headers["set-cookie"]


# --- 6. Sesiones revocables ---------------------------------------------------------

def test_logout_invalida_la_cookie(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as c:
        login(c, CLAVE)
        robada = c.cookies.get("parking_admin")
        c.post("/admin/logout")
        c.cookies.set("parking_admin", robada)
        assert c.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"


def test_cambiar_password_cierra_las_demas_sesiones(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as movil, TestClient(app) as portatil:
        login(movil, CLAVE)
        login(portatil, CLAVE)
        cambiar_password(portatil, CLAVE, "nueva-clave-segura")
        assert movil.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"
        assert portatil.get("/admin").status_code == 200


# --- 7. Documentación de la API --------------------------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentacion_api_desactivada(client, path):
    assert client.get(path).status_code == 404


# --- 8. Cabeceras de seguridad -----------------------------------------------------------

def test_cabeceras_de_seguridad(client):
    h = client.get("/").headers
    csp = h["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in csp
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "same-origin"


def test_paginas_de_admin_no_se_cachean(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as c:
        login(c, CLAVE)
        assert "no-store" in c.get("/admin").headers["cache-control"]


def test_plantillas_sin_javascript_en_linea():
    """La CSP bloquea los manejadores en línea (onclick, onchange...); no debe quedar ninguno."""
    for plantilla in (RAIZ / "app" / "templates").glob("*.html"):
        texto = plantilla.read_text()
        assert not re.search(r"\son[a-z]+\s*=", texto), plantilla.name
        assert "<script>" not in texto, plantilla.name


# --- 9. Mensajes no inyectables desde la URL ------------------------------------------------

def test_mensajes_de_la_url_se_ignoran(entorno):
    entorno.setenv("ADMIN_PASSWORD", CLAVE)
    with TestClient(app) as c:
        falso = "Tu plaza ha sido cancelada. Llama al 600 000 000"
        assert falso not in c.get("/", params={"error": falso}).text
        login(c, CLAVE)
        assert falso not in c.get("/admin", params={"msg": falso, "error": falso}).text


def test_confirmacion_no_se_puede_falsificar(client):
    r = client.get("/confirmacion", params={"tipo": "reserva", "plaza": 999, "fecha": "2026-10-15"})
    assert "Has reservado la plaza 999" not in r.text
    assert r.url.path == "/"


def test_mensajes_siguen_funcionando(client):
    r = client.post("/reservar/1", data={"nombre": "Ana"})
    assert "Has reservado la plaza 1" in r.text
    assert "ya está ocupada" in client.post("/reservar/1", data={"nombre": "Pepe"}).text
    # El mensaje se muestra una sola vez
    assert "ya está ocupada" not in client.get("/").text


# --- 10. Dependencias con versión fija -------------------------------------------------------

def test_dependencias_con_version_fija():
    for fichero in ("requirements.txt", "requirements-dev.txt"):
        for linea in (RAIZ / fichero).read_text().splitlines():
            linea = linea.split("#")[0].strip()
            if linea and not linea.startswith("-r"):
                assert re.fullmatch(r"[A-Za-z0-9_.\[\]-]+==[0-9][0-9A-Za-z.]*", linea), linea
