import hashlib
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import calendario, db, models

BASE_DIR = Path(__file__).parent
APP_VERSION = (BASE_DIR.parent / "VERSION").read_text(encoding="utf-8").strip()
NOMBRE_COOKIE = "parking_nombre"
SESION_COOKIE = "parking_admin"
SESION_DURACION = 30 * 24 * 3600
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Plazas de garaje", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["app_version"] = APP_VERSION


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
    finally:
        conn.close()


def parse_fecha(valor: str | None) -> date:
    try:
        return date.fromisoformat(valor) if valor else calendario.hoy()
    except ValueError:
        return calendario.hoy()


def redirect(path: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=status.HTTP_303_SEE_OTHER)


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

def _firma(conn, expira: int) -> str:
    secreto = models.get_config(conn, "secret").encode()
    return hmac.new(secreto, f"admin:{expira}".encode(), hashlib.sha256).hexdigest()


def sesion_valida(request: Request, conn) -> bool:
    try:
        expira, firma = request.cookies.get(SESION_COOKIE, "").split(".")
        return int(expira) > time.time() and hmac.compare_digest(firma, _firma(conn, int(expira)))
    except ValueError:
        return False


def require_admin(request: Request, conn=Depends(get_conn)) -> None:
    if not sesion_valida(request, conn):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})


def credenciales_correctas(usuario: str, password: str) -> bool:
    ok_usuario = secrets.compare_digest(usuario.encode(), os.environ.get("ADMIN_USER", "admin").encode())
    password_file = os.environ.get("ADMIN_PASSWORD_FILE")
    expected_password = Path(password_file).read_text() if password_file else os.environ.get("ADMIN_PASSWORD", "admin")
    ok_password = secrets.compare_digest(password.encode(), expected_password.encode())
    return ok_usuario and ok_password


# --- Público ---------------------------------------------------------------

@app.get("/health/", include_in_schema=False)
def health(conn=Depends(get_conn)):
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get("/")
def libres(request: Request, dia: str | None = None, error: str | None = None, conn=Depends(get_conn)):
    dia, fecha, dias = elegir_dia(conn, dia)
    return templates.TemplateResponse(request, "libres.html", {
        "dia": dia,
        "fecha": fecha,
        "dias": dias,
        "plazas": models.plazas_libres(conn, fecha),
        "error": error,
    })


@app.get("/reservar/{plaza_id}")
def reservar_form(request: Request, plaza_id: int, dia: str | None = None, conn=Depends(get_conn)):
    dia, fecha, _ = elegir_dia(conn, dia)
    plaza = models.get_plaza(conn, plaza_id)
    if plaza is None or not models.esta_libre(conn, plaza_id, fecha):
        return redirect("/", dia=dia, error="Esta plaza ya no está libre.")
    return templates.TemplateResponse(request, "reservar.html", {
        "plaza": plaza,
        "dia": dia,
        "fecha": fecha,
        "nombre": request.cookies.get(NOMBRE_COOKIE, ""),
    })


def confirmar(tipo: str, plaza, fecha: date, nombre: str) -> RedirectResponse:
    resp = redirect("/confirmacion", tipo=tipo, plaza=plaza["numero"], fecha=fecha.isoformat())
    resp.set_cookie(NOMBRE_COOKIE, nombre.strip(), max_age=365 * 24 * 3600, samesite="lax")
    return resp


@app.post("/reservar/{plaza_id}")
def reservar(plaza_id: int, nombre: str = Form(...), conn=Depends(get_conn)):
    fecha = dias_usuario(conn)["siguiente"]
    error = models.reservar(conn, plaza_id, fecha, nombre)
    if error:
        return redirect("/", error=error)
    plaza = models.get_plaza(conn, plaza_id)
    models.avisar(conn, f"{nombre.strip()} ha reservado la plaza {plaza['numero']} para {fecha_larga(fecha).lower()}.")
    return confirmar("reserva", plaza, fecha, nombre)


