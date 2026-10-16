import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import calendario
from app.main import app

# Miércoles normal: el siguiente laborable es el jueves 15
MIERCOLES = date(2026, 10, 14)
JUEVES = date(2026, 10, 15)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PARKING_TOTAL", "5")
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(calendario, "hoy", lambda: MIERCOLES)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    """Cliente con la sesión de admin iniciada (usuario admin, contraseña admin)."""
    r = client.post("/admin/login", data={"usuario": "admin", "password": "admin"})
    assert r.url.path == "/admin"
    return client


def hoy_es(monkeypatch, d: date):
    monkeypatch.setattr(calendario, "hoy", lambda: d)


def libres(client, dia="siguiente"):
    html = client.get("/", params={"dia": dia}).text
    # Números visibles de las plazas libres (no el id interno de la plaza)
    return sorted(int(n) for n in re.findall(r'<span class="num">(\d+)</span>', html))


def reservar(client, plaza_id, nombre="Ana"):
    return client.post(f"/reservar/{plaza_id}", data={"nombre": nombre})


def solicitar(client, plaza_id, nombre="Ana"):
    return client.post(f"/solicitar/{plaza_id}", data={"nombre": nombre})


def solicitud_ids(admin):
    html = admin.get("/admin/solicitudes").text
    return [int(n) for n in re.findall(r'/admin/solicitudes/(\d+)/aprobar', html)]


def hacer_nominal(admin, plaza_id, titular="Luis"):
    # Al principio las plazas son 1..5 y su id coincide con el número
    r = admin.post(f"/admin/plazas/{plaza_id}", data={"numero": plaza_id, "tipo": "nominal", "titular": titular})
    assert "guardada" in r.text


# --- Día para el que se reserva ----------------------------------------------

@pytest.mark.parametrize("hoy, esperado, etiqueta", [
    (date(2026, 10, 14), date(2026, 10, 15), "Mañana"),     # miércoles → jueves
    (date(2026, 10, 16), date(2026, 10, 19), "Lunes"),      # viernes → lunes
    (date(2026, 10, 9), date(2026, 10, 13), "Martes"),      # viernes, lunes 12 festivo → martes
    (date(2026, 11, 6), date(2026, 11, 10), "Martes"),      # viernes, lunes 9 Almudena → martes
    (date(2026, 12, 4), date(2026, 12, 9), "Miércoles"),    # puente de diciembre (7 y 8) → miércoles
    (date(2027, 3, 24), date(2027, 3, 29), "Lunes"),        # Semana Santa 2027
    (date(2026, 10, 17), date(2026, 10, 19), None),         # sábado → lunes (sin pestañas)
])
def test_siguiente_laborable(client, monkeypatch, hoy, esperado, etiqueta):
    hoy_es(monkeypatch, hoy)
    html = client.get("/").text
    assert re.search(r"\b%d de " % esperado.day, html)
    if etiqueta:
        assert f">{etiqueta}</a>" in html
    r = reservar(client, 1)
    assert r.url.path == "/confirmacion"
    assert f"fecha={esperado.isoformat()}" in str(r.url)


def test_no_laborable_sin_pestana_hoy(client, monkeypatch):
    hoy_es(monkeypatch, date(2026, 10, 17))  # sábado
    html = client.get("/").text
    assert 'href="/?dia=hoy"' not in html
    assert "no se pueden pedir plazas para hoy" in solicitar(client, 1).text


def test_admin_puede_anadir_festivo(admin):
    admin.post("/admin/festivos", data={"fecha": JUEVES.isoformat(), "nombre": "Fiesta inventada"})
    assert "fecha=2026-10-16" in str(reservar(admin, 1).url)
    assert "Fiesta inventada" in admin.get("/admin", params={"fecha": JUEVES.isoformat()}).text
    admin.post(f"/admin/festivos/{JUEVES.isoformat()}/borrar")
    assert "fecha=2026-10-15" in str(reservar(admin, 2, nombre="Otro").url)


# --- Público ---------------------------------------------------------------

