# Especificación funcional — Gestión de plazas de garaje

| | |
|---|---|
| **Versión** | 1.5 |
| **Estado** | ✅ Implementado · quedan preguntas abiertas (§12) |
| **Última revisión** | 16/10/2026 |
| **Código** | `app/` · tests en `tests/test_app.py` (39 casos, todos en verde) |

**Leyenda de estado:** ✅ Implementado · 🟡 Parcial · ⬜ Pendiente

---

## 1. Objetivo

Ofrecer una aplicación web sencilla, pensada sobre todo para el móvil, para repartir las plazas de un garaje compartido. Quien necesita aparcar ve enseguida qué plazas quedan libres y reserva una en segundos, sin crearse una cuenta. El administrador controla toda la ocupación y recibe un aviso de cada reserva.

## 2. Alcance

**Incluido**
- Conjunto de plazas definido por el administrador, con **la numeración real del garaje** (no tiene por qué ser consecutiva).
- Plazas **fijas** (asignadas a un titular), que el admin puede liberar para un día concreto, y plazas **reservables**.
- Reservas por día completo, indicando solo el nombre.
- Reserva directa para el **siguiente día laborable**; para el mismo día, solicitud que el admin debe aprobar.
- Calendario laboral de la ciudad de Madrid (2026 y 2027), que el admin puede ampliar.
- Panel de administración con acceso por usuario y contraseña: tablero de ocupación, solicitudes, avisos y ajustes.

**Fuera de alcance (por ahora)**
- Cuentas de usuario, registro o inicio de sesión para quienes reservan.
- Consulta o cancelación de reservas por parte del usuario: para cancelar, escribe al admin.
- Reservas por horas o por franjas.
- Avisos fuera de la aplicación (email, notificaciones del móvil, mensajería). Ver §12.
- Pagos, control de acceso físico y lectura de matrículas.

## 3. Glosario

| Término | Definición |
|---|---|
| **Plaza reservable** | Plaza que cualquiera puede reservar si está libre ese día. |
| **Plaza fija** | Plaza asignada de forma permanente a un titular (en el código, `nominal`). Está cerrada para los demás, salvo los días concretos en que el admin la libera. |
| **Día laborable** | Día de lunes a viernes que no es festivo según el calendario de la aplicación (§7). |
| **Siguiente día laborable** | Primer día laborable después de hoy. Por ejemplo, el lunes cuando hoy es viernes, o el día posterior a un festivo cuando hoy es su víspera. |
| **Liberación** | Acción del admin que abre una plaza fija a todos durante **un único día**. Al día siguiente vuelve a estar cerrada sin que nadie tenga que hacer nada. |
| **Reserva** | Ocupación de una plaza durante un día completo por una persona, identificada por su nombre. |
| **Solicitud** | Petición de plaza para el mismo día. No ocupa la plaza hasta que el admin la aprueba. |
| **Aviso** | Notificación al admin cada vez que un usuario reserva o solicita. |

## 4. Roles

| Rol | Identificación | Permisos |
|---|---|---|
| **Usuario** | Solo su nombre. No tiene cuenta ni contraseña. | Ver las plazas libres, reservar para el siguiente día laborable y solicitar plaza para hoy. |
| **Administrador** | Pantalla de acceso con usuario y contraseña (por defecto **admin / admin**). | Ver todas las plazas, liberar u ocupar cualquiera, aprobar o rechazar solicitudes, consultar avisos y configurar plazas, festivos y su correo de contacto. |

## 5. Requisitos funcionales

### 5.1 Usuario

| ID | Requisito | Estado |
|---|---|---|
| RF-01 | El usuario solo ve las plazas **libres**. Las reservadas y las fijas no se muestran. | ✅ |
| RF-02 | El usuario puede **reservar una plaza para el siguiente día laborable**. La reserva es inmediata. Los viernes se reserva para el lunes, y los festivos también se saltan. | ✅ |
| RF-03 | Si pide plaza **para el mismo día**, no se reserva: se **envía una solicitud al admin**. | ✅ |
| RF-04 | Para reservar o solicitar solo hay que **escribir el nombre, en un único campo**. | ✅ |
| RF-05 | Al terminar se muestra la confirmación **"Has reservado la plaza N"** (o "Has solicitado…") con la fecha, y el aviso **"Si quieres cancelar, envía un correo al admin"**, que incluye un enlace al correo si está configurado. | ✅ |
| RF-06 | La aplicación recuerda el nombre en el navegador para no tener que escribirlo cada vez. | ✅ |
| RF-07 | La pestaña del día siguiente indica el día real: "Mañana" o, si no es el día siguiente, el día de la semana ("Lunes", "Martes"…). | ✅ |

### 5.2 Administrador

