# Plazas de garaje

Aplicación web, pensada para el móvil, para repartir las plazas de un garaje compartido. Quien necesita aparcar abre la página, elige una plaza libre, escribe su nombre y ya está: no hay cuentas. Un administrador controla la ocupación desde un panel.

- Cada plaza es **reservable** o **fija** (de un titular, que el admin puede ceder un día concreto).
- Se reserva directamente para el **siguiente día laborable**: el viernes, para el lunes; los festivos también se saltan. Las reservas se abren a la hora que fija el admin (por defecto, las 08:00).
- Para **hoy** se envía una solicitud, que el admin aprueba o rechaza.
- Para cancelar, se escribe al admin.

| Documento | Para qué sirve |
|---|---|
| Este README | Arrancar el proyecto y entender cómo trabajar en él |
| [`specs.md`](specs.md) | Qué debe hacer la aplicación: requisitos, reglas de negocio y preguntas abiertas (§12) |

**Stack:** Docker · Python 3.14 · FastAPI · Jinja2 · SQLite. HTML generado en el servidor, sin JavaScript de terceros ni paso de compilación.

## Puesta en marcha

La app se ejecuta en Docker. **Solo necesitas Docker con Compose:**

```bash
git clone https://github.com/angoru/parking.git
cd parking
docker compose up --build
```

Abre <http://127.0.0.1:8642>. La primera vez se crean las plazas de ejemplo 1 a 10 y los festivos de Madrid.

Para entrar al panel, ve a <http://127.0.0.1:8642/admin/login> con `admin` / `admin`. La app obliga a elegir una contraseña de al menos 10 caracteres antes de dejarte usarlo.

| Quiero… | Cómo |
|---|---|
| Arrancar en segundo plano | `docker compose up -d --build` |
| Ver los logs | `docker compose logs -f app` |
| Parar, conservando los datos | `docker compose down` |
| Empezar de cero, **borrando los datos** | `docker compose down -v` |
| Recuperar el acceso del admin | `docker compose exec app python -m app.restablecer_password` |
| Aplicar parches de Python y Debian | `docker compose build --pull && docker compose up -d` |

Los datos están en el volumen `datos`, en un único archivo SQLite (`/data/parking.db`).

### Para desarrollar

Docker basta para ejecutar la app. Para trabajar en el código, con recarga automática y tests, necesitas además Python 3.14:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/uvicorn app.main:app --reload --port 8642
```

Así, los datos van a `parking.db`, en la carpeta del proyecto; para empezar de cero, borra `parking.db*`.

Para pasar los tests sin instalar Python:

```bash
docker run --rm -v "$PWD":/src:ro,Z python:3.14-slim sh -c 'cp -r /src /tmp/p && cd /tmp/p && pip install -q -r requirements-dev.txt && python -m pytest -q'
```

## Desplegar

Este repositorio **no incluye despliegue ni credenciales**: cada instalación decide dónde y cómo se ejecuta. Vale cualquier sitio donde se pueda correr la imagen del `Dockerfile`, y `compose.yaml` es un buen punto de partida. Hay que respetar lo siguiente:

- **Contraseña:** define `ADMIN_PASSWORD` o `ADMIN_PASSWORD_FILE`, o cambia la de fábrica nada más arrancar. Mientras siga siendo la de fábrica, **el primero que llegue a `/admin/login` se queda con el panel**.
- **Plazas:** usa `PARKING_TOTAL=0` y da de alta las reales en **Ajustes**. Configura también el correo de contacto.
- **Una sola réplica:** los límites de intentos están en memoria y SQLite es un único archivo.
- **Disco persistente en `/data`,** escribible por el UID 10001. No sirve un sistema de archivos de red: SQLite en modo WAL necesita memoria compartida en la misma máquina.
- **Proxy con HTTPS** que conserve la cabecera `Host` (si no, todo POST recibe un 403) y sobrescriba `X-Forwarded-For`. Con [Caddy](https://caddyserver.com/) basta con esto:
  ```
  garaje.tudominio.es {
      reverse_proxy 127.0.0.1:8642
  }
  ```
- **Solo el proxy puede llegar al puerto de la app:** la imagen confía en sus cabeceras con `--forwarded-allow-ips "*"`. Si el puerto queda expuesto, se puede falsear la IP y saltarse los límites. Por eso `compose.yaml` lo publica en `127.0.0.1`.

**Secretos:** nunca en el repositorio. `.env` está en `.gitignore`, y Compose lo lee solo.

### Copias de seguridad

Nunca copies el archivo con la app en marcha: usa la API de backup de SQLite. Las copias contienen nombres de personas, así que guárdalas cifradas.

```bash
# Hacer una copia
docker compose exec app python -c "import sqlite3; sqlite3.connect('/data/parking.db').backup(sqlite3.connect('/data/copia.db'))"
docker compose cp app:/data/copia.db ./copia.db

