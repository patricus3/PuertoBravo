"""Arranque del servidor en línea de Puerto Bravo.

    python -m servidor                      con servidor.conf de la carpeta actual, si existe
    python -m servidor mi_servidor.conf     con otro archivo de configuración
    python -m servidor --ejemplo            escribe un servidor.conf de ejemplo y sale
    python -m servidor --comprobar          revisa servidor.conf, dice lo que no vale y sale
    python -m servidor --opciones           dice todas las opciones, con su explicación, y sale
    python -m servidor --parar              para con orden el servidor que está en marcha con esa configuración
    python -m servidor --actualizar         lo para avisando de que se reinicia para actualizarse: los juegos esperan y vuelven solos
    python -m servidor --reiniciar          lo mismo, diciendo que es por mantenimiento
    python -m servidor --puerto=47821       cualquier opción se puede dar también así, sin tocar el archivo

Las banderas valen también en inglés: --example, --check, --options, --stop, --update, --restart.

Mientras funciona, se le pueden escribir órdenes, en español o en inglés: ayuda (o help) las dice todas.
"""
from .idioma import tr
import asyncio
import os
import signal
import sys
import threading
import time

from . import enmarcha, opciones
from .nucleo import ARCHIVO_ORDEN, CONFIG, Servidor, leer_config

# El ejemplo de servidor.conf sale de la descripción de las opciones: no se escribe a mano, y así no se queda atrás.
EJEMPLO = opciones.texto_conf()


# Para parar con orden un servidor que no tiene consola delante (una tarea programada, un servicio): basta con dejar
# este archivo en su carpeta de datos. El servidor lo ve, lo borra, avisa a los jugadores, lo guarda todo y sale. Según
# lo que lleve escrito, para sin más (parar), o avisa de que vuelve enseguida (actualizar, reiniciar).
ARCHIVO_PARAR = ARCHIVO_ORDEN


def _hora():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def pedir_parada(cfg, espera=20.0, orden="parar"):
    """Pide a un servidor en marcha que pare, dejándole el archivo de parada. Devuelve si lo ha recogido.
    Con ``orden`` «actualizar» o «reiniciar», el servidor avisa antes a los jugadores de que vuelve enseguida."""
    ruta = os.path.join(cfg["datos"], ARCHIVO_PARAR)
    if not os.path.isdir(cfg["datos"]):
        print(tr("No existe la carpeta de datos «%s»: ahí no hay ningún servidor que parar.") % cfg["datos"])
        return False
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(orden + "\n")
    fin = time.time() + espera
    while time.time() < fin:
        if not os.path.exists(ruta):
            print(tr("El servidor ha recogido la orden: avisa a los jugadores, lo guarda todo y se para.") if orden == "parar" else
                  tr("El servidor ha recogido la orden: avisa a los jugadores con una cuenta atrás, lo guarda todo y se para. "
                     "Los juegos esperarán y volverán a entrar solos cuando lo arranques otra vez."))
            return True
        time.sleep(0.5)
    try:
        os.remove(ruta)
    except OSError:
        pass
    print(tr("Nadie ha recogido la orden: no parece que haya un servidor en marcha con esa carpeta de datos."))
    return False