| ID | Requisito | Estado |
|---|---|---|
| RF-10 | El admin puede **ver todas las plazas** y su estado en cualquier día. El tablero marca los días no laborables y los días pasados, que solo se pueden consultar. | ✅ |
| RF-10b | **Tablero de ocupación** con: indicadores del día (libres, reservadas, fijas en uso y solicitudes pendientes), barra de **ocupación** (ocupadas sobre el total, en %), **filtros** (todas, libres, ocupadas, fijas) y una **rejilla de plazas**. Cada plaza muestra su número, su estado, quién la ocupa y la acción que corresponde. En el móvil se ve en dos columnas y en el ordenador en varias. | ✅ |
| RF-11 | El admin puede **liberar cualquier plaza**: anular su reserva o, si es fija, dejarla libre ese día. Así se gestionan también las cancelaciones que llegan por correo. | ✅ |
| RF-11b | El admin puede **marcar plazas como fijas** y **liberar una plaza fija para un día concreto, y solo ese día**. Puede ser **el mismo día** o cualquier día futuro. **Al día siguiente vuelve a estar cerrada.** En el tablero el botón aparece como «Liberar este día». | ✅ |
| RF-12 | El admin puede **ocupar cualquier plaza** a nombre de cualquier persona, o devolver al titular una fija liberada. | ✅ |
| RF-13 | El admin puede **aprobar o rechazar** las solicitudes para el mismo día. | ✅ |
| RF-14 | **Cada reserva envía un aviso al admin.** Las solicitudes también generan aviso. | ✅ Dentro de la app (ver P-01) |
| RF-15 | El menú del admin muestra cuántas solicitudes están pendientes y cuántos avisos no se han leído. | ✅ |
| RF-16 | El admin **inicia sesión** con usuario y contraseña (**admin / admin**) y puede cerrarla. La sesión dura 30 días. | ✅ |
| RF-17 | El admin **da de alta plazas con su número real**, sueltas o por rangos (por ejemplo, `12, 15, 20-25`). La numeración no tiene que ser consecutiva. | ✅ |
| RF-17b | Cada plaza se edita **en una sola línea**: número, titular, guardar (✓) y eliminar (✕). **Si tiene titular, es fija; si el titular está vacío, es reservable.** | ✅ |
| RF-18 | El admin puede **añadir y eliminar festivos**. | ✅ |
| RF-19 | El admin puede configurar el **correo de contacto** que ve el usuario tras reservar. | ✅ |

## 6. Reglas de negocio

| ID | Regla |
|---|---|
| RN-01 | Una plaza admite **una sola reserva por día**. Si dos personas la reservan a la vez, la segunda recibe "plaza ya ocupada". |
| RN-02 | Cada nombre puede tener como máximo **una reserva o una solicitud pendiente por día**. Al comparar nombres no se distinguen mayúsculas de minúsculas. |
| RN-03 | La reserva directa siempre es para el **siguiente día laborable**. El usuario no puede elegir otra fecha. |
| RN-04 | Solo se pueden solicitar plazas para hoy si **hoy es laborable**. Los fines de semana y festivos no aparece la pestaña "Hoy". |
| RN-05 | Una solicitud **no bloquea** la plaza, así que puede haber varias para la misma. Si al aprobar una la plaza ya está ocupada, esa solicitud se **rechaza automáticamente** indicando el motivo. |
| RN-06 | Una liberación afecta a **una sola fecha**. Ese día, la plaza fija funciona como reservable; antes y después sigue cerrada. Para cederla varios días hay que liberar cada día por separado. Si el admin la ocupa sin indicar nombre, o con el nombre del titular, vuelve a su titular. |
| RN-06b | Una plaza fija se puede liberar **el mismo día**. Como es para hoy, quien la quiera la **solicita** y el admin aprueba (RN-04, RN-05). Si se libera para el siguiente día laborable o uno posterior, se puede reservar directamente cuando llegue su turno. |
| RN-06c | No se pueden liberar ni ocupar plazas en **días pasados**. En el tablero, los días pasados se muestran sin botones. |
| RN-07 | El número de plaza es **único**; no puede haber dos plazas con el mismo. Al renumerar una plaza, sus reservas, liberaciones y solicitudes se mantienen, porque están ligadas a la plaza y no a su número. |
| RN-07b | No se puede eliminar una plaza con reservas futuras; antes hay que liberarlas. |
| RN-08 | Una plaza con reservas futuras no se puede convertir en fija. |
| RN-09 | Las acciones del admin no generan avisos. Solo avisan las de los usuarios. |
| RN-10 | Las cancelaciones las hace el admin (con "Liberar") cuando el usuario se lo pide por correo. |

## 7. Calendario laboral