@app.post("/solicitar/{plaza_id}")
def solicitar(plaza_id: int, nombre: str = Form(...), conn=Depends(get_conn)):
    fecha = dias_usuario(conn)["hoy"]
    if fecha is None:
        return redirect("/", error="Hoy no es laborable: no se pueden pedir plazas para hoy.")
    error = models.solicitar(conn, plaza_id, fecha, nombre)
    if error:
        return redirect("/", dia="hoy", error=error)
    plaza = models.get_plaza(conn, plaza_id)
    models.avisar(conn, f"{nombre.strip()} solicita la plaza {plaza['numero']} para hoy.")
    return confirmar("solicitud", plaza, fecha, nombre)


@app.get("/confirmacion")
def confirmacion(request: Request, tipo: str, plaza: int, fecha: str, conn=Depends(get_conn)):
    dia = parse_fecha(fecha)
    email = models.get_config(conn, "admin_email")
    asunto = quote(f"Cancelar reserva de la plaza {plaza} para el {fecha_larga(dia).lower()}")
    return templates.TemplateResponse(request, "confirmacion.html", {
        "tipo": tipo,
        "plaza": plaza,
        "fecha": dia,
        "email": email,
        "mailto": f"mailto:{email}?subject={asunto}" if email else None,
    })


# --- Administración --------------------------------------------------------

@app.get("/admin/login")
def login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/admin/login")
def login(usuario: str = Form(...), password: str = Form(...), conn=Depends(get_conn)):
    if not credenciales_correctas(usuario, password):
        return redirect("/admin/login", error="Usuario o contraseña incorrectos.")
    expira = int(time.time()) + SESION_DURACION
    resp = redirect("/admin")
    resp.set_cookie(SESION_COOKIE, f"{expira}.{_firma(conn, expira)}",
                    max_age=SESION_DURACION, httponly=True, samesite="lax")
    return resp


@app.post("/admin/logout")
def logout():
    resp = redirect("/admin/login")
    resp.delete_cookie(SESION_COOKIE)
    return resp


admin_only = [Depends(require_admin)]


def admin_page(request: Request, conn, template: str, **context):
    return templates.TemplateResponse(request, template, {
        "admin": True,
        "pendientes": models.contar_pendientes(conn),
        "no_leidos": models.contar_no_leidos(conn),
        "msg": request.query_params.get("msg"),
        "error": request.query_params.get("error"),
        **context,
    })


FILTROS = {
    "libres": ("libre", "nominal_liberada"),
    "ocupadas": ("reservada", "nominal"),
    "fijas": ("nominal", "nominal_liberada"),
}


@app.get("/admin", dependencies=admin_only)
def admin(request: Request, fecha: str | None = None, ver: str | None = None, conn=Depends(get_conn)):
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
                      pasado=dia < calendario.hoy())


@app.post("/admin/plazas/{plaza_id}/liberar", dependencies=admin_only)
def admin_liberar(plaza_id: int, fecha: str = Form(...), ver: str | None = Form(None), conn=Depends(get_conn)):
    dia = parse_fecha(fecha)
    error = models.liberar(conn, plaza_id, dia)
    return redirect("/admin", fecha=dia.isoformat(), ver=ver, error=error,
                    msg=None if error else "Plaza liberada.")


@app.post("/admin/plazas/{plaza_id}/ocupar", dependencies=admin_only)
def admin_ocupar(plaza_id: int, fecha: str = Form(...), nombre: str = Form(""), ver: str | None = Form(None),
                 conn=Depends(get_conn)):
    dia = parse_fecha(fecha)
    error = models.ocupar(conn, plaza_id, dia, nombre)
    return redirect("/admin", fecha=dia.isoformat(), ver=ver, error=error,
                    msg=None if error else "Plaza ocupada.")


@app.get("/admin/solicitudes", dependencies=admin_only)
def admin_solicitudes(request: Request, conn=Depends(get_conn)):
    return admin_page(request, conn, "admin_solicitudes.html",
                      solicitudes=models.solicitudes_pendientes(conn))


