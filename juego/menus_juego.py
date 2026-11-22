"""Menús del juego: principal, pausa, opciones, móvil, lugares, tiendas, casino y guardado."""
from .i18n import tr
import json
import math
import os
import random
import time

import zlib

from . import NOMBRE, VERSION, ayuda, cifrado, i18n, packs, rutas
from . import mundo as M
from .config import OPCIONES
from .combate import ayuda_arma, ficha_corta
from .menus import Dialogo, Menu, Opcion

RANURAS = ["auto", "rapido", "1", "2", "3", "4", "5"]
NOMBRE_RANURA = {"auto": tr("Guardado automático"), "rapido": tr("Guardado rápido")}


# ====================================================================== guardado
CARPETA = "partidas"


def _archivo(ranura, ext=None):
    """Archivo de una ranura. En el juego compilado las partidas van protegidas y con extensión propia."""
    ext = ext or (rutas.EXT_PARTIDA if cifrado.COMPILADO else ".json")
    return os.path.join(rutas.carpeta_data(CARPETA), f"partida_{ranura}{ext}")


def _archivos_validos(ranura):
    """Los archivos de una ranura que el juego acepta. En el juego compilado solo valen las partidas protegidas:
    una partida legible, escrita o retocada a mano, no se carga."""
    posibles = [r for r in (_archivo(ranura, rutas.EXT_PARTIDA), _archivo(ranura, ".json")) if os.path.exists(r)]
    if cifrado.COMPILADO:
        posibles = [r for r in posibles if cifrado.esta_cifrado(r)]
    return posibles


def leer_ranura(ranura):
    """Lee la ranura. En el código fuente, si hay una partida con cada extensión, vale la más reciente."""
    for ruta in sorted(_archivos_validos(ranura), key=os.path.getmtime, reverse=True):
        try:
            return cifrado.leer_json(ruta)
        except (OSError, ValueError, zlib.error):
            continue
    return None


def escribir_ranura(p, ranura):
    if getattr(p, "en_servidor", False):                 # en un servidor, el personaje se guarda en el servidor
        return p.sv_guardar(ya=True)
    d = p.a_dict()
    d["fecha"] = time.strftime("%d/%m/%Y %H:%M")
    d["resumen"] = tr('{len} misiones, {dinero} euros, día {dia}').format(len=(len(p.completadas)), dinero=(p.j.dinero), dia=(p.dia))
    try:
        cifrado.escribir_json(_archivo(ranura), d)          # en el juego compilado la partida queda protegida
        return True
    except OSError:
        return False


def texto_ranura(ranura):
    d = leer_ranura(ranura)
    nombre = NOMBRE_RANURA.get(ranura, tr('Ranura {ranura}').format(ranura=(ranura)))
    if not d:
        return tr('{nombre}: vacía').format(nombre=(nombre))
    return tr('{nombre}: {get}. {get2}. Guardada el {get3}').format(nombre=(nombre), get=(d.get('resumen', '')), get2=(d.get('lugar', '')), get3=(d.get('fecha', '')))


def mas_reciente():
    mejor = None
    for r in RANURAS:
        tiempos = [os.path.getmtime(a) for a in _archivos_validos(r)]
        if not tiempos or leer_ranura(r) is None:      # una partida estropeada o manipulada no cuenta
            continue
        t = max(tiempos)
        if mejor is None or t > mejor[0]:
            mejor = (t, r)
    return mejor[1] if mejor else None


def autoguardar(p):
    if escribir_ranura(p, "auto"):
        p.decir(tr("Partida guardada automáticamente."))


def guardado_rapido(p):
    if p.mision:
        p.app.son("error")
        p.decir(tr("No se puede guardar durante una misión."), True)
    elif p.j.estrellas:
        p.app.son("error")
        p.decir(tr("No se puede guardar mientras te busca la policía."), True)
    elif escribir_ranura(p, "rapido"):
        p.app.son("guardado")
        p.decir(tr("Guardado rápido hecho."), True)


def menu_guardar(p):
    app = p.app
    if p.mision:
        app.son("error")
        p.decir(tr("No se puede guardar durante una misión."), True)
        return

    def hacer(r):
        def f():
            if escribir_ranura(p, r):
                app.son("guardado")
                app.cerrar(m)
                app.decir(tr('Partida guardada en la ranura {r}.').format(r=(r)), True)
            else:
                app.son("error")
                app.decir(tr("No se pudo guardar la partida."), True)
        return f
    m = Menu(app, tr("Guardar partida. Elige una ranura"), lambda: [Opcion(texto_ranura(r), hacer(r), ayuda=tr("Guarda aquí la partida tal como está ahora. Si la ranura ya tenía una partida, la sustituye.")) for r in RANURAS[2:]])
    app.abrir(m)


def menu_cargar(app):
    def hacer(r):
        def f():
            d = leer_ranura(r)
            if not d:
                app.son("error")
                app.decir(tr("Esa ranura está vacía."), True)
                return
            app.empezar_partida(d)
        return f
    app.abrir(Menu(app, tr("Cargar partida"), lambda: [Opcion(texto_ranura(r), hacer(r), ayuda=tr("Carga la partida guardada en esta ranura y sigues desde ahí. Si estabas jugando, lo que no hayas guardado se pierde.")) for r in RANURAS]))


# Lo que pasa de una partida a la siguiente al empezar de nuevo conservando lo ganado.
CONSERVA = ("dinero", "banco", "armas", "arma", "objetos", "mochila", "mochila_grande", "vestuario", "calzado", "hab", "logros", "propiedades", "garajes", "barcos", "salud_max", "ropa", "casetes", "stats",
            "bolsa", "negocios", "personaje", "nombre", "apellido", "genero", "perro", "conocidos", "cobro_negocios")


def partida_mas(app):
    """Nueva partida conservando lo ganado en una partida guardada."""
    from .partida import PartidaMasNueva, migrar

    def empezar(r):
        def f():
            try:
                d = migrar(leer_ranura(r))
            except (PartidaMasNueva, TypeError):
                app.son("error")
                app.decir(tr("Esa partida no se puede leer con esta versión del juego."), True)
                return
            viejo = d.get("jugador", {})
            app.empezar_partida(None, personaje=viejo.get("personaje"))
            p = app.partida
            for k in CONSERVA:
                if k in viejo and hasattr(p.j, k):
                    setattr(p.j, k, viejo[k])
            p.j.ciclo = int(viejo.get("ciclo", 0)) + 1
            __import__("juego.genero", fromlist=["x"]).poner(p.j.genero)
            if p.j.personaje == "propio":
                from . import registro
                registro.ocultar(p.j.nombre)
                registro.ocultar(p.j.apellido)
            p.j.salud = p.j.salud_max
            if p.j.arma not in p.j.armas:
                p.j.arma = "punos"
            app.decir(tr('Empiezas de nuevo con lo que tenías: {dinero} euros, {len} armas y {len2} propiedades. Es tu vuelta número {v}: los enemigos de las misiones aguantan algo más.').format(dinero=(p.j.dinero), len=(len(p.j.armas)), len2=(len(p.j.propiedades)), v=(p.j.ciclo + 1)))
        return f
    ops = [Opcion(texto_ranura(r), empezar(r), ayuda=tr("Empiezas la historia desde el principio con el dinero, las armas, las propiedades y lo demás que tenías en esta partida. La partida guardada no se toca.")) for r in RANURAS if leer_ranura(r) is not None]
    app.abrir(Menu(app, tr("Nueva partida conservando lo ganado. Elige de qué partida guardada"), ops or [Opcion(tr("No hay ninguna partida guardada"), ayuda=tr("Para esto hace falta una partida guardada. Guarda una desde el menú de pausa o en una casa tuya y vuelve aquí."))]))


# ====================================================================== principal
def principal(app):
    def ops():
        lista = []
        r = mas_reciente()
        if r:
            lista.append(Opcion(tr("Continuar"), lambda: app.empezar_partida(leer_ranura(r)), ayuda=tr("Carga la partida guardada más reciente.")))
        lista += [
            Opcion(tr("Nueva partida"), lambda: __import__("juego.menus_vida", fromlist=["x"]).elegir_personaje(app),
                   ayuda=tr("Eliges con qué personaje juegas y empiezas la historia desde el principio. Tus partidas guardadas no se tocan.")),
            Opcion(tr("Cargar partida"), lambda: menu_cargar(app), ayuda=tr("Elige una de tus partidas guardadas: el guardado automático, el rápido o una de las cinco ranuras.")),
            Opcion(tr("Nueva partida conservando lo ganado"), lambda: partida_mas(app),
                   ayuda=tr("Empiezas la historia desde el principio, pero con el dinero, las armas, las habilidades, las casas, los vehículos y los barcos de una partida guardada. "
                         "Los enemigos de las misiones aguantan algo más cada vez. La partida guardada no se toca.")),
            Opcion(tr("Jugar en un servidor"), lambda: __import__("juego.menus_enlinea", fromlist=["x"]).servidores(app),
                   ayuda=tr("Un servidor es un mundo que no se apaga, con jugadores de verdad: puedes hacer todo lo que haces jugando por tu cuenta, y además encontrarte con los demás, "
                         "comerciar, formar bandas, pelear por los barrios o hacer misiones en grupo. Tu personaje se guarda en el servidor.")),
            Opcion(tr("Jugar con amigos"), lambda: app.decir(tr("Para jugar con amigos, empieza o carga tu partida, abre el móvil con la tecla M y entra en Jugar con amigos. "
                                                        "Desde ahí puedes abrir tu partida, con o sin contraseña, y darles tu dirección, o unirte a la de un amigo."), True),
                   ayuda=tr("El propio juego monta el servidor en tu ordenador. No hace falta ningún programa más.")),
            Opcion(tr("Aprender los sonidos del juego"), lambda: sonidos(app),
                   ayuda=tr("Escucha cada sonido del juego con su explicación: primero los más importantes y después todos, por grupos, con un buscador.")),
            Opcion(tr("Opciones"), lambda: opciones(app), ayuda=tr("Sonido, voz, movimiento, orientación, dificultad, teclas, mando y el resto de ajustes, por secciones. Los cambios se guardan al salir.")),
            Opcion(tr("Ayuda: lista de teclas"), lambda: ayuda_teclas(app, "todo"),
                   ayuda=tr("Todas las teclas del juego, a pie, al volante y en cualquier momento, y los botones del mando. Si has cambiado alguna tecla, dice la tuya.")),
            Opcion(tr("Abrir el manual"), lambda: abrir_manual(app), ayuda=tr("Abre el manual completo del juego en tu navegador. El juego sigue abierto detrás.")),
            Opcion(tr("Acerca de"), lambda: acerca(app), ayuda=tr("La versión que tienes, quién ha hecho el juego, dónde avisar de un fallo y cómo invitarle a un café.")),
            Opcion(tr("Salir"), app.salir, ayuda=tr("Cierra el juego.")),
        ]
        return lista
    app.abrir(Menu(app, tr('{NOMBRE}. Menú principal').format(NOMBRE=(NOMBRE)), ops, escapable=False,
                   intro=tr("Usa las flechas arriba y abajo para moverte y pulsa Intro para elegir")))


def acerca(app):
    """Versión, autor, licencia, enlaces y la invitación a un café."""
    from . import ANIO, AUTOR, CAFE, FALLOS, MASTODON, VERSION, WEB

    def abrir(url, que):
        def hacer():
            try:
                os.startfile(url)
                app.decir(tr('Abriendo {que} en tu navegador.').format(que=(que)), True)
            except (OSError, AttributeError):
                app.son("error")
                app.decir(tr('No se pudo abrir el navegador. La dirección es {url}').format(url=(url)), True)
        return hacer
    m = Menu(app, tr('Acerca de {NOMBRE}').format(NOMBRE=(NOMBRE)), [
        Opcion(tr('{NOMBRE}, versión {VERSION}').format(NOMBRE=(NOMBRE), VERSION=(VERSION)), ayuda=tr("La versión que tienes instalada. Las versiones nuevas se buscan en Opciones, Actualizaciones.")),
        Opcion(tr('Hecho por {AUTOR}').format(AUTOR=(AUTOR)), ayuda=tr("Más abajo están la página del proyecto, dónde avisar de un fallo y el perfil del autor en Mastodon.")),
        Opcion(tr('Copyright {ANIO}, {AUTOR}. Software libre con licencia MIT: puedes usarlo, modificarlo y repartirlo').format(ANIO=(ANIO), AUTOR=(AUTOR)),
               ayuda=tr("El texto completo de la licencia está en la página del proyecto.")),
        Opcion(tr("Un audiojuego de mundo abierto, en español, pensado desde el principio para jugarse sin ver la pantalla"),
               ayuda=tr("Todo se juega de oído, con tu lector de pantalla o con la voz de Windows, y con el teclado o con un mando.")),
        Opcion(tr("Invítame a un café si te gusta mi trabajo"), abrir(CAFE, tr("la página de donaciones de PayPal")),
               ayuda=tr("El juego es gratis y lo seguirá siendo. Si te ha hecho pasar un buen rato y quieres agradecerlo, Intro abre la página de donaciones en el navegador.")),
        Opcion(tr("Página del proyecto en GitHub"), abrir(WEB, tr("la página del proyecto")), ayuda=tr("La descripción completa, el código fuente y todas las versiones.")),
        Opcion(tr("Avisar de un fallo o proponer una mejora"), abrir(FALLOS, tr("la página de incidencias")),
               ayuda=tr("En Opciones, Registro para informar de fallos, se explica qué carpeta adjuntar.")),
        Opcion(tr("Mastodon del autor"), abrir(MASTODON, tr("el perfil de Mastodon")), ayuda=tr("Abre en tu navegador el perfil del autor en Mastodon.")),
        Opcion(tr("Novedades de esta versión"), abrir(i18n.doc("novedades"), tr("las novedades")),
               ayuda=tr("Abre en tu navegador lo que ha cambiado en cada versión del juego, empezando por la última.")),
        Opcion(tr("Agradecimientos: a quienes prueban el juego y avisan de los fallos. Los sonidos son mejorables y toda ayuda con ellos es bienvenida"),
               ayuda=tr("La guía cambiar sonidos, en la carpeta data, docs, explica cómo sustituir cualquier sonido o montar un pack completo.")),
        Opcion(tr("Componentes: las voces de las escenas están generadas por ordenador con Phonon 40m, un modelo de voz de Gradium con licencia "
               "Creative Commons de reconocimiento y uso no comercial. El modelo local de inteligencia artificial, si lo instalas, funciona con llama punto c p p"),
               ayuda=tr("El texto de la licencia de Phonon va con el juego, en el archivo LICENCIA Phonon Gradium, y en la carpeta data, phonon.")),
        Opcion(tr("Volver"), lambda: app.cerrar(m)),
    ])
    app.abrir(m)


def _canciones_txt(app):
    try:
        n = sum(1 for f in os.listdir(app.radio.usuario) if f.lower().endswith(rutas.EXT_AUDIO))
    except OSError:
        n = 0
    return tr("está vacía") if n == 0 else tr("tiene una canción") if n == 1 else tr('tiene {n} canciones').format(n=(n))


def abrir_mi_musica(app):
    """Abre en el Explorador la carpeta de la emisora Mi música, creándola si falta."""
    ruta = app.radio.usuario
    try:
        os.makedirs(ruta, exist_ok=True)
        os.startfile(ruta)
        app.decir(tr('Carpeta de mi música abierta en el Explorador de Windows. Ahora {_canciones_txt}. Copia en ella tus canciones y sintoniza Mi música en la radio de un vehículo.').format(_canciones_txt=(_canciones_txt(app))), True)
    except (OSError, AttributeError):
        app.son("error")
        app.decir(tr('No he podido abrir la carpeta. Está en {ruta}').format(ruta=(ruta)), True)


def mi_musica(app):
    """Cómo poner tu propia música, paso a paso y sin nombrar carpetas internas: la carpeta la abre el juego."""
    md = getattr(app, "mando", None)
    con_mando = md is not None and md.conectado
    pasos = [
        tr("Uno. Elige más abajo Abrir la carpeta de mi música. Se abre una ventana de Windows con una carpeta: es la de tus canciones. El juego sigue abierto detrás."),
        tr("Dos. Copia ahí tus canciones, como en cualquier carpeta: búscalas en tu ordenador, cópialas con Control C y pégalas en esa ventana con Control V. "
        "Valen archivos mp3, ogg, flac y wav. También puedes pegar carpetas enteras."),
        tr("Tres. Vuelve al juego con Alt y Tabulador. No hace falta cerrarlo ni reiniciarlo."),
        tr("Cuatro. Sube a cualquier vehículo y cambia de emisora, ") + (tr("con la combinación del mando que dice la ayuda, ") if con_mando else tr("con la R, "))
        + tr("hasta oír Mi música. Dentro de Mi música, la misma tecla pasa a la canción siguiente. Si tienes el reproductor con auriculares, también suena a pie."),
        tr("Tus canciones no salen de tu ordenador: en un servidor en línea nadie las oye, y las actualizaciones del juego no las tocan."),
    ]
    ops = [Opcion(t.rstrip("."), ayuda=tr("Es un paso de la explicación: Intro lo vuelve a leer. La opción que abre la carpeta está después del último paso.")) for t in pasos]               # el menú pone el punto
    ops.append(Opcion(lambda: tr('Abrir la carpeta de mi música: {_canciones_txt}').format(_canciones_txt=(_canciones_txt(app))), lambda: abrir_mi_musica(app),
                      ayuda=tr("Abre la carpeta en el Explorador de Windows, y la crea si no existe. Al volver a este menú dice cuántas canciones hay.")))
    ops.append(Opcion(tr("Volver"), lambda: app.cerrar(m)))
    m = Menu(app, tr("Mi música: cómo poner tus canciones en la radio. Son cuatro pasos: recórrelos con las flechas"), ops)
    app.abrir(m)


def abrir_manual(app):
    ruta = i18n.doc("manual")
    try:
        os.startfile(ruta)
        app.decir(tr("Abriendo el manual en tu navegador."), True)
    except (OSError, AttributeError):
        app.son("error")
        app.decir(tr("No se encontró el manual. Está en la carpeta data, docs."), True)


def grupos_de_sonidos(nombres):
    """Los sonidos, repartidos en los grupos del catálogo: [(título, [sonido, ...]), ...], cada grupo por orden alfabético del
    nombre que se dice. Es la misma clasificación para Aprender los sonidos, para el volumen de cada sonido y para la guía.
    Ninguno se queda fuera: el que no esté en el catálogo va a «Otros sonidos». Las canciones de la radio y la música no entran."""
    from . import catalogo_sonidos as cat
    return cat.clasificar(nombres)


def sonidos_aprender(nombres):
    """Lo que enseña Aprender los sonidos: [(título del grupo, [(sonido, texto), ...]), ...]. Primero los más importantes,
    en el orden en que conviene aprenderlos, y después todos, por grupos, cada uno con su nombre y su explicación."""
    from . import catalogo_sonidos as cat
    return ([(tr("Los más importantes"), [(s, cat.texto_aprender(s, suelto=True)) for s in cat.importantes(nombres)])]
            + [(titulo, [(s, cat.texto_aprender(s)) for s in lista]) for titulo, lista in cat.clasificar(nombres)])


def _n_sonidos(n):
    return tr("1 sonido") if n == 1 else tr('{n} sonidos').format(n=(n))


def buscar_sonido(app, mostrar):
    """Pide una palabra y enseña los sonidos que la tienen en el nombre o en la explicación, sin contar tildes ni mayúsculas.
    mostrar(texto, [(sonido, título de su grupo), ...]) abre la lista. Con mando se escribe con la rueda de letras."""
    from . import catalogo_sonidos as cat
    from .menus import EntradaTexto

    def hecho(texto):
        texto = (texto or "").strip()
        if not texto:
            app.decir(tr("No has escrito nada."), True)
            return
        hallados = cat.buscar(texto, app.mez.sonidos)
        if not hallados:
            app.son("error")
            app.decir(tr('Ningún sonido tiene {texto} en el nombre ni en la explicación. Prueba con otra palabra, o con menos letras.').format(texto=(texto)), True)
            return
        mostrar(texto, hallados)
    app.abrir(EntradaTexto(app, tr("Buscar un sonido. Escribe parte de su nombre o de lo que significa"), hecho, maximo=40,
                           ayuda=tr("Vale una palabra o un trozo: por ejemplo sirena, puerta o policía. Da igual escribirlo con tildes o sin ellas, y en mayúsculas o en minúsculas. "
                                 "Con varias palabras, salen los sonidos que las tienen todas.")))


def sonidos(app):
    """Aprender los sonidos: todos los del juego. Primero los más importantes y después todos, por grupos, y un buscador."""
    def tocar(s):
        return lambda: app.mez.sonar(s, cat="interfaz", vol=0.9)

    def lista_(titulo, pares, intro=tr("Pulsa Intro sobre cada elemento para escuchar su sonido. Una letra salta al siguiente que empieza por ella")):
        m = Menu(app, f"{titulo}, {_n_sonidos(len(pares))}", [Opcion(texto, tocar(s), callado=True, ayuda=tr("Intro lo hace sonar otra vez. Su volumen se ajusta en Opciones, Sonido y música, Ajustar el volumen de cada sonido.")) for s, texto in pares] + [Opcion(tr("Volver"), lambda: app.cerrar(m))],      # solo suena el sonido que se está aprendiendo
                 intro=intro)
        app.abrir(m)

    def hallados(texto, lista):
        from . import catalogo_sonidos as cat
        lista_(tr('Sonidos con {texto}').format(texto=(texto)), [(s, tr('{nombre}, del grupo {titulo}. {describir}').format(nombre=(cat.nombre(s)), titulo=(titulo), describir=(cat.describir(s)))) for s, titulo in lista],
               intro=tr("Pulsa Intro sobre cada uno para escucharlo"))
    partes = sonidos_aprender(app.mez.sonidos)
    total = sum(len(lista) for _, lista in partes[1:])
    ops = [Opcion(f"{titulo}: {_n_sonidos(len(lista))}", (lambda titulo=titulo, lista=lista: lista_(titulo, lista)),
                  ayuda=tr("Los que más se oyen y más ayudan a orientarse, en el orden en que conviene aprenderlos.") if k == 0
                  else tr("Dentro, los sonidos van por orden alfabético de su nombre."))
           for k, (titulo, lista) in enumerate(partes)]
    ops.insert(1, Opcion(tr("Buscar un sonido"), lambda: buscar_sonido(app, hallados),
                         ayuda=tr("Escribe parte del nombre de un sonido o de lo que significa, y te salen los que coinciden, cada uno con su grupo. No hace falta poner las tildes.")))
    principal_ = Menu(app, tr("Aprender los sonidos"), ops + [Opcion(tr("Volver"), lambda: app.cerrar(principal_))],
                      intro=tr('El juego tiene {total} sonidos. Primero están los más importantes, después Buscar un sonido, y después todos, por grupos y en orden alfabético. Pulsa Intro para entrar en un grupo').format(total=(total)))
    app.abrir(principal_)