Se consideran no laborables los **sábados, los domingos y los festivos** de la tabla de festivos. La aplicación viene cargada con los festivos de la **ciudad de Madrid** (nacionales, autonómicos y locales). Para años posteriores, o para otros municipios, el admin los gestiona en **Ajustes → Festivos**.

| 2026 | 2027 |
|---|---|
| 1 ene · Año Nuevo | 1 ene · Año Nuevo |
| 6 ene · Epifanía del Señor | 6 ene · Epifanía del Señor |
| 2 abr · Jueves Santo | 19 mar · San José |
| 3 abr · Viernes Santo | 25 mar · Jueves Santo |
| 1 may · Fiesta del Trabajo | 26 mar · Viernes Santo |
| 2 may · Fiesta de la Comunidad de Madrid | 1 may · Fiesta del Trabajo |
| 15 may · **San Isidro** (local) | 15 may · **San Isidro** (local) |
| 15 ago · Asunción de la Virgen | 16 ago · Asunción (trasladado) |
| 12 oct · Fiesta Nacional de España | 12 oct · Fiesta Nacional de España |
| 2 nov · Todos los Santos (trasladado) | 1 nov · Todos los Santos |
| 9 nov · **La Almudena** (local) | 9 nov · **La Almudena** (local) |
| 7 dic · Constitución (trasladado) | 6 dic · Día de la Constitución |
| 8 dic · Inmaculada Concepción | 8 dic · Inmaculada Concepción |
| 25 dic · Natividad del Señor | 25 dic · Natividad del Señor |

**Fuentes:**
- Decreto 75/2025 (BOCM, 25/09/2025) y Decreto 82/2026 (BOCM n.º 234, 01/10/2026) de la Comunidad de Madrid, para los festivos regionales.
- Acuerdos del Pleno del Ayuntamiento de Madrid de 30/09/2025 y 29/09/2026, para San Isidro y La Almudena. Los festivos locales de 2027 se publicarán en el BOCM en diciembre de 2026; conviene comprobarlos entonces.

**Ejemplos:**

| Hoy | Se reserva para |
|---|---|
| Viernes 16/10/2026 | Lunes 19/10 |
| Viernes 09/10/2026 | Martes 13/10 (el 12 es festivo) |
| Viernes 04/12/2026 | Miércoles 09/12 (el 7 y el 8 son festivos) |
| Miércoles 24/03/2027 | Lunes 29/03 (Semana Santa) |

## 8. Estados de una plaza (por día)

| Estado | Significado | ¿La ve el usuario? | Acción del admin |
|---|---|---|---|
| 🟩 **Libre** | Plaza reservable sin reserva | Sí | Ocupar |
| 🟩 **Fija liberada** | Fija cedida ese día, todavía sin reservar | Sí | Ocupar o devolver al titular |
| ⬛ **Reservada** | Tiene una reserva (puede ser una fija cedida a otra persona) | No | Liberar |
| 🟦 **Fija** | Ocupada por su titular | No | Liberar |

## 9. Flujos principales

**Reservar para el siguiente día laborable**
1. El usuario abre la app y ve las plazas libres del siguiente día laborable, en la pestaña "Mañana" o con el nombre del día de la semana.
2. Toca una plaza libre, escribe su nombre y confirma.
3. Ve "Has reservado la plaza N" junto con cómo cancelar. El admin recibe un aviso.

**Pedir plaza para hoy**
1. Si hoy es laborable, el usuario va a la pestaña **Hoy**, elige una plaza y envía la solicitud.
2. Ve "Has solicitado la plaza N". El admin recibe un aviso y la solicitud aparece en su lista de pendientes.
3. El admin la aprueba o la rechaza.

**Cancelar una reserva**
1. El usuario escribe al admin, con el enlace de correo de la pantalla de confirmación, que ya incluye el asunto.
2. El admin abre el tablero de ese día y pulsa **Liberar** en la plaza.

**Ceder una plaza fija un día concreto**
1. El titular avisa de que no la usará tal día (puede ser hoy).
2. El admin va a ese día en el tablero y pulsa **Liberar este día** en la plaza fija.
3. Ese día la plaza aparece como libre:
   - si el día es hoy, se puede **solicitar**;
   - si es el siguiente día laborable, se puede **reservar**.
4. Al día siguiente la plaza vuelve a estar cerrada de forma automática.
5. Mientras nadie la reserve, el admin puede devolverla al titular con **Ocupar**.

## 10. Pantallas

| Pantalla | Ruta | Rol |
|---|---|---|
| Plazas libres (pestañas Hoy / siguiente laborable) | `/` | Usuario |
| Reservar o solicitar | `/reservar/{plaza}` | Usuario |
| Confirmación | `/confirmacion` | Usuario |
| Acceso admin | `/admin/login` | Admin |
| Tablero de ocupación | `/admin` | Admin |
| Solicitudes pendientes | `/admin/solicitudes` | Admin |
| Avisos | `/admin/avisos` | Admin |
| Ajustes: alta y numeración de plazas, correo y festivos | `/admin/ajustes` | Admin |

