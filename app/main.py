import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, unquote, urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi import Path as PathParam
from fastapi import Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import calendario, db, models, seguridad

BASE_DIR = Path(__file__).parent
APP_VERSION = (BASE_DIR.parent / "VERSION").read_text(encoding="utf-8").strip()
NOMBRE_COOKIE = "parking_nombre"
SESION_COOKIE = "parking_admin"
# Identificador aleatorio del dispositivo, para el límite de reservas por hora
DISPOSITIVO_COOKIE = "parking_dispositivo"
# Reservas y solicitudes hechas desde este dispositivo: «r|s.fecha.token,...»
MIAS_COOKIE = "parking_mias"
MIAS_MAX = 10
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Un id de la URL que no cabe en un entero de SQLite daría un error 500
IdFila = Annotated[int, PathParam(ge=0, le=2**63 - 1)]

# Scripts y estilos, solo los propios: nada en línea
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


# Sin /docs, /redoc ni /openapi.json: no hay API pública que documentar
app = FastAPI(title="Plazas de garaje", version=APP_VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["app_version"] = APP_VERSION


def es_https(request: Request) -> bool:
    return request.url.scheme == "https"


def cookie_segura(request: Request) -> bool:
    return es_https(request) or os.environ.get("COOKIE_SECURE") == "1"


def origen_ajeno(request: Request) -> bool:
    """Defensa contra CSRF además de SameSite=Lax, que no frena a otras webs del mismo dominio
    (por ejemplo, las de otros subdominios). Los navegadores envían Origin en todo POST."""
    origen = request.headers.get("origin")
    return request.method == "POST" and origen is not None and urlsplit(origen).netloc != request.headers.get("host")


@app.middleware("http")
async def cabeceras_de_seguridad(request: Request, call_next):
    if origen_ajeno(request):
        resp = PlainTextResponse("Origen no permitido.", status_code=status.HTTP_403_FORBIDDEN)
    else:
        resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    if es_https(request):
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def fecha_larga(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    hoy = calendario.hoy()
    prefijo = {hoy: "Hoy, ", hoy + timedelta(days=1): "Mañana, "}.get(d, "")
    texto = f"{DIAS_SEMANA[d.weekday()]} {d.day} de {MESES[d.month - 1]}"
    return prefijo + texto if prefijo else texto.capitalize()


templates.env.filters["fecha_larga"] = fecha_larga


def get_conn():
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# scope="function": la transacción se confirma antes de responder. Con el valor por defecto,
# el navegador recibiría «Has reservado» antes de que la reserva estuviera guardada.
Conn = Depends(get_conn, scope="function")


def parse_fecha(valor: str | None) -> date:
    try:
        d = date.fromisoformat(valor) if valor else calendario.hoy()
    except (TypeError, ValueError):
        return calendario.hoy()
    # El tablero enlaza al día anterior y al siguiente: no pueden salirse del calendario
    return d if date.min < d < date.max else calendario.hoy()


def ip_cliente(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def dispositivo(request: Request) -> str | None:
    valor = request.cookies.get(DISPOSITIVO_COOKIE, "")
    return valor if TOKEN_RE.fullmatch(valor) else None


def recordar_dispositivo(request: Request, resp):
    if dispositivo(request) is None:
        resp.set_cookie(DISPOSITIVO_COOKIE, secrets.token_urlsafe(16), max_age=2 * 365 * 24 * 3600,
                        httponly=True, samesite="lax", secure=cookie_segura(request))
    return resp


def leer_mias(request: Request) -> list[tuple[str, str, str]]:
    """Entradas de la cookie de este dispositivo que siguen vigentes (de hoy en adelante)."""
    hoy = calendario.hoy().isoformat()
    entradas = []
    for parte in request.cookies.get(MIAS_COOKIE, "").split(","):
        tipo, _, resto = parte.partition(".")
        fecha, _, token = resto.partition(".")
        try:
            vigente = date.fromisoformat(fecha).isoformat() >= hoy
        except ValueError:
            continue
        if tipo in ("r", "s") and vigente and TOKEN_RE.fullmatch(token):
            entradas.append((tipo, fecha, token))
    return entradas[-MIAS_MAX:]


# --- Respuestas: los mensajes van en una cookie de un solo uso, nunca en la URL ----------

def redirect(path: str, msg: str | None = None, error: str | None = None, conf: dict | None = None,
             **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    resp = RedirectResponse(f"{path}?{query}" if query else path, status_code=status.HTTP_303_SEE_OTHER)
    flash = {k: v for k, v in {"msg": msg, "error": error, "conf": conf}.items() if v}
    if flash:
        resp.set_cookie(seguridad.FLASH_COOKIE, seguridad.codificar_flash(flash),
                        max_age=60, httponly=True, samesite="lax")
    return resp


def flash(request: Request) -> dict:
    return seguridad.leer_flash(request.cookies.get(seguridad.FLASH_COOKIE))


def render(request: Request, template: str, context: dict, status_code: int = 200):
    mensajes = flash(request)
    resp = templates.TemplateResponse(request, template, {
        "msg": mensajes.get("msg"),
        "error": mensajes.get("error"),
        **context,
    }, status_code=status_code)
    if mensajes:
        resp.delete_cookie(seguridad.FLASH_COOKIE)
    return resp


# --- Días que puede elegir quien reserva -------------------------------------

def dias_usuario(conn) -> dict:
    """Hoy (con solicitud, solo si es laborable) y el siguiente día laborable (reserva directa)."""
    hoy = calendario.hoy()
    siguiente = calendario.siguiente_laborable(conn, hoy)
    return {
        "hoy": hoy if calendario.es_laborable(conn, hoy) else None,
        "siguiente": siguiente,
        "etiqueta": "Mañana" if siguiente == hoy + timedelta(days=1) else DIAS_SEMANA[siguiente.weekday()].capitalize(),
    }


def elegir_dia(conn, dia: str | None) -> tuple[str, date, dict]:
    dias = dias_usuario(conn)
    if dia == "hoy" and dias["hoy"]:
        return "hoy", dias["hoy"], dias
    return "siguiente", dias["siguiente"], dias


# --- Sesión del admin ----------------------------------------------------------

def _ir_a(path: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": path})


def require_sesion(request: Request, conn=Conn) -> None:
    if not seguridad.sesion_valida(conn, request.cookies.get(SESION_COOKIE)):
        raise _ir_a("/admin/login")


def require_admin(request: Request, conn=Conn, _=Depends(require_sesion)) -> None:
    # Con la contraseña de fábrica solo se puede entrar a cambiarla
    if seguridad.usa_password_por_defecto(conn):
        raise _ir_a("/admin/password")


# --- Público ---------------------------------------------------------------

@app.get("/health/", include_in_schema=False)
def health(conn=Conn):
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get("/")
def libres(request: Request, dia: str | None = None, conn=Conn):
    dia, fecha, dias = elegir_dia(conn, dia)
    return recordar_dispositivo(request, render(request, "libres.html", {
        "dia": dia,
        "fecha": fecha,
        "dias": dias,
        "plazas": models.plazas_libres(conn, fecha),
        "mias": models.mis_reservas(conn, leer_mias(request)),
    }))


@app.get("/reservar/{plaza_id}")
def reservar_form(request: Request, plaza_id: IdFila, dia: str | None = None, conn=Conn):
    dia, fecha, _ = elegir_dia(conn, dia)
    plaza = models.get_plaza(conn, plaza_id)
    if plaza is None or not models.esta_libre(conn, plaza_id, fecha):
        return redirect("/", dia=dia, error="Esta plaza ya no está libre.")
    return recordar_dispositivo(request, render(request, "reservar.html", {
        "plaza": plaza,
        "dia": dia,
        "fecha": fecha,
        "nombre": unquote(request.cookies.get(NOMBRE_COOKIE, "")),
        "nombre_max": models.NOMBRE_MAX,
    }))


def claves_limite(request: Request) -> list[tuple[str, int]]:
    """Límites de reservas por hora: por dispositivo y, más alto, por IP."""
    claves = [(f"reserva-ip:{ip_cliente(request)}", seguridad.reservas_por_hora_ip())]
    if disp := dispositivo(request):
        claves.append((f"reserva-disp:{disp}", seguridad.reservas_por_hora()))
    return claves


def demasiadas_reservas(request: Request):
    """Frena los scripts que reservan muchas plazas con nombres inventados."""
    if any(seguridad.limitador.excedido(clave, maximo, seguridad.RESERVAS_VENTANA)
           for clave, maximo in claves_limite(request)):
        return render(request, "aviso.html", {
            "titulo": "Demasiadas reservas",
            "texto": "Demasiadas reservas desde este dispositivo en la última hora. Inténtalo más tarde "
                     "o escribe al admin.",
        }, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def confirmar(request: Request, tipo: str, plaza, fecha: date, nombre: str, token: str,
              nueva: bool) -> RedirectResponse:
    # Pulsar dos veces no cuenta dos veces para el límite
    if nueva:
        for clave, _ in claves_limite(request):
            seguridad.limitador.anotar(clave)
    resp = redirect("/confirmacion", conf={"tipo": tipo, "plaza": plaza["numero"], "fecha": fecha.isoformat()})
    resp.set_cookie(NOMBRE_COOKIE, quote(models.limpiar_texto(nombre)), max_age=365 * 24 * 3600,
                    httponly=True, samesite="lax", secure=cookie_segura(request))
    mias = leer_mias(request)
    # Las reservas que crea el admin no tienen token: no se pueden seguir desde el dispositivo
    if token:
        entrada = (tipo[0], fecha.isoformat(), token)
        mias = [e for e in mias if e != entrada] + [entrada]
    resp.set_cookie(MIAS_COOKIE, ",".join(".".join(e) for e in mias[-MIAS_MAX:]), max_age=30 * 24 * 3600,
                    httponly=True, samesite="lax", secure=cookie_segura(request))
    return resp


DIA_CAMBIADO = "El día ha cambiado desde que abriste la plaza: vuelve a elegirla."


@app.post("/reservar/{plaza_id}")
def reservar(request: Request, plaza_id: IdFila, nombre: str = Form(...), fecha: str = Form(""),
             conn=Conn):
    if bloqueo := demasiadas_reservas(request):
        return bloqueo
    dia = dias_usuario(conn)["siguiente"]
    # El formulario dice para qué día era: si ha pasado la medianoche, no se reserva otro día sin avisar
    if fecha != dia.isoformat():
        return redirect("/", error=DIA_CAMBIADO)
    error, token, nueva = models.reservar_usuario(conn, plaza_id, dia, nombre)
    if error:
        return redirect("/", error=error)
    plaza = models.get_plaza(conn, plaza_id)
    nombre = models.limpiar_texto(nombre)
    if nueva:
        models.avisar(conn, f"{nombre} ha reservado la plaza {plaza['numero']} para {fecha_larga(dia).lower()}.")
    return confirmar(request, "reserva", plaza, dia, nombre, token, nueva)


@app.post("/solicitar/{plaza_id}")
def solicitar(request: Request, plaza_id: IdFila, nombre: str = Form(...), fecha: str = Form(""),
              conn=Conn):
    if bloqueo := demasiadas_reservas(request):
        return bloqueo
    dia = dias_usuario(conn)["hoy"]
    if dia is None:
        return redirect("/", error="Hoy no es laborable: no se pueden pedir plazas para hoy.")
    if fecha != dia.isoformat():
        return redirect("/", error=DIA_CAMBIADO)
    error, token, nueva = models.solicitar(conn, plaza_id, dia, nombre)
    if error:
        return redirect("/", dia="hoy", error=error)
    plaza = models.get_plaza(conn, plaza_id)
    nombre = models.limpiar_texto(nombre)
    if nueva:
        models.avisar(conn, f"{nombre} solicita la plaza {plaza['numero']} para hoy.")
    return confirmar(request, "solicitud", plaza, dia, nombre, token, nueva)


@app.get("/confirmacion")
def confirmacion(request: Request, conn=Conn):
    # Los datos llegan en la cookie de un solo uso: no se puede fabricar una confirmación con un enlace
    conf = flash(request).get("conf")
    if not isinstance(conf, dict):
        return redirect("/")
    dia = parse_fecha(conf.get("fecha"))
    plaza = conf.get("plaza")
    email = models.get_config(conn, "admin_email")
    asunto = quote(f"Cancelar reserva de la plaza {plaza} para el {fecha_larga(dia).lower()}")
    return render(request, "confirmacion.html", {
        "tipo": conf.get("tipo"),
        "plaza": plaza,
        "fecha": dia,
        "email": email,
        "mailto": f"mailto:{email}?subject={asunto}" if email else None,
    })


# --- Acceso del admin ------------------------------------------------------------

@app.get("/admin/login")
def login_form(request: Request):
    return render(request, "login.html", {})


@app.post("/admin/login")
def login(request: Request, usuario: str = Form(...), password: str = Form(...), conn=Conn):
    clave = f"login:{ip_cliente(request)}"
    if seguridad.limitador.excedido(clave, seguridad.LOGIN_MAX_FALLOS, seguridad.LOGIN_VENTANA):
        return render(request, "login.html", {
            "error": "Demasiados intentos fallidos. Espera 15 minutos antes de volver a probar.",
        }, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    if not seguridad.credenciales_correctas(conn, usuario, password):
        seguridad.limitador.anotar(clave)
        return redirect("/admin/login", error="Usuario o contraseña incorrectos.")
    seguridad.limitador.olvidar(clave)
    token = seguridad.crear_sesion(conn)
    resp = redirect("/admin/password" if seguridad.usa_password_por_defecto(conn) else "/admin")
    resp.set_cookie(SESION_COOKIE, token, max_age=seguridad.SESION_DURACION,
                    httponly=True, samesite="lax", secure=cookie_segura(request))
    return resp


@app.post("/admin/logout")
def logout(request: Request, conn=Conn):
    seguridad.cerrar_sesion(conn, request.cookies.get(SESION_COOKIE))
    resp = redirect("/admin/login")
    resp.delete_cookie(SESION_COOKIE)
    return resp


@app.get("/admin/password", dependencies=[Depends(require_sesion)])
def password_form(request: Request, conn=Conn):
    return render(request, "password.html", {
        "admin": True,
        "obligatorio": seguridad.usa_password_por_defecto(conn),
        "minimo": seguridad.PASSWORD_MINIMA,
    })


@app.post("/admin/password", dependencies=[Depends(require_sesion)])
def cambiar_password(request: Request, actual: str = Form(...), nueva: str = Form(...), repetir: str = Form(...),
                     conn=Conn):
    if not seguridad.password_correcta(conn, actual):
        return redirect("/admin/password", error="La contraseña actual no es correcta.")
    error = seguridad.validar_password_nueva(nueva, repetir)
    if error:
        return redirect("/admin/password", error=error)
    seguridad.guardar_password(conn, nueva)
    seguridad.cerrar_otras_sesiones(conn, request.cookies.get(SESION_COOKIE))
    return redirect("/admin", msg="Contraseña cambiada. Se han cerrado las demás sesiones.")


# --- Administración --------------------------------------------------------

admin_only = [Depends(require_admin)]


def alertas_admin(conn) -> list[str]:
    """Cosas de la configuración que afectan al día a día y hay que resolver."""
    alertas = []
    if not models.get_config(conn, "admin_email"):
        alertas.append("Falta tu correo en Ajustes: sin él, quien reserva no sabe a quién escribir para cancelar.")
    for anio in models.faltan_festivos(conn):
        alertas.append(f"Faltan los festivos de {anio}: añádelos en Ajustes para que no se pueda "
                       "reservar en días sin trabajo.")
    return alertas


def admin_page(request: Request, conn, template: str, **context):
    return render(request, template, {
        "admin": True,
        "pendientes": models.contar_pendientes(conn),
        "no_leidos": models.contar_no_leidos(conn),
        "alertas": alertas_admin(conn),
        **context,
    })


FILTROS = {
    "libres": ("libre", "nominal_liberada"),
    "ocupadas": ("reservada", "nominal"),
    "fijas": ("nominal", "nominal_liberada"),
}


@app.get("/admin", dependencies=admin_only)
def admin(request: Request, fecha: str | None = None, ver: str | None = None, conn=Conn):
    dia = parse_fecha(fecha)
    plazas = models.estado_plazas(conn, dia)
    no_laborable = calendario.festivo(conn, dia) or ("Fin de semana" if dia.weekday() >= 5 else None)
    cuenta = {e: sum(p["estado"] == e for p in plazas)
              for e in ("libre", "nominal_liberada", "reservada", "nominal")}
    resumen = {
        "total": len(plazas),
        "libres": cuenta["libre"] + cuenta["nominal_liberada"],
        "reservadas": cuenta["reservada"],
        "fijas": cuenta["nominal"],
        "ocupadas": cuenta["reservada"] + cuenta["nominal"],
    }
    resumen["pct"] = round(100 * resumen["ocupadas"] / resumen["total"]) if plazas else 0
    ver = ver if ver in FILTROS else "todas"
    if ver != "todas":
        plazas = [p for p in plazas if p["estado"] in FILTROS[ver]]
    return admin_page(request, conn, "admin.html",
                      fecha=dia,
                      hoy=calendario.hoy(),
                      anterior=dia - timedelta(days=1),
                      siguiente=dia + timedelta(days=1),
                      plazas=plazas,
                      resumen=resumen,
                      ver=ver,
                      no_laborable=no_laborable,
                      pasado=dia < calendario.hoy(),
                      nombre_max=models.NOMBRE_MAX)


def _filtro(ver: str | None) -> str | None:
    return ver if ver in FILTROS else None


@app.post("/admin/plazas/{plaza_id}/liberar", dependencies=admin_only)
def admin_liberar(plaza_id: IdFila, fecha: str = Form(...), ver: str | None = Form(None), conn=Conn):
    dia = parse_fecha(fecha)
    antes = models.estado_plaza(conn, plaza_id, dia)
    error = models.liberar(conn, plaza_id, dia)
    if not error:
        cuando = fecha_larga(dia).lower()
        if antes["estado"] == "reservada":
            texto = f"Admin anuló la reserva de {antes['reservada_por']} en la plaza {antes['numero']} para {cuando}."
        else:
            texto = f"Admin cedió la plaza fija {antes['numero']} de {antes['titular']} para {cuando}."
        models.avisar(conn, texto, leido=True)
    return redirect("/admin", fecha=dia.isoformat(), ver=_filtro(ver), error=error,
                    msg=None if error else "Plaza liberada.")


@app.post("/admin/plazas/{plaza_id}/ocupar", dependencies=admin_only)
def admin_ocupar(plaza_id: IdFila, fecha: str = Form(...), nombre: str = Form(""), ver: str | None = Form(None),
                 conn=Conn):
    dia = parse_fecha(fecha)
    error = models.ocupar(conn, plaza_id, dia, nombre)
    if not error:
        p = models.estado_plaza(conn, plaza_id, dia)
        quien = p["reservada_por"] if p["estado"] == "reservada" else f"su titular, {p['titular']}"
        models.avisar(conn, f"Admin asignó la plaza {p['numero']} a {quien} para {fecha_larga(dia).lower()}.",
                      leido=True)
    return redirect("/admin", fecha=dia.isoformat(), ver=_filtro(ver), error=error,
                    msg=None if error else "Plaza ocupada.")


@app.get("/admin/solicitudes", dependencies=admin_only)
def admin_solicitudes(request: Request, conn=Conn):
    return admin_page(request, conn, "admin_solicitudes.html",
                      solicitudes=models.solicitudes_pendientes(conn))


@app.post("/admin/solicitudes/{solicitud_id}/aprobar", dependencies=admin_only)
def admin_aprobar(solicitud_id: IdFila, conn=Conn):
    error = models.aprobar(conn, solicitud_id)
    return redirect("/admin/solicitudes", error=error, msg=None if error else "Solicitud aprobada.")


@app.post("/admin/solicitudes/{solicitud_id}/rechazar", dependencies=admin_only)
def admin_rechazar(solicitud_id: IdFila, conn=Conn):
    ok = models.rechazar(conn, solicitud_id)
    return redirect("/admin/solicitudes", msg="Solicitud rechazada." if ok else None,
                    error=None if ok else "La solicitud ya no está pendiente.")


@app.get("/admin/avisos", dependencies=admin_only)
def admin_avisos(request: Request, conn=Conn):
    # Se leen antes de marcarlos, para resaltar los no leídos en esta visita
    avisos = models.avisos_recientes(conn)
    models.marcar_leidos(conn)
    return admin_page(request, conn, "admin_avisos.html", avisos=avisos)


@app.get("/admin/ajustes", dependencies=admin_only)
def admin_ajustes(request: Request, conn=Conn):
    return admin_page(request, conn, "admin_ajustes.html",
                      email=models.get_config(conn, "admin_email") or "",
                      festivos=models.festivos_futuros(conn),
                      plazas=models.list_plazas(conn),
                      nombre_max=models.NOMBRE_MAX,
                      texto_max=models.TEXTO_MAX)


@app.post("/admin/plazas", dependencies=admin_only)
def admin_crear_plazas(numeros: str = Form(...), conn=Conn):
    creadas, error = models.crear_plazas(conn, numeros)
    msg = None
    if creadas:
        msg = f"Plaza{'s' if len(creadas) != 1 else ''} añadida{'s' if len(creadas) != 1 else ''}: {', '.join(map(str, creadas))}."
    return redirect("/admin/ajustes", msg=msg, error=error)


@app.post("/admin/plazas/{plaza_id}/borrar", dependencies=admin_only)
def admin_borrar_plaza(plaza_id: IdFila, conn=Conn):
    plaza = models.get_plaza(conn, plaza_id)
    error = models.borrar_plaza(conn, plaza_id)
    return redirect("/admin/ajustes", error=error, msg=None if error else f"Plaza {plaza['numero']} eliminada.")


@app.post("/admin/email", dependencies=admin_only)
def admin_email(email: str = Form(""), conn=Conn):
    email = email.strip()
    if email and (len(email) > 254 or not EMAIL_RE.fullmatch(email)):
        return redirect("/admin/ajustes", error="El correo no es válido.")
    models.set_config(conn, "admin_email", email)
    return redirect("/admin/ajustes", msg="Correo guardado.")


@app.post("/admin/festivos", dependencies=admin_only)
def admin_festivo(fecha: str = Form(...), nombre: str = Form(...), conn=Conn):
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return redirect("/admin/ajustes", error="Fecha no válida.")
    error = models.add_festivo(conn, dia, nombre)
    if error:
        return redirect("/admin/ajustes", error=error)
    msg = "Festivo añadido."
    if n := models.reservas_del_dia(conn, dia):
        msg += (f" Ojo: ese día ya hay {n} reserva{'s' if n != 1 else ''}; avisa a quien reservó "
                "o libéralas desde el tablero.")
    return redirect("/admin/ajustes", msg=msg)


@app.post("/admin/festivos/{fecha}/borrar", dependencies=admin_only)
def admin_borrar_festivo(fecha: str, conn=Conn):
    ok = models.delete_festivo(conn, fecha)
    return redirect("/admin/ajustes", msg="Festivo eliminado." if ok else None,
                    error=None if ok else "Ese festivo no existe.")


@app.post("/admin/plazas/{plaza_id}", dependencies=admin_only)
def admin_plaza(plaza_id: IdFila, numero: int = Form(...), titular: str = Form(""), tipo: str | None = Form(None),
                conn=Conn):
    # Con titular la plaza es fija; sin él, reservable
    tipo = tipo or ("nominal" if titular.strip() else "reservable")
    error = models.update_plaza(conn, plaza_id, numero, tipo, titular)
    return redirect("/admin/ajustes", error=error, msg=None if error else f"Plaza {numero} guardada.")