def opciones_teclado(app):
    """Cambiar con qué tecla se hace cada función del juego."""
    from . import teclado
    cfg = app.cfg

    def cambiar(funcion, que):
        def abrir():
            def elegida(k):
                desplazada = teclado.cambiar(cfg, funcion, k)
                cfg.guardar()
                app.son("guardado")
                extra = tr(' Lo que hacía {nombre} pasa a {nombre2}.').format(nombre=(teclado.nombre(k)), nombre2=(teclado.nombre(teclado.tecla_de(cfg, desplazada)))) if desplazada is not None else ""
                app.decir(tr('Hecho: {v}, con {nombre}.{extra}').format(v=(que.split(':')[0].split('.')[0]), nombre=(teclado.nombre(k)), extra=(extra)), True)
            app.abrir(teclado.Captura(app, tr('Tecla nueva para: {v}').format(v=(que.split('.')[0])), elegida))
        return abrir

    def restablecer():
        teclado.restablecer(cfg)
        cfg.guardar()
        app.decir(tr("Teclas originales restablecidas."), True)

    def ops():
        def en_menus(_d=1):
            cfg["teclas_menus"] = not cfg["teclas_menus"]
            cfg.guardar()
        lista = [Opcion(lambda: tr('Teclas cambiadas: {len}').format(len=(len(teclado.cambios(cfg)))),
                        ayuda=tr("Cuántas funciones tienes ahora con una tecla distinta de la original. Debajo, cada función dice con qué tecla va.")),
                 Opcion(lambda: tr('Usar también las teclas cambiadas en los menús y los diálogos: {v}').format(v=(tr('sí') if cfg['teclas_menus'] else tr('no'))), ajuste=en_menus,
                        ayuda=tr("Con sí, si has puesto el movimiento en otras teclas, los menús también se recorren con ellas. Sirve, por ejemplo, si tu lector de pantalla se queda con las flechas. "
                              "Al escribir un texto las teclas son siempre las normales. Si te lías, Restablecer las teclas originales lo deja todo como estaba."))]
        for k, ctx, que in teclado.funciones():
            actual = teclado.tecla_de(cfg, k)
            marca = tr(', ahora con {nombre}').format(nombre=(teclado.nombre(actual))) if actual != k else ""
            lista.append(Opcion(f"{ctx}. {teclado.nombre(k).capitalize()}{marca}: {que}", cambiar(k, que),
                                ayuda=tr("Intro, y después pulsa la tecla que quieres usar. Las dos teclas se intercambian, así que ninguna función se queda sin tecla.")))
        lista.append(Opcion(tr("Restablecer las teclas originales"), restablecer, ayuda=tr("Devuelve todas las funciones a su tecla de siempre y lo guarda al momento.")))
        return lista
    app.abrir(Menu(app, tr("Teclado: cambiar las teclas"), ops, al_cerrar=cfg.guardar,
                   intro=tr("Elige una función y pulsa Intro. No se pueden cambiar Escape, Intro, F1, F12, la Mayúsculas derecha ni las teclas de control y alt")))


def ayuda_teclas(app, contexto):
    grupos = {"pie": ["pie", "general"], "coche": ["coche", "general"], "todo": ["general", "pie", "coche"]}[contexto]
    titulos = {"general": tr("En cualquier momento"), "pie": tr("A pie"), "coche": tr("Al volante")}
    from . import teclado
    ops = [Opcion(tr('Tecla cambiada. {c}.').format(c=(c)), ayuda=tr("Una tecla que has cambiado tú. Se cambia o se restablece en Opciones, Teclado: cambiar las teclas.")) for c in teclado.cambios(app.cfg)]
    for g in grupos:
        for tecla, que in ayuda.TECLAS[g]:
            k = teclado._codigo(tecla)
            if k is not None and teclado.tecla_de(app.cfg, k) != k:
                tecla = teclado.nombre(teclado.tecla_de(app.cfg, k)).capitalize()        # la ayuda dice la tecla que has puesto tú
            ops.append(Opcion(f"{titulos[g]}. {tecla}: {que}.", ayuda=tr("Solo informa: Intro lo vuelve a leer. Las teclas se cambian en Opciones, Teclado: cambiar las teclas.")))
    md = app.mando
    if md.conectado or contexto == "todo":
        lineas = [Opcion(t, ayuda=tr("Lo que hace este botón del mando. Los botones se reasignan en Opciones, Mando.")) for t in md.lineas_ayuda({"pie": ("pie", "menu"), "coche": ("coche", "menu"), "todo": ("pie", "coche", "menu")}[contexto])]
        ops = lineas + ops if md.conectado else ops + lineas
    app.abrir(Menu(app, tr("Ayuda de teclas y botones"), ops, intro=tr("Recorre la lista con las flechas. Escape para volver")))


class MenuVolumenes(Menu):
    """Un menú de sonidos con su volumen: además de lo de cualquier menú, Suprimir devuelve el sonido elegido a su volumen de serie."""

    def tecla(self, ev):
        import pygame
        if ev.key == pygame.K_DELETE:
            quitar = getattr(self.opciones[self.i], "restablecer", None) if self.opciones else None
            if quitar:
                quitar()
            else:
                self.app.son("menu_borde")
            return
        super().tecla(ev)


def volumen_sonidos(app):
    """El volumen de cada sonido, por los mismos grupos que Aprender los sonidos: Intro escucha y las flechas ajustan ese sonido.
    Se puede buscar un sonido, ver los que están cambiados y restablecer uno, un grupo o todos."""
    from . import catalogo_sonidos as cat
    cfg = app.cfg

    def tocar(s):
        return lambda: app.mez.sonar(s, cat="interfaz", vol=0.9)

    def cambiados(nombres):
        return [s for s in nombres if packs.cambiado(cfg, s)]

    def quitar(nombres):
        """Devuelve esos sonidos a su volumen de serie y guarda. Dice cuántos estaban cambiados."""
        n, recargar = packs.restablecer(app.mez, cfg, nombres)
        if recargar:
            app.recargar_sonidos()
        cfg.guardar()
        return n

    def op(s, prefijo=None):
        def aj(d):
            packs.ajustar(app.mez, cfg, s, d)
            tocar(s)()

        def texto():
            pct = int(round(packs.factor(cfg, s) * 100))
            return tr('{v}: {pct} por ciento').format(v=(prefijo or cat.nombre(s)), pct=(pct)) + (tr(", cambiado") if pct != 100 else "")

        def restablecer():
            if quitar([s]):
                tocar(s)()
                app.decir(tr('{nombre} vuelve al 100 por ciento.').format(nombre=(cat.nombre(s))), True)
            else:
                app.son("menu_borde")
                app.decir(tr('{nombre} ya está al 100 por ciento.').format(nombre=(cat.nombre(s))), True)
        o = Opcion(texto, tocar(s), ajuste=aj, callado=True,
                   ayuda=tr('Archivo {s}. {describir} Intro lo hace sonar. Izquierda y derecha lo bajan o lo suben, del 30 al 200 por ciento. Suprimir lo devuelve al 100.').format(s=(s), describir=(cat.describir(s))))
        o.restablecer = restablecer
        return o

    def lista_(titulo, nombres, prefijos=None, que=tr("este grupo")):
        def restablecer():
            n = quitar(nombres)
            if n:
                app.son("guardado")
            app.decir(tr('{_n_sonidos} de {que} vuelven a su volumen de serie.').format(_n_sonidos=(_n_sonidos(n)), que=(que)) if n > 1 else tr('Un sonido de {que} vuelve a su volumen de serie.').format(que=(que)) if n
                      else tr('En {que} no hay ningún sonido cambiado.').format(que=(que)), True)

        def titulo_():
            n = len(cambiados(nombres))
            return f"{titulo}, {_n_sonidos(len(nombres))}" + (tr(', cambiados: {n}').format(n=(n)) if n else "")
        m = MenuVolumenes(app, titulo_, [op(s, (prefijos or {}).get(s)) for s in nombres]
                          + [Opcion(lambda: tr('Restablecer {que}. Cambiados: {len}').format(que=(que), len=(len(cambiados(nombres)))), restablecer,
                                    ayuda=tr("Devuelve al 100 por ciento todos los sonidos de esta lista. Los demás no se tocan.")),
                             Opcion(tr("Volver"), lambda: app.cerrar(m))],
                          al_cerrar=cfg.guardar, intro=tr("Intro para escuchar. Izquierda y derecha para ajustar. Suprimir devuelve ese sonido al 100 por ciento"))
        app.abrir(m)

    def hallados(texto, lista):
        lista_(tr('Sonidos con {texto}').format(texto=(texto)), [s for s, _ in lista], {s: tr('{nombre}, del grupo {titulo}').format(nombre=(cat.nombre(s)), titulo=(titulo)) for s, titulo in lista}, que=tr("esta búsqueda"))

    def ver_cambiados():
        """Los que no están a su volumen de serie, de todos los grupos: Intro devuelve uno al 100 por ciento."""
        def uno(s, titulo):
            def hacer():
                quitar([s])
                tocar(s)()
                if cambiados(app.mez.sonidos):
                    m.refrescar(False)
                    app.decir(tr('{nombre} vuelve al 100 por ciento. {texto}').format(nombre=(cat.nombre(s)), texto=(m.opciones[m.i].texto)), True)
                else:
                    app.cerrar(m)
                    app.decir(tr('{nombre} vuelve al 100 por ciento. Ya no queda ningún sonido cambiado.').format(nombre=(cat.nombre(s))), True)
            return Opcion(lambda: tr('Restablecer {nombre}, del grupo {titulo}: está al {int} por ciento').format(nombre=(cat.nombre(s)), titulo=(titulo), int=(int(round(packs.factor(cfg, s) * 100)))), hacer, callado=True,
                          ayuda=tr('Archivo {s}. {describir} Intro lo devuelve al 100 por ciento y lo hace sonar. Para ajustarlo de otra forma, búscalo en su grupo.').format(s=(s), describir=(cat.describir(s))))

        def ops():
            return ([uno(s, titulo) for titulo, lista in grupos for s in cambiados(lista)]
                    + [Opcion(tr("Restablecerlos todos"), lambda: (app.cerrar(m), restablecer_todos()),
                              ayuda=tr("Devuelve al 100 por ciento todos los sonidos cambiados, de todos los grupos, y cierra esta lista.")), Opcion(tr("Volver"), lambda: app.cerrar(m))])
        if not cambiados(app.mez.sonidos):
            app.son("menu_borde")
            app.decir(tr("No tienes ningún sonido cambiado: todos están a su volumen de serie."), True)
            return
        m = Menu(app, lambda: tr('Sonidos cambiados, {_n_sonidos}').format(_n_sonidos=(_n_sonidos(len(cambiados(app.mez.sonidos))))), ops, al_cerrar=cfg.guardar,
                 intro=tr("Pulsa Intro sobre uno para devolverlo a su volumen de serie"))
        app.abrir(m)
    grupos = grupos_de_sonidos(app.mez.sonidos)

    def restablecer_todos():
        n = len(cambiados(app.mez.sonidos))
        cfg["vol_sonidos"].clear()
        cfg.guardar()
        app.recargar_sonidos()
        app.decir(tr("Todos los sonidos vuelven a su volumen normal.") if n else tr("Ningún sonido estaba cambiado: todos siguen a su volumen normal."), True)

    def grupo_txt(titulo, v):
        def texto():
            n = len(cambiados(v))
            return f"{titulo}: {_n_sonidos(len(v))}" + (tr(', cambiados: {n}').format(n=(n)) if n else "")
        return texto
    ops = [Opcion(tr("Buscar un sonido"), lambda: buscar_sonido(app, hallados),
                  ayuda=tr("Escribe parte del nombre de un sonido o de lo que significa, y te salen los que coinciden, cada uno con su grupo y su volumen, listos para ajustar. No hace falta poner las tildes.")),
           Opcion(lambda: tr('Sonidos cambiados: {len}').format(len=(len(cambiados(app.mez.sonidos)))), ver_cambiados,
                  ayuda=tr("La lista de los sonidos que no están a su volumen de serie, de todos los grupos. Dentro, Intro devuelve uno al 100 por ciento."))]
    ops += [Opcion(grupo_txt(titulo, v), (lambda titulo=titulo, v=v: lista_(titulo, v)),
                   ayuda=tr("Dentro, los sonidos van por orden alfabético de su nombre. Una letra salta al siguiente que empieza por ella.")) for titulo, v in grupos]
    ops.append(Opcion(lambda: tr('Restablecer todos. Tienes {_n_sonidos} {v}').format(_n_sonidos=(_n_sonidos(len(cambiados(app.mez.sonidos)))), v=(tr('ajustado') if len(cambiados(app.mez.sonidos)) == 1 else tr('ajustados'))), restablecer_todos,
                      ayuda=tr("Devuelve todos los sonidos del juego al 100 por ciento.")))
    principal_ = Menu(app, tr("Ajustar el volumen de cada sonido"), ops + [Opcion(tr("Volver"), lambda: app.cerrar(principal_))], al_cerrar=cfg.guardar,
                      intro=tr("Los sonidos están por los mismos grupos que en Aprender los sonidos. Cada uno se ajusta del 30 al 200 por ciento de su volumen de serie, "
                            "y encima se aplican los volúmenes generales de efectos, de ambiente y de avisos. Pulsa Intro para entrar en un grupo"))
    app.abrir(principal_)


# ======================================================================= opciones
def _estilo_piloto(cfg):
    """Cómo conduce el piloto del GPS, que también se elige al volante con un toque de la A."""
    from .conduccion import ESTILOS_PILOTO, nombre_estilo

    def aj(d):
        e = cfg["piloto_estilo"]
        i = ESTILOS_PILOTO.index(e) if e in ESTILOS_PILOTO else 0
        cfg["piloto_estilo"] = ESTILOS_PILOTO[(i + d) % len(ESTILOS_PILOTO)]
    return Opcion(lambda: tr('Cómo conduce el piloto: {estilo}').format(estilo=nombre_estilo(cfg["piloto_estilo"])), ajuste=aj,
                  ayuda=tr("Automático corre solo cuando hace falta; Tranquilo va despacio; Normal cumple las normas siempre; Con prisa pero cumpliendo las normas "
                           "acelera a fondo sin que lo multen; y Con prisa saltándose las normas no espera en los semáforos. Se elige también al volante con un toque de la A."))