def test_inicial_todas_libres(client):
    assert libres(client, "hoy") == [1, 2, 3, 4, 5]
    assert libres(client) == [1, 2, 3, 4, 5]


def test_nominales_no_aparecen(admin):
    hacer_nominal(admin, 2)
    assert libres(admin) == [1, 3, 4, 5]
    assert "ya está ocupada" in reservar(admin, 2).text


def test_confirmacion_reserva(client):
    r = reservar(client, 3)
    assert "Has reservado la plaza 3" in r.text
    assert "Si quieres cancelar, envía un correo al admin" in r.text
    assert 3 not in libres(client)
    assert 3 in libres(client, "hoy")


def test_confirmacion_con_correo_del_admin(admin):
    admin.post("/admin/email", data={"email": "garaje@ejemplo.com"})
    assert 'href="mailto:garaje@ejemplo.com?subject=' in reservar(admin, 3).text


def test_no_hay_mis_reservas(client):
    assert client.get("/mis-reservas").status_code == 404
    assert "Mis reservas" not in client.get("/").text


def test_doble_reserva_rechazada(client):
    reservar(client, 1, nombre="Ana")
    assert "ya está ocupada" in reservar(client, 1, nombre="Pepe").text


def test_una_plaza_por_nombre_y_dia(client):
    reservar(client, 1, nombre="Ana")
    assert "ya tiene una plaza" in reservar(client, 2, nombre="ana").text
    solicitar(client, 3, nombre="Ana")
    assert "ya tiene una plaza" in solicitar(client, 4, nombre="Ana").text


# --- Solicitudes para hoy ----------------------------------------------------

def test_solicitud_hoy_no_ocupa_hasta_aprobar(admin):
    assert "Has solicitado la plaza 2" in solicitar(admin, 2, nombre="Marta").text
    assert 2 in libres(admin, "hoy")
    assert len(solicitud_ids(admin)) == 1
    assert 'Solicitudes <span class="badge">1</span>' in admin.get("/admin").text


def test_aprobar_solicitud(admin):
    solicitar(admin, 2, nombre="Marta")
    (sid,) = solicitud_ids(admin)
    assert "Solicitud aprobada" in admin.post(f"/admin/solicitudes/{sid}/aprobar").text
    assert 2 not in libres(admin, "hoy")
    assert solicitud_ids(admin) == []


def test_rechazar_solicitud(admin):
    solicitar(admin, 2, nombre="Marta")
    (sid,) = solicitud_ids(admin)
    admin.post(f"/admin/solicitudes/{sid}/rechazar")
    assert 2 in libres(admin, "hoy")
    assert solicitud_ids(admin) == []


def test_aprobar_plaza_ya_ocupada_la_rechaza(admin):
    solicitar(admin, 2, nombre="Marta")
    solicitar(admin, 2, nombre="Pepe")
    primera, segunda = solicitud_ids(admin)
    admin.post(f"/admin/solicitudes/{primera}/aprobar")
    assert "No se pudo aprobar" in admin.post(f"/admin/solicitudes/{segunda}/aprobar").text
    assert solicitud_ids(admin) == []


# --- Admin: tablero, liberar y ocupar -----------------------------------------

def test_tablero_muestra_todas(admin):
    hacer_nominal(admin, 1, "Luis")
    reservar(admin, 2, nombre="Marta")
    html = admin.get("/admin", params={"fecha": JUEVES.isoformat()}).text
    assert html.count('<li class="spot-card ') == 5
    assert 'spot-card nominal' in html and "Luis" in html
    assert 'spot-card reservada' in html and "Marta" in html


def kpi(html, etiqueta):
    m = re.search(etiqueta + r'</span>\s*<span class="kpi-value">(\d+)</span>', html)
    return int(m.group(1))


