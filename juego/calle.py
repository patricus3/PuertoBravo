"""La calle con vida propia (1.7.1): defensa propia, gente que reacciona y que habla entre sí, munición y armas de los
caídos, patrullas que circulan sin buscarte, ambulancias que acuden, rendirse y el helicóptero de la policía.

Casi todo se enciende y se apaga en Opciones, La calle. Los números y las frases salen de los datos del juego
(data/datos/vida.json, sección calle), que un mod puede cambiar. En un servidor con policía común, la policía la lleva
el servidor: aquí no se ponen patrullas, ni helicóptero, ni rendición.
"""
from .i18n import tr
import math
import random

from . import gente as G
from . import mundo as M
from .entidades import Objeto, Persona, Vehiculo

_AJUSTES = {
    "reaccion_cada": 8, "grito_prob": 85,
    "panico_prob": 75, "panico_cada": 2.6, "panico_max": 3, "panico_vol": 45,
    "charla_poco": 150, "charla_normal": 70, "charla_mucho": 30, "parejas": 20,
    "municion_prob": 70, "municion_min": 40, "municion_max": 120, "arma_prob": 35,
    "patrullas": 2, "patrullas_noche": 1, "auxilio_prob": 60,
    "ambulancia_prob": 80, "ambulancia_espera_min": 12, "ambulancia_espera_max": 30, "ambulancia_atiende": 14,
    "rendicion_multa": 300, "rendicion_dinero": 5, "rendicion_horas": 8, "rendicion_nivel_armas": 5,
    "helicoptero_nivel": 5, "helicoptero_llega": 20, "helicoptero_salud": 260, "helicoptero_altura": 40, "helicoptero_radio": 45,
    "helicoptero_pierde": 8, "helicoptero_busca": 35, "helicoptero_reconoce": 4, "helicoptero_vuelve": 90,
    "helicoptero_dano_minimo": 40, "helicoptero_multa": 2000,
}
# Los que pueden valer cero: una probabilidad a cero apaga esa parte, y cero patrullas es ninguna.
_CERO = ("grito_prob", "panico_prob", "parejas", "municion_prob", "arma_prob", "patrullas", "patrullas_noche", "auxilio_prob", "ambulancia_prob",
         "rendicion_dinero", "helicoptero_multa", "helicoptero_dano_minimo")
_LISTAS = {
    "frases_huye": [tr("{quien} sale corriendo."), tr("{quien} grita y echa a correr."), tr("{quien} huye calle abajo."), tr("{quien} se asusta y corre.")],
    "frases_huyen": [tr("{n} personas salen corriendo."), tr("La gente huye: {n} personas echan a correr."), tr("{n} personas gritan y se dispersan.")],
    "frases_aparta": [tr("{quien} se aparta de un salto."), tr("{quien} se quita de en medio."), tr("{quien} se echa a un lado.")],
    "frases_charla": [tr("{quien}, al pasar:"), tr("Oyes a {quien_min}, que pasa hablando:"), tr("{quien} le dice a quien va a su lado:")],
    "charla_temas": ["tiempo", "futbol", "trabajo_duro", "dinero", "comida", "barrio_vida", "ciudad_cambio", "policia", "delincuencia", "transporte",
                     "salud", "cansancio", "fiestas", "politica", "animales", "ninos_colegio", "deporte", "cine_tele", "juego_suerte", "noticias",
                     "movil", "compras_ropa", "casa_alquiler", "agua_sequia", "ricos_jefes", "familia", "hijos", "coches", "musica", "mar_playa", "puerto"],
    "frases_auxilio": [tr("¡Policía! ¡Suelta el arma!"), tr("¡Alto, policía!"), tr("¡Quieto ahí! ¡Policía!")],
    "frases_rendicion": [tr("¡Las manos donde yo las vea! ¡No te muevas!"), tr("¡Quiet[o|a]! ¡Al suelo, despacio!"), tr("¡No hagas ninguna tontería! ¡Las manos arriba!")],
    "megafono": [tr("Le tenemos localizado. Deténgase y salga con las manos en alto."), tr("Aquí la policía. No tiene escapatoria: ríndase."),
                 tr("Le habla la policía. Tire el arma y quédese donde está."), tr("Le vemos desde el aire. No empeore las cosas: entréguese.")],
    "helicoptero_sin_techo": ["monumento", "salida", "pesca", "muelle", "embarcadero", "carrera", "helipuerto", "tesoro", "tranvia", "taxi", "feria"],
}
AJUSTES = dict(_AJUSTES)
LISTAS = {k: list(v) for k, v in _LISTAS.items()}
CHARLA = {"nada": None, "pocas": "charla_poco", "algunas": "charla_normal", "muchas": "charla_mucho"}


def configurar(datos):
    """Lee la sección calle de los datos. Lo que falte o venga mal vale lo de serie."""
    c = next((x for x in datos.get("calle", []) if isinstance(x, dict)), {})
    for k, serie in _AJUSTES.items():
        try:
            n = float(c.get(k, serie))
            AJUSTES[k] = n if n > 0 or (n == 0 and k in _CERO) else serie
        except (TypeError, ValueError):
            AJUSTES[k] = serie
    for k, serie in _LISTAS.items():
        v = c.get(k)
        LISTAS[k] = [str(x) for x in v if str(x).strip()] if isinstance(v, list) and any(str(x).strip() for x in v) else list(serie)


def aj(k):
    return AJUSTES[k]


def genero_de(p):
    """«h» o «m»: el de su ficha si ya tiene nombre; si no, el de su voz (las agudas, de mujer; las graves, de hombre)."""
    f = getattr(p, "ficha", None)
    if f:
        return "m" if f.get("genero") == "m" else "h"
    return "m" if getattr(p, "tono", 1.0) > 1.1 else "h"


def voz_tono(p):
    """El tono con el que suena la voz grabada de esa persona: cerca del natural, un poco distinto en cada una."""
    t = getattr(p, "tono", 1.0)
    return max(0.86, min(1.14, 0.94 + (t - 1.22) * 0.7 if t > 1.1 else 0.92 + (t - 0.80) * 0.9))


def quien(p, minuscula=False):
    f = getattr(p, "ficha", None)
    if f and f.get("presentado") and f.get("nombre"):
        return f["nombre"]
    t = tr("Una mujer") if genero_de(p) == "m" else tr("Un hombre")
    return t.lower() if minuscula else t