def opciones(app):
    """Opciones organizadas por secciones. Cada sección termina con «Volver»."""
    cfg = app.cfg
    nombres = {"brujula": tr("brújula, cada flecha va a un punto cardinal"), "giro": tr("con giros, izquierda y derecha giran"),
               "asistida": tr("asistida, el coche sigue el carril solo"), "libre": tr("libre, tú llevas el volante"),
               "completa": tr("completa, apunta sola al enemigo más cercano"), "manual": tr("manual, hay que encararse al enemigo"),
               "facil": tr("fácil"), "normal": tr("normal"), "dificil": tr("difícil"),
               "cardinal": tr("puntos cardinales"), "reloj": tr("horas del reloj"), "relativa": tr("delante, derecha, detrás, izquierda"),
               "todos": tr("todo el mundo"), "mujeres": tr("las mujeres"), "hombres": tr("los hombres"), "x": tr("prefiero no decirlo"), "h": tr("hombre"), "m": tr("mujer"),
               "nada": tr("nunca"), "pocas": tr("pocas veces"), "algunas": tr("de vez en cuando"), "muchas": tr("a menudo"),
               "apagado": tr("apagado, nadie intenta quitártelos"), "tranquilo": tr("tranquilo, pocos asaltos y con mucho plazo"), "duro": tr("duro, asaltos seguidos y con poco plazo"),
               "no": tr("no, te esperan los mismos vayas con quien vayas"), "moderado": tr("moderado, algo más de oposición si vas acompañado"),
               "fuerte": tr("fuerte, bastante más oposición si vas acompañado"),
               "suave": tr("suave, se nota sin agobiar"), "exigente": tr("exigente, todo pesa más")}
    from .honrado import AJ as HON
    from .reconquista import AJ as REC
    OPCIONES.setdefault("detalle_voz", ["poco", "normal", "mucho"])
    nombres.update({"poco": tr("poco, sin recordar las teclas"), "mucho": tr("mucho, con la explicación de cada opción")})

    def numero(clave, nombre, minimo, maximo, paso, ayuda_=None):
        def aj(d):
            cfg[clave] = max(minimo, min(maximo, cfg[clave] + paso * d))
            app.aplicar_volumenes()
            if cfg["voz_sapi"]:
                app.decir(f"{nombre}: {cfg[clave]}", True)
        return Opcion(lambda: f"{nombre}: {cfg[clave]}", ajuste=aj, ayuda=ayuda_)
    canal = {"vol_efectos": "efectos", "vol_ambiente": "ambiente", "vol_musica": "musica", "vol_interfaz": "interfaz", "vol_ambiente_musical": "musica"}

    def vol(clave, nombre, ayuda_=tr("Cámbialo con las flechas izquierda y derecha.")):
        def aj(d):
            cfg[clave] = round(max(0.0, min(1.0, cfg[clave] + 0.1 * d)), 1)
            app.aplicar_volumenes()
            app.mez.sonar("baliza" if clave not in ("vol_musica", "vol_ambiente_musical") else "menu_ok", cat=canal.get(clave, "interfaz"))
        return Opcion(lambda: tr('{nombre}: {int} por ciento').format(nombre=(nombre), int=(int(cfg[clave] * 100))), ajuste=aj, ayuda=ayuda_)

    def lista(clave, nombre, ayuda_=None):
        def aj(d):
            ops = OPCIONES[clave]
            cfg[clave] = ops[(ops.index(cfg[clave]) + d) % len(ops)]
        return Opcion(lambda: f"{nombre}: {nombres[cfg[clave]]}", ajuste=aj, ayuda=ayuda_)

    def lista_c(clave, nombre, ayuda_=None):
        propios = {"apagado": tr("apagado, todo como en versiones anteriores"), "suave": tr("suave, se nota sin agobiar"), "normal": tr("normal"), "exigente": tr("exigente, todo pesa más")}

        def aj(d):
            ops = OPCIONES[clave]
            cfg[clave] = ops[(ops.index(cfg[clave]) + d) % len(ops)]
        return Opcion(lambda: f"{nombre}: {propios[cfg[clave]]}", ajuste=aj, ayuda=ayuda_)

    def si_no(clave, nombre, ayuda_=None, al_cambiar=None):
        def aj(d):
            cfg[clave] = not cfg[clave]
            if al_cambiar:
                al_cambiar()
        return Opcion(lambda: f"{nombre}: {tr('sí') if cfg[clave] else tr('no')}", ajuste=aj, ayuda=ayuda_)

    def seccion(titulo, ops, ayuda_=None):
        def abrir():
            m = Menu(app, titulo, ops + [Opcion(tr("Volver"), lambda: app.cerrar(m), ayuda=tr("Vuelve al menú de opciones. También sirve Escape."))],
                     al_cerrar=cfg.guardar, intro=tr("Cambia cada opción con las flechas izquierda y derecha. F1 explica la opción"))
            app.abrir(m)
        return Opcion(titulo, abrir, ayuda=ayuda_)

    def nombre_pack():
        actual = cfg["pack_sonidos"]
        if not actual:
            return tr("por defecto")
        for pk in packs.listar():
            if pk["id"] == actual:
                return tr('{nombre}, {n} sonidos').format(nombre=(pk['nombre']), n=(pk['n']))
        return tr('{actual}, no instalado').format(actual=(actual))

    def cambiar_pack(d):
        ids = [""] + [pk["id"] for pk in packs.listar()]
        actual = cfg["pack_sonidos"] if cfg["pack_sonidos"] in ids else ""
        cfg["pack_sonidos"] = ids[(ids.index(actual) + d) % len(ids)]
        app.recargar_sonidos()
        cfg.guardar()
        if len(ids) == 1:
            app.decir(tr("No hay ningún pack instalado. Copia la carpeta de un pack dentro de data, sonidos."), True)
            return
        app.mez.sonar("puerta_coche", cat="interfaz", vol=0.8)          # una muestra, para oír el cambio

    def adultos(d):
        from . import menus_adultos
        menus_adultos.alternar_modo(app)

    def mando():
        from . import menus_extra
        menus_extra.opciones_mando(app)

    from . import i18n

    def idioma_txt():
        if cfg["idioma"] == "auto":                       # cada idioma, en el tuyo y en el suyo: «vietnamita (Tiếng Việt)»
            t = tr('Idioma: automático, el de tu sistema ({nombre})').format(nombre=i18n.idioma_en(i18n.elegir("auto")))
        else:
            t = tr('Idioma: {nombre}').format(nombre=i18n.nombre_en(cfg["idioma"]))
        return t + (tr(". Se aplica al volver a abrir el juego") if i18n.elegir(cfg["idioma"]) != i18n.actual() else "")

    def cambiar_idioma(d):
        ops = ["auto"] + list(i18n.disponibles())
        actual = cfg["idioma"] if cfg["idioma"] in ops else "auto"
        cfg["idioma"] = ops[(ops.index(actual) + d) % len(ops)]
        cfg.guardar()

    secciones = [
        Opcion(idioma_txt, ajuste=cambiar_idioma,
               ayuda=tr("Cámbialo con las flechas izquierda y derecha. Automático usa el idioma de tu sistema: si es español, el juego va en español; "
                        "si no, en ese idioma si está instalado, y si no, en inglés. El cambio se aplica al volver a abrir el juego. "
                        "Los idiomas nuevos se instalan desde Opciones, Actualizaciones, Componentes, o copiando su carpeta en data, idiomas.")),
        seccion(tr("Sonido y música"), [
            vol("vol_maestro", tr("Volumen general"), tr("Sube o baja a la vez todo el sonido del juego, de diez en diez. La voz de tu lector de pantalla no cambia. Al cambiarlo suena una muestra. Cámbialo con las flechas izquierda y derecha.")), vol("vol_efectos", tr("Volumen de efectos"), tr("Los sonidos de lo que pasa a tu alrededor: motores, pasos, disparos, puertas y golpes. Al cambiarlo suena una muestra. Cámbialo con las flechas izquierda y derecha.")), vol("vol_ambiente", tr("Volumen del ambiente"), tr("El fondo de cada sitio: la ciudad, el mar, los pájaros, la lluvia, los truenos y las campanas. Al cambiarlo suena una muestra. Cámbialo con las flechas izquierda y derecha.")),
            vol("vol_interfaz", tr("Volumen de avisos y balizas"), tr("Los sonidos de los menús, del dinero, de los mensajes y de las misiones, y las balizas. Al cambiarlo suena una muestra. Cámbialo con las flechas izquierda y derecha.")),
            vol("vol_senales", tr("Volumen de las señales de ayuda"), tr("Baliza del GPS, radar, tono de puntería, sensor de proximidad, semáforos y el sonido propio de cada lugar. "
                "Se aplica además del volumen de su grupo: bájalo si las señales te tapan lo demás, o baja lo demás y deja este al máximo. Cámbialo con las flechas izquierda y derecha.")),
            vol("vol_musica", tr("Volumen de la radio y la música"), tr("La radio de los vehículos, el reproductor con auriculares y la música de ambiente. Al cambiarlo suena una muestra. Cámbialo con las flechas izquierda y derecha.")),
            Opcion(lambda: tr('La radio, al bajarte del vehículo: {v}').format(v=(tr('se queda en pausa y sigue luego por donde iba') if cfg['radio_pausa'] else tr('sigue sonando sin ti, como una emisora de verdad'))),
                   ajuste=lambda d: (cfg.__setitem__("radio_pausa", not cfg["radio_pausa"]), setattr(app.radio, "pausa", bool(cfg["radio_pausa"]))),
                   ayuda=tr("Vale para todas las emisoras y para Mi música. En pausa: al bajarte, la canción se detiene, y al subir a cualquier vehículo sigue justo donde se quedó; "
                         "cada emisora recuerda la suya, así que al volver a una que dejaste, sigue con su canción. Sin pausa: la emisora sigue su curso aunque no la oigas, "
                         "y al volver te la encuentras más adelante. Las canciones de menos de un minuto y medio empiezan siempre desde el principio.")),
            si_no("radio_coches", tr("En un servidor, oír la radio de los vehículos de otros jugadores"),
                  tr("Con sí, cuando tienes cerca el vehículo de otro jugador que lleva puesta una emisora del juego, la oyes floja y apagada, desde donde está su vehículo, "
                  "y se pierde al alejarte. Solo suena si tú no llevas tu propia radio puesta, y solo una a la vez. Nunca se oye la música propia de nadie: de «Mi música» "
                  "no sale nada de tu ordenador, solo se cuenta qué emisora del juego llevas. Con no, no oyes la radio de nadie; los demás siguen oyendo la tuya.")),
            Opcion(tr("Mi música: cómo poner tus canciones en la radio, paso a paso"), lambda: mi_musica(app),
                   ayuda=tr("Los cuatro pasos para oír tu propia música en la radio de los vehículos, y la opción que abre la carpeta donde se copian las canciones.")),
            Opcion(lambda: tr('Abrir la carpeta de mi música: {_canciones_txt}').format(_canciones_txt=(_canciones_txt(app))), lambda: abrir_mi_musica(app),
                   ayuda=tr("Abre en el Explorador de Windows la carpeta donde se copian tus canciones, y la crea si no existe. Lo que copies ahí, en mp3, ogg, flac o wav, "
                         "suena en la emisora Mi música, que está en la radio de cualquier vehículo: se cambia de emisora con la R. No hace falta cerrar el juego: "
                         "al volver a sintonizar Mi música ya están las canciones nuevas.")),
            si_no("musica_ambiente", tr("Música de ambiente"), tr("Música de fondo que cambia con la situación. Se calla sola cuando pones la radio en un vehículo y vuelve cuando la apagas o te bajas.")),
            vol("vol_ambiente_musical", tr("Volumen de la música de ambiente"), tr("Respecto a la radio. Cámbialo con las flechas izquierda y derecha.")),
            Opcion(lambda: tr('Pack de sonidos: {nombre_pack}').format(nombre_pack=(nombre_pack())), ajuste=cambiar_pack,
                   ayuda=tr("Elige con las flechas izquierda y derecha entre los sonidos por defecto y los packs, que son las subcarpetas de data, sonidos. Se aplica al momento. Los sonidos que el pack no trae siguen sonando con el original.")),
            Opcion(lambda: tr('Motor de sonido: {v}').format(v=(tr('envolvente, binaural') if cfg['motor_sonido'] == 'envolvente' else tr('clásico'))) +
                   (tr(". Se aplicará al volver a abrir el juego") if (cfg["motor_sonido"] == "envolvente") != bool(getattr(app.mez, "envolvente", False)) else ""),
                   ajuste=lambda d: cfg.__setitem__("motor_sonido", "clasico" if cfg["motor_sonido"] == "envolvente" else "envolvente"),
                   ayuda=tr("El motor envolvente usa sonido binaural: con auriculares se distingue si algo suena delante o detrás, y no solo a izquierda o derecha. "
                         "Además mezcla el sonido fuera del programa, así que no da tirones cuando hay muchos sonidos a la vez. El clásico es el de siempre. "
                         "El cambio se aplica al cerrar y volver a abrir el juego. En ordenadores con procesador antiguo, y con el sonido mono activado, se usa siempre el clásico.")),
            Opcion(lambda: tr('Sonido holgado, para equipos donde el audio da chasquidos o cortes: {v}').format(v=(tr('sí') if cfg['sonido_holgado'] else tr('no'))) +
                   (tr(". Se aplicará al volver a abrir el juego") if bool(cfg["sonido_holgado"]) != bool(getattr(app.mez, "holgado", False)) and not getattr(app.mez, "envolvente", False) else ""),
                   ajuste=lambda d: cfg.__setitem__("sonido_holgado", not cfg["sonido_holgado"]),
                   ayuda=tr("Con el motor clásico, el juego prepara el sonido en trozos más grandes. Los sonidos llegan unas centésimas de segundo más tarde, "
                         "pero dejan de oírse chasquidos, cortes o tartamudeos en ordenadores justos de potencia o con tarjetas de sonido delicadas. "
                         "Pruébalo si el audio te da tirones; otra solución es el motor envolvente. El cambio se aplica al cerrar y volver a abrir el juego.")),
            si_no("eco_lugares", tr("Eco según el lugar, solo con el motor envolvente"),
                  tr("Con el motor envolvente, los sonidos del mundo llevan el eco del sitio donde estás: poco en el campo y en la playa, algo en la calle, más entre naves, largo en la montaña y corto y cercano dentro de un local. "
                  "Además, lo que vuela suena por encima, y si vuelas tú, la ciudad suena por debajo. Con el motor clásico esta opción no hace nada."),
                  al_cambiar=app.aplicar_volumenes),
            si_no("sonido_mono", tr("Sonido mono, lo mismo por los dos oídos"),
                  tr("Para quien oye por un solo oído o usa un solo auricular. Se pierde la sensación de izquierda y derecha: oriéntate con el radar, el escáner y el GPS hablado."),
                  al_cambiar=app.aplicar_volumenes),
            si_no("atenuar_al_hablar", tr("Bajar el ambiente y la música mientras habla la voz"),
                  tr("Cada vez que el juego dice algo, el sonido de fondo y la música bajan un momento para que se entienda mejor. Los efectos importantes, como motores, pasos y disparos, no bajan."),
                  al_cambiar=app.aplicar_volumenes),
            si_no("igualar_volumen", tr("Igualar el volumen de los sonidos cambiados"), tr("Lleva cada sonido de un pack, o que hayas sustituido a mano, al mismo nivel que tenía el original, para que ninguno quede demasiado fuerte ni demasiado flojo."), al_cambiar=app.recargar_sonidos),
            Opcion(tr("Ajustar el volumen de cada sonido"), lambda: volumen_sonidos(app), ayuda=tr("Todos los sonidos del juego, por los mismos grupos que en Aprender los sonidos, y con un buscador. Intro los hace sonar y las flechas izquierda y derecha suben o bajan ese sonido en concreto, del 30 al 200 por ciento. Se suma a los volúmenes generales de arriba: primero se aplica el de cada sonido y encima el de efectos, ambiente o avisos. Dice cuántos tienes cambiados y deja restablecer uno, un grupo o todos.")),
        ], tr("Volúmenes, música de ambiente y packs de sonidos.")),
        seccion(tr("Movimiento y conducción"), [
            lista("movimiento", tr("Movimiento a pie"), tr("En modo brújula el oído mira siempre al norte. Con giros, el sonido gira contigo.")),
            lista("conduccion", tr("Conducción"), tr("También se cambia durante el juego con F2.")),
            si_no("correr_alternar", tr("Correr con una pulsación, sin mantener la tecla"),
                  tr("Con sí, una pulsación de Mayúsculas te pone a correr y otra te devuelve al paso, sin tener que mantenerla. Con no, corres mientras la mantienes pulsada.")),
            si_no("frenada_auto", tr("Frenada automática ante el tráfico"), tr("En conducción asistida, el coche frena solo para no chocar con el vehículo de delante. Mantén A para adelantarlo.")),
            si_no("viajes_trayecto", tr("Viajes en taxi y en autobús con trayecto"),
                  tr("Con sí, al coger un taxi o un autobús se oye el viaje durante un rato: el motor, la calzada y la radio. Dura entre doce segundos y un minuto según la distancia, y con Intro llegas ya. Con no, llegas al momento.")),
            si_no("vuelo_real", tr("Vuelo real: altura, y travesías de verdad entre localidades"),
                  tr("Con sí, un helicóptero o una avioneta despegan, tienen altura, que se sube con la D y se baja con la A, y aterrizan con la F; y al salir volando de una localidad, o con Intro en un helipuerto o un aeropuerto, "
                  "se hace una travesía de verdad hasta otra, con rumbo, altitud, viento, torre y aproximación. Hay piloto automático y se puede acelerar. Con no, es como antes: se vuela siempre a la misma altura y "
                  "se cambia de localidad de un salto desde un helipuerto. La explicación entera está en cualquier helipuerto o aeropuerto, en Cómo funciona volar.")),
            si_no("vuelo_asistido", tr("Aterrizaje asistido en las travesías"),
                  tr("Con sí, al acercarte al campo de destino el aparato baja y se encara solo, aunque pilotes a mano. Con no, lo haces tú: bajas a la altitud que dice la torre y mantienes en el centro los chasquidos de alineación; "
                  "si entras alto o torcido, la torre te manda dar otra vuelta, y a la segunda te guía ella. Se cambia también durante el vuelo, en el menú de vuelo.")),
            si_no("vuelo_combustible", tr("Las aeronaves gastan combustible"),
                  tr("Con el vuelo real. Con sí, cada aparato tiene su depósito, que se llena en helipuertos, aeropuertos y aeródromos; el juego avisa en la reserva, y si se acaba, el motor se para y planeas. "
                  "Con no, el depósito no se gasta nunca.")),
            si_no("piloto_gps", tr("Piloto del GPS, el coche va solo hasta el destino"),
                  tr("Con un destino marcado en el GPS y en conducción asistida, el coche conduce solo: acelera, frena, gira, espera en los semáforos y se detiene al llegar. "
                  "Con cualquier flecha o el espacio mandas tú. Se activa también con la tecla Y al volante.")),
            _estilo_piloto(cfg),
            si_no("sonar", tr("Sensor de proximidad al volante"), tr("Al volante, pita cuando tienes un obstáculo cerca: más agudo cuanto más cerca, y por el lado en que está. Al activarlo se oye una muestra."),
                  al_cambiar=lambda: cfg["sonar"] and app.mez.sonar("sonar", cat="interfaz", vol=0.6)),
        ], tr("Cómo caminas y cómo conduces.")),
        seccion(tr("Orientación y avisos"), [
            lista("direcciones", tr("Formato de las direcciones"), tr("Cómo se dicen las direcciones del radar y del GPS.")),
            si_no("gps_voz", tr("Indicaciones habladas del GPS"),
                  tr("Con sí, mientras sigues un destino marcado en el GPS, el juego te dice cuándo y hacia dónde girar. Con no, no dice nada por el camino y solo te guía la baliza, si la tienes activada.")),
            si_no("baliza", tr("Baliza sonora del GPS"), tr("Un toque que suena desde la dirección que tienes que seguir. Al activarla se oye una muestra."),
                  al_cambiar=lambda: cfg["baliza"] and app.mez.sonar("baliza", cat="interfaz", vol=0.8)),
            si_no("anunciar_cruces", tr("Anunciar los cruces"),
                  tr("Con sí, a pie suena un toque al llegar a un cruce y se dice dónde estás; al volante se avisa del cruce que viene y de con qué calle es. Con no, los cruces no se anuncian.")),
            si_no("anunciar_lugares", tr("Anunciar los lugares al llegar a su puerta"),
                  tr("Con sí, al llegar a la puerta de un lugar se dice cuál es y, si allí empieza una misión, que puedes empezarla con Intro. Con no, no se dice nada al llegar.")),
            si_no("anunciar_barrios", tr("Anunciar los cambios de barrio"),
                  tr("Con sí, cada vez que pasas a otro barrio se dice su nombre. Con no, no se dice, y la tecla N te dice dónde estás cuando quieras.")),
            si_no("describir_zonas", tr("Describir cada barrio la primera vez que entras"),
                  tr("La primera vez que pisas un barrio, además de su nombre, el juego dice cómo es. Las demás veces solo dice el nombre. La tecla N lo repite cuando quieras.")),
            si_no("anunciar_superficie", tr("Anunciar los cambios de suelo"), tr("Dice acera, calzada, césped o arena cada vez que cambia el suelo que pisas.")),
            si_no("localizador", tr("Sonido propio de cada lugar cercano"), tr("Cada tipo de lugar suena de una manera cuando pasas cerca. Al activarlo se oye una muestra, la de un bar. En el menú principal, Aprender los sonidos los tiene todos."),
                  al_cambiar=lambda: cfg["localizador"] and app.mez.sonar("lugar_bar", cat="interfaz", vol=0.8)),
            si_no("semaforos", tr("Semáforos acústicos en los cruces"), tr("En los cruces con semáforo se oye si puedes cruzar. Al activarlo se oye una muestra."),
                  al_cambiar=lambda: cfg["semaforos"] and app.mez.sonar("semaforo_pio", cat="interfaz", vol=0.8)),
        ], tr("GPS, baliza, anuncios y sonidos de orientación.")),
        seccion(tr("Combate y dificultad"), [
            lista("dificultad", tr("Dificultad"), tr("Cambia el daño que recibes.")),
            lista("punteria", tr("Ayuda de puntería"),
                  tr("Completa: al disparar se apunta sola al enemigo más cercano que esté a tu alcance. Manual: tienes que estar encarado hacia el enemigo para darle.")),
            si_no("fuego_amigo", tr("Fuego amigo: puedes herir a tu perro, a tus guardaespaldas y a tu banda"),
                  tr("Con sí, que es lo realista, tus balas y tus explosivos les hacen daño: el perro te coge miedo hasta que hagáis las paces, y tu gente aguanta dos avisos antes de volverse contra ti. "
                  "Con no, no se les puede apuntar ni herir, ni por accidente.")),
            si_no("aviso_acierto", tr("Aviso al dar en el blanco"), tr("Cada vez que aciertas a un enemigo o a un vehículo suena un toque agudo y el mando da un golpe corto. Al fijar un objetivo con la Q, el mando también avisa."),
                  al_cambiar=lambda: cfg["aviso_acierto"] and app.mez.sonar("tono_objetivo", cat="interfaz", vol=0.45, tono=2.0)),
            lista("escolta_misiones", tr("Las misiones se ajustan a tu escolta"),
                  tr("Con toda tu banda y dos guardaespaldas, las misiones se hacían solas. Con esta opción, cuando llegas a una misión con gente a tu lado, te esperan algunos enemigos más, "
                  "que aguantan más y apuntan mejor, según cuántos lleves. El primero de los tuyos no cuenta, y hay un tope para que ninguna misión se vuelva imposible. "
                  "Moderado, que es lo de serie: como mucho la mitad más de enemigos. Fuerte: como mucho el doble. No: te esperan siempre los mismos. "
                  "No cuenta en los tutoriales ni en un servidor en línea. El juego te avisa cuando la oposición sube por tu escolta.")),
            si_no("ayuda_persecucion", tr("Ayuda en las persecuciones"),
                  tr("Para las misiones en las que hay que perseguir un vehículo o seguir a alguien a pie. Con sí, que es lo de serie, el juego te dice más a menudo por dónde va, "
                  "con la calle y hacia dónde tira, y te canta cada giro; quien huye afloja antes si te quedas atrás, tienes algo más de tiempo cuando hay un límite, "
                  "y a pie se tarda un poco más en perder de vista a quien sigues. Es una ayuda suave: la persecución sigue habiendo que hacerla. "
                  "Con no, todo va como siempre: menos avisos y sin esas ventajas. No cuenta en un servidor en línea.")),
            si_no("mod_enemigos", tr("Modificador: enemigos más duros"), tr("Los enemigos de las misiones aguantan la mitad más. Cada modificador activo te hace ganar experiencia un veinticinco por ciento más deprisa.")),
            si_no("mod_policia", tr("Modificador: policía más severa"), tr("Cada delito cuenta la mitad más, así que la búsqueda sube antes. Cada modificador activo te hace ganar experiencia un veinticinco por ciento más deprisa.")),
            si_no("mod_dinero", tr("Modificador: misiones peor pagadas"), tr("Las misiones pagan la mitad. Cada modificador activo te hace ganar experiencia un veinticinco por ciento más deprisa.")),
            si_no("multas", tr("Multa o soborno cuando te cogen por poco"),
                  tr("Con uno o dos niveles de búsqueda y dinero suficiente, cuando un agente te coge puedes pagar la multa en el acto, intentar sobornarle o dejarte detener. Con no, te detienen siempre, como antes.")),
            si_no("sucesos", tr("Sucesos callejeros al azar"), tr("Atracos, pandilleros y maletines perdidos que aparecen de vez en cuando por la calle.")),
            si_no("invulnerable", tr("Asistencia: no recibir daño"), tr("Para explorar sin preocuparte de nada.")),
            si_no("sin_policia", tr("Asistencia: sin policía"), tr("Los delitos no cuentan y nadie te persigue.")),
            si_no("vida_realista", tr("Vida realista: hambre, sed, sueño e higiene"), tr("Hay que comer, beber, dormir y lavarse. Con hambre, con sed o con sueño vas más despacio y apuntas peor, y si los ignoras pierdes salud. "
                  "Se bebe en bares, tiendas y en tu cocina; la ducha, en tu casa o en un hotel. Ir sucio baja el ánimo. La tecla V te dice cómo estás, y Mayúsculas V, solo eso. "
                  "Además de comer fuera o pedir a domicilio, puedes hacer la compra en las tiendas de comida, guardarla en la cocina de tu casa y cocinar: es lo que más alimenta y lo más barato.")),
            si_no("averias", tr("Averías: pinchazos y revisiones"),
                  tr("Cada vehículo cuenta los kilómetros que rueda. De tarde en tarde pincha una rueda: se oye, y el coche no pasa de media velocidad hasta que la cambias, "
                  "con una de repuesto desde el móvil, en un taller o llamando a la asistencia. Cada cierto número de kilómetros toca revisión en un taller; si no la pasas, los frenos van a peor. "
                  "La tecla V, al volante, dice los kilómetros y lo que le pasa.")),
            si_no("normas_trafico", tr("Normas de tráfico: multas y carné por puntos"),
                  tr("Saltarte un semáforo en rojo o ir muy por encima del límite cuesta una multa y puntos del carné, pero solo si te ve la policía. "
                  "Sin puntos te retiran el carné, y conducir delante de un agente pasa a ser un delito. Los puntos se recuperan con un curso en una academia. "
                  "Con la sirena puesta, o cuando ya te buscan, no hay multas. Los semáforos cuentan en conducción asistida. La tecla V dice los puntos que te quedan.")),
            si_no("combustible", tr("Combustible: los vehículos gastan y hay que repostar"),
                  tr("Cada coche, moto o camión tiene su depósito y gasta al rodar, más cuanto más deprisa. Avisa al entrar en reserva; con el depósito vacío, el motor se para. "
                  "Se reposta en las gasolineras sin bajarte del vehículo, con un bidón comprado en ellas o llamando a la asistencia en carretera desde el móvil, en Servicios. "
                  "La tecla V te dice cuánto queda. No cuenta en los barcos, en lo que vuela, en las bicicletas ni en los vehículos de las misiones.")),
        ], tr("Dificultad, puntería y asistencias.")),
        seccion(tr("La calle: gente, policía y bandas"), [
            si_no("defensa_propia", tr("Defensa propia: defenderte de quien te ataca primero no es delito"),
                  tr("Con sí, si un atracador, un pandillero o cualquiera te ataca sin que tú le hayas tocado antes, dispararle o tumbarle no cuenta como delito, ni tampoco parar a los de un suceso callejero. "
                  "Además, si hay agentes cerca o llega una patrulla, van también a por él y no solo a por ti. No vale para los enemigos de las misiones ni para quien has atacado tú primero, "
                  "y los explosivos siguen siendo delito. Con no, todo es como antes: cualquier disparo y cualquier baja cuentan.")),
            si_no("frases_reacciones", tr("Decir cuándo la gente huye o se aparta"),
                  tr("Los gritos y las quejas de la gente, con voz de hombre o de mujer, se oyen siempre. Con sí, además el juego dice con palabras quién sale corriendo o se aparta y hacia dónde, "
                  "como mucho una vez cada pocos segundos; si son varios, lo dice de una vez. Con no, solo se oyen.")),
            lista("charla_peatones", tr("Gente que habla al pasar"),
                  tr("Al pasar a pie o despacio junto a dos personas, a veces se oye lo que van diciendo: una frase suelta y, a veces, la respuesta. Nunca en mitad de una persecución, de una pelea o de una escena. "
                  "Elige cuánto: nunca, pocas veces, que es una cada dos o tres minutos como mucho, de vez en cuando, o a menudo.")),
            si_no("soltar_municion", tr("Los enemigos caídos sueltan munición"),
                  tr("Con sí, un enemigo que llevaba un arma de fuego igual que una de las tuyas deja a veces en el suelo munición de esa arma. Se recoge sola al pasar a pie por encima, como el dinero, "
                  "y se oye un cargador. Con no, solo sueltan dinero, como antes.")),
            si_no("soltar_armas", tr("Dificultad: los enemigos caídos sueltan a veces su arma"),
                  tr("Con sí, un enemigo caído deja a veces en el suelo el arma que llevaba, si tú no la tienes: te la quedas al pasar por encima. Hace el juego más fácil y la armería menos necesaria, "
                  "por eso viene apagada. En un servidor en línea no cuenta.")),
            si_no("patrullas_calle", tr("Patrullas de policía circulando por la calle"),
                  tr("Con sí, algún coche patrulla hace su ronda por las calles aunque nadie te busque, como en los servidores en línea. Ven los delitos que cometas cerca, y con las normas de tráfico activadas "
                  "son quienes ponen las multas. Si te atacan y hay una cerca, acude. Con no, la policía solo aparece cuando te busca. En un servidor con policía común las lleva el servidor.")),
            si_no("ambulancias", tr("Ambulancias que acuden cuando hay heridos"),
                  tr("Con sí, un rato después de un tiroteo o de un atropello llega una ambulancia con la sirena, se arrima a la acera, los sanitarios atienden y se va. Es ambiente: no te persigue, no te atropella y no cambia nada. "
                  "Solo jugando en solitario.")),
            si_no("helicoptero_policia", tr("Helicóptero de la policía con el nivel de búsqueda más alto"),
                  tr("Con sí, al llegar al nivel 5 acude un helicóptero: se le oye llegar y dar vueltas por encima de ti, y te habla por el altavoz. Mientras te tenga localizado no puedes despistar a la policía. "
                  "Te pierde si te pegas a una fachada unos segundos o entras en un edificio, y no te reconoce si cambias de vehículo sin que te vea. Se le puede derribar con un rifle o un explosivo, "
                  "pero entonces la policía tarda el doble en olvidarte y el helicóptero se paga al ser detenido. Hace el nivel 5 bastante más difícil: por eso viene apagado. "
                  "En un servidor con policía común no sale.")),
            si_no("guerra_calle", tr("Modo: guerra de barrios en la calle"),
                  tr("Con no, que es lo de siempre, los barrios se conquistan y se defienden desde el móvil, en Territorios. Con sí, cada barrio de las ciudades es de una banda y los suyos andan por sus calles. "
                  "Un barrio se conquista yendo allí: al tumbar a dos de los suyos, o plantándoles cara desde el móvil cuando ya estás dentro, la banda viene a por ti en tres oleadas. Tu propia banda acude a ayudarte. "
                  "No hay que salir del barrio hasta acabar. Y cuando ataquen un barrio tuyo, lo defiendes entrando en él. En un servidor en línea no cuenta: allí los barrios son de las bandas de los jugadores.")),
            lista("reconquista", tr("Las bandas intentan reconquistar tus barrios"),
                  tr('Jugando sin conexión, conquistar no es el final: cuando tienes todos los barrios de una ciudad, o muchos sin tenerlos todos, las bandas vencidas se rehacen y, pasados unos días de calma, intentan recuperarlos. Te avisan del asalto y tienes unas horas para ir a defender el barrio en persona o para enviar a tu gente desde el móvil; si no haces nada, lo pierdes. Te preparas en el móvil, en Territorios, Defensa de tus barrios: guardias, refuerzos, informantes, treguas y golpes a sus escondites. Elige cuánto aprietan: apagado, y nadie te los disputa de esta manera; tranquilo, con pocos asaltos y {entero} horas para responder; normal, que es lo de serie, con {entero2} horas; o duro, con asaltos más seguidos, más fuertes y {entero3} horas. Nunca hay dos asaltos a la vez. En un servidor en línea y jugando con amigos no ocurre.').format(entero=(REC.entero('plazo_tranquilo')), entero2=(REC.entero('plazo_normal')), entero3=(REC.entero('plazo_duro')))),
            si_no("gente_actua", tr("La gente con la que hablas también actúa"),
                  tr("Con sí, después de hablar contigo una persona puede hacer algo por su cuenta, según su carácter y la confianza que te tenga: acompañarte un rato si le has caído bien, "
                  "darte un puñetazo si insistes después de haberla ofendido, o denunciarte si la insultas. Lo decide el juego, sin inteligencia artificial. "
                  "Con no, la gente solo habla, como antes. Pedir un favor y proponer a alguien que se una a tu banda están siempre en la conversación, porque eso lo eliges tú.")),
            si_no("oficio_policia", tr("Modo: poder trabajar de policía"),
                  tr("Con sí, en las comisarías puedes ingresar en la policía y, ya de agente, empezar un turno: te dan un coche patrulla y la emisora te pasa avisos de robos, peleas, "
                  "conductores temerarios y persecuciones. Los resuelves dando el alto, reduciendo, deteniendo o multando, cobras por cada uno y asciendes. De servicio, la fuerza contra los sospechosos no es delito; "
                  "cualquier otro delito te cuesta un apercibimiento o la placa. Con no, que es lo de siempre, nada de esto aparece. Solo jugando en solitario.")),
        ], tr("Cómo reacciona la gente, qué hace la policía cuando no te busca, cómo se pelea por los barrios y el oficio de policía.")),
        seccion(tr("Vida, reputación y consecuencias"), [
            lista_c("consecuencias", tr("Nivel de consecuencias"),
                    tr('Cuánto pesa en el mundo cómo te ven los vecinos y la calle. Apagado: todo como en versiones anteriores; el prestigio solo cuenta en la paga, el banco y la policía. Suave, que es lo de serie: en las tiendas te rebajan si te aprecian, hasta un {entero} por ciento, y te fían; donde te evitan te cobran algo más; los vecinos a veces encubren una falta pequeña; un negocio atendido rinde más y uno abandonado, algo menos; sin fama ni escolta, alguna banda puede pedir dinero a tu negocio; y si llevas doble vida, lo que se va sabiendo puede acabar en el periódico. Normal: lo mismo con toda su fuerza, y con mala fama o antecedentes la policía te para de vez en cuando. Exigente: todo pesa la mitad más y, donde te evitan, hay comercios que no te atienden. Lo que eliges tú, como un contrato fijo, un título, un crédito o mejorar un negocio, está siempre, con cualquier nivel. En un servidor en línea no cuenta.').format(entero=(HON.entero('rebaja_ejemplar')))),
            si_no("impuestos_facturas", tr("Impuestos y facturas"),
                  tr('Con sí, cada {entero} días te cobran la luz y el agua de tus casas, su contribución y un impuesto sobre lo que han dado tus negocios, y de vez en cuando pasa una inspección por alguno. Son cantidades pequeñas, se avisan {entero2} días antes, se cobran solas y se pueden consultar en el móvil. Si no llega el dinero, queda a deber con recargo; a los {entero3} impagos te embargan parte de lo que ganes hasta saldarlo, pero nunca te quitan nada de golpe. Una partida ya empezada tiene {entero4} días de gracia. Con no, no hay facturas, impuestos ni inspecciones, como antes.').format(entero=(HON.entero('cobro_dias')), entero2=(HON.entero('aviso_dias')), entero3=(HON.entero('impagos_embargo')), entero4=(HON.entero('gracia_dias')))),
            si_no("antecedentes", tr("Antecedentes penales"),
                  tr('Con sí, cada detención y cada multa que pagas a un agente queda en tu ficha, más grave cuanto más te buscaban. Los antecedentes cierran los empleos de confianza, el ingreso en la policía y, si son graves, los créditos; y cada delito cuenta algo más mientras estés fichado. Caducan solos: a los {entero} días los leves, a los {entero2} los medios y a los {entero3} los graves, y se atenúan con servicios a la comunidad o con un abogado. Lo que hiciste antes de esta versión no cuenta. Con no, no se apunta nada, como antes.').format(entero=(HON.entero('caduca_leve')), entero2=(HON.entero('caduca_media')), entero3=(HON.entero('caduca_grave')))),
            si_no("pareja_familiar", tr("Vida sentimental apta para todos"),
                  tr("Con sí, aunque el contenido para adultos esté desactivado, en el móvil aparece Vida sentimental: personas a las que conocer, citas, regalos, ser pareja, prometeros, "
                  "vivir juntos y una boda sencilla. Sin nada de contenido para adultos. Con no, las relaciones solo existen con el contenido para adultos activado, como antes.")),
            si_no("vida_en_persona", tr("La vida social se vive en persona"),
                  tr("Con sí, las personas de tu vida social se tratan cara a cara: una cita, un regalo en mano, un beso, la noche o pedir salir, donde está esa persona, "
                  "en vuestra casa si vivís juntos, o mientras va contigo. Desde el móvil se llama, se escribe, se queda en un sitio a una hora, se manda un regalo a domicilio, "
                  "se da dinero y se rompe. Una cita se vive yendo juntos al sitio. Con no, todo se hace desde el móvil, como antes.")),
            Opcion(lambda: tr("Horarios: ") + {"apagado": tr("no, todo abre siempre y cada persona está siempre en su sitio, como antes"),
                                           "gente": tr("la gente: cada persona de tu vida social está en su sitio en sus horas, y libra un día a la semana"),
                                           "todo": tr("la gente y los locales: además, cada local abre y cierra a sus horas y cierra algún día")}[cfg["horarios"]],
                   ajuste=lambda d: cfg.__setitem__("horarios", OPCIONES["horarios"][(OPCIONES["horarios"].index(cfg["horarios"]) + d) % 3]),
                   ayuda=tr("Cámbialo con las flechas. Con horarios, la ficha de cada persona dice cuándo está en su sitio y qué día libra; fuera de esas horas, llámale o proponle quedar. "
                         "Con los locales, al llegar a uno cerrado el juego dice cuándo abre. Lo que pide una misión o un trabajo en curso está siempre abierto, y tus casas y negocios también. "
                         "El primer día de la partida es lunes.")),
        ], tr("Ser buena persona, delincuente o las dos cosas: cuánto pesan el prestigio y la fama, los impuestos, los antecedentes y las relaciones.")),
        Opcion(tr("Personas e inteligencia artificial"), lambda: __import__("juego.menus_charla", fromlist=["x"]).opciones_ia(app),
               ayuda=tr("Cómo contestan las personas de la calle cuando les escribes lo que quieres: con el motor del juego o con una inteligencia artificial.")),
        Opcion(tr("Teclado: cambiar las teclas"), lambda: opciones_teclado(app),
               ayuda=tr("Elige con qué tecla se hace cada cosa mientras juegas. Sirve si tu teclado es distinto, si juegas con una mano o si alguna tecla choca con tu lector de pantalla.")),
        Opcion(tr("Mando"), mando, ayuda=tr("Mandos de Xbox y PlayStation: ver qué hace cada botón, reasignarlos y activar la vibración.")),
        seccion(tr("Jugar en línea"), [
            si_no("reconectar", tr("En un servidor, esperar y volver a entrar solo si se corta o se reinicia"),
                  tr("Con sí, cuando el servidor en el que juegas se reinicia para actualizarse, o se corta la conexión, el juego no te devuelve al menú: se queda esperando, "
                  "con tu partida tal cual, prueba a entrar cada pocos segundos y, cuando el servidor vuelve, sigues donde estabas: mismo sitio, mismo vehículo, "
                  "misma salud, mismas armas y misma misión. Entra con tu identidad de siempre, sin pedirte nada. Escape deja de esperar. "
                  "Con no, como antes: vuelves al menú principal y entras tú a mano.")),
            numero("reconectar_minutos", tr("Minutos que se espera como mucho a que vuelva el servidor"), 1, 120, 1,
                   tr("De 1 a 120. Pasado ese tiempo sin que el servidor vuelva, el juego deja de intentarlo, lo dice y sale al menú principal. De serie, 10.")),
        ], tr("Qué hace el juego cuando el servidor en el que juegas se reinicia o se corta la conexión.")),
        seccion(tr("Voz"), [
            si_no("voz_sapi", tr("Usar la voz de Windows en lugar del lector de pantalla"),
                  tr("Con sí, el juego habla con la voz de Windows, que se ajusta justo debajo. Con no, habla tu lector de pantalla, y si no tienes ninguno abierto, la voz de Windows. Se aplica al momento."), al_cambiar=lambda: app.voz.cambiar(cfg["voz_sapi"])),
            numero("voz_velocidad", tr("Velocidad de la voz de Windows"), -10, 10, 1, tr("De menos diez a diez. Solo afecta a la voz de Windows; si usas un lector de pantalla, la velocidad se cambia en el lector.")),
            numero("voz_tono", tr("Tono de la voz de Windows"), -10, 10, 1, tr("De menos diez, más grave, a diez, más agudo. Solo afecta a la voz de Windows.")),
            numero("voz_volumen", tr("Volumen de la voz de Windows"), 0, 100, 10, tr("De cero a cien. Solo afecta a la voz de Windows.")),
            lista("detalle_voz", tr("Cuánto explica el juego al hablar"),
                  tr("Con poco, se quitan las frases que solo recuerdan qué tecla pulsar. Con mucho, en los menús se lee además la explicación de cada opción, sin tener que pulsar F1. Normal es lo de siempre.")),
            si_no("historial_al_final", tr("Al llegar un mensaje nuevo, el historial salta al final"),
                  tr("El historial de mensajes se repasa con Re Pág y Av Pág; Control Re Pág va al primero y Control Av Pág al último. Con sí, cada mensaje nuevo te lleva al final, "
                  "como siempre. Con no, si estás repasando, sigues donde estabas aunque lleguen mensajes, y vas al último con Control Av Pág.")),
            si_no("menu_posicion", tr("Decir la posición en los menús, por ejemplo 3 de 9"),
                  tr("Al moverte por un menú, después de cada opción dice cuál es y cuántas hay.")),
            si_no("voces_grabadas", tr("Voces en las escenas"),
                  ayuda_=tr("Con sí, las escenas de las misiones suenan con una voz distinta para cada personaje, en lugar de leerlas tu lector de pantalla, y el texto sigue saliendo en braille. "
                         "Te llaman por el nombre del personaje con el que juegas y te hablan en masculino o en femenino, según hayas elegido. La frase que no tenga voz la dice tu lector. "
                         "Con no, todo lo dice tu lector de pantalla o, si no usas lector, la voz de Windows.")),
            si_no("voces_propias", tr("Generar las voces de tu propio personaje"),
                  ayuda_=tr("Solo cuenta si juegas con un personaje hecho por ti. Con sí, las frases de la historia que dicen tu nombre se generan en tu ordenador, con las voces de los personajes, la primera vez que juegas con ese nombre: "
                         "unos segundos de espera al empezar y el resto mientras juegas. Con no, o si tu equipo no puede con el generador, esas frases las dice tu lector de pantalla. ") + __import__("juego.vozgen", fromlist=["x"]).motivo()),
        ], tr("Con qué voz habla el juego.")),
        Opcion(tr("Registro para informar de fallos"), lambda: __import__("juego.menus_registro", fromlist=["x"]).opciones(app),
               ayuda=tr("El juego anota lo que pasa en cada sesión para poder encontrar los fallos. Aquí ves dónde está, qué contiene y cómo enviarlo.")),
        Opcion(tr("Actualizaciones"), lambda: __import__("juego.menus_actualizar", fromlist=["x"]).opciones(app),
               ayuda=tr("Buscar una versión nueva del juego e instalarla, y elegir de dónde se actualiza: el servidor del juego, GitHub, los dos o una dirección tuya.")),
        seccion(tr("Contenido para adultos"), [
            Opcion(lambda: tr('Contenido para mayores de 18 años: {v}').format(v=(tr('activado') if cfg['adultos'] else tr('desactivado'))), ajuste=adultos,
                   ayuda=tr("Añade relaciones sentimentales y sexuales, ligar con cualquiera, aventuras, compañía de pago, drogas y trapicheo, contado de forma sensual pero sin escenas explícitas. Todo tiene consecuencias en el ánimo, la salud, la reputación y las relaciones. Desactivado, nada de eso aparece en el juego.")),
            lista("atraccion", tr("Me atraen"), tr("Con quién puedes coquetear.")),
            lista("mi_genero", tr("Soy"), tr("Sirve para saber a quién le puedes gustar. Si prefieres no decirlo, le puedes gustar a cualquiera.")),
            si_no("noche_por_pasos", tr("La noche con alguien, paso a paso"),
                  tr("Con sí, cuando pasas la noche con alguien decides tú qué haces en cada momento y la otra persona responde. Fijarte en lo que quiere, y parar si te lo pide, es lo que hace que salga bien. "
                  "Se sigue contando de forma sensual, sin escenas explícitas. Con no, la noche se cuenta en un par de frases, como antes.")),
            si_no("pareja_convive", tr("Vida en pareja: poder pedirle a tu pareja que se venga a vivir contigo"),
                  tr("Con sí, en la ficha de tu pareja aparece la opción de pedirle que se mude a una de tus casas. Cada persona decide: unas aceptan cuando la relación va bien, y otras no dejan su casa por nadie. "
                  "Si acepta, te la encuentras en casa, cocina para los dos o te pide que cocines tú, te pide cosas de vez en cuando y nota si no apareces. Puedes pedirle que se vaya. "
                  "Con no, que es como viene, cada uno sigue en su casa. Los planes nuevos en pareja no dependen de esta opción. Solo jugando en solitario.")),
        ], tr("Activa o desactiva los temas para mayores de 18 años.")),
    ]
    principal_ = Menu(app, tr("Opciones"), secciones + [Opcion(tr("Volver"), lambda: app.cerrar(principal_), ayuda=tr("Cierra las opciones. También sirve Escape."))],
                      al_cerrar=cfg.guardar, intro=tr("Las opciones están agrupadas por secciones. Pulsa Intro para entrar en una"))
    app.abrir(principal_)


