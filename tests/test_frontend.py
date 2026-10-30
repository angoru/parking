"""Calidad del HTML y el CSS: lo que un navegador no avisa y es fácil romper sin darse cuenta."""
import re
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import calendario, seguridad
from app.main import app

RAIZ = Path(__file__).resolve().parent.parent / "app"
CSS = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
JS = (RAIZ / "static" / "app.js").read_text(encoding="utf-8")
PLANTILLAS = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "templates").glob("*.html"))
CLAVE = "clave-de-prueba-123"
CSS_SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
SELECTORES = re.sub(r"\{[^{}]*\}", "{}", CSS_SIN_COMENTARIOS)
CLASES_CSS = set(re.findall(r"\.([a-zA-Z][\w-]*)", SELECTORES))
FUERA_DE_VARIABLES = CSS_SIN_COMENTARIOS.split("* { box-sizing", 1)[1]


def clases_en_plantillas() -> set[str]:
    clases = set()
    for atributo in re.findall(r'class="([^"]*)"', PLANTILLAS):
        clases |= set(re.sub(r"\{\{.*?\}\}|\{%.*?%\}", " ", atributo).split())
    # Las que se escriben con Jinja: class="{{ 'punto-aviso' if ... else 'punto-vacio' }}"
    for atributo in re.findall(r'class="[^"]*\{\{([^"]*?)\}\}', PLANTILLAS):
        clases |= set(re.findall(r"'([a-z-]+)'", atributo))
    # En {% block contenido_clase %}
    clases |= set(re.findall(r"contenido_clase %\}([\w-]+)\{%", PLANTILLAS))
    return {c for c in clases if not c.endswith("-")}


def test_toda_clase_usada_tiene_estilos():
    # «contenido-…», «fija»… sí están en el CSS; las variantes con {{ }} se comprueban abajo
    assert clases_en_plantillas() - CLASES_CSS == set()


def test_todo_estilo_tiene_quien_lo_use():
    dinamicas = set(re.findall(r"([a-z][\w-]*)-\{\{", PLANTILLAS))
    usadas = clases_en_plantillas() | set(re.findall(r'toggle\("([\w-]+)"', JS))
    sobran = {c for c in CLASES_CSS - usadas if not any(c.startswith(f"{d}-") for d in dinamicas)}
    assert sobran == set()


def test_nombres_de_clase_en_kebab_case():
    assert [c for c in CLASES_CSS if not re.fullmatch(r"[a-z]+(-[a-z]+)*", c)] == []


def test_toda_variable_usada_existe_y_toda_definida_se_usa():
    definidas = set(re.findall(r"(--[\w-]+)\s*:", CSS_SIN_COMENTARIOS))
    usadas = set(re.findall(r"var\((--[\w-]+)\)", CSS_SIN_COMENTARIOS))
    assert usadas == definidas


def test_colores_radios_y_tamanos_salen_de_las_variables():
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", FUERA_DE_VARIABLES) == []
    assert re.findall(r"border-radius:\s(?!var\(|50%)[^;}]+", FUERA_DE_VARIABLES) == []
    # 16px es a propósito: con menos, iOS hace zoom al escribir
    assert re.findall(r"font-size:\s(?!var\(|16px)[^;}]+", FUERA_DE_VARIABLES) == []


def test_modo_oscuro_redefine_solo_variables_que_existen():
    claro, oscuro = CSS_SIN_COMENTARIOS.split("@media (prefers-color-scheme: dark)", 1)
    oscuro = oscuro.split("/* ---", 1)[0].split("* { box-sizing", 1)[0]
    assert set(re.findall(r"(--[\w-]+)\s*:", oscuro)) <= set(re.findall(r"(--[\w-]+)\s*:", claro))


