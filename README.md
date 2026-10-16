# Plazas de garaje

Aplicación web (pensada para el móvil) para reservar plazas de garaje.

- Las plazas se dan de alta con su número real desde el panel del admin.
- Cada plaza es **fija** (de un titular; el admin puede cederla un día concreto) o **reservable**.
- La página principal muestra **solo las plazas libres**; las reservadas y las nominales no aparecen.
- Se reserva directamente para el **siguiente día laborable** (el viernes, para el lunes; los festivos de Madrid también se saltan). Para **hoy** se envía una solicitud que el admin aprueba o rechaza.
- Tras reservar se muestra "Has reservado la plaza N"; para cancelar, se escribe al admin.
- No hay cuentas: para reservar basta con escribir el nombre.
- El admin ve todas las plazas, puede liberar u ocupar cualquiera y recibe un aviso de cada reserva.

La especificación funcional completa está en [`specs.md`](specs.md).

El despliegue en un servidor (GitHub Actions, GHCR, Caddy y copias cifradas) se describe en [`DEPLOY.md`](DEPLOY.md).

## Versiones

La versión actual está en [`VERSION`](VERSION) y aparece al pie de todas las páginas. Para publicar una nueva versión, actualiza ese archivo siguiendo `mayor.menor.parche` y crea la etiqueta Git `v<versión>` sobre el commit desplegado. También lo devuelve FastAPI en `app.version` (no se publica `/openapi.json`).

## Puesta en marcha

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # requirements-dev.txt para desarrollar (tests)
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8642 --no-server-header
```

Desde el móvil (en la misma red): `http://<ip-del-ordenador>:8642`.

**Primer acceso del admin:** entra con `admin` / `admin` y la app te obligará a elegir una contraseña nueva
(mínimo 10 caracteres) antes de dejarte usar el panel. Después se cambia en **Ajustes → Seguridad**.

## Seguridad

- **Contraseña del admin:** se guarda con *scrypt* en la base de datos. Cambiarla cierra las demás sesiones.
- **Sesiones:** token aleatorio en una cookie `HttpOnly` y `SameSite=Lax`; en la base de datos solo se guarda su hash,
  así que «Salir» invalida la sesión de verdad.
- **Límites por IP** (en memoria, se reinician al reiniciar el servidor):
  5 intentos de login fallidos cada 15 minutos y `RESERVAS_POR_HORA` reservas o solicitudes por hora.
- **Cabeceras:** `Content-Security-Policy` sin scripts en línea, `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy` y `Cache-Control: no-store` en el panel del admin. `--no-server-header` oculta el servidor.
- **Mensajes:** los avisos tras una acción viajan en una cookie de un solo uso, nunca en la URL.

### Publicarla fuera de la red local (HTTPS)

En la red de casa u oficina funciona por HTTP, pero **la contraseña viaja sin cifrar por la wifi**. Para publicarla,
ponla detrás de un proxy con HTTPS, por ejemplo [Caddy](https://caddyserver.com/), que obtiene el certificado solo:

```
# Caddyfile
garaje.tudominio.es {
    reverse_proxy 127.0.0.1:8642
}
```

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8642 --no-server-header \
    --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Con eso la app detecta HTTPS: marca las cookies como `Secure` y envía `Strict-Transport-Security`.
Si el proxy está en otra máquina, usa `COOKIE_SECURE=1` y pon su IP en `--forwarded-allow-ips`
(nunca `*`: cualquiera podría falsear su IP y saltarse los límites).

## Variables de entorno

| Variable         | Por defecto  | Uso                                                        |
|------------------|--------------|------------------------------------------------------------|
| `ADMIN_USER`     | `admin`      | Usuario del acceso admin (`/admin/login`).                 |
| `ADMIN_PASSWORD` | —            | Contraseña inicial del admin. Sin ella, la inicial es `admin` y hay que cambiarla al entrar. La que se guarde desde la app tiene prioridad. |
| `ADMIN_PASSWORD_FILE` | —       | Archivo con la contraseña inicial (secreto del contenedor). Tiene prioridad sobre `ADMIN_PASSWORD`; la guardada desde la app, sobre ambas. |
| `COOKIE_SECURE`  | —            | `1` para marcar las cookies como `Secure` aunque la app no vea HTTPS (proxy en otra máquina). |
| `RESERVAS_POR_HORA` | `5`       | Máximo de reservas y solicitudes por hora desde una misma IP. |
| `PARKING_DB`     | `parking.db` | Ruta del archivo SQLite.                                   |
| `PARKING_TOTAL`  | `10`         | Solo la primera vez: crea las plazas 1..N. Después se numeran desde Admin → Ajustes. |

## Páginas

- `/` — plazas libres, pestañas Hoy (solicitar) y siguiente día laborable (reservar).
- `/reservar/{id}` — formulario con el nombre.
- `/confirmacion` — "Has reservado la plaza N" y cómo cancelar.
- `/admin/login` — acceso del admin.
- `/admin/password` — cambiar la contraseña del admin (obligatorio la primera vez).
- `/admin` — tablero del día con todas las plazas; liberar y ocupar.
- `/admin/solicitudes` — aprobar o rechazar las solicitudes para hoy.
- `/admin/avisos` — avisos de reservas, solicitudes y cancelaciones.
- `/admin/ajustes` — alta y numeración de plazas (sueltas o por rangos), plazas fijas, correo del admin y festivos.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

`tests/test_seguridad.py` cubre los hallazgos del análisis de seguridad, incluida una prueba de reservas simultáneas
contra un servidor real.
