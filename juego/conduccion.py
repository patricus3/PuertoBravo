"""Vehículos: conducción del jugador (asistida o libre), tráfico, policía motorizada."""
from .i18n import tr
import math
import random

import pygame

from . import gente as G
from . import mundo as M
from .entidades import Persona, Vehiculo


# De serie, por si faltan en los datos (vida.json, sección ambiente): el volumen de la radio por los auriculares y como
# música de fondo de un local, y los tipos de local donde suena.
NIVEL_WALKMAN = 0.7
NIVEL_HILO = 0.3
LOCALES_CON_MUSICA = ("tienda", "comida", "pizzeria", "bar", "taberna", "ropa", "gimnasio", "club", "casino", "taller", "concesionario",
                      "feria", "empenos", "nautica", "armeria")

# Cómo conduce el piloto del GPS (opción «piloto_estilo»): se elige con un toque de la A al volante. Mantener la A sigue
# siendo cambiar al carril contrario; un toque corto, de menos de A_TOQUE milisegundos, abre el menú.
ESTILOS_PILOTO = ("auto", "tranquilo", "normal", "prisa_legal", "prisa", "muy_prisa")
A_TOQUE = 350


def nombre_estilo(e):
    return {"auto": tr("Automático"), "tranquilo": tr("Tranquilo"), "normal": tr("Normal, cumpliendo las normas"),
            "prisa_legal": tr("Con prisa, pero cumpliendo las normas"), "prisa": tr("Con prisa, saltándose las normas"),
            "muy_prisa": tr("Con muchísima prisa, a toda velocidad")}.get(e, e)


def ayuda_estilo(e):
    return {"auto": tr("Va a velocidad de ciudad y corre más solo cuando hace falta: con la sirena o en una misión contra el reloj, que además no espera en los semáforos; en un trabajo contra el reloj corre más, pero espera en rojo."),
            "tranquilo": tr("Despacio y con suavidad: acelera poco, frena pronto y para en todos los semáforos. Nunca tiene prisa."),
            "normal": tr("A velocidad de ciudad, sin pasar del límite, y espera en todos los semáforos, aunque vayas contra el reloj."),
            "prisa_legal": tr("Acelera a fondo y va un poco por encima del límite, pero sin llegar a lo que se multa; para en rojo, aunque no frena si el semáforo solo está a punto de cambiar."),
            "prisa": tr("Al noventa por ciento de lo que da el vehículo y sin esperar en los semáforos. Si te ve la policía, te costará multas y puntos del carné."),
            "muy_prisa": tr("A toda la velocidad que da el vehículo y sin esperar en los semáforos. Con tan poco margen para frenar, choca más a menudo. Si te ve la policía, multas y puntos del carné.")}.get(e, "")