def test_tablero_resumen_y_filtros(admin):
    hacer_nominal(admin, 1, "Luis")
    reservar(admin, 2, nombre="Marta")
    solicitar(admin, 3, nombre="Pepe")
    html = admin.get("/admin", params={"fecha": JUEVES.isoformat()}).text
    assert (kpi(html, "Libres"), kpi(html, "Reservadas"), kpi(html, "Fijas en uso"), kpi(html, "Solicitudes")) == (3, 1, 1, 1)
    assert "2 de 5 · 40 %" in html
    def visibles(ver):
        h = admin.get("/admin", params={"fecha": JUEVES.isoformat(), "ver": ver}).text
        return sorted(int(n) for n in re.findall(r'<span class="spot-num">(\d+)</span>', h))
    assert visibles("libres") == [3, 4, 5]
    assert visibles("ocupadas") == [1, 2]
    assert visibles("fijas") == [1]
    assert visibles("otra") == [1, 2, 3, 4, 5]
    # Al liberar desde un filtro se vuelve al mismo filtro
    r = admin.post("/admin/plazas/2/liberar", data={"fecha": JUEVES.isoformat(), "ver": "ocupadas"})
    assert "ver=ocupadas" in str(r.url)


def test_liberar_y_ocupar_nominal(admin):
    hacer_nominal(admin, 1, "Luis")
    fecha = JUEVES.isoformat()
    assert "Plaza liberada" in admin.post("/admin/plazas/1/liberar", data={"fecha": fecha}).text
    assert 1 in libres(admin)
    assert 1 not in libres(admin, "hoy")
    reservar(admin, 1, nombre="Ana")
    assert 1 not in libres(admin)
    admin.post("/admin/plazas/1/liberar", data={"fecha": fecha})
    assert 1 in libres(admin)
    admin.post("/admin/plazas/1/ocupar", data={"fecha": fecha, "nombre": ""})
    assert 1 not in libres(admin)


def test_fija_liberada_solo_ese_dia(admin, monkeypatch):
    hacer_nominal(admin, 1, "Luis")
    admin.post("/admin/plazas/1/liberar", data={"fecha": JUEVES.isoformat()})
    assert 1 in libres(admin)                       # jueves: libre
    html = admin.get("/admin", params={"fecha": "2026-10-16"}).text
    assert "Liberar este día" in html               # viernes: vuelve a estar cerrada
    hoy_es(monkeypatch, JUEVES)                     # el jueves se reserva para el viernes
    assert 1 not in libres(admin)
    assert 1 in libres(admin, "hoy")


def test_fija_liberada_el_mismo_dia(admin):
    hacer_nominal(admin, 1, "Luis")
    assert 1 not in libres(admin, "hoy")
    admin.post("/admin/plazas/1/liberar", data={"fecha": MIERCOLES.isoformat()})
    assert 1 in libres(admin, "hoy")
    assert 1 not in libres(admin)                   # mañana sigue cerrada
    assert "Has solicitado la plaza 1" in solicitar(admin, 1, nombre="Ana").text


def test_no_se_libera_un_dia_pasado(admin):
    hacer_nominal(admin, 1, "Luis")
    ayer = "2026-10-13"
    assert "No se puede liberar un día pasado" in admin.post("/admin/plazas/1/liberar", data={"fecha": ayer}).text
    assert "Liberar este día" not in admin.get("/admin", params={"fecha": ayer}).text


def test_ocupar_y_liberar_reservable(admin):
    fecha = MIERCOLES.isoformat()
    assert "Plaza ocupada" in admin.post("/admin/plazas/3/ocupar", data={"fecha": fecha, "nombre": "Visita"}).text
    assert 3 not in libres(admin, "hoy")
    assert "ya está ocupada" in admin.post("/admin/plazas/3/ocupar", data={"fecha": fecha, "nombre": "Otro"}).text
    admin.post("/admin/plazas/3/liberar", data={"fecha": fecha})
    assert 3 in libres(admin, "hoy")
    assert "ya estaba libre" in admin.post("/admin/plazas/3/liberar", data={"fecha": fecha}).text


# --- Avisos al admin -----------------------------------------------------------

def test_cada_reserva_avisa_al_admin(admin):
    reservar(admin, 3, nombre="Lucía")
    solicitar(admin, 4, nombre="Raúl")
    assert 'Avisos <span class="badge">2</span>' in admin.get("/admin").text
    html = admin.get("/admin/avisos").text
    assert "Lucía ha reservado la plaza 3" in html
    assert "Raúl solicita la plaza 4 para hoy" in html
    assert 'Avisos <span class="badge">' not in admin.get("/admin").text


