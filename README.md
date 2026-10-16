# Plazas de garaje

Aplicación web (pensada para el móvil) para reservar plazas de garaje.

- Hay un número total de plazas configurable.
- Cada plaza es **nominal** (asignada fija a un titular, nunca se reserva) o **reservable**.
- La página principal muestra **solo las plazas libres**; las reservadas y las nominales no aparecen.
- Se reserva directamente para el **siguiente día laborable** (el viernes, para el lunes; los festivos de Madrid también se saltan). Para **hoy** se envía una solicitud que el admin aprueba o rechaza.
- Tras reservar se muestra "Has reservado la plaza N"; para cancelar, se escribe al admin.
- No hay cuentas: para reservar basta con escribir el nombre.
- El admin ve todas las plazas, puede liberar u ocupar cualquiera y recibe un aviso de cada reserva.

La especificación funcional completa está en [`specs.md`](specs.md).

## Puesta en marcha

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ADMIN_PASSWORD=tu-clave .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8642
```

Desde el móvil (en la misma red): `http://<ip-del-ordenador>:8642`.

## Variables de entorno

| Variable         | Por defecto  | Uso                                                        |
|------------------|--------------|------------------------------------------------------------|
| `ADMIN_USER`     | `admin`      | Usuario del acceso admin (`/admin/login`).                 |
| `ADMIN_PASSWORD` | `admin`      | Contraseña del acceso admin. **Cámbiala antes de publicar la app.** |
| `PARKING_DB`     | `parking.db` | Ruta del archivo SQLite.                                   |
| `PARKING_TOTAL`  | `10`         | Solo la primera vez: crea las plazas 1..N. Después se numeran desde Admin → Ajustes. |

## Páginas

- `/` — plazas libres, pestañas Hoy (solicitar) y siguiente día laborable (reservar).
- `/reservar/{id}` — formulario con el nombre.
- `/confirmacion` — "Has reservado la plaza N" y cómo cancelar.
- `/admin/login` — acceso del admin.
- `/admin` — tablero del día con todas las plazas; liberar y ocupar.
- `/admin/solicitudes` — aprobar o rechazar las solicitudes para hoy.
- `/admin/avisos` — avisos de reservas, solicitudes y cancelaciones.
- `/admin/ajustes` — alta y numeración de plazas (sueltas o por rangos), plazas fijas, correo del admin y festivos.

## Tests

```bash
.venv/bin/pytest
```
