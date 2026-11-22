"""Servidor en línea de Puerto Bravo.

Un solo hilo con asyncio. Cada jugador tiene su cola de salida: uno con mala conexión no frena a los demás.
Mensajes: una línea de JSON cada uno, igual que en Jugar con amigos, de modo que el juego habla el mismo idioma.

Lo que decide el servidor, y no el juego de cada cual:
- quién es quién (una clave pública por cuenta, y la firma de un reto al entrar);
- los disparos y golpes entre jugadores: alcance, cadencia, zonas seguras, modo pasivo, bandas y alianzas;
- de quién es cada vehículo dejado en la calle y quién lo conduce;
- las bandas, su caja, los territorios y las guerras;
- la hora, el día y el tiempo que hace, iguales para todos;
- el personaje de cada jugador, que se guarda aquí y se retoma al volver.

Funciona con Python 3.8 o posterior y solo usa la biblioteca de serie.
"""
from .idioma import es, tr
import asyncio
import binascii
import hashlib
import json
import math
import os
import random
import secrets
import time

from . import compat, copias, firma, opciones
from .almacen import Almacen
from .bots import Bots
from .trafico import Trafico
from .peatones import Peatones
from .policia import Policia

VERSION_RED = 2                   # la versión del protocolo que habla este servidor
PROTOCOLO_MIN = 2                 # la más antigua con la que todavía se entiende
# Lo que sabe hacer este servidor. El juego lo mira para no pedir lo que el servidor no tiene, sea cual sea su versión.
FUNCIONES = ("vehiculos", "combate", "bandas", "barrios", "grupos", "propiedades", "robos", "personajes", "mundo", "versiones",
             # desde la 1.7.1: canales de rol y ficha, la radio de los coches de otros, traer, renombrar y guardar tus vehículos
             # aparcados, los pasajeros, las cifras del tope de dinero y los encargos repetibles reconocidos
             "rol", "radio", "mis_vehiculos", "pasajeros", "topes", "encargos",
             # avisa antes de pararse para una actualización o un mantenimiento, espera a que los juegos guarden y dice
             # por qué se cierra, para que el juego espere y vuelva a entrar solo
             "reconexion",
             # a cada juego se le habla con lo que su versión conoce (un arma o un vehículo nuevos le llegan como el más
             # parecido), el personaje no pierde nada al pasar por una versión anterior, y los contratos fijos cobran
             # una nómina que paga el servidor
             "equivalencias", "nominas")
CANALES =("todos", "cerca", "banda", "priv", "grupo")
CANALES_ROL = ("ic", "ooc", "yo")                 # en personaje, fuera de personaje y una acción
# Órdenes que cualquiera puede escribir en el chat con una barra delante, también con un juego anterior a los canales de rol.
ORDENES_ROL = {"yo": "yo", "me": "yo", "ep": "ic", "ic": "ic", "fp": "ooc", "ooc": "ooc", "ficha": "ficha"}
MAX_FICHA = 200
# Lo más que paga un encargo repetible de cada tipo, si el mundo del juego no lo dice (un juego anterior a la 1.7.1).
ENCARGOS_DE_SERIE = {"contrato": 4000, "atraco_banco": 15000, "atraco_local": 8000, "asalto_proveedor": 6000, "encargo_coche": 12000,
                     "conquista": 3000, "defensa": 1500, "boxeo": 6000, "mma": 12000}
# Claves públicas de quien publica el juego: con ellas se comprueba que el mundo que trae un jugador es el de una
# versión de verdad. Son las mismas con las que el juego comprueba sus actualizaciones.
CLAVES_PUBLICAS = ("2793c73fefcdb5518570569e41e9ae291373c41126b30d4b3fb99359b09ca23f",)
# Parar con orden desde fuera: basta con dejar este archivo en la carpeta de datos. El servidor lo mira cada segundo, lo
# borra y hace lo que diga su primera palabra: parar, actualizar o reiniciar (con los segundos de aviso detrás, si se quiere).
ARCHIVO_ORDEN = "parar.txt"
# Por qué se para el servidor. Se lo dice a los juegos en el mensaje de cierre: con «apagado» vuelven al menú; con las
# otras dos, esperan y vuelven a entrar solos. El texto es el que oye quien juega con una versión anterior.
CAUSAS = {"apagado": es("El servidor se ha cerrado."),
          "actualizacion": es("El servidor se reinicia para actualizarse. Volverá en unos minutos: vuelve a entrar entonces."),
          "reinicio": es("El servidor se reinicia por mantenimiento. Volverá en unos minutos: vuelve a entrar entonces.")}
VUELVE = {"actualizacion": 120, "reinicio": 60}      # segundos que se calcula que tarda en volver, para decírselo a los juegos
AVISOS_PARADA = (60, 30, 10)                          # se repite la cuenta atrás cuando queda esto
CODIGO_VUELVE = 75                                    # código con el que termina el programa cuando se ha parado para volver
MUNDO_VACIO = {"version": "0", "huella": "", "mapas": {}, "armas": {}, "modelos": {}, "misiones": {}}
# Mensajes que nombran un arma o un vehículo: a quien juega con un mundo que no los tiene se le cambian por el más parecido.
TRADUCIBLES = frozenset(("tiro", "herido", "evento", "po_disparo", "veh_ocupado", "veh_libre", "veh_ok", "veh_mio", "ok", "grupo_msg"))


def version_tupla(t):
    out = []
    for trozo in str(t or "0").split("."):
        num = "".join(c for c in trozo if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)



MAX_LINEA = 600 * 1024            # un personaje guardado cabe de sobra
# Mensajes que el juego manda solo, sin que el jugador haga nada: no cuentan como actividad.
PASIVOS = ("estado", "ping", "guardar", "quien", "banda_lista")
ESTADOS = {"t": "estados"}       # lo que se reparte diez veces por segundo va ya escrito: esto es solo su etiqueta
MAX_NORMAL = 16 * 1024            # cualquier otro mensaje
SEGURAS = ("hospital", "comisaria", "casa", "ong", "protectora")     # lugares donde nadie puede herir a nadie
RADIO_SEGURO = 16.0
RANGOS = ("jefe", "mano", "miembro")
RANGO_TXT = {"jefe": es("jefe"), "mano": es("mano derecha"), "miembro": es("miembro")}

# Las opciones, con su valor de serie, su explicación y sus límites, están descritas una sola vez en opciones.py.
CONFIG = opciones.valores_de_serie()


def leer_config(ruta, avisos=None):
    """Archivo de texto, una opción por línea: nombre = valor. Las líneas que empiezan por almohadilla son comentarios.
    Lo que no vale se cambia por su valor de serie; si se pasa una lista en ``avisos``, ahí queda dicho qué y por qué."""
    c, problemas = opciones.leer(ruta)
    if avisos is not None:
        avisos.extend(problemas)
    return c


def si(v):
    return str(v).strip().lower() in ("si", "sí", "1", "true", "yes")


