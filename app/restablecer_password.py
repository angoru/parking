"""Restablece la contraseña del admin si se ha olvidado la que se puso desde el panel.

    python -m app.restablecer_password
    docker compose exec app python -m app.restablecer_password   (en el servidor)

Borra la contraseña guardada y cierra todas las sesiones. Vuelve a valer la de
ADMIN_PASSWORD_FILE o ADMIN_PASSWORD; si no hay ninguna, admin/admin, que obliga a cambiarla.
"""
from . import db, seguridad


def restablecer() -> str:
    db.init_db()
    conn = db.connect()
    try:
        conn.execute("DELETE FROM config WHERE key = 'admin_password'")
        conn.execute("DELETE FROM sesiones")
        conn.commit()
    finally:
        conn.close()
    if seguridad.password_entorno():
        return "Contraseña restablecida: vuelve a valer la de ADMIN_PASSWORD_FILE o ADMIN_PASSWORD."
    return "Contraseña restablecida a admin/admin: la app pedirá cambiarla al entrar."


if __name__ == "__main__":
    print(restablecer())