@app.post("/admin/solicitudes/{solicitud_id}/aprobar", dependencies=admin_only)
def admin_aprobar(solicitud_id: int, conn=Depends(get_conn)):
    error = models.aprobar(conn, solicitud_id)
    return redirect("/admin/solicitudes", error=error, msg=None if error else "Solicitud aprobada.")


@app.post("/admin/solicitudes/{solicitud_id}/rechazar", dependencies=admin_only)
def admin_rechazar(solicitud_id: int, conn=Depends(get_conn)):
    ok = models.rechazar(conn, solicitud_id)
    return redirect("/admin/solicitudes", msg="Solicitud rechazada." if ok else None,
                    error=None if ok else "La solicitud ya no está pendiente.")


@app.get("/admin/avisos", dependencies=admin_only)
def admin_avisos(request: Request, conn=Depends(get_conn)):
    # Se calculan los no leídos antes de marcarlos, para resaltarlos en esta visita
    no_leidos = models.contar_no_leidos(conn)
    avisos = models.avisos_recientes(conn)
    models.marcar_leidos(conn)
    return admin_page(request, conn, "admin_avisos.html", avisos=avisos, nuevos=no_leidos)


@app.get("/admin/ajustes", dependencies=admin_only)
def admin_ajustes(request: Request, conn=Depends(get_conn)):
    return admin_page(request, conn, "admin_ajustes.html",
                      email=models.get_config(conn, "admin_email") or "",
                      festivos=models.festivos_futuros(conn),
                      plazas=models.list_plazas(conn))


@app.post("/admin/plazas", dependencies=admin_only)
def admin_crear_plazas(numeros: str = Form(...), conn=Depends(get_conn)):
    creadas, error = models.crear_plazas(conn, numeros)
    msg = None
    if creadas:
        msg = f"Plaza{'s' if len(creadas) != 1 else ''} añadida{'s' if len(creadas) != 1 else ''}: {', '.join(map(str, creadas))}."
    return redirect("/admin/ajustes", msg=msg, error=error)


@app.post("/admin/plazas/{plaza_id}/borrar", dependencies=admin_only)
def admin_borrar_plaza(plaza_id: int, conn=Depends(get_conn)):
    plaza = models.get_plaza(conn, plaza_id)
    error = models.borrar_plaza(conn, plaza_id)
    return redirect("/admin/ajustes", error=error, msg=None if error else f"Plaza {plaza['numero']} eliminada.")


@app.post("/admin/email", dependencies=admin_only)
def admin_email(email: str = Form(""), conn=Depends(get_conn)):
    models.set_config(conn, "admin_email", email.strip())
    return redirect("/admin/ajustes", msg="Correo guardado.")


@app.post("/admin/festivos", dependencies=admin_only)
def admin_festivo(fecha: str = Form(...), nombre: str = Form(...), conn=Depends(get_conn)):
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return redirect("/admin/ajustes", error="Fecha no válida.")
    error = models.add_festivo(conn, dia, nombre)
    return redirect("/admin/ajustes", error=error, msg=None if error else "Festivo añadido.")


@app.post("/admin/festivos/{fecha}/borrar", dependencies=admin_only)
def admin_borrar_festivo(fecha: str, conn=Depends(get_conn)):
    ok = models.delete_festivo(conn, fecha)
    return redirect("/admin/ajustes", msg="Festivo eliminado." if ok else None,
                    error=None if ok else "Ese festivo no existe.")


@app.post("/admin/plazas/{plaza_id}", dependencies=admin_only)
def admin_plaza(plaza_id: int, numero: int = Form(...), titular: str = Form(""), tipo: str | None = Form(None),
                conn=Depends(get_conn)):
    # Con titular la plaza es fija; sin él, reservable
    tipo = tipo or ("nominal" if titular.strip() else "reservable")
    error = models.update_plaza(conn, plaza_id, numero, tipo, titular)
    return redirect("/admin/ajustes", error=error, msg=None if error else f"Plaza {numero} guardada.")
