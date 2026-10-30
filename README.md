# Plazas de garaje

Aplicación web, pensada para el móvil, para repartir las plazas de un garaje compartido. Quien necesita aparcar abre la página, elige una plaza libre, escribe su nombre y ya está: no hay cuentas. Un administrador controla la ocupación desde un panel.

- Cada plaza es **reservable** o **fija** (de un titular, que el admin puede ceder un día concreto).
- Se reserva directamente para el **siguiente día laborable**: el viernes, para el lunes; los festivos también se saltan.
- Para **hoy** se envía una solicitud, que el admin aprueba o rechaza.
- Para cancelar, se escribe al admin.

| Documento | Para qué sirve |
|---|---|
| Este README | Arrancar el proyecto y entender cómo trabajar en él |
| [`specs.md`](specs.md) | Qué debe hacer la aplicación: requisitos, reglas de negocio y preguntas abiertas (§12) |
| [`DEPLOY.md`](DEPLOY.md) | Servidor, secretos, copias de seguridad, restauración y cómo desplegar en otro servidor |

**Stack:** Python 3.14 · FastAPI · Jinja2 · SQLite. HTML generado en el servidor, sin JavaScript de terceros ni paso de compilación.

## Puesta en marcha

Solo necesitas Python 3.14, la versión que usan CI y producción.

```bash
git clone https://github.com/angoru/parking.git
cd parking
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/uvicorn app.main:app --reload --port 8642
```

Abre <http://127.0.0.1:8642>. La primera vez se crea `parking.db` con las plazas de ejemplo 1 a 10 y los festivos de Madrid.

Para entrar al panel, ve a <http://127.0.0.1:8642/admin/login> con `admin` / `admin`. La app obliga a elegir una contraseña de al menos 10 caracteres antes de dejarte usarlo.

Para empezar de cero, para el servidor y borra `parking.db*`.

> **No publiques la app sin configurar `ADMIN_PASSWORD`.** Mientras nadie haya cambiado la contraseña de fábrica, el primero que llegue a `/admin/login` se queda con el panel. Por eso tampoco conviene usar `--host 0.0.0.0` (para probar desde el móvil) en una red que no sea de confianza. El despliegue se detiene si falta ese secreto.

## Cómo está organizado