# Restaurarla: copia.db tiene que ser legible por todos (chmod 644)
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/copia.db":/copia.db:ro,Z app sh -c 'cp /copia.db /data/parking.db && rm -f /data/parking.db-wal /data/parking.db-shm'
docker compose start app
```

## Cómo está organizado

```
app/
  main.py                  Rutas, cookies, cabeceras de seguridad. Sin SQL.
  models.py                Reglas de negocio y todas las consultas SQL.
  seguridad.py             Contraseña, sesiones, límites de intentos, mensajes de un solo uso.
  calendario.py            Festivos y días laborables. calendario.hoy() y hora_actual() son la única fuente de la fecha y la hora.
  db.py                    Esquema, conexión y migraciones.
  restablecer_password.py  Recuperar el acceso si se olvida la contraseña.
  templates/  static/      Páginas Jinja2, CSS y un único app.js propio.
tests/
  test_app.py              Reglas de negocio y pantallas.
  test_seguridad.py        Seguridad y concurrencia, con un servidor real en algunos casos.
  test_frontend.py         Calidad y estructura del HTML y el CSS.
Dockerfile  compose.yaml   Imagen de la app y arranque con un solo comando.
.github/                   CI sin secretos (tests, auditoría, imagen) y Dependabot.
```

**Una petición:** la ruta de `main.py` recibe una conexión con `conn=Conn`, llama a `models.py` y responde con una plantilla o una redirección. Al terminar la ruta se confirma la transacción, antes de enviar la respuesta. Si se lanza una excepción, se deshace.

**Datos (SQLite, tablas en `db.py`):**

| Tabla | Contenido |
|---|---|
| `plazas` | Número real, tipo (`reservable` o `nominal`) y titular |
| `reservas` | Plaza, fecha y nombre. Solo una por plaza y día (`UNIQUE`) |
| `solicitudes` | Peticiones para hoy: `pendiente`, `aprobada` o `rechazada` |
| `liberaciones` | Días en que una plaza fija queda abierta a todos |
| `festivos` | Días no laborables, además de sábados y domingos |
| `avisos` | Historial que ve el admin |
| `sesiones` | Sesiones del admin (solo el hash del token) |
| `config` | Contraseña del admin (hash *scrypt*), su correo, la hora de apertura e indicadores internos |

### Convenciones que conviene respetar

- **`nominal` en el código es «fija» en la interfaz.** El código y la interfaz están en español.
- **Comprobar y escribir, siempre con bloqueo.** Toda función que compruebe algo y luego escriba empieza por `_bloquear_escritura(conn)`, porque hay peticiones simultáneas.
- **Nunca `date.today()` ni `datetime.now()`.** Usa `calendario.hoy()` y `calendario.hora_actual()`, que van en hora de Madrid y que los tests pueden fijar.
- **Nada de JavaScript ni CSS en línea.** Ni `<script>`, `onclick` o `style=`: la CSP lo bloquea y un test lo comprueba. El comportamiento va en `app.js` y los estilos, en `style.css`.
- **CSS:** clases en español y en kebab-case, con el patrón `componente` y `componente-parte` o `componente-variante`. Colores, tamaños de letra y radios salen de las variables de `:root`. `tests/test_frontend.py` comprueba todo esto, además de que no sobren clases ni variables y de que cada página tenga un `h1` y sus campos, nombre accesible.
- **Los mensajes no van en la URL.** Usa `redirect(path, msg=...)`, que los manda en una cookie de un solo uso.
- **Base de datos:** una columna nueva se añade a `SCHEMA` y a `COLUMNAS_NUEVAS` en `db.py`, y se migra sola al arrancar. Para cambios más complejos no hay herramienta de migraciones.
- **Toda regla nueva lleva su test.** Las pruebas fijan la fecha con `monkeypatch`, así que no dependen del día en que se ejecutan.

### Decisiones de producto ya tomadas

No las reabras sin hablarlo con quien lleva el proyecto:

- **Sin cuentas ni inicio de sesión para quien reserva**, y sin más datos que el nombre, en un único campo. El único rol especial es el admin.
- **El titular de una plaza fija puede reservar además otra plaza.** La única regla por nombre es una reserva o solicitud pendiente por día.
- **Las cancelaciones las hace el admin**, que recibe la petición por correo.

## Cómo trabajar en el proyecto

1. **Requisitos:** los nuevos llegan a la sección `# Inbox`, al final de `specs.md`. Se implementan, se pasan al cuerpo de la especificación con una versión nueva en su historial (§13) y el Inbox se queda vacío con una nota.
2. **Cambios:** en una rama, con tests. `specs.md` se actualiza en el mismo cambio.
3. **Publicar:** subir a `main` solo pasa los tests. Las versiones se marcan con una release (ver la sección siguiente).