def _vigilar_cierre_de_consola(parar, parado):
    """En Windows, cerrar la ventana de la consola, cerrar la sesión o apagar el equipo también paran el servidor con
    orden: se avisa, se guarda todo y se sale, en vez de cortarlo en seco. Devuelve algo que hay que conservar."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        def manejador(tipo):
            if tipo in (2, 5, 6):                # cerrar la ventana, cerrar la sesión, apagar el equipo
                parar(tipo)
                parado.wait(4.5)                 # Windows da unos cinco segundos antes de cortar
                return 1
            return 0
        ctypes.windll.kernel32.SetConsoleCtrlHandler(manejador, 1)
        return manejador
    except Exception:
        return None


# Las banderas valen también en inglés, como las órdenes de la consola.
BANDERAS_EN = {"--example": "--ejemplo", "--check": "--comprobar", "--options": "--opciones", "--stop": "--parar",
               "--update": "--actualizar", "--restart": "--reiniciar"}


def main(args=None):
    args = [BANDERAS_EN.get(a.lower(), a) for a in (sys.argv[1:] if args is None else args)]
    ruta = next((a for a in args if not a.startswith("--")), "servidor.conf")
    if "--ejemplo" in args:
        if os.path.exists(ruta):
            print(tr("Ya hay un %s en esta carpeta. No lo toco.") % os.path.basename(ruta))
            return 1
        with open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.write(EJEMPLO)
        print(tr("Escrito %s. Ábrelo con un editor de texto, cámbialo a tu gusto y arranca el servidor.") % os.path.basename(ruta))
        return 0
    if "--opciones" in args:
        print(EJEMPLO)
        return 0
    avisos = []
    cfg = leer_config(ruta, avisos)
    for a in args:                                           # también valen opciones sueltas: --puerto=47821
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            k = k.strip().lower()
            if k in CONFIG:
                valor, error = opciones.validar_valor(k, v)
                if error:
                    avisos.append(tr("--%s: %s. No se le hace caso.") % (k, error))
                else:
                    cfg[k] = valor
            else:
                avisos.append(tr("--%s: no existe ninguna opción con ese nombre.") % k)
    if "--parar" in args:
        return 0 if pedir_parada(cfg) else 1
    for bandera, orden in (("--actualizar", "actualizar"), ("--reiniciar", "reiniciar")):
        if bandera in args:
            return 0 if pedir_parada(cfg, orden=orden) else 1
    if "--comprobar" in args:
        if not os.path.exists(ruta):
            print(tr("No hay ningún archivo %s. Con --ejemplo se escribe uno.") % ruta)
            return 1
        for a in avisos:
            print(a)
        print(tr("La configuración tiene %d problemas.") % len(avisos) if avisos else tr("La configuración está bien."))
        return 1 if avisos else 0
    try:
        srv = Servidor(cfg)
    except Exception as e:                                   # la carpeta de datos no se puede crear, la base está dañada...
        print(tr("No se puede arrancar con la carpeta de datos «%s»: %s: %s") % (cfg["datos"], type(e).__name__, e))
        return 2
    srv.ruta_conf = os.path.abspath(ruta) if os.path.exists(ruta) else None
    srv.log = lambda t: print("%s  %s" % (_hora(), t), flush=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for a in avisos:
        srv.log(tr("Configuración: %s") % a)
    try:
        loop.run_until_complete(srv.iniciar())
    except OSError as e:
        print(tr("No se pudo abrir el puerto %s: %s. Puede que el servidor ya esté en marcha, o que otro programa use ese puerto.") % (cfg["puerto"], e))
        return 2
    except RuntimeError as e:
        print(str(e))
        return 2
    if not os.path.exists(ruta):
        srv.log(tr("No hay archivo de configuración: uso los valores de serie. Con --ejemplo se escribe uno."))
    srv.log(tr("Datos del mundo: versión %s, huella %s. %d localidades.") % (srv.mundo.get("version"), srv.mundo.get("huella"), len(srv.mundo["mapas"])))
    tope = int(srv.cfg["max_jugadores"])
    srv.log((tr("Caben %d jugadores a la vez.") % tope) if tope > 0 else tr("Caben todos los jugadores que entren: no hay límite."))
    if srv.huella_cert:
        srv.log(tr("Huella del certificado: %s") % srv.huella_cert)
    srv.log(tr("Escribe ayuda o help para ver las órdenes: valen en español y en inglés."))

    def consola():
        try:
            for linea in sys.stdin:
                linea = linea.strip()
                if linea:
                    loop.call_soon_threadsafe(lambda t=linea: print(srv.orden(t), flush=True))
        except Exception:
            pass
    threading.Thread(target=consola, daemon=True).start()

    # La ficha de servidor en marcha: con ella, la actualización del juego en Windows sabe que está abierto y cómo volver a
    # arrancarlo. Solo se escribe en el juego compilado.
    enmarcha.anotar("consola", srv.cfg["datos"], conf=srv.ruta_conf, args=args)

    def parar(senal=None, *_):
        # Control+C y cerrar la ventana son de quien lo lleva: se apaga sin más. Si lo para el sistema (la señal de
        # terminar de systemd o de Docker, cerrar la sesión o apagar el equipo), lo normal es que vuelva: se dice a los
        # juegos que esperen. En los dos casos hay poco tiempo antes de que el sistema corte: no se espera más de tres segundos.
        vuelve = senal in (getattr(signal, "SIGTERM", None), 5, 6) and senal is not None
        loop.call_soon_threadsafe(lambda: loop.create_task(
            srv.detener(causa="reinicio" if vuelve else "apagado", espera=min(3.0, float(srv.cfg.get("parada_espera", 6) or 0)))))
    parado = threading.Event()
    _vigilancia = _vigilar_cierre_de_consola(parar, parado)      # hay que conservar la referencia mientras funcione
    for s in (signal.SIGINT, getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
        if s is not None:
            try:
                signal.signal(s, parar)
            except (ValueError, OSError):
                pass

    async def esperar():
        # El archivo de órdenes (--parar, --actualizar, --reiniciar) lo mira el propio servidor, cada segundo.
        while srv.activo:
            await asyncio.sleep(0.5)
        for _ in range(100):                                 # hasta que termine de guardar
            if srv.detenido:
                break
            await asyncio.sleep(0.1)
    try:
        loop.run_until_complete(esperar())
    except KeyboardInterrupt:
        loop.run_until_complete(srv.detener())
    enmarcha.quitar()
    print("%s  %s" % (_hora(), tr("Servidor parado. Todo guardado.")), flush=True)
    if srv.codigo_salida:
        print("%s  %s" % (_hora(), tr("Se ha parado para volver: el programa termina con el código %d.") % srv.codigo_salida), flush=True)
    parado.set()
    if _vigilancia is not None:                              # ya no hay nada que vigilar: se retira
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_vigilancia, 0)
        except Exception:
            pass
    return int(srv.codigo_salida or 0)


if __name__ == "__main__":
    sys.exit(main())