# ========================================================================== intro
def intro(p):
    app = p.app

    def empezar():
        bar = p.mundo.lugares["bar_gaviota"]
        p.decir(tr('Estás en la {describir}. {situar}. Camina con las flechas y pulsa Intro ante la puerta. Pulsa F1 para ver las teclas.').format(describir=(p.mundo.describir(p.j.x, p.j.y)), situar=(p.situar(bar.x, bar.y, bar.nombre))))
        p.gps_a_lugar(bar, callar=True)

    def tras_intro():
        def con():
            app.cerrar(m)
            app.abrir(Dialogo(app, ayuda.TUTORIAL, empezar))

        def sin():
            app.cerrar(m)
            empezar()
        m = Menu(app, tr("¿Quieres escuchar el tutorial?"), [Opcion(tr("Sí, explícame cómo se juega"), con, ayuda=tr("Un narrador te explica cómo se juega: el sonido, el movimiento y las teclas básicas. Se puede saltar con Escape.")),
                                                          Opcion(tr("No, ya sé jugar"), sin, ayuda=tr("Empiezas a jugar al momento, con el GPS marcando el bar donde empieza la historia. Las teclas están siempre en F1."))], escapable=False)
        app.abrir(m)
    app.abrir(Dialogo(app, [(q, p.txt(t)) for q, t in ayuda.INTRO], tras_intro))


# ========================================================================== pausa
def pausa(p):
    app = p.app

    def salir():
        def si():
            app.volver_al_menu()
        app.abrir(Menu(app, tr("¿Salir al menú principal? Se perderá lo que no hayas guardado"), [Opcion(tr("No, seguir jugando"), lambda: app.cerrar()), Opcion(tr("Sí, salir"), si, ayuda=tr("Vuelves al menú principal. Lo que no hayas guardado se pierde."))]))
    ops = [
        Opcion(tr("Reanudar"), lambda: app.cerrar()),
        Opcion(tr("Objetivo actual"), lambda: app.decir(p.objetivo_txt(), True), ayuda=tr("Dice qué tienes que hacer ahora en la misión o el trabajo en curso, o qué misión te espera si no tienes ninguna.")),
        Opcion(tr("Guardar partida"), lambda: menu_guardar(p), ayuda=tr("Elige una de las cinco ranuras para guardar la partida tal como está. Durante una misión no se puede.")),
        Opcion(tr("Cargar partida"), lambda: menu_cargar(app), ayuda=tr("Elige una de tus partidas guardadas y sigues desde ahí. Lo que no hayas guardado de esta partida se pierde.")),
        Opcion(tr("Opciones"), lambda: opciones(app), ayuda=tr("Sonido, voz, movimiento, orientación, dificultad, teclas, mando y el resto de ajustes, por secciones. Los cambios se guardan al salir.")),
        Opcion(tr("Ayuda de teclas"), lambda: ayuda_teclas(app, "todo"), ayuda=tr("Todas las teclas del juego, a pie, al volante y en cualquier momento, y los botones del mando. Si has cambiado alguna tecla, dice la tuya.")),
        Opcion(tr("Aprender los sonidos"), lambda: sonidos(app), ayuda=tr("Escucha cada sonido del juego con su explicación: primero los más importantes y después todos, por grupos, con un buscador.")),
        Opcion(tr("Mi música: poner tus canciones en la radio"), lambda: mi_musica(app),
               ayuda=tr("Los cuatro pasos para oír tu propia música en la radio de los vehículos, y la opción que abre la carpeta donde se copian las canciones.")),
        Opcion(tr("Abrir el manual"), lambda: abrir_manual(app), ayuda=tr("Abre el manual completo del juego en tu navegador. El juego sigue abierto detrás.")),
        Opcion(tr("Salir al menú principal"), salir, ayuda=tr("Antes de salir te pregunta. Lo que no hayas guardado se pierde.")),
    ]
    app.abrir(Menu(app, tr("Pausa"), ops))


# ========================================================================== móvil
GRUPOS = [(tr("Todos los lugares"), None), (tr("Mis casas y negocios"), "propio"), (tr("Sin visitar"), "nuevo"),
          (tr("Tiendas y comida"), ("tienda", "comida", "pizzeria", "farmacia", "bar")), (tr("Armerías"), ("armeria",)),
          (tr("Talleres y desguace"), ("taller", "desguace")), (tr("Casas y negocios en venta"), ("casa", "negocio")),
          (tr("Servicios: hospital, comisaría y taxi"), ("hospital", "comisaria", "taxi", "periodico")),
          (tr("Ocio: casino y carreras"), ("casino", "carrera")), (tr("Monumentos y sitios de interés"), ("monumento",))]