def finito(v):
    """Un número de verdad. Un juego trucado puede mandar un infinito o un «no es un número»: con eso dentro, las cuentas
    de distancias dejan de valer para todos, así que no se admite."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(tr("no es un número que valga"))
    return v


def _constante_no_valida(nombre):
    raise ValueError(tr("un mensaje no puede traer %s") % nombre)


def limpiar_nombre(t, tope=24):
    t = "".join(ch for ch in str(t or "") if ch.isprintable() and ch not in "\\/<>|\"").strip()
    return " ".join(t.split())[:tope]


class Jugador:
    def __init__(self, ident, escritor):
        self.id = ident
        self.escritor = escritor
        self.cola = asyncio.Queue()
        self.cuenta = None
        self.nombre = ""
        self.admin = False
        self.conectado = True
        self.dentro = False
        self.mapa = None
        self.x = self.y = 0.0
        self.rumbo = 0.0
        self.vel = 0.0
        self.veh = None            # modelo que conduce
        self.vid = None            # identificador del vehículo común que conduce
        self.salud = 100.0
        self.dinero = 0
        self.arma = "punos"
        self.barrio = None
        self.agachado = False
        self.interior = False
        self.estrellas = 0
        self.po = []
        self.puntos = 0.0          # puntos de delito: de ellos sale el nivel de búsqueda
        self.t_evasion = 0.0       # segundos sin ningún policía cerca
        self.t_poli = 0.0          # lo que falta para que salga otra patrulla
        self.poli_enviada = False
        self.detenido = 0.0        # le han echado el guante: hasta este momento le tienen cogido
        self.estado = {}
        self.t_ataque = 0.0
        self.golpeado = {}         # quién me ha dado: {id de sesión: momento}
        self.agredio = {}          # a quién he dado yo primero
        self.pasivo = False
        self.t_pasivo = 0.0
        self.protegido = 0.0
        self.banda = None
        self.rango = None
        self.grupo = None          # id del líder del grupo de misión
        self.fichas = 120.0        # para frenar a quien manda demasiado
        self.t_fichas = time.monotonic()
        self.t_ultimo = time.monotonic()
        self.fantasma = 0.0        # se ha ido en pleno combate: sigue ahí hasta este momento
        self.t_vid = 0.0           # cuándo cogió el vehículo que conduce
        self.atracos = {}          # a quién ha atracado y cuándo
        self.bot = False           # lo lleva el servidor, no una persona
        self.saldo = None          # lo que el servidor le reconoce: bolsillo más banco
        self.credito = 0           # dinero que le ha dado el propio servidor y aún no ha aparecido en su juego
        self.margen = 0.0          # lo que aún puede ganar por su cuenta sin que se le discuta
        self.t_margen = time.monotonic()
        self.t_saldo = 0.0
        self.banco = 0
        self.cobros = []           # lo que el servidor le ha cobrado y su juego puede no haber restado todavía, por orden
        self.t_cobros = 0.0        # cuándo fue el último de esos cobros
        self.gastos = []           # lo que se le ha visto gastar hace poco: [momento, euros]
        self.prop_pend = {}        # casas y negocios que acaba de apuntarse y aún no se le ha visto pagar: lugar -> [momento, precio]
        self.aspecto = ""          # lo que lleva puesto, como lo cuenta su juego
        self.misiones_pagadas = set()
        self.mapa_fuera = None     # la localidad en la que dice estar, si el mundo del servidor no la tiene
        self.ip = None             # de dónde viene la conexión: solo en memoria, para el límite por dirección
        self.juego = ""            # versión del juego con la que ha entrado
        self.huella = ""           # huella del mundo que trae su juego
        self.proto = VERSION_RED   # versión del protocolo acordada con su juego
        self.t_actividad = time.monotonic()      # la última vez que se movió o hizo algo
        self.sabe = set()          # lo nuevo que su juego dice entender: a quien no lo dice se le habla como a un juego anterior
        self.pasajero_de = None    # id del jugador en cuyo vehículo va de pasajero
        self.radio = ""            # la emisora del juego que lleva puesta en el vehículo, si quiere que se oiga
        self.ficha = ""            # su frase de rol, la que los demás pueden leer
        self.fiado = []            # pagas de encargos repetibles reconocidas y aún no vistas en su juego: [momento, euros]
        self.gasto_pend = 0        # lo que se le ha visto gastar por su cuenta desde la última vez que guardó el personaje
        self.descuento = 0         # lo que el servidor le ha dicho que pierde (un atraco, una caída) y su juego aún no ha restado
        self.total_guardado = None # el dinero (bolsillo más banco) que hay en su personaje guardado
        self.t_aviso_encargo = 0.0
        self.avisado = set()       # avisos de compatibilidad que ya se le han dado: no se repiten
        self.raros = set()         # tipos de mensaje suyos que no se han podido atender: se apuntan una vez
        self.cat = None            # qué armas y vehículos conoce su juego, si lo ha dicho él al entrar (un mundo sin firma)
        self.suyo = None           # los nombres de lo que trae su mundo, para decirle qué no coincide
        self.contrato = {}         # su contrato fijo, como lo lleva el servidor: empleo, puesto, turnos y cuándo cobra

    def dist(self, otro):
        return math.hypot(self.x - otro.x, self.y - otro.y)

    def publico(self):
        return {"id": self.id, "nombre": self.nombre, "banda": self.banda, "ia": self.bot}


class Servidor(Bots, Trafico, Peatones, Policia):
    def __init__(self, config=None, mundo=None, reloj_real=time.time):
        self.cfg = dict(CONFIG)
        self.cfg.update(config or {})
        self.ahora = reloj_real
        carpeta = self.cfg["datos"]
        os.makedirs(carpeta, exist_ok=True)
        self.alm = Almacen(os.path.join(carpeta, "puertobravo.db"))
        self.claves_publicas = CLAVES_PUBLICAS
        self.ruta_conf = None                                 # de qué archivo salió la configuración, si salió de alguno
        self.t_inicio = None                                  # cuándo empezó a escuchar
        self.por_ip = {}                                      # conexiones abiertas por dirección: solo en memoria
        self._t_guardado = self._t_copia = time.monotonic()
        # Los mundos que este servidor ha tenido o ha comprobado: {huella: versión}. Quien trae uno de estos puede
        # entrar aunque el servidor vaya ya con el de una versión más nueva.
        try:
            self.mundos_conocidos = {str(k): str(v) for k, v in dict(self.alm.meta("mundos", {})).items()}
        except (TypeError, ValueError):
            self.mundos_conocidos = {}
        # Qué conoce el juego de cada mundo: los de las versiones publicadas, que vienen con el servidor, y los que ha
        # ido comprobando. Con esto se le habla a cada juego de lo que entiende.
        self.catalogos = {h: compat.en_uso(c) for h, c in compat.CATALOGOS.items()}
        try:
            self._catalogos_guardados = {str(h): c for h, c in dict(self.alm.meta("catalogos", {})).items() if compat.en_uso(c) is not None}
        except (TypeError, ValueError):
            self._catalogos_guardados = {}
        for h, c in self._catalogos_guardados.items():
            self.catalogos.setdefault(h, compat.en_uso(c))
        self.empleos = None                                   # los contratos fijos y sus nóminas, si el mundo los trae
        if mundo is None:                                     # el último que trajo un jugador; si no, el que venga con el servidor; si no, ninguno
            leidos = []
            for ruta in (os.path.join(carpeta, "mundo_actual.json"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "mundo.json")):
                try:
                    with open(ruta, encoding="utf-8") as f:
                        leidos.append(json.load(f))
                except (OSError, ValueError):
                    continue
            if leidos:
                mundo = leidos[0]
                # Si el guardado y el que trae el servidor son el mismo mundo (la misma huella), vale el del servidor: puede
                # contar más cosas de ese mismo mundo (las nóminas, por ejemplo) que cuando se guardó el otro.
                if len(leidos) > 1 and isinstance(mundo, dict) and isinstance(leidos[1], dict) and mundo.get("huella") and mundo.get("huella") == leidos[1].get("huella"):
                    mundo = leidos[1]
        self._poner_mundo(mundo or dict(MUNDO_VACIO), guardar=False)
        self.robos = {}                                       # atracos a negocios en marcha: id de sesión -> datos
        self.encargos = {}                                    # encargos repetibles cobrados: cuenta -> {tipo: [momentos]}. Solo en memoria
        self.jugadores = {}
        self._n = 0
        self.vehiculos = {v["id"]: v for v in self.alm.vehiculos()}
        self._nv = max(list(self.vehiculos) + [0])
        for v in self.vehiculos.values():
            v["por"] = None
        self.reloj = float(self.alm.meta("reloj", 540.0))
        self.dia = int(self.alm.meta("dia", 1))
        self.lluvia = bool(self.alm.meta("lluvia", False))
        self.semilla = int(self.alm.meta("semilla", 0)) or random.randrange(1, 10 ** 9)
        self.alm.poner_meta("semilla", self.semilla)
        self.guerras = self.alm.meta("guerras", [])          # [{mapa, barrio, ataca, defiende, inicio, fin, pa, pd}]
        self.ayudas = set(tuple(x) for x in self.alm.meta("ayudas", []))
        self.invitaciones_banda = {}                          # id de sesión -> {banda, de, hasta}
        self.invitaciones_grupo = {}
        self.propuestas_alianza = {}                          # banda destino -> banda que propone
        self.cifrado = False
        self.huella_cert = ""
        self.servidor = None
        self.activo = False
        self.detenido = False                                 # pasa a True cuando ha parado del todo y lo ha guardado todo
        self.parando = None                                   # la causa, mientras avisa y espera antes de parar
        self.cerrando = False                                 # ya ha dicho a los juegos que se cierra: no entra nadie más
        self.causa_parada = None                              # por qué se paró, para quien lo arrancó
        self.codigo_salida = 0                                # con qué código debe terminar el programa que lo lleva
        self._parada_fin = 0.0
        self._guardan = set()                                 # juegos de los que se espera el último guardado antes de cortar
        self.tareas = []
        self.conexiones = set()
        self.log = print
        self.rng = random.Random()
        self.bots_iniciar()
        self.trafico_iniciar()
        self.peatones_iniciar()
        self.policia_iniciar()
        try:                                                  # a quién buscaba la policía cuando el servidor se paró: no se libra por el reinicio
            for cuenta, puntos in dict(self.alm.meta("buscados", {})).items():
                self.buscados_fuera[int(cuenta)] = (float(puntos), time.monotonic())
        except (TypeError, ValueError):
            pass
        self.alm.poner_meta("buscados", {})
        self.alm.guardar()

    # El registro: lo que va diciendo el servidor. Quien lo arranca dice adónde va (la consola, el panel, una lista en las
    # pruebas) con ``srv.log = función``; si la opción registro_archivo está puesta, va además a registro.txt.
    @property
    def log(self):
        return self._anotar

    @log.setter
    def log(self, salida):
        self._destino_registro = salida

    def _anotar(self, texto):
        if si(self.cfg.get("registro_archivo", "no")):
            try:
                ruta = os.path.join(self.cfg["datos"], "registro.txt")
                if os.path.exists(ruta) and os.path.getsize(ruta) > 2 * 1024 * 1024:      # no crece sin fin: se guarda el anterior
                    os.replace(ruta, os.path.join(self.cfg["datos"], "registro_anterior.txt"))
                with open(ruta, "a", encoding="utf-8", newline="\n") as f:
                    f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), texto))
            except OSError:
                pass
        self._destino_registro(texto)

    def _poner_mundo(self, mundo, guardar=True):
        """El mundo del juego con el que trabaja el servidor. Lo trae el juego, no el servidor: así un mismo servidor
        sirve para las versiones que vayan saliendo."""
        self.mundo = mundo
        self.seguras = {}
        self.lugares = {}                                     # los que se pueden comprar: casas y negocios
        for mid, m in mundo["mapas"].items():
            self.seguras[mid] = [(l["x"], l["y"]) for l in m["lugares"] if l["tipo"] in SEGURAS]
            for l in m["lugares"]:
                if l["tipo"] in ("casa", "negocio") and l.get("precio", 0) > 0:
                    self.lugares[l["id"]] = dict(l, mapa=mid)
        if mundo.get("huella") and mundo["mapas"]:
            self._recordar_mundo(mundo["huella"], mundo.get("version"))
            if not mundo.get("provisional"):
                self._recordar_catalogo(mundo["huella"], mundo)
        self.empleos = compat.empleos_validos(mundo)
        for c in self.catalogos.values():                     # lo más parecido a cada cosa se calcula con el mundo que hay: otra vez
            c["eq"].clear()
        for j in getattr(self, "jugadores", {}).values():
            if j.cat:
                j.cat["eq"].clear()
        # Si el mundo cambia con gente dentro, nada de lo que estaba en marcha puede apuntar a algo que ya no existe.
        for j in getattr(self, "jugadores", {}).values():
            if j.mapa is not None and j.mapa not in mundo["mapas"]:
                j.mapa = None
        for ident in [i for i, r in getattr(self, "robos", {}).items() if r["lugar"] not in self.lugares]:
            self.robos.pop(ident, None)
        if hasattr(self, "guerras"):
            self.guerras = [g for g in self.guerras if g["mapa"] in mundo["mapas"]]
        for nombre in ("trafico", "peatones", "agentes"):      # lo que lleva el servidor por las calles se vuelve a poner solo
            cosas = getattr(self, nombre, None)
            if isinstance(cosas, dict):
                for ident in [i for i, c in cosas.items() if c.get("m") not in mundo["mapas"]]:
                    del cosas[ident]
        self._abiertos = {}                                   # las manzanas por las que andan los agentes se calculan otra vez
        if guardar:
            ruta = os.path.join(self.cfg["datos"], "mundo_actual.json")
            with open(ruta + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                json.dump(mundo, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(ruta + ".tmp", ruta)

    def _recordar_mundo(self, huella, version):
        """Apunta un mundo como conocido: el que tiene el servidor, o uno firmado por quien publica el juego."""
        huella = str(huella or "")
        if not huella or self.mundos_conocidos.get(huella) == str(version or ""):
            return
        self.mundos_conocidos[huella] = str(version or "")
        while len(self.mundos_conocidos) > 200:               # con el tiempo, los más antiguos dejan sitio
            self.mundos_conocidos.pop(next(iter(self.mundos_conocidos)))
        self.alm.poner_meta("mundos", self.mundos_conocidos)

    def _recordar_catalogo(self, huella, mundo):
        """Apunta qué armas y vehículos conoce el juego de un mundo comprobado (el del servidor, o uno firmado)."""
        huella = str(huella or "")
        if not huella or huella in compat.CATALOGOS:
            return
        c = compat.catalogo_de(mundo)
        if self._catalogos_guardados.get(huella) == c:
            return
        self._catalogos_guardados[huella] = c
        while len(self._catalogos_guardados) > 40:
            self._catalogos_guardados.pop(next(iter(self._catalogos_guardados)))
        self.catalogos[huella] = compat.en_uso(c)
        self.alm.poner_meta("catalogos", self._catalogos_guardados)

    def _cat(self, j):
        """Lo que conoce el juego de un jugador, si no es lo mismo que el mundo del servidor. None si es el mismo mundo, o
        si no se sabe: entonces se le habla sin cambiar nada."""
        if j.bot or not j.huella or j.huella == self.mundo.get("huella"):
            return None
        return j.cat or self.catalogos.get(j.huella)

    def _arma_eq(self, cat, arma):
        eq = cat["eq"].get("a:" + arma)
        if eq is None:
            eq = cat["eq"]["a:" + arma] = compat.arma_equivalente(arma, self.mundo["armas"], cat["armas"])
        return eq

    def _modelo_eq(self, cat, modelo):
        eq = cat["eq"].get("m:" + modelo)
        if eq is None:
            eq = cat["eq"]["m:" + modelo] = compat.modelo_equivalente(modelo, self.mundo["modelos"], cat["modelos"])
        return eq

    def _traducir(self, j, obj):
        """Un mensaje que nombra un arma o un vehículo, puesto para el juego de este jugador: si su versión no los
        conoce, lleva el más parecido de los que sí. None si no hay nada que cambiar. Solo cambia lo que oye y ve: el
        daño ya lo ha decidido el servidor con sus cifras."""
        cat = self._cat(j)
        if cat is None:
            return None
        t = obj.get("t")
        armas, modelos = self.mundo["armas"], self.mundo["modelos"]
        if t in ("tiro", "herido", "po_disparo"):
            a = obj.get("arma")
            if isinstance(a, str) and a in armas and a not in cat["armas"]:
                return dict(obj, arma=self._arma_eq(cat, a))
        elif t == "evento":
            q = obj.get("que")
            if isinstance(q, str) and q.startswith("d:") and q[2:] in armas and q[2:] not in cat["armas"]:
                return dict(obj, que=("d:" + self._arma_eq(cat, q[2:]))[:20])
        elif t == "grupo_msg":
            # los enemigos de la misión de un compañero: cada uno con un arma que su juego conozca
            d = obj.get("d")
            lista = d.get("e") if isinstance(d, dict) and d.get("que") == "enemigos" else None

            def fuera(e):
                a = e.get("arma") if isinstance(e, dict) else None
                return isinstance(a, str) and a in armas and a not in cat["armas"]
            if isinstance(lista, list) and any(fuera(e) for e in lista):
                return dict(obj, d=dict(d, e=[dict(e, arma=self._arma_eq(cat, e["arma"])) if fuera(e) else e for e in lista]))
        elif t == "ok":
            vs = [v for v in obj.get("vehiculos") or [] if isinstance(v, dict)]
            if any(v.get("modelo") in modelos and v.get("modelo") not in cat["modelos"] for v in vs):
                return dict(obj, vehiculos=[dict(v, modelo=self._modelo_eq(cat, v["modelo"])) if v.get("modelo") in modelos and v.get("modelo") not in cat["modelos"] else v
                                            for v in vs])
        else:
            v = obj.get("v")
            if isinstance(v, dict) and v.get("modelo") in modelos and v.get("modelo") not in cat["modelos"]:
                return dict(obj, v=dict(v, modelo=self._modelo_eq(cat, v["modelo"])))
        return None

    async def _recibir_mundo(self, j, lector, m):
        """Pide al juego de quien entra el mundo de su versión. Devuelve (texto, firmado), o (None, False) si no llega bien.
        Firmado quiere decir que lo avala quien publica el juego: es el de una versión de verdad, sin mods."""
        self._enviar(j, {"t": "pide_mundo"})
        r = await self._leer(lector, MAX_LINEA, 40)
        if not r or r.get("t") != "mundo":
            return None, False
        try:                                                  # viene comprimido: pesa la sexta parte
            import base64
            import zlib
            texto = zlib.decompressobj().decompress(base64.b64decode(r["z"]), 4 * 1024 * 1024).decode("utf-8") if r.get("z") else r.get("datos")
        except Exception:
            return None, False
        if not isinstance(texto, str) or not texto:
            return None, False
        firmado = False
        try:
            f = binascii.unhexlify(str(r.get("firma") or ""))
            for clave in self.claves_publicas:
                if f and await asyncio.get_event_loop().run_in_executor(None, firma.verificar, binascii.unhexlify(clave), texto.encode("utf-8"), f):
                    firmado = True
                    break
        except Exception:
            firmado = False
        return texto, firmado

    @staticmethod
    def _mundo_de_texto(texto, huella):
        """El mundo que viene en un texto, si está bien formado y su huella es la que dice el juego. Si no, None."""
        try:
            nuevo = json.loads(texto)
            assert isinstance(nuevo["mapas"], dict) and isinstance(nuevo["armas"], dict) and isinstance(nuevo["modelos"], dict) and isinstance(nuevo["misiones"], dict)
            assert nuevo["huella"] == huella and nuevo["mapas"]
            for mapa in nuevo["mapas"].values():
                assert isinstance(mapa["lugares"], list) and isinstance(mapa["barrios"], list)
            return nuevo
        except Exception:
            return None

    async def _admitir_mundo(self, j, lector, m, es_admin):
        """El juego de quien entra trae un mundo que no es el del servidor. Devuelve (True, "") si puede entrar, o
        (False, motivo). Por el camino, si procede, el servidor adopta ese mundo o lo apunta como conocido.

        El servidor trabaja con el mundo de la versión más nueva que ha visto, pero no echa a quien va con otra: basta
        con que su mundo sea uno que el servidor ya tuvo, o uno firmado por quien publica el juego. Cada cual juega con
        lo que su versión conoce."""
        huella, juego = str(m.get("huella") or ""), m.get("juego")
        modo = str(self.cfg["actualizar_mundo"]).lower()
        estricto = str(self.cfg["versiones"]).lower() == "iguales"
        # Con «admitir», que es lo de serie, quien trae unos datos que el servidor no puede comprobar (mods, o una versión
        # sin firma) entra igual: juega en lo común, y el servidor arbitra con su mundo y le dice qué no coincide.
        admitir = str(self.cfg.get("mundo_distinto", "admitir")).lower() != "rechazar" and not estricto
        vacio = not self.mundo["mapas"]
        provisional = bool(self.mundo.get("provisional")) and not vacio      # el que hay lo trajo alguien sin firma, a falta de otro
        dice_firma = bool(m.get("firmado"))
        mas_nuevo = version_tupla(juego) > version_tupla(self.mundo.get("version")) or vacio
        por_admin = modo == "admin" and es_admin
        puede_adoptar = modo != "no" and ((mas_nuevo and dice_firma) or por_admin or (provisional and dice_firma))
        # Conocido: un mundo que este servidor ya tuvo o comprobó, o el de una versión publicada de las que trae apuntadas.
        conocido = (huella in self.mundos_conocidos or huella in compat.CATALOGOS) and not vacio
        texto, firmado = None, False
        if (puede_adoptar or (vacio and admitir and modo != "no")
                or (not vacio and not estricto and ((dice_firma and not conocido) or (admitir and huella not in self.catalogos)))):
            texto, firmado = await self._recibir_mundo(j, lector, m)
        nuevo = self._mundo_de_texto(texto, huella) if texto else None
        if nuevo is not None:
            nuevo.pop("provisional", None)                    # eso lo dice el servidor, no quien lo trae
            # Lo que conoce su juego, dicho por él: sirve para hablarle de lo que entiende y para decirle qué no coincide.
            # Solo para esta sesión; lo que se guarda para otras veces es lo firmado.
            j.cat = compat.en_uso(compat.catalogo_de(nuevo))
            j.suyo = {c: {k: {"nombre": str((v or {}).get("nombre") or k)[:60]} for k, v in list(nuevo[c].items())[:compat.MAX_IDS] if isinstance(v, dict)}
                      for c in ("armas", "modelos")}
            if firmado:
                self._recordar_catalogo(huella, nuevo)
        if nuevo is not None and puede_adoptar and ((firmado and (mas_nuevo or provisional)) or por_admin):
            antes = self.mundo.get("version")
            self._poner_mundo(nuevo)
            self.log(tr("El mundo pasa de la versión %s a la %s%s.") % (antes, nuevo.get("version"), tr(", firmado por quien publica el juego") if firmado else tr(", traído por un administrador, sin firma")))
            self._a_todos({"t": "aviso", "texto": (es("El servidor pasa a los datos de la versión %s del juego. Quien tenga otra versión tendrá que "
                                                      "ponerse esta para volver a entrar.") if estricto else
                                                   es("El servidor pasa a los datos de la versión %s del juego. Quien tenga una versión anterior puede "
                                                      "seguir jugando: lo nuevo lo oirá y lo verá como lo más parecido de lo que su juego conoce."))
                           % nuevo.get("version"), "son": "notificacion"})
            return True, ""
        if nuevo is not None and vacio and admitir and modo != "no":
            # El servidor no tenía mundo y el primero que entra trae uno sin firma (lleva mods, o juega desde el código):
            # se usa mientras no llegue otro mejor. Lo sustituye el primero firmado que entre, o el de un administrador.
            self._poner_mundo(dict(nuevo, provisional=True))
            self.log(tr("El servidor no tenía mundo: toma, de momento, el que trae %s, de la versión %s, que no viene firmado por quien publica el juego. "
                     "Lo cambiará por el primero firmado que llegue.") % (limpiar_nombre(m.get("nombre")) or tr("quien entra"), nuevo.get("version")))
            return True, ""
        if not vacio and not estricto:
            if nuevo is not None and firmado:                 # es de una versión de verdad: desde ahora, conocido
                self._recordar_mundo(huella, nuevo.get("version"))
                self.alm.guardar()
                conocido = True
            if conocido or admitir:
                return True, ""
        if vacio:
            return False, (es("Este servidor acaba de estrenarse y todavía no tiene los datos del juego: se los da el primero que entra, y los tuyos no le han "
                           "llegado bien o no los puede aceptar. Prueba otra vez; si sigue igual, que entre primero quien lleva el servidor."))
        if version_tupla(juego) < version_tupla(self.mundo.get("version")) and (estricto or vacio or not m.get("firmado")):
            return False, es("Este servidor va con la versión %s del juego y la tuya es anterior. Actualiza el juego para entrar.") % self.mundo.get("version", "?")
        return False, (es("Los datos de tu juego no son los de este servidor, que va con la versión %s: llevas mods que cambian el mundo, "
                       "o una versión que el servidor no puede comprobar.") % self.mundo.get("version", "?"))
    # ================================================================ arranque
    def _contexto_tls(self):
        modo = str(self.cfg["cifrado"]).lower()
        if modo == "no":
            return None
        import ssl
        cert, llave = self.cfg["certificado"], self.cfg["llave"]
        if not cert:
            cert = os.path.join(self.cfg["datos"], "certificado.pem")
            llave = os.path.join(self.cfg["datos"], "llave.pem")
            if not (os.path.exists(cert) and os.path.exists(llave)):
                self._crear_certificado(cert, llave)
        if not (os.path.exists(cert) and os.path.exists(llave or cert)):
            if si(modo):
                raise RuntimeError(tr("El cifrado es obligatorio pero no hay certificado y no se ha podido crear: hace falta el programa openssl."))
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, llave or None)
        try:
            pem = open(cert, encoding="ascii").read()
            der = ssl.PEM_cert_to_DER_cert(pem[pem.index("-----BEGIN CERTIFICATE-----"):pem.index("-----END CERTIFICATE-----") + 25])
            self.huella_cert = hashlib.sha256(der).hexdigest()
        except Exception:
            self.huella_cert = ""
        return ctx

    def _crear_certificado(self, cert, llave):
        """Un certificado propio, válido diez años. Con el programa openssl si está; si no, lo hace el propio servidor."""
        import shutil
        import subprocess
        exe = shutil.which("openssl")
        if not exe:
            return self._certificado_propio(cert, llave)
        try:
            subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", llave, "-out", cert, "-days", "3650",
                            "-subj", "/CN=PuertoBravo"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            try:
                os.chmod(llave, 0o600)
            except OSError:
                pass
            return True
        except Exception:
            return self._certificado_propio(cert, llave)

    def _certificado_propio(self, cert, llave):
        try:
            from . import certificado
            self.log(tr("Creando el certificado para cifrar la conexión. Tarda unos segundos y solo se hace la primera vez."))
            certificado.escribir(cert, llave)
            try:
                os.chmod(llave, 0o600)
            except OSError:
                pass
            return True
        except Exception as e:
            self.log(tr("No se ha podido crear el certificado: %s: %s") % (type(e).__name__, e))
            return False

    async def iniciar(self):
        ctx = self._contexto_tls()
        self.cifrado = ctx is not None
        self.servidor = await asyncio.start_server(self._atender, self.cfg["interfaz"], int(self.cfg["puerto"]), ssl=ctx, limit=MAX_LINEA)
        self.puerto = self.servidor.sockets[0].getsockname()[1]
        self.activo = True
        try:
            os.remove(os.path.join(self.cfg["datos"], ARCHIVO_ORDEN))      # una orden que quedó de otra vez no cuenta
        except OSError:
            pass
        self.t_inicio = time.time()
        self._t_guardado = self._t_copia = time.monotonic()
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(self._error_del_bucle)
        self.tareas = [loop.create_task(self._bucle_estados()), loop.create_task(self._bucle_lento())]
        self.log(tr("Servidor «%s» escuchando en el puerto %s, %s.") % (self.cfg["nombre"], self.puerto, tr("con cifrado") if self.cifrado else tr("SIN cifrado")))

    def _error_del_bucle(self, loop, contexto):
        """Lo que falla por dentro sin que nadie lo recoja. Va al registro en una línea, no a la consola como un volcado.

        Hay un caso que no es un error de nadie y no se dice: en Windows, cuando un jugador corta la conexión justo cuando
        el servidor la está cerrando, Python se queja al cerrar un enchufe de red que ya está cerrado. Ahí solo se termina
        de cerrar lo que quedaba abierto."""
        exc = contexto.get("exception")
        asa = contexto.get("handle")
        if isinstance(exc, OSError) and "connection_lost" in str(asa or contexto.get("message") or ""):
            try:
                enchufe = getattr(getattr(getattr(asa, "_callback", None), "__self__", None), "_sock", None)
                if enchufe is not None:
                    enchufe.close()
            except Exception:
                pass
            return
        try:
            self.log(tr("Error interno del servidor: %s%s") % (contexto.get("message") or tr("sin más datos"), (": %s: %s" % (type(exc).__name__, exc)) if exc is not None else ""))
        except Exception:
            pass

    def _humanos(self):
        return [j for j in self.jugadores.values() if j.dentro and not j.bot and j.conectado]

    def _anunciar_parada(self, j, causa, queda, vuelve):
        """La cuenta atrás, a un jugador: a un juego que sabe reconectar, con cifras, para que lo diga a su manera y sepa
        que tiene que esperar; a uno anterior, como un aviso de los de siempre."""
        queda = max(0, int(round(queda)))
        if "reconexion" in j.sabe:
            self._enviar(j, {"t": "parada", "causa": causa, "en": queda, "vuelve": int(vuelve)})
            return
        que = es("para actualizarse") if causa == "actualizacion" else es("por mantenimiento")
        self._aviso(j, es("Aviso del servidor: dentro de %d segundos se reinicia %s. Tu personaje se guarda solo. Volverá en unos minutos: "
                          "vuelve a entrar entonces.") % (queda, que), "notificacion")

    async def detener(self, motivo=None, causa="apagado", aviso=0.0, vuelve=None, espera=None, codigo=0):
        """Para el servidor con orden: avisa (con cuenta atrás si se pide), dice a los juegos que se cierra y por qué,
        espera un momento a que manden su último guardado, saca a cada jugador por el camino de siempre (su vehículo queda
        aparcado, y su saldo y su margen, guardados) y lo guarda todo.

        ``causa`` es «apagado», «actualizacion» o «reinicio»: con las dos últimas, los juegos que saben hacerlo esperan y
        vuelven a entrar solos. ``aviso`` son los segundos de cuenta atrás; ``espera``, lo más que se aguarda a los
        guardados (si no se dice, la opción parada_espera); ``codigo``, con qué código debe salir el programa."""
        if not self.activo or self.parando:
            return
        causa = causa if causa in CAUSAS else "apagado"
        self.parando = causa
        self.causa_parada, self.codigo_salida = causa, int(codigo)
        vuelve = int(VUELVE.get(causa, 0) if vuelve is None else vuelve)
        try:
            aviso = max(0.0, float(aviso or 0))
        except (TypeError, ValueError):
            aviso = 0.0
        if aviso > 0 and causa != "apagado" and self._humanos():
            self.log(tr("Aviso a los jugadores: el servidor se para dentro de %d segundos, %s.") % (aviso, tr("para actualizarse") if causa == "actualizacion" else tr("por mantenimiento")))
            self._parada_fin = time.monotonic() + aviso
            for j in self._humanos():
                self._anunciar_parada(j, causa, aviso, vuelve)
            dichos = set(m for m in AVISOS_PARADA if m >= aviso - 3)      # lo que ya queda dicho con el primer aviso
            while True:
                queda = self._parada_fin - time.monotonic()
                if queda <= 0 or not self._humanos():             # se han ido todos: no hay a quién esperar
                    break
                marca = next((m for m in AVISOS_PARADA if m not in dichos and queda <= m), None)
                if marca is not None:
                    dichos.add(marca)
                    for j in self._humanos():
                        self._anunciar_parada(j, causa, queda, vuelve)
                await asyncio.sleep(0.2)
        # El cierre. Quien lo recibe guarda su personaje y se despide: se le espera un momento, sin dejar entrar a nadie más.
        self.cerrando = True
        cierre = {"t": "cerrado", "motivo": str(motivo or CAUSAS[causa])[:300], "causa": causa, "vuelve": vuelve}
        self._guardan = set(j.id for j in self._humanos())
        for j in list(self.jugadores.values()):
            self._enviar(j, cierre)
        try:
            espera = float(self.cfg.get("parada_espera", 6) if espera is None else espera)
        except (TypeError, ValueError):
            espera = 6.0
        ahora = time.monotonic()
        minimo, tope = ahora + 0.2, ahora + max(0.2, espera)
        while time.monotonic() < tope and (self._guardan or time.monotonic() < minimo):
            await asyncio.sleep(0.05)
        if self._guardan:
            self.log((tr("No ha llegado a tiempo el último guardado de %d jugador: su personaje queda como estaba en el anterior.")
                      if len(self._guardan) == 1 else
                      tr("No ha llegado a tiempo el último guardado de %d jugadores: su personaje queda como estaba en el anterior.")) % len(self._guardan))
        self.activo = False
        for t in self.tareas:
            t.cancel()
        self.servidor.close()
        for j in list(self.jugadores.values()):
            if j.dentro and not j.bot:
                # Por el camino de siempre: lo que conducía queda aparcado, y su saldo y su margen, guardados. A quien no
                # haya llegado a guardar se le reconoce otra vez lo que gastó desde su último guardado.
                self._salida(j, callar=True)
            j.dentro = False
            self._cortar(j)
        ahora = time.monotonic()                              # la búsqueda de quien estaba dentro, o salió hace poco, sobrevive al reinicio
        self.alm.poner_meta("buscados", {str(c): p for c, (p, cuando) in self.buscados_fuera.items() if p and ahora - cuando < 600})
        self.guardar_todo()
        for t in list(self.conexiones):
            t.cancel()
        if self.conexiones:
            await asyncio.wait(list(self.conexiones), timeout=3)
        try:
            await asyncio.wait_for(self.servidor.wait_closed(), 3)
        except Exception:
            pass
        self.alm.cerrar()
        self.detenido = True                                  # ya está todo guardado y cerrado

    def parar_para_volver(self, causa="actualizacion", aviso=None, codigo=CODIGO_VUELVE):
        """Para el servidor avisando de que va a volver: para actualizarlo o por mantenimiento. Los juegos esperan y
        vuelven a entrar solos. Se le llama desde dentro del bucle del servidor; devuelve los segundos de aviso."""
        if aviso is None:
            aviso = self.cfg.get("parada_aviso", 20)
        try:
            aviso = max(0, min(600, int(aviso)))
        except (TypeError, ValueError):
            aviso = 20
        asyncio.get_event_loop().create_task(self.detener(causa=causa, aviso=aviso, codigo=codigo))
        return aviso

    def orden_externa(self, texto):
        """Una orden dejada en el archivo de órdenes de la carpeta de datos: parar, actualizar o reiniciar. Detrás puede
        llevar los segundos de aviso."""
        partes = str(texto or "").split()
        que = partes[0].lower() if partes else "parar"
        try:
            aviso = int(partes[1]) if len(partes) > 1 else None
        except ValueError:
            aviso = None
        if que in ("actualizar", "actualizacion"):
            self.log(tr("Se ha pedido parar el servidor para actualizarlo."))
            self.parar_para_volver("actualizacion", aviso)
        elif que in ("reiniciar", "reinicio", "mantenimiento"):
            self.log(tr("Se ha pedido parar el servidor por mantenimiento."))
            self.parar_para_volver("reinicio", aviso)
        else:
            self.log(tr("Se ha pedido parar el servidor."))
            asyncio.get_event_loop().create_task(self.detener())

    def _mirar_orden(self):
        ruta = os.path.join(self.cfg["datos"], ARCHIVO_ORDEN)
        if self.parando or not os.path.exists(ruta):
            return
        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                texto = f.read(200)
            os.remove(ruta)
        except OSError:
            return
        self.orden_externa(texto)

    def guardar_todo(self):
        self.alm.poner_meta("reloj", self.reloj)
        self.alm.poner_meta("dia", self.dia)
        self.alm.poner_meta("lluvia", self.lluvia)
        self.alm.poner_meta("guerras", self.guerras)
        self.alm.poner_meta("ayudas", [list(x) for x in list(self.ayudas)[-4000:]])
        self.alm.guardar_vehiculos([dict(v, por=None) for v in self.vehiculos.values()])
        self.alm.guardar()

    # ================================================================== envío
    def _enviar(self, j, obj, hecho=None):
        """Pone un mensaje en la cola de un jugador. ``hecho`` es el mismo mensaje ya escrito, cuando va a muchos."""
        t = obj.get("t")
        if t in ("dinero", "paga_mision", "nomina") and not j.bot:      # lo que da el servidor queda apuntado: es dinero justificado
            j.credito += max(0, int(obj.get("n", 0)))
        elif t in ("baja", "atraco_ok", "robo_fin") and not j.bot:
            j.credito += max(0, int(obj.get("botin", 0)))
        elif t in ("atracado", "caes") and not j.bot:          # lo que le quita el servidor no es una compra suya
            j.descuento += max(0, int(obj.get("pierde", 0)))
        elif t == "robos_dia" and not j.bot:
            j.descuento += max(0, int(obj.get("total", 0)))
        if j.conectado:
            if t in TRADUCIBLES and j.huella != self.mundo.get("huella"):      # su juego es de otra versión: lo que no conoce, por lo más parecido
                otro = self._traducir(j, obj)
                if otro is not None:
                    obj, hecho = otro, None
            j.cola.put_nowait(obj if hecho is None else hecho)
            if j.cola.qsize() > 600:                         # no lee: fuera, sin frenar a nadie
                self._cortar(j)

    @staticmethod
    def _codificar(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"

    def _a_todos(self, obj, menos=None, mapa=None):
        """A todos los que están dentro, o a los de una localidad. El mensaje se escribe una sola vez, no una por jugador:
        con cien jugadores es cien veces menos trabajo."""
        hecho = None
        for j in self.jugadores.values():
            if j.dentro and j is not menos and (mapa is None or j.mapa == mapa):
                if hecho is None and not j.bot:
                    hecho = self._codificar(obj)
                self._enviar(j, obj, hecho)

    def _a_banda(self, banda, obj, menos=None):
        hecho = None
        for j in self.jugadores.values():
            if j.dentro and j.banda == banda and j is not menos:
                if hecho is None and not j.bot:
                    hecho = self._codificar(obj)
                self._enviar(j, obj, hecho)

    def _aviso(self, j, texto, sonido=None):
        self._enviar(j, {"t": "aviso", "texto": texto, "son": sonido})

    def _cortar(self, j):
        j.conectado = False
        try:
            j.escritor.close()
        except Exception:
            pass

    def _echar(self, j, motivo):
        """Le dice por qué se va y corta un momento después, para que le llegue el mensaje."""
        self._enviar(j, {"t": "expulsado", "motivo": motivo})
        j.cola.put_nowait(None)                  # quien escribe termina lo pendiente, espera un momento y corta

    async def _escribir(self, j):
        try:
            while j.conectado:
                obj = await j.cola.get()
                if obj is None:
                    break
                j.escritor.write(obj if isinstance(obj, bytes) else self._codificar(obj))
                await asyncio.wait_for(j.escritor.drain(), 20)
            # Despedida sin prisas: si se cierra nada más enviar, en Windows al otro lado le llega un corte en vez del
            # último mensaje (un rechazo, por ejemplo). Se avisa de que no hay más y se le da medio segundo para leer.
            try:
                if j.escritor.can_write_eof():
                    j.escritor.write_eof()
            except Exception:
                pass
            await asyncio.sleep(0.5)
        except Exception:
            pass
        self._cortar(j)

    # ============================================================== conexión
    async def _leer(self, lector, tope=MAX_NORMAL, espera=60):
        linea = await asyncio.wait_for(lector.readline(), espera)
        if not linea:
            return None
        if len(linea) > tope:
            raise ValueError(tr("mensaje demasiado largo"))
        try:
            m = json.loads(linea.decode("utf-8"), parse_constant=_constante_no_valida)      # ni NaN ni Infinity: no son JSON
        except ValueError:
            return {}
        return m if isinstance(m, dict) else {}

    async def _atender(self, lector, escritor):
        self._n += 1
        j = Jugador(self._n, escritor)
        tarea = asyncio.get_event_loop().create_task(self._escribir(j))
        yo = asyncio.current_task() if hasattr(asyncio, "current_task") else None
        if yo is not None:
            self.conexiones.add(yo)
        try:
            par = escritor.get_extra_info("peername")
            j.ip = str(par[0]) if isinstance(par, (tuple, list)) and par else None      # solo en memoria: no se guarda en ningún sitio
        except Exception:
            j.ip = None
        if j.ip is not None:
            self.por_ip[j.ip] = self.por_ip.get(j.ip, 0) + 1
        try:
            if si(self.cfg["registro_ip"]):
                self.log(tr("Conexión desde %s") % (par,))
            tope_ip = int(self.cfg["conexiones_por_ip"])
            if tope_ip > 0 and j.ip is not None and self.por_ip.get(j.ip, 0) > tope_ip:
                self._rechazo(j, es("Hay demasiadas conexiones desde tu dirección. Prueba dentro de un momento."))
            elif await self._entrada(j, lector):
                while j.conectado and self.activo:
                    m = await self._leer(lector, MAX_LINEA, 90)
                    if m is None:
                        break
                    if not m:
                        continue
                    if not self._ficha(j):
                        self._echar(j, es("Tu juego manda demasiados mensajes."))
                        break
                    j.t_ultimo = time.monotonic()
                    if m.get("t") == "adios":
                        break
                    if m.get("t") not in PASIVOS:
                        j.t_actividad = j.t_ultimo           # ha hecho algo: no está parado
                    try:
                        self._mensaje(j, m)
                    except Exception as e:                    # un mensaje raro no tumba el servidor, ni echa a quien lo manda
                        # Puede venir de un juego de otra versión, con otra forma. Se deja pasar y se apunta una sola vez por
                        # jugador y tipo de mensaje: así nadie llena el registro a base de mandar cosas raras.
                        clave = str(m.get("t"))[:30]
                        if clave not in j.raros and len(j.raros) < 20:
                            j.raros.add(clave)
                            self.log(tr("Un mensaje «%s» de %s no se ha podido atender y se deja pasar: %s: %s") % (clave, j.nombre, type(e).__name__, e))
        except (asyncio.TimeoutError, ConnectionError, OSError, ValueError, asyncio.IncompleteReadError):
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:                                # nada de lo que mande un cliente debe tumbar al servidor
            self.log(tr("Error atendiendo a un jugador: %s: %s") % (type(e).__name__, e))
        finally:
            if j.ip is not None:
                quedan = self.por_ip.get(j.ip, 1) - 1
                if quedan > 0:
                    self.por_ip[j.ip] = quedan
                else:
                    self.por_ip.pop(j.ip, None)
            if self.activo:
                self._salida(j)
            j.cola.put_nowait(None)
            try:
                await asyncio.wait_for(tarea, 3)
            except Exception:
                tarea.cancel()
            finally:
                # Hasta aquí esta conexión sigue contando: al parar, el servidor espera también a que termine esta despedida.
                # Si se descontaba antes, el servidor podía darse por parado con ella a medias y quedaban dos tareas sin terminar.
                self.conexiones.discard(yo)
                try:
                    escritor.close()
                except Exception:
                    pass

    def _ficha(self, j):
        ahora = time.monotonic()
        j.fichas = min(160.0, j.fichas + (ahora - j.t_fichas) * 60.0)
        j.t_fichas = ahora
        j.fichas -= 1.0
        return j.fichas > 0

    def _rechazo(self, j, motivo, codigo="", **mas):
        """No entra, y se le dice por qué. Con ``codigo``, además, de un modo que el juego entiende sin leer el texto:
        «version», «lleno» o «reiniciando». Un juego anterior no lo mira."""
        m = {"t": "rechazo", "motivo": motivo}
        if codigo:
            m["codigo"] = codigo
            m.update(mas)
        self._enviar(j, m)
        return False

    def _nombres(self, opcion):
        """Una lista de nombres de jugador escrita en la configuración, separados por comas."""
        return {limpiar_nombre(x).lower() for x in str(self.cfg.get(opcion, "")).split(",") if x.strip()}

    def _cuantos(self):
        """Cuántas personas hay dentro. Los personajes que lleva el servidor no cuentan."""
        return sum(1 for o in self.jugadores.values() if o.dentro and not o.bot)

    async def _entrada(self, j, lector):
        """Saludo, reto firmado y, si todo va bien, la bienvenida con el personaje guardado."""
        m = await self._leer(lector, MAX_NORMAL, 15)
        if not m or m.get("t") != "hola":
            return False
        if self.cerrando:
            return self._rechazo(j, es("El servidor se está reiniciando. Prueba otra vez dentro de un momento."), "reiniciando")
        # La versión del protocolo se acuerda: el juego dice la más nueva que habla (v) y la más antigua con la que se
        # entiende (vmin); se usa la más nueva que hablen los dos. Así entra tanto quien va por delante como quien va por detrás.
        v = m.get("v")
        if not isinstance(v, int) or isinstance(v, bool) or v < PROTOCOLO_MIN:
            return self._rechazo(j, es("Tu juego es demasiado antiguo para este servidor. Actualiza el juego."))
        vmin = m.get("vmin")
        if isinstance(vmin, int) and not isinstance(vmin, bool) and vmin > VERSION_RED:
            return self._rechazo(j, es("Tu juego es más nuevo de lo que este servidor entiende. Quien lleva el servidor tiene que actualizarlo."))
        j.proto = min(v, VERSION_RED)
        j.juego = "".join(ch for ch in str(m.get("juego") or "") if ch.isalnum() or ch in ".-")[:20]
        j.huella = str(m.get("huella") or "")[:64]
        if isinstance(m.get("sabe"), list):                   # un juego anterior no lo manda: se le habla como siempre
            j.sabe = {x[:20] for x in m["sabe"][:30] if isinstance(x, str)}
        pub = str(m.get("pub", "")).lower()
        if len(pub) != 64 or any(ch not in "0123456789abcdef" for ch in pub):
            return self._rechazo(j, es("Tu juego no ha enviado una identidad válida."))
        reto = secrets.token_hex(24)
        self._enviar(j, {"t": "reto", "n": reto, "servidor": self.cfg["nombre"], "protocolo": j.proto, "v": VERSION_RED, "vmin": PROTOCOLO_MIN})
        f = await self._leer(lector, MAX_NORMAL, 20)
        if not f or f.get("t") != "firma":
            return False
        if self.cerrando:                                     # se ha empezado a cerrar mientras saludaba
            return self._rechazo(j, es("El servidor se está reiniciando. Prueba otra vez dentro de un momento."), "reiniciando")
        try:
            # Comprobar la firma cuesta unas décimas de segundo en una máquina modesta: se hace aparte, sin parar a los que juegan.
            valida = await asyncio.get_event_loop().run_in_executor(
                None, firma.verificar, binascii.unhexlify(pub), ("puertobravo-entrada|" + reto).encode("ascii"), binascii.unhexlify(str(f.get("f", ""))))
        except Exception:
            valida = False
        if not valida:
            return self._rechazo(j, es("No se ha podido comprobar tu identidad."))
        fila = self.alm.cuenta_por_pub(pub)
        vetados = self._nombres("vetados")
        if (fila is not None and (fila["vetado"] or fila["nombre"].lower() in vetados)) or (fila is None and limpiar_nombre(m.get("nombre")).lower() in vetados):
            return self._rechazo(j, es("No puedes entrar en este servidor."))
        minima = str(self.cfg.get("version_minima", "")).strip()
        if minima and version_tupla(j.juego) < version_tupla(minima):
            return self._rechazo(j, es("Este servidor pide la versión %s del juego o una posterior, y la tuya es la %s. Actualiza el juego para entrar.") % (minima, j.juego or es("desconocida")),
                                 "version", minima=minima)
        admins = self._nombres("admins")
        es_admin = (fila is not None and (bool(fila["admin"]) or fila["nombre"].lower() in admins)) or (fila is None and si(self.cfg["primer_admin"]) and not self.alm.hay_cuentas())
        # Se mira el mundo de quien entra si no es el del servidor. Y también si el del servidor es provisional (lo trajo
        # alguien sin firma a un servidor vacío) y este viene firmado, aunque diga la misma huella: el firmado es el que vale.
        distinto = j.huella != self.mundo["huella"] or (bool(self.mundo.get("provisional")) and bool(m.get("firmado")))
        if distinto and (si(self.cfg["comprobar_datos"]) or not self.mundo["mapas"]):
            vale, motivo = await self._admitir_mundo(j, lector, m, es_admin)
            if not vale:
                return self._rechazo(j, motivo)
        tope = int(self.cfg["max_jugadores"])                 # con 0 no hay límite; quien administra entra siempre
        if tope > 0 and not es_admin and self._cuantos() >= tope:
            return self._rechazo(j, es("El servidor está lleno."), "lleno")
        if fila is None:                                      # cuenta nueva: aquí se mira quién puede entrar
            modo = str(self.cfg["entrada"]).lower()
            if modo == "clave" and not secrets.compare_digest(str(m.get("clave", "")), hashlib.sha256(("puerto-bravo|" + str(self.cfg["clave"])).encode("utf-8")).hexdigest()):
                return self._rechazo(j, es("La contraseña de entrada no es correcta."))
            if modo == "invitacion" and not self.alm.invitacion_libre(str(m.get("invitacion", "")).strip().upper()):
                return self._rechazo(j, es("Este servidor es solo para invitados, y ese código de invitación no vale o ya se ha usado."))
            nombre = limpiar_nombre(m.get("nombre")) or es("Jugador")
            if len(nombre) < 2:
                return self._rechazo(j, es("Ese nombre es demasiado corto."))
            base, k = nombre, 2
            while self.alm.cuenta_por_nombre(nombre) is not None:
                nombre = "%s %d" % (base[:21], k)
                k += 1
            primera = si(self.cfg["primer_admin"]) and not self.alm.hay_cuentas()
            fila = self.alm.crear_cuenta(pub, nombre, admin=primera)
            if modo == "invitacion":
                self.alm.usar_invitacion(str(m.get("invitacion", "")).strip().upper(), fila["id"])
        heredado = None
        for o in list(self.jugadores.values()):               # una sola sesión por cuenta: la nueva echa a la vieja
            if o.cuenta == fila["id"] and o is not j and not si(self.cfg["varias_sesiones"]):
                if not o.dentro and o.fantasma:
                    # Se le cortó la conexión en plena pelea y vuelve antes de quince segundos: no quedan dos con su
                    # nombre. El que vuelve hereda la pelea, y no estrena protección de llegada: cortar no es escapatoria.
                    heredado = o
                    self.jugadores.pop(o.id, None)
                    self._a_todos({"t": "sale", "id": o.id})
                    continue
                estaba = o.dentro
                self._salida(o, callar=True)
                self._echar(o, es("Has entrado con tu personaje desde otro sitio."))
                if estaba:                                    # que a los demás no les queden dos con su nombre: el de antes se va
                    self._a_todos({"t": "sale", "id": o.id}, menos=o)
        j.cuenta, j.nombre = fila["id"], fila["nombre"]
        j.admin = bool(fila["admin"]) or j.nombre.lower() in admins
        mi = self.alm.miembro(j.cuenta)
        if mi is not None:
            j.banda, j.rango = mi["banda"], mi["rango"]
        j.protegido = time.monotonic() + float(self.cfg["proteccion"])
        if heredado is not None:
            j.protegido, j.golpeado, j.agredio = 0.0, dict(heredado.golpeado), dict(heredado.agredio)
        j.saldo = fila["saldo"] if "saldo" in fila.keys() else None
        try:
            j.misiones_pagadas = set(json.loads(fila["misiones"] or "[]"))
        except (ValueError, TypeError, IndexError):
            j.misiones_pagadas = set()
        j.margen = self._margen_de_entrada(fila)
        j.t_margen = time.monotonic()
        j.ficha = str((fila["ficha"] if "ficha" in fila.keys() else "") or "")[:MAX_FICHA]
        j.t_actividad = time.monotonic()
        j.dentro = True
        self.jugadores[j.id] = j
        partida = None
        if fila["partida"]:
            try:
                partida = json.loads(fila["partida"])
            except ValueError:
                partida = None
        j.total_guardado = self._dinero_de_partida(partida)
        dias_fuera = max(0, self.dia - int(fila["dia_salida"] or self.dia)) if fila["partida"] else 0
        pendientes = self.alm.pendientes(j.cuenta)
        try:                                                  # lo que perdió al caer estando fuera: su juego lo resta al entrar
            j.descuento = sum(max(0, int(c.get("pierde", 0) or 0)) for c in pendientes if isinstance(c, dict) and c.get("que") == "caido")
        except (TypeError, ValueError):
            j.descuento = 0
        if j.saldo is not None:
            # Lo que cobró estando fuera (le compraron una casa, o volvió al mercado) es dinero suyo: entra en su saldo.
            # Si no, su juego se lo daría y acto seguido se lo quitaría por no cuadrar con lo que el servidor tiene apuntado.
            try:
                cobrado = sum(max(0, int(c.get("n", 0) or 0)) for c in pendientes if isinstance(c, dict) and c.get("que") in ("venta", "caducada"))
            except (TypeError, ValueError):
                cobrado = 0
            if cobrado:
                j.saldo += cobrado
                self.alm.poner(j.cuenta, saldo=int(j.saldo))
        partida_de = (fila["juego"] if "juego" in fila.keys() else "") or ""      # con qué versión se guardó el personaje la última vez
        self.alm.poner(j.cuenta, visto=self.ahora(), juego=j.juego)
        if fila["partida"] and not (fila["partida_juego"] if "partida_juego" in fila.keys() else ""):
            # Un personaje de antes de que el servidor apuntara con qué versión se guardó: fue con la de su última entrada.
            self.alm.poner(j.cuenta, partida_juego=partida_de)
        self.alm.guardar()
        # Si su juego no es de la versión del mundo del servidor: qué no coincide, y el personaje sin lo que su juego no
        # conoce (un juego anterior puede fallar con un arma que no tiene). Lo apartado sigue guardado aquí.
        cat = self._cat(j)
        le_falta, sobra = compat.diferencias(self.mundo, cat, j.suyo)
        j.suyo = None
        para_el = compat.adaptar_partida(partida, cat)
        try:
            j.contrato = json.loads((fila["contrato"] if "contrato" in fila.keys() else "") or "{}")
            assert isinstance(j.contrato, dict)
        except (ValueError, TypeError, AssertionError):
            j.contrato = {}
        mundo_ok = {"version": self.mundo.get("version"), "huella": self.mundo.get("huella"), "igual": j.huella == self.mundo.get("huella")}
        if not mundo_ok["igual"] and cat is not None:         # un juego anterior no mira esta clave
            mundo_ok["distinto"] = {"faltan": le_falta, "sobran": sobra}
        self._enviar(j, {
            "t": "ok", "id": j.id, "nombre": j.nombre, "cuenta": j.cuenta, "admin": j.admin, "protegido": False,
            "protocolo": j.proto, "funciones": list(FUNCIONES),
            # Con qué mundo trabaja el servidor, y si es el mismo que trae este juego. Si no lo es, juegan juntos igual:
            # cada uno con lo que su versión conoce.
            "mundo": mundo_ok,
            "partida_de": partida_de,
            "jugadores": [o.publico() for o in self.jugadores.values() if o.dentro and o is not j],
            "servidor": {"nombre": self.cfg["nombre"], "bienvenida": self.cfg["bienvenida"], "pvp": si(self.cfg["pvp"]), "pasivo": si(self.cfg["modo_pasivo"]),
                         "seguras": si(self.cfg["zonas_seguras"]), "adultos": si(self.cfg["adultos"]), "trafico": self._tr_activo(), "peatones": self._pe_activo(), "policia": self._po_activo(), "proteccion": int(self.cfg["proteccion"]),
                         "max_jugadores": tope,
                         # lo de la 1.7.1: un juego anterior no mira estas claves
                         "rol": si(self.cfg["rol"]), "rol_metros": int(self.cfg["rol_metros"]), "radio_coches": si(self.cfg["radio_coches"]),
                         # la vida honrada, conectado: si hay nóminas de contrato fijo y si las tiendas tratan según el prestigio
                         "nominas": self._nominas() is not None, "trato_prestigio": si(self.cfg["trato_prestigio"]),
                         "economia": self._economia_datos(j),
                         "precios": {k: int(self.cfg[k]) for k in ("precio_banda", "precio_barrio", "renta_barrio", "precio_guerra", "guerra_espera", "guerra_dura")}},
            "ficha": j.ficha,
            "saldo": j.saldo if si(self.cfg["economia"]) else None,
            "partida": para_el, "dias_fuera": dias_fuera, "hora": self._hora(), "semilla": self.semilla,
            "contrato": self._contrato_publico(j),
            "banda": self._banda_datos(j.banda), "territorios": self._territorios(), "recompensa": int(fila["recompensa"] or 0),
            "pendientes": pendientes,
            "props": self._props(), "robos": self._robos_de_entrada(j),
            "vehiculos": [self._veh_publico(v) for v in self.vehiculos.values()],
            # los que el servidor tiene apuntados a nombre de este jugador y están aparcados (un juego anterior no lo mira)
            "mis_vehiculos": [v["id"] for v in self.vehiculos.values() if v.get("dueno") == j.cuenta and v["por"] is None]})
        dia = str(self.cfg.get("mensaje_dia", "")).strip()
        if dia:
            self._aviso(j, es("Mensaje del día: %s") % dia[:300], "notificacion")
        difiere = compat.texto_diferencias(le_falta, sobra)
        if difiere:                                           # qué no coincide entre su juego y este servidor, y qué va a notar
            self._aviso(j, difiere, "notificacion")
        if para_el is not partida:
            self._aviso(j, es("Tu personaje tiene armas o vehículos de una versión más nueva del juego. Con esta no los verás, pero no los pierdes: "
                           "se quedan guardados en el servidor y los tendrás otra vez cuando entres con esa versión."), "notificacion")
        self._a_todos({"t": "entra", "id": j.id, "nombre": j.nombre, "banda": j.banda}, menos=j)
        self.po_entra(j)
        if self.parando and self.parando != "apagado" and self._parada_fin > time.monotonic():      # entra en plena cuenta atrás: que lo sepa
            self._anunciar_parada(j, self.parando, self._parada_fin - time.monotonic(), VUELVE.get(self.parando, 0))
        self.log(tr("Entra %s%s. Hay %d.") % (j.nombre, (tr(", con el juego %s") % j.juego) if j.juego else "", self._cuantos()))
        return True

    def _robos_de_entrada(self, j):
        total = self.alm.cobrar_robos(j.cuenta)
        j.descuento += total                                  # su juego lo descuenta al entrar: no es una compra
        return total

    def _va_con(self, o):
        """El jugador en cuyo vehículo va «o» de pasajero, o None. Quien va dentro de un vehículo no anda por la calle:
        ni le atropellan, ni le atracan a pie, y la chapa le cubre como al conductor."""
        if o.pasajero_de is None or o.veh is not None:
            return None
        c = self.jugadores.get(o.pasajero_de)
        if c is None or not c.dentro or c.veh is None or c.mapa != o.mapa or c.dist(o) > 45:
            return None
        return c

    def _aviso_compat(self, j, clave, texto):
        """Un aviso de compatibilidad, una sola vez por sesión: algo de su versión del juego que aquí no existe."""
        if clave not in j.avisado and not j.bot:
            j.avisado.add(clave)
            self._aviso(j, texto, "notificacion")
    def _salida(self, j, callar=False):
        self._guardan.discard(j.id)
        if not j.dentro:
            return
        j.dentro = False
        ahora = time.monotonic()
        en_combate = any(ahora - t < 15 for t in j.golpeado.values()) or any(ahora - t < 15 for t in j.agredio.values())
        if j.vid is not None and j.vid in self.vehiculos:      # lo que conducía se queda aparcado donde estaba
            v = self.vehiculos[j.vid]
            v.update(por=None, m=j.mapa, x=j.x, y=j.y, r=j.rumbo, t=self.ahora())
            self._a_todos({"t": "veh_libre", "v": self._veh_publico(v)}, menos=j)
            j.vid = None
        self._grupo_salir(j, callar=True)
        self.invitaciones_grupo.pop(j.id, None)                # ni la que le hicieron, ni las que hizo
        for ident in [i for i, lider in self.invitaciones_grupo.items() if lider == j.id]:
            self.invitaciones_grupo.pop(ident, None)
        self.po_sale(j)
        self._devolver_sin_guardar(j)
        self._guardar_saldo(j)
        if j.cuenta is not None:
            self.alm.poner(j.cuenta, visto=self.ahora(), dia_salida=self.dia)
            self.alm.guardar()
        if en_combate and not callar and self.activo:
            j.fantasma = ahora + 15                            # salir no sirve de escapatoria: sigue ahí quince segundos
            j.conectado = False
            return
        self.jugadores.pop(j.id, None)
        if not callar:
            self._a_todos({"t": "sale", "id": j.id})
            self.log(tr("Sale %s.") % j.nombre)

    # ================================================================ mensajes
    def _mensaje(self, j, m):
        t = m.get("t")
        f = getattr(self, "_m_" + str(t), None) if isinstance(t, str) and t.replace("_", "").isalnum() else None
        if f is not None:
            f(j, m)

    def _m_ping(self, j, m):
        self._enviar(j, {"t": "pong"})

    def _m_estado(self, j, m):
        e = m.get("e")
        if not isinstance(e, dict):
            return
        try:
            mapa = e.get("m")
            if mapa not in self.mundo["mapas"]:
                # Una localidad que el mundo de este servidor no tiene: es de otra versión del juego, o de un mod. No se le
                # echa: sigue jugando allí por su cuenta, y a los demás les consta que anda por otra parte.
                if isinstance(mapa, str) and mapa and self.mundo["mapas"]:
                    j.mapa, j.mapa_fuera = None, mapa[:40]
                    j.t_actividad = time.monotonic()
                    self._aviso_compat(j, "mapa:" + mapa[:40], es("Esta localidad no existe en la versión del juego con la que va este servidor, la %s. "
                                       "Puedes estar en ella, pero aquí no verás a los demás jugadores ni ellos a ti.") % self.mundo.get("version", "?"))
                return
            cambio = mapa != j.mapa
            j.mapa, j.mapa_fuera = mapa, None
            x, y = finito(e.get("x") or 0), finito(e.get("y") or 0)
            rumbo, vel = finito(e.get("r") or 0), max(0.0, min(500.0, finito(e.get("s") or 0)))
            if cambio or abs(x - j.x) > 1.0 or abs(y - j.y) > 1.0:
                j.t_actividad = time.monotonic()               # se ha movido: no está parado
            j.x, j.y = x, y
            j.rumbo, j.vel = rumbo, vel
            j.veh = e.get("v") if e.get("v") in self.mundo["modelos"] else ("utilitario" if e.get("v") else None)
            j.salud = max(0.0, min(999.0, finito(e.get("sa", j.salud))))
            j.dinero = max(0, int(e.get("di", j.dinero)))
            j.banco = max(0, int(e.get("ba", j.banco)))
            self._cuadrar_saldo(j)
            j.arma = e.get("ar") if e.get("ar") in self.mundo["armas"] else "punos"
            if j.arma == "punos" and isinstance(e.get("ar"), str) and e.get("ar") not in ("", "punos") and self.mundo["armas"]:
                self._aviso_compat(j, "arma:" + e["ar"][:40], es("El arma que llevas no existe en la versión del juego con la que va este servidor: "
                                   "contra otros jugadores cuenta como ir con las manos."))
            j.barrio = e.get("b") if isinstance(e.get("b"), str) else None
            j.agachado, j.interior = bool(e.get("ag")), bool(e.get("in"))
            # Lo de la 1.7.1, que un juego anterior no manda: de quién va de pasajero y qué emisora del juego lleva puesta.
            if "pj" in e:
                pj = e.get("pj")
                j.pasajero_de = pj if isinstance(pj, int) and not isinstance(pj, bool) and pj != j.id and pj in self.jugadores else None
            ra = e.get("ra")
            j.radio = ra if (isinstance(ra, str) and 0 < len(ra) <= 24 and ra.replace("_", "").isalnum() and j.veh is not None
                             and si(self.cfg["radio_coches"])) else ""
            if not self._po_activo():                         # sin policía del servidor, la búsqueda la lleva su juego
                j.estrellas = max(0, min(5, int(e.get("es") or 0)))
                po = e.get("po")                              # y la policía que le persigue la ven también los que están cerca
                j.po = [f for f in po[:10] if isinstance(f, list) and 4 <= len(f) <= 6] if isinstance(po, list) and j.estrellas else []
            else:
                j.po = []
        except (TypeError, ValueError):
            return
        if j.vid is not None and j.vid in self.vehiculos:
            v = self.vehiculos[j.vid]
            v.update(m=j.mapa, x=j.x, y=j.y, r=j.rumbo)
            if j.veh is None and time.monotonic() - j.t_vid > 3:   # va a pie y no avisó de que lo dejaba
                self._soltar_vehiculo(j, v)
        if cambio:
            self._enviar(j, {"t": "territorios", "e": self._territorios()})

    # ================================================================= economía
    def _cuadrar_saldo(self, j):
        """El dinero de cada jugador lo lleva el servidor. Gastar, siempre. Ganar, lo que el servidor ha dado (botines,
        ventas, pagas, misiones comprobadas) y, por su cuenta, hasta un tanto por hora. Lo que pase de ahí no se reconoce."""
        if not si(self.cfg["economia"]):
            return
        total = j.dinero + j.banco
        if j.saldo is None:                                   # personaje nuevo: con lo que empieza, sin pasarse
            j.saldo = min(total, int(self.cfg["saldo_inicial"]))
        ahora = time.monotonic()
        if j.cobros:
            # Lo que cobra el servidor (fundar una banda, ingresar en la caja, comprarle una casa a otro) se descuenta aquí
            # al momento, pero al juego le llega un instante después: las posiciones que mandó mientras tanto todavía
            # traen ese dinero. No es dinero de más ni hay que quitárselo otra vez: es el mismo cobro, que está de camino.
            if ahora - j.t_cobros > 15:
                j.cobros = []                                 # quien no hace caso de un cobro no se queda con el dinero
            else:
                falta = sum(j.cobros)
                while j.cobros and total - j.saldo < falta:   # los primeros ya los ha restado su juego
                    falta -= j.cobros.pop(0)
                if falta > 0:
                    j.dinero = max(0, j.dinero - falta)
                    total -= falta
        tope = float(self.cfg["ganancia_hora"])
        # El margen que no se usa se guarda, hasta unas horas: así una buena racha cabe entera.
        j.margen = min(tope * self._acumula(), j.margen + (ahora - j.t_margen) * tope / 3600.0)
        j.t_margen = ahora
        delta = total - j.saldo
        if delta <= 0:
            if delta < 0:                                     # ha gastado: se apunta, por si su juego se lo tiene que devolver
                j.gastos.append([ahora, -delta])
                del j.gastos[:-8]
                ajeno = min(-delta, j.descuento)              # lo que le han quitado no es un gasto suyo
                j.descuento -= ajeno
                j.gasto_pend += -delta - ajeno                # y por si se corta la conexión antes de que guarde el personaje
            j.saldo = total
            if j.prop_pend:
                self._ver_pagos(j)
            return
        de_credito = min(delta, j.credito)
        j.credito -= de_credito
        de_fiado = 0                                          # la paga de un encargo repetible reconocido: vale un momento
        j.fiado = [f for f in j.fiado if ahora - f[0] <= 30 and f[1] > 0]
        for f in j.fiado:
            parte = min(delta - de_credito - de_fiado, f[1])
            f[1] -= parte
            de_fiado += parte
        de_margen = min(delta - de_credito - de_fiado, int(j.margen))
        j.margen -= de_margen
        j.saldo += de_credito + de_fiado + de_margen
        sobra = total - j.saldo
        if sobra > 0:
            j.dinero = max(0, j.dinero - sobra)               # para el servidor, ese dinero no existe
            if ahora - j.t_saldo > 4:
                j.t_saldo = ahora
                self.log(tr("A %s no se le reconocen %d euros de %d: el tope es de %d por hora.") % (j.nombre, sobra, delta, int(tope)))
                # Con las cifras: cuánto ha ganado, cuánto vale, cuál es el tope y cuándo vuelve a tener margen. Un juego
                # anterior solo mira «quita» y «saldo».
                self._enviar(j, dict(self._economia_datos(j), t="saldo", quita=sobra, saldo=j.saldo, ganado=int(delta), aceptado=int(delta - sobra)))

    def _acumula(self):
        try:
            return max(1, int(self.cfg.get("ganancia_acumula", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def _economia_datos(self, j):
        """Las cifras del tope de dinero, para decírselas al jugador con claridad. None si aquí el servidor no lleva el dinero."""
        if not si(self.cfg["economia"]):
            return None
        tope = int(self.cfg["ganancia_hora"])
        return {"tope": tope, "acumula": tope * self._acumula(), "horas": self._acumula(), "margen": int(max(0.0, j.margen)),
                "por_minuto": tope // 60, "encargos_hora": int(self.cfg["encargos_hora"]), "encargo_max": int(self.cfg["encargo_max"])}

    def _m_economia(self, j, m):
        """El jugador pregunta cómo va de margen: se le dice el tope, lo que le queda y a qué ritmo vuelve."""
        d = self._economia_datos(j)
        if d is not None:
            ahora = time.monotonic()
            j.margen = min(float(d["acumula"]), j.margen + (ahora - j.t_margen) * d["tope"] / 3600.0)
            j.t_margen = ahora
            d = self._economia_datos(j)
        self._enviar(j, {"t": "economia", "e": d})

    def _margen_de_entrada(self, fila):
        """Con cuánto margen entra: quien es nuevo, con un cuarto de hora; quien vuelve, con el que tenía más lo que se le
        ha ido acumulando mientras estaba fuera, hasta el tope de horas. Entrar y salir no lo rellena."""
        tope = float(self.cfg["ganancia_hora"])
        try:
            guardado = fila["margen"] if "margen" in fila.keys() else None
            cuando = fila["t_margen"] if "t_margen" in fila.keys() else None
            if guardado is None or cuando is None:
                return tope / 4.0
            return max(0.0, min(tope * self._acumula(), float(guardado) + max(0.0, self.ahora() - float(cuando)) * tope / 3600.0))
        except (TypeError, ValueError, IndexError):
            return tope / 4.0

    @staticmethod
    def _dinero_de_partida(p):
        """El dinero (bolsillo más banco) que hay en un personaje guardado, o None si no se puede saber."""
        try:
            jd = p["jugador"]
            return max(0, int(jd.get("dinero", 0) or 0)) + max(0, int(jd.get("banco", 0) or 0))
        except (TypeError, KeyError, ValueError, AttributeError):
            return None

    def _devolver_sin_guardar(self, j):
        """Se va sin que su juego haya guardado lo último (un corte de conexión): lo que gastó por su cuenta desde el último
        guardado se le reconoce otra vez, porque lo que compró no está en el personaje guardado. Nunca más de lo que ese
        personaje tiene: lo que cobró el servidor o le dio a otro jugador no vuelve."""
        if not si(self.cfg["economia"]) or j.bot or j.saldo is None or j.total_guardado is None or j.gasto_pend <= 0:
            return
        vuelve = int(min(j.gasto_pend, max(0, j.total_guardado - j.saldo)))
        j.gasto_pend = 0
        if vuelve > 0:
            j.saldo += vuelve
            self.log(tr("%s se ha ido sin guardar su última compra: se le reconocen otra vez %d euros.") % (j.nombre, vuelve))

    def _encargo_tope(self, tipo):
        """Lo más que paga un encargo repetible de ese tipo, o None si el servidor no lo conoce."""
        try:
            suyo = (self.mundo.get("encargos") or {}).get(tipo)
            n = int(suyo) if suyo is not None else ENCARGOS_DE_SERIE.get(tipo)
        except (TypeError, ValueError, AttributeError):
            n = ENCARGOS_DE_SERIE.get(tipo)
        return None if n is None else max(0, min(int(n), int(self.cfg["encargo_max"])))

    def _encargo(self, j, tipo, paga):
        """Ha cumplido un encargo repetible (un contrato, un combate, un atraco): su paga queda justificada, sin gastar la
        ganancia por hora, hasta un número de veces por hora de cada tipo y con un máximo por encargo."""
        if not si(self.cfg["economia"]) or j.bot or j.cuenta is None:
            return
        tipo = str(tipo)[:40]
        por_hora = int(self.cfg["encargos_hora"])
        tope = self._encargo_tope(tipo)
        try:
            paga = max(0, int(paga))
        except (TypeError, ValueError):
            return
        if por_hora <= 0 or tope is None or paga <= 0:
            return
        ahora = time.monotonic()
        mios = self.encargos.setdefault(j.cuenta, {})
        hechos = [x for x in mios.get(tipo, []) if ahora - x < 3600]
        if len(hechos) >= por_hora:
            mios[tipo] = hechos
            if ahora - j.t_aviso_encargo > 60:
                j.t_aviso_encargo = ahora
                falta = int((3600 - (ahora - hechos[0])) // 60) + 1
                self._aviso(j, es("Ya has cobrado %d encargos de este tipo en la última hora, que es lo que este servidor reconoce: este cuenta "
                                  "contra tu ganancia por hora. Dentro de %d minutos vuelve a reconocerte otro.") % (por_hora, falta))
            return
        mios[tipo] = hechos + [ahora]
        j.fiado.append([ahora, min(paga, tope)])

    def _ver_pagos(self, j):
        """Casa cada compra de casa o negocio pendiente con un gasto que se le haya visto al jugador en esos segundos. La
        que casa queda como pagada; la que en veinte segundos no ha casado se queda sin pagar: suya, pero sin valor de venta."""
        ahora = time.monotonic()
        for lugar, (cuando, precio) in list(j.prop_pend.items()):
            falta = precio
            usados = []
            for g in j.gastos:
                if g[1] > 0 and cuando - 6 <= g[0] <= cuando + 20:
                    parte = min(falta, g[1])
                    usados.append((g, parte))
                    falta -= parte
                    if falta <= 0:
                        break
            if falta <= 0:
                for g, parte in usados:
                    g[1] -= parte                              # ese gasto ya ha servido para esto: no vale también para otra cosa
                j.gasto_pend = max(0, j.gasto_pend - precio)   # y la casa ya es suya en el servidor: ese dinero no vuelve
                self.alm.marcar_pagada(lugar, j.cuenta)
                del j.prop_pend[lugar]
            elif ahora - cuando > 20:
                del j.prop_pend[lugar]

    def _devolucion(self, j, n):
        """El juego de un jugador le devuelve lo que pagó por algo que al final no es suyo (una casa que otro compró un
        instante antes). Se da por bueno solo lo que el servidor le ha visto gastar hace un momento: quien no pagó nada
        no recibe nada por pedir casas ajenas."""
        if not si(self.cfg["economia"]) or j.bot:
            return
        ahora = time.monotonic()
        for g in reversed(j.gastos):
            if n <= 0:
                break
            if ahora - g[0] <= 20 and g[1] > 0:
                parte = min(n, g[1])
                g[1] -= parte
                n -= parte
                j.credito += parte

    def _m_mision_ok(self, j, m):
        """Ha completado una misión de su historia: su recompensa queda justificada, una vez."""
        mi = self.mundo["misiones"].get(m.get("id")) if isinstance(m.get("id"), str) else None
        if mi is None:
            # No es de la historia: es un encargo repetible que el juego arma al momento (un contrato, un combate del
            # gimnasio, un atraco, un encargo de coche). El juego dice cuánto ha pagado; el servidor, hasta dónde lo cree.
            if m.get("encargo") and isinstance(m.get("id"), str):
                self._encargo(j, m["id"], m.get("n"))
            return
        if mi["dinero"] <= 0:
            return
        if not mi["repetible"]:
            if m["id"] in j.misiones_pagadas:
                return
            j.misiones_pagadas.add(m["id"])
            self.alm.poner(j.cuenta, misiones=json.dumps(sorted(j.misiones_pagadas)))
            j.credito += int(mi["dinero"])
        else:
            self._encargo(j, m["id"], mi["dinero"])

    def _guardar_saldo(self, j):
        if j.cuenta is not None and j.saldo is not None and not j.bot:
            self.alm.poner(j.cuenta, saldo=int(j.saldo), margen=float(j.margen), t_margen=float(self.ahora()))

    def _m_guardar(self, j, m):
        self._guardar_saldo(j)
        p = m.get("p")
        if isinstance(p, dict):
            # El personaje se guarda entero, con todo lo que traiga, también lo que este servidor no conoce. Y si lo guarda
            # un juego anterior al que lo guardó la última vez, lo que ese juego no sabe guardar (los campos, las armas y
            # los vehículos de la versión más nueva) se conserva de lo que había: pasar por una versión anterior no borra nada.
            de = j.juego
            fila = self.alm.cuenta(j.cuenta)
            antes_de = ((fila["partida_juego"] if fila is not None and "partida_juego" in fila.keys() else "") or "") if fila is not None else ""
            if fila is not None and fila["partida"] and antes_de and version_tupla(j.juego) < version_tupla(antes_de):
                try:
                    p = compat.fundir_partida(p, json.loads(fila["partida"]), self._cat(j) or self.catalogos.get(j.huella))
                    de = antes_de
                except (ValueError, TypeError):
                    pass
            texto = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
            if len(texto) > MAX_LINEA:
                if "guardar" not in j.raros:                  # una vez por sesión: no se guarda, y que se sepa
                    j.raros.add("guardar")
                    self.log(tr("El personaje de %s ocupa demasiado (%d KB) y no se guarda: queda el anterior.") % (j.nombre, len(texto) // 1024))
                    self._aviso(j, es("Tu personaje ocupa demasiado para este servidor y no se ha podido guardar: queda como estaba en el guardado anterior."), "error")
            else:
                self.alm.poner(j.cuenta, partida=texto, dia_salida=self.dia, partida_juego=de)
                j.gasto_pend, j.total_guardado = 0, self._dinero_de_partida(p)      # lo comprado hasta aquí ya está en el personaje
            if m.get("ya"):
                self.alm.guardar()
                self._enviar(j, {"t": "guardado"})
                self._guardan.discard(j.id)                    # si el servidor se está parando, de este ya no hay que esperar nada

    # ------------------------------------------------------------- contratos fijos y nóminas
    # El contrato lo vive el juego de cada uno (el jefe, la evaluación, los avisos), pero el dinero lo pone el servidor:
    # él cuenta los turnos, él sabe cuándo acaba el periodo y él paga la nómina, con las cifras del mundo y sus topes.
    # Lo que diga el juego sobre cuánto cobra no cuenta para nada.
    def _nominas(self):
        """Los contratos fijos del mundo, si aquí se pagan nóminas. None si el dueño las ha quitado o si el mundo del servidor
        no los trae (el de una versión anterior a la 1.7.1)."""
        return self.empleos if self.empleos and si(self.cfg.get("nominas", "si")) else None

    def _contrato_publico(self, j):
        """Lo que el juego necesita saber de su contrato en este servidor. None si aquí no hay nóminas."""
        e = self._nominas()
        if e is None:
            return None
        c = j.contrato if isinstance(j.contrato, dict) and j.contrato.get("e") in e["puestos"] else {}
        out = {"periodo": e["periodo"], "tope": int(self.cfg.get("nomina_max", 0)), "turnos_dia": int(self.cfg.get("nomina_turnos_dia", 0))}
        if c:
            out.update(empleo=c["e"], puesto=int(c.get("p", 0)), turnos=int(c.get("t", 0)), fin=int(c.get("fin", self.dia)))
        return out

    def _guardar_contrato(self, j):
        if j.cuenta is not None and not j.bot:
            self.alm.poner(j.cuenta, contrato=json.dumps(j.contrato, separators=(",", ":")) if j.contrato else "")

    def _m_contrato(self, j, m):
        e = self._nominas()
        que = m.get("que")
        if e is None:
            return self._enviar(j, {"t": "contrato", "que": "no", "motivo": es("En este servidor no hay nóminas de contratos fijos.")})
        c = j.contrato if isinstance(j.contrato, dict) else {}
        if que == "firmar":
            empleo = m.get("empleo")
            if not isinstance(empleo, str) or empleo not in e["puestos"]:
                return self._enviar(j, {"t": "contrato", "que": "no", "motivo": es("Ese empleo no existe en la versión del juego con la que va este servidor.")})
            # Se entra por abajo; con una carta de recomendación, un escalón más arriba, que es lo más que da el juego.
            puesto = 1 if m.get("puesto") == 1 and len(e["puestos"][empleo]) > 1 else 0
            if c.get("e") == empleo:                           # ya lo tenía firmado aquí: sigue como iba, no empieza otro periodo
                return self._enviar(j, {"t": "contrato", "que": "firmado", "c": self._contrato_publico(j)})
            j.contrato = {"e": empleo, "p": puesto, "t": 0, "fin": self.dia + e["periodo"], "dia": self.dia, "hoy": 0, "sube": 0}
            self._guardar_contrato(j)
            return self._enviar(j, {"t": "contrato", "que": "firmado", "c": self._contrato_publico(j)})
        if not c or c.get("e") not in e["puestos"]:
            if que != "dejar":
                self._enviar(j, {"t": "contrato", "que": "no", "motivo": es("Este servidor no tiene apuntado ningún contrato tuyo.")})
            j.contrato = {}
            return self._guardar_contrato(j)
        puestos = e["puestos"][c["e"]]
        k = max(0, min(len(puestos) - 1, int(c.get("p", 0))))
        cupo, sueldo = puestos[k]
        if que == "dejar":
            j.contrato = {}
            self._guardar_contrato(j)
        elif que == "turno":
            if c.get("dia") != self.dia:
                c["dia"], c["hoy"] = self.dia, 0
            if int(c.get("hoy", 0)) < int(self.cfg["nomina_turnos_dia"]):      # no más turnos al día de los que caben en un día
                c["hoy"] = int(c.get("hoy", 0)) + 1
                c["t"] = min(cupo * 3, int(c.get("t", 0)) + 1)
                self._guardar_contrato(j)
            self._enviar(j, {"t": "contrato", "que": "turno", "c": self._contrato_publico(j)})
        elif que == "ascenso":
            # Sube un puesto, y solo uno, tras un periodo cobrado con el cupo cumplido: el juego decide si lo merece; el
            # servidor, que no vaya más deprisa de lo que se puede.
            if int(c.get("sube", 0)) > 0 and k + 1 < len(puestos):
                c["p"], c["sube"] = k + 1, 0
                self._guardar_contrato(j)
            self._enviar(j, {"t": "contrato", "que": "puesto", "c": self._contrato_publico(j)})
        elif que == "cobrar":
            falta = int(c.get("fin", self.dia)) - self.dia
            if falta > 0:                                      # aún no toca: ni se paga ni cambia nada, se pida las veces que se pida
                return self._enviar(j, {"t": "nomina", "n": 0, "faltan": falta, "c": self._contrato_publico(j)})
            turnos = int(c.get("t", 0))
            parte = min(1.0, turnos / float(cupo))
            paga = int(sueldo * parte)
            if turnos >= cupo and m.get("buena"):              # la prima por una buena evaluación, la del mundo y no más
                paga += int(sueldo * e["prima"] / 100.0)
            paga = max(0, min(paga, int(self.cfg["nomina_max"])))
            if m.get("mala"):                                  # su jefe no le paga este periodo: el juego lo dice, y el servidor no insiste
                paga = 0
            c.update(t=0, fin=self.dia + e["periodo"], sube=1 if turnos >= cupo else 0)
            self._guardar_contrato(j)
            self._guardar_saldo(j)
            if paga > 0:
                self.log(tr("Nómina de %s: %d euros por %d de %d turnos.") % (j.nombre, paga, turnos, cupo))
            self._enviar(j, {"t": "nomina", "n": paga, "turnos": turnos, "cupo": cupo, "c": self._contrato_publico(j)})

    def _m_aspecto(self, j, m):
        """Lo que lleva puesto un jugador, como lo cuenta su juego: se reparte tal cual a los demás. El servidor no sabe de
        ropa ni tiene por qué: la da el juego de cada uno."""
        texto = "".join(c for c in str(m.get("texto", "")) if c.isprintable())[:200]
        j.aspecto = texto
        self._a_todos({"t": "aspecto", "de": j.id, "texto": texto}, menos=j)

    def _m_chat(self, j, m):
        texto = str(m.get("texto", "")).strip()[:300]
        if not texto:
            return
        canal = m.get("canal") if m.get("canal") in CANALES + CANALES_ROL else "todos"
        if texto.startswith("/"):
            # Las órdenes de rol las puede escribir cualquiera, y con cualquier versión del juego: barra yo, barra ep
            # (en personaje), barra fp (fuera de personaje) y barra ficha. Las demás son de quien administra.
            orden, _, resto = texto[1:].partition(" ")
            de_rol = ORDENES_ROL.get(orden.lower())
            if de_rol == "ficha":
                return self._m_ficha(j, {"texto": resto})
            if de_rol is not None:
                canal, texto = de_rol, resto.strip()
                if not texto:
                    return self._aviso(j, es("Detrás de esa orden va lo que quieres decir. Por ejemplo: barra yo abre la puerta."))
            elif j.admin:
                return self._aviso(j, self.orden(texto[1:], j.nombre))
        if canal in CANALES_ROL:
            return self._chat_rol(j, canal, texto)
        obj = {"t": "chat", "de": j.id, "nombre": j.nombre, "texto": texto, "canal": canal}
        if canal == "cerca":
            for o in self.jugadores.values():
                if o.dentro and o is not j and o.mapa == j.mapa and j.dist(o) <= 80:
                    self._enviar(o, obj)
        elif canal == "banda":
            if j.banda is None:
                return self._aviso(j, es("No estás en ninguna banda."))
            self._a_banda(j.banda, obj, menos=j)
        elif canal == "grupo":
            for o in self._grupo(j):
                if o is not j:
                    self._enviar(o, obj)
        elif canal == "priv":
            o = self.jugadores.get(m.get("a"))
            if o is not None and o.dentro:
                self._enviar(o, obj)
        else:
            self._a_todos(obj, menos=j)

    def _chat_rol(self, j, canal, texto):
        """Los canales de rol. En personaje («ic») y las acciones («yo») llegan a quien está cerca; fuera de personaje
        («ooc»), a todo el servidor. A quien juega con una versión que no los conoce le llegan por el chat de siempre,
        con unas palabras delante que dicen qué son."""
        if not si(self.cfg["rol"]):
            return self._aviso(j, es("En este servidor los canales de rol están apagados: usa el chat de siempre."))
        texto = "".join(ch for ch in texto if ch.isprintable()).strip()
        if not texto:
            return
        metros = float(self.cfg["rol_metros"])
        nuevo = {"t": "chat", "de": j.id, "nombre": j.nombre, "texto": texto, "canal": canal}
        if canal == "ooc":
            viejo = dict(nuevo, canal="todos", texto=es("(fuera de personaje) %s") % texto)
        elif canal == "yo":
            viejo = dict(nuevo, canal="cerca", texto=es("(acción) %s %s") % (j.nombre, texto))
        else:
            viejo = dict(nuevo, canal="cerca", texto=es("(en personaje) %s") % texto)
        oyen = 0
        for o in self.jugadores.values():
            if not o.dentro or o is j or o.bot:
                continue
            if canal != "ooc" and (j.mapa is None or o.mapa != j.mapa or j.dist(o) > metros):
                continue
            oyen += 1
            self._enviar(o, nuevo if "rol" in o.sabe else viejo)
        if "rol" in j.sabe:                                     # para que sepa si le ha oído alguien: no se ve quién hay cerca
            self._enviar(j, {"t": "rol_oido", "canal": canal, "n": oyen})
        elif oyen == 0 and canal != "ooc":
            self._aviso(j, es("No hay nadie lo bastante cerca para oírlo."))

    def _m_ficha(self, j, m):
        """La frase de ficha de un jugador: con «a», leer la de otro; sin ella, poner la propia (vacía, la quita)."""
        if "a" in m:
            o = self.jugadores.get(m.get("a")) if isinstance(m.get("a"), int) else None
            if o is None or not o.dentro:
                return self._aviso(j, es("Esa persona ya no está."))
            return self._enviar(j, {"t": "ficha", "de": o.id, "nombre": o.nombre, "texto": o.ficha if si(self.cfg["rol"]) else ""})
        if not si(self.cfg["rol"]):
            return self._aviso(j, es("En este servidor los canales de rol están apagados: no hay fichas."))
        texto = " ".join("".join(ch for ch in str(m.get("texto", "")) if ch.isprintable()).split())[:MAX_FICHA]
        j.ficha = texto
        if j.cuenta is not None and not j.bot:
            self.alm.poner(j.cuenta, ficha=texto)
        if "rol" in j.sabe:
            self._enviar(j, {"t": "ficha", "de": j.id, "nombre": j.nombre, "texto": texto, "tuya": True})
        else:
            self._aviso(j, (es("Tu ficha dice ahora: %s") % texto) if texto else es("Has quitado tu ficha."))

    def _m_act(self, j, m):
        d = m.get("d")
        if isinstance(d, dict) and len(json.dumps(d)) < 3000:
            # Subir y bajar del vehículo de otro lo cuenta así el juego, también el de antes de la 1.7.1: de aquí sabe el
            # servidor quién va de pasajero aunque ese juego no lo diga con su posición.
            if d.get("que") == "sube" and isinstance(d.get("a"), int) and not isinstance(d.get("a"), bool) and d["a"] != j.id and d["a"] in self.jugadores:
                j.pasajero_de = d["a"]
            elif d.get("que") == "baja":
                j.pasajero_de = None
            self._a_todos({"t": "act", "de": j.id, "nombre": j.nombre, "d": d}, menos=j)

    def _m_evento(self, j, m):
        que = str(m.get("que", ""))[:20]
        self._a_todos({"t": "evento", "de": j.id, "que": que}, menos=j, mapa=j.mapa)
        if j.mapa is None:
            return
        if que.startswith("d:") or que == "grito":             # la gente de la calle se asusta, y si hay una patrulla cerca, lo ve
            self.peatones_susto(j.mapa, j.x, j.y, 40 if que.startswith("d:") else 15)
            if que.startswith("d:"):
                self.patrulla_ve(j)

    def _m_dinero(self, j, m):
        o = self.jugadores.get(m.get("a"))
        try:
            n = max(1, min(100000, int(m.get("n", 0))))
        except (TypeError, ValueError):
            return
        if o is None or not o.dentro or o is j:
            return
        if si(self.cfg["economia"]) and not j.bot:
            # El dinero lo lleva el servidor: lo que uno da sale de su saldo, y tiene que llevarlo encima. Si no, quien
            # recibe tendría dinero que no ha salido de ningún bolsillo. Quien acaba de entrar y aún no ha dicho cuánto
            # lleva, no lleva nada.
            if j.saldo is None or j.dinero < n:
                self._aviso(j, es("No llevas %d euros encima: no se entregan.") % n, "error")
                self._enviar(j, {"t": "dinero", "nombre": es("El servidor, de vuelta"), "n": n})      # su juego ya los había restado
                j.credito = max(0, j.credito - n)             # una devolución no es dinero nuevo
                return
            j.dinero -= n
            j.saldo = max(0, j.saldo - n)
        self._enviar(o, {"t": "dinero", "de": j.id, "nombre": j.nombre, "n": n})

    def _m_dar(self, j, m):
        """Dar un arma, munición o un objeto a otro jugador que está al lado."""
        o = self.jugadores.get(m.get("a"))
        if o is None or not o.dentro or o is j or o.mapa != j.mapa or j.dist(o) > 12:
            return self._aviso(j, es("Esa persona ya no está a tu lado."))
        try:
            n = max(1, min(999, int(m.get("n", 1))))
        except (TypeError, ValueError):
            return
        clase = m.get("clase") if m.get("clase") in ("arma", "balas", "objeto") else None
        ident = str(m.get("id", ""))[:40]
        if clase is None or not ident:
            return
        cat = self._cat(o)
        if clase in ("arma", "balas") and cat is not None and ident not in cat["armas"]:
            # El juego del otro es de una versión que no tiene esa arma: no la puede recibir. A quien la daba, su juego ya se
            # la había quitado: se le devuelve, para que no se pierda por el camino.
            self._enviar(j, {"t": "recibe", "de": j.id, "nombre": es("El servidor, de vuelta"), "clase": clase, "id": ident, "n": n})
            return self._aviso(j, es("%s juega con una versión del juego que no tiene esa arma: no la puede recibir, y te la quedas.") % o.nombre, "error")
        self._enviar(o, {"t": "recibe", "de": j.id, "nombre": j.nombre, "clase": clase, "id": ident, "n": n})
        self._enviar(j, {"t": "dado", "a": o.id, "nombre": o.nombre, "clase": clase, "id": ident, "n": n})

    def _m_quien(self, j, m):
        self._enviar(j, {"t": "quien", "e": [dict(o.publico(), mapa=o.mapa, pasivo=o.pasivo, recompensa=self._recompensa(o)) for o in self.jugadores.values() if o.dentro]})

    def _recompensa(self, j):
        f = self.alm.cuenta(j.cuenta)
        return int(f["recompensa"] or 0) if f else 0

    # ============================================================ hora y mundo
    def _hora(self):
        return {"reloj": round(self.reloj, 1), "dia": self.dia, "lluvia": self.lluvia, "luces": round(self.t_luces, 2)}

    def segura(self, j):
        if not si(self.cfg["zonas_seguras"]):
            return False
        if j.interior:
            return True
        return any(math.hypot(j.x - x, j.y - y) <= RADIO_SEGURO for x, y in self.seguras.get(j.mapa, ()))

    async def _bucle_estados(self):
        n = 0
        while self.activo:
            await asyncio.sleep(0.1)
            n += 1
            try:
                self.bots_mover(0.1)
                self.trafico_mover(0.1)
                self.peatones_mover(0.1)
                self.policia_mover(0.1)
            except Exception as e:
                self.log(tr("Error moviendo a los personajes y el tráfico del servidor: %s: %s") % (type(e).__name__, e))
            try:
                self._repartir_estados(n)
            except Exception as e:
                self.log(tr("Error repartiendo las posiciones: %s: %s") % (type(e).__name__, e))

    def _repartir_estados(self, n):
        """Diez veces por segundo: a cada jugador, dónde están los demás.

        Pensado para que valga igual con cuatro que con cuatrocientos, en procesador y en red:
        - La ficha de cada jugador se escribe una sola vez por vuelta, no una por cada uno que la recibe, y se agrupa por
          localidad y por zona. A los que están en la misma zona les llega el mismo texto, ya hecho.
        - A cada cual le llegan al detalle, diez veces por segundo, los que tiene cerca (su zona y las de alrededor).
        - De los demás de su localidad le llega una ficha corta, con dónde andan, una vez por segundo.
        - De los de las demás localidades, lo mismo cada dos segundos.
        - Si alrededor hay una multitud, las fichas al detalle se reparten menos veces por segundo.
        Con radio_detalle a 0 se reparte todo al detalle y siempre, como cuando hay poca gente."""
        todos = [j for j in self.jugadores.values() if j.dentro or j.fantasma]
        radio = float(self.cfg.get("radio_detalle", 0) or 0)
        medio = n % 10 == 0                                    # una vez por segundo, toda la localidad
        lejos = n % 20 == 0                                    # cada dos segundos, las demás localidades
        escribir = json.dumps
        zonas, cuantos = {}, {}                                # (localidad, zona) -> fichas al detalle, y cuántas son
        cortas = {}                                            # localidad -> fichas cortas
        mia, mia_corta = {}, {}                                # la de cada uno, para quitarla de lo que se le manda
        huella_mundo = self.mundo.get("huella")
        conducidos = {o.veh for o in todos if o.veh and o.veh in self.mundo["modelos"]}      # los modelos que hay ahora mismo en marcha
        for o in todos:
            if o.mapa is None:
                if lejos and o.dentro and o.mapa_fuera:        # en una localidad que este servidor no conoce
                    f = '"%d":%s,' % (o.id, escribir({"m": o.mapa_fuera, "x": 0, "y": 0, "r": 0, "v": None, "s": 0}, separators=(",", ":")))
                    mia_corta[o.id] = f
                    cortas.setdefault(None, []).append(f)
                continue
            ficha = {"m": o.mapa, "x": round(o.x, 1), "y": round(o.y, 1), "r": round(o.rumbo), "v": o.veh, "s": round(o.vel, 1),
                     "vi": o.vid, "ag": int(o.agachado), "pa": int(o.pasivo), "sg": int(self.segura(o)), "in": int(o.interior), "es": o.estrellas}
            if o.po:
                ficha["po"] = o.po
            if o.radio:
                ficha["ra"] = o.radio
            if o.pasajero_de is not None and self._va_con(o) is not None:
                ficha["pj"] = o.pasajero_de
            f = '"%d":%s,' % (o.id, escribir(ficha, separators=(",", ":")))
            mia[o.id] = f
            clave = (o.mapa, int(o.x // radio), int(o.y // radio)) if radio > 0 else (o.mapa, 0, 0)
            zonas.setdefault(clave, []).append(f)
            if (medio and radio > 0) or lejos:
                f = '"%d":%s,' % (o.id, escribir({"m": o.mapa, "x": round(o.x), "y": round(o.y), "r": 0, "v": o.veh, "s": 0}, separators=(",", ":")))
                mia_corta[o.id] = f
                cortas.setdefault(o.mapa, []).append(f)
        for clave, fichas in zonas.items():
            cuantos[clave] = len(fichas)
            zonas[clave] = "".join(fichas)
        cortas = {mapa: "".join(fichas) for mapa, fichas in cortas.items()}
        alrededor, de_fuera = {}, {}                           # lo que rodea a cada zona y lo de fuera de cada localidad: se hace una vez
        po_activo, pe_activo = self._po_activo(), self._pe_activo()
        tr_o_po = self._tr_activo() or po_activo
        for j in todos:
            if not j.dentro or j.bot:
                continue
            partes = ""
            if j.mapa is not None:
                clave = (j.mapa, int(j.x // radio), int(j.y // radio)) if radio > 0 else (j.mapa, 0, 0)
                cerca = alrededor.get(clave)
                if cerca is None:
                    if radio > 0:
                        trozos, gente = [], 0
                        for dx in (-1, 0, 1):
                            for dy in (-1, 0, 1):
                                otra = (clave[0], clave[1] + dx, clave[2] + dy)
                                if otra in zonas:
                                    trozos.append(zonas[otra])
                                    gente += cuantos[otra]
                        cerca = ("".join(trozos), gente)
                    else:
                        cerca = (zonas.get(clave, ""), 0)
                    alrededor[clave] = cerca
                texto, gente = cerca
                cada = 1 if gente <= 24 else 2 if gente <= 60 else 4      # entre una multitud, menos veces por segundo
                if radio > 0 and medio:
                    # primero las fichas cortas de toda la localidad y después las de detalle: si alguien sale dos veces, vale la última
                    partes = cortas.get(j.mapa, "").replace(mia_corta[j.id], "", 1) + texto.replace(mia[j.id], "", 1)
                elif n % cada == 0:
                    partes = texto.replace(mia[j.id], "", 1)
            if lejos:
                fuera = de_fuera.get(j.mapa)
                if fuera is None:
                    fuera = de_fuera[j.mapa] = "".join(t for mapa, t in cortas.items() if mapa != j.mapa or mapa is None)
                if j.mapa is None and j.id in mia_corta:
                    fuera = fuera.replace(mia_corta[j.id], "", 1)
                partes = fuera + partes
            if partes and j.huella != huella_mundo:            # su juego es de otra versión: los vehículos que no conoce, por el más parecido
                cat = self._cat(j)
                if cat is not None:
                    for modelo in conducidos:
                        if modelo not in cat["modelos"]:
                            partes = partes.replace('"v":%s,' % escribir(modelo), '"v":%s,' % escribir(self._modelo_eq(cat, modelo)))
            mas = {}
            if j.mapa is not None and n % 2 == 0:
                if po_activo:
                    mas["es"] = j.estrellas                    # su nivel de búsqueda: el que vale es este
                    ag = self.agentes_para(j)                  # los agentes a pie que tiene cerca
                    if ag or getattr(j, "ve_agentes", False):
                        mas["po"] = ag
                    j.ve_agentes = bool(ag)
                if tr_o_po:                                    # el tráfico de su localidad, cinco veces por segundo
                    mas["tr"] = self.trafico_para(j)
                    mas["lu"] = round(self.t_luces, 2)         # y la hora de los semáforos, para que no se desajusten
                if pe_activo:
                    mas["pe"] = self.peatones_para(j)          # y la gente de la calle que tiene cerca
                    mas["lu"] = round(self.t_luces, 2)
            if partes or "tr" in mas or "pe" in mas or "po" in mas:
                cuerpo = '{"t":"estados","e":{' + partes[:-1] + "}"
                if mas:
                    cuerpo += "," + escribir(mas, separators=(",", ":"))[1:-1]
                self._enviar(j, ESTADOS, (cuerpo + "}\n").encode("utf-8"))

    async def _bucle_lento(self):
        """Cada segundo: el reloj, las guerras, los que se fueron en combate, los vehículos viejos y el guardado."""
        k = 0
        while self.activo:
            await asyncio.sleep(1.0)
            k += 1
            try:
                self._mirar_orden()
                self._tic(1.0, k)
            except Exception as e:
                self.log(tr("Error en el reloj del servidor: %s: %s") % (type(e).__name__, e))

    def _tic(self, dt, k):
        self.reloj += dt / 2.0                                 # un minuto del juego son dos segundos, como en el juego
        if self.reloj >= 1440:
            self.reloj -= 1440
            self.dia += 1
            self._medianoche()
        if k % 30 == 0:
            if self.rng.random() < 0.04:
                self.lluvia = not self.lluvia
            self._a_todos({"t": "hora", "h": self._hora()})
        ahora = time.monotonic()
        parado = 60.0 * int(self.cfg.get("inactividad_minutos", 0) or 0)
        for j in list(self.jugadores.values()):
            if not j.dentro and j.fantasma and ahora >= j.fantasma:
                self.jugadores.pop(j.id, None)
                self._a_todos({"t": "sale", "id": j.id})
            elif j.dentro and not j.bot and ahora - j.t_ultimo > 75:
                self._cortar(j)
            elif parado > 0 and j.dentro and not j.bot and not j.admin and ahora - j.t_actividad > parado:
                self.log(tr("%s lleva %d minutos sin hacer nada: se le saca para dejar sitio.") % (j.nombre, parado // 60))
                self._echar(j, es("Llevas %d minutos sin hacer nada y el servidor te ha sacado para dejar sitio. Tu personaje está guardado: puedes volver a entrar.") % (parado // 60))
                j.t_actividad = ahora
        self.bots_pensar(dt)
        self.trafico_pensar()
        self.peatones_pensar()
        self.policia_pensar()
        self._guerras_paso(dt)
        self._robos_paso()
        if k % 60 == 0:
            tope = self.ahora() - 3600.0 * int(self.cfg["vehiculos_horas"])
            for v in [v for v in self.vehiculos.values() if v["por"] is None and v.get("t", 0) < tope]:
                self._quitar_vehiculo(v["id"])
            for ident in [i for i, d in self.invitaciones_banda.items() if d["hasta"] < ahora]:
                self.invitaciones_banda.pop(ident, None)
        if ahora - self._t_guardado >= 60.0 * max(1, int(self.cfg.get("guardado_minutos", 1) or 1)):
            self._t_guardado = ahora
            self.guardar_todo()
        horas = int(self.cfg.get("copia_auto_horas", 0) or 0)
        if horas > 0 and ahora - self._t_copia >= 3600.0 * horas:
            self._t_copia = ahora
            try:
                self.log(tr("Copia de seguridad automática hecha: %s") % os.path.basename(self.copia_seguridad(automatica=True)))
            except Exception as e:
                self.log(tr("No se ha podido hacer la copia de seguridad automática: %s: %s") % (type(e).__name__, e))

    def copia_seguridad(self, automatica=False):
        """Guarda todo y hace una copia de seguridad en la carpeta copias, dentro de la de datos. Devuelve su ruta."""
        self.guardar_todo()
        ruta = copias.hacer(self.cfg["datos"], conexion=self.alm.db, conf=self.ruta_conf, automatica=automatica)
        if automatica:
            copias.podar(self.cfg["datos"], int(self.cfg.get("copias_guardar", 7) or 7))
        return ruta
    def _medianoche(self):
        renta = int(self.cfg["renta_barrio"])
        cuentas = {}
        for t in self.alm.territorios():
            cuentas[t["banda"]] = cuentas.get(t["banda"], 0) + renta
        for banda, total in cuentas.items():
            self.alm.apunte(banda, es("Barrios"), total, es("renta de los barrios"))
            self._a_banda(banda, {"t": "aviso", "texto": es("Los barrios de tu banda dejan %d euros en la caja.") % total, "son": "dinero"})
            self._banda_difundir(banda)
        self._a_todos({"t": "hora", "h": self._hora(), "medianoche": True})
        self._propiedades_abandonadas()
        for j in self.jugadores.values():                     # lo que les robaron ayer a sus negocios se descuenta ahora
            if j.dentro:
                total = self.alm.cobrar_robos(j.cuenta)
                if total:
                    self._enviar(j, {"t": "robos_dia", "total": total})

    # ================================================================ vehículos
    def _veh_publico(self, v):
        return {k: v.get(k) for k in ("id", "modelo", "nombre", "m", "x", "y", "r", "salud", "por", "mejoras")}

    def _m_veh_tomar(self, j, m):
        """El jugador se sube a un vehículo de su mundo: desde ahora es de todos, y cualquiera puede quitárselo."""
        modelo = m.get("modelo")
        if modelo not in self.mundo["modelos"] or j.mapa is None:
            return
        if j.vid is not None and j.vid in self.vehiculos:
            self._soltar_vehiculo(j, self.vehiculos[j.vid])
        self._nv += 1
        try:
            salud = max(1.0, min(2000.0, finito(m.get("salud", self.mundo["modelos"][modelo]["salud"]))))
        except (TypeError, ValueError):
            salud = float(self.mundo["modelos"][modelo]["salud"])
        mejoras = m.get("mejoras") if isinstance(m.get("mejoras"), dict) and len(json.dumps(m.get("mejoras"))) < 300 else {}
        v = {"id": self._nv, "modelo": modelo, "nombre": limpiar_nombre(m.get("nombre"), 40) or self.mundo["modelos"][modelo]["nombre"],
             "m": j.mapa, "x": j.x, "y": j.y, "r": j.rumbo, "salud": salud, "por": j.id, "dueno": j.cuenta, "t": self.ahora(), "mejoras": mejoras}
        self.vehiculos[v["id"]] = v
        j.vid = v["id"]
        j.t_vid = time.monotonic()
        self._enviar(j, {"t": "veh_tuyo", "id": v["id"], "ref": m.get("ref")})
        self._a_todos({"t": "veh_ocupado", "id": v["id"], "por": j.id, "v": self._veh_publico(v)}, menos=j)

    def _soltar_vehiculo(self, j, v, datos=None):
        datos = datos or {}
        try:
            v.update(m=j.mapa, x=finito(datos.get("x", j.x)), y=finito(datos.get("y", j.y)), r=finito(datos.get("r", j.rumbo)),
                     salud=max(0.0, min(2000.0, finito(datos.get("salud", v["salud"])))))
        except (TypeError, ValueError):
            pass
        if datos.get("nombre") and v.get("dueno") == j.cuenta:   # le ha puesto nombre: un juego anterior manda el de siempre
            v["nombre"] = limpiar_nombre(datos.get("nombre"), 40) or v["nombre"]
        v["por"] = None
        v["t"] = self.ahora()
        j.vid = None
        self._a_todos({"t": "veh_libre", "v": self._veh_publico(v)}, menos=j)
        mios = sorted((o for o in self.vehiculos.values() if o.get("dueno") == j.cuenta and o["por"] is None), key=lambda o: o.get("t", 0))
        for viejo in mios[:-int(self.cfg["vehiculos_por_jugador"])]:
            self._quitar_vehiculo(viejo["id"])

    def _m_veh_dejar(self, j, m):
        v = self.vehiculos.get(m.get("id"))
        if v is not None and v["por"] == j.id:
            self._soltar_vehiculo(j, v, m)

    def _m_veh_subir(self, j, m):
        """Subirse a un vehículo aparcado de otro jugador: el primero que lo pide se lo lleva."""
        v = self.vehiculos.get(m.get("id"))
        if v is None:
            return self._enviar(j, {"t": "veh_no", "id": m.get("id"), "motivo": es("Ese vehículo ya no está."), "por": "no_esta"})
        if v["por"] is not None and v["por"] != j.id:
            return self._enviar(j, {"t": "veh_no", "id": v["id"], "motivo": es("Alguien se te ha adelantado."), "por": "ocupado"})
        if v["m"] != j.mapa or math.hypot(v["x"] - j.x, v["y"] - j.y) > 14:
            return self._enviar(j, {"t": "veh_no", "id": v["id"], "motivo": es("Estás demasiado lejos."), "por": "lejos"})
        if j.vid is not None and j.vid in self.vehiculos and j.vid != v["id"]:
            self._soltar_vehiculo(j, self.vehiculos[j.vid])
        robo = v.get("dueno") not in (None, j.cuenta)
        antes = v.get("dueno")
        if robo and not any(o.dentro and o.cuenta == antes for o in self.jugadores.values()):
            self.alm.dejar_pendiente(antes, {"que": "coche", "nombre": v["nombre"], "por": j.nombre})      # se lo dirá al volver
        v.update(por=j.id, dueno=j.cuenta, t=self.ahora())
        j.vid = v["id"]
        j.t_vid = time.monotonic()
        self._enviar(j, {"t": "veh_ok", "id": v["id"], "v": self._veh_publico(v), "robado": robo})
        if robo:                                               # al dueño se le dice antes de que el coche desaparezca de su calle
            for o in self.jugadores.values():
                if o.dentro and o.cuenta == antes:
                    self._aviso(o, es("%s se ha llevado tu %s.") % (j.nombre, v["nombre"]), "alarma")
        self._a_todos({"t": "veh_ocupado", "id": v["id"], "por": j.id, "v": self._veh_publico(v)}, menos=j)

    def _m_veh_asaltar(self, j, m):
        """Sacar a otro jugador de su vehículo y quedárselo: tiene que ir despacio y tenerlo al lado."""
        v = self.vehiculos.get(m.get("id"))
        o = self.jugadores.get(v["por"]) if v is not None else None
        if v is None or o is None or o is j:
            return self._enviar(j, {"t": "veh_no", "id": m.get("id"), "motivo": es("Ese vehículo ya no está."), "por": "no_esta"})
        if o.mapa != j.mapa or j.dist(o) > 9:
            return self._enviar(j, {"t": "veh_no", "id": v["id"], "motivo": es("Estás demasiado lejos."), "por": "lejos"})
        if o.vel > 6:
            return self._enviar(j, {"t": "veh_no", "id": v["id"], "motivo": es("Va demasiado rápido para abrir la puerta.")})
        if not self._puede_atacar(j, o, avisar=True):
            return self._enviar(j, {"t": "veh_no", "id": v["id"], "motivo": ""})
        self._marcar_agresion(j, o)
        self._enviar(o, {"t": "sacado", "por": j.id, "nombre": j.nombre, "id": v["id"]})
        o.vid = None
        v.update(por=j.id, dueno=j.cuenta, t=self.ahora(), m=j.mapa)
        j.vid = v["id"]
        j.t_vid = time.monotonic()
        self._enviar(j, {"t": "veh_ok", "id": v["id"], "v": self._veh_publico(v), "robado": True, "asalto": o.nombre})
        self._a_todos({"t": "veh_ocupado", "id": v["id"], "por": j.id, "v": self._veh_publico(v)}, menos=j)

    def _m_veh_dano(self, j, m):
        v = self.vehiculos.get(m.get("id"))
        if v is None or v["m"] != j.mapa:
            return
        try:
            n = max(0.0, min(500.0, float(m.get("n", 0))))
        except (TypeError, ValueError):
            return
        if v["por"] is not None and v["por"] != j.id:           # va alguien dentro: el daño se lo aplica su juego
            o = self.jugadores.get(v["por"])
            if o is not None and self._puede_atacar(j, o, avisar=True):
                self._marcar_agresion(j, o)
                self._enviar(o, {"t": "veh_golpe", "id": v["id"], "n": n, "de": j.id, "nombre": j.nombre})
            return
        v["salud"] = max(0.0, v["salud"] - n)
        if v["salud"] <= 0:
            self._a_todos({"t": "veh_revienta", "id": v["id"], "x": v["x"], "y": v["y"], "m": v["m"]})
            self._quitar_vehiculo(v["id"], avisar=False)
        else:
            self._a_todos({"t": "veh_salud", "id": v["id"], "salud": v["salud"]}, mapa=v["m"])

    def _m_veh_fin(self, j, m):
        """El vehículo deja de existir: lo ha metido en su garaje, lo ha vendido o ha reventado."""
        v = self.vehiculos.get(m.get("id"))
        if v is not None and (v["por"] == j.id or (v["por"] is None and v.get("dueno") == j.cuenta)):
            if j.vid == v["id"]:
                j.vid = None
            self._quitar_vehiculo(v["id"])

    # Lo que se puede hacer desde lejos con un vehículo propio que está aparcado: ponerle nombre, que te lo traigan y
    # mandarlo a un garaje. El garaje lo lleva el juego de cada uno; el servidor solo dice que sí y lo quita de la calle.
    def _veh_mio(self, j, m):
        v = self.vehiculos.get(m.get("id")) if isinstance(m.get("id"), int) else None
        if v is None or v["por"] is not None or v.get("dueno") != j.cuenta:
            self._enviar(j, {"t": "veh_mio", "que": "no", "id": m.get("id"), "motivo": es("Ese vehículo ya no está aparcado a tu nombre: se lo han llevado, lo han reventado o ha caducado.")})
            return None
        return v

    def _m_veh_nombre(self, j, m):
        v = self._veh_mio(j, m)
        if v is None:
            return
        v["nombre"] = limpiar_nombre(m.get("nombre"), 40) or (self.mundo["modelos"].get(v["modelo"]) or {}).get("nombre") or v["nombre"]
        self._a_todos({"t": "veh_libre", "v": self._veh_publico(v)}, menos=j)
        self._enviar(j, {"t": "veh_mio", "que": "nombre", "id": v["id"], "v": self._veh_publico(v)})

    def _m_veh_traer(self, j, m):
        if j.mapa is None:
            return self._enviar(j, {"t": "veh_mio", "que": "no", "id": m.get("id"), "motivo": es("Aquí no te lo pueden traer.")})
        v = self._veh_mio(j, m)
        if v is None:
            return
        try:
            x, y, r = finito(m.get("x", j.x)), finito(m.get("y", j.y)), finito(m.get("r", 0))
        except (TypeError, ValueError):
            x, y, r = j.x, j.y, 0.0
        if math.hypot(x - j.x, y - j.y) > 60:                  # se lo dejan a su lado, no donde él diga
            x, y = j.x, j.y
        self._a_todos({"t": "veh_fuera", "id": v["id"]}, menos=j)      # de donde estaba, desaparece
        v.update(m=j.mapa, x=x, y=y, r=r, t=self.ahora())
        self._a_todos({"t": "veh_libre", "v": self._veh_publico(v)}, menos=j)
        self._enviar(j, {"t": "veh_mio", "que": "traer", "id": v["id"], "v": self._veh_publico(v)})

    def _m_veh_guardar(self, j, m):
        v = self._veh_mio(j, m)
        if v is None:
            return
        self._enviar(j, {"t": "veh_mio", "que": "garaje", "id": v["id"], "v": self._veh_publico(v), "ref": str(m.get("ref", ""))[:60]})
        self._quitar_vehiculo(v["id"])

    def _quitar_vehiculo(self, ident, avisar=True):
        v = self.vehiculos.pop(ident, None)
        if v is not None:
            o = self.jugadores.get(v.get("por"))
            if o is not None and o.vid == ident:
                o.vid = None
            if avisar:
                self._a_todos({"t": "veh_fuera", "id": ident})

    # ============================================================== propiedades
    def _props(self):
        return {f["lugar"]: {"cuenta": f["cuenta"], "nombre": f["nombre"], "oferta": int(f["oferta"] or 0)} for f in self.alm.propiedades()}

    def _prop_difundir(self, lugar, antes=None):
        f = self.alm.propiedad(lugar)
        self._a_todos({"t": "prop", "lugar": lugar, "cuenta": f["cuenta"] if f else None, "nombre": f["nombre"] if f else "",
                       "oferta": int(f["oferta"] or 0) if f else 0, "antes": antes})

    def _m_prop_soltar(self, j, m):
        """Vender tu casa o tu negocio al mercado: recuperas una parte y vuelve a estar en venta para cualquiera."""
        l = self.lugares.get(m.get("lugar"))
        f = self.alm.propiedad(l["id"]) if l is not None else None
        if f is None or f["cuenta"] != j.cuenta:
            return self._aviso(j, es("Eso no es tuyo."))
        self._ver_pagos(j)
        f = self.alm.propiedad(l["id"])
        # Solo da dinero lo que el servidor vio pagar. Lo que se trajo de fuera, o se apuntó sin que saliera el dinero, se
        # puede tener y usar, pero al venderlo no devuelve nada: si no, bastaría apuntarse casas y venderlas para hacerse rico.
        pagada = bool(f["pagada"]) or not si(self.cfg["economia"])
        n = int(l["precio"]) * int(self.cfg["venta_mercado"]) // 100 if pagada else 0
        self.alm.quitar_propiedad(l["id"])
        j.prop_pend.pop(l["id"], None)
        self._prop_difundir(l["id"], antes=j.cuenta)
        if n:
            j.dinero += n
            self._enviar(j, {"t": "dinero", "nombre": es("La venta de %s") % l["nombre"], "n": n})
        else:
            self._aviso(j, es("%s vuelve al mercado, pero no te da dinero: a este servidor no le consta que la pagaras aquí.") % l["nombre"])
        self._a_todos({"t": "aviso", "texto": es("%s vuelve a estar en venta, en %s.") % (l["nombre"], self.mundo["mapas"][l["mapa"]]["nombre"])}, menos=j)

    def _m_prop_oferta(self, j, m):
        """Poner tu propiedad en venta para otros jugadores, al precio que tú digas. Con cero, se retira."""
        l = self.lugares.get(m.get("lugar"))
        f = self.alm.propiedad(l["id"]) if l is not None else None
        if f is None or f["cuenta"] != j.cuenta:
            return self._aviso(j, es("Eso no es tuyo."))
        try:
            precio = max(0, min(10 ** 8, int(m.get("precio", 0))))
        except (TypeError, ValueError):
            return
        self._ver_pagos(j)
        if precio and si(self.cfg["economia"]) and not self.alm.propiedad(l["id"])["pagada"]:
            return self._aviso(j, es("No puedes vender %s a otro jugador: a este servidor no le consta que la pagaras aquí.") % l["nombre"], "error")
        self.alm.poner_oferta(l["id"], precio)
        self._prop_difundir(l["id"])
        if precio:
            self._a_todos({"t": "aviso", "texto": es("%s vende %s por %d euros.") % (j.nombre, l["nombre"], precio)}, menos=j)

    def _m_prop_adquirir(self, j, m):
        """Comprarle a otro jugador la propiedad que tiene en venta."""
        l = self.lugares.get(m.get("lugar"))
        f = self.alm.propiedad(l["id"]) if l is not None else None
        if f is None or f["cuenta"] == j.cuenta or not f["oferta"]:
            return self._aviso(j, es("Eso no está en venta."))
        precio = int(f["oferta"])
        if not self._cobrar(j, precio, es("comprar %s") % l["nombre"]):
            return
        vendedor = f["cuenta"]
        self.alm.poner_propiedad(l["id"], j.cuenta, pagada=True)
        en_linea = next((o for o in self.jugadores.values() if o.dentro and o.cuenta == vendedor), None)
        if en_linea is not None:
            en_linea.dinero += precio
            self._enviar(en_linea, {"t": "dinero", "nombre": es("%s, por %s") % (j.nombre, l["nombre"]), "n": precio})
        else:
            self.alm.dejar_pendiente(vendedor, {"que": "venta", "lugar": l["id"], "n": precio, "por": j.nombre})
        self._prop_difundir(l["id"], antes=vendedor)

    def _propiedades_abandonadas(self):
        """Lo de quien lleva mucho sin entrar vuelve al mercado, y a él se le guarda su parte para cuando vuelva."""
        tope = self.ahora() - 86400.0 * int(self.cfg["propiedad_dias"])
        en_linea = {o.cuenta for o in self.jugadores.values() if o.dentro}
        for f in self.alm.propiedades_abandonadas(tope):
            l = self.lugares.get(f["lugar"])
            if l is None or f["cuenta"] in en_linea:
                continue
            self.alm.quitar_propiedad(f["lugar"])
            self.alm.dejar_pendiente(f["cuenta"], {"que": "caducada", "lugar": f["lugar"],
                                                   "n": int(l["precio"]) * int(self.cfg["venta_mercado"]) // 100 if f["pagada"] or not si(self.cfg["economia"]) else 0})
            self._prop_difundir(f["lugar"], antes=f["cuenta"])

    def _m_prop_comprar(self, j, m):
        """Una casa o un negocio solo puede ser de un jugador. El primero que lo compra se lo queda."""
        l = self.lugares.get(m.get("lugar"))
        if l is None:
            return
        f = self.alm.propiedad(l["id"])
        if f is not None and f["cuenta"] != j.cuenta:
            self._devolucion(j, int(l.get("precio", 0)))       # su juego le devuelve lo pagado: es dinero que ya era suyo
            return self._enviar(j, {"t": "prop_no", "lugar": l["id"], "nombre": f["nombre"]})
        if f is None:
            self.alm.poner_propiedad(l["id"], j.cuenta, pagada=not si(self.cfg["economia"]) or j.bot)
            if si(self.cfg["economia"]) and not j.bot and int(l.get("precio", 0) or 0) > 0:
                j.prop_pend[l["id"]] = [time.monotonic(), int(l["precio"])]     # el juego la paga por su cuenta: hay que verlo
                self._ver_pagos(j)
            self._prop_difundir(l["id"])
            self._a_todos({"t": "aviso", "texto": es("%s compra %s, en %s.") % (j.nombre, l["nombre"], self.mundo["mapas"][l["mapa"]]["nombre"])}, menos=j)

    def _banda_de(self, cuenta):
        mi = self.alm.miembro(cuenta)
        return mi["banda"] if mi is not None else None

    def _m_robo(self, j, m):
        """Atracar el negocio de otro jugador: hay que aguantar dentro veinte segundos, y al dueño le salta el aviso."""
        l = self.lugares.get(m.get("lugar"))
        f = self.alm.propiedad(l["id"]) if l is not None and l["tipo"] == "negocio" else None
        if f is None or f["cuenta"] == j.cuenta:
            return self._aviso(j, es("Este negocio no es de otro jugador."))
        if not si(self.cfg["pvp"]):
            return self._aviso(j, es("En este servidor no se roba a otros jugadores."))
        if j.pasivo:
            return self._aviso(j, es("En modo pasivo no puedes atracar a nadie."))
        if j.mapa != l["mapa"] or math.hypot(j.x - l["x"], j.y - l["y"]) > 30 or j.veh:
            return self._aviso(j, es("Tienes que estar en la puerta, a pie."))
        if j.arma == "punos":
            return self._aviso(j, es("Con las manos vacías no impones. Saca un arma."))
        banda = self._banda_de(f["cuenta"])
        if banda is not None and j.banda is not None and (banda == j.banda or banda in self.alm.aliadas(j.banda)):
            return self._aviso(j, es("Ese negocio es de alguien de tu banda o de una banda aliada."))
        if f["robado_dia"] == self.dia:
            return self._aviso(j, es("A este negocio ya le han vaciado la caja hoy. Vuelve otro día."))
        if j.id in self.robos or any(r["lugar"] == l["id"] for r in self.robos.values()):
            return self._aviso(j, es("Ya hay un atraco en marcha."))
        segundos = int(self.cfg["robo_segundos"])
        self.robos[j.id] = {"lugar": l["id"], "fin": time.monotonic() + segundos, "dueno": f["cuenta"], "nombre_dueno": f["nombre"]}
        self._enviar(j, {"t": "robo_empieza", "lugar": l["id"], "segundos": segundos, "nombre": f["nombre"]})
        for o in self.jugadores.values():                     # salta la alarma: al dueño y a su banda
            if o.dentro and o is not j and (o.cuenta == f["cuenta"] or (banda is not None and o.banda == banda)):
                self._enviar(o, {"t": "robo_aviso", "lugar": l["id"], "de": j.id, "nombre": j.nombre, "segundos": segundos, "tuyo": o.cuenta == f["cuenta"]})

    def _robo_fin(self, j, ok, motivo=""):
        r = self.robos.pop(j.id, None)
        if r is None:
            return
        l = self.lugares[r["lugar"]]
        botin = 0
        if ok:
            botin = int(l.get("ingresos", 0))
            self.alm.robo_en(l["id"], self.dia, botin)
            j.dinero += botin
        if j.dentro:
            self._enviar(j, {"t": "robo_fin", "ok": bool(ok), "botin": botin, "motivo": motivo, "lugar": l["id"]})
        for o in self.jugadores.values():
            if o.dentro and o.cuenta == r["dueno"]:
                self._aviso(o, (es("%s ha vaciado la caja de %s: %d euros. Se te descuentan a medianoche.") % (j.nombre, l["nombre"], botin)) if ok
                            else (es("%s no ha conseguido atracar %s.") % (j.nombre, l["nombre"])), "alarma" if ok else "llegada")

    def _robos_paso(self):
        ahora = time.monotonic()
        for ident, r in list(self.robos.items()):
            j = self.jugadores.get(ident)
            l = self.lugares[r["lugar"]]
            if j is None or not j.dentro:
                self.robos.pop(ident, None)
                continue
            if j.salud <= 0:
                self._robo_fin(j, False, es("Te han tumbado antes de vaciar la caja."))
            elif j.mapa != l["mapa"] or math.hypot(j.x - l["x"], j.y - l["y"]) > 35 or j.veh:
                self._robo_fin(j, False, es("Te has ido antes de vaciar la caja."))
            elif ahora >= r["fin"]:
                self._robo_fin(j, True)

    # ================================================================== combate
    def _relacion(self, a, b):
        """amigos: misma banda sin fuego amigo, bandas aliadas o el mismo grupo de misión."""
        if a.grupo is not None and a.grupo == b.grupo:
            return "grupo"
        if a.banda is not None and b.banda is not None:
            if a.banda == b.banda:
                f = self.alm.banda(a.banda)
                return None if (f is not None and f["fuego"]) else "banda"
            if b.banda in self.alm.aliadas(a.banda):
                return "aliados"
        return None

    def _puede_atacar(self, a, o, avisar=False):
        ahora = time.monotonic()
        motivo = None
        if not si(self.cfg["pvp"]):
            motivo = es("En este servidor no hay combate entre jugadores.")
        elif a.mapa != o.mapa:
            motivo = es("Ya no está aquí.")
        elif a.pasivo:
            motivo = es("Estás en modo pasivo: no puedes herir a nadie.")
        elif o.pasivo:
            motivo = es("%s está en modo pasivo: no se le puede herir.") % o.nombre
        elif ahora < a.protegido:
            motivo = es("Acabas de llegar: todavía no puedes atacar a nadie.")
        elif ahora < o.protegido:
            motivo = es("%s acaba de llegar y está protegido unos segundos.") % o.nombre
        elif self.segura(a) or self.segura(o):
            motivo = es("Zona segura: aquí nadie puede herir a nadie.")
        else:
            rel = self._relacion(a, o)
            if rel == "banda":
                motivo = es("%s es de tu banda, y el fuego amigo está quitado.") % o.nombre
            elif rel == "aliados":
                motivo = es("%s es de una banda aliada.") % o.nombre
            elif rel == "grupo":
                motivo = es("%s va contigo en la misión.") % o.nombre
        if motivo and avisar and ahora - getattr(a, "_t_motivo", 0) > 3:
            a._t_motivo = ahora
            self._enviar(a, {"t": "fallo", "a": o.id, "motivo": motivo})
        return motivo is None

    def _marcar_agresion(self, a, o):
        ahora = time.monotonic()
        if ahora - a.golpeado.get(o.id, -999) > 60:             # él no me había tocado: el que empieza soy yo
            a.agredio[o.id] = ahora
        o.golpeado[a.id] = ahora

    def _m_ataque(self, j, m):
        """Un disparo o un golpe contra otro jugador. El servidor decide si llega y cuánto quita."""
        o = self.jugadores.get(m.get("a"))
        if o is None or o is j or (not o.dentro and not o.fantasma):
            return
        # El arma con la que cuenta el servidor: la que dice el mensaje si su mundo la tiene; si no, la que lleva (que, si
        # tampoco la conoce, son las manos). De ahí salen el daño, el alcance y la cadencia, iguales para todos, sea cual
        # sea la versión de quien dispara y de quien recibe. A los demás se les nombra esa, no la que diga el mensaje.
        cual = m.get("arma") if m.get("arma") in self.mundo["armas"] else j.arma
        arma = self.mundo["armas"].get(cual)
        if arma is None:
            return
        ahora = time.monotonic()
        if ahora - j.t_ataque < float(arma["cadencia"]) * 0.75:
            return                                             # más rápido de lo que dispara esa arma
        if not self._puede_atacar(j, o, avisar=True):
            return
        j.t_ataque = ahora
        d = j.dist(o)
        alcance = float(arma["alcance"])
        self._a_todos({"t": "tiro", "de": j.id, "arma": cual, "x": round(j.x, 1), "y": round(j.y, 1)}, menos=j, mapa=j.mapa)
        self._marcar_agresion(j, o)
        if d > alcance * 1.15 + 3.0:
            return self._enviar(j, {"t": "fallo", "a": o.id, "motivo": "", "lejos": True})
        prob = float(arma["precision"]) * (1.0 - 0.45 * min(1.0, d / max(1.0, alcance)))
        dentro = o.veh or self._va_con(o) is not None         # al volante o de pasajero: la chapa cubre igual
        if o.agachado:
            prob *= 0.8
        if dentro:
            prob *= 0.75
        if arma["tipo"] == "cuerpo":
            prob = max(prob, 0.85)
        if self.rng.random() > prob:
            self._enviar(j, {"t": "fallo", "a": o.id, "motivo": ""})
            self._enviar(o, {"t": "silbido", "de": j.id, "nombre": j.nombre, "x": round(j.x, 1), "y": round(j.y, 1)})
            return
        dano = float(arma["dano"]) * (1.0 - 0.4 * min(1.0, d / max(1.0, alcance))) * self.rng.uniform(0.85, 1.15)
        if dentro:
            dano *= 0.5                                        # la chapa para parte
        dano = round(max(1.0, dano), 1)
        o.salud = max(0.0, o.salud - dano)
        self._enviar(j, {"t": "impacto", "a": o.id, "nombre": o.nombre, "dano": dano})
        if o.bot:
            return self.bot_golpeado(o, j)
        if o.dentro:
            self._enviar(o, {"t": "herido", "de": j.id, "nombre": j.nombre, "arma": cual, "dano": dano, "x": round(j.x, 1), "y": round(j.y, 1)})
        elif o.salud <= 0:                                     # se fue en pleno combate y ha caído igual
            self._caida(o, j, ausente=True)

    def _m_atropello(self, j, m):
        o = self.jugadores.get(m.get("a"))
        if o is None or o is j or not o.dentro or j.veh is None or o.veh is not None:
            return
        if self._va_con(o) is not None:                        # va de pasajero, en este vehículo o en otro: no está en la calzada
            return
        if o.mapa != j.mapa or j.dist(o) > 7 or not self._puede_atacar(j, o, avisar=True):
            return
        ahora = time.monotonic()
        if ahora - j.t_ataque < 1.0:
            return
        j.t_ataque = ahora
        self._marcar_agresion(j, o)
        dano = round(min(95.0, max(5.0, j.vel * 5.0)), 1)
        o.salud = max(0.0, o.salud - dano)
        self._enviar(j, {"t": "impacto", "a": o.id, "nombre": o.nombre, "dano": dano, "atropello": True})
        if o.bot:
            return self.bot_golpeado(o, j)
        self._enviar(o, {"t": "herido", "de": j.id, "nombre": j.nombre, "arma": "atropello", "dano": dano, "x": round(j.x, 1), "y": round(j.y, 1)})

    def _m_atraco(self, j, m):
        """Atracar a otro jugador, como a cualquiera de la calle: con un arma en la mano y a su lado."""
        o = self.jugadores.get(m.get("a"))
        if o is None or o is j or not o.dentro:
            return
        if o.mapa != j.mapa or j.dist(o) > 6 or j.veh or o.veh or self._va_con(o) is not None or self._va_con(j) is not None:
            return self._aviso(j, es("Para atracar a alguien tenéis que estar los dos a pie y a un paso."))
        if j.arma == "punos":
            return self._aviso(j, es("Con las manos vacías no impones. Saca un arma."))
        if not self._puede_atacar(j, o, avisar=True):
            return
        ahora = time.monotonic()
        if ahora - j.atracos.get(o.cuenta, -9999) < 300:
            return self._aviso(j, es("A %s ya le has atracado hace un momento. No lleva más encima.") % o.nombre)
        j.atracos[o.cuenta] = ahora
        botin = min(int(self.cfg["atraco_max"]), o.dinero * int(self.cfg["atraco"]) // 100)
        self._marcar_agresion(j, o)
        o.dinero = max(0, o.dinero - botin)
        j.dinero += botin
        self._enviar(o, {"t": "atracado", "de": j.id, "nombre": j.nombre, "pierde": botin})
        self._enviar(j, {"t": "atraco_ok", "a": o.id, "nombre": o.nombre, "botin": botin})
        if o.bot:
            self.bot_golpeado(o, j)

    def _m_po_golpe(self, j, m):
        """Le ha dado a un policía de los que persiguen a otro jugador: el golpe llega al juego de ese jugador."""
        o = self.jugadores.get(m.get("a"))
        if o is None or not o.dentro or o.mapa != j.mapa or o.bot:
            return
        try:
            dano = max(0.0, min(500.0, float(m.get("dano", 0))))
        except (TypeError, ValueError):
            return
        self._enviar(o, {"t": "po_golpe", "k": m.get("k"), "dano": dano, "de": j.id, "nombre": j.nombre})

    def _m_explosion(self, j, m):
        """Una granada, un cóctel o un cohete de un jugador: alcanza a los demás jugadores que estén dentro del radio."""
        arma = self.mundo["armas"].get(m.get("arma"))
        if arma is None or arma.get("tipo") != "explosivo":
            return
        ahora = time.monotonic()
        if ahora - j.t_ataque < float(arma["cadencia"]) * 0.75:
            return
        j.t_ataque = ahora
        try:
            x, y = finito(m.get("x")), finito(m.get("y"))
        except (TypeError, ValueError):
            return
        if math.hypot(x - j.x, y - j.y) > float(arma["alcance"]) * 1.3 + 6:
            return                                             # más lejos de lo que se puede lanzar
        radio = float(arma.get("radio") or 8.0)
        self._a_todos({"t": "estalla", "de": j.id, "x": round(x, 1), "y": round(y, 1)}, menos=j, mapa=j.mapa)
        self.peatones_susto(j.mapa, x, y, 60, 14.0)
        self.patrulla_ve(j)
        for o in list(self.jugadores.values()):
            if o is j or not o.dentro or o.mapa != j.mapa:
                continue
            d = math.hypot(o.x - x, o.y - y)
            if d > radio or not self._puede_atacar(j, o):
                continue
            self._marcar_agresion(j, o)
            dano = round(max(1.0, float(arma["dano"]) * (1.0 - 0.6 * d / radio) * (0.5 if (o.veh or self._va_con(o) is not None) else 1.0)), 1)
            o.salud = max(0.0, o.salud - dano)
            self._enviar(j, {"t": "impacto", "a": o.id, "nombre": o.nombre, "dano": dano})
            if o.bot:
                self.bot_golpeado(o, j)
                continue
            self._enviar(o, {"t": "herido", "de": j.id, "nombre": j.nombre, "arma": m.get("arma"), "dano": dano, "x": round(x, 1), "y": round(y, 1)})

    def _m_caido(self, j, m):
        """El juego de quien cae avisa de que ha caído ante otro jugador."""
        o = self.jugadores.get(m.get("por"))
        if o is None or time.monotonic() - j.golpeado.get(o.id, -999) > 20:
            j.golpeado.clear()
            return
        self._caida(j, o)

    def _caida(self, caido, por, ausente=False):
        ahora = time.monotonic()
        botin = min(int(self.cfg["botin_max"]), caido.dinero * int(self.cfg["botin"]) // 100)
        self.alm.sumar(por.cuenta, "bajas", 1)
        self.alm.sumar(caido.cuenta, "caidas", 1)
        recompensa = self._recompensa(caido)
        inocente = ahora - caido.agredio.get(por.id, -999) > 90 and ahora - por.agredio.get(caido.id, -999) <= 90 and recompensa == 0
        texto_extra = ""
        if recompensa > 0:
            self.alm.sumar(caido.cuenta, "recompensa", -recompensa)
            texto_extra = es(" Cobras además los %d euros que ofrecían por su cabeza.") % recompensa
        if inocente:
            sube = int(self.cfg["recompensa"])
            self.alm.sumar(por.cuenta, "recompensa", sube)
            self._enviar(por, {"t": "buscado", "recompensa": self._recompensa(por), "sube": sube})
        por.dinero += botin
        if por.dentro:
            self._enviar(por, {"t": "baja", "a": caido.id, "nombre": caido.nombre, "botin": botin + recompensa, "texto": texto_extra})
        if ausente or not caido.dentro:
            self.alm.dejar_pendiente(caido.cuenta, {"que": "caido", "por": por.nombre, "pierde": botin})
            caido.fantasma = ahora                             # desaparece ya
        else:
            self._enviar(caido, {"t": "caes", "por": por.id, "nombre": por.nombre, "pierde": botin})
            caido.protegido = ahora + float(self.cfg["proteccion"])
            caido.dinero = max(0, caido.dinero - botin)
        caido.golpeado.clear()
        caido.agredio.clear()
        if caido.id in self.robos:
            self._robo_fin(caido, False, es("Te han tumbado antes de vaciar la caja."))
        self._guerra_baja(por, caido)
        self._a_todos({"t": "muerte", "quien": caido.nombre, "por": por.nombre}, menos=por if por.dentro else None)
        self.alm.guardar()

    def _m_pasivo(self, j, m):
        if not si(self.cfg["modo_pasivo"]):
            return self._aviso(j, es("En este servidor no hay modo pasivo."))
        ahora = time.monotonic()
        quiere = bool(m.get("si"))
        if quiere == j.pasivo:
            return
        if any(ahora - t < 60 for t in j.agredio.values()) or any(ahora - t < 30 for t in j.golpeado.values()):
            return self._aviso(j, es("No puedes cambiar de modo en mitad de una pelea. Espera un minuto."))
        if ahora - j.t_pasivo < 120 and j.t_pasivo:
            return self._aviso(j, es("Acabas de cambiar de modo. Espera dos minutos."))
        j.pasivo, j.t_pasivo = quiere, ahora
        self._enviar(j, {"t": "pasivo", "si": quiere})

    # =================================================================== bandas
    def _banda_datos(self, banda):
        if banda is None:
            return None
        f = self.alm.banda(banda)
        if f is None:
            return None
        en_linea = {o.cuenta for o in self.jugadores.values() if o.dentro}
        return {"id": f["id"], "nombre": f["nombre"], "caja": int(f["caja"]), "fuego": bool(f["fuego"]),
                "miembros": [{"cuenta": m["cuenta"], "nombre": m["nombre"], "rango": m["rango"], "en_linea": m["cuenta"] in en_linea} for m in self.alm.miembros(banda)],
                "aliadas": [self.alm.banda(a)["nombre"] for a in self.alm.aliadas(banda) if self.alm.banda(a) is not None],
                "apuntes": [{"nombre": a["nombre"], "cantidad": a["cantidad"], "motivo": a["motivo"]} for a in self.alm.apuntes(banda)],
                "barrios": [{"mapa": t["mapa"], "barrio": t["barrio"]} for t in self.alm.territorios() if t["banda"] == banda]}

    def _banda_difundir(self, banda):
        d = self._banda_datos(banda)
        for o in self.jugadores.values():
            if o.dentro and o.banda == banda:
                self._enviar(o, {"t": "banda", "b": d, "rango": o.rango})

    def _territorios(self):
        nombres = {b["id"]: b["nombre"] for b in self.alm.bandas()}
        return {"barrios": [{"mapa": t["mapa"], "barrio": t["barrio"], "banda": t["banda"], "nombre": nombres.get(t["banda"], "?")} for t in self.alm.territorios()],
                "guerras": [dict(g, ataca_n=nombres.get(g["ataca"], "?"), defiende_n=nombres.get(g["defiende"], "?"),
                                 falta=int(max(0, g["inicio"] - self.ahora())), queda=int(max(0, g["fin"] - self.ahora()))) for g in self.guerras]}

    def _difundir_territorios(self):
        self._a_todos({"t": "territorios", "e": self._territorios()})

    def _cobrar(self, j, n, motivo):
        """Lo que cuesta algo del servidor sale del bolsillo del jugador: su juego lo descuenta."""
        if j.dinero < n:
            self._aviso(j, es("No te llega: hacen falta %d euros y llevas %d.") % (n, j.dinero), "error")
            return False
        j.dinero -= n
        if j.saldo is not None:
            j.saldo = max(0, j.saldo - n)
            if si(self.cfg["economia"]) and not j.bot:        # su juego lo restará cuando le llegue el aviso
                j.cobros.append(n)
                j.t_cobros = time.monotonic()
        self._enviar(j, {"t": "cobro", "n": n, "motivo": motivo})
        return True

    def _m_banda_crear(self, j, m):
        nombre = limpiar_nombre(m.get("nombre"), 30)
        if j.banda is not None:
            return self._aviso(j, es("Ya estás en una banda. Sal de ella antes de fundar otra."))
        if len(nombre) < 3:
            return self._aviso(j, es("El nombre de la banda tiene que tener al menos tres letras."))
        if self.alm.banda_por_nombre(nombre) is not None:
            return self._aviso(j, es("Ya hay una banda con ese nombre."))
        if not self._cobrar(j, int(self.cfg["precio_banda"]), es("fundar la banda")):
            return
        j.banda, j.rango = self.alm.crear_banda(nombre, j.cuenta), "jefe"
        self._banda_difundir(j.banda)
        self._a_todos({"t": "aviso", "texto": es("%s ha fundado la banda %s.") % (j.nombre, nombre), "son": "territorio"}, menos=j)
        self._a_todos({"t": "de_banda", "id": j.id, "banda": j.banda})

    def _m_banda_invitar(self, j, m):
        o = self.jugadores.get(m.get("a"))
        if j.banda is None or j.rango not in ("jefe", "mano"):
            return self._aviso(j, es("Solo el jefe y su mano derecha pueden invitar."))
        if o is None or not o.dentro or o.banda is not None:
            return self._aviso(j, es("Esa persona no está, o ya tiene banda."))
        f = self.alm.banda(j.banda)
        self.invitaciones_banda[o.id] = {"banda": j.banda, "de": j.nombre, "hasta": time.monotonic() + 180}
        self._enviar(o, {"t": "banda_invita", "banda": j.banda, "nombre": f["nombre"], "de": j.nombre})
        self._aviso(j, es("Invitación enviada a %s.") % o.nombre)

    def _m_banda_resp(self, j, m):
        inv = self.invitaciones_banda.pop(j.id, None)
        if inv is None or j.banda is not None or self.alm.banda(inv["banda"]) is None:
            return self._aviso(j, es("Esa invitación ya no vale."))
        if not m.get("si"):
            return
        self.alm.meter_miembro(j.cuenta, inv["banda"])
        j.banda, j.rango = inv["banda"], "miembro"
        self._banda_difundir(j.banda)
        self._a_banda(j.banda, {"t": "aviso", "texto": es("%s entra en la banda.") % j.nombre, "son": "pareja"}, menos=j)
        self._a_todos({"t": "de_banda", "id": j.id, "banda": j.banda})

    def _fuera_de_banda(self, cuenta):
        self.alm.sacar_miembro(cuenta)
        for o in self.jugadores.values():
            if o.cuenta == cuenta:
                o.banda = o.rango = None
                if o.dentro:
                    self._enviar(o, {"t": "banda", "b": None, "rango": None})
                    self._a_todos({"t": "de_banda", "id": o.id, "banda": None})

    def _m_banda_salir(self, j, m):
        if j.banda is None:
            return
        banda = j.banda
        era_jefe = j.rango == "jefe"
        nombre = j.nombre
        self._fuera_de_banda(j.cuenta)
        resto = self.alm.miembros(banda)
        if not resto:
            return self._disolver(banda)
        if era_jefe:                                           # hereda la mano derecha, o el más antiguo
            nuevo = resto[0]
            self.alm.meter_miembro(nuevo["cuenta"], banda, "jefe")
            self.alm.poner_banda(banda, jefe=nuevo["cuenta"])
            for o in self.jugadores.values():
                if o.cuenta == nuevo["cuenta"]:
                    o.rango = "jefe"
            self._a_banda(banda, {"t": "aviso", "texto": es("%s deja la banda. Ahora manda %s.") % (nombre, nuevo["nombre"])})
        else:
            self._a_banda(banda, {"t": "aviso", "texto": es("%s deja la banda.") % nombre})
        self._banda_difundir(banda)

    def _disolver(self, banda):
        f = self.alm.banda(banda)
        self.alm.borrar_banda(banda)
        self.guerras = [g for g in self.guerras if banda not in (g["ataca"], g["defiende"])]
        if f is not None:
            self._a_todos({"t": "aviso", "texto": es("La banda %s se ha disuelto. Sus barrios quedan libres.") % f["nombre"]})
        self._difundir_territorios()

    def _m_banda_expulsar(self, j, m):
        mi = self.alm.miembro(m.get("cuenta"))
        if j.banda is None or j.rango != "jefe" or mi is None or mi["banda"] != j.banda or mi["cuenta"] == j.cuenta:
            return self._aviso(j, es("Solo el jefe puede echar a alguien de la banda."))
        self._fuera_de_banda(mi["cuenta"])
        self._a_banda(j.banda, {"t": "aviso", "texto": es("El jefe ha echado a alguien de la banda.")})
        self._banda_difundir(j.banda)

    def _m_banda_rango(self, j, m):
        mi = self.alm.miembro(m.get("cuenta"))
        rango = m.get("rango")
        if j.banda is None or j.rango != "jefe" or mi is None or mi["banda"] != j.banda or mi["cuenta"] == j.cuenta or rango not in RANGOS:
            return self._aviso(j, es("Solo el jefe reparte los rangos."))
        self.alm.meter_miembro(mi["cuenta"], j.banda, rango)
        if rango == "jefe":                                    # ceder el mando
            self.alm.meter_miembro(j.cuenta, j.banda, "mano")
            self.alm.poner_banda(j.banda, jefe=mi["cuenta"])
            j.rango = "mano"
        for o in self.jugadores.values():
            if o.cuenta == mi["cuenta"]:
                o.rango = rango
        self._banda_difundir(j.banda)

    def _m_banda_ingresar(self, j, m):
        try:
            n = max(1, min(1000000, int(m.get("n", 0))))
        except (TypeError, ValueError):
            return
        if j.banda is None or not self._cobrar(j, n, es("ingreso en la caja de la banda")):
            return
        self.alm.apunte(j.banda, j.nombre, n, es("ingreso"))
        self._banda_difundir(j.banda)

    def _m_banda_sacar(self, j, m):
        try:
            n = max(1, int(m.get("n", 0)))
        except (TypeError, ValueError):
            return
        f = self.alm.banda(j.banda) if j.banda is not None else None
        if f is None or j.rango not in ("jefe", "mano"):
            return self._aviso(j, es("De la caja solo sacan el jefe y su mano derecha."))
        if n > f["caja"]:
            return self._aviso(j, es("En la caja hay %d euros.") % f["caja"])
        self.alm.apunte(j.banda, j.nombre, -n, es("retirada"))
        j.dinero += n
        self._enviar(j, {"t": "dinero", "nombre": es("La caja de la banda"), "n": n})
        self._banda_difundir(j.banda)

    def _m_banda_fuego(self, j, m):
        if j.banda is None or j.rango != "jefe":
            return self._aviso(j, es("El fuego amigo lo decide el jefe."))
        self.alm.poner_banda(j.banda, fuego=int(bool(m.get("si"))))
        self.alm.guardar()
        self._a_banda(j.banda, {"t": "aviso", "texto": es("Fuego amigo de la banda: %s.") % (es("sí, cuidado con los tuyos") if m.get("si") else "no")})
        self._banda_difundir(j.banda)

    def _m_banda_disolver(self, j, m):
        if j.banda is None or j.rango != "jefe":
            return self._aviso(j, es("Solo el jefe puede disolver la banda."))
        banda = j.banda
        f = self.alm.banda(banda)
        if f is not None and f["caja"] > 0:                    # lo que queda en la caja se lo lleva el jefe
            j.dinero += int(f["caja"])
            self._enviar(j, {"t": "dinero", "nombre": es("La caja de la banda"), "n": int(f["caja"])})
        for mi in self.alm.miembros(banda):
            self._fuera_de_banda(mi["cuenta"])
        self._disolver(banda)

    def _m_banda_lista(self, j, m):
        out = []
        for b in self.alm.bandas():
            out.append({"id": b["id"], "nombre": b["nombre"], "miembros": len(self.alm.miembros(b["id"])),
                        "barrios": sum(1 for t in self.alm.territorios() if t["banda"] == b["id"])})
        self._enviar(j, {"t": "bandas", "e": out, "tuya": self._banda_datos(j.banda), "territorios": self._territorios()})

    def _m_alianza(self, j, m):
        otra = self.alm.banda_por_nombre(str(m.get("banda", "")))
        if j.banda is None or j.rango != "jefe" or otra is None or otra["id"] == j.banda:
            return self._aviso(j, es("Las alianzas las propone el jefe, a otra banda que exista."))
        if m.get("romper"):
            self.alm.aliar(j.banda, otra["id"], False)
            self._a_banda(otra["id"], {"t": "aviso", "texto": es("La banda %s rompe la alianza con la vuestra.") % self.alm.banda(j.banda)["nombre"]})
            self._banda_difundir(j.banda)
            return self._banda_difundir(otra["id"])
        if self.propuestas_alianza.get(j.banda) == otra["id"]:   # ellos ya nos lo habían propuesto: hecho
            self.propuestas_alianza.pop(j.banda, None)
            self.alm.aliar(j.banda, otra["id"], True)
            for b in (j.banda, otra["id"]):
                self._a_banda(b, {"t": "aviso", "texto": es("Alianza cerrada entre %s y %s.") % (self.alm.banda(j.banda)["nombre"], otra["nombre"]), "son": "pareja"})
                self._banda_difundir(b)
            return
        self.propuestas_alianza[otra["id"]] = j.banda
        self._a_banda(otra["id"], {"t": "aviso", "texto": es("La banda %s os propone una alianza. Si vuestro jefe se la propone a ellos, queda cerrada.") % self.alm.banda(j.banda)["nombre"]})
        self._aviso(j, es("Propuesta enviada a %s.") % otra["nombre"])

    def _barrio_valido(self, mapa, barrio):
        return mapa in self.mundo["mapas"] and any(b["id"] == barrio for b in self.mundo["mapas"][mapa]["barrios"])

    def _m_barrio_reclamar(self, j, m):
        """Quedarse con el barrio en el que estás, si no es de nadie. Lo paga la caja."""
        if j.banda is None or j.rango not in ("jefe", "mano"):
            return self._aviso(j, es("Los barrios los reclama el jefe o su mano derecha."))
        if not self._barrio_valido(j.mapa, j.barrio):
            return self._aviso(j, es("Aquí no hay ningún barrio que reclamar."))
        if self.alm.territorio(j.mapa, j.barrio) is not None:
            return self._aviso(j, es("Este barrio ya tiene dueño. Para quitárselo hay que declararle la guerra."))
        f = self.alm.banda(j.banda)
        mios = sum(1 for t in self.alm.territorios() if t["banda"] == j.banda)
        if mios >= len(self.alm.miembros(j.banda)) + 1:
            return self._aviso(j, es("Con la gente que sois no podéis sostener más barrios. Hace falta más banda."))
        precio = int(self.cfg["precio_barrio"])
        if f["caja"] < precio:
            return self._aviso(j, es("Reclamar un barrio cuesta %d euros de la caja, y hay %d.") % (precio, f["caja"]))
        self.alm.apunte(j.banda, j.nombre, -precio, es("reclamar un barrio"))
        self.alm.poner_territorio(j.mapa, j.barrio, j.banda)
        self._a_todos({"t": "aviso", "texto": es("La banda %s se queda con un barrio de %s.") % (f["nombre"], self.mundo["mapas"][j.mapa]["nombre"]), "son": "territorio"})
        self._banda_difundir(j.banda)
        self._difundir_territorios()

    def _m_barrio_guerra(self, j, m):
        """Declarar la guerra por el barrio en el que estás. No empieza ya: se avisa y se pelea a una hora."""
        if j.banda is None or j.rango not in ("jefe", "mano"):
            return self._aviso(j, es("La guerra la declara el jefe o su mano derecha."))
        t = self.alm.territorio(j.mapa, j.barrio) if self._barrio_valido(j.mapa, j.barrio) else None
        if t is None or t["banda"] == j.banda:
            return self._aviso(j, es("Este barrio no es de otra banda."))
        if t["banda"] in self.alm.aliadas(j.banda):
            return self._aviso(j, es("Ese barrio es de una banda aliada. Rompe antes la alianza."))
        if any(g["mapa"] == j.mapa and g["barrio"] == j.barrio for g in self.guerras):
            return self._aviso(j, es("Ya hay una guerra declarada por este barrio."))
        f = self.alm.banda(j.banda)
        precio = int(self.cfg["precio_guerra"])
        if f["caja"] < precio:
            return self._aviso(j, es("Declarar una guerra cuesta %d euros de la caja, y hay %d.") % (precio, f["caja"]))
        self.alm.apunte(j.banda, j.nombre, -precio, es("declarar una guerra"))
        inicio = self.ahora() + 60 * int(self.cfg["guerra_espera"])
        g = {"mapa": j.mapa, "barrio": j.barrio, "ataca": j.banda, "defiende": t["banda"], "inicio": inicio,
             "fin": inicio + 60 * int(self.cfg["guerra_dura"]), "pa": 0, "pd": 0, "fase": "espera"}
        self.guerras.append(g)
        lugar = es("%s, en %s") % (self._nombre_barrio(g), self.mundo["mapas"][g["mapa"]]["nombre"])
        for b, texto in ((g["defiende"], es("¡%s os declara la guerra por %s! Empieza dentro de %d minutos y dura %d. Gana quien más gente tenga dentro del barrio "
                                            "y más rivales tumbe.") % (f["nombre"], lugar, int(self.cfg["guerra_espera"]), int(self.cfg["guerra_dura"]))),
                         (g["ataca"], es("Guerra declarada por %s. Empieza dentro de %d minutos y dura %d. Hay que estar dentro del barrio.") % (
                             lugar, int(self.cfg["guerra_espera"]), int(self.cfg["guerra_dura"])))):
            self._a_banda(b, {"t": "aviso", "texto": texto, "son": "sirena_lejana"})
        self._banda_difundir(j.banda)
        self._difundir_territorios()

    def _nombre_barrio(self, g):
        return next((b["nombre"] for b in self.mundo["mapas"][g["mapa"]]["barrios"] if b["id"] == g["barrio"]), g["barrio"])

    def _guerras_paso(self, dt):
        ahora = self.ahora()
        for g in list(self.guerras):
            if g["fase"] == "espera" and ahora >= g["inicio"]:
                g["fase"] = "lucha"
                for b in (g["ataca"], g["defiende"]):
                    self._a_banda(b, {"t": "aviso", "texto": es("¡Empieza la guerra por %s! Todos al barrio.") % self._nombre_barrio(g), "son": "sirena"})
                self._difundir_territorios()
            if g["fase"] != "lucha":
                continue
            for o in self.jugadores.values():                  # un punto por segundo y por cada uno que está dentro y en pie
                if o.dentro and o.mapa == g["mapa"] and o.barrio == g["barrio"] and o.salud > 0 and not o.pasivo:
                    if o.banda == g["ataca"]:
                        g["pa"] += dt
                    elif o.banda == g["defiende"]:
                        g["pd"] += dt
            if ahora >= g["fin"]:
                self._guerra_fin(g)
            elif int(g["fin"] - ahora) % 120 == 0:
                for b in (g["ataca"], g["defiende"]):
                    self._a_banda(b, {"t": "aviso", "texto": es("Guerra por %s: atacantes %d puntos, defensores %d. Quedan %d minutos.") % (
                        self._nombre_barrio(g), int(g["pa"]), int(g["pd"]), max(0, int((g["fin"] - ahora) // 60)))})

    def _guerra_baja(self, por, caido):
        for g in self.guerras:
            if g["fase"] == "lucha" and caido.mapa == g["mapa"] and caido.barrio == g["barrio"]:
                if por.banda == g["ataca"] and caido.banda == g["defiende"]:
                    g["pa"] += 30
                elif por.banda == g["defiende"] and caido.banda == g["ataca"]:
                    g["pd"] += 30

    def _guerra_fin(self, g):
        self.guerras.remove(g)
        ataca, defiende = self.alm.banda(g["ataca"]), self.alm.banda(g["defiende"])
        gana_ataque = g["pa"] > g["pd"] and ataca is not None
        nombre = self._nombre_barrio(g)
        if gana_ataque:
            self.alm.poner_territorio(g["mapa"], g["barrio"], g["ataca"])
        texto = es("La guerra por %s ha terminado: %d a %d. %s") % (nombre, int(g["pa"]), int(g["pd"]),
                (es("El barrio pasa a %s.") % ataca["nombre"]) if gana_ataque else (es("%s lo conserva.") % (defiende["nombre"] if defiende else es("Su dueño"))))
        self._a_todos({"t": "aviso", "texto": texto, "son": "territorio"})
        for b in (g["ataca"], g["defiende"]):
            self._banda_difundir(b)
        self._difundir_territorios()

    # ========================================================= grupo de misión
    def _grupo(self, j):
        if j.grupo is None:
            return [j]
        return [o for o in self.jugadores.values() if o.dentro and o.grupo == j.grupo]

    def _grupo_difundir(self, lider):
        gente = [o for o in self.jugadores.values() if o.dentro and o.grupo == lider]
        if len(gente) < 2:
            for o in gente:
                o.grupo = None
                self._enviar(o, {"t": "grupo", "lider": None, "miembros": []})
            return
        for o in gente:
            self._enviar(o, {"t": "grupo", "lider": lider, "miembros": [{"id": x.id, "nombre": x.nombre} for x in gente]})

    def _m_grupo_invitar(self, j, m):
        o = self.jugadores.get(m.get("a"))
        if o is None or not o.dentro or o is j:
            return
        if j.grupo is not None and j.grupo != j.id:
            return self._aviso(j, es("Vas en el grupo de otro: solo invita quien lo lleva."))
        if o.grupo is not None:
            return self._aviso(j, es("%s ya va en un grupo.") % o.nombre)
        if len(self._grupo(j)) >= 4:
            return self._aviso(j, es("En un grupo caben cuatro."))
        self.invitaciones_grupo[o.id] = j.id
        self._enviar(o, {"t": "grupo_invita", "de": j.id, "nombre": j.nombre, "mision": str(m.get("mision", ""))[:80]})
        self._aviso(j, es("Invitación enviada a %s.") % o.nombre)

    def _m_grupo_resp(self, j, m):
        lider = self.jugadores.get(self.invitaciones_grupo.pop(j.id, None))
        if lider is None or not lider.dentro or j.grupo is not None or not m.get("si"):
            return
        lider.grupo = j.grupo = lider.id
        self._grupo_difundir(lider.id)
        for o in self._grupo(j):
            if o is not j:
                self._aviso(o, es("%s se une al grupo.") % j.nombre, "amigo_entra")

    def _grupo_salir(self, j, callar=False):
        lider = j.grupo
        if lider is None:
            return
        j.grupo = None
        if not callar and j.dentro:
            self._enviar(j, {"t": "grupo", "lider": None, "miembros": []})
        resto = [o for o in self.jugadores.values() if o.dentro and o.grupo == lider]
        if lider == j.id:                                      # se va quien lo llevaba: el grupo se deshace
            for o in resto:
                o.grupo = None
                self._enviar(o, {"t": "grupo", "lider": None, "miembros": []})
                self._aviso(o, es("%s ha deshecho el grupo.") % j.nombre)
        else:
            for o in resto:
                self._aviso(o, es("%s deja el grupo.") % j.nombre)
            self._grupo_difundir(lider)

    def _m_grupo_salir(self, j, m):
        self._grupo_salir(j)

    def _m_grupo_msg(self, j, m):
        """Lo que se cuentan entre sí los juegos de un grupo: los enemigos de la misión, los golpes y los pasos."""
        d = m.get("d")
        if j.grupo is None or not isinstance(d, dict) or len(json.dumps(d)) > 12000:
            return
        for o in self._grupo(j):
            if o is not j:
                self._enviar(o, {"t": "grupo_msg", "de": j.id, "nombre": j.nombre, "d": d})

    def _m_mision_hecha(self, j, m):
        """Quien lleva el grupo ha completado una misión: los que le ayudaban cobran su parte, una vez por misión."""
        mi = self.mundo["misiones"].get(m.get("id"))
        if mi is None or j.grupo != j.id:
            return
        parte = mi["dinero"] // 2
        for o in self._grupo(j):
            if o is j or o.mapa != j.mapa:
                continue
            clave = (j.cuenta, o.cuenta, m.get("id"))
            if clave in self.ayudas and not mi["repetible"]:
                self._aviso(o, es("Misión completada: %s. Ya cobraste por ayudar en ella.") % mi["titulo"], "mision_ok")
                continue
            self.ayudas.add(clave)
            self._enviar(o, {"t": "paga_mision", "titulo": mi["titulo"], "n": parte, "de": j.nombre})

    # ============================================================ administrar
    # El nombre inglés de cada orden. Valen las dos formas en cualquier servidor, esté en el idioma que esté: quien lo
    # administra escribe las órdenes como prefiera, en la consola, en el panel o en el chat.
    ORDENES_EN = {"help": "ayuda", "status": "estado", "players": "jugadores", "accounts": "cuentas", "announce": "aviso",
                  "tell": "decir", "kick": "expulsar", "ban": "vetar", "unban": "perdonar", "unadmin": "quitaradmin",
                  "deleteaccount": "borrarcuenta", "invite": "invitar", "invites": "invitaciones", "revoke": "anular",
                  "motd": "mensaje", "time": "hora", "gangs": "bandas", "save": "guardar", "backup": "copia", "backups": "copias",
                  "reload": "recargar", "update": "actualizar", "restart": "reiniciar", "maintenance": "mantenimiento",
                  "shutdown": "apagar", "stop": "apagar"}
    _EN_DE = {}
    for _en, _es in ORDENES_EN.items():
        _EN_DE.setdefault(_es, _en)                             # el primero es el que sale en la ayuda (shutdown, no stop)
    del _en, _es

    @classmethod
    def _con_ingles(cls, linea):
        """Cómo sale una orden en la ayuda. En español, con su nombre inglés al lado: «expulsar nombre (kick)». En
        cualquier otro idioma, solo el inglés, «kick name»: el nombre español sigue valiendo, pero no hace falta leerlo."""
        orden, _, resto = linea.partition(" ")
        en = cls._EN_DE.get(orden)
        if not en:
            return linea
        from .idioma import actual
        if actual() == "es":
            return "%s (%s)" % (linea, en)
        return en + ((" " + resto) if resto else "")

    AYUDA_ORDENES = (
        ("ayuda", tr("dice todas las órdenes")),
        ("estado", tr("cómo está el servidor: puerto, cifrado, mundo, tiempo en marcha y cuánta gente hay")),
        ("jugadores", tr("quién está dentro y dónde")),
        ("cuentas", tr("todas las cuentas del servidor, con las vetadas y las que administran")),
        ("aviso " + tr("texto"), tr("dice algo a todos los que están dentro")),
        ("decir " + tr("nombre: texto"), tr("dice algo solo a un jugador")),
        ("expulsar " + tr("nombre"), tr("saca a un jugador; puede volver a entrar. Detrás de dos puntos se le puede decir el motivo")),
        ("vetar " + tr("nombre"), tr("saca a un jugador y no le deja volver")),
        ("perdonar " + tr("nombre"), tr("levanta el veto")),
        ("admin " + tr("nombre"), tr("hace administrador a un jugador")),
        ("quitaradmin " + tr("nombre"), tr("le quita la administración")),
        ("borrarcuenta " + tr("nombre"), tr("borra una cuenta con su personaje, sus propiedades y su sitio en la banda; no se puede deshacer")),
        ("invitar", tr("crea un código de invitación de un solo uso; con un número detrás, crea varios")),
        ("invitaciones", tr("las invitaciones que hay, libres y usadas")),
        ("anular " + tr("código"), tr("anula una invitación que aún no ha usado nadie")),
        ("mensaje " + tr("texto"), tr("cambia el mensaje del día; sin texto, lo quita")),
        ("hora " + tr("número"), tr("pone la hora del juego, de 0 a 23")),
        ("bandas", tr("las bandas, con su gente y su caja")),
        ("guardar", tr("guarda todo ahora")),
        ("copia", tr("hace una copia de seguridad")),
        ("copias", tr("las copias de seguridad que hay")),
        ("recargar", tr("vuelve a leer servidor.conf y aplica lo que se puede cambiar sin reiniciar")),
        ("actualizar", tr("avisa a todos de que el servidor se reinicia para actualizarse, espera la cuenta atrás, lo guarda todo y lo para; "
                       "los juegos esperan y vuelven a entrar solos cuando lo arranques otra vez. Detrás se pueden poner los segundos de aviso")),
        ("reiniciar", tr("lo mismo, pero diciendo que es por mantenimiento. Detrás se pueden poner los segundos de aviso")),
        ("apagar", tr("avisa a todos, lo guarda todo y para el servidor")),
    )

    def resumen(self):
        """Cómo está el servidor ahora mismo, para quien lo administra: el panel y la orden estado salen de aquí.
        No lleva nada personal: la dirección de cada jugador solo va si la opción registro_ip lo permite."""
        con_ip = si(self.cfg["registro_ip"])
        gente = []
        for j in self.jugadores.values():
            if j.dentro and not j.bot:
                gente.append({"id": j.id, "cuenta": j.cuenta, "nombre": j.nombre, "admin": bool(j.admin), "juego": j.juego,
                              "mapa": self.mundo["mapas"].get(j.mapa, {}).get("nombre") if j.mapa else None,
                              "fuera": bool(j.mapa is None and j.mapa_fuera), "mismo_mundo": j.huella == self.mundo.get("huella"),
                              "ip": j.ip if con_ip else None})
        return {"activo": self.activo, "parando": self.parando, "nombre": self.cfg["nombre"], "puerto": getattr(self, "puerto", None), "cifrado": self.cifrado,
                "huella_cert": self.huella_cert, "mundo_version": self.mundo.get("version"), "mundo_huella": self.mundo.get("huella"),
                "localidades": len(self.mundo["mapas"]), "inicio": self.t_inicio, "max_jugadores": int(self.cfg["max_jugadores"]),
                "entrada": str(self.cfg["entrada"]), "personajes": len(self.bots), "protocolo": VERSION_RED,
                "jugadores": sorted(gente, key=lambda g: g["nombre"].lower())}

    def lista_cuentas(self):
        """Las cuentas, para administrarlas: nombre, si administra, si está vetada, cuándo se la vio y con qué versión."""
        dentro = {j.cuenta for j in self.jugadores.values() if j.dentro and not j.bot}
        return [{"id": f["id"], "nombre": f["nombre"], "admin": bool(f["admin"]), "vetado": bool(f["vetado"]), "visto": f["visto"], "creada": f["creada"],
                 "juego": f["juego"] or "", "dentro": f["id"] in dentro} for f in self.alm.lista_cuentas()]

    def lista_invitaciones(self):
        return [{"codigo": f["codigo"], "creada": f["creada"], "usada": f["usada_por"] is not None, "por": f["nombre"] or ""} for f in self.alm.invitaciones()]

    def aplicar_config(self, nueva):
        """Cambia la configuración con el servidor en marcha. Devuelve (opciones aplicadas, opciones que esperan al reinicio).
        Lo que no vale no se toca."""
        limpio, _ = opciones.validar(nueva, completar=False)
        al_momento, con_reinicio = opciones.cambios(self.cfg, dict(self.cfg, **limpio))
        for clave in al_momento:
            self.cfg[clave] = limpio[clave]
        if "admins" in al_momento:                             # quien administra por la lista, lo sabe ya
            admins = self._nombres("admins")
            for j in self.jugadores.values():
                if j.dentro and not j.bot and j.cuenta is not None:
                    fila = self.alm.cuenta(j.cuenta)
                    j.admin = bool(fila and fila["admin"]) or j.nombre.lower() in admins
        if "vetados" in al_momento:
            vetados = self._nombres("vetados")
            for j in list(self.jugadores.values()):
                if j.dentro and not j.bot and j.nombre.lower() in vetados:
                    self._echar(j, es("Un administrador te ha sacado del servidor."))
        return al_momento, con_reinicio

    def _tiempo_en_marcha(self):
        if not self.t_inicio:
            return tr("parado")
        s = int(max(0, time.time() - self.t_inicio))
        d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
        partes = ([(tr("%d día") if d == 1 else tr("%d días")) % d] if d else []) + ([(tr("%d hora") if h == 1 else tr("%d horas")) % h] if h else [])
        return ", ".join(partes + [(tr("%d minuto") if m == 1 else tr("%d minutos")) % m])

    def orden(self, texto, quien="consola"):
        """Órdenes de administración: desde la consola del servidor, desde el panel, o desde el chat con una barra delante."""
        partes = texto.strip().split(None, 1)
        if not partes:
            return ""
        que, resto = partes[0].lower(), (partes[1].strip() if len(partes) > 1 else "")
        que = self.ORDENES_EN.get(que, que)                     # español o inglés, en cualquier servidor: help, kick, ban...
        dentro = [j for j in self.jugadores.values() if j.dentro and not j.bot]

        def buscar(nombre):
            return next((j for j in dentro if j.nombre.lower() == nombre.lower()), None)
        if quien != "consola" and que not in ("ayuda", "?", "jugadores", "estado"):
            self.log(tr("%s da la orden %s.") % (quien, que))
        if que in ("ayuda", "?"):
            if quien != "consola":                              # por el chat, corto: se oye, no se lee
                return tr("Órdenes: ") + ", ".join(self._con_ingles(o) for o, _ in self.AYUDA_ORDENES) + "."
            return (tr("Órdenes (cada una vale en español o en inglés, en cualquier servidor):") + "\n"
                    + "\n".join("  %s: %s." % (self._con_ingles(o), a) for o, a in self.AYUDA_ORDENES))
        if que == "estado":
            r = self.resumen()
            tope = r["max_jugadores"]
            return (tr("Servidor «%s», en marcha desde hace %s. Puerto %s, %s. Mundo de la versión %s, huella %s, con %d localidades. "
                       "Hay %d %s%s y %d personajes del servidor.") % (
                        r["nombre"], self._tiempo_en_marcha(), r["puerto"], tr("con cifrado") if r["cifrado"] else tr("sin cifrado"), r["mundo_version"],
                        r["mundo_huella"], r["localidades"], len(dentro), tr("jugador") if len(dentro) == 1 else tr("jugadores"),
                        (tr(" de %d") % tope) if tope > 0 else tr(", sin límite"), r["personajes"]))
        if que == "jugadores":
            return (tr("Hay %d: ") % len(dentro)) + ", ".join(tr("%s en %s") % (j.nombre, self.mundo["mapas"].get(j.mapa, {}).get("nombre", tr("sin situar"))) for j in dentro) if dentro else tr("No hay nadie.")
        if que == "cuentas":
            cs = self.lista_cuentas()
            if not cs:
                return tr("Todavía no hay ninguna cuenta.")
            return (tr("Hay %d: ") % len(cs)) + ", ".join(c["nombre"] + (tr(" (administra)") if c["admin"] else "") + (tr(" (vetada)") if c["vetado"] else "")
                                                       + (tr(" (dentro)") if c["dentro"] else "") for c in cs) + "."
        if que == "aviso" and resto:
            self._a_todos({"t": "aviso", "texto": es("Aviso del servidor: %s") % resto[:300], "son": "notificacion"})
            return tr("Aviso enviado.")
        if que == "decir" and resto:
            nombre, _, dicho = resto.partition(":")
            j = buscar(nombre.strip())
            if j is None or not dicho.strip():
                return tr("Escribe decir (o tell), el nombre de alguien que esté dentro, dos puntos y el mensaje.")
            self._aviso(j, es("Quien administra el servidor te dice: %s") % dicho.strip()[:300], "notificacion")
            return tr("Dicho a %s.") % j.nombre
        if que in ("expulsar", "vetar") and resto:
            nombre, _, motivo = resto.partition(":")
            nombre = nombre.strip()
            j = buscar(nombre)
            fila = self.alm.cuenta_por_nombre(nombre)
            if fila is None:
                return tr("No hay nadie con ese nombre.")
            if que == "vetar":
                self.alm.poner(fila["id"], vetado=1)
                self.alm.guardar()
            if j is not None:
                self._echar(j, (es("Un administrador te ha sacado del servidor. Motivo: %s") % motivo.strip()[:200]) if motivo.strip() else
                            es("Un administrador te ha sacado del servidor."))
            elif que == "expulsar":
                return tr("%s no está dentro ahora mismo.") % fila["nombre"]
            return (tr("%s, vetado: no podrá volver a entrar.") if que == "vetar" else tr("%s, expulsado.")) % fila["nombre"]
        if que == "perdonar" and resto:
            fila = self.alm.cuenta_por_nombre(resto)
            if fila is None:
                return tr("No hay nadie con ese nombre.")
            self.alm.poner(fila["id"], vetado=0)
            self.alm.guardar()
            return tr("%s puede volver a entrar.") % fila["nombre"]
        if que in ("admin", "quitaradmin") and resto:
            fila = self.alm.cuenta_por_nombre(resto)
            if fila is None:
                return tr("No hay nadie con ese nombre.")
            pone = que == "admin"
            self.alm.poner(fila["id"], admin=int(pone))
            self.alm.guardar()
            j = buscar(resto)
            por_lista = fila["nombre"].lower() in self._nombres("admins")
            if j is not None:
                j.admin = pone or por_lista
            if not pone and por_lista:
                return tr("%s sigue administrando porque está en la lista de administradores de la configuración. Quítalo también de ahí.") % fila["nombre"]
            return (tr("%s ya es administrador.") if pone else tr("%s ya no administra.")) % fila["nombre"]
        if que == "borrarcuenta" and resto:
            fila = self.alm.cuenta_por_nombre(resto)
            if fila is None:
                return tr("No hay nadie con ese nombre.")
            mi = self.alm.miembro(fila["id"])
            if mi is not None and mi["rango"] == "jefe" and len(self.alm.miembros(mi["banda"])) > 1:
                return tr("%s es jefe de una banda con más gente. Antes tiene que ceder el mando o disolverla.") % fila["nombre"]
            j = buscar(fila["nombre"])
            if j is not None:
                self._salida(j, callar=True)
                self._echar(j, es("Un administrador ha borrado tu cuenta de este servidor."))
                self._a_todos({"t": "sale", "id": j.id})
            if mi is not None:                                 # era el único de su banda: la banda se va con él
                self._fuera_de_banda(fila["id"])
                if not self.alm.miembros(mi["banda"]):
                    self._disolver(mi["banda"])
                else:
                    self._banda_difundir(mi["banda"])
            suyas = [f["lugar"] for f in self.alm.propiedades() if f["cuenta"] == fila["id"]]
            for v in [v for v in self.vehiculos.values() if v.get("dueno") == fila["id"] and v["por"] is None]:
                self._quitar_vehiculo(v["id"])
            self.alm.borrar_cuenta(fila["id"])
            for lugar in suyas:                                # lo que tenía vuelve a estar en venta
                self._prop_difundir(lugar, antes=fila["id"])
            return tr("Cuenta de %s borrada, con su personaje y sus propiedades.") % fila["nombre"]
        if que == "invitar":
            try:
                n = max(1, min(50, int(resto))) if resto else 1
            except ValueError:
                return tr("Detrás de invitar, si pones algo, tiene que ser cuántos códigos quieres: de 1 a 50.")
            codigos = []
            for _ in range(n):
                codigo = secrets.token_hex(4).upper()
                self.alm.crear_invitacion(codigo)
                codigos.append(codigo)
            if n == 1:
                return tr("Código de invitación, de un solo uso: %s") % codigos[0]
            return tr("Códigos de invitación, de un solo uso cada uno: %s") % ", ".join(codigos)
        if que == "invitaciones":
            inv = self.lista_invitaciones()
            if not inv:
                return tr("No hay ninguna invitación. Se crean con la orden invitar (o invite).")
            return "; ".join("%s, %s" % (i["codigo"], (tr("usada por %s") % (i["por"] or tr("una cuenta que ya no existe"))) if i["usada"] else tr("libre"))
                             for i in inv) + "."
        if que == "anular" and resto:
            return tr("Invitación anulada.") if self.alm.borrar_invitacion(resto.strip().upper()) else tr("No hay ninguna invitación libre con ese código.")
        if que == "mensaje":
            valor, error = opciones.validar_valor("mensaje_dia", resto)
            if error:
                return tr("El mensaje del día %s.") % error
            self.cfg["mensaje_dia"] = valor
            if valor:
                self._a_todos({"t": "aviso", "texto": es("Mensaje del día: %s") % valor, "son": "notificacion"})
                return tr("Mensaje del día cambiado, hasta que el servidor se reinicie. Para dejarlo fijo, ponlo en la configuración.")
            return tr("Mensaje del día quitado.")
        if que == "hora" and resto:
            try:
                self.reloj = (finito(resto.replace(",", ".")) % 24) * 60
            except ValueError:
                return tr("Dime la hora con un número, de 0 a 23.")
            self._a_todos({"t": "hora", "h": self._hora()})
            return tr("Hora cambiada.")
        if que == "bandas":
            bs = self.alm.bandas()
            return "; ".join(tr("%s, %d miembros, %d euros") % (b["nombre"], len(self.alm.miembros(b["id"])), b["caja"]) for b in bs) if bs else tr("No hay bandas.")
        if que == "guardar":
            self.guardar_todo()
            self._t_guardado = time.monotonic()
            return tr("Guardado.")
        if que == "copia":
            try:
                return tr("Copia hecha en %s") % self.copia_seguridad()
            except Exception as e:
                return tr("No se ha podido hacer la copia: %s: %s") % (type(e).__name__, e)
        if que == "copias":
            lista = copias.listar(self.cfg["datos"])
            if not lista:
                return tr("No hay ninguna copia de seguridad.")
            return (tr("Hay %d, la más nueva primero: ") % len(lista)) + ", ".join(os.path.basename(c[0]) for c in lista[:30]) + "."
        if que == "recargar":
            if not self.ruta_conf or not os.path.exists(self.ruta_conf):
                return tr("Este servidor no se arrancó con un archivo de configuración: no hay nada que recargar.")
            nueva, avisos = opciones.leer(self.ruta_conf)
            al_momento, con_reinicio = self.aplicar_config(nueva)
            nombre = lambda c: opciones.POR_CLAVE[c].etiqueta
            return " ".join(avisos + [
                (tr("Aplicado: %s.") % ", ".join(nombre(c) for c in al_momento)) if al_momento else tr("No había nada que aplicar al momento."),
                (tr("Esperan a que reinicies el servidor: %s.") % ", ".join(nombre(c) for c in con_reinicio)) if con_reinicio else ""]).strip()
        if que in ("actualizar", "reiniciar", "mantenimiento"):
            if self.parando:
                return tr("El servidor ya se está parando.")
            try:
                aviso = int(resto) if resto else None
            except ValueError:
                return tr("Detrás de %s, si pones algo, tienen que ser los segundos de aviso.") % que
            aviso = self.parar_para_volver("actualizacion" if que == "actualizar" else "reinicio", aviso)
            return (tr("Aviso dado. El servidor se para dentro de %d segundos, guardándolo todo. Los juegos esperarán y volverán a entrar solos "
                       "cuando lo arranques otra vez.") % aviso)
        if que == "apagar":
            asyncio.get_event_loop().create_task(self.detener(es("Un administrador ha apagado el servidor.")))
            return tr("Apagando.")
        uso = next((o for o in self.AYUDA_ORDENES if o[0].split()[0] == que), None)
        if uso is not None:                                    # la orden existe, pero le falta el nombre, el texto o el número
            return tr("A esa orden le falta algo. Se escribe así: %s. Sirve para esto: %s.") % (self._con_ingles(uso[0]), uso[1])
        return tr("No conozco esa orden. Escribe ayuda o help.")