## 11. Requisitos no funcionales

| ID | Requisito | Estado |
|---|---|---|
| RNF-01 | Diseño **pensado primero para el móvil**: botones grandes y formularios que no fuerzan el zoom. Comprobado a 390 px de ancho. Modo oscuro automático. | ✅ |
| RNF-02 | Sin JavaScript de terceros en el navegador. Páginas ligeras generadas en el servidor. | ✅ |
| RNF-03 | Datos guardados en **SQLite**, en un único archivo (`PARKING_DB`). | ✅ |
| RNF-04 | Sesión de admin con una cookie firmada (HMAC) a la que no puede acceder JavaScript (`HttpOnly`). Las credenciales se pueden cambiar con `ADMIN_USER` y `ADMIN_PASSWORD`. | ✅ |
| RNF-05 | Tests automáticos que cubren todas las reglas anteriores, con la fecha de "hoy" fijada para probar fines de semana y festivos. | ✅ |
| RNF-06 | Servir la app por **HTTPS** en producción. | ⬜ |

**Stack:** Python 3 · FastAPI · Jinja2 · SQLite. Las instrucciones de arranque están en el [README](README.md).

## 12. Preguntas abiertas y próximos pasos

| ID | Tema | Situación actual | Propuesta |
|---|---|---|---|
| P-01 | **Canal de los avisos** | El aviso solo se ve al entrar en el panel de admin. | Enviarlo además por email, Telegram o notificación del móvil, para que llegue sin abrir la app. |
| P-02 | **Resultado de la solicitud** | Como ya no existe "Mis reservas", el usuario no ve si su solicitud para hoy se aprobó. | Que el admin se lo comunique, o mostrar el estado en la pantalla de confirmación. |
| P-03 | **Contraseña por defecto** | El admin entra con admin / admin. | Cambiarla con `ADMIN_PASSWORD` antes de publicar la app en internet. |
| P-04 | **Hora límite** para reservar el siguiente día laborable | Se puede reservar hasta las 23:59 del día anterior. | ¿Fijar una hora de cierre (por ejemplo, las 20:00)? |
| P-05 | **Autogestión del titular** | Solo el admin puede liberar una plaza fija. | Permitir que el titular la ceda él mismo. |
| P-06 | **Histórico** | Las reservas pasadas se guardan, pero no se pueden consultar. | Añadir una pantalla de histórico o una exportación a CSV. |
| P-07 | **Despliegue** | Solo se ha ejecutado en local. | Elegir alojamiento, dominio y HTTPS (ver RNF-06). |
| P-08 | **Festivos de 2028** | Hay festivos cargados hasta 2027. | Añadirlos en Ajustes cuando se publiquen (BOCM, octubre a diciembre de 2027). |

## 13. Historial de versiones

| Versión | Fecha | Cambios |
|---|---|---|
| 1.0 | 16/10/2026 | Versión inicial: plazas configurables, fijas y reservables; lista de libres adaptada al móvil; reservas por día; admin básico. |
| 1.1 | 16/10/2026 | Roles de usuario y admin sin cuentas; reserva para el día siguiente y solicitud para hoy; tablero del admin para liberar y ocupar; aprobación de solicitudes; avisos al admin; se elimina la matrícula. |
| 1.2 | 16/10/2026 | Reserva para el **siguiente día laborable** con el calendario de festivos de Madrid 2026–2027, editable; se elimina "Mis reservas"; pantalla de confirmación con instrucciones para cancelar por correo; acceso del admin con usuario y contraseña (admin / admin); ajustes de festivos y del correo del admin. |
| 1.3 | 16/10/2026 | Plazas **fijas**: el admin las libera para **un único día**, que puede ser el mismo día, y al día siguiente vuelven a estar cerradas. No se pueden liberar días pasados. En la interfaz, «nominal» pasa a llamarse «fija». |
| 1.4 | 16/10/2026 | **Numeración libre de plazas**: el admin las da de alta con su número real (sueltas o por rangos), las renumera y las elimina. Desaparece el «número total de plazas» (antes las plazas se numeraban 1..N). Edición en una sola línea por plaza: el titular determina si es fija. |
| 1.5 | 16/10/2026 | Rediseño del **tablero del admin**: indicadores, barra de ocupación, filtros por estado y rejilla de plazas con etiqueta de estado (punto de color siempre acompañado de texto). Modo claro y oscuro. |

---

# Inbox

_Vacío. Las entradas del 16/10/2026 se han incorporado en la versión 1.2._