```
app/
  main.py                  Rutas, cookies, cabeceras de seguridad. Sin SQL.
  models.py                Reglas de negocio y todas las consultas SQL.
  seguridad.py             Contraseña, sesiones, límites de intentos, mensajes de un solo uso.
  calendario.py            Festivos y días laborables. calendario.hoy() es la única fuente de «hoy».
  db.py                    Esquema, conexión y migraciones.
  restablecer_password.py  Recuperar el acceso si se olvida la contraseña.
  templates/  static/      Páginas Jinja2, CSS y un único app.js propio.
tests/
  test_app.py              Reglas de negocio y pantallas.
  test_seguridad.py        Seguridad y concurrencia, con un servidor real en algunos casos.
deploy/                    Compose, Caddy, script de copias y timer de systemd.
.github/                   Pipeline de CI/CD y Dependabot.
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
| `config` | Contraseña del admin (hash *scrypt*), su correo e indicadores internos |

### Convenciones que conviene respetar

- **`nominal` en el código es «fija» en la interfaz.** El código y la interfaz están en español.
- **Comprobar y escribir, siempre con bloqueo.** Toda función que compruebe algo y luego escriba empieza por `_bloquear_escritura(conn)`, porque hay peticiones simultáneas.
- **Nunca `date.today()`.** Usa `calendario.hoy()`, que va en hora de Madrid y que los tests pueden fijar.
- **Nada de JavaScript en línea.** Ni `<script>` ni `onclick`: la CSP lo bloquea y un test lo comprueba. El comportamiento va en `app.js`.
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
3. **Publicar:** subir a `main` no despliega nada; **lo que llega a producción son las releases** (ver la sección siguiente).

Las **preguntas abiertas** y los próximos pasos están en `specs.md` §12.

**Cada año:**
- En noviembre, el panel avisa si faltan los festivos del año siguiente; se añaden en **Ajustes**. Hay cargados hasta 2027; los locales de 2027 conviene comprobarlos cuando se publiquen en el BOCM, en diciembre de 2026.
- Revisa si conviene subir de versión menor de Python. La 3.14 tiene soporte hasta octubre de 2030.

### Versiones y releases

`VERSION` sigue `mayor.menor.parche` y aparece al pie de todas las páginas, así que ese pie dice qué hay en producción. La versión de `specs.md` es la del documento, no la de la app.

| Subo… | Cuando… |
|---|---|
| `parche` (1.1.**1**) | Corrijo fallos o publico una actualización de seguridad |
| `menor` (1.**2**.0) | Añado funciones |
| `mayor` (**2**.0.0) | El cambio no es compatible: por ejemplo, una versión anterior ya no funcionaría con la base de datos |

**Para publicar una versión**, con los cambios ya en `main` y los tests en verde:

```bash
echo 1.2.0 > VERSION
git commit -am "Versión 1.2.0" && git push origin main
gh release create v1.2.0 --generate-notes --title v1.2.0
```

Publicar la release **despliega en producción sin más aprobación**. Las notas generadas solo enumeran pull requests; si has subido directamente a `main`, escríbelas con `--notes`.

| Qué ocurre | Tests y auditoría | Imagen y despliegue |
|---|---|---|
| Push o PR a `main` | Sí | No |
| Release publicada | Sí | Sí, de esa release |
| Domingo a las 03:00 UTC | Sí | Sí, de la última release, reconstruida con los parches del momento |
| `gh workflow run deploy.yml -f tag=v1.1.0` | Sí | Sí, de la release indicada |
| Borrador o pre-release | No | No |

El pipeline se detiene sin desplegar si la release no se llama `vX.Y.Z` o si `VERSION` no coincide con ella. En ese caso, borra la release con `gh release delete v1.2.0 --cleanup-tag`, corrígelo y vuelve a crearla. Una release creada desde otro workflow con `GITHUB_TOKEN` no despliega, porque GitHub no lanza workflows con ese token.

**Si una versión sale mal:** si no arranca, el despliegue vuelve solo a la imagen anterior. Si arranca pero funciona mal, despliega la buena con `gh workflow run deploy.yml -f tag=v1.1.0` y márcala como última con `gh release edit v1.1.0 --latest`; si no, el domingo se volvería a desplegar la mala.

### Actualizaciones

| Qué | Cómo se fija | Cómo se actualiza |
|---|---|---|
| Python y Debian | `python:3.14-slim`, libre dentro de la 3.14 | **Solos**, en la reconstrucción semanal |
| Dependencias indirectas (Starlette, Pydantic…) | Sin fijar | **Solas**, en la reconstrucción semanal |
| Dependencias directas (`requirements.txt`) | Versión exacta | Dependabot abre un PR semanal: **hay que fusionarlo y publicar una release** |
| Acciones de GitHub | Commit exacto | Dependabot abre un PR semanal: **hay que fusionarlo**. El domingo se usa el pipeline de `main`, con los archivos de la última release |
| Python 3.15 y siguientes | — | **A mano**: cambia `Dockerfile` y `deploy.yml`, y prueba |

El job `audit` pasa `pip-audit` en cada ejecución. Si falla, no frena el despliegue, pero GitHub envía un correo. **Mira esos correos y los PR de Dependabot: es lo único de este proceso que necesita a una persona.** Fusionar un PR no llega a producción: las correcciones de seguridad en dependencias directas necesitan una release de parche. Los avisos de las ejecuciones programadas llegan a quien modificó por última vez el `cron`, así que si cambia el responsable, debe cambiarlo o comprobar sus notificaciones.

## Operación

| Quiero… | Cómo |
|---|---|
| Ver si producción funciona | `curl -fsS https://garaje.example.com/health/` |
| Ver los logs | `cd /opt/app && docker compose logs -f app` |
| Recuperar el acceso del admin | `cd /opt/app && docker compose exec app python -m app.restablecer_password` |
| Volver a una versión anterior | `gh workflow run deploy.yml -f tag=v1.1.0` (ver [Versiones y releases](#versiones-y-releases)) |
| Restaurar una copia de seguridad | [`DEPLOY.md`](DEPLOY.md#restaurar-una-copia) |
| Desplegar en otro servidor | [`DEPLOY.md`](DEPLOY.md#desplegar-en-otro-servidor) |

## Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `ADMIN_USER` | `admin` | Usuario del panel. |
| `ADMIN_PASSWORD_FILE` | — | Archivo con la contraseña inicial (secreto del contenedor). Tiene prioridad sobre `ADMIN_PASSWORD`. |
| `ADMIN_PASSWORD` | — | Contraseña inicial. Sin esta ni la anterior, es `admin` y hay que cambiarla al entrar. |
| `COOKIE_SECURE` | — | `1` para marcar las cookies como `Secure` aunque la app no vea HTTPS. |
| `RESERVAS_POR_HORA` | `5` | Reservas y solicitudes por hora desde un dispositivo. |
| `RESERVAS_POR_HORA_IP` | `60` | Reservas y solicitudes por hora desde una IP. Es más alto porque en una oficina todos comparten IP. |
| `PARKING_DB` | `parking.db` | Ruta del archivo SQLite. |
| `PARKING_TOTAL` | `10` | Solo al crear la base de datos: plazas de ejemplo 1..N. En producción, `0`. |

La contraseña guardada desde el panel tiene prioridad sobre las dos de arriba. Por eso, **cambiar el secreto `ADMIN_PASSWORD` no cambia la contraseña** si ya se ha cambiado desde la app. Para volver al secreto, usa `restablecer_password`.

## Seguridad

La URL es pública y quien reserva no se identifica, así que lo que hay que proteger es el panel del admin, los nombres guardados y la disponibilidad del servicio.

**Qué hay implementado:**

- **Contraseña:** *scrypt*, mínimo 10 caracteres, 5 intentos fallidos por IP cada 15 minutos.
- **Sesiones:** token aleatorio en cookie `HttpOnly`, `SameSite=Lax` y `Secure`. En la base de datos solo está su hash, así que «Salir» invalida la sesión de verdad. Cambiar la contraseña cierra las demás.
- **CSRF:** `SameSite=Lax`, y además se rechaza con 403 cualquier POST cuyo `Origin` no coincida con el `Host`. En `example.com` hace falta lo segundo: los demás proyectos del servidor cuentan como el mismo sitio, y `SameSite` no los frena.
- **XSS:** autoescape de Jinja2 y CSP sin scripts en línea.
- **SQL:** siempre con parámetros. Los avisos de `bandit` sobre `models.py` (B608) son falsos positivos: las partes interpoladas son constantes del código.
- **Cabeceras:** CSP, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` y `no-store` en el panel.
- **Contenedor:** usuario sin privilegios, sistema de archivos de solo lectura salvo `/data`, sin *capabilities* y solo accesible desde Caddy.
- **Copias:** cifradas con restic. **CI:** acciones fijadas por commit, porque reciben la clave SSH del servidor.

**Si cambias de proxy:** tiene que conservar la cabecera `Host` (Caddy lo hace) y sobrescribir `X-Forwarded-For`. `--forwarded-allow-ips "*"` en el `Dockerfile` solo es seguro porque el puerto se publica en `127.0.0.1` y Caddy es lo único que llega a él. Si cambia cualquiera de las dos cosas, se podría falsear la IP y saltarse los límites.

**Riesgos conocidos y aceptados por ahora:**

| Riesgo | Situación | Seguimiento |
|---|---|---|
| Cualquiera con la URL puede reservar con cualquier nombre | Es consecuencia de no tener cuentas. El límite por IP frena pero no impide llenar el garaje, y la URL aparece en los registros públicos de certificados. El admin puede liberar las plazas. | P-13 |
| El despliegue entra como `root` en un servidor compartido | Si alguien se hace con la cuenta de GitHub o con la clave, controla también los demás proyectos del servidor. | P-14 |
| Dependencias indirectas y base sin fijar | Es a propósito, para recibir los parches sin intervención. A cambio, una versión maliciosa de una dependencia llegaría a producción sin revisión en el siguiente domingo, y dos construcciones pueden ser distintas. | P-15 |
| Los nombres se guardan sin límite de tiempo | Son datos personales: siguen en `reservas` y `avisos` indefinidamente, y en las copias hasta 12 meses. | P-16 |
| Un solo admin, sin segundo factor | La sesión dura 30 días. | P-11 |
| Límites en memoria | Se reinician al reiniciar el contenedor. | Aceptado |
| `parking_flash` sin `Secure` | Solo lleva mensajes durante 60 segundos, y HTTPS ya es obligatorio. | Aceptado |
| CSP con `style-src 'unsafe-inline'` | Hace falta para el ancho de la barra de ocupación. Los scripts siguen bloqueados. | Aceptado |

Para revisar las dependencias a mano: `pip install pip-audit && pip-audit -r requirements.txt`.

## Licencia

El código propio de este proyecto se distribuye bajo la licencia [0BSD](LICENSE), una licencia libre muy permisiva que permite usar, modificar y distribuir ese código sin exigir atribución. Las dependencias conservan sus respectivas licencias y sus condiciones de redistribución.