class Calle:
    """Mixin de Partida."""

    def calle_iniciar(self):
        self._reacciones = []            # quién acaba de asustarse en este fotograma, para decirlo de una vez
        self.t_reaccion = -99.0
        self.t_charla = random.uniform(15, 40)
        self.t_patrullas = 4.0
        self.t_auxilio = -99.0
        self.t_aviso_auxilio = -99.0
        self.ambulancia = None           # la ambulancia que viene, atiende o se va: una cada vez
        self.t_ambulancia = 0.0
        self.rendido = None              # con las manos arriba: {"x", "y", "t", "arresto"}
        self.t_rendicion_rota = -99.0
        self.heli = None                 # el helicóptero de la policía: {"estado", "veh", ...}
        self.t_heli = None
        self.t_heli_aviso = -99.0
        self.t_represalia = -99.0

    def calle_cambio_mapa(self):
        """Al cambiar de localidad no queda nada de lo de la calle anterior."""
        self.ambulancia = None
        self.rendido = None
        self.heli = None
        self.t_heli = None
        self._reacciones = []

    def actualizar_calle(self, dt):
        self._decir_reacciones()
        self._charla_peatones(dt)
        self.t_patrullas -= dt
        if self.t_patrullas <= 0:
            self.t_patrullas = 3.0
            self._poner_patrullas()
        self._ambulancia(dt)
        self._rendicion(dt)
        self._helicoptero(dt)

    # ------------------------------------------------------------------ 1. defensa propia
    def es_agresor(self, p):
        return bool(self.cfg["defensa_propia"]) and getattr(p, "agresor", False)

    def en_defensa_propia(self):
        """¿Hay cerca alguien que te ha atacado primero? Entonces disparar para defenderte no es delito."""
        if not self.cfg["defensa_propia"]:
            return False
        x, y = self.pos()
        return any(getattr(p, "agresor", False) and not p.muerto and p.dist(x, y) < 80 for p in self.personas)

    def marcar_agresor(self, p):
        """Alguien te ataca sin que tú le hayas tocado antes: desde ahora, defenderte de él no cuenta como delito.
        No vale para los enemigos de una misión ni de una guerra de barrio, que ahí el que va a buscarlos eres tú."""
        if not self.cfg["defensa_propia"] or p.tipo in ("policia", "aliado", "perro", "civil") or p.tag not in (None, "evento"):
            return
        if getattr(p, "provocado", False) or getattr(p, "deportivo", False) or getattr(p, "inofensivo", False):
            return
        if not getattr(p, "agresor", False):
            p.agresor = True
            if "defensa_propia" not in self.j.recordado:
                self.j.recordado.append("defensa_propia")
                self.son("notificacion", cat="interfaz")
                self.decir(tr("Te han atacado primero: defenderte de quien te ataca no cuenta como delito.")
                           + ("" if self.sv_policia_comun() else tr(" Si llegan agentes, irán también a por él.")))
        self.pedir_auxilio()

    def pedir_auxilio(self):
        """Alguien avisa a la policía de la pelea: acude la patrulla que ande cerca o, a veces, sale una."""
        j = self.j
        if j.estrellas or self.cfg["sin_policia"] or not self.mundo.policia or self.mundo.tipo == "mar" or self.sv_policia_comun():
            return
        if (self.mision and self.mision["def"].get("tutorial")) or self.t - self.t_auxilio < 45:
            return
        if any(getattr(v, "auxilio", None) for v in self.vehiculos):      # ya hay una en camino, o con los agentes fuera
            return
        self.t_auxilio = self.t
        x, y = self.pos()
        cerca = [v for v in self.vehiculos if v.ia == "policia" and not v.muerto and not v.desplegado and v.dist(x, y) < 220]
        if cerca:
            v = min(cerca, key=lambda v: v.dist(x, y))
        elif random.random() < aj("auxilio_prob") * (2 if self.hon_buena_gente() else 1) / 100.0:      # a la buena gente se le ayuda antes
            v = self._crear_patrulla(x, y)
            if v is None:
                return
        else:
            return
        v.auxilio = self.t + 60.0
        v.t_calma = 0.0
        self.decir(tr("Alguien ha avisado a la policía: una patrulla viene hacia la pelea."))

    def _crear_patrulla(self, x, y, ronda=False):
        pos = self._punto_llegada(x, y)
        if pos is None or any(o.dist(pos[0], pos[1]) < 25 for o in self.vehiculos):
            return None
        e = G.agentes_nivel(1)
        v = Vehiculo(self.modelos.get(e["vehiculo"]) or self.modelos["patrulla"], pos[0], pos[1], pos[2], "policia")
        v.agentes = e
        v.ocupado = True
        v.ronda = ronda
        v.vel = v.vel_obj = random.uniform(8.0, 11.0)
        self.vehiculos.append(v)
        return v

    def _agresores(self, x, y, radio):
        if not self.cfg["defensa_propia"]:
            return []
        return [e for e in self.personas if getattr(e, "agresor", False) and not e.muerto and e.tipo not in ("policia", "aliado", "perro") and e.dist(x, y) < radio]

    def agente_auxilia(self, p, dt):
        """Un agente con un agresor a la vista va a por él. Si además te buscan a ti, va a por quien tenga más cerca.
        Devuelve True si en este fotograma se ha ocupado del agresor."""
        if getattr(p, "po_id", None) is not None or getattr(self, "rendido", None):
            return False
        cand = self._agresores(p.x, p.y, 45)
        if not cand:
            return False
        e = min(cand, key=lambda q: q.dist(p.x, p.y))
        de = e.dist(p.x, p.y)
        px, py = self.pos()
        if self.j.estrellas > 0 and p.dist(px, py) < de:
            return False
        a = self.armas_d.get(p.arma or "pistola", self.armas_d["punos"])
        cuerpo = a["tipo"] == "cuerpo"
        alcance = 1.8 if cuerpo else min(a["alcance"], 28.0)
        if de > alcance * 0.6:
            self._andar_hacia(p, e.x, e.y, 3.7, dt)
            p.t_paso -= dt
            if p.t_paso <= 0 and p.dist(px, py) < 30:
                p.t_paso = 0.33
                self.son("paso_npc", xy=(p.x, p.y), ref=3, maxd=30, vol=0.9, tono=0.85)
        if not getattr(p, "ha_dado_alto", False):
            p.ha_dado_alto = True
            if self.t - self.t_aviso_auxilio > 12:
                self.t_aviso_auxilio = self.t
                self.decir(f"{p.nombre}: {random.choice(LISTAS['frases_auxilio'])}")
        p.t_disparo -= dt
        if de > alcance or p.t_disparo > 0:
            return True
        p.t_disparo = random.uniform(0.9, 1.6)
        self.son(a["sonido"], xy=(p.x, p.y), ref=4 if cuerpo else 12, maxd=200, vol=0.8)
        if random.random() < getattr(p, "punteria", G.PUNTERIA) * (1.0 - 0.5 * de / alcance):
            self.herir_por_otro(e, a["dano"] * 0.6, p)
        return True

    def herir_por_otro(self, e, dano, autor):
        """A alguien le da otro que no eres tú (un agente): ni es delito tuyo, ni cuenta entre tus enemigos, ni deja botín."""
        if e.muerto:
            return
        e.salud -= dano
        if e.salud > 0:
            self.voz_persona(e, "dolor")
            return
        e.muerto = True
        e.t_estado = self.t
        self.son("muerte_npc", xy=(e.x, e.y), ref=6, tono=e.tono)
        self.decir(tr('{nombre} abate a {nombre2}.').format(nombre=(autor.nombre), nombre2=(e.nombre)))
        if self.objetivo is e:
            self.objetivo = None
            if self.cfg["punteria"] == "completa":
                self.fijar(callar=True)
        self.aviso_ambulancia(e.x, e.y)

    def patrulla_sin_busqueda(self, v, d, dt):
        """Lo que hace un coche patrulla cuando no te buscan: nada, hacer su ronda, o acudir a una pelea en la que te han atacado."""
        aux = getattr(v, "auxilio", None)
        if not aux:
            if v.sirena:
                v.sirena.parar()
                v.sirena = None
            if v.desplegado:
                return 0.0, self._decidir_trafico
            if getattr(v, "ronda", False):
                if self._obstaculo(v) or self._semaforo_rojo(v):
                    return 0.0, self._decidir_trafico
                return v.vel_obj, self._decidir_trafico
            return 11.0, self._decidir_trafico
        px, py = self.pos()
        hay = bool(self._agresores(v.x, v.y, 70) or self._agresores(px, py, 60))
        if v.desplegado:
            v.t_calma = 0.0 if hay else getattr(v, "t_calma", 0.0) + dt
            if v.t_calma > 6.0:
                self._recoger_agentes(v)
            return 0.0, self._decidir_policia
        if self.t > aux or (not hay and d < 70):                 # ya no hay pelea a la que ir
            v.auxilio = None
            v.ronda = True
            return v.vel_obj, self._decidir_trafico
        if v.sirena is None:
            v.sirena = self.son("sirena", bucle=True, xy=(v.x, v.y), ref=14, maxd=260, vol=0.7)
        if d < 16:
            if v.vel < 1.0:
                self._desplegar_auxilio(v)
            return 0.0, self._decidir_policia
        dx, dy = M.DIRS[v.dir]
        a = (px - v.x) * dx + (py - v.y) * dy
        lat = abs((px - v.x) * dy - (py - v.y) * dx)
        if a < -15 and lat < 20 and self.t > v.t_giro:
            v.t_giro = self.t + 3
            v.dir = (v.dir + 2) % 4
        if self._obstaculo(v, 9):                                # acude deprisa, pero no se lleva a nadie por delante
            return 0.0, self._decidir_policia
        return (min(v.modelo["vel_max"] * 0.6, 9.0) if d < 35 else v.modelo["vel_max"] * 0.6), self._decidir_policia

    def _desplegar_auxilio(self, v):
        v.desplegado = True
        v.ocupado = False
        v.t_calma = 0.0
        e = getattr(v, "agentes", None) or G.agentes_nivel(1)
        for k in range(e["ocupantes"]):
            x, y = self.mundo.punto_libre(v.x + random.uniform(-3, 3), v.y + random.uniform(-3, 3))
            f = G.enemigo({"clase": e["clase"]}) if k and e["clase"] else e
            p = G.vestir(Persona("policia", x, y, f["nombre"]), f)
            p.hostil = False
            p.estado = "quieto"
            p.coche = v
            p.t_disparo = random.uniform(0.4, 1.0)
            self.personas.append(p)
        self.son("puerta_coche", xy=(v.x, v.y))
        self.decir(tr('Llega una patrulla y se bajan {ocupantes} agentes. {situar}. Van a por quien te ha atacado, no a por ti.').format(ocupantes=(e['ocupantes']), situar=(self.situar(v.x, v.y, tr('Está')))))

    def _recoger_agentes(self, v):
        for p in [p for p in self.personas if p.tipo == "policia" and getattr(p, "coche", None) is v]:
            self.personas.remove(p)
            if self.objetivo is p:
                self.objetivo = None
        v.desplegado = False
        v.ocupado = True
        v.auxilio = None
        v.ronda = True
        if v.sirena:
            v.sirena.parar()
            v.sirena = None
        self.son("puerta_coche", xy=(v.x, v.y))
        if v.dist(*self.pos()) < 60:
            self.decir(tr("Los agentes vuelven al coche patrulla y siguen su ronda."))

    # ------------------------------------------------------------------ 2. la gente reacciona
    def voz_persona(self, p, cual, vol=0.6):
        """El grito o la queja de una persona, con voz de hombre o de mujer."""
        mujer = genero_de(p) == "m"
        if cual == "grito":
            if mujer:
                return self.son("grito_mujer", xy=(p.x, p.y), ref=6, maxd=80, vol=vol, tono=voz_tono(p))
            return self.son("grito_hombre", xy=(p.x, p.y), ref=6, maxd=80, vol=vol, tono=voz_tono(p))
        if mujer:
            return self.son("dolor_mujer", xy=(p.x, p.y), ref=6, vol=vol + 0.2, tono=voz_tono(p))
        return self.son("dolor_npc", xy=(p.x, p.y), ref=6, tono=p.tono)

    def asustar(self, p, segundos, que="huye", grito=None, callar=False):
        """Un peatón se asusta y huye (o se aparta): se le oye gritar, y el lector lo dice, sin saturar.
        Con «callar», solo se le oye: quien llama ya cuenta lo que pasa."""
        if p.muerto or p.tipo != "civil":
            return
        ya = p.estado == "huye"
        p.t_estado = max(p.t_estado, segundos) if ya else segundos
        p.estado = "huye"
        if ya:
            return
        if random.random() < (aj("grito_prob") / 100.0 if grito is None else grito):
            self.voz_persona(p, "grito")
        if not callar:
            self._reacciones.append((p, que))
        p.t_panico = None                                        # el pánico de después empieza de nuevo (panico)

    def panico(self, p, d, dt):
        """Mientras huye, a quien se ha asustado se le sigue oyendo: chillidos y gritos sueltos cada pocos segundos, cada
        vez con un tono distinto, para que la calle no se quede muda después del primer grito. Se oyen como mucho unos
        pocos a la vez (panico_max), para que una multitud corriendo no tape todo lo demás."""
        t = getattr(p, "t_panico", None)
        if t is None:
            p.t_panico = random.uniform(0.8, 1.8)                # el primero, después del grito del susto
            return
        p.t_panico = t - dt
        if p.t_panico > 0:
            return
        cada = aj("panico_cada")
        p.t_panico = random.uniform(cada * 0.6, cada * 1.5)
        if d > 45 or random.random() >= aj("panico_prob") / 100.0:
            return
        sonando = [c for c in getattr(self, "_panico_canales", []) if c.activo]
        if len(sonando) >= int(aj("panico_max")):
            self._panico_canales = sonando
            return
        self._panico_canales = sonando + [self.voz_panico(p)]

    def voz_panico(self, p):
        """Un chillido de pánico. Si el pack de sonidos trae panico_hombre y panico_mujer, suenan esos; si no, el grito de
        susto, más agudo y más bajo, con un tono distinto cada vez."""
        mujer = genero_de(p) == "m"
        vol = aj("panico_vol") / 100.0
        propio = "panico_mujer" if mujer else "panico_hombre"
        if propio in getattr(self.mez, "sonidos", {}):
            return self.son(propio, xy=(p.x, p.y), ref=6, maxd=60, vol=vol * random.uniform(0.8, 1.0), tono=voz_tono(p) * random.uniform(0.94, 1.06))
        return self.son("grito_mujer" if mujer else "grito_hombre", xy=(p.x, p.y), ref=5, maxd=60,
                        vol=vol * random.uniform(0.65, 1.0), tono=voz_tono(p) * random.uniform(1.0, 1.28))

    def _decir_reacciones(self):
        r, self._reacciones = self._reacciones, []
        if not r or not self.cfg["frases_reacciones"] or self.t - self.t_reaccion < aj("reaccion_cada"):
            return
        x, y = self.pos()
        cerca = [(p, que) for p, que in r if p.dist(x, y) < 30]
        if not cerca:
            return
        self.t_reaccion = self.t
        p, que = min(cerca, key=lambda e: e[0].dist(x, y))
        if len(cerca) == 1:
            frase = random.choice(LISTAS["frases_aparta" if que == "aparta" else "frases_huye"]).format(quien=quien(p))
        else:
            frase = random.choice(LISTAS["frases_huyen"]).format(n=len(cerca))
        self.decir(f"{frase.rstrip('.')}, {self.direccion_txt(p.x, p.y)}.")

    # ------------------------------------------------------------------ 3. peatones que hablan entre ellos
    def pareja_de_paseo(self, p):
        """A veces la gente pasea de dos en dos: quien acaba de salir a la calle lleva a alguien al lado."""
        if random.random() >= aj("parejas") / 100.0:
            return None
        q = Persona("civil", 0, 0)
        q.bloque, q.sentido, q.vel = p.bloque, p.sentido, p.vel
        q.u = p.u - 1.4 * p.sentido
        self._pos_perimetro(q)
        self.personas.append(q)
        return q

    def _charla_peatones(self, dt):
        cada = CHARLA.get(self.cfg["charla_peatones"])
        if cada is None:
            return
        self.t_charla -= dt
        if self.t_charla > 0:
            return
        self.t_charla = 2.0                                      # si ahora no puede ser, vuelve a mirar enseguida
        j = self.j
        if j.estrellas or self.transicion or self.mision_en_escena() or (j.veh and abs(j.veh.vel) > 4) or getattr(self, "guerra", None):
            return
        x, y = self.pos()
        if any(p.hostil and not p.muerto and p.dist(x, y) < 45 for p in self.personas):
            return
        cerca = [p for p in self.personas if p.tipo == "civil" and not p.muerto and p.estado == "pasea" and not p.tag and p.dist(x, y) < 11]
        pares = [(a, b) for a in cerca for b in cerca if a.id < b.id and a.dist(b.x, b.y) < 6 and self.t - getattr(a, "t_charla", -999.0) > 120]
        if not pares:
            return
        a, b = random.choice(pares)
        if random.random() < 0.5:
            a, b = b, a
        a.t_charla = b.t_charla = self.t
        self.t_charla = aj(cada) * random.uniform(0.7, 1.4)
        self.decir(self.frase_de_paso(a, b))

    def frase_de_paso(self, a, b):
        """Lo que se oye al pasar junto a dos personas que hablan: una frase de la base de conversación, y a veces la respuesta."""
        from . import charla, respuestas
        fa, fb = charla.ficha(a), charla.ficha(b)
        bx = self.mundo.barrio(a.x, a.y)
        ctx = {"barrio": bx["nombre"], "ciudad": self.mundo.nombre, "hora": self.hora_txt(), "tu": ""}
        frase = respuestas.suelta(fa, ctx, LISTAS["charla_temas"])
        self.son("murmullo", xy=(a.x, a.y), ref=4, maxd=30, vol=0.8, tono=voz_tono(a))
        t = random.choice(LISTAS["frases_charla"]).format(quien=quien(a), quien_min=quien(a, True)) + " " + frase
        if random.random() < 0.5:
            t += tr(' {quien} contesta: {comentario}').format(quien=(quien(b)), comentario=(respuestas.comentario(fb)))
        return t

    # ------------------------------------------------------------------ 4. munición y armas de los caídos
    def soltar_botin(self, p):
        """Un enemigo caído suelta munición de su arma, si tú llevas una igual; con la opción de dificultad, a veces el arma entera."""
        a = self.armas_d.get(p.arma or "")
        if not a or a["id"] == "punos" or p.tipo in ("civil", "aliado", "perro"):
            return None
        tengo = a["id"] in self.j.armas
        de_fuego = a["tipo"] in ("fuego", "explosivo")
        if self.cfg["soltar_armas"] and not self.en_servidor and not tengo and random.random() < aj("arma_prob") / 100.0:
            tipo = "arma"
        elif self.cfg["soltar_municion"] and de_fuego and tengo and random.random() < aj("municion_prob") / 100.0:
            tipo = "municion"
        else:
            return None
        balas = max(1, int(float(a.get("cargador", 1) or 1) * random.uniform(aj("municion_min"), max(aj("municion_min"), aj("municion_max"))) / 100.0)) if de_fuego else 0
        x, y = self.mundo.punto_libre(p.x + random.uniform(-1.5, 1.5), p.y + random.uniform(-1.5, 1.5))
        o = Objeto(tipo, tr('{nombre} en el suelo').format(nombre=(a['nombre'])) if tipo == "arma" else tr('Munición de {nombre}').format(nombre=(a['nombre'])), x, y)
        o.arma = a["id"]
        o.valor = balas
        self.objetos.append(o)
        return o

    def recoger_botin(self, o):
        j = self.j
        a = self.armas_d.get(getattr(o, "arma", ""))
        if not a:
            return
        self.son("recoger_municion", cat="interfaz")
        n = int(o.valor)
        if a["id"] not in j.armas:
            if o.tipo != "arma":
                self.decir(tr('Munición de {nombre}: ya no llevas esa arma, así que no te sirve.').format(nombre=(a['nombre'])))
                return
            cap = int(a.get("cargador", 0) or 0)
            j.armas[a["id"]] = {"cargador": min(cap, n), "reserva": max(0, n - cap)}
            num = self.orden_armas.index(a["id"]) + 1
            self.decir(tr('Recoges del suelo: {nombre}').format(nombre=(a['nombre'])) + (tr(", con una bala") if n == 1 else tr(', con {n} balas').format(n=(n)) if n else "") + "."
                       + (tr(' Es el arma número {num}.').format(num=(num)) if num <= 9 else tr(" Elígela con la coma o con la tecla I.")))
        elif n:
            m = j.armas[a["id"]]
            m["reserva"] += n
            self.decir(tr('Recoges {n} {v} de {nombre}. Llevas {v2}.').format(n=(n), v=(tr('bala') if n == 1 else tr('balas')), nombre=(a['nombre']), v2=(m['cargador'] + m['reserva'])))
        else:
            self.decir(tr('{nombre}: ya llevas una igual.').format(nombre=(a['nombre'])))

    # ------------------------------------------------------------------ 5. patrullas que circulan
    def patrullas_activas(self):
        return bool(self.cfg["patrullas_calle"]) and not self.cfg["sin_policia"] and self.mundo.policia and self.mundo.tipo != "mar" \
            and not self.sv_policia_comun() and not (self.mision and self.mision["def"].get("tutorial"))

    def _poner_patrullas(self):
        if not self.patrullas_activas() or self.j.estrellas or self.transicion:
            return
        quiero = int(aj("patrullas_noche" if self.es_noche() else "patrullas"))
        if sum(1 for v in self.vehiculos if getattr(v, "ronda", False) and not v.muerto) >= quiero:
            return
        self._crear_patrulla(*self.pos(), ronda=True)

    # ------------------------------------------------------------------ 6. ambulancias
    def aviso_ambulancia(self, x, y):
        """Ha caído alguien: al rato acude una ambulancia, atiende y se va. Solo ambiente; una cada vez."""
        if not self.cfg["ambulancias"] or self.en_servidor or self.ambulancia or self.t < self.t_ambulancia or self.mundo.tipo == "mar":
            return
        if "ambulancia" not in self.modelos or (self.mision and self.mision["def"].get("tutorial")) or random.random() >= aj("ambulancia_prob") / 100.0:
            return
        self.ambulancia = {"estado": "espera", "t": random.uniform(aj("ambulancia_espera_min"), max(aj("ambulancia_espera_min"), aj("ambulancia_espera_max"))),
                           "x": x, "y": y, "limite": 150.0, "veh": None}

    def _ambulancia(self, dt):
        a = self.ambulancia
        if not a:
            return
        v = a["veh"]
        if v is not None and v.muerto:                           # la han reventado, o has cambiado de localidad
            self.ambulancia = None
            self.t_ambulancia = self.t + 60
            return
        if a["estado"] == "espera":
            a["limite"] -= dt
            if a["limite"] <= 0:
                self.ambulancia = None
                return
            sigue = any(p.hostil and not p.muerto and p.activo and not getattr(p, "inofensivo", False) and p.dist(a["x"], a["y"]) < 50 for p in self.personas)
            if sigue or self.j.estrellas >= 3:                    # mientras dure el tiroteo, no entran
                return
            a["t"] -= dt
            if a["t"] > 0:
                return
            pos = self._punto_llegada(a["x"], a["y"])
            if pos is None:
                self.ambulancia = None
                return
            v = Vehiculo(self.modelos["ambulancia"], pos[0], pos[1], pos[2], "ambulancia")
            v.ocupado = True
            v.tag = "ambulancia"
            v.vel = 10.0
            v.destino = (a["x"], a["y"])
            v.sirena = self.son("sirena_ambulancia", bucle=True, xy=(v.x, v.y), ref=12, maxd=240, vol=0.6)
            self.vehiculos.append(v)
            a.update(estado="viene", veh=v, limite=55.0)
            self.decir(tr("Se oye una ambulancia: viene a atender a los heridos."))
        elif a["estado"] == "atiende":
            a["t"] -= dt
            if a["t"] <= 0:
                for p in [p for p in self.personas if p.muerto and not p.tag and p.dist(a["x"], a["y"]) < 30]:
                    self.personas.remove(p)                      # se los llevan
                self.son("curar", xy=(v.x, v.y), ref=8, maxd=60)
                self.son("puerta_coche", xy=(v.x, v.y), tono=0.82)
                v.lat_obj = 0.0
                a.update(estado="se_va", limite=45.0)
                if v.dist(*self.pos()) < 70:
                    self.decir(tr("Los sanitarios terminan y la ambulancia se va."))
        elif a["estado"] == "se_va":
            a["limite"] -= dt
            if a["limite"] <= 0 or v.dist(*self.pos()) > 220:
                self.quitar_vehiculo(v)
                self.ambulancia = None
                self.t_ambulancia = self.t + 40

    def _decidir_destino(self, v, i, j):
        tx, ty = v.destino
        ops = self._validas(v, i, j)
        return min(ops, key=lambda d: abs((i + M.DIRS[d][0]) * M.B - tx) + abs((j + M.DIRS[d][1]) * M.B - ty) + random.uniform(0, 10))

    def _ia_ambulancia(self, v, d, dt):
        """La ambulancia: va al sitio con la sirena, sin llevarse a nadie por delante; se arrima a la acera, atiende y se va como un coche más."""
        a = self.ambulancia
        if not a or a.get("veh") is not v:
            return 0.0, self._decidir_trafico
        if a["estado"] == "viene":
            tx, ty = v.destino
            dd = math.hypot(tx - v.x, ty - v.y)
            a["limite"] -= dt
            if dd < 40:
                v.lat_obj = 2.2                                  # se arrima a la acera para no cortar la calle
            if dd < 20 or a["limite"] <= 0:
                if v.vel < 1.0:
                    if v.sirena:
                        v.sirena.parar()
                        v.sirena = None
                    a.update(estado="atiende", t=aj("ambulancia_atiende"), x=v.x, y=v.y)
                    self.son("puerta_coche", xy=(v.x, v.y), tono=0.82)
                    if d < 120:
                        self.decir(tr('Llega la ambulancia y los sanitarios atienden a los heridos. {situar}.').format(situar=(self.situar(v.x, v.y, tr('Está')))))
                return 0.0, self._decidir_destino
            if self._obstaculo(v, 11):
                return 0.0, self._decidir_destino
            dx, dy = M.DIRS[v.dir]
            if (tx - v.x) * dx + (ty - v.y) * dy < -15 and abs((tx - v.x) * dy - (ty - v.y) * dx) < 20 and self.t > v.t_giro:
                v.t_giro = self.t + 3
                v.dir = (v.dir + 2) % 4
            return (7.0 if dd < 40 else min(v.modelo["vel_max"] * 0.6, 16.0)), self._decidir_destino
        if a["estado"] == "atiende":
            return 0.0, self._decidir_trafico
        if self._obstaculo(v) or self._semaforo_rojo(v):
            return 0.0, self._decidir_trafico
        return 10.0, self._decidir_trafico

    # ------------------------------------------------------------------ 7. rendirse
    def rendicion_txt(self, nivel=None):
        """Lo que te cuesta rendirte con ese nivel de búsqueda, en una frase."""
        j = self.j
        n = j.estrellas if nivel is None else nivel
        if n <= 2:
            return tr("Con tan poca búsqueda es una detención corriente: puedes arreglarlo con una multa, si la opción está activada.")
        multa, horas, todas = self._pena_rendicion(n)
        return (tr('Con nivel {n}: {multa} euros de multa, {horas} horas de calabozo y te quedas sin tus armas de fuego').format(n=(n), multa=(multa), horas=(horas))
                + (tr(" y sin las demás armas ni el chaleco.") if todas else "."))

    def _pena_rendicion(self, n):
        j = self.j
        multa = min(j.dinero, int(aj("rendicion_multa") * n + j.dinero * aj("rendicion_dinero") * n / 100.0))
        return multa, int(8 + aj("rendicion_horas") * (n - 2)), n >= aj("rendicion_nivel_armas")

    def _agentes_cerca(self, radio=70):
        x, y = self.pos()
        return any(p.tipo == "policia" and not p.muerto and p.dist(x, y) < radio for p in self.personas) or \
            any(v.ia == "policia" and not v.muerto and v.dist(x, y) < radio for v in self.vehiculos)

    def rendirse(self):
        """Mayúsculas H: levantas las manos. Los agentes dejan de disparar y vienen a detenerte."""
        j = self.j
        if self.transicion:
            return False
        if self.rendido:
            self._romper_rendicion(tr("Bajas las manos."))
            return False
        if self.sv_policia_comun():
            self.decir(tr("En este servidor la policía la lleva el servidor, y con ella no hay rendición con las manos arriba."), True)
            return False
        if j.estrellas == 0:
            self.decir(tr("Nadie te busca: no hay ante quién rendirse."), True)
            return False
        if self.t < self.t_rendicion_rota:
            self.app.son("error")
            self.decir(tr("Acabas de romper una rendición: los agentes no se fían. Espera un poco."), True)
            return False
        if j.veh and abs(j.veh.vel) > 2:
            self.decir(tr("Detén el vehículo antes de rendirte."), True)
            return False
        if not self._agentes_cerca():
            self.decir(tr("No hay ningún agente cerca ante quien rendirte. Espera a que lleguen."), True)
            return False
        x, y = self.pos()
        self.rendido = {"x": x, "y": y, "t": 0.0, "arresto": 0.0, "dicho": False}
        self.son("levantarse")
        self.sv_ruido("grito")
        self.decir(tr("Levantas las manos y gritas que te rindes. Los agentes dejan de disparar y vienen a por ti: no te muevas ni ataques. ")
                   + self.rendicion_txt() + tr(" Con Mayúsculas H otra vez, bajas las manos."), True)
        return True

    def _romper_rendicion(self, texto):
        if not self.rendido:
            return
        self.rendido = None
        self.t_rendicion_rota = self.t + 25.0
        self.decir(texto + tr(" Los agentes vuelven a disparar."), True)

    def _rendicion(self, dt):
        r = self.rendido
        if not r:
            return
        j = self.j
        if j.estrellas == 0 or self.transicion:
            self.rendido = None
            return
        x, y = self.pos()
        if math.hypot(x - r["x"], y - r["y"]) > 1.5:
            self._romper_rendicion(tr("Te has movido: se acabó la rendición."))
            return
        r["t"] += dt
        if r["t"] > 50 and not self._agentes_cerca(90):
            self.rendido = None
            self.decir(tr("Nadie viene a detenerte. Bajas las manos."))

    def agente_detiene(self, p, d, dt):
        """Con las manos arriba, el agente no dispara: se acerca y te esposa. Devuelve True si te ha detenido."""
        r = self.rendido
        if not r["dicho"] and d < 25:
            r["dicho"] = True
            self.decir(f"{p.nombre}: {random.choice(LISTAS['frases_rendicion'])}")
        if d > 1.8:
            self._andar_hacia(p, *self.pos(), 3.7, dt)
            p.t_paso -= dt
            if p.t_paso <= 0 and d < 30:
                p.t_paso = 0.33
                self.son("paso_npc", xy=(p.x, p.y), ref=3, maxd=30, vol=0.9, tono=0.85)
        if d < 3.0:
            r["arresto"] += dt
            if r["arresto"] > 1.2:
                self.detener(rendicion=True)
                return True
        return False

    # ------------------------------------------------------------------ 8. helicóptero de la policía
    def heli_activo(self):
        return bool(self.cfg["helicoptero_policia"]) and not self.cfg["sin_policia"] and self.mundo.policia and self.mundo.tipo != "mar" \
            and not self.sv_policia_comun() and "helicoptero" in self.modelos

    def heli_te_tiene(self):
        """El helicóptero te tiene localizado: mientras sea así, no hay manera de despistar a la policía."""
        h = self.heli
        return bool(h and h["estado"] == "vigila")

    def _aspecto(self):
        v = self.j.veh
        return ("veh", v.id) if v else ("pie",)

    def oculto_del_cielo(self):
        """A pie y pegado a una fachada, bajo el alero, o a cubierto tras una pared: desde arriba no se te ve."""
        j = self.j
        if j.veh:
            return False
        return any(self.mundo.superficie(j.x + dx, j.y + dy) == "pared" for dx, dy in ((1.2, 0), (-1.2, 0), (0, 1.2), (0, -1.2)))

    def entrar_bajo_techo(self, l):
        """Entras en un edificio (un local, tu casa, un garaje, un taller): el helicóptero deja de verte en el acto."""
        h = self.heli
        if h and h["estado"] == "vigila" and l.tipo not in LISTAS["helicoptero_sin_techo"]:
            self._heli_pierde(tr("Al entrar bajo techo, el helicóptero te pierde de vista."))

    def _heli_voz(self, texto):
        h = self.heli
        v = h["veh"]
        c = self.son("megafono", xy=(v.x, v.y), ref=40, maxd=450, vol=0.9)
        c.alto = aj("helicoptero_altura")
        self.decir(texto)

    def _heli_llega(self):
        x, y = self.pos()
        ang = random.uniform(0, 2 * math.pi)
        v = Vehiculo(self.modelos["helicoptero"], x + math.sin(ang) * 320, y + math.cos(ang) * 320, 0, "heli_policia")
        v.nombre = tr("Helicóptero de la policía")
        v.salud = v.salud_max = float(aj("helicoptero_salud"))
        v.hostil = v.ocupado = v.volando = True
        v.tag = "helicoptero"
        v.canal = self.son("helicoptero_policia", bucle=True, xy=(v.x, v.y), ref=35, maxd=460, vol=0.9)
        v.canal.alto = aj("helicoptero_altura")
        self.vehiculos.append(v)
        self.heli = {"estado": "llega", "veh": v, "ang": ang, "sentido": random.choice([-1, 1]), "t_oculto": 0.0, "t_visto": 0.0, "t_busca": 0.0,
                     "t_megafono": 0.0, "centro": (x, y), "vistos": set(), "pista": False}
        self.son("notificacion", cat="interfaz")
        self.decir(tr('Se oye un helicóptero: la policía te busca también desde el aire. {situar}. Mientras te tenga localizado no podrás despistar a nadie: pégate a una fachada, entra en un edificio o cambia de vehículo sin que te vea.').format(situar=(self.situar(v.x, v.y, tr('Viene')))))

    def _heli_fuera(self, texto=None, volver=None):
        h = self.heli
        self.heli = None
        self.t_heli = self.t + (aj("helicoptero_vuelve") if volver is None else volver)
        if h and not h["veh"].muerto:
            self.quitar_vehiculo(h["veh"])
        if texto:
            self.decir(texto)

    def _heli_pierde(self, texto):
        h = self.heli
        x, y = self.pos()
        h.update(estado="busca", centro=(x, y), t_busca=float(aj("helicoptero_busca")), t_visto=0.0, t_oculto=0.0)
        self.son("policia_perdida", cat="interfaz", vol=0.5)
        self.decir(texto + tr(" Da vueltas buscándote: ya puedes despistar a la policía. Si sales al descubierto tal como te vio, te encuentra; con otro vehículo no te reconoce."))

    def _helicoptero(self, dt):
        j = self.j
        h = self.heli
        nivel = aj("helicoptero_nivel")
        if h is None:
            if not self.heli_activo() or j.estrellas < nivel or self.transicion:
                self.t_heli = None
                return
            if self.t_heli is None:
                self.t_heli = self.t + aj("helicoptero_llega")
            if self.t >= self.t_heli:
                self._heli_llega()
            return
        v = h["veh"]
        if h["estado"] == "cae":
            h["t"] -= dt
            if h["t"] <= 0:
                self._heli_se_estrella(h)
            return
        if v.muerto:
            self.heli = None
            return
        if j.estrellas < nivel or not self.heli_activo():
            self._heli_fuera(None if self.transicion or j.estrellas == 0 else tr("El helicóptero de la policía se retira."))
            return
        x, y = self.pos()
        radio = aj("helicoptero_radio")
        oculto = self.oculto_del_cielo()
        if h["estado"] == "llega":
            tx, ty, vel = x, y, 42.0
            if v.dist(x, y) < radio + 12:
                h["ang"] = math.atan2(v.x - x, v.y - y)
                if oculto:
                    h.update(estado="busca", centro=(x, y), t_busca=float(aj("helicoptero_busca")))
                    self.decir(tr("El helicóptero llega y da vueltas sobre la zona: todavía no te ha visto."))
                else:
                    h["estado"] = "vigila"
                    h["vistos"].add(self._aspecto())
                    self._heli_voz(tr("El helicóptero te enfoca. Por el altavoz: ") + random.choice(LISTAS["megafono"]))
                    h["t_megafono"] = random.uniform(22, 38)
        else:
            cx, cy = (x, y) if h["estado"] == "vigila" else h["centro"]
            r = radio if h["estado"] == "vigila" else radio * 1.3
            h["ang"] += h["sentido"] * (26.0 / r) * dt
            tx, ty, vel = cx + math.sin(h["ang"]) * r, cy + math.cos(h["ang"]) * r, 34.0
        ddx, ddy = tx - v.x, ty - v.y
        dist = math.hypot(ddx, ddy)
        if dist > 0.1:
            paso = min(dist, vel * dt)
            v.x, v.y = v.x + ddx / dist * paso, v.y + ddy / dist * paso
            v.rumbo = M.rumbo_a(ddx, ddy)
        if v.canal:
            v.canal.mover(v.x, v.y)
        if h["estado"] == "vigila":
            h["vistos"].add(self._aspecto())
            if oculto:
                h["t_oculto"] += dt
                h["t_tic"] = h.get("t_tic", 0.0) - dt
                if h["t_tic"] <= 0:                              # mientras no te ve, el latido de «te buscan y no te ven», más agudo
                    h["t_tic"] = 1.0
                    self.son("buscando", vol=0.5, cat="interfaz", tono=1.3)
                if not h["pista"] and h["t_oculto"] > 1.0:      # se explica una vez por helicóptero
                    h["pista"] = True
                    self.decir(tr("Pegad[o|a] a la fachada, el helicóptero no te ve. Aguanta así unos segundos."))
                if h["t_oculto"] >= aj("helicoptero_pierde"):
                    self._heli_pierde(tr("El helicóptero te ha perdido de vista."))
            else:
                h["t_oculto"] = 0.0
                h["t_megafono"] -= dt
                if h["t_megafono"] <= 0:
                    h["t_megafono"] = random.uniform(22, 38)
                    self._heli_voz(tr("Helicóptero de la policía: ") + random.choice(LISTAS["megafono"]))
        elif h["estado"] == "busca":
            h["t_busca"] -= dt
            a_la_vista = not oculto and math.hypot(x - h["centro"][0], y - h["centro"][1]) < radio * 2
            # te reconoce si vas como te vio, o si un agente de tierra te tiene delante y le canta dónde estás
            if a_la_vista and (self._aspecto() in h["vistos"] or self._agentes_cerca(40)):
                h["t_visto"] += dt
                if h["t_visto"] >= aj("helicoptero_reconoce"):
                    h.update(estado="vigila", t_visto=0.0, t_oculto=0.0)
                    h["t_megafono"] = random.uniform(22, 38)
                    self.son("estrella_sube", cat="interfaz", vol=0.6)
                    self._heli_voz(tr("¡El helicóptero te ha vuelto a localizar! Por el altavoz: ") + random.choice(LISTAS["megafono"]))
            else:
                h["t_visto"] = 0.0
            if h["estado"] == "busca" and h["t_busca"] <= 0:
                self._heli_fuera(tr("El helicóptero no te encuentra y se retira."))

    def heli_danado(self, v, dano):
        """Le das al helicóptero. Las armas ligeras no le hacen nada: hace falta un rifle, una carabina o un explosivo."""
        h = self.heli
        if not h or h["veh"] is not v or h["estado"] == "cae":
            return
        if dano < aj("helicoptero_dano_minimo") * 0.55:
            if self.t - self.t_heli_aviso > 8:
                self.t_heli_aviso = self.t
                self.decir(tr("Las balas rebotan en el helicóptero: hace falta un arma pesada, un rifle o un explosivo."))
            return
        antes = v.salud / v.salud_max
        v.salud -= dano
        self.son("bala_impacto", xy=(v.x, v.y), ref=30, maxd=300)
        if antes > 0.5 >= v.salud / v.salud_max > 0:
            self.decir(tr("El helicóptero echa humo."))
        if v.salud > 0:
            return
        j = self.j
        v.salud = 0.0
        c = self.son("explosion", xy=(v.x, v.y), ref=40, maxd=500)
        c.alto = aj("helicoptero_altura")
        x, y = v.x, v.y
        self.quitar_vehiculo(v)
        self.heli = {"estado": "cae", "veh": v, "t": 2.2, "x": x, "y": y}
        j.stats["helicopteros"] = j.stats.get("helicopteros", 0) + 1
        j.cargos_helicoptero = int(getattr(j, "cargos_helicoptero", 0)) + 1
        self.cambiar_ciudadania(-8.0)
        self.cambiar_reputacion(4)
        self.t_represalia = self.t + 120.0
        self.t_evasion = 0.0
        self.app.vibrar(1.0, 1.0, 500)
        self.decir(tr('¡Has derribado el helicóptero de la policía! Cae envuelto en llamas, {metros}, {direccion_txt}: apártate. Toda la policía de la comarca se vuelca en buscarte: durante dos minutos tardarás el doble en despistarla, y si te cogen pagarás {int} euros más por el helicóptero.').format(metros=(M.metros(math.hypot(x - self.pos()[0], y - self.pos()[1]))), direccion_txt=(self.direccion_txt(x, y)), int=(int(aj('helicoptero_multa')))), True)

    def _heli_se_estrella(self, h):
        x, y = h["x"], h["y"]
        self.heli = None
        self.t_heli = self.t + aj("helicoptero_vuelve")
        self.son("explosion", xy=(x, y), ref=30, maxd=400)
        self.son("cristal", xy=(x, y), ref=20, maxd=200)
        self.app.vibrar(1.0, 1.0, 600)
        j = self.j
        px, py = self.pos()
        d = math.hypot(px - x, py - y)
        for o in list(self.vehiculos):
            if not o.muerto and not getattr(o, "volando", False) and o.dist(x, y) < 10:
                self.danar_vehiculo(o, 90 * (1 - o.dist(x, y) / 10.0))
        if d < 10 and not j.veh:
            self.danar_jugador(15 + 50 * (1 - d / 10.0), (x, y))
        for p in self.personas:
            if p.tipo == "civil" and not p.muerto and p.dist(x, y) < 50:
                self.asustar(p, 14)