GRUPOS += [(tr("Viajes: carreteras, autobuses y embarcaderos"), ("salida", "estacion", "embarcadero", "muelle", "nautica")),
           (tr("Bancos, gimnasios, cines y otros servicios"), ("banco", "gimnasio", "cine", "hotel", "ropa", "loteria", "empenos", "concesionario", "pescaderia", "taberna", "pesca"))]


def lista_lugares(p, al_elegir=None, titulo=None, mapa=None, otras=True):
    app = p.app
    mundo = mapa or p.mundo
    titulo = titulo or tr('Lugares de {nombre}').format(nombre=(mundo.nombre))

    def otras_localidades():
        ops = [Opcion(f"{m.nombre}. {p.desc_localidad(m)}", (lambda m=m: lista_lugares(p, al_elegir, None, m, False)),
                      ayuda=tr("Abre la lista de lugares de esa localidad. Al elegir uno, el GPS te lleva primero hasta la carretera, la estación o el embarcadero que va allí."))
               for m in p.mapas.values() if m.id != p.mundo.id]
        app.abrir(Menu(app, tr("Otras localidades"), ops, intro=tr("El GPS te guiará hasta la carretera, la estación o el embarcadero que lleva allí")))

    def abrir_grupo(nombre, filtro):
        def ops():
            lista = []
            for l in sorted(mundo.lugares.values(), key=lambda l: l.nombre.lower()):
                if filtro == "propio" and l.id not in p.j.propiedades:
                    continue
                if filtro == "nuevo" and l.id in p.j.visitados:
                    continue
                if isinstance(filtro, tuple) and l.tipo not in filtro:
                    continue
                marca = "" if l.id in p.j.visitados else tr(", sin visitar")

                def ir(l=l):
                    while len(app.pila) > 1 and app.pila[-1] is not p:
                        app.pila.pop()
                    app.teclas.clear()
                    if al_elegir:
                        al_elegir(l)
                    else:
                        p.gps_a_lugar(l)
                texto = p.situar(l.x, l.y, l.nombre) if l.mapa == p.mundo.id else l.nombre
                lista.append(Opcion(texto + marca, ir, ayuda=l.desc))
            return lista or [Opcion(tr("No hay ningún lugar en esta lista"), ayuda=tr("En este grupo no hay nada ahora mismo. Prueba con otro grupo o con Todos los lugares."))]
        mg = Menu(app, nombre, ops, intro=tr("En orden alfabético. Pulsa una letra para saltar, Intro para elegir y F1 para la descripción"))
        app.abrir(mg)
    grupos = [Opcion(n, (lambda n=n, f=f: abrir_grupo(n, f)), ayuda=tr("Los lugares de este grupo, en orden alfabético y con dónde está cada uno. Sobre un lugar, F1 dice cómo es.")) for n, f in GRUPOS]
    if al_elegir is None and mapa is None and (p.mision or p.trabajo):
        def al_objetivo():
            while len(app.pila) > 1 and app.pila[-1] is not p:
                app.pila.pop()
            app.teclas.clear()
            p.enfocar_objetivo()
        grupos.insert(0, Opcion(lambda: tr("Objetivo de la misión. ") + (p.objetivo_posicion_txt() or tr("Pulsa Intro para oír qué toca ahora.")), al_objetivo,
                                ayuda=tr("El sitio, el vehículo o la persona que pide ahora la misión o el trabajo, con su nombre tal como sale en el mapa. Intro lo marca en el GPS, dejando cualquier desvío. "
                                      "Sin abrir esta lista se hace con Mayúsculas O.")))
    if otras and len(p.mapas) > 1:
        grupos.append(Opcion(tr("Otras localidades"), otras_localidades,
                              ayuda=tr("Las demás localidades del juego, cada una con sus lugares. El GPS te guía hasta la salida que lleva a la que elijas.")))
    mp = Menu(app, titulo, grupos)
    app.abrir(mp)