def test_sin_selectores_repartidos_por_el_fichero():
    # Un selector aparece una sola vez fuera de las media queries, para que no se pisen entre sí
    base = FUERA_DE_VARIABLES.split("@media", 1)[0]
    repetidos = [s for s, n in Counter(s.strip() for s in re.findall(r"(?m)^([^\s@}][^{}]*?)\s*\{", base)).items() if n > 1]
    assert repetidos == []


def test_sin_estilos_en_linea_y_csp_que_los_bloquea(client):
    assert not re.search(r"\sstyle\s*=", PLANTILLAS) and "<style" not in PLANTILLAS
    csp = client.get("/").headers["content-security-policy"]
    assert "unsafe-inline" not in csp and "style-src 'self'" in csp


class Pagina(HTMLParser):
    """Recoge lo que hace falta para comprobar la estructura de una página."""

    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.ids = []
        self.etiquetas_para = set()
        self.dentro_de_label = 0
        self.campos = []
        self.sin_nombre = []
        self._boton = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "h1":
            self.h1 += 1
        elif tag == "label":
            self.dentro_de_label += 1
            self.etiquetas_para.add(a.get("for"))
        elif tag == "input" and a.get("type") != "hidden":
            self.campos.append((a, self.dentro_de_label > 0))
        elif tag == "button":
            self._boton = {"attrs": a, "texto": ""}

    def handle_endtag(self, tag):
        if tag == "label":
            self.dentro_de_label -= 1
        elif tag == "button" and self._boton:
            if not (self._boton["texto"].strip() or self._boton["attrs"].get("aria-label")):
                self.sin_nombre.append(self._boton["attrs"])
            self._boton = None

    def handle_data(self, data):
        if self._boton:
            self._boton["texto"] += data


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PARKING_TOTAL", "3")
    monkeypatch.delenv("ADMIN_USER", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", CLAVE)
    monkeypatch.setattr(calendario, "hoy", lambda: date(2026, 10, 14))
    seguridad.limitador.reset()
    with TestClient(app) as c:
        yield c


def analizar(html: str) -> Pagina:
    pagina = Pagina()
    pagina.feed(html)
    return pagina


RUTAS_PUBLICAS = ["/", "/?dia=hoy", "/reservar/1", "/reservar/1?dia=hoy", "/admin/login"]
RUTAS_ADMIN = ["/admin", "/admin?ver=libres", "/admin/solicitudes", "/admin/avisos", "/admin/ajustes", "/admin/password"]


def comprobar_estructura(html: str):
    p = analizar(html)
    assert p.h1 == 1
    assert len(p.ids) == len(set(p.ids))
    assert p.sin_nombre == []
    for attrs, en_label in p.campos:
        assert en_label or attrs.get("aria-label") or attrs.get("id") in p.etiquetas_para, attrs


@pytest.mark.parametrize("ruta", RUTAS_PUBLICAS)
def test_estructura_paginas_publicas(client, ruta):
    comprobar_estructura(client.get(ruta).text)


@pytest.mark.parametrize("ruta", RUTAS_ADMIN)
def test_estructura_paginas_de_admin(client, ruta):
    client.post("/admin/login", data={"usuario": "admin", "password": CLAVE})
    comprobar_estructura(client.get(ruta).text)


def test_estructura_con_reservas_y_confirmacion(client):
    html = client.post("/reservar/1", data={"nombre": "Ana", "fecha": "2026-10-15"}).text
    comprobar_estructura(html)
    comprobar_estructura(client.get("/").text)


def test_marca_la_pagina_actual_en_menu_pestanas_y_filtros(client):
    assert '<a href="/?dia=hoy" aria-current="page">Hoy</a>' in client.get("/?dia=hoy").text
    client.post("/admin/login", data={"usuario": "admin", "password": CLAVE})
    assert '<a href="/admin/ajustes" aria-current="page">Ajustes</a>' in client.get("/admin/ajustes").text
    assert re.search(r'ver=libres" aria-current="page">Libres</a>', client.get("/admin?ver=libres").text)


def test_el_favicon_existe(client):
    assert client.get("/static/favicon.svg").status_code == 200