def test_acciones_del_admin_no_avisan(admin):
    admin.post("/admin/plazas/1/ocupar", data={"fecha": MIERCOLES.isoformat(), "nombre": "Visita"})
    assert "Todavía no hay avisos" in admin.get("/admin/avisos").text


# --- Admin: acceso y configuración -------------------------------------------

def test_admin_requiere_login(client):
    for path in ("/admin", "/admin/solicitudes", "/admin/avisos", "/admin/ajustes"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    r = client.post("/admin/plazas", data={"numeros": "7"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/login"


def test_login_incorrecto(client):
    r = client.post("/admin/login", data={"usuario": "admin", "password": "mal"})
    assert "Usuario o contraseña incorrectos" in r.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_logout(admin):
    admin.post("/admin/logout")
    assert admin.get("/admin", follow_redirects=False).status_code == 303


def test_cookie_falsificada(client):
    client.cookies.set("parking_admin", "9999999999.firmafalsa")
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_anadir_plazas_con_numeros_sueltos_y_rangos(admin):
    r = admin.post("/admin/plazas", data={"numeros": "12, 15, 20-22, 3"})
    assert "Plazas añadidas: 12, 15, 20, 21, 22" in r.text
    assert "Ya existían: 3" in r.text
    assert libres(admin) == [1, 2, 3, 4, 5, 12, 15, 20, 21, 22]
    assert "Escribe números de plaza" in admin.post("/admin/plazas", data={"numeros": "abc"}).text


def plaza_id(admin, numero):
    html = admin.get("/admin/ajustes").text
    return int(re.search(r'action="/admin/plazas/(\d+)" class="plaza-row">\s*<input[^>]*value="%d"' % numero, html).group(1))


def test_renumerar_plaza_conserva_reservas(admin):
    reservar(admin, 2, nombre="Ana")
    r = admin.post("/admin/plazas/2", data={"numero": 214, "tipo": "reservable"})
    assert "Plaza 214 guardada" in r.text
    assert libres(admin, "hoy") == [1, 3, 4, 5, 214]
    assert 214 not in libres(admin)                     # la reserva de Ana sigue en esa plaza
    assert "Ana" in admin.get("/admin", params={"fecha": JUEVES.isoformat()}).text
    assert "Ya existe la plaza 3" in admin.post("/admin/plazas/2", data={"numero": 3, "tipo": "reservable"}).text


def test_eliminar_plaza(admin):
    assert "Plaza 4 eliminada" in admin.post(f"/admin/plazas/{plaza_id(admin, 4)}/borrar").text
    assert libres(admin) == [1, 2, 3, 5]
    reservar(admin, 5)
    assert "tiene reservas futuras" in admin.post(f"/admin/plazas/{plaza_id(admin, 5)}/borrar").text
    assert 5 in libres(admin, "hoy")


def test_cambiar_titular_de_fija_liberada_y_reservada(admin):
    hacer_nominal(admin, 1, "Luis")
    admin.post("/admin/plazas/1/liberar", data={"fecha": JUEVES.isoformat()})
    reservar(admin, 1, nombre="Ana")
    r = admin.post("/admin/plazas/1", data={"numero": 1, "tipo": "nominal", "titular": "Carmen"})
    assert "Plaza 1 guardada" in r.text


def test_reservable_con_reservas_no_pasa_a_fija(admin):
    reservar(admin, 5)
    r = admin.post("/admin/plazas/5", data={"numero": 5, "tipo": "nominal", "titular": "Luis"})
    assert "cancélalas antes de hacerla fija" in r.text


def test_titular_decide_si_la_plaza_es_fija(admin):
    # Desde Ajustes solo se envían número y titular
    admin.post("/admin/plazas/3", data={"numero": 3, "titular": "Luis"})
    assert 3 not in libres(admin)
    admin.post("/admin/plazas/3", data={"numero": 3, "titular": "  "})
    assert 3 in libres(admin)