Las **preguntas abiertas** y los próximos pasos están en `specs.md` §12.

**Cada año:**
- En noviembre, el panel avisa si faltan los festivos del año siguiente; se añaden en **Ajustes**. Hay cargados hasta 2027; los locales de 2027 conviene comprobarlos cuando se publiquen en el BOCM, en diciembre de 2026.
- Revisa si conviene subir de versión menor de Python. La 3.14 tiene soporte hasta octubre de 2030.

### Versiones y releases

`VERSION` sigue `mayor.menor.parche` y aparece al pie de todas las páginas, así que ese pie dice qué versión está en marcha. La versión de `specs.md` es la del documento, no la de la app.

| Subo… | Cuando… |
|---|---|
| `parche` (1.1.**1**) | Corrijo fallos o publico una actualización de seguridad |
| `menor` (1.**2**.0) | Añado funciones |
| `mayor` (**2**.0.0) | El cambio no es compatible: por ejemplo, una versión anterior ya no funcionaría con la base de datos |

Cambia `VERSION` en un PR y, una vez fusionado, crea la release con el mismo número: `gh release create v1.2.0 --generate-notes --title v1.2.0`. La release solo marca la versión: **no despliega nada**. Subir `VERSION` es imprescindible si cambian el CSS o el JS, porque los navegadores los guardan por versión.

### Actualizaciones

| Qué | Cómo se fija | Cómo se actualiza |
|---|---|---|
| Python y Debian | `python:3.14-slim`, libre dentro de la 3.14 | Al reconstruir la imagen con `--pull` |
| Dependencias indirectas (Starlette, Pydantic…) | Sin fijar | Al reconstruir la imagen sin caché |
| Dependencias directas (`requirements.txt`) | Versión exacta | Dependabot abre un PR semanal: **hay que fusionarlo** |
| Acciones de GitHub | Commit exacto | Dependabot abre un PR semanal: **hay que fusionarlo** |
| Python 3.15 y siguientes | — | **A mano**: cambia `Dockerfile` y `ci.yml`, y prueba |

CI pasa `pip-audit` también cada domingo, aunque nadie toque el código. Si falla, GitHub envía un correo a quien modificó por última vez el `cron`. **Nada se actualiza solo en una instalación ya en marcha:** hay que reconstruir la imagen.

## Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `ADMIN_USER` | `admin` | Usuario del panel. |
| `ADMIN_PASSWORD_FILE` | — | Archivo con la contraseña inicial (secreto del contenedor). Tiene prioridad sobre `ADMIN_PASSWORD`. |
| `ADMIN_PASSWORD` | — | Contraseña inicial. Sin esta ni la anterior, es `admin` y hay que cambiarla al entrar. |
| `COOKIE_SECURE` | — | `1` para marcar las cookies como `Secure` aunque la app no vea HTTPS. |
| `RESERVAS_POR_HORA` | `5` | Reservas y solicitudes por hora desde un dispositivo. |
| `RESERVAS_POR_HORA_IP` | `60` | Reservas y solicitudes por hora desde una IP. Es más alto porque en una oficina todos comparten IP. |
| `PARKING_DB` | `/data/parking.db` en la imagen; `parking.db` sin Docker | Ruta del archivo SQLite. |
| `PARKING_TOTAL` | `10` | Solo al crear la base de datos: plazas de ejemplo 1..N. En producción, `0`. |
| `PUERTO` | `8642` | Solo en `compose.yaml`: puerto local donde se publica la app. |

La contraseña guardada desde el panel tiene prioridad sobre las dos de arriba. Por eso, **cambiar `ADMIN_PASSWORD` no cambia la contraseña** si ya se ha cambiado desde la app. Para volver a ella, usa `restablecer_password`.

## Seguridad

La URL es pública y quien reserva no se identifica, así que lo que hay que proteger es el panel del admin, los nombres guardados y la disponibilidad del servicio.

**Qué hay implementado:**

- **Contraseña:** *scrypt*, mínimo 10 caracteres, 5 intentos fallidos por IP cada 15 minutos.
- **Sesiones:** token aleatorio en cookie `HttpOnly`, `SameSite=Lax` y `Secure`. En la base de datos solo está su hash, así que «Salir» invalida la sesión de verdad. Cambiar la contraseña cierra las demás.
- **CSRF:** `SameSite=Lax`, y además se rechaza con 403 cualquier POST cuyo `Origin` no coincida con el `Host`. Lo segundo hace falta porque `SameSite` no frena a otras webs del mismo dominio.
- **XSS:** autoescape de Jinja2 y CSP sin scripts ni estilos en línea.
- **SQL:** siempre con parámetros. Los avisos de `bandit` sobre `models.py` (B608) son falsos positivos: las partes interpoladas son constantes del código.
- **Cabeceras:** CSP, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` y `no-store` en el panel.
- **Contenedor:** usuario sin privilegios, sistema de archivos de solo lectura salvo `/data`, sin *capabilities* y publicado solo en `127.0.0.1`.
- **Repositorio:** sin secretos ni credenciales, y CI sin acceso a ningún servidor. Las acciones de CI van fijadas por commit.

**Riesgos conocidos y aceptados por ahora:**

| Riesgo | Situación | Seguimiento |
|---|---|---|
| Cualquiera con la URL puede reservar con cualquier nombre | Es consecuencia de no tener cuentas. El límite por IP frena pero no impide llenar el garaje, y la URL aparece en los registros públicos de certificados. El admin puede liberar las plazas. | P-13 |
| Dependencias indirectas y base sin fijar | Es a propósito, para recibir los parches al reconstruir. A cambio, dos construcciones pueden ser distintas y una versión maliciosa entraría sin revisión. | P-15 |
| Los nombres se guardan sin límite de tiempo | Son datos personales: siguen en `reservas` y `avisos` indefinidamente, y en las copias que se hagan. | P-16 |
| Un solo admin, sin segundo factor | La sesión dura 30 días. | P-11 |
| Límites en memoria | Se reinician al reiniciar el contenedor. | Aceptado |
| `parking_flash` sin `Secure` | Solo lleva mensajes durante 60 segundos. | Aceptado |

Para revisar las dependencias a mano: `pip install pip-audit && pip-audit -r requirements.txt`.

## Licencia

El código propio de este proyecto se distribuye bajo la licencia [0BSD](LICENSE), una licencia libre muy permisiva que permite usar, modificar y distribuir ese código sin exigir atribución. Las dependencias conservan sus respectivas licencias y sus condiciones de redistribución.