class Conduccion:
    # ------------------------------------------------------------- utilidades
    def modo_asistido(self):
        v = self.j.veh
        if v is not None and v.modelo.get("vuela"):
            return False
        return (self.cfg["conduccion"] == "asistida" or self.chofer_conduce()) and not self.libre_temp and self.mundo.tipo != "mar"

    def _alinear(self, v):
        """Coloca el vehículo en el sentido de la vía más cercana. False si está fuera de la calzada."""
        t, idx, dist = self.mundo.via_cercana(v.x, v.y)
        if dist > M.ACERA + 1:
            return False
        r = v.rumbo % 360
        if t == "H":
            v.dir = 1 if 0 <= r < 180 else 3
        else:
            v.dir = 0 if (r < 90 or r >= 270) else 2
        v.rumbo = v.dir * 90.0
        return True

    def preparar_conduccion(self):
        v = self.j.veh
        if not v:
            return
        if self.mundo.tipo == "mar" or v.modelo.get("vuela"):
            self.libre_temp = False
        elif self.cfg["conduccion"] == "asistida" or self.chofer_conduce():
            self.libre_temp = not self._alinear(v)
            if self.libre_temp:
                self.decir(tr("Estás fuera de la calzada: conducción libre hasta que vuelvas a una calle."))
        else:
            self.libre_temp = False
        v.aviso_cruce = None

    @staticmethod
    def _golpe(v):
        """Cuánto daño le hace un choque a este vehículo respecto a uno de serie: menos con la suspensión reforzada."""
        from . import sistemas
        return sistemas.factor_golpes(v)

    def _motor(self, v, propio):
        if v.canal is None:
            if propio:
                from . import sistemas
                v.canal = self.son(v.modelo["motor"], bucle=True, vol=0.42 * sistemas.factor_motor_volumen(v), tono=v.modelo["tono"] * 0.6)
            else:
                v.canal = self.son(v.modelo["motor"], bucle=True, xy=(v.x, v.y), ref=7, maxd=95, vol=0.85, tono=v.modelo["tono"] * 0.6)

    @staticmethod
    def _linea_cruzada(a0, a1):
        if a1 > a0:
            k = math.floor(a1 / M.B)
            return k if k > math.floor(a0 / M.B) or (a0 < k * M.B <= a1) else None
        if a1 < a0:
            k = math.ceil(a1 / M.B)
            return k if k < math.ceil(a0 / M.B) else None
        return None

    def _mover_via(self, v, dt, lat_obj, decidir):
        m = self.mundo
        dx, dy = M.DIRS[v.dir]
        if dx == 0:
            i = m._idx(v.x, m.NX)
            obj = m.carril("V", i, v.dir, lat_obj)
            v.x += max(-6 * dt, min(6 * dt, obj - v.x))
            a0 = v.y
            v.y += dy * v.vel * dt
            if v.vel > 0:
                linea = self._linea_cruzada(a0, v.y)
                if linea is not None and 0 <= linea < m.NY:
                    self._en_cruce(v, i, linea, decidir)
            if v.dir in (0, 2) and (v.y < 0 or v.y > m.alto):    # el borde del mapa para a quien sigue de frente, no a quien acaba de girar en la última calle
                v.y = max(0.0, min(m.alto, v.y))
                v.vel = 0.0
        else:
            jj = m._idx(v.y, m.NY)
            obj = m.carril("H", jj, v.dir, lat_obj)
            v.y += max(-6 * dt, min(6 * dt, obj - v.y))
            a0 = v.x
            v.x += dx * v.vel * dt
            if v.vel > 0:
                linea = self._linea_cruzada(a0, v.x)
                if linea is not None and 0 <= linea < m.NX:
                    self._en_cruce(v, linea, jj, decidir)
            if v.dir in (1, 3) and (v.x < 0 or v.x > m.ancho):
                v.x = max(0.0, min(m.ancho, v.x))
                v.vel = 0.0
        v.rumbo = v.dir * 90.0

    def _en_cruce(self, v, i, j, decidir):
        antes = v.dir
        nd = decidir(v, i, j)
        if nd != v.dir:
            v.dir = nd
            m = self.mundo
            # El giro se hace en el centro del cruce, y el carril de quien gira a la derecha queda tres metros más atrás:
            # un coche del tráfico que gira así sale ya dentro de su calle nueva, no de vuelta en el morro del que le seguía.
            jv = self.j.veh
            av = 1.0
            if v is not jv and nd == (antes + 1) % 4:
                av = M.CARRIL + 4.5                              # a más de un coche de distancia del carril que deja
                if jv is not None:                               # salvo que justo ahí, en la calle nueva, esté tu vehículo: entonces gira como siempre y frena detrás de ti
                    ndx, ndy = M.DIRS[nd]
                    ox, oy = jv.x - i * M.B, jv.y - j * M.B
                    if abs(ox * ndy - oy * ndx - M.CARRIL) < 2.6 and av - 3.6 < ox * ndx + oy * ndy < av + 8.0:
                        av = 1.0
            if nd in (0, 2):
                v.x = m.carril("V", i, nd)
                v.y = j * M.B + M.DIRS[nd][1] * av
            else:
                v.y = m.carril("H", j, nd)
                v.x = i * M.B + M.DIRS[nd][0] * av
            v.rumbo = nd * 90.0

    def _validas(self, v, i, j, atras=False):
        ops = [d for d in (v.dir, (v.dir + 1) % 4, (v.dir - 1) % 4) if self.mundo.dir_valida(i, j, d)]
        if not ops or atras:
            ops.append((v.dir + 2) % 4)
        return ops

    def _viene_de_frente(self, v):
        """¿Viene tu vehículo de frente por esta misma calle, a punto de pasar por el cruce? Quien gira a la izquierda cruza
        tu carril: como en la calle de verdad, no se gira delante de quien viene."""
        jv = self.j.veh
        if jv is None or jv is v or jv.muerto or jv.vel < 1.0 or jv.dir != (v.dir + 2) % 4 or getattr(jv, "volando", False):
            return False
        dx, dy = M.DIRS[v.dir]
        a = (jv.x - v.x) * dx + (jv.y - v.y) * dy
        lat = abs((jv.x - v.x) * dy - (jv.y - v.y) * dx)
        return lat < 2 * M.CALZADA and -2.0 < a < 10.0 + jv.vel * 1.5

    def _decidir_trafico(self, v, i, j):
        ops = self._validas(v, i, j)
        if len(ops) > 1 and (v.dir - 1) % 4 in ops and self._viene_de_frente(v):
            ops.remove((v.dir - 1) % 4)
        if v.dir in ops and random.random() < 0.6:
            return v.dir
        return random.choice(ops)

    def _decidir_policia(self, v, i, j):
        px, py = self.pos()
        ops = self._validas(v, i, j)
        return min(ops, key=lambda d: abs((i + M.DIRS[d][0]) * M.B - px) + abs((j + M.DIRS[d][1]) * M.B - py) + random.uniform(0, 20))

    def _decidir_huida(self, v, i, j):
        px, py = self.pos()
        ops = self._validas(v, i, j)
        return max(ops, key=lambda d: math.hypot((i + M.DIRS[d][0]) * M.B - px, (j + M.DIRS[d][1]) * M.B - py) + random.uniform(0, 70))

    def _decidir_jugador(self, v, i, j):
        m = self.mundo
        g = v.giro
        if g == 0 and self.piloto_puesto():
            g = self.giro_gps()
        cand = {-1: (v.dir - 1) % 4, 1: (v.dir + 1) % 4, 2: (v.dir + 2) % 4}.get(g, v.dir)
        forzado = False
        if not m.dir_valida(i, j, cand):
            forzado = True
            cand = next(d for d in (v.dir, (v.dir + 1) % 4, (v.dir - 1) % 4, (v.dir + 2) % 4) if m.dir_valida(i, j, d))
        v.giro = 0
        self._parar_intermitente()
        self.cruce_act = (i, j)
        self.infraccion_semaforo(v, i, j)
        if cand != v.dir:
            if abs(v.vel) > 15:
                self.son("frenazo", vol=0.6)
                if abs(v.vel) > 30:
                    self.danar_vehiculo(v, 4)
                    self.decir(tr("¡Derrapas!"))
                v.vel *= 0.6
            via = m.avenidas[i] if cand in (0, 2) else m.calles[j]
            self.decir((tr("Fin de la vía. ") if forzado else "") + tr('{via}, hacia el {v}.').format(via=(via), v=(M.NOMBRE_DIR[cand])))
        return cand

    def _parar_intermitente(self):
        c = getattr(self, "intermitente", None)
        if c:
            c.parar()
        self.intermitente = None

    # ---------------------------------------------------- entrar y salir
    def entrar_salir(self):
        if getattr(self, "pasajero", None) is not None:
            self.bajar_de_amigo()
            return
        if not self.j.veh and self.subir_con_amigo():
            return
        self._entrar_salir()

    def _entrar_salir(self):
        j = self.j
        if self.mundo.tipo == "mar" and j.veh:
            if j.veh.modelo.get("vuela"):
                self.decir(tr("No puedes bajarte de un helicóptero sobre el mar.") if not self.vuelo_real() else tr("No puedes posarte sobre el mar."), True)
                return
            if abs(j.veh.vel) > 3:
                self.decir(tr("Frena antes de tirarte al agua."), True)
                return
            self.salir_vehiculo()                               # te tiras al agua: el barco se queda donde está
            self.empezar_a_nadar(tr("Te tiras al agua."))
            return
        if j.veh:
            if j.veh.modelo.get("vuela") and self.vuelo_real() and self.vuelo_aterrizar(j.veh):
                return                                           # en el aire: la F aterriza, y al tocar tierra te bajas
            if abs(j.veh.vel) > 3:
                self.decir(tr("Frena antes de bajarte."), True)
                return
            if j.veh.modelo.get("vuela") and not self.mundo.transitable(j.veh.x, j.veh.y):
                self.decir(tr("No puedes aterrizar aquí: debajo hay un edificio. Busca una calle o un espacio abierto; la tecla C te dice sobre qué estás."), True)
                return
            self.salir_vehiculo()
            return
        if self.forzando:
            self.forzando["canal"].parar()
            self.forzando = None
            self.decir(tr("Dejas de forzar la cerradura."), True)
            return
        cerca = [v for v in self.vehiculos if not v.muerto and v.dist(j.x, j.y) <= 5.5 and not getattr(v, "volando", False)]
        if not cerca:
            self.decir(tr("No hay ningún vehículo a tu lado. Usa el radar con Tabulador para encontrar uno."), True)
            return
        v = min(cerca, key=lambda v: (v.tag != "mision", not self._tuyo_para_subir(v), v.dist(j.x, j.y)))
        if v.ardiendo >= 0:
            self.decir(tr("¡Ese vehículo está ardiendo!"), True)
            return
        if self.sv_pedir_vehiculo(v):                            # lo dejó ahí otro jugador: el servidor dice quién se lo lleva
            return
        if v.ia == "policia" and not v.desplegado and v.ocupado:
            self.decir(tr("Ese coche patrulla está lleno de policías."), True)
            return
        if v.ia == "enemigos" and v.ocupado:
            self.decir(tr("Ese vehículo está lleno de enemigos."), True)
            return
        if v.ia == "ambulancia":
            self.decir(tr("Los sanitarios están trabajando y no te dejan subir."), True)
            return
        if v.ia == "chofer":                                     # tu chófer, que todavía está llegando: para y te recoge
            self._chofer_llega(v)
        if v.ia in ("trafico", "huida") and v.ocupado:
            if abs(v.vel) > 6:
                self.decir(tr("Va demasiado rápido para abrir la puerta."), True)
                return
            self.son_puerta(v, xy=(v.x, v.y))
            p = Persona("civil", *self.mundo.punto_libre(v.x + 2, v.y + 2), nombre=tr("Conductor"))
            p.estado = "huye"
            p.t_estado = 12
            self.personas.append(p)
            self.voz_persona(p, "grito", vol=1.0)
            self.delito(2, tr("robo de vehículo con violencia"))
            v.ocupado = False
            self._subir(v, True)
            return
        if v.cerrado:
            con_ganzua = j.objetos.get("ganzua", 0) > 0
            self.forzando = {"veh": v, "t": 1.5 if con_ganzua else 3.5, "ganzua": con_ganzua,
                             "canal": self.son("ganzua", bucle=True, vol=0.7)}
            self.decir(tr('Fuerzas la cerradura de {nombre}').format(nombre=(v.nombre)) + (tr(" con la ganzúa.") if con_ganzua else tr(". No te muevas.")), True)
            return
        self._subir(v, v.ia == "policia" or not getattr(v, "propio", False))

    def _tuyo_para_subir(self, v):
        """Con varios vehículos pegados, la F prefiere el tuyo, o al que te lleva el GPS, al de un desconocido."""
        g = self.gps or {}
        return (self.es_mio(v) or v is getattr(self, "ultimo_veh", None) or getattr(v, "traido", False) or getattr(v, "red_dueno", False)
                or v is g.get("cosa") or v is g.get("sigue"))

    def son_puerta(self, v, xy=None):
        """Subir o bajar no suena igual en todo: una moto y una bici no tienen puerta, un barco es una cubierta,
        la puerta de un camión pesa y la de un deportivo es ligera."""
        motor = v.modelo.get("motor", "")
        kw = {"xy": xy} if xy else {}
        if motor in ("motor_moto", "motor_bici"):
            return self.son("levantarse", vol=0.7, tono=0.9 if motor == "motor_moto" else 1.25, **kw)
        if v.modelo.get("barco"):
            return self.son("paso_muelle0", vol=0.9, tono=0.8, **kw)
        tono = {"motor_camion": 0.7, "motor_furgoneta": 0.82, "motor_tractor": 0.75, "motor_deportivo": 1.15,
                "motor_helicoptero": 1.3, "motor_avioneta": 1.3}.get(motor, 1.0)
        return self.son("puerta_coche", tono=tono, **kw)

    def _forzar(self, dt):
        f = self.forzando
        v = f["veh"]
        if v.muerto or v.dist(self.j.x, self.j.y) > 6:
            f["canal"].parar()
            self.forzando = None
            return
        f["t"] -= dt
        if f["t"] <= 0:
            f["canal"].parar()
            self.forzando = None
            v.cerrado = False
            if f["ganzua"]:
                self.j.objetos["ganzua"] -= 1
            elif v.con_alarma:
                v.alarma = self.son("alarma", bucle=True, xy=(v.x, v.y), ref=8, maxd=110, vol=0.8)
                v.t_alarma = 18.0
                self.decir(tr("¡Salta la alarma!"))
                self.delito(1.2, tr("robo de vehículo"), siempre=bool(v.tag))
            else:
                self.delito(0.5, tr("robo de vehículo"))
            if not v.tag:
                self.moc_botin("guantera")                       # a veces hay algo en la guantera (mochila.py)
            self._subir(v, True)

    def _subir(self, v, robado, callar=False):
        j = self.j
        if getattr(self, "nadando", False):                  # sales del agua
            self._fin_agua()
            self.son("salpicadura", vol=0.6)
        if v.sirena:
            v.sirena.parar()
            v.sirena = None
        if v.canal:
            v.canal.parar()
            v.canal = None
        if v.plaza is not None:
            self.plazas_usadas.add(v.plaza)
            self.plazas_activas.pop(v.plaza, None)
            v.plaza = None
        if v.ia == "policia":
            self.delito(3, tr("robo de un coche patrulla"), siempre=True)
        v.ia = None
        v.ocupado = False
        v.vel = 0.0
        if robado and not getattr(v, "propio", False):
            j.stats["vehiculos_robados"] += 1
        v.propio = True
        j.veh = v
        if v.modelo.get("vuela") and self.vuelo_real():
            self.vuelo_prep(v)                                   # altura, fase y combustible (vuelo.py)
        con_chofer = self.chofer_al_subir(v)                     # si lo trae tu chófer, vas de pasajero
        j.agachado = False
        self.oy_rumbo = v.rumbo
        self.ultimo_veh = None
        self.son_puerta(v)
        if v.modelo.get("motor") != "motor_bici" and not getattr(v, "en_marcha", False):      # en un golpe, el conductor lo tenía arrancado
            self.son("arranque", vol=0.6)
        v.en_marcha = False
        self._motor(v, True)
        self.rodadura = self.son("rodadura", bucle=True, vol=0.0)
        self.preparar_conduccion()
        self.sv_subido(v)
        radio = self.app.radio
        self._hilo = False
        if self.j.walkman and radio.sonando_ahora() and radio.actual == self.cfg["emisora"] % len(radio.emisoras):
            radio.poner_nivel(1.0)                               # ya la venías oyendo por los auriculares: sigue sin cortarse
            r = radio.nombre()
        else:
            radio.poner_nivel(1.0)
            r = radio.sintonizar(self.cfg["emisora"])
        if callar:
            return
        if con_chofer:
            self.decir(self.chofer_texto_subir(v), True)
            return
        suyo = tr(', tu {nombre}').format(nombre=(v.modelo['nombre'])) if v.nombre != v.modelo["nombre"] and getattr(v, "mio", False) else ""      # con nombre propio: se dice también qué es
        txt = tr('Subes a {nombre}{suyo}. Estado {int} por ciento. Miras al {cardinal}.').format(nombre=(v.nombre), suyo=(suyo), int=(int(100 * v.salud / v.salud_max)), cardinal=(M.cardinal(v.rumbo)))
        if v.modelo.get("trabajo"):
            txt += tr(" Pulsa J para trabajar con este vehículo.")
        if v.modelo.get("sirena"):
            txt += tr(" La tecla P enciende la sirena.")
        if v.modelo.get("vuela"):
            txt += self.vuelo_texto_subir(v) if self.vuelo_real() else tr(" Vuelas por encima de todo: izquierda y derecha giran, arriba acelera. Para bajarte, detente sobre una calle o un espacio abierto.")
        elif self.cfg["piloto_gps"] and not v.modelo.get("barco") and self.mundo.tipo != "mar":
            # el piloto se puede dejar puesto en Opciones: que se sepa por qué no arranca solo
            if not self.modo_asistido():
                txt += tr(" Tienes el piloto del GPS puesto, pero solo conduce en conducción asistida, y ahora vas en libre.")
            elif self.gps:
                txt += tr(' El piloto del GPS te lleva a {nombre}: no toques las flechas.').format(nombre=(self.gps['nombre']))
            else:
                txt += tr(" El piloto del GPS está puesto: marca un destino y te lleva solo.")
        self.decir(txt, True)
        if self.app.radio.id_actual() != "apagada":
            self.decir(r)

    # ------------------------------------------------------------ la radio a pie y en los locales
    def ambiente_cfg(self):
        """Los ajustes de la radio a pie y en los locales, de los datos del juego."""
        d = next((x for x in self.datos.get("ambiente", []) if isinstance(x, dict)), {})
        try:
            return {"locales": tuple(d.get("locales_con_musica") or LOCALES_CON_MUSICA),
                    "walkman": max(0.05, min(1.0, float(d.get("volumen_auriculares", NIVEL_WALKMAN * 100)) / 100.0)),
                    "hilo": max(0.02, min(1.0, float(d.get("volumen_local", NIVEL_HILO * 100)) / 100.0))}
        except (TypeError, ValueError):
            return {"locales": LOCALES_CON_MUSICA, "walkman": NIVEL_WALKMAN, "hilo": NIVEL_HILO}

    def walkman_puesto(self):
        return bool(self.j.walkman) and self.j.objetos.get("walkman", 0) > 0

    def walkman(self):
        """Mayúsculas R, a pie: el reproductor con auriculares. Cada pulsación pasa a la emisora siguiente; una de ellas es apagado."""
        j = self.j
        radio = self.app.radio
        if not j.objetos.get("walkman"):
            self.app.son("error")
            self.decir(tr("No tienes reproductor con auriculares. Se compra en las tiendas."), True)
            return
        self._hilo = False
        if not j.walkman:
            j.walkman = True                                     # al encenderlo, la emisora en la que lo dejaste
            if radio.emisoras[self.cfg["emisora"] % len(radio.emisoras)]["id"] == "apagada":
                self.cfg["emisora"] = (self.cfg["emisora"] + 1) % len(radio.emisoras)
        else:
            self.cfg["emisora"] = (self.cfg["emisora"] + 1) % len(radio.emisoras)
        self.app.son("radio_cambio")
        radio.poner_nivel(self.ambiente_cfg()["walkman"])
        texto = radio.sintonizar(self.cfg["emisora"])
        if radio.id_actual() == "apagada":
            j.walkman = False
            self.decir(tr("Reproductor apagado. Te quitas los auriculares."), True)
        else:
            self.decir(tr("Auriculares puestos. ") + texto, True)

    def walkman_al_empezar(self):
        """Al cargar una partida en la que ibas con los auriculares puestos, sigue sonando."""
        if self.walkman_puesto() and not self.j.veh:
            self.app.radio.poner_nivel(self.ambiente_cfg()["walkman"])
            self.app.radio.sintonizar(self.cfg["emisora"])

    def hilo_musical(self, l):
        """Al entrar en un local con música: suena una emisora del juego, bajita, como en las tiendas de verdad. Cada local
        tiene la suya. Si ya llevas los auriculares puestos, sigues oyendo lo tuyo."""
        radio = self.app.radio
        if self.j.veh or self.walkman_puesto() and radio.sonando_ahora():
            return False
        amb = self.ambiente_cfg()
        if l.get("sin_musica") or not (l.get("musica") or l.tipo in amb["locales"]):
            return False
        musicales = radio.musicales()
        if not musicales:
            return False
        import zlib
        radio.poner_nivel(amb["hilo"])
        radio.sintonizar(musicales[zlib.crc32(l.id.encode("utf-8")) % len(musicales)])
        self._hilo = True
        return True

    def fin_hilo_musical(self):
        if getattr(self, "_hilo", False):
            self._hilo = False
            self.app.radio.apagar()

    def salir_vehiculo(self, forzado=False):
        j = self.j
        v = j.veh
        if not v:
            return
        j.veh = None
        self._parar_intermitente()
        if v.canal:
            v.canal.parar()
            v.canal = None
        if getattr(self, "rodadura", None):
            self.rodadura.parar()
            self.rodadura = None
        if self.walkman_puesto() and self.app.radio.id_actual() != "apagada":
            self.app.radio.poner_nivel(self.ambiente_cfg()["walkman"])            # te bajas con los auriculares puestos: sigue sonando
        else:
            self.app.radio.apagar()
        if self.sirena_propia:
            self.sirena_propia.parar()
            self.sirena_propia = None
        v.vel = 0.0
        v.ia = None
        if getattr(v, "fase", None) is not None:                 # una aeronave que dejas, la dejas posada
            v.fase, v.alt = "tierra", 0.0
        rad = math.radians(v.rumbo + 90)
        for lado in (3.0, -3.0, 5.0, -5.0, 0.0):
            x, y = v.x + math.sin(rad) * lado, v.y + math.cos(rad) * lado
            if self.mundo.transitable(x, y):
                j.x, j.y = x, y
                break
        if not self.mundo.transitable(j.x, j.y):
            j.x, j.y = self.mundo.punto_libre(v.x, v.y)
        j.rumbo = v.rumbo
        self.libre_temp = False
        if self.trabajo and self.trabajo.get("veh") is v:
            self.terminar_trabajo(tr("Dejas el vehículo de trabajo: se acaba el servicio.") + (tr(" La carga se queda sin entregar. Para volver a empezar, sube al camión y pulsa J.") if self.trabajo.get("tipo") == "camion" else ""))
        if not v.tag and not v.muerto:
            self.ultimo_veh = v
            self.veh_fuera = None                                # el que cuenta es el último del que te bajas
            for d in self.mis_lejos:
                d.pop("ultimo", None)
        self.sv_bajado(v)
        if not forzado:
            self.son_puerta(v)
            self.decir(tr('Te bajas. {describir}.').format(describir=(self.mundo.describir(j.x, j.y))), True)

    # ------------------------------------------------------ teclas al volante
    def tecla_coche(self, ev, mayus):
        k = ev.key
        v = self.j.veh
        if self.chofer_tecla(k):                                 # conduce tu chófer: las teclas de conducir no hacen nada
            return
        if k in (pygame.K_LEFT, pygame.K_RIGHT) and self.modo_asistido():
            g = 1 if k == pygame.K_RIGHT else -1
            self._parar_intermitente()
            if v.giro == g:
                v.giro = 0
                self.decir(tr("Intermitente quitado. Seguirás recto."), True)
            else:
                v.giro = g
                self.intermitente = self.son("intermitente", bucle=True, pan=0.7 * g, vol=0.6)
                self.decir(tr("Girarás a la ") + ("derecha" if g > 0 else "izquierda") + tr(" en el próximo cruce."), True)
        elif k == pygame.K_u:
            if abs(v.vel) > 6:
                self.decir(tr("Frena para dar media vuelta."), True)
            elif self.modo_asistido():
                v.dir = (v.dir + 2) % 4
                v.rumbo = v.dir * 90.0
                v.aviso_cruce = None
                self.decir(tr('Media vuelta. Ahora vas hacia el {v}.').format(v=(M.NOMBRE_DIR[v.dir])), True)
            else:
                v.rumbo = (v.rumbo + 180) % 360
                self.decir(tr('Media vuelta. Vas hacia el {cardinal}.').format(cardinal=(M.cardinal(v.rumbo))), True)
        elif k == pygame.K_h:
            self.son(v.modelo.get("claxon", "claxon"), vol=0.8)
            self.enviar_evento("claxon")
            for p in self.personas:
                if p.tipo == "civil" and not p.muerto and p.dist(v.x, v.y) < 18 and p.estado == "pasea":
                    self.asustar(p, 4, "aparta", grito=0.15)
        elif k == pygame.K_r:
            self.son("radio_cambio", vol=0.5, cat="musica")
            if mayus:
                self.cfg["emisora"] = 0
            else:
                if self.app.radio.id_actual() == "usuario" and len(self.app.radio.pistas_usuario) > self.app.radio.pista_idx % max(1, len(self.app.radio.pistas_usuario)) + 1:
                    self.decir(self.app.radio.siguiente_pista(), True)       # dentro de «Mi música», R pasa de canción
                    return
                self.app.radio.pista_idx = 0
                self.cfg["emisora"] = (self.cfg["emisora"] + 1) % len(self.app.radio.emisoras)
            self.decir(self.app.radio.sintonizar(self.cfg["emisora"]), True)
        elif k == pygame.K_e:
            if not self.modo_asistido():
                v.rumbo = round(v.rumbo / 90.0) * 90 % 360
                self.decir(tr('Enderezas hacia el {cardinal}.').format(cardinal=(M.cardinal(v.rumbo))), True)
        elif k == pygame.K_j:
            self.alternar_trabajo()
        elif k == pygame.K_w:
            self.decir(tr('{int} kilómetros por hora.').format(int=(int(abs(v.vel) * 3.6))), True)
        elif k == pygame.K_a and not mayus and not (v.modelo.get("vuela") and self.vuelo_real()):
            self._a_pulsada = pygame.time.get_ticks()           # un toque corto abre los ajustes del piloto (lo mira conducir)
        elif k == pygame.K_y:
            self.alternar_piloto()

    def alternar_piloto(self):
        """Activa o desactiva el piloto del GPS y dice por qué no arranca, si no puede."""
        v = self.j.veh
        if v is None:
            return
        self.cfg["piloto_gps"] = not self.cfg["piloto_gps"]
        if not self.cfg["piloto_gps"]:
            self.decir(tr("Piloto del GPS desactivado."), True)
        elif v.modelo.get("barco") or self.mundo.tipo == "mar":
            self.decir(tr("Piloto del GPS activado, pero en el agua no conduce: solo en tierra."), True)
        elif v.modelo.get("vuela"):
            self.decir(tr("Piloto del GPS activado para cuando conduzcas en tierra. En el aire no lleva los mandos")
                       + (tr(": para eso está el piloto automático del vuelo.") if self.vuelo_real() else "."), True)
        elif not self.modo_asistido():
            self.decir(tr("Piloto del GPS activado, pero solo funciona en conducción asistida. Cámbiala en Opciones, Movimiento y conducción."), True)
        elif not self.gps:
            self.decir(tr("Piloto del GPS activado. Marca un destino en el GPS y el coche irá solo: acelera, frena, gira y para en los semáforos."), True)
        else:
            self.decir(tr('Piloto del GPS activado: el coche va solo hasta {nombre}. Con cualquier flecha o el espacio mandas tú.').format(nombre=(self.gps['nombre'])), True)

    def _mirar_toque_a(self):
        """Un toque corto de la A al volante (pulsar y soltar enseguida) abre los ajustes del piloto. Mantenerla sigue
        siendo cambiar al carril contrario, así que el menú se abre al soltarla, no al pulsarla."""
        t0 = getattr(self, "_a_pulsada", None)
        if t0 is None or pygame.K_a in self.app.teclas:
            return
        self._a_pulsada = None
        if pygame.time.get_ticks() - t0 < A_TOQUE:
            self.menu_piloto()

    def menu_piloto(self):
        """Los ajustes del piloto del GPS: activarlo y cómo conduce."""
        from .menus import Menu, Opcion

        def elegir(e):
            self.cfg["piloto_estilo"] = e
            self._piloto_prisa = False
            self.app.cerrar(menu)
            self.decir(tr('Piloto: {estilo}. {ayuda}').format(estilo=nombre_estilo(e), ayuda=ayuda_estilo(e)), True)

        def opciones():
            ops = [Opcion(lambda: tr("Piloto del GPS: activado") if self.cfg["piloto_gps"] else tr("Piloto del GPS: desactivado"),
                          self.alternar_piloto, ayuda=tr("Intro lo activa o lo desactiva, como la Y al volante."), callado=True)]
            for e in ESTILOS_PILOTO:
                ops.append(Opcion(lambda e=e: nombre_estilo(e) + (tr(", elegido") if self.cfg["piloto_estilo"] == e else ""),
                                  lambda e=e: elegir(e), ayuda=ayuda_estilo(e)))
            return ops

        menu = Menu(self.app, tr("Ajustes del piloto del GPS"), opciones,
                    intro=tr('Ahora conduce así: {estilo}').format(estilo=nombre_estilo(self.cfg["piloto_estilo"])))
        menu.i = 1 + ESTILOS_PILOTO.index(self.cfg["piloto_estilo"]) if self.cfg["piloto_estilo"] in ESTILOS_PILOTO else 0
        self.app.abrir(menu)

    def piloto_puesto(self):
        """El piloto del GPS está activado, o conduce tu chófer, que usa el mismo piloto."""
        return bool(self.cfg["piloto_gps"]) or self.chofer_conduce()

    def piloto_completo(self):
        """¿Conduce el coche solo? Con el piloto del GPS activado, en conducción asistida, en tierra y con un destino marcado."""
        v = self.j.veh
        return bool(self.piloto_puesto() and self.gps and v and self.modo_asistido() and self.mundo.tipo != "mar"
                    and not v.modelo.get("barco") and not v.modelo.get("vuela"))

    def _pilotar(self, v, dt, freno):
        """El piloto lleva los pedales: velocidad de ciudad, despacio al llegar y parado en rojo o con algo delante."""
        mo = v.modelo
        if getattr(v, "seco", False):                            # sin combustible no hay piloto que valga
            return
        dx, dy = self.gps["dest"]
        dist = math.hypot(dx - v.x, dy - v.y)
        # Con prisa (la sirena puesta, o una misión o un trabajo contra el reloj) el piloto corre más. Solo se salta los
        # semáforos con la sirena o en una misión: en un trabajo (el autobús, el taxi, el reparto) te costaría multas y
        # puntos del carné, así que espera en rojo como cualquiera, aunque vaya más deprisa.
        # El estilo elegido con la A manda sobre todo eso; con «Automático», lo de siempre.
        from .realismo import aj
        estilo = self.cfg["piloto_estilo"]
        limite = aj("limite_ciudad") / 3.6
        acel = 0.8                                               # cuánto pisa el acelerador, sobre lo que da el vehículo
        apurar = False                                           # pasa los semáforos que están a punto de cambiar
        quien = self.chofer["nombre"].split(",")[0] if self.chofer_conduce() else tr("El piloto")
        if estilo == "tranquilo":
            salta, objetivo, acel = False, min(mo["vel_max"] * 0.45, 8.5), 0.45
        elif estilo == "normal":
            salta, objetivo = False, min(mo["vel_max"] * 0.6, 14.0, limite)
        elif estilo == "prisa_legal":                            # por encima del límite, pero sin llegar a lo que se multa
            salta, acel, apurar = False, 1.0, True
            objetivo = min(mo["vel_max"] * 0.85, limite * (1.0 + aj("margen_velocidad") / 200.0))
        elif estilo == "prisa":
            salta, objetivo, acel, apurar = True, mo["vel_max"] * 0.9, 1.0, True        # lo que da el vehículo, sin tope de ciudad
        elif estilo == "muy_prisa":
            salta, objetivo, acel, apurar = True, mo["vel_max"], 1.0, True              # a fondo: la frenada automática sigue mirando delante
        else:
            salta = bool(self.sirena_propia) or bool(self.mision and self.mision.get("limite") is not None)
            prisa = salta or bool(self.trabajo and self.trabajo.get("limite") is not None)
            objetivo = min(mo["vel_max"] * 0.85, 21.0) if prisa else min(mo["vel_max"] * 0.6, 14.0)
            if prisa and not getattr(self, "_piloto_prisa", False):
                self.decir(tr('Vas con prisa: {v} corre más').format(v=(tr('el piloto') if quien in ('El piloto', tr('El piloto')) else quien)) + (tr(" y no espera en los semáforos.") if salta else tr(", pero espera en los semáforos.")))
            self._piloto_prisa = prisa
        ruta = self.gps.get("ruta") or []
        if ruta and self.modo_asistido():                        # el destino ha quedado atrás (te has pasado, o el que persigues ha girado): media vuelta
            px, py = ruta[0]
            lejos = math.hypot(px - v.x, py - v.y)
            if lejos > 8 and abs(M.norm180(M.rumbo_a(px - v.x, py - v.y) - v.rumbo)) > 120:
                if v.vel > 6:
                    v.vel = max(0.0, v.vel - freno * dt)
                    return
                v.dir = (v.dir + 2) % 4
                v.rumbo = v.dir * 90.0
                v.aviso_cruce = None
                if self.t - getattr(self, "t_piloto_vuelta", -99) > 5:
                    self.t_piloto_vuelta = self.t
                    self.decir(tr('{quien} da media vuelta. Ahora vas hacia el {v}.').format(quien=(quien), v=(M.NOMBRE_DIR[v.dir])))
                return
        if self.gps.get("sigue") is None:                        # a un sitio se llega y se para; a quien persigues, no
            radio = self.gps.get("radio") or 16
            if dist < 45:
                objetivo = min(objetivo, max(2.0, dist * 0.3))
            if dist <= radio * 0.8:
                objetivo = 0.0                                   # ha llegado: se detiene, para que puedas entrar o entregar
                if v.vel > 0.5:
                    self._piloto_parado = False
                elif not getattr(self, "_piloto_parado", False):
                    self._piloto_parado = True
                    if self.chofer_conduce():
                        self.son("llegada", cat="interfaz", vol=0.6)
                        self._chofer_dice("chofer_frases_llegada", tr('{nombre}. Con F te bajas, y te espera.').format(nombre=(self.gps['nombre'])))
                    else:
                        self.decir(tr('El piloto se detiene: has llegado a {nombre}.').format(nombre=(self.gps['nombre'])))
            else:
                self._piloto_parado = False
        hasta_linea = None if salta else self._piloto_semaforo(v, freno, apurar)
        if hasta_linea is not None:
            # frena para quedarse en la línea, sea cual sea el vehículo: un autobús frena peor que un turismo y antes se metía en el cruce
            objetivo = min(objetivo, math.sqrt(2.0 * max(1.0, freno * 0.8) * max(0.0, hasta_linea - 0.6)))
            if objetivo < 0.8:
                objetivo = 0.0
            if self.t - getattr(self, "t_aviso_rojo", -99) > 20:
                self.t_aviso_rojo = self.t
                self.decir(tr('Semáforo en rojo. {quien} espera.').format(quien=(quien)))
        if v.vel < objetivo:
            v.vel = min(objetivo, v.vel + mo["acel"] * acel * dt)
        elif v.vel > objetivo:
            v.vel = max(objetivo, v.vel - freno * dt)

    # --------------------------------------------------------- conducir
    def conducir(self, dt):
        j = self.j
        v = j.veh
        t = self.app.teclas
        self._mirar_toque_a()                           # un toque de la A: los ajustes del piloto
        if self.chofer_conduce():                       # conduce tu chófer: los pedales y el volante son suyos
            t = frozenset()
        mo = v.modelo
        if mo.get("vuela") and self.vuelo_real():       # volar de verdad: despegue, altura, combustible y aterrizaje (vuelo.py)
            t = self.vuelo_controles(v, dt, t)
        from . import sistemas                          # las mejoras del taller cambian cómo va el vehículo
        freno = mo["freno"] * (sistemas.factor_lluvia(v) if self.lluvia else 1.0) * sistemas.factor_frenada(v) * self.factor_averia_frenos(v)
        con_motor = self.gastar_combustible(v, dt)
        self.rodar(v, dt)
        self.vigilar_velocidad(v, dt)
        if v.ardiendo >= 0 or not con_motor:
            v.vel -= math.copysign(min(abs(v.vel), (6 if v.ardiendo >= 0 else 3.5) * dt), v.vel)
            if not con_motor and pygame.K_UP in t and self.t - getattr(self, "t_aviso_seco", -99) > 6:
                self.t_aviso_seco = self.t
                self.son("motor_seco", cat="interfaz")
                self.decir(tr("El motor no arranca: no queda combustible."))
        elif pygame.K_UP in t:
            v.vel += mo["acel"] * sistemas.factor_aceleracion(v) * dt * (2.5 if v.vel < 0 else 1.0)
        elif pygame.K_DOWN in t:
            if v.vel > 0.3:
                v.vel = max(0.0, v.vel - freno * dt)
            else:
                v.vel = max(-6.0, v.vel - 4 * dt)
        elif self.piloto_completo() and pygame.K_SPACE not in t:
            self._pilotando = True
            self._pilotar(v, dt, freno)
        elif (getattr(self, "_pilotando", False) or self.chofer_conduce()) and self.piloto_puesto() and not self.gps and v.vel > 0:
            v.vel = max(0.0, v.vel - freno * dt)                 # el piloto ha llegado: no suelta el coche rodando, lo para
        else:
            v.vel -= math.copysign(min(abs(v.vel), 1.8 * dt), v.vel)
        if getattr(self, "_pilotando", False) and (v.vel <= 0 or pygame.K_UP in t or pygame.K_DOWN in t) and not self.piloto_completo():
            self._pilotando = False
        if pygame.K_SPACE in t and abs(v.vel) > 0:
            if abs(v.vel) > 9 and self.t - getattr(self, "t_frenazo", -9) > 1.2:
                self.t_frenazo = self.t
                self.son("frenazo", vol=0.5)
            v.vel -= math.copysign(min(abs(v.vel), freno * 1.7 * dt), v.vel)
        vmax = mo["vel_max"] * self.factor_averia_velocidad(v) * sistemas.factor_velocidad(v) * (0.55 + 0.45 * min(1.0, v.salud / (0.5 * v.salud_max))) * (1 + 0.01 * self.nivel("conduccion"))
        v.vel = min(v.vel, vmax)
        x0, y0 = v.x, v.y
        if self.modo_asistido():
            lat = -6.0 if pygame.K_a in t else 2.2 if pygame.K_d in t else 0.0
            if (self.cfg["frenada_auto"] or self.piloto_completo()) and v.vel > 0:
                self._frenada_auto(v, dt, freno)
            self._aviso_cruce(v)
            self._mover_via(v, dt, lat, self._decidir_jugador)
            if self.mundo.via_cercana(v.x, v.y)[2] > M.ACERA + 2:
                self.libre_temp = True
        else:
            self._conducir_libre(v, dt, t)
        j.stats["metros_coche"] += math.hypot(v.x - x0, v.y - y0)
        self.ganar_xp("conduccion", math.hypot(v.x - x0, v.y - y0) / 60.0)
        if v.canal:
            carga = 0.12 if pygame.K_UP in t else 0.0
            v.canal.tono(mo["tono"] * sistemas.factor_tono(v) * (0.6 + carga + 1.3 * abs(v.vel) / mo["vel_max"]))
        if getattr(self, "rodadura", None):
            rv, rt = sistemas.factor_rodadura(v)                 # unos neumáticos mejores ruedan más bajo y más graves
            self.rodadura.volumen(min(0.5, abs(v.vel) / 50.0) * rv)
            self.rodadura.tono((0.7 + abs(v.vel) / 40.0) * rt)
        self._choques_jugador(v)
        self._sonar(v, dt)
        if (pygame.K_LCTRL in t or pygame.K_RCTRL in t) and self.arma().get("automatica"):
            self.atacar()

    def _frenada_auto(self, v, dt, freno):
        """Asistente: frena solo para no embestir al vehículo que va delante en tu carril."""
        dx, dy = M.DIRS[v.dir]
        mejor = None
        for o in self.vehiculos:
            # las patrullas que te persiguen no cuentan; las que van de ronda son un coche más, y se frena tras ellas
            if o is v or o.muerto or o.tag == "objetivo" or o.ia == "huida" or (o.ia == "policia" and self.j.estrellas > 0) or getattr(o, "volando", False):
                continue
            a = (o.x - v.x) * dx + (o.y - v.y) * dy
            lat = abs((o.x - v.x) * dy - (o.y - v.y) * dx)
            if 0 < a < 40 and lat < 2.3 and (mejor is None or a < mejor[0]):
                vel_o = o.vel * (1 if o.ia not in ("aparcado", None) and o.dir == v.dir else 0)
                mejor = (a, max(0.0, vel_o))
        if mejor is None:
            self.t_atasco = 0.0
            return
        a, vel_o = mejor
        hueco = a - 5.5
        seguro = vel_o + max(0.0, hueco) * 0.9
        if v.vel > seguro:
            v.vel = max(seguro if hueco > 0 else 0.0, v.vel - freno * 1.6 * dt)
        if v.vel < 0.5 and vel_o < 0.5:
            self.t_atasco = getattr(self, "t_atasco", 0.0) + dt
            if self.t_atasco > 2.5 and self.t - getattr(self, "t_aviso_atasco", -99) > 25:
                self.t_aviso_atasco = self.t
                self.decir(tr("Tráfico detenido delante. Espera, o mantén pulsada la A para adelantar por la izquierda."))
        else:
            self.t_atasco = 0.0

    def _aviso_cruce(self, v):
        m = self.mundo
        dx, dy = M.DIRS[v.dir]
        a = v.y if dx == 0 else v.x
        s = dy if dx == 0 else dx
        idx = math.floor(a / M.B) + 1 if s > 0 else math.ceil(a / M.B) - 1
        tope = m.NY if dx == 0 else m.NX
        if not (0 <= idx < tope) or v.vel <= 0.5:
            return
        d = abs(idx * M.B - a)
        clave = (v.dir, idx)
        if d < max(32.0, v.vel * 3.2) and v.aviso_cruce != clave:
            v.aviso_cruce = clave
            if v.giro == 0 and self.piloto_puesto():
                g = self.giro_gps()
                if g in (-1, 1):
                    v.giro = g
            if self.cfg["anunciar_cruces"]:
                via = m.calles[idx] if dx == 0 else m.avenidas[idx]
                i, jj = (m._idx(v.x, m.NX), idx) if dx == 0 else (idx, m._idx(v.y, m.NY))
                txt = tr('Cruce con {via}').format(via=(via))
                if v.giro:
                    txt += tr(", girarás a la ") + ("derecha" if v.giro > 0 else "izquierda")
                elif not m.dir_valida(i, jj, v.dir):
                    txt += tr(", fin de la vía")
                self.son("cruce", cat="interfaz", vol=0.5)
                self.decir(txt + ".")

    def _conducir_libre(self, v, dt, t):
        giro = (1 if pygame.K_RIGHT in t else 0) - (1 if pygame.K_LEFT in t else 0)
        mar = self.mundo.tipo == "mar"
        if giro:
            antes = M.cardinal(v.rumbo)
            v.rumbo = (v.rumbo + giro * (55 if mar else 80) * dt * min(1.0, abs(v.vel) / 5.0 + (0.35 if mar else 0)) * (1 if v.vel >= 0 else -1)) % 360
            if M.cardinal(v.rumbo) != antes:
                self.decir(M.cardinal(v.rumbo).capitalize(), True)
        rad = math.radians(v.rumbo)
        sx, sy = math.sin(rad), math.cos(rad)
        nx, ny = v.x + sx * v.vel * dt, v.y + sy * v.vel * dt
        s = self.mundo.superficie(nx, ny)
        if v.modelo.get("vuela"):
            if s == "fuera" or (mar and not (0 <= nx <= self.mundo.ancho and 0 <= ny <= self.mundo.alto)):
                if self.vuelo_real():                            # el borde de la localidad: de aquí sale la travesía a otra
                    self.vuelo_borde(v)
                    return
                v.vel = 0.0
                self.decir(tr("Fin del mapa. Da la vuelta, o usa un helipuerto para volar a otra localidad."))
                return
            v.x, v.y = nx, ny
            v.dir = M.dir_de_rumbo(v.rumbo)
            return
        if mar:
            if s != "agua":
                imp = abs(v.vel)
                if imp > 2:
                    self.son("choque" if imp > 8 else "choque_leve")
                    self.danar_vehiculo(v, imp * 1.2 * self._golpe(v))
                    self.decir(tr("¡Encallas en la arena de una isla!") if s == "arena" else tr("Fin del mapa: aquí empieza el océano abierto. Da la vuelta."))
                v.vel = -v.vel * 0.2
                return
            v.x, v.y = nx, ny
            v.dir = M.dir_de_rumbo(v.rumbo)
            return
        if s in ("pared", "fuera"):
            imp = abs(v.vel)
            if imp > 2:
                fg = self._golpe(v)                              # con la suspensión reforzada el golpe hace menos daño, y suena más seco y más bajo
                self.son("choque" if imp > 8 else "choque_leve", vol=0.5 + 0.5 * fg, tono=0.8 + 0.2 * fg)
                self.danar_vehiculo(v, imp * 1.3 * fg)
                if imp > 12:
                    self.danar_jugador(imp * 0.6 * fg, None)
                self.app.vibrar(min(1.0, imp / 12.0), 0.6, 350)
                self.decir(tr("¡Te estrellas contra una pared!") if s == "pared" else tr("Fin de la ciudad."))
            v.vel = -v.vel * 0.25
            return
        v.x, v.y = nx, ny
        if s in ("hierba", "arena") and v.modelo["id"] != "todoterreno":
            v.vel *= max(0.0, 1.0 - 0.8 * dt)
        v.dir = M.dir_de_rumbo(v.rumbo)
        # aviso de bordillo: suena por el lado en el que se acaba la calzada
        self.t_bordillo -= dt
        if self.t_bordillo <= 0 and abs(v.vel) > 2:
            self.t_bordillo = 0.3
            for lado in (-1, 1):
                lx = v.x + sx * 4 + sy * 3.5 * lado
                ly = v.y + sy * 4 - sx * 3.5 * lado
                if self.mundo.superficie(lx, ly) != "calzada":
                    self.son("bordillo", pan=0.85 * lado, vol=0.6, cat="interfaz")
                    self.app.vibrar(0.5 if lado < 0 else 0.0, 0.0 if lado < 0 else 0.5, 120)
        if self.libre_temp and s == "calzada" and self.cfg["conduccion"] == "asistida":
            t_, idx, dist = self.mundo.via_cercana(v.x, v.y)
            eje = 90 if t_ == "H" else 0
            desv = abs(M.norm180(v.rumbo - eje))
            if min(desv, 180 - desv) < 35 and dist < M.CALZADA:
                self.libre_temp = False
                self._alinear(v)
                v.aviso_cruce = None
                self.decir(tr('De nuevo en {nombre_via}. Conducción asistida.').format(nombre_via=(self.mundo.nombre_via(t_, idx))))

    def _sonar(self, v, dt):
        """Sensor de proximidad: pita más rápido cuanto más cerca está el obstáculo de delante."""
        if not self.cfg["sonar"] or abs(v.vel) < 1 or v.modelo.get("vuela"):
            return
        self.t_sonar -= dt
        if self.t_sonar > 0:
            return
        rad = math.radians(v.rumbo)
        sx, sy = math.sin(rad), math.cos(rad)
        mejor = None
        for o in self.vehiculos:
            if o is v or o.muerto or getattr(o, "volando", False):
                continue
            a = (o.x - v.x) * sx + (o.y - v.y) * sy
            lat = (o.x - v.x) * sy - (o.y - v.y) * sx
            if 0 < a < 45 and abs(lat) < 2.6 and (mejor is None or a < mejor[0]):
                mejor = (a, lat)
        if mejor is None:
            self.t_sonar = 0.15
            return
        self.son("sonar", pan=max(-1, min(1, mejor[1] / 2.6)), vol=0.5, tono=1.0 + (45 - mejor[0]) / 90.0, cat="interfaz")
        self.t_sonar = max(0.08, mejor[0] / 45.0 * 0.8)

    def _choques_jugador(self, v):
        if v.t_choque > self.t or v.modelo.get("vuela"):
            return
        for o in self.vehiculos:
            if o is v or o.muerto or getattr(o, "volando", False):
                continue
            if abs(o.x - v.x) < 4 and abs(o.y - v.y) < 4 and o.dist(v.x, v.y) < 3.4:
                rad = math.radians(v.rumbo)
                rel = v.vel - (o.vel * math.cos(math.radians(o.rumbo - v.rumbo)) if o.ia not in ("aparcado", None) else 0.0)
                imp = abs(rel)
                if imp < 1.5:
                    continue
                v.t_choque = self.t + 0.6
                fg = self._golpe(v)
                self.son("choque" if imp > 8 else "choque_leve", xy=(o.x, o.y), ref=10, vol=0.5 + 0.5 * fg, tono=0.8 + 0.2 * fg)
                self.app.vibrar(min(1.0, imp / 14.0), 0.5, 300)
                self.danar_vehiculo(v, imp * (0.4 if o.tag == "objetivo" else 0.6) * (1 - 0.03 * self.nivel("conduccion")) * fg)
                self.danar_vehiculo(o, imp * (2.2 if o.tag == "objetivo" else 1.4))
                if imp > 14:
                    self.danar_jugador(imp * 0.4 * fg, None)
                atras = -1 if v.vel > 0 else 1
                v.x += math.sin(rad) * 1.5 * atras
                v.y += math.cos(rad) * 1.5 * atras
                v.vel *= 0.35
                if o.ia in ("trafico", "huida", "policia"):
                    o.vel = max(o.vel, min(o.vel + imp * 0.4, 30)) if o.ia == "huida" else o.vel * 0.6
                if o.ia == "trafico":
                    self.son(o.modelo.get("claxon", "claxon"), xy=(o.x, o.y))
                if o.ia == "policia":
                    self.delito(1, None, siempre=True)
                return
        if abs(v.vel) > 3:
            for p in self.personas:
                if not p.muerto and p.tipo not in ("aliado", "perro") and abs(p.x - v.x) < 3 and abs(p.y - v.y) < 3 and p.dist(v.x, v.y) < 2.3:
                    self.son("golpe", xy=(p.x, p.y))
                    self.danar_persona(p, abs(v.vel) * 8, atropello=True)
                    v.vel *= 0.8

    # ------------------------------------------------- vehículos del mundo
    def _obstaculo(self, v, alcance=13.0):
        dx, dy = M.DIRS[v.dir]
        j = self.j
        px, py = self.pos()
        cand = [(px, py)] if (j.veh or self.mundo.superficie(px, py) == "calzada") else []
        for o in self.vehiculos:
            if o is not v and o is not j.veh and o.ia != "aparcado" and not o.muerto and not getattr(o, "volando", False):
                cand.append((o.x, o.y))
        for cx, cy in cand:
            a = (cx - v.x) * dx + (cy - v.y) * dy
            lat = abs((cx - v.x) * dy - (cy - v.y) * dx)
            if 0.5 < a < alcance and lat < 2.4:
                return True
        return False

    def _piloto_semaforo(self, v, freno, apurar=False):
        """El piloto ante el próximo cruce: los metros hasta la línea de parada si tiene que parar, o None si puede pasar.
        Para si está en rojo, y también si se pondrá en rojo antes de cruzarlo y le da para frenar (en el juego no hay
        ámbar). Mira tan lejos como haga falta para frenar a tiempo con lo que frena ese vehículo."""
        m = self.mundo
        dx, dy = M.DIRS[v.dir]
        a = v.y if dx == 0 else v.x
        s = dy if dx == 0 else dx
        idx = math.floor(a / M.B) + 1 if s > 0 else math.ceil(a / M.B) - 1
        if not (0 <= idx < (m.NY if dx == 0 else m.NX)):
            return None
        d = abs(idx * M.B - a)
        linea = d - 8.0                                          # la línea de parada, antes de la calzada que se cruza
        vel = max(0.0, v.vel)
        decel = max(1.0, freno * 0.8)
        parar = vel * vel / (2.0 * decel)
        if linea < -0.5 or d > max(17.0, parar + 12.0):
            return None
        if dx == 0:
            verde = m.verde_vertical(m._idx(v.x, m.NX), idx, self.t)
        else:
            verde = not m.verde_vertical(idx, m._idx(v.y, m.NY), self.t)
        if not verde:
            return max(0.0, linea) if linea > 0.5 or vel < 3 else None      # ya en la línea y lanzado: mejor despejar el cruce
        if vel < 1 or linea <= parar + 1.0 or apurar:
            return None                                          # verde y sin sitio para parar con suavidad (o con prisa): pasa
        falta = 14.0 - ((self.t + getattr(m, "desfase_luces", 0.0)) % 14.0)
        if (d + 9.0) / vel > falta:                              # se pondrá en rojo antes de cruzarlo: se queda
            return linea
        return None

    def _semaforo_rojo(self, v):
        m = self.mundo
        dx, dy = M.DIRS[v.dir]
        a = v.y if dx == 0 else v.x
        s = dy if dx == 0 else dx
        idx = math.floor(a / M.B) + 1 if s > 0 else math.ceil(a / M.B) - 1
        d = abs(idx * M.B - a)
        if not (7.5 < d < 17):
            return False
        if dx == 0:
            return 0 <= idx < m.NY and not m.verde_vertical(m._idx(v.x, m.NX), idx, self.t)
        return 0 <= idx < m.NX and m.verde_vertical(idx, m._idx(v.y, m.NY), self.t)

    def actualizar_vehiculos(self, dt):
        j = self.j
        px, py = self.pos()
        for v in list(self.vehiculos):
            if v.muerto:
                continue
            if v.ardiendo >= 0:
                v.ardiendo -= dt
                if v.fuego:
                    v.fuego.mover(v.x, v.y)
                if v.ardiendo <= 0:
                    self.explotar(v)
                    continue
            if v.alarma is not None:
                v.t_alarma = getattr(v, "t_alarma", 0) - dt
                v.alarma.mover(v.x, v.y)
                if v.t_alarma <= 0:
                    v.alarma.parar()
                    v.alarma = None
            if v is j.veh:
                continue
            d = v.dist(px, py)
            if v.ia in ("aparcado", None):
                if v.sirena:
                    v.sirena.mover(v.x, v.y)
                continue
            if v.ia == "heli_policia":                           # el helicóptero de la policía: lo mueve calle.py
                continue
            if v.ia == "servidor":                               # tráfico común: lo mueve el servidor
                self.sv_trafico_paso(v, d, dt)
                continue
            if v.ia == "barco":
                tx, ty = v.destino
                if math.hypot(tx - v.x, ty - v.y) < 30:
                    v.destino = self.mundo.punto_libre(random.uniform(0, self.mundo.ancho), random.uniform(0, self.mundo.alto))
                desv = M.norm180(M.rumbo_a(tx - v.x, ty - v.y) - v.rumbo)
                v.rumbo = (v.rumbo + max(-30 * dt, min(30 * dt, desv))) % 360
                v.vel += max(-2 * dt, min(2 * dt, v.vel_obj - v.vel))
                rad = math.radians(v.rumbo)
                nx, ny = v.x + math.sin(rad) * v.vel * dt, v.y + math.cos(rad) * v.vel * dt
                if self.mundo.transitable(nx, ny):
                    v.x, v.y = nx, ny
                else:
                    v.rumbo = (v.rumbo + 90) % 360
                if d < 220:
                    if v.canal is None:
                        v.canal = self.son(v.modelo["motor"], bucle=True, xy=(v.x, v.y), ref=10, maxd=220, vol=0.8)
                        v.canal.alto = 35.0 if v.modelo.get("vuela") else 0.0          # un helicóptero suena por encima
                    v.canal.mover(v.x, v.y)
                    v.canal.tono(v.modelo["tono"] * (0.7 + v.vel / 20.0))
                elif v.canal:
                    v.canal.parar()
                    v.canal = None
                continue
            obj = v.vel_obj
            decidir = self._decidir_trafico
            if v.ardiendo >= 0:
                obj = 0.0
            elif v.ia == "trafico":
                if self._obstaculo(v) or self._semaforo_rojo(v):
                    obj = 0.0
                    v.t_parado += dt
                    if v.t_parado > 3 and self.t > v.t_claxon and d < 30 and self._obstaculo(v, 9):
                        v.t_claxon = self.t + random.uniform(3, 6)
                        self.son(v.modelo.get("claxon", "claxon"), xy=(v.x, v.y), ref=8)
                else:
                    v.t_parado = 0.0
            elif v.ia == "huida":
                decidir = self._decidir_huida
                obj = v.vel_obj * (0.6 + 0.4 * max(0.0, v.salud / v.salud_max))
                if d > 160:
                    obj *= 0.55        # espera un poco al jugador para que la persecución no se pierda
            elif v.ia == "policia":
                obj, decidir = self._ia_patrulla(v, d, dt)
            elif v.ia == "enemigos":
                obj, decidir = self._ia_enemigos(v, d, dt)
            elif v.ia == "chofer":
                obj, decidir = self._ia_chofer(v, d, dt)
                if v.ia != "chofer":                             # acaba de llegar: ya está parado a tu lado
                    continue
            elif v.ia == "ambulancia":
                obj, decidir = self._ia_ambulancia(v, d, dt)
            v.vel += max(-v.modelo["freno"] * dt, min(v.modelo["acel"] * dt, obj - v.vel))
            if v.vel > 0.05:
                self._mover_via(v, dt, getattr(v, "lat_obj", 0.0), decidir)
            if d < 100:
                self._motor(v, False)
                v.canal.mover(v.x, v.y)
                v.canal.tono(v.modelo["tono"] * (0.6 + 1.3 * abs(v.vel) / v.modelo["vel_max"]))
            elif v.canal:
                v.canal.parar()
                v.canal = None
            if v.sirena:
                v.sirena.mover(v.x, v.y)
            # atropello del jugador a pie (quien va de pasajero con otro jugador no está en la calzada)
            if not j.veh and v.vel > 3 and d < 2.4 and self.t > v.t_choque and v.ia != "ambulancia" and getattr(self, "pasajero", None) is None:
                v.t_choque = self.t + 1.5
                self.son("golpe")
                self.danar_jugador(v.vel * 2.2, (v.x, v.y))
                self.decir(tr("¡Te ha atropellado un vehículo!"))
                v.vel *= 0.3

    def _ia_patrulla(self, v, d, dt):
        j = self.j
        if j.estrellas == 0:                                     # no te buscan: hace su ronda, o acude a una pelea (calle.py)
            return self.patrulla_sin_busqueda(v, d, dt)
        v.auxilio = None
        if v.sirena is None:
            # Con varias patrullas, cada sirena suena más floja: juntas no deben tapar ni saturar todo lo demás.
            otras = sum(1 for o in self.vehiculos if o is not v and o.sirena is not None)
            v.sirena = self.son("sirena", bucle=True, xy=(v.x, v.y), ref=14, maxd=260, vol=0.8 / (1 + 0.6 * otras))
        if v.desplegado:
            return 0.0, self._decidir_policia
        vel_j = abs(j.veh.vel) if j.veh else 0.0
        px, py = self.pos()
        if d < 14 and vel_j < 4:
            if v.vel < 1.0:
                v.desplegado = True
                v.ocupado = False
                e = getattr(v, "agentes", None) or G.agentes_nivel(j.estrellas)      # qué agentes trae: lo dice la tabla de la policía de los datos
                for k in range(e["ocupantes"]):
                    x, y = self.mundo.punto_libre(v.x + random.uniform(-3, 3), v.y + random.uniform(-3, 3))
                    f = G.enemigo({"clase": e["clase"]}) if k and e["clase"] else e      # cada agente, su arma, si el tipo trae varias
                    p = G.vestir(Persona("policia", x, y, f["nombre"]), f)
                    p.hostil = True
                    p.estado = "ataca"
                    p.coche = v
                    self.personas.append(p)
                self.son("puerta_coche", xy=(v.x, v.y))
            return 0.0, self._decidir_policia
        dx, dy = M.DIRS[v.dir]
        a = (px - v.x) * dx + (py - v.y) * dy
        lat = abs((px - v.x) * dy - (py - v.y) * dx)
        if a < -15 and lat < 20 and self.t > v.t_giro:
            v.t_giro = self.t + 3
            v.dir = (v.dir + 2) % 4
        if j.veh and d < 4.6 and self.t > v.t_choque and not j.veh.modelo.get("vuela"):
            v.t_choque = self.t + 2.5
            self.son("choque_leve")
            self.danar_vehiculo(j.veh, 7)
            j.veh.vel *= 0.75
            v.vel *= 0.5
        lim = v.modelo["vel_max"] * (0.62 + 0.06 * j.estrellas)
        if d < 30:
            lim = min(lim, max(8.0, vel_j + 3))
        return lim, self._decidir_policia

    # ------------------------------------------------- enemigos que llegan en un vehículo
    def llegar_en_vehiculo(self, modelo_id, gente, x=None, y=None):
        """Un grupo de enemigos llega en un vehículo: sale a unos doscientos metros, viene por la calle hacia ti con la
        misma conducción que una patrulla, para cerca y se bajan. «gente» son las personas ya creadas, que no están en la
        calle hasta que se bajan. Devuelve el vehículo, o None si aquí no puede venir ninguno (en el mar, o un modelo
        que no existe o no es de tierra): entonces quien llama los pone a pie."""
        mo = self.modelos.get(modelo_id)
        if not gente or mo is None or mo.get("barco") or mo.get("vuela"):
            return None
        px, py = self.pos() if x is None else (x, y)
        pos = self._punto_llegada(px, py)
        if pos is None:
            return None
        v = Vehiculo(mo, pos[0], pos[1], pos[2], "enemigos")
        v.nombre = tr('{nombre} con {len} enemigos').format(nombre=(mo['nombre']), len=(len(gente))) if len(gente) > 1 else tr('{nombre} de {nombre2}').format(nombre=(mo['nombre']), nombre2=(gente[0].nombre))
        v.ocupado = v.hostil = True
        v.vel = 11.0
        v.tag = "enemigos"
        v.pasajeros = list(gente)
        v.t_llegada = self.t + 50.0                              # si para entonces no te ha alcanzado, se bajan donde estén
        for q in gente:
            q.x, q.y = v.x, v.y
        self.vehiculos.append(v)
        self.son("frenazo", xy=(v.x, v.y), ref=30, maxd=320, vol=0.6)      # se le oye arrancar derrapando, a lo lejos
        return v

    def bajar_enemigos(self, v):
        """El vehículo de los enemigos ha llegado: se bajan y van a por ti. El vehículo se queda ahí, vacío."""
        gente = [q for q in getattr(v, "pasajeros", []) if not q.muerto]
        v.pasajeros = []
        v.desplegado, v.ocupado, v.hostil, v.tag, v.ia, v.vel = True, False, False, None, "aparcado", 0.0
        if v.canal:
            v.canal.parar()
            v.canal = None
        for q in gente:
            q.x, q.y = self.mundo.punto_libre(v.x + random.uniform(-3, 3), v.y + random.uniform(-3, 3))
            q.t_disparo = random.uniform(1.2, 2.4)
            self.personas.append(q)
        if self.objetivo is v:
            self.objetivo = None
        if not gente:
            return
        self.son("puerta_coche", xy=(v.x, v.y))
        self.decir(tr('{v} de {nombre}. {situar}. Pulsa Q para fijar al más cercano.').format(v=(tr('Se baja uno') if len(gente) == 1 else tr('Se bajan {len}').format(len=(len(gente)))), nombre=(v.modelo['nombre']), situar=(self.situar(v.x, v.y, tr('Está')))))
        if self.cfg["punteria"] == "completa":
            self.fijar(callar=True)

    def _ia_enemigos(self, v, d, dt):
        """Un vehículo con enemigos dentro: viene a por ti como una patrulla, sin sirena; al alcanzarte, para y se bajan."""
        j = self.j
        vel_j = abs(j.veh.vel) if j.veh else 0.0
        if (d < 16 and vel_j < 4) or self.t > getattr(v, "t_llegada", 1e18):
            if v.vel < 1.0:
                self.bajar_enemigos(v)
            return 0.0, self._decidir_policia
        px, py = self.pos()
        dx, dy = M.DIRS[v.dir]
        a = (px - v.x) * dx + (py - v.y) * dy
        lat = abs((px - v.x) * dy - (py - v.y) * dx)
        if a < -15 and lat < 20 and self.t > v.t_giro:           # te ha pasado de largo: da la vuelta
            v.t_giro = self.t + 3
            v.dir = (v.dir + 2) % 4
        if j.veh and d < 4.6 and self.t > v.t_choque and not j.veh.modelo.get("vuela"):      # te embiste
            v.t_choque = self.t + 2.5
            self.son("choque_leve")
            self.danar_vehiculo(j.veh, 6)
            j.veh.vel *= 0.8
            v.vel *= 0.5
        lim = v.modelo["vel_max"] * 0.7
        if d < 30:
            lim = min(lim, max(8.0, vel_j + 3))
        return lim, self._decidir_policia

    def crear_vehiculo(self, modelo_id, x, y, d, ia="aparcado", nombre=None, tag=None):
        v = Vehiculo(self.modelos.get(modelo_id, self.modelos["utilitario"]), x, y, d, ia)
        if nombre:
            v.nombre = nombre
        v.tag = tag
        self.vehiculos.append(v)
        return v