def movil(p):
    app = p.app
    j = p.j

    def volver_al_objetivo():
        while app.pila and app.pila[-1] is not p:
            app.cerrar(app.pila[-1])
        p.enfocar_objetivo()

    def misiones():
        def ops():
            lista = []
            en_curso = p.mision["def"] if p.mision else None
            if en_curso is not None:                             # la que estás haciendo: Intro guía a lo que toca ahora, no a donde empezó
                lista.append(Opcion(lambda: tr('En curso: {titulo}. {v}').format(titulo=(en_curso['titulo']), v=(p.objetivo_posicion_txt() or tr('Pulsa Intro para oír qué toca ahora.'))), volver_al_objetivo,
                                    ayuda=tr("Es la misión que estás haciendo. Intro vuelve a su objetivo de ahora: lo marca en el GPS, dejando cualquier desvío, y si está cerca lo deja elegido en el radar. "
                                          "Fuera del móvil se hace con Mayúsculas O.")))
            for m in p.misiones_disponibles():
                if en_curso is not None and m.get("id") == en_curso.get("id"):
                    continue
                l = p.lugares[m["lugar"]]

                def ir(l=l):
                    app.cerrar(mm)
                    app.cerrar(menu)
                    p.gps_a_lugar(l)
                donde = p.situar(l.x, l.y, l.nombre) if l.mapa == p.mundo.id else p.nombre_lugar(l)
                if m.get("explicacion"):                         # no es una misión: se lee aquí mismo
                    lista.append(Opcion(tr('Explicación: {titulo}. {txt}').format(titulo=(m['titulo']), txt=(p.txt(m['resumen']))), (lambda m=m: p.explicacion(m)),
                                        ayuda=tr("Pulsa Intro para leerla ahora. No es una misión: no hay que ir a ningún sitio ni hacer nada. Al llegar al final cuenta como hecha.")))
                    continue
                if m.get("tutorial") and m["id"] != "tut01":
                    def empezar(m=m):
                        if p.mision:
                            app.son("error")
                            app.decir(tr("Termina o abandona antes la misión que tienes en curso."), True)
                            return
                        while app.pila and app.pila[-1] is not p:
                            app.cerrar(app.pila[-1])
                        p.iniciar_mision(m)
                    lista.append(Opcion(tr('Tutorial: {titulo}. {txt} {mision_vehiculo_txt}').format(titulo=(m['titulo']), txt=(p.txt(m['resumen'])), mision_vehiculo_txt=(p.mision_vehiculo_txt(m))).rstrip(), empezar, ayuda=tr("Pulsa Intro para empezarlo ahora, estés donde estés. Si estás lejos de donde se hace, el tutorial te lleva allí él mismo.")))
                    continue
                lista.append(Opcion(f"{m['titulo']}. {p.txt(m['resumen'])} {p.mision_vehiculo_txt(m)} {donde}".replace("  ", " "), ir, ayuda=tr("Pulsa Intro para marcar el lugar en el GPS.")))
            return lista or [Opcion(tr("No hay misiones disponibles ahora mismo"), ayuda=tr("Ahora mismo no te espera ninguna misión. Vuelve a mirar más adelante."))]
        mm = Menu(app, tr("Misiones disponibles"), ops, intro=tr("Intro marca en el GPS el lugar donde empieza") + (tr(". La primera es la que tienes en curso: Intro vuelve a su objetivo de ahora") if p.mision else ""))
        app.abrir(mm)

    def abandonar():
        app.cerrar(menu)
        p.abandonar_mision()

    def taxi():
        if j.estrellas:
            app.son("error")
            app.decir(tr("Ningún taxista te recoge mientras te busca la policía."), True)
            return
        if p.mision:
            app.son("error")
            app.decir(tr("Durante una misión tienes que llegar por tus medios."), True)
            return
        app.cerrar(menu)
        menu_viaje(p)

    def propiedades():
        ops = []
        for pid in j.propiedades:
            l = p.lugares.get(pid)
            if not l:
                continue
            if l.tipo == "negocio":
                ops.append(Opcion(tr('{nombre_lugar}: negocio, {get} euros al día').format(nombre_lugar=(p.nombre_lugar(l)), get=(l.get('ingresos', 0))),
                                  ayuda=tr("Lo que te da este negocio cada medianoche, según cómo lo cobres. Para gestionarlo, ve al negocio.")))
            else:
                g = j.garajes.get(pid, [])
                ops.append(Opcion(tr('{nombre_lugar}: casa, {len} de {get} vehículos en el garaje').format(nombre_lugar=(p.nombre_lugar(l)), len=(len(g)), get=(l.get('garaje', 0))),
                                  ayuda=tr("Una casa tuya y cuántos vehículos tienes en su garaje. Allí puedes guardar la partida, descansar y meter o sacar vehículos.")))
        for b in j.barcos:
            e = p.lug(b.get("en"))
            ops.append(Opcion(tr('Barco {get}, amarrado en {v}').format(get=(b.get('nombre', b['modelo'])), v=(p.nombre_lugar(e) if e else tr('puerto'))), ayuda=tr("Uno de tus barcos y el sitio donde está amarrado.")))
        ops.append(Opcion(tr('Cuenta del banco: {banco} euros').format(banco=(j.banco)), ayuda=tr("El dinero que tienes en el banco, aparte del que llevas encima. Se ingresa y se saca en los bancos.")))
        if p.negocios_tuyos():
            ops.insert(0, Opcion(lambda: tr('Cómo cobras tus negocios: {cobro_txt}').format(cobro_txt=(p.cobro_txt())), p.cambiar_cobro,
                                 ayuda=tr("Intro cambia entre las tres formas: que te lo traigan en mano cada medianoche, que te lo ingresen en el banco, o ir tú a recogerlo a cada negocio, con un diez por ciento más.")))
        app.abrir(Menu(app, tr("Tus propiedades"), ops))

    def estadisticas():
        s = j.stats
        h, mi = int(s["tiempo"] // 3600), int(s["tiempo"] % 3600 // 60)
        total = len(p.datos["misiones"])
        ops = [tr('Misiones completadas: {len} de {total}').format(len=(len(p.completadas)), total=(total)), tr('Dinero: {dinero} euros. Ganado en total: {dinero_ganado}').format(dinero=(j.dinero), dinero_ganado=(s['dinero_ganado'])),
               tr('Tiempo jugado: {h} horas y {mi} minutos. Día {dia}').format(h=(h), mi=(mi), dia=(p.dia)), tr('Lugares visitados: {len} de {len2}').format(len=(len(j.visitados)), len2=(len(p.lugares))),
               tr('Barrios y localidades visitados: {len} de {sum}').format(len=(len(j.barrios_vistos)), sum=(sum(len(m.barrios) for m in p.mapas.values()))),
               tr('Objetos de colección: {len} de {total_casetes}').format(len=(len(j.casetes)), total_casetes=(p.total_casetes())),
               tr('Peces pescados: {get}. Servicios de trabajo: {get2}').format(get=(s.get('peces', 0)), get2=(s.get('servicios', 0))),
               tr('Vehículos robados: {vehiculos_robados}. Vendidos al desguace: {vendidos}').format(vehiculos_robados=(s['vehiculos_robados']), vendidos=(s['vendidos'])), tr('Enemigos abatidos: {enemigos}').format(enemigos=(s['enemigos'])),
               tr('Carreras de taxi: {carreras_taxi}. Pizzas entregadas: {pizzas}').format(carreras_taxi=(s['carreras_taxi']), pizzas=(s['pizzas'])), tr('Carreras callejeras ganadas: {len} de {len2}').format(len=(len(s['carreras'])), len2=(len(p.datos['carreras']))),
               tr('Distancia a pie: {int} metros. Al volante: {int2} kilómetros').format(int=(int(s['metros_pie'])), int2=(int(s['metros_coche'] / 1000))),
               tr('Veces en el hospital: {muertes}. Detenciones: {detenciones}').format(muertes=(s['muertes']), detenciones=(s['detenciones']))]
        app.abrir(Menu(app, tr("Estadísticas"), [Opcion(t, ayuda=tr("Un dato de tu partida, que se va poniendo al día mientras juegas. Intro lo vuelve a leer.")) for t in ops]))

    def barrios():
        ops = [Opcion(f"{b['nombre']}{'' if m.nombre == b['nombre'] else ', ' + m.nombre}{'' if b['id'] in j.barrios_vistos else tr(', sin visitar')}. {p.barrio_desc(b, m)}",
                      ayuda=tr("Un barrio o una localidad, y cómo es. Los que todavía no has pisado dicen sin visitar."))
               for m in p.mapas.values() for b in m.barrios]
        app.abrir(Menu(app, tr("Barrios y localidades"), ops))

    def inventario():
        ops = []
        desc_obj = {o["id"]: o.get("desc", "") for o in p.datos["objetos"]}      # la ayuda de cada objeto está en sus datos
        for ident in p.orden_armas:
            if ident in j.armas:
                a = p.armas_d[ident]
                t = f"{p.orden_armas.index(ident) + 1}: {a['nombre']}"
                if a["tipo"] in ("fuego", "explosivo"):
                    from .combate import municion_txt
                    t += ", " + municion_txt(a, j.armas[ident])
                ops.append(Opcion(t + ", " + ficha_corta(a), ayuda=ayuda_arma(a)))
        ops.append(Opcion(tr('Botiquines: {get}').format(get=(j.objetos.get('botiquin', 0))), ayuda=desc_obj.get("botiquin")))
        ops.append(Opcion(tr('Ganzúas: {get}').format(get=(j.objetos.get('ganzua', 0))), ayuda=desc_obj.get("ganzua")))
        if j.perro:
            ops.append(Opcion(tr('Raciones de pienso para {perro}: {get}').format(perro=(j.perro), get=(j.objetos.get('pienso', 0))), ayuda=desc_obj.get("pienso")))
        ops.append(Opcion(tr('Blindaje: {int}').format(int=(int(j.blindaje))),
                          ayuda=tr("Lo que aguanta tu chaleco o tu protección antes de que el daño te llegue a la salud. Se repone en la armería.")))
        from . import mochila
        ops.append(Opcion(p.moc_txt() + tr(". Intro la abre"), lambda: mochila.menu_mochila(p),
                          ayuda=tr("Lo que llevas encima: objetos de valor encontrados o robados, y la mercancía. Se venden en las casas de empeños y se guardan en el armario de tus casas.")))
        ops += __import__("juego.menus_cocina", fromlist=["x"]).opciones_movil(p)
        app.abrir(Menu(app, tr("Inventario"), ops))

    def diario():
        """Lo que ha pasado en la historia, de lo último a lo primero. Desde aquí se repite cualquier misión ya hecha."""
        por_id = {m["id"]: m for m in p.datos["misiones"]}

        def repetir(m):
            def f():
                if p.mision:
                    app.son("error")
                    app.decir(tr("Termina o abandona antes la misión que tienes en curso."), True)
                    return
                l = p.lugares.get(m["lugar"])
                if l is None:
                    app.son("error")
                    app.decir(tr("Esa misión es de un mod que ahora no está cargado."), True)
                    return

                def si():
                    while app.pila and app.pila[-1] is not p:
                        app.cerrar(app.pila[-1])
                    p.llevarte_a(l.mapa, l.x, l.y)                 # tu vehículo va contigo y queda aparcado a tu lado
                    p.iniciar_mision(m, repeticion=True)
                app.abrir(Menu(app, tr('¿Repetir {titulo}? Te lleva al lugar donde empieza. No cuenta ni da recompensa').format(titulo=(m['titulo'])),
                               [Opcion(tr("Sí, repetirla"), si, ayuda=tr("Te lleva al sitio donde empieza la misión, con tu vehículo al lado, y empieza al momento. No da recompensa ni cambia la historia.")),
                                Opcion(tr("No"), lambda: app.cerrar())]))
            return f

        def ops_d():
            lista = [Opcion(p.resumen_historia, ayuda=tr("Por dónde vas en la historia. Debajo están tus decisiones y las misiones que has hecho."))]
            for clave, valor in p.decisiones.items():
                if isinstance(valor, dict) and valor.get("texto"):
                    renta = int(valor.get("renta", 0))
                    lista.append(Opcion(tr('Decisión: {texto}').format(texto=(valor['texto'])) + (tr('. Te deja {renta} euros cada medianoche').format(renta=(renta)) if renta > 0 else tr('. Te cuesta {v} euros cada medianoche').format(v=(-renta)) if renta < 0 else ""),
                                        ayuda=tr("Algo que decidiste en la historia y, si es el caso, lo que te sigue dando o costando cada medianoche.")))
            for ident in reversed(p.completadas):
                m = por_id.get(ident)
                if m is None or (m.get("adultos") and not app.cfg["adultos"]):
                    continue
                nota = tr(", saltada") if ident in p.saltadas else ""
                lista.append(Opcion(f"{m['titulo']}{nota}. {p.txt(m.get('resumen', ''))}", repetir(m), ayuda=tr("Intro para volver a jugar esta misión. Repetirla no da recompensa ni cambia la historia.")))
            return lista
        app.abrir(Menu(app, tr('Diario. {len} misiones hechas').format(len=(len(p.completadas))), ops_d, intro=tr("Arriba, por dónde vas. Debajo, lo que has hecho, de lo último a lo primero. Intro repite una misión")))

    def ops():
        lista = [Opcion(tr("Objetivo actual"), lambda: app.decir(p.objetivo_txt(), True), ayuda=tr("Dice qué tienes que hacer ahora en la misión o el trabajo en curso, o qué misión te espera si no tienes ninguna.")),
                 Opcion(tr("Misiones disponibles"), misiones, ayuda=tr("Las misiones que puedes hacer ahora, con dónde empieza cada una. Intro marca el sitio en el GPS.")),
                 Opcion(tr("Diario: lo que ha pasado y repetir misiones"), diario,
                        ayuda=tr("Un resumen de por dónde vas en la historia y la lista de las misiones que has hecho. Desde ahí puedes repetir cualquiera."))]
        if p.mision or p.trabajo:
            lista.insert(1, Opcion(tr("Volver al objetivo: marcarlo en el GPS y en el radar"), volver_al_objetivo,
                                   ayuda=tr("Deja cualquier desvío y vuelve a marcar en el GPS lo que pide ahora la misión o el trabajo. Si está cerca, lo deja elegido en el radar. "
                                         "Fuera del móvil se hace con Mayúsculas O.")))
        if p.mision:
            lista.append(Opcion(tr("Abandonar la misión en curso"), abandonar, ayuda=tr("Dejas la misión a medias y sin recompensa. Más adelante la puedes volver a empezar.")))
        from . import menus_extra as mx
        from .pantallas import ExploradorMapa
        lista += [Opcion(tr("Lugares y GPS"), lambda: lista_lugares(p), ayuda=tr("Todos los lugares de la localidad, por grupos y con dónde está cada uno. Intro sobre uno lo marca en el GPS.")),
                  Opcion(tr("Explorar el mapa con el cursor"), lambda: app.abrir(ExploradorMapa(app, p)), ayuda=tr("Recorre la localidad cruce a cruce sin mover al personaje. También se abre con F9.")),
                  Opcion(tr("Marcadores personales"), lambda: mx.marcadores(p),
                         ayuda=tr("Guarda el punto donde estás para volver luego con el GPS, ve a uno que ya guardaste o borra el último.")),
                  Opcion(tr("Dónde está mi vehículo"), lambda: (app.cerrar(menu), p.localizar_vehiculo()),
                         ayuda=tr("Dice dónde dejaste el vehículo del que te bajaste y lo marca en el GPS. Si ibas a otro sitio, al llegar al vehículo el GPS vuelve solo a ese destino. "
                               "Sin abrir el móvil, se hace con Mayúsculas L. Si tienes más vehículos, están todos en Mis vehículos.")),
                  Opcion(lambda: tr("Mis vehículos") + (tr(': {mis_en_calle} en la calle y {mis_en_garajes} en garajes').format(mis_en_calle=(p.mis_en_calle()), mis_en_garajes=(p.mis_en_garajes())) if not p.en_servidor else ""),
                         lambda: __import__("juego.misvehiculos", fromlist=["x"]).menu_mis_vehiculos(p),
                         ayuda=tr("Todos tus vehículos, con su nombre, su modelo, su estado, sus mejoras y dónde está cada uno. Desde ahí marcas cualquiera en el GPS, pides que te lo traigan, "
                               "lo mandas a un garaje o le cambias el nombre. Son tuyos los que compras, los que mejoras en un taller, los que sacas de un garaje y los que bautizas: "
                               "esos no desaparecen aunque te alejes o cojas otro.")),
                  Opcion(tr("Servicios: vehículo, chófer, guardaespaldas, ambulancia y taxi"), lambda: mx.servicios(p),
                         ayuda=tr("Lo que puedes pedir por teléfono: que te traigan un vehículo de un garaje, un chófer, guardaespaldas, una ambulancia, un taxi o la asistencia en carretera.")),
                  ] + ([Opcion(lambda: tr("Pedir comida a domicilio") + (": " + p.pedido_txt() if j.pedido else ""),
                               lambda: __import__("juego.domicilio", fromlist=["x"]).menu_domicilio(p),
                               ayuda=tr("Solo desde una casa tuya, o en su puerta. Eliges de la carta, pagas el pedido y el envío, y al rato llaman al timbre. "
                                     "Lo que pidas quita el hambre y la sed de la vida realista y da algo de salud. Si no estás en casa cuando llegue, el repartidor espera un rato y se va."))]
                       if (p.casa_aqui() is not None or j.pedido) else []) + ([Opcion(lambda: tr("Tu perro. ") + p.perro_txt(), lambda: mx.menu_perro(p), ayuda=tr("Acariciarlo, darle de comer, mandarlo a casa o llamarlo. A pie también se abre con Mayúsculas Y."))] if j.perro else []) + [
                  Opcion(lambda: tr("Jugar con amigos") + (tr(': conectado, {v} jugadores').format(v=(len(p.remotos) + 1)) if p.online_activo() else ""),
                         lambda: __import__("juego.menus_online", fromlist=["x"]).amigos(p),
                         ayuda=tr("Abre tu partida para que entren tus amigos, o únete a la de uno. Tu propio juego hace de servidor: no hace falta nada más.")),
                  Opcion(lambda: tr('Tus conocidos: {len}').format(len=(len(j.conocidos))), lambda: __import__("juego.menus_charla", fromlist=["x"]).conocidos(p),
                         ayuda=tr("La gente de la calle que te ha dado su número. Hablas con cualquiera con la tecla J.")),
                  Opcion(tr("Tu carrera: vida honrada y vida delictiva"), lambda: __import__("juego.menus_vida", fromlist=["x"]).carrera(p),
                         ayuda=tr("Un resumen de tu vida: cómo te ven, lo que has trabajado de forma honrada y lo que has hecho fuera de la ley.")),
                  Opcion(lambda: tr("Vida, reputación y consecuencias") + (tr(': {len} asuntos pendientes').format(len=(len(j.honra.get('asuntos') or []))) if j.honra.get("asuntos") else ""),
                         lambda: __import__("juego.menus_honrado", fromlist=["x"]).menu_vida(p),
                         ayuda=tr("Cómo te ve la ciudad y cómo te ve la calle, y qué ganas o pierdes por ello. Aquí están también tus antecedentes, tu contrato, tus estudios, tus negocios, "
                               "los créditos, las facturas y los impuestos que vienen, los asuntos que esperan una decisión tuya y por dónde vas en el buen camino.")),
                  Opcion(tr("Habilidades y logros"), lambda: mx.progreso(p), ayuda=tr("Tu nivel en cada habilidad, que sube al practicarla, y los logros que llevas conseguidos.")),
                  Opcion(tr("Territorios: guerras de barrio"), lambda: mx.territorios(p),
                         ayuda=tr("Los barrios de las bandas: conquistarlos, defender los tuyos, reclutar gente y hacer tratos. Cada barrio tuyo te paga cada medianoche.")),
                  Opcion(lambda: tr("Lotería. ") + __import__("juego.loteria", fromlist=["x"]).estado_txt(p), lambda: __import__("juego.loteria", fromlist=["x"]).menu_movil(p),
                         ayuda=tr("El próximo sorteo, tus boletos, comprobar si te ha tocado y los últimos números premiados. El sorteo es cada día a las nueve de la noche.")),
                  ] + ([Opcion(tr("Vida social: relaciones"), lambda: __import__("juego.menus_adultos", fromlist=["x"]).vida_social(p),
                               ayuda=tr("Las personas con las que tienes relación y cómo os va: llamar, escribir, quedar, regalar y lo demás que se hace con cada una.")),
                        Opcion(tr("Sustancias y mercancía"), lambda: __import__("juego.menus_adultos", fromlist=["x"]).menu_sustancias(p),
                               ayuda=tr("Lo que llevas encima para tomar o para vender, los efectos que notas ahora y tu dependencia."))] if p.modo_adulto() else
                       [Opcion(tr("Vida sentimental: conocer a alguien, citas, compromiso y boda"), lambda: __import__("juego.menus_adultos", fromlist=["x"]).vida_social(p),
                               ayuda=tr("Personas a las que puedes conocer, con las que quedar y, si la cosa va bien, ser pareja, prometeros, vivir juntos y casaros. Sin contenido para adultos."))]
                       if p.vida_sentimental() and not p.en_servidor else []) + [
                  Opcion(tr("Inventario"), inventario, ayuda=tr("Tus armas con su munición, los botiquines, las ganzúas, el blindaje y la mochila.")),
                  Opcion(tr("Propiedades"), propiedades, ayuda=tr("Tus casas, tus negocios con lo que dan al día, tus barcos y lo que tienes en el banco.")),
                  Opcion(tr("Barrios"), barrios, ayuda=tr("Todos los barrios y localidades del juego, con cómo es cada uno y cuáles te faltan por visitar.")),
                  Opcion(tr("Estadísticas"), estadisticas, ayuda=tr("Las cifras de tu partida: misiones, dinero, tiempo jugado, lugares visitados, distancias y más."))]
        return lista
    menu = Menu(app, lambda: tr('Móvil. {hora_txt}. {dinero} euros').format(hora_txt=(p.hora_txt()), dinero=(j.dinero)), ops)
    app.abrir(menu)


def menu_viaje(p):
    app = p.app

    def viajar(l):
        x, y = p.pos()
        d = math.hypot(l.x - x, l.y - y)
        coste = int(p.precio("taxi_base", 10) + d * 0.05)
        if not p.pagar(coste):
            return

        def llegar():
            p.teletransportar(l.x, l.y)
            p.pasar_horas(d / 600.0)
            p.app.son("puerta_coche")
            p.decir(tr('El taxi te deja en {nombre} por {coste} euros. Son las {hora_txt}.').format(nombre=(l.nombre), coste=(coste), hora_txt=(p.hora_txt())))
        from .pantallas import viajar as trayecto
        trayecto(p.app, max(12.0, min(45.0, d / 14.0)), llegar, destino=l.nombre)
    if p.mundo.tipo == "mar":
        p.app.decir(tr("En mitad del mar no hay taxis."), True)
        return
    lista_lugares(p, viajar, tr("Taxi: ¿a dónde te llevo? El precio depende de la distancia"), otras=False)


def menu_armas(p):
    app = p.app
    j = p.j

    def elegir(ident):
        def f():
            app.cerrar(m)
            p.elegir_arma(ident)
        return f
    ops = []
    for ident in p.orden_armas:
        if ident in j.armas:
            a = p.armas_d[ident]
            t = a["nombre"]
            if a["tipo"] in ("fuego", "explosivo"):
                t += tr(', {v} disparos').format(v=(j.armas[ident]['cargador'] + j.armas[ident]['reserva']))
            ops.append(Opcion(t + ", " + ficha_corta(a) + (tr(", en la mano") if ident == j.arma else ""), elegir(ident), ayuda=ayuda_arma(a)))
    m = Menu(app, tr("Tus armas"), ops, intro=tr("Intro para empuñar. F1 describe el arma: daño, alcance, cadencia y precisión"))
    m.i = next((k for k, i in enumerate([i for i in p.orden_armas if i in j.armas]) if i == j.arma), 0)
    app.abrir(m)


# ========================================================================= lugares
def lugar(p, l):
    app = p.app
    j = p.j
    if not p.lugar_abierto(l):
        app.son("error")
        app.decir(tr('{nombre}. Está cerrado: aquí todavía no te conocen.').format(nombre=(l.nombre)), True)
        return
    if p.entrada_vetada(l):                                      # lo atracaste hace poco: no te abren, o llaman a la policía
        return
    portero = p.portero_no_deja(l)                               # oliendo mal, en el club o el casino no entras (necesidades.py)
    if portero:
        app.son("error")
        app.decir(f"{l.nombre}. {portero}", True)
        return
    from . import encuentros
    abierto, cerrado_txt = encuentros.local_abierto(p, l)        # con los horarios de los locales, cada uno abre a sus horas
    if not abierto:
        app.son("error")
        app.decir(cerrado_txt, True)
        return
    if p.hon_negativa(l):                                        # con el nivel exigente, donde te evitan hay comercios que no te atienden
        return
    en_coche = j.veh is not None
    from .combustible import tiene_surtidor
    if en_coche and tiene_surtidor(l) and p.gasta(j.veh):
        pass                                                     # en una gasolinera se reposta sin bajarse
    elif en_coche and l.tipo not in ("taller", "desguace", "casa", "carrera", "salida", "muelle", "estacion", "embarcadero", "pesca", "monumento", "helipuerto", "tesoro", "aeropuerto", "tranvia", "tren"):
        app.decir(tr('{nombre}. Bájate del vehículo con F para entrar.').format(nombre=(l.nombre)), True)
        return
    if en_coche and abs(j.veh.vel) > 3:
        app.decir(tr("Detén el vehículo primero."), True)
        return
    p.entrar_bajo_techo(l)                                       # si te sigue el helicóptero de la policía, al entrar deja de verte
    from . import menus_lugares as ml
    f = {"casa": _casa, "armeria": _armeria, "tienda": _tienda, "farmacia": _farmacia, "comida": _comida,
         "pizzeria": _comida, "hospital": _hospital, "comisaria": _comisaria, "taller": _taller,
         "desguace": _desguace, "casino": _casino, "bar": _bar, "negocio": _negocio, "taxi": _taxi,
         "carrera": _carrera, "periodico": _periodico, "salida": ml.salida, "estacion": ml.estacion,
         "embarcadero": ml.embarcadero, "muelle": ml.muelle, "pesca": ml.punto_pesca, "nautica": ml.nautica,
         "concesionario": ml.concesionario, "banco": ml.banco, "loteria": ml.loteria, "empenos": ml.empenos,
         "pescaderia": ml.pescaderia, "gimnasio": ml.gimnasio, "ropa": ml.ropa, "cine": ml.cine,
         "hotel": ml.hotel, "taberna": ml.taberna, "tranvia": ml.tranvia, "tren": ml.tren, "aeropuerto": ml.aeropuerto}.get(l.tipo)
    if l.tipo in ("helipuerto", "protectora", "feria", "tesoro"):
        from . import menus_extra as mx
        f = {"helipuerto": mx.helipuerto, "protectora": mx.protectora, "feria": mx.feria, "tesoro": mx.tesoro}[l.tipo]
    if l.tipo in ("club", "proveedor"):
        from . import menus_adultos as ma
        f = {"club": ma.club, "proveedor": ma.proveedor}[l.tipo]
    if l.tipo in ("empleo", "academia", "ong"):
        from . import menus_vida as mv
        f = {"empleo": mv.empleo, "academia": mv.academia, "ong": mv.ong}[l.tipo]
    if f is None and p.vida_realista() and p.tiene_fuente(l):        # en un parque o una plaza hay una fuente (necesidades.py)
        _menu_lugar(p, l, [Opcion(l.desc or l.nombre, ayuda=tr("Cómo es este sitio. Intro lo vuelve a leer.")), Opcion(tr("Beber agua de la fuente"), lambda: app.decir(p.beber_en_fuente(), True),
                                                                ayuda=tr("Gratis. Quita la sed, con la vida realista."))])
        return
    if f is None:
        app.decir(f"{l.nombre}. {l.desc}", True)
        return
    if not en_coche and l.tipo not in ("salida", "muelle", "embarcadero", "estacion", "pesca", "tesoro", "helipuerto", "carrera", "taxi", "tranvia", "tren", "aeropuerto"):
        p.entrar_interior(l)
    f(p, l)
    if app.pila and app.pila[-1] is p:
        p.salir_interior(silencio=True)
    elif not en_coche and app.pila and isinstance(app.pila[-1], Menu):
        from . import atracos, sistemas
        sistemas.con_recorrido(p, l, app.pila[-1], Opcion)
        atracos.con_atraco(p, l, app.pila[-1], Opcion)           # todo local con caja en los datos se puede atracar
        if p.vida_realista() and p.tiene_fuente(l):              # y si tiene fuente, se bebe (necesidades.py)
            app.pila[-1].opciones.insert(max(0, len(app.pila[-1].opciones) - 1),
                                         Opcion(tr("Beber agua de la fuente"), lambda: app.decir(p.beber_en_fuente(), True), ayuda=tr("Gratis. Quita la sed, con la vida realista.")))
        from . import menus_capo
        menus_capo.opciones_lugar(p, l, app.pila[-1])            # cajero, fichas del casino y gestor (capo.py)
    if p.acompanante:
        from . import sistemas
        sistemas.visita_con_acompanante(p, l)
    if l.tipo in ("bar", "taberna") and not en_coche and app.pila and isinstance(app.pila[-1], Menu) and app.pila[-1] is not p:
        from . import sistemas
        sistemas.con_cartas(p, app.pila[-1], Menu, Opcion)


def _menu_lugar(p, l, ops, intro=None):
    m = Menu(p.app, lambda: tr('{nombre}. Tienes {dinero} euros').format(nombre=(l.nombre), dinero=(p.j.dinero)), ops, intro=intro)
    p.app.abrir(m)
    return m


def _comprar_comida(p, c, factor=1.0):
    def f():
        precio = int(c["precio"] * factor)
        con_hambre = p.vida_realista() and p.j.hambre >= 15           # con vida realista se come por hambre, aunque la salud esté entera
        if p.j.salud >= p.j.salud_max and not con_hambre:
            p.app.decir(tr("No tienes hambre: tu salud está al máximo.") if not p.vida_realista() else tr("Ahora no tienes hambre. La tecla V te dice cómo vas de hambre y de sueño."), True)
            return
        if p.pagar(precio):
            p.j.salud = min(p.j.salud_max, p.j.salud + c["salud"])
            p.son("comer", cat="interfaz")
            hambre = p.necesidades_txt()
            p.app.decir(tr('{nombre}. Salud {int}.{hambre}').format(nombre=(c['nombre']), int=(int(p.j.salud)), hambre=(hambre)), True)
    return f


# Las protecciones que se venden en la armería además del chaleco están en los datos (vida.json, protecciones).
def _proteccion(p, nombre, precio, tope):
    if p.j.blindaje >= tope:
        p.app.decir(tr("Ya llevas una protección igual o mejor, en perfecto estado."), True)
    elif p.pagar(precio):
        p.j.blindaje = float(tope)
        p.son("dinero", cat="interfaz")
        p.app.decir(tr('{nombre} puest[o|a]. Blindaje {tope}.').format(nombre=(nombre), tope=(tope)).replace("[o|a]", "a" if nombre.endswith("a") else "o"), True)


def _comprar_walkman(p):
    o = next((x for x in p.datos["objetos"] if x["id"] == "walkman"), {"nombre": tr("Reproductor con auriculares"), "precio": 75, "desc": ""})

    def f():
        if p.j.objetos.get("walkman"):
            p.app.decir(tr("Ya tienes uno. Se enciende con Mayúsculas R, a pie."), True)
        elif p.pagar(o["precio"]):
            p.j.objetos["walkman"] = 1
            p.son("dinero", cat="interfaz")
            p.app.decir(tr('{nombre} comprado. A pie, Mayúsculas R lo enciende y cambia de emisora.').format(nombre=(o['nombre'])), True)
    return Opcion(lambda: tr('{nombre}: {precio} euros').format(nombre=(o['nombre']), precio=(o['precio'])) + (tr(". Ya lo tienes") if p.j.objetos.get("walkman") else ""), f, ayuda=o.get("desc", ""))


def _comprar_objeto(p, ident):
    o = next(x for x in p.datos["objetos"] if x["id"] == ident)

    def f():
        if ident == "chaleco":
            if p.j.blindaje >= 100:
                p.app.decir(tr("Ya llevas una protección igual o mejor, en perfecto estado."), True)
            elif p.pagar(o["precio"]):
                p.j.blindaje = 100.0
                p.son("dinero", cat="interfaz")
                p.app.decir(tr("Chaleco puesto. Blindaje 100."), True)
        elif p.pagar(o["precio"]):
            p.j.objetos[ident] = p.j.objetos.get(ident, 0) + 1
            p.son("dinero", cat="interfaz")
            p.app.decir(tr('{nombre} comprado. Tienes {v}.').format(nombre=(o['nombre']), v=(p.j.objetos[ident])), True)
    return Opcion(lambda: tr('{nombre}: {precio} euros').format(nombre=(o['nombre']), precio=(o['precio'])), f, ayuda=o["desc"])


def _casa(p, l):
    app = p.app
    j = p.j
    if l.id not in j.propiedades:
        precio = int(l.get("precio", 0))

        dueno = p.sv_dueno(l)
        if dueno:                                            # en un servidor: ya es de otro jugador
            oferta = p.sv_oferta(l)
            _menu_lugar(p, l, [Opcion(tr('Esta vivienda es de {dueno}, otro jugador. ').format(dueno=(dueno)) + (tr('La vende por {oferta} euros').format(oferta=(oferta)) if oferta else tr("No está en venta")),
                               ayuda=tr("En un servidor, cada vivienda es de un solo jugador. Si su dueño la vende, aquí sale el precio."))]
                        + ([Opcion(tr('Comprársela por {oferta} euros').format(oferta=(oferta)), lambda: p.red.enviar({"t": "prop_adquirir", "lugar": l.id}),
                                   ayuda=tr("Se lo pides al servidor: si tienes el dinero y sigue en venta, la vivienda pasa a ser tuya."))] if oferta else [])
                        + [Opcion(tr("Descripción"), lambda: app.decir(l.desc, True), ayuda=tr("Dice cómo es este sitio."))])
            return

        def comprar():
            if p.pagar(precio):
                j.propiedades.append(l.id)
                p.sv_comprado(l)
                app.cerrar(m)
                app.son("mision_ok")
                app.decir(tr('¡{nombre} es tuya! Aquí puedes guardar la partida, descansar y dejar {get} vehículos.').format(nombre=(l.nombre), get=(l.get('garaje', 0))), True)
        m = _menu_lugar(p, l, [Opcion(tr('Comprar por {precio} euros').format(precio=(precio)), comprar, ayuda=l.desc)] + __import__("juego.menus_honrado", fromlist=["x"]).opcion_hipoteca(p, l, lambda: app.cerrar(m))
                        + [Opcion(tr("Descripción"), lambda: app.decir(l.desc, True), ayuda=tr("Dice cómo es este sitio."))], tr("Esta vivienda está en venta"))
        return
    if p.alquilada(l.id):                                    # vive un inquilino: solo se ve el contrato y se puede recuperar
        from . import alquiler
        alquiler.menu_alquilada(p, l, Menu, Opcion, _menu_lugar)
        return
    garaje = j.garajes.setdefault(l.id, [])

    def descansar():
        if j.estrellas:
            app.son("error")
            app.decir(tr("No puedes descansar con la policía en la puerta."), True)
            return
        p.pasar_horas(8, dormir=True)
        j.salud = j.salud_max
        p.son("pasan_horas", cat="interfaz")
        from . import sistemas
        app.decir(tr('Duermes ocho horas. Salud al máximo.{al_dormir_en_casa} Son las {hora_txt} del día {dia}.').format(al_dormir_en_casa=(sistemas.al_dormir_en_casa(p, l)), hora_txt=(p.hora_txt()), dia=(p.dia)), True)
        if l.id == j.convive_casa and j.convive:                 # has dormido en casa, con quien vive contigo
            j.convive_hoy["visto"] = p.dia
            p.peticion_cumplida("dormir")

    def esconderse():
        p.pasar_horas(3)
        p._fin_persecucion()
        p.son("pasan_horas", cat="interfaz")
        app.decir(tr('Te quedas tres horas con las persianas bajadas. La policía deja de buscarte. Son las {hora_txt}.').format(hora_txt=(p.hora_txt())), True)
        m.refrescar(False)

    def guardar_veh(v=None):
        v = v or j.veh
        if v is None or v.muerto:
            return
        if v.tag:
            app.son("error")
            app.decir(p.motivo_ajeno(v), True)
            return
        if v.modelo.get("vuela"):
            app.son("error")
            app.decir(tr("Una aeronave no cabe en el garaje de una casa: se guarda en un hangar, en un helipuerto, un aeropuerto o un aeródromo."), True)
            return
        if len(garaje) >= int(l.get("garaje", 0)):
            app.son("error")
            app.decir(tr("El garaje está lleno."), True)
            return
        garaje.append(p._ficha_garaje(v))
        if p.chofer and p.chofer.get("veh") is v:
            p.despedir_chofer(callar=True)
        if j.veh is v:
            p.salir_vehiculo(forzado=True)
            j.x, j.y = l.x, l.y
        p.quitar_vehiculo(v)
        p.ultimo_veh = None
        p.son_puerta(v)
        app.decir(tr('{nombre} guardado en el garaje.').format(nombre=(v.nombre)), True)
        m.refrescar(False)

    def sacar(k):
        def f():
            d = garaje.pop(k)
            x, y, di = p.mundo.plaza_junto_a(l)
            v = p._veh_de_dict(dict(d, rumbo=di * 90.0), x, y)
            app.cerrar(m)
            app.decir(tr('{nombre} te espera en la calle. {situar}.').format(nombre=(v.nombre), situar=(p.situar(x, y, tr('Está')))), True)
            p.hacer_mio(v)                                      # lo que sale de tu garaje es tuyo: ya no se pierde en la calle
        return f

    def nombres():
        """Ponerle nombre al vehículo que traes, al que has dejado cerca o a los del garaje."""
        from .misvehiculos import nombre_completo

        def ops_n():
            cosas = ([j.veh] if j.veh and not j.veh.tag else []) + ([p.tu_vehiculo(90)] if not j.veh and p.tu_vehiculo(90) is not None else [])
            lista = [Opcion(tr('{nombre_completo}, en la calle').format(nombre_completo=(nombre_completo(p, v.nombre, v.modelo['id']))), lambda v=v: p.renombrar_vehiculo(v, lambda: mn.refrescar(False)),
                            ayuda=tr("Intro y escribes el nombre. Si lo dejas en blanco, vuelve a llamarse como su modelo.")) for v in cosas]
            lista += [Opcion(tr('{nombre_completo}, en el garaje').format(nombre_completo=(nombre_completo(p, d.get('nombre'), d['modelo']))), lambda d=d: p.renombrar_vehiculo(d, lambda: mn.refrescar(False)),
                             ayuda=tr("Intro y escribes el nombre. Si lo dejas en blanco, vuelve a llamarse como su modelo.")) for d in garaje]
            return lista or [Opcion(tr("No hay ningún vehículo aquí al que ponerle nombre"),
                                    ayuda=tr("Ven con el vehículo, déjalo aparcado cerca o guárdalo en el garaje, y vuelve a entrar."))]
        mn = Menu(app, tr("A qué vehículo le pones nombre"), ops_n)
        app.abrir(mn)

    def ops():
        lista = []
        if not p.mision:
            lista.append(Opcion(tr("Guardar la partida"), lambda: menu_guardar(p), ayuda=tr("Elige una de las cinco ranuras para guardar la partida tal como está.")))
        if j.veh:
            lista.append(Opcion(tr('Meter {nombre} en el garaje').format(nombre=(j.veh.nombre)), guardar_veh,
                                ayuda=tr("Guardas el vehículo en el que has venido y te quedas a pie en la puerta. No caben las aeronaves ni los vehículos que no puedes quedarte, y nada si el garaje está lleno.")))
        else:
            cerca = p.tu_vehiculo(90)
            if cerca is not None:
                lista.append(Opcion(tr('Meter en el garaje {nombre}, que has dejado a {int} metros').format(nombre=(cerca.nombre), int=(int(cerca.dist(*p.pos())))), lambda: guardar_veh(cerca),
                                    ayuda=tr("Guarda el vehículo del que te has bajado, sin tener que volver a por él.")))
            lista.append(Opcion(tr("Descansar ocho horas y recuperar la salud"), descansar,
                                ayuda=tr("Pasan ocho horas y la salud se llena. No se puede mientras te busca la policía.")))
            if 0 < j.estrellas <= 2:
                lista.append(Opcion(tr("Esconderte hasta que la policía deje de buscarte"), esconderse,
                                    ayuda=tr("Pasan tres horas con las persianas bajadas y la policía deja de buscarte. Solo sale con uno o dos niveles de búsqueda.")))
        for k, d in enumerate(garaje):
            lista.append(Opcion(tr('Sacar del garaje: {get}').format(get=(d.get('nombre', d['modelo']))), sacar(k),
                                ayuda=tr("El vehículo sale a la calle, aparcado junto a la casa. Sigue siendo tuyo: no se pierde aunque te alejes.")))
        if garaje or j.veh or p.tu_vehiculo(90) is not None:
            lista.append(Opcion(tr("Ponerle nombre a un vehículo"), nombres,
                                ayuda=tr("Bautiza el vehículo que traes o cualquiera de los del garaje. El juego dirá ese nombre al subir, al localizarlo y en las listas.")))
        lista.append(Opcion(tr('Garaje: {len} de {get} plazas ocupadas').format(len=(len(garaje)), get=(l.get('garaje', 0))),
                            ayuda=tr("Para guardar un vehículo, ven con él hasta la puerta y pulsa Intro sin bajarte, o déjalo aparcado cerca y entra: la opción de meterlo sale en este menú. "
                                  "También puedes mandarlo desde el móvil, en Mis vehículos o en Servicios. Para sacar uno, elige Sacar del garaje. "
                                  "Lo que sacas de aquí sigue siendo tuyo en la calle: no desaparece, y lo tienes en el móvil, en Mis vehículos.")))
        if j.perro and j.perro_en_casa:
            lista.append(Opcion(tr('{perro} te espera en casa: llévatelo contigo').format(perro=(j.perro)), lambda: (p.llamar_perro(), m.refrescar(False)),
                                ayuda=tr("Sale de casa y vuelve a ir contigo.")))
        elif j.perro and p.perro() is not None:
            lista.append(Opcion(tr('Dejar a {perro} en casa').format(perro=(j.perro)), lambda: (p.mandar_perro_a_casa(l), m.refrescar(False)), ayuda=tr("Se queda aquí, con comida y agua, hasta que vuelvas a por él o lo llames desde el móvil.")))
        from . import convivencia, domicilio, laboratorio, sistemas
        lista += convivencia.opciones_casa(p, l, Menu, Opcion)
        if not p.domicilio_motivo() or j.pedido:
            lista.append(Opcion(lambda: tr("Pedir comida a domicilio") + (": " + p.pedido_txt() if j.pedido else ""), lambda: domicilio.menu_domicilio(p),
                                ayuda=tr("Eliges de la carta, pagas el pedido y el envío, y al rato llaman al timbre. Quita el hambre y la sed de la vida realista y da algo de salud. "
                                      "Mientras estás en este menú el tiempo no corre: sal a la puerta y espera cerca.")))
        from . import menus_cocina
        lista += menus_cocina.opcion_casa(p, l)
        puestos = len(sistemas.muebles_de(j, l))
        cuantos = sum(1 for mu in sistemas.MUEBLES if mu[1] != "garaje" or int(l.get("garaje", 0)))
        lista.append(Opcion(tr('Amueblar la casa: {puestos} de {cuantos} cosas puestas').format(puestos=(puestos), cuantos=(cuantos)), lambda: sistemas.menu_muebles(p, l, Menu, Opcion),
                            ayuda=tr("Un sofá, una cocina nueva, una cama de las buenas, una bañera, plantas y cuadros, y un banco de herramientas si la casa tiene garaje. "
                                  "Cada cosa mejora lo que haces en su habitación al recorrer la casa por dentro, o lo que descansas al dormir.")))
        lista += laboratorio.opciones_casa(p, l, Menu, Opcion)
        from . import mochila, vestuario
        lista.append(Opcion(lambda: tr('Vestirte: {aspecto_txt}').format(aspecto_txt=(p.aspecto_txt())), lambda: vestuario.menu_vestirte(p, l),
                            ayuda=tr("Tu ropa, tu calzado y tus complementos: todo lo que has comprado alguna vez. Te lo pones sin pagar. "
                                  "Cambiarte de ropa despista a la policía si te busca poco y no hay agentes cerca.")))
        lista.append(Opcion(lambda: tr('Armario: {almacen_txt}').format(almacen_txt=(p.almacen_txt(l.id))), lambda: mochila.menu_armario(p, l),
                            ayuda=tr("Guarda aquí objetos de la mochila, mercancía y armas, y sácalos cuando los necesites. "
                                  "Lo que está en casa no te lo quita la policía ni se pierde si te tumban.")))
        from . import alquiler
        lista += alquiler.opciones_casa(p, l, Menu, Opcion, lambda: app.cerrar(m))
        lista += __import__("juego.menus_enlinea", fromlist=["x"]).opciones_propiedad(p, l)
        if not j.veh:
            lista.append(Opcion(tr("Recorrer la casa por dentro"), recorrer,
                                ayuda=tr("Entras y vas de una habitación a otra con las flechas: salón, cocina, baño, dormitorio y garaje. En cada una, Intro hace lo suyo. "
                                      "En la cocina se guarda la compra, se abre la nevera y la despensa, y se cocina.")))
        return lista

    def recorrer():
        from . import sistemas
        app.son("puerta_entrar")
        app.abrir(sistemas.Interior(p, l, {"descansar": descansar, "garaje": lambda: app.decir(
            tr('Garaje: {len} de {get} plazas ocupadas').format(len=(len(garaje)), get=(l.get('garaje', 0))) + ("." if not garaje else ": " + ", ".join(d.get("nombre", d["modelo"]) for d in garaje) + ".") +
            tr(" Para sacar un vehículo, usa el menú de la casa."), True)}))
    m = _menu_lugar(p, l, ops, p.saludo_de_casa(l) or None)


SIN_SILENCIADOR = ("escopeta", "escopeta_combate", "ametralladora", "minigun", "lanzacohetes", "ballesta")


def donde_se_vende(a):
    """El tipo de local donde se compra un arma: lo dicen sus datos. Si no dicen nada, en la armería."""
    return a.get("donde") or "armeria"


def armas_en_venta(p, l, factor=1.0):
    """Las armas que se venden en un local que no es una armería (una tienda, una casa de empeños), y su munición."""
    j = p.j

    def comprar(a):
        def f():
            if a["id"] not in j.armas:
                if p.pagar(int(a["precio"] * factor)):
                    p.dar_arma(a["id"], a.get("balas", 0))
                    p.son("dinero", cat="interfaz")
            elif a["tipo"] == "cuerpo":
                p.app.decir(tr('Ya tienes {nombre}.').format(nombre=(a['nombre'])), True)
            elif p.pagar(int(a.get("precio_balas", 0) * factor)):
                j.armas[a["id"]]["reserva"] += a.get("balas", 0)
                p.son("recarga", cat="interfaz")
                p.app.decir(tr('Munición comprada. Reserva: {reserva} balas.').format(reserva=(j.armas[a['id']]['reserva'])), True)
        return f

    def texto(a):
        def f():
            if a["id"] not in j.armas:
                return tr('{nombre}: {int} euros. {capitalize}').format(nombre=(a['nombre']), int=(int(a['precio'] * factor)), capitalize=(ficha_corta(a).capitalize()))
            if a["tipo"] == "cuerpo":
                return tr('{nombre}: ya la tienes').format(nombre=(a['nombre']))
            return tr('Munición para {nombre}, {get} balas: {int} euros. Tienes {reserva} de reserva').format(nombre=(a['nombre']), get=(a.get('balas', 0)), int=(int(a.get('precio_balas', 0) * factor)), reserva=(j.armas[a['id']]['reserva']))
        return f
    return [Opcion(texto(a), comprar(a), ayuda=ayuda_arma(a)) for a in p.datos["armas"] if a.get("precio", 0) > 0 and donde_se_vende(a) == l.tipo]


def _armeria(p, l):
    app = p.app
    j = p.j
    factor = float(l.get("descuento", 1.0)) * p.mercado("armas", l.id)

    def comprar(a):
        def f():
            if a["id"] not in j.armas:
                if p.pagar(int(a["precio"] * factor)):
                    p.dar_arma(a["id"], a.get("balas", 0))
                    p.son("dinero", cat="interfaz")
                    m.refrescar(False)
            else:
                if p.pagar(int(a["precio_balas"] * factor)):
                    j.armas[a["id"]]["reserva"] += a["balas"]
                    p.son("recarga", cat="interfaz")
                    app.decir(tr('Munición comprada. Reserva: {reserva} balas.').format(reserva=(j.armas[a['id']]['reserva'])), True)
        return f

    def mejorar(a, cual, precio):
        def f():
            if p.pagar(int(precio * factor)):
                j.armas[a["id"]][cual] = True
                p.son("recarga", cat="interfaz")
                app.decir(tr('{v} montado en {nombre}.').format(v=(tr('Silenciador') if cual == 'silenciador' else tr('Cargador ampliado')), nombre=(a['nombre'])), True)
                m.refrescar(False)
        return f

    def ops():
        lista = []
        for a in p.datos["armas"]:
            if a["precio"] <= 0:
                continue
            if a["id"] not in j.armas:
                if donde_se_vende(a) != "armeria":               # esa se compra en otro tipo de local; aquí, solo su munición
                    continue
                lista.append(Opcion(tr('{nombre}: {int} euros. {capitalize}').format(nombre=(a['nombre']), int=(int(a['precio'] * factor)), capitalize=(ficha_corta(a).capitalize())), comprar(a), ayuda=ayuda_arma(a)))
            elif a["tipo"] in ("fuego", "explosivo"):
                from .combate import unidad
                lista.append(Opcion(tr('Munición para {nombre}, {balas} {unidad}: {int} euros. Tienes {reserva} de reserva').format(nombre=(a['nombre']), balas=(a['balas']), unidad=(unidad(a, a['balas'])), int=(int(a['precio_balas'] * factor)), reserva=(j.armas[a['id']]['reserva'])), comprar(a), ayuda=ayuda_arma(a)))
        for a in p.datos["armas"]:                              # mejoras para las armas de fuego que ya tienes
            if a["id"] in j.armas and a["tipo"] == "fuego":
                mio = j.armas[a["id"]]
                if not mio.get("silenciador") and a.get("ruido", 2) > 0 and a["id"] not in SIN_SILENCIADOR and not a.get("sin_silenciador"):
                    lista.append(Opcion(tr('Silenciador para {nombre}: {int} euros').format(nombre=(a['nombre']), int=(int(p.precio('silenciador', 900) * factor))), mejorar(a, "silenciador", p.precio("silenciador", 900)),
                                        ayuda=tr("Los disparos dejan de oírse desde lejos: la gente no huye y nadie llama a la policía por el ruido. Lo que hagas a la vista de alguien se sigue viendo. Se pierde con el arma si te detienen.")))
                if not mio.get("ampliado") and a.get("cargador", 0) > 1:
                    lista.append(Opcion(tr('Cargador ampliado para {nombre}, de {cargador} a {int} balas: {int2} euros').format(nombre=(a['nombre']), cargador=(a['cargador']), int=(int(a['cargador'] * 1.5)), int2=(int(p.precio('cargador_ampliado', 600) * factor))), mejorar(a, "ampliado", p.precio("cargador_ampliado", 600)),
                                        ayuda=tr("Caben la mitad más de balas, así que recargas menos veces. Se pierde con el arma si te detienen.")))
        lista.append(_comprar_objeto(p, "chaleco"))
        for pr in p.datos.get("protecciones", []):
            lista.append(Opcion(tr('{nombre}: {int} euros').format(nombre=(pr['nombre']), int=(int(pr['precio'] * factor))),
                                (lambda pr=pr: _proteccion(p, pr["nombre"], int(pr["precio"] * factor), int(pr.get("blindaje", 100)))), ayuda=pr.get("desc", "")))
        lista.append(_comprar_objeto(p, "ganzua"))
        lista.append(Opcion(tr('Galería de tiro: {precio} euros la tanda').format(precio=(p.precio('galeria_tiro', 20))), tiro, ayuda=tr("Diez dianas que suenan a la izquierda, al centro o a la derecha. Mejora tu puntería y da premio con siete aciertos.")))
        return lista

    def tiro():
        if p.pagar(p.precio("galeria_tiro", 20)):
            from .pantallas import TiroAlBlanco
            while len(app.pila) > 1 and app.pila[-1] is not p:
                app.pila.pop()
            app.abrir(TiroAlBlanco(app, p))
    m = _menu_lugar(p, l, ops, tr("F1 describe cada arma"))


def tiene_surtidor_rueda(p, l):
    """Las gasolineras venden ruedas de repuesto cuando las averías están activadas."""
    from . import combustible as C
    return C.tiene_surtidor(l) and p.averias_activas()


def _surtidor(p, l):
    """Las opciones del surtidor de una gasolinera, con el combustible activado."""
    from . import combustible as C
    if not (C.tiene_surtidor(l) and p.combustible_activo()):
        return []
    app = p.app
    pl = C.precio_litro(l)

    def echar(litros):
        def f():
            v = p.vehiculo_para_repostar()
            if v is None or C.deposito(v.modelo) <= 0:
                app.son("error")
                app.decir(tr("No tienes aquí ningún vehículo que reposte. Ven con él, o déjalo aparcado al lado."), True)
                return
            n = p.repostar(v, litros, precio=pl)
            if n:
                app.decir(tr('{int} litros a {nombre}: {max} euros.{combustible_txt}').format(int=(int(round(n))), nombre=(v.nombre), max=(max(1, int(round(n * pl)))), combustible_txt=(p.combustible_txt(v))), True)
            elif C.capacidad(v) - p.litros(v) < 0.5:
                app.decir(tr("El depósito ya está lleno."), True)
        return f

    def bidon():
        if p.pagar(C.PRECIO_BIDON):
            p.j.objetos["bidon"] = p.j.objetos.get("bidon", 0) + 1
            p.son("dinero", cat="interfaz")
            app.decir(tr('Bidón de gasolina comprado. Llevas {bidon}.').format(bidon=(p.j.objetos['bidon'])), True)

    def cuanto():
        v = p.vehiculo_para_repostar()
        if v is None or C.deposito(v.modelo) <= 0:
            return tr("Llenar el depósito: ven con tu vehículo o déjalo aparcado al lado")
        hueco = C.capacidad(v) - p.litros(v)
        return tr('Llenar el depósito de {nombre}: {int} litros, {int2} euros').format(nombre=(v.nombre), int=(int(round(hueco))), int2=(int(round(hueco * pl))))
    return [Opcion(cuanto, echar(None), ayuda=tr("Llena el depósito del vehículo que llevas o del que has dejado aparcado al lado. Se paga al momento.")),
            Opcion(tr('Echar diez litros: {int} euros').format(int=(int(round(10 * pl)))), echar(10),
                   ayuda=tr("Echa diez litros al vehículo que llevas o al que has dejado aparcado al lado, o lo que quepa si falta menos. Se paga al momento.")),
            Opcion(lambda: tr('Bidón de gasolina de {LITROS_BIDON} litros: {PRECIO_BIDON} euros. Llevas {get}').format(LITROS_BIDON=(C.LITROS_BIDON), PRECIO_BIDON=(C.PRECIO_BIDON), get=(p.j.objetos.get('bidon', 0))), bidon,
                   ayuda=tr("Para llevarlo encima. Si te quedas tirado, se lo echas al depósito desde el móvil, en Servicios."))]


def _tienda(p, l):
    app = p.app
    j = p.j

    def atracar():
        p.atracar_local(l)                                       # el mismo atraco que el de cualquier local con caja (atracos.py)
    factor = p.mercado("comida", l.id)
    ops = _surtidor(p, l) + _agua(p)
    if tiene_surtidor_rueda(p, l):
        from . import realismo as R

        def repuesto():
            if p.pagar(int(R.aj("precio_rueda"))):
                j.objetos["rueda"] = j.objetos.get("rueda", 0) + 1
                p.son("dinero", cat="interfaz")
                app.decir(tr('Rueda de repuesto comprada. Llevas {rueda}.').format(rueda=(j.objetos['rueda'])), True)
        ops.append(Opcion(lambda: tr('Rueda de repuesto: {int} euros. Llevas {get}').format(int=(int(R.aj('precio_rueda'))), get=(j.objetos.get('rueda', 0))), repuesto,
                          ayuda=tr("Si pinchas, la cambias tú desde el móvil, en Servicios, con el vehículo parado.")))
    ops += [Opcion(lambda c=c: tr('{nombre}, recupera {salud} de salud: {int} euros').format(nombre=(c['nombre']), salud=(c['salud']), int=(int(c['precio'] * factor))), _comprar_comida(p, c, factor),
                  ayuda=tr("Comes al momento y recuperas esa salud. Con la salud al máximo no comes, salvo que tengas hambre con la vida realista.")) for c in p.datos["comidas"][:3:2]]
    from . import menus_cocina
    ops += menus_cocina.opcion_rapida(p, l)                      # la comida para casa: lo mismo que en los pasillos, sin pasear
    ops += [_comprar_objeto(p, "botiquin"), _comprar_objeto(p, "ganzua"), _comprar_walkman(p)] + armas_en_venta(p, l) + ([_comprar_objeto(p, "pienso")] if p.j.perro else []) + [__import__("juego.loteria", fromlist=["x"]).opcion_en_local(p, l), Opcion(tr("Atracar la tienda"), atracar, ayuda=tr("Necesitas un arma de fuego en la mano. La policía te buscará, y la tienda te recuerda: durante unos días no te dejan entrar."))]
    m = _menu_lugar(p, l, ops)


def _salud_intima(p):
    """Opciones de farmacias y hospitales del contenido para adultos."""
    if not p.modo_adulto():
        return []
    art = p.articulos_intimos()[0]
    return [Opcion(lambda: tr('{nombre}: {precio} euros. Llevas {get}').format(nombre=(art['nombre']), precio=(art['precio']), get=(p.j.intimos.get('preservativos', 0))), lambda: p.comprar_articulo(art), ayuda=art["desc"]),
            Opcion(tr('Prueba de salud sexual, gratis. El tratamiento, si hace falta, {precio} euros').format(precio=(p.precio('tratamiento_its', 120))), p.prueba_y_tratamiento,
                   ayuda=tr("La prueba es gratis. Si da positivo, pagas el tratamiento en el acto y te curas en unos días."))]


def _farmacia(p, l):
    _menu_lugar(p, l, [_comprar_objeto(p, "botiquin")] + _salud_intima(p))


def _agua(p):
    """Con la vida realista, en cualquier sitio donde se come o se compra se puede beber agua."""
    if not p.vida_realista():
        return []

    def f():
        if p.j.sed < 15:
            p.app.decir(tr("Ahora no tienes sed."), True)
        elif p.pagar(p.precio("agua", 1)):
            p.son("beber", cat="interfaz")
            p.app.decir(tr("Una botella de agua fresca.") + p.necesidades_txt(), True)
    return [Opcion(tr('Botella de agua: {precio} euros').format(precio=(p.precio('agua', 1))), f, ayuda=tr("Quita la sed. La comida también quita algo, pero menos."))]


def _comida(p, l):
    factor = (3.0 if l.get("caro") else 1.0) * p.mercado("comida", l.id)
    ops = [Opcion(lambda c=c: tr('{nombre}, recupera {salud} de salud: {int} euros').format(nombre=(c['nombre']), salud=(c['salud']), int=(int(c['precio'] * factor))), _comprar_comida(p, c, factor),
                  ayuda=tr("Comes al momento y recuperas esa salud. Con la salud al máximo no comes, salvo que tengas hambre con la vida realista.")) for c in p.datos["comidas"]]
    ops += _agua(p)
    if l.tipo == "pizzeria":
        def trabajar():
            p.app.cerrar(m)
            p.empezar_pizzas()
        ops.append(Opcion(tr("Trabajar repartiendo pizzas"), trabajar, ayuda=tr("Cuatro entregas contrarreloj. Cuanto antes llegues, más propina.")))
    m = _menu_lugar(p, l, ops)


def _hospital(p, l):
    j = p.j

    def curar():
        falta = int(j.salud_max - j.salud)
        if falta <= 0:
            p.app.decir(tr("Estás como una rosa. No necesitas nada."), True)
        elif p.pagar(falta * p.precio("cura_punto", 2)):
            j.salud = j.salud_max
            p.son("curar", cat="interfaz")
            p.app.decir(tr("Te curan. Salud al máximo."), True)
    ops = [Opcion(lambda: tr('Que te curen: {v} euros. Salud actual {int}').format(v=(max(0, int(j.salud_max - j.salud)) * p.precio('cura_punto', 2)), int=(int(j.salud))), curar,
                  ayuda=tr("Te dejan la salud al máximo. Pagas por cada punto que te falta; si no te falta ninguno, no pagas nada.")), _comprar_objeto(p, "botiquin")]
    if p.modo_adulto():
        from . import menus_adultos as ma
        ops.append(Opcion(tr('Desintoxicación: {precio} euros y dos días en la clínica').format(precio=(p.precio('desintoxicacion', 800))), lambda: ma.desintoxicar(p), ayuda=tr("Elimina todas tus dependencias.")))
        ops += _salud_intima(p)
    _menu_lugar(p, l, ops)


def _comisaria(p, l):
    j = p.j

    def sobornar():
        if not j.estrellas:
            p.app.decir(tr("No te busca nadie."), True)
            return
        if p.pagar(p.precio("soborno_estrella", 400) * j.estrellas):
            p._fin_persecucion()
            p.app.decir(tr("Un sobre cambia de manos y tu expediente desaparece. Ya no te buscan."), True)
    from . import agente
    m = _menu_lugar(p, l, lambda: [Opcion(lambda: tr('Pagar un soborno para que dejen de buscarte: {v} euros').format(v=(p.precio('soborno_estrella', 400) * j.estrellas)), sobornar,
                                          ayuda=tr("Pagas por cada nivel de búsqueda que tienes y la policía deja de buscarte al momento. Si no te busca nadie, no pagas.")),
                                   Opcion(lambda: tr('Tu historial: {detenciones} detenciones').format(detenciones=(j.stats['detenciones'])), ayuda=tr("Cuántas veces te han detenido en toda la partida.")),
                                   Opcion(lambda: tr("Antecedentes penales. ") + p.hon_antecedentes_txt(), lambda: __import__("juego.menus_honrado", fromlist=["x"]).menu_antecedentes(p, l),
                                          ayuda=tr("Lo que consta en tu ficha, cuándo caduca y cómo atenuarlo: servicios a la comunidad o un abogado."))] + agente.opciones_comisaria(p, l, Menu, Opcion, lambda: m.refrescar(False)))


def _taller(p, l):
    app = p.app
    j = p.j
    if not j.veh:
        if p.local_atracable(l):                                 # a pie no hay nada que reparar, pero la caja está ahí
            _menu_lugar(p, l, [Opcion(tr("Ven con un vehículo para repararlo, pintarlo o mejorarlo"),
                                      ayuda=tr("A pie no hay nada que reparar. Vuelve conduciendo el vehículo y párate en la puerta."))])
        else:
            app.decir(tr('{nombre}. Ven con un vehículo para repararlo o pintarlo.').format(nombre=(l.nombre)), True)
        return
    v = j.veh

    def coste():
        return int(p.precio("reparacion_base", 40) + (1 - v.salud / v.salud_max) * max(300, v.modelo["valor"]) * 0.3)

    def reparar():
        if v.salud >= v.salud_max:
            app.decir(tr("El vehículo está perfecto."), True)
        elif p.pagar(coste()):
            v.salud = v.salud_max
            p.son("reparar", cat="interfaz")
            app.decir(tr("Vehículo reparado al 100 por ciento."), True)

    def pintar():
        x, y = p.pos()
        if any(e.tipo == "policia" and not e.muerto and e.dist(x, y) < 45 for e in p.personas) or any(p.es_patrulla(o) and o.dist(x, y) < 45 for o in p.vehiculos):
            app.son("error")
            app.decir(tr("¡Tienes a la policía encima! Despístalos un poco antes de pintar."), True)
            return
        if p.pagar(p.precio("pintura", 300)):
            p.son("pintura", cat="interfaz")
            p._fin_persecucion()
            app.decir(tr("Pintura nueva y matrículas nuevas. La policía ya no busca este vehículo."), True)
    from . import realismo as R
    from . import sistemas

    def rueda():
        if not getattr(v, "pinchada", False):
            app.decir(tr("No tiene ninguna rueda pinchada."), True)
        elif p.pagar(int(R.aj("precio_cambio_rueda"))):
            v.pinchada = False
            p.son("reparar", cat="interfaz")
            app.decir(tr("Rueda cambiada. Vuelve a rodar bien."), True)

    def revision():
        if p.pagar(int(R.aj("precio_revision"))):
            p.pasar_revision(v)
            p.son("reparar", cat="interfaz")
            app.decir(tr('Revisión pasada: aceite, frenos y ruedas. {nombre} queda como debe.').format(nombre=(v.nombre)), True)

    def nombre():
        if v.tag:
            app.son("error")
            app.decir(p.motivo_ajeno(v), True)
        else:
            p.renombrar_vehiculo(v)

    def repuesto():
        if p.pagar(int(R.aj("precio_rueda"))):
            j.objetos["rueda"] = j.objetos.get("rueda", 0) + 1
            p.son("dinero", cat="interfaz")
            app.decir(tr('Rueda de repuesto comprada. Llevas {rueda}.').format(rueda=(j.objetos['rueda'])), True)
    averias = [Opcion(lambda: tr('Cambiar la rueda pinchada: {int} euros').format(int=(int(R.aj('precio_cambio_rueda')))) if getattr(v, "pinchada", False) else tr("Ruedas: ninguna pinchada"), rueda,
                      ayuda=tr("Si tu vehículo tiene una rueda pinchada, te la cambian y vuelve a rodar bien. Si no, no pagas nada.")),
               Opcion(lambda: tr('Pasar la revisión: {int} euros. Lleva {int2} kilómetros').format(int=(int(R.aj('precio_revision'))), int2=(int(getattr(v, 'km', 0)))) + (tr(". Le toca") if getattr(v, "revision_debida", False) else ""), revision,
                      ayuda=tr("Aceite, frenos y ruedas. Si le toca y no la pasas, los frenos van perdiendo. Arregla también un pinchazo.")),
               Opcion(lambda: tr('Rueda de repuesto: {int} euros. Llevas {get}').format(int=(int(R.aj('precio_rueda'))), get=(j.objetos.get('rueda', 0))), repuesto,
                      ayuda=tr("Para llevarla encima. Si pinchas, la cambias tú desde el móvil, en Servicios, con el vehículo parado."))] if p.averias_activas() else []
    _menu_lugar(p, l, [Opcion(lambda: tr('Reparar {nombre}: {coste} euros. Estado {int} por ciento').format(nombre=(v.nombre), coste=(coste()), int=(int(100 * v.salud / v.salud_max))), reparar,
                              ayuda=tr("Lo dejan al 100 por ciento. Cuanto más dañado está y más vale, más cuesta.")),
                       Opcion(tr('Pintar y cambiar matrículas: {precio} euros. Elimina la búsqueda policial').format(precio=(p.precio('pintura', 300))), pintar,
                              ayuda=tr("Pintura y matrículas nuevas: la policía deja de buscarte y de buscar este vehículo. No se puede con agentes o una patrulla cerca."))] + averias + sistemas.opciones_taller(p, v, Opcion) +
                [Opcion(lambda: tr('Ponerle nombre: se llama {nombre}').format(nombre=(v.nombre)), nombre,
                        ayuda=tr("Bautiza este vehículo, gratis. El juego dirá ese nombre al subir, al localizarlo y en las listas, y el vehículo queda a tu nombre: ya no se pierde en la calle.")),
                 Opcion(lambda: sistemas.resumen(v) + p.averias_txt(v) + ("" if p.puede_ser_mio(v) or p.en_servidor else ". " + p.motivo_ajeno(v) if v.tag else ""),
                        ayuda=tr("Las mejoras que lleva este vehículo y sus averías, si tiene. Intro lo vuelve a leer."))])


def _desguace(p, l):
    app = p.app
    j = p.j
    if not j.veh:
        def encargo():
            if p.mision or p.trabajo:
                app.son("error")
                app.decir(tr("Termina antes lo que tienes entre manos."), True)
            else:
                p.empezar_encargo_coche(l)
        _menu_lugar(p, l, [Opcion(tr("Pedir un encargo de coche"), encargo, ayuda=tr("Te piden un modelo concreto: róbalo donde te digan y tráelo en buen estado. Se puede repetir siempre que quieras.")),
                           Opcion(tr("Para vender un vehículo, ven montado en él"),
                                  ayuda=tr("Aquí compran vehículos para despiece. Vuelve montado en el que quieras vender y te dicen cuánto dan."))])
        return
    v = j.veh
    from . import desguace

    def precio():
        return desguace.precio(p, v)

    def vender():
        if v.tag:
            app.son("error")
            app.decir(p.motivo_ajeno(v), True)
            return
        if desguace.cupo_lleno(p, l):
            app.son("error")
            app.decir(desguace.frase_lleno(), True)
            return
        dicho = desguace.comentario(p, v)
        n = precio()
        if n <= 0:
            app.son("error")
            app.decir(tr("Eso no lo quieren ni regalado."), True)
            return
        app.cerrar(m)
        if p.chofer and p.chofer.get("veh") is v:
            p.despedir_chofer(callar=True)
        p.salir_vehiculo(forzado=True)
        p.quitar_vehiculo(v)
        j.x, j.y = l.x, l.y
        j.stats["vendidos"] += 1
        desguace.apuntar_venta(p, l, v)
        if dicho:
            p.decir(dicho)
        p.dar_dinero(n, tr('Vendes {nombre}').format(nombre=(v.nombre)))
    m = _menu_lugar(p, l, [Opcion(lambda: tr('Vender {nombre} por {precio} euros').format(nombre=(v.nombre), precio=(precio())), vender,
                                  ayuda=tr("Te pagan al momento y el vehículo desaparece. Dan más cuanto más vale y mejor está, y menos si es robado o si ya les has vendido otros del mismo modelo. Cada desguace compra unos pocos al día."))])


def _negocio(p, l):
    app = p.app
    j = p.j
    precio = int(l.get("precio", 0))
    ingresos = int(l.get("ingresos", 0))
    if l.id in j.propiedades:
        mm = _menu_lugar(p, l, lambda: [
            Opcion(lambda: tr('Es tuyo. Da {ingreso_negocio} euros cada día, a medianoche').format(ingreso_negocio=(p.ingreso_negocio(l))),
                   ayuda=tr("Lo que te da este negocio cada medianoche, según cómo lo cobres. Puede subir o bajar según lo atiendas.")),
            Opcion(lambda: tr('Forma de cobro de todos tus negocios: {cobro_txt}').format(cobro_txt=(p.cobro_txt())), lambda: (p.cambiar_cobro(), mm.refrescar(False)),
                   ayuda=tr("Intro cambia entre las tres formas: que te lo traigan en mano cada medianoche, que te lo ingresen en el banco, o venir tú a recogerlo, con un diez por ciento más.")),
        ] + ([Opcion(lambda: tr('Recoger la caja: {int} euros').format(int=(int(j.cajas.get(l.id, 0)))), lambda: (p.recoger_caja(l), mm.refrescar(False)),
                     ayuda=tr("Te llevas lo que hay en la caja, con un diez por ciento más por venir en persona. En la caja caben siete días."))] if j.cobro_negocios == "recoger" else [])
            + __import__("juego.menus_honrado", fromlist=["x"]).opciones_negocio(p, l, lambda: mm.refrescar(False))
            + __import__("juego.menus_enlinea", fromlist=["x"]).opciones_propiedad(p, l))
        return

    dueno = p.sv_dueno(l)
    if dueno:                                                # en un servidor: el negocio es de otro jugador, y se le puede atracar
        oferta = p.sv_oferta(l)
        _menu_lugar(p, l, [
            Opcion(tr('Este negocio es de {dueno}, otro jugador. ').format(dueno=(dueno)) + (tr('Lo vende por {oferta} euros').format(oferta=(oferta)) if oferta else tr("No está en venta")),
                   ayuda=tr("En un servidor, cada negocio es de un solo jugador. Si su dueño lo vende, aquí sale el precio.")),
        ] + ([Opcion(tr('Comprárselo por {oferta} euros').format(oferta=(oferta)), lambda: p.red.enviar({"t": "prop_adquirir", "lugar": l.id}),
                    ayuda=tr("Se lo pides al servidor: si tienes el dinero y sigue en venta, el negocio pasa a ser tuyo."))] if oferta else []) + [
            Opcion(tr("Atracar el negocio"), lambda: (__import__("juego.menus_extra", fromlist=["x"])._volver_al_juego(p), p.sv_robar_negocio(l)),
                   ayuda=tr('Con un arma en la mano. Salta la alarma, a {dueno} y a su banda les llega el aviso, y tienes que aguantar en la puerta veinte segundos, a pie y sin alejarte. Si lo consigues te llevas la caja del día, {ingresos} euros, que a él se le descuentan a medianoche. A cada negocio solo se le puede vaciar la caja una vez al día.').format(dueno=(dueno), ingresos=(ingresos))),
            Opcion(tr("Descripción"), lambda: app.decir(l.desc, True), ayuda=tr("Dice cómo es este sitio."))])
        return

    def comprar():
        if p.pagar(precio):
            j.propiedades.append(l.id)
            p.sv_comprado(l)
            app.cerrar(m)
            app.son("mision_ok")
            app.decir(tr('¡{nombre} es tuyo! Ganarás {ingresos} euros cada día.').format(nombre=(l.nombre), ingresos=(ingresos)), True)
    m = _menu_lugar(p, l, [Opcion(tr('Comprar el negocio por {precio} euros. Da {ingresos} euros al día').format(precio=(precio), ingresos=(ingresos)), comprar, ayuda=l.desc)]
                    + __import__("juego.menus_honrado", fromlist=["x"]).opcion_hipoteca(p, l, lambda: app.cerrar(m)))


def _taxi(p, l):
    app = p.app

    def alquilar():
        if p.pagar(p.precio("alquiler_taxi", 40)):
            x, y, d = p.mundo.plaza_junto_a(l)
            v = p.crear_vehiculo("taxi", x, y, d, None)
            v.propio = True
            app.cerrar(m)
            app.decir(tr('Tienes un taxi en la calle. {situar}. Sube con F y pulsa J para empezar a hacer carreras.').format(situar=(p.situar(x, y, tr('Está')))), True)

    def viajar():
        if p.j.estrellas or p.mision:
            app.son("error")
            app.decir(tr("Ahora mismo ningún taxista quiere llevarte."), True)
            return
        app.cerrar(m)
        menu_viaje(p)
    m = _menu_lugar(p, l, [Opcion(tr("Que te lleven a otro lugar"), viajar,
                                  ayuda=tr("Eliges el destino y el taxi te lleva. El precio depende de la distancia, y pasa el tiempo del viaje. No te llevan si te busca la policía ni durante una misión.")),
                           Opcion(tr('Alquilar un taxi para trabajar de taxista: {precio} euros').format(precio=(p.precio('alquiler_taxi', 40))), alquilar,
                                  ayuda=tr("Te dejan un taxi aparcado en la calle. Súbete con F y pulsa J para empezar a hacer carreras y cobrar por cada una."))])


def _carrera(p, l):
    app = p.app
    if not p.j.veh:
        app.decir(tr('{nombre}. Ven con un vehículo si quieres correr.').format(nombre=(l.nombre)), True)
        return

    def correr(c):
        def f():
            app.cerrar(m)
            p.empezar_carrera(c)
        return f
    ops = [Opcion(tr('{nombre}: premio de {premio} euros, {tiempo} segundos').format(nombre=(c['nombre']), premio=(c['premio']), tiempo=(c['tiempo'])) + (tr(", ya ganada") if c["id"] in p.j.stats["carreras"] else ""), correr(c),
                  ayuda=tr("Empieza al momento: pasa por los puntos de control antes de que se acabe el tiempo. La primera vez que la ganas cobras el premio entero; las siguientes, un tercio."))
           for c in p.datos["carreras"] if c.get("mapa", "puerto_bravo") == p.mundo.id]
    m = _menu_lugar(p, l, ops or [Opcion(tr("Hoy no hay carreras"), ayuda=tr("En esta localidad no se corre ninguna carrera."))])


def _periodico(p, l):
    n = len(p.completadas)
    titulares = [tr("Hoy en El Faro: el Ayuntamiento promete arreglar el reloj de la plaza por decimoquinta vez."),
                 tr("Hoy en El Faro: suben los robos de coches en el Barrio Viejo."),
                 tr("Hoy en El Faro: tiroteo en el puerto, la policía no encuentra testigos."),
                 tr("Hoy en El Faro: ¿quién paga a Los Calaveras? Una investigación de Marta Salgado."),
                 tr("Hoy en El Faro: el empresario Octavio Belmonte niega cualquier relación con el crimen organizado."),
                 tr("Hoy en El Faro: atraco millonario en el Casino Belmonte."),
                 tr("Hoy en El Faro: el comisario Varela, detenido. Las grabaciones que hunden a Belmonte."),
                 tr("Hoy en El Faro: Puerto Bravo respira. Belmonte, a disposición judicial.")]
    p.app.decir(f"{l.nombre}. {titulares[min(len(titulares) - 1, n * len(titulares) // 21)]}", True)


def _bar(p, l):
    app = p.app
    j = p.j

    def beber():
        if p.pagar(p.precio("cana_tapa", 4)):
            p.ha_bebido(50)
            j.salud = min(j.salud_max, j.salud + 10)
            p.son("comer", cat="interfaz")
            app.decir(tr('Una caña y una tapa. Salud {int}.').format(int=(int(j.salud))), True)

    def hablar():
        app.decir(tr("Encarna: ") + p.objetivo_txt(sugerir=True), True)
    from . import loteria
    ops = [Opcion(tr('Tomar una caña con tapa: {precio} euros').format(precio=(p.precio('cana_tapa', 4))), beber, ayuda=tr("Recuperas diez de salud y, con la vida realista, se te quita casi toda la sed.")),
           Opcion(tr("Hablar con Encarna"), hablar, ayuda=tr("Encarna te dice qué tienes que hacer ahora o por dónde deberías pasarte.")), loteria.opcion_en_local(p, l)]
    if p.modo_adulto():
        ops.insert(1, Opcion(tr('Tomar una copa: {precio} euros').format(precio=(p.precio('copa_bar', 6))), lambda: p.consumir("alcohol", de_inventario=False) if p.pagar(p.precio("copa_bar", 6)) else None, ayuda=tr("Alcohol: sube el ánimo, pero caminas torcido y apuntas peor.")))
    _menu_lugar(p, l, ops)


# ========================================================================== casino
def _casino(p, l):
    app = p.app
    from . import menus_extra as mx
    _menu_lugar(p, l, [Opcion(tr("Máquina tragaperras"), lambda: _tragaperras(p), ayuda=tr("Apuestas 5, 25 o 100 euros por tirada. Tres símbolos iguales multiplican la apuesta, más cuanto mejor es el símbolo, y dos iguales la doblan.")),
                       Opcion(tr("Mesa de blackjack"), lambda: _blackjack(p), ayuda=tr("Apuestas 20, 100 o 500 euros y juegas contra la banca a acercarte a 21 sin pasarte.")),
                       Opcion(tr("Ruleta"), lambda: mx.ruleta(p), ayuda=tr("Apuestas al rojo o al negro, a par o impar, a una docena o a un solo número. Con el cero pierdes."))])


def _tragaperras(p):
    app = p.app
    simbolos = ["cereza", "limón", "campana", "herradura", "siete"]
    premios = {"cereza": 5, "limón": 8, "campana": 15, "herradura": 30, "siete": 100}

    def tirar(apuesta):
        def f():
            if not p.pagar(apuesta):
                return
            r = [random.choices(simbolos, weights=[30, 26, 20, 14, 10])[0] for _ in range(3)]
            p.son("lugar_casino", cat="interfaz", vol=0.5)
            txt = ", ".join(r) + ". "
            if r[0] == r[1] == r[2]:
                g = apuesta * premios[r[0]]
                p.dar_dinero(g)
                txt += tr('¡Premio! Ganas {g} euros.').format(g=(g))
            elif r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
                g = apuesta * 2
                p.dar_dinero(g)
                txt += tr('Pareja. Ganas {g} euros.').format(g=(g))
            else:
                txt += tr("Nada.")
            app.decir(txt + tr(' Tienes {dinero} euros.').format(dinero=(p.j.dinero)), True)
        return f
    app.abrir(Menu(app, tr("Tragaperras. Elige la apuesta"), [Opcion(tr('Tirar por {a} euros').format(a=(a)), tirar(a),
                                                                ayuda=tr("Pagas la tirada y salen tres símbolos. Tres iguales dan de 5 a 100 veces la apuesta, según el símbolo; el mejor es el siete. Dos iguales dan el doble. Si no, pierdes la apuesta.")) for a in (5, 25, 100)]))


def _blackjack(p):
    app = p.app
    e = {"fase": "apuesta", "apuesta": 0, "yo": [], "banca": []}
    nombres = {1: "as", 11: "jota", 12: "reina", 13: "rey"}

    def carta():
        return random.randint(1, 13)

    def nom(c):
        return nombres.get(c, str(c))

    def total(mano):
        t = sum(min(c, 10) for c in mano)
        if 1 in mano and t + 10 <= 21:
            t += 10
        return t

    def fin(resultado):
        a = e["apuesta"]
        tb = total(e["banca"])
        txt = tr('La banca tiene {join}: {tb}. ').format(join=(', '.join(nom(c) for c in e['banca'])), tb=(tb))
        if resultado == "gana":
            p.dar_dinero(a * 2)
            txt += tr('¡Ganas {a} euros!').format(a=(a))
        elif resultado == "blackjack":
            p.dar_dinero(int(a * 2.5))
            txt += tr('¡Blackjack! Ganas {int} euros.').format(int=(int(a * 1.5)))
        elif resultado == "empate":
            p.j.dinero += a
            txt += tr("Empate. Recuperas la apuesta.")
        else:
            txt += tr('Pierdes {a} euros.').format(a=(a))
        e["fase"] = "apuesta"
        m.i = 0
        m.refrescar(False)
        app.decir(txt + tr(' Tienes {dinero} euros.').format(dinero=(p.j.dinero)), True)

    def plantarse():
        while total(e["banca"]) < 17:
            e["banca"].append(carta())
        ty, tb = total(e["yo"]), total(e["banca"])
        fin("gana" if tb > 21 or ty > tb else "empate" if ty == tb else "pierde")

    def pedir():
        e["yo"].append(carta())
        t = total(e["yo"])
        if t > 21:
            app.decir(tr('Sacas {nom}: {t}. Te pasas.').format(nom=(nom(e['yo'][-1])), t=(t)), True)
            fin("pierde")
        elif t == 21:
            plantarse()
        else:
            app.decir(tr('Sacas {nom}. Tienes {t}.').format(nom=(nom(e['yo'][-1])), t=(t)), True)

    def apostar(a):
        def f():
            if not p.pagar(a):
                return
            e.update(fase="juego", apuesta=a, yo=[carta(), carta()], banca=[carta(), carta()])
            if total(e["yo"]) == 21:
                fin("blackjack" if total(e["banca"]) != 21 else "empate")
                return
            m.i = 0
            m.refrescar(False)
            app.decir(tr('Tienes {nom} y {nom2}: {total}. La banca enseña {nom3}. Pedir carta.').format(nom=(nom(e['yo'][0])), nom2=(nom(e['yo'][1])), total=(total(e['yo'])), nom3=(nom(e['banca'][0]))), True)
        return f

    def ops():
        if e["fase"] == "apuesta":
            return [Opcion(tr('Apostar {a} euros').format(a=(a)), apostar(a),
                           ayuda=tr("Pagas la apuesta y os reparten dos cartas a ti y dos a la banca. Si ganas, te llevas otro tanto; con un blackjack de salida, una vez y media; si empatas, recuperas la apuesta.")) for a in (20, 100, 500)]
        return [Opcion(tr("Pedir carta"), pedir, ayuda=tr("Te dan otra carta. Si pasas de 21, pierdes; si llegas justo a 21, te plantas solo.")),
                Opcion(tr("Plantarse"), plantarse, ayuda=tr("Te quedas con lo que tienes. La banca saca cartas hasta llegar a 17 o más, y gana quien se acerque más a 21 sin pasarse.")),
                Opcion(lambda: tr('Tu mano: {join}: {total}. La banca enseña {nom}').format(join=(', '.join(nom(c) for c in e['yo'])), total=(total(e['yo'])), nom=(nom(e['banca'][0]))),
                       ayuda=tr("Tus cartas, lo que suman y la carta que enseña la banca. Intro lo vuelve a leer."))]
    m = Menu(app, tr("Blackjack. Gana quien se acerque más a 21 sin pasarse"), ops)
    app.abrir(m)
