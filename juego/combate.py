"""Combate, daños, peatones, nivel de búsqueda y policía."""
from .i18n import tr
import math
import random

import pygame

from . import gente as G
from . import mundo as M
from .entidades import Objeto, Persona, Vehiculo
from .menus import Dialogo

UMBRAL = [1, 4, 8, 13, 20]
# Cuántas patrullas persiguen como mucho con cada nivel de búsqueda, y cada cuántos segundos llega una nueva.
PATRULLAS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4}
RITMO_PATRULLAS = {1: 9.0, 2: 7.0, 3: 6.0, 4: 5.0, 5: 4.0}


RIVAL_CAE = (tr("cae a la lona."), tr("se va al suelo y no se levanta."), tr("besa la lona."), tr("se desploma: fuera de combate."), tr("dobla las rodillas y cae."))

def _num(x):
    """Un número como se dice: 0,4 y no 0.4; 35 y no 35.0."""
    return f"{float(x):.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _grado(valor, tramos, ultimo):
    return next((nombre for tope, nombre in tramos if valor < tope), ultimo)


def ficha_corta(a):
    """Lo justo para comparar armas de un vistazo, en la propia opción del menú."""
    cuerpo = a.get("tipo") == "cuerpo"
    return tr('daño {_num}, ').format(_num=(_num(a.get('dano', 0)))) + (tr("cuerpo a cuerpo") if cuerpo else tr('alcance {_num} metros').format(_num=(_num(a.get('alcance', 0)))))


def ficha_arma(a):
    """Daño, alcance, cadencia y precisión de un arma, con palabras y con cifras. Sale de los datos del arma, así que vale para las de los mods."""
    dano, alcance, cad, prec = float(a.get("dano", 0)), float(a.get("alcance", 0)), float(a.get("cadencia", 1) or 1), float(a.get("precision", 1))
    tipo = a.get("tipo")
    golpe = tr("por golpe") if tipo == "cuerpo" else tr("por explosión, en el centro") if tipo == "explosivo" else tr("por bala")
    partes = [tr('Daño {_grado}: {_num} puntos {golpe}; un peatón aguanta 50 y tú, 100').format(_grado=(_grado(dano, ((20, 'bajo'), (40, 'medio'), (70, 'alto')), tr('muy alto'))), _num=(_num(dano)), golpe=(golpe))]
    if tipo == "cuerpo":
        partes.append(tr('Alcance: cuerpo a cuerpo, {_num} metros').format(_num=(_num(alcance))))
    else:
        partes.append(tr('Alcance {_grado}: {_num} metros').format(_grado=(_grado(alcance, ((25, 'corto'), (50, 'medio')), 'largo')), _num=(_num(alcance))))
    if tipo == "explosivo" and a.get("radio"):
        partes.append(tr('La explosión alcanza {_num} metros alrededor').format(_num=(_num(a['radio']))))
    que = "golpe" if tipo == "cuerpo" else "lanzamiento" if tipo == "explosivo" else "disparo"
    ritmo = _grado(cad, ((0.2, tr("muy rápida")), (0.5, tr("rápida")), (0.9, tr("media"))), tr("lenta"))
    if cad < 0.34:
        partes.append(tr('Cadencia {ritmo}: unos {int} {que}s por segundo').format(ritmo=(ritmo), int=(int(round(1 / cad))), que=(que)) + (tr(", automática: dispara mientras mantienes pulsado") if a.get("automatica") else ""))
    else:
        partes.append(tr('Cadencia {ritmo}: un {que} cada {v}').format(ritmo=(ritmo), que=(que), v=(tr('segundo') if cad == 1 else _num(cad) + tr(' segundos'))))
    if tipo != "explosivo":
        partes.append(tr('Precisión {_grado}: acierta {int} de cada cien, y menos cuanto más lejos').format(_grado=(_grado(prec, ((0.75, 'baja'), (0.85, 'regular'), (0.93, 'buena')), tr('muy buena'))), int=(int(round(prec * 100)))))
    if a.get("cargador") and tipo == "fuego":
        partes.append(tr('Cargador de {int} balas').format(int=(int(a['cargador']))))
    if tipo != "cuerpo":
        partes.append(tr("No hace ruido") if not a.get("ruido", 2) else tr("Hace mucho ruido") if a.get("ruido", 2) >= 3 else tr("Hace ruido"))
    return ". ".join(partes) + "."


def ayuda_arma(a):
    """La descripción del arma y, detrás, su ficha."""
    return " ".join(t for t in (str(a.get("desc", "")).strip(), ficha_arma(a)) if t)



def unidad(a, n):
    """«bala», «granada», «cóctel»...: lo dicen los datos de cada arma («unidad»: singular|plural)."""
    sing, _, plur = str(a.get("unidad") or "bala|balas").partition("|")
    return sing if n == 1 else (plur or sing + "s")


def municion_txt(a, m):
    """La munición de un arma tuya, con su unidad: «12 balas y 30 de reserva», «1 granada y 2 de reserva»."""
    return tr('{cargador} {unidad} y {reserva} de reserva').format(cargador=(m['cargador']), unidad=(unidad(a, m['cargador'])), reserva=(m['reserva']))

class Combate:
    # ------------------------------------------------------------------ armas
    def arma(self):
        return self.armas_d.get(self.j.arma, self.armas_d["punos"])

    def dar_arma(self, ident, balas=0):
        a = self.armas_d.get(ident)
        if not a:
            return
        j = self.j
        if ident not in j.armas:
            j.armas[ident] = {"cargador": a.get("cargador", 0), "reserva": 0}
            n = self.orden_armas.index(ident) + 1
            self.decir(tr('Consigues: {nombre}.').format(nombre=(a['nombre'])) + (tr(' Es el arma número {n}.').format(n=(n)) if n <= 9 else tr(" Elígela con la coma o con la tecla I.")))
            j.arma = ident
        if a["tipo"] in ("fuego", "explosivo"):
            j.armas[ident]["reserva"] += balas

    def elegir_arma(self, idx, paso=1):
        j = self.j
        if isinstance(idx, str):
            j.arma = idx
        elif idx is None:
            mias = [a for a in self.orden_armas if a in j.armas]
            j.arma = mias[(mias.index(j.arma) + paso) % len(mias)]
        else:
            if idx >= len(self.orden_armas):
                return
            ident = self.orden_armas[idx]
            if ident not in j.armas:
                self.decir(tr('No tienes {nombre}.').format(nombre=(self.armas_d[ident]['nombre'])), True)
                return
            j.arma = ident
        a = self.arma()
        self.son("amartillar", vol=0.4, cat="interfaz")
        t = a["nombre"]
        if a["tipo"] in ("fuego", "explosivo"):
            m = j.armas[j.arma]
            t += ", " + municion_txt(a, m)
        self.decir(t, True)

    def capacidad(self, ident):
        """Balas que caben en el cargador de un arma tuya: la mitad más si lleva el cargador ampliado."""
        a = self.armas_d.get(ident) or {}
        n = int(a.get("cargador", 0))
        return int(n * 1.5) if self.j.armas.get(ident, {}).get("ampliado") and a.get("tipo") == "fuego" else n

    def recargar(self):
        j = self.j
        a = self.arma()
        if a["tipo"] not in ("fuego", "explosivo"):
            return
        m = j.armas[j.arma]
        falta = self.capacidad(j.arma) - m["cargador"]
        if falta <= 0:
            self.decir(tr("El cargador está lleno."), True)
        elif m["reserva"] <= 0:
            self.app.son("error")
            self.decir(tr("No te queda munición de reserva."), True)
        else:
            n = min(falta, m["reserva"])
            m["cargador"] += n
            m["reserva"] -= n
            j.t_ataque = 0.9
            self.son("recarga", vol=0.7)

    # --------------------------------------------------------------- objetivos
    def _objetivos(self, todos=False):
        x, y = self.pos()
        lista = []
        for p in self.personas:
            if not p.muerto and (p.hostil or todos) and p.dist(x, y) < 90:
                if p.tipo in ("aliado", "perro") and not self.cfg["fuego_amigo"]:
                    continue                                     # sin fuego amigo, a los tuyos ni se les apunta
                lista.append(p)
        for v in self.vehiculos:
            if v.muerto or v is self.j.veh:
                continue
            if (v.hostil or v.tag == "objetivo" or (todos and v.ia != "aparcado")) and v.dist(x, y) < 250:
                lista.append(v)
        lista += self.sv_objetivos(todos)                        # en un servidor, también los otros jugadores
        lista.sort(key=lambda e: e.dist(x, y))
        return lista

    DISPARO_VEH = (tr("Puedes responder sin bajarte: pulsa Q para fijar a quien tengas cerca y Control para disparar desde el vehículo, con un arma de fuego en la mano. "
                   "La tecla I cambia de arma."))

    def recordar_disparo_veh(self):
        """Una vez por partida, cuando viene a cuento: vas en un vehículo, llevas un arma de fuego y tienes enemigos cerca
        (los de una misión, una banda que te ha visto, quien te persigue). Antes solo se decía si llegaban a dispararte."""
        j = self.j
        if not j.veh or "disparo_veh" in j.recordado or self.mundo.tipo == "mar" or self.de_servicio():
            return
        if not any(self.armas_d.get(i, {}).get("tipo") == "fuego" for i in j.armas):
            return
        x, y = self.pos()
        cerca = any(not e.muerto and e.hostil and e.activo and e.tipo != "policia" and e.dist(x, y) < 45 for e in self.personas) or \
            any(not o.muerto and (o.hostil or o.tag == "objetivo") and o is not j.veh and not self.es_patrulla(o) and o.dist(x, y) < 60 for o in self.vehiculos)
        if cerca:
            j.recordado.append("disparo_veh")
            self.son("notificacion", cat="interfaz")
            self.decir(tr("Tienes enemigos cerca y vas al volante. ") + self.DISPARO_VEH)

    def fijar(self, any_=False, callar=False):
        lista = self._objetivos(any_)
        if not lista:
            self.objetivo = None
            if not callar:
                self.decir(tr("No hay enemigos cerca.") if not any_ else tr("No hay nadie cerca."), True)
            return None
        if self.objetivo in lista:
            self.objetivo = lista[(lista.index(self.objetivo) + 1) % len(lista)]
        else:
            self.objetivo = lista[0]
        o = self.objetivo
        self.t_objetivo = 0.0
        if not callar:
            self.app.vibrar(0.0, 0.5, 60)                   # objetivo fijado
            self.decir(tr("Fijado: ") + self.situar(o.x, o.y, o.nombre) + tr('. {len} en total.').format(len=(len(lista))), True)
        return o

    def atacar(self):
        j = self.j
        if j.t_ataque > 0 or self.transicion:
            return
        if self.rendido:
            self._romper_rendicion(tr("Atacas con las manos arriba: se acabó la rendición."))
        a = self.arma()
        x, y = self.pos()
        fuego = a["tipo"] == "fuego"
        if a["tipo"] == "explosivo":
            self._lanzar_explosivo(a, x, y)
            return
        if j.veh and not fuego:
            self.decir(tr("Desde el vehículo solo puedes usar armas de fuego: pulsa I para elegir una, Q para fijar a quien tengas cerca y Control para disparar."), True)
            j.t_ataque = 0.5
            return
        if fuego:
            m = j.armas[j.arma]
            if m["cargador"] <= 0:
                self.son("sin_balas")
                j.t_ataque = 0.3
                if m["reserva"] > 0:
                    self.recargar()
                else:
                    self.decir(tr("Sin munición."), True)
                return
            m["cargador"] -= 1
            if m.get("silenciador"):                             # con silenciador: un chasquido seco, y nadie se entera
                self.son(a["sonido"], vol=0.3, tono=random.uniform(1.5, 1.6))
            else:
                self.son(a["sonido"], vol=0.75, tono=random.uniform(0.96, 1.04))
                self.sv_ruido("d:" + a["id"])                    # en un servidor, los demás jugadores oyen el disparo
                if a.get("ruido", 2) > 0:
                    self._ruido_disparo(x, y)
        else:
            self.son("golpe_aire", vol=0.5)
        j.t_ataque = a["cadencia"]
        o = self.objetivo
        if o is not None and (o.muerto or o.dist(x, y) > max(a["alcance"], 60) * 1.5):
            o = None
        if o is None or (not fuego and o.dist(x, y) > a["alcance"]):
            cand = [e for e in self._objetivos(False) if e.dist(x, y) <= a["alcance"]]
            if not cand and not fuego:
                cand = [p for p in self.personas if not p.muerto and p.tipo not in ("aliado", "perro") and p.dist(x, y) <= a["alcance"]]
            if cand and (self.cfg["punteria"] == "completa" or not fuego):
                o = cand[0]
                if fuego:
                    self.objetivo = o
            elif cand:
                # puntería manual: hay que estar encarado al enemigo
                frente = j.veh.rumbo if j.veh else j.rumbo
                enc = [e for e in cand if abs(M.norm180(M.rumbo_a(e.x - x, e.y - y) - frente)) < 25]
                o = enc[0] if enc else None
        if o is None:
            return
        d = o.dist(x, y)
        if d > a["alcance"]:
            if fuego and self.t - self.t_fuera_alcance > 2.5:
                self.t_fuera_alcance = self.t
                self.decir(tr('Fuera de alcance: {metros}.').format(metros=(M.metros(d))))
            return
        if getattr(o, "tipo", "") == "jugador":                  # otro jugador: si le das o no lo decide el servidor
            if not fuego:
                self.son(a["sonido"], xy=(o.x, o.y), ref=6)
            self.sv_atacar(o, a)
            return
        prob = a["precision"] * (1.0 - 0.5 * d / a["alcance"]) if fuego else a["precision"]
        if j.veh:
            prob *= 0.75
        if self.cfg["dificultad"] == "facil":
            prob = min(1.0, prob + 0.12)
        prob = max(0.05, min(1.0, prob + 0.012 * self.nivel("punteria") + self.mod_punteria()))
        if getattr(self, "cubierto", None):
            prob *= 0.85                                         # desde detrás de algo se apunta peor
        if random.random() > prob:
            if fuego:
                self.son("bala_impacto", xy=(o.x + random.uniform(-2, 2), o.y + random.uniform(-2, 2)), ref=8, maxd=120, vol=0.6)
            return
        if self.cfg["aviso_acierto"]:                        # has dado: un toque agudo y un golpe corto en el mando
            self.son("tono_objetivo", cat="interfaz", vol=0.45, tono=2.0)
            self.app.vibrar(0.15, 0.8, 90)
        if isinstance(o, Vehiculo):
            self.son("bala_impacto", xy=(o.x, o.y), ref=10, maxd=150)
            self.danar_vehiculo(o, a["dano"] * 0.55)
        else:
            if not fuego:
                self.son(a["sonido"], xy=(o.x, o.y), ref=6)
            self.ganar_xp("punteria", 4)
            self.danar_persona(o, a["dano"])

    def _lanzar_explosivo(self, a, x, y):
        j = self.j
        m = j.armas[j.arma]
        if m["cargador"] <= 0:
            if m["reserva"] > 0:
                m["reserva"] -= 1
                m["cargador"] = 1
            else:
                self.son("sin_balas")
                self.decir(tr('No te quedan: {nombre}.').format(nombre=(a['nombre'])), True)
                j.t_ataque = 0.4
                return
        m["cargador"] -= 1
        if m["reserva"] > 0 and a.get("cargador", 1) == 1:
            m["reserva"] -= 1
            m["cargador"] = 1
        j.t_ataque = a["cadencia"]
        o = self.objetivo
        if o is None or o.muerto or o.dist(x, y) > a["alcance"]:
            cand = [e for e in self._objetivos(False) if e.dist(x, y) <= a["alcance"]]
            o = cand[0] if cand else None
        if o is not None:
            tx, ty = o.x, o.y
        else:
            rad = math.radians(j.veh.rumbo if j.veh else j.rumbo)
            tx, ty = x + math.sin(rad) * a["alcance"] * 0.6, y + math.cos(rad) * a["alcance"] * 0.6
        self.son(a["sonido"], vol=0.7)
        d = math.hypot(tx - x, ty - y)
        self.explosiones.append({"t": 0.35 + d / 45.0, "x": tx, "y": ty, "radio": a.get("radio", 8), "dano": a["dano"], "arma": a["id"],
                                 "sigue": o if getattr(o, "volando", False) else None})
        self.decir(tr('Quedan {v}.').format(v=(m['cargador'] + m['reserva'])))

    def _estallar(self, e):
        j = self.j
        x, y, r = e["x"], e["y"], e["radio"]
        blanco = e.get("sigue")
        if blanco is not None and not blanco.muerto:             # iba contra algo que vuela: estalla arriba, junto a él, y abajo no hace nada
            c = self.son("explosion", xy=(blanco.x, blanco.y), ref=30, maxd=400)
            c.alto = 35.0
            self.delito(3, tr("uso de explosivos"), siempre=self.mundo.policia and random.random() < 0.5)
            self.danar_vehiculo(blanco, e["dano"] * 1.3)
            return
        self.son("explosion", xy=(x, y), ref=30, maxd=400)
        self.sv_explosion(x, y, e.get("arma"))
        self.delito(3, tr("uso de explosivos"), siempre=self.mundo.policia and random.random() < 0.5)
        for p in list(self.personas):
            if not p.muerto and (p.tipo not in ("aliado", "perro") or self.cfg["fuego_amigo"]):
                d = p.dist(x, y)
                if d < r:
                    self.danar_persona(p, e["dano"] * (1 - 0.6 * d / r))
                elif p.tipo == "civil" and d < 50:
                    self.asustar(p, 12)
        for v in list(self.vehiculos):
            d = v.dist(x, y)
            if not v.muerto and d < r + 2 and not getattr(v, "volando", False):
                self.danar_vehiculo(v, e["dano"] * 1.3 * (1 - 0.5 * d / (r + 2)))
        px, py = self.pos()
        d = math.hypot(px - x, py - y)
        if d < r and not j.veh:
            self.danar_jugador(e["dano"] * 0.5 * (1 - d / r), (x, y))

    def _trato_policia(self):
        """Te han cogido por algo menor: pagar la multa, intentar un soborno o dejarte detener."""
        from .menus import Menu, Opcion
        j = self.j
        app = self.app
        multa = self.coste_multa()
        soborno = int(multa * 0.6)
        prob = max(0.25, min(0.9, 0.45 + j.reputacion / 200.0))

        def fuera(texto):
            app.cerrar(menu)
            for p in self.personas:
                if p.tipo == "policia":
                    p.t_arresto = 0.0
            self.limpiar_busqueda(hablar=False)
            self.decir(texto)

        def pagar():
            j.dinero -= multa
            self.son("dinero", cat="interfaz")
            self.hon_antecedente(1, tr("Multa pagada a un agente"))
            fuera(tr('Pagas {multa} euros de multa. El agente te deja ir y ya no te buscan. Conservas tus armas.').format(multa=(multa)))

        def sobornar():
            j.dinero -= soborno
            if random.random() < prob:
                self.son("dinero", cat="interfaz")
                self.cambiar_reputacion(1)
                fuera(tr('El agente mira a los lados, se guarda los {soborno} euros y se da la vuelta. Ya no te buscan.').format(soborno=(soborno)))
            else:
                app.cerrar(menu)
                app.son("error")
                self.decir(tr('El agente se queda con los {soborno} euros y además te detiene por intento de soborno.').format(soborno=(soborno)))
                self.detener(sin_trato=True)

        def nada():
            app.cerrar(menu)
            self.detener(sin_trato=True)
        self.son("esposas", cat="interfaz", vol=0.5)
        from . import mochila
        lleva = self.moc_comprometido()                          # te cachea: con mercancía o algo robado encima no hay multa (mochila.py)
        if lleva:
            soborno = int(multa * 1.5)
            prob = max(0.15, prob - 0.2)
            self.decir(mochila.AJ.frase("frases_cacheo", que=lleva))
        menu = Menu(app, tr('Un agente te ha cogido. Búsqueda de nivel {estrellas}. Tienes {dinero} euros').format(estrellas=(j.estrellas), dinero=(j.dinero)),
                    ([] if lleva else [Opcion(tr('Pagar la multa en el acto: {multa} euros').format(multa=(multa)), pagar, ayuda=tr("Pagas, te quitan la búsqueda y te vas. Conservas las armas y no pasas por comisaría."))]) + [
                     Opcion(tr('Intentar un soborno: {soborno} euros').format(soborno=(soborno)), sobornar,
                            ayuda=(tr("Con lo que llevas encima, sale más caro que una multa y es más difícil") if lleva else tr("Más barato")) + tr(', y puede salir mal: ahora mismo sale bien unas {int} veces de cada cien, más cuanta más fama tengas. Si sale mal, pierdes ese dinero y te detienen.').format(int=(int(prob * 100)))),
                     Opcion(tr("Dejar que te detengan"), nada, ayuda=tr("Lo de siempre: comisaría, una multa mayor y pierdes las armas de fuego, la mercancía y lo robado que lleves encima."))], escapable=False)
        app.abrir(menu)

    def _ruido_disparo(self, x, y):
        if not self.en_defensa_propia():                         # disparar a quien te ha atacado primero no es delito
            self.delito(0.4, tr("disparos en la vía pública"))
        for p in self.personas:
            if p.tipo == "civil" and not p.muerto and p.estado == "pasea" and p.dist(x, y) < 40:
                self.asustar(p, 10)

    # ------------------------------------------------------------------ daños
    def danar_persona(self, p, dano, atropello=False):
        if p.muerto:
            return
        if p.tipo in ("aliado", "perro"):                        # los tuyos: solo con fuego amigo, y sin volverse enemigos a la primera
            self.herir_amigo(p, dano)
            return
        j = self.j
        self.sv_golpe_eco(p, dano)                               # en una misión en grupo, el golpe cuenta para todos
        self.sv_golpe_policia(p, dano)                           # y si es un agente que persigue a otro jugador, le llega a su juego
        self.sv_golpe_peaton(p, dano)                            # y si es alguien de la calle, que es de todos, también
        self.sv_golpe_agente(p, dano)                            # o un agente de los que lleva el servidor
        if self.se_rinde_con(p, dano):                           # uno al que hay que asustar o detener: se rinde en vez de caer
            return
        p.salud -= dano
        if p.salud <= 0:
            p.muerto = True
            p.t_estado = self.t
            self.son("muerte_npc", xy=(p.x, p.y), ref=6, tono=p.tono)
            if not getattr(p, "inofensivo", False) and not getattr(p, "deportivo", False):
                self.aviso_ambulancia(p.x, p.y)                  # al rato acude una ambulancia
            if p.tipo == "civil":
                self.delito(3 if atropello else 4, "atropello" if atropello else "homicidio")
                self.decir(tr("Has atropellado a un peatón.") if atropello else tr('{nombre} cae al suelo.').format(nombre=(p.nombre)))
            elif p.tipo == "policia":
                self.delito(6, tr("agresión a un agente"), siempre=True)
                self.decir(tr("Policía abatido."))
            elif getattr(p, "inofensivo", False):                # un muñeco o una diana de prácticas: ni delito, ni botín, ni cuenta
                self.decir(tr('{nombre}: al suelo.').format(nombre=(p.nombre)))
                return
            elif getattr(p, "deportivo", False):                 # un rival del gimnasio: es deporte, ni delito ni botín
                self.decir(f"{p.nombre} {random.choice(RIVAL_CAE)}")
                if self.objetivo is p:
                    self.objetivo = None
                return
            else:
                j.stats["enemigos"] += 1
                banda = getattr(p, "banda", None) or (tr("Los Calaveras") if p.tipo == "banda" else G.banda_en(p.nombre))
                defensa = self.es_agresor(p) and not getattr(p, "provocado", False) and p.tag in (None, "evento")
                self.decir(tr('{nombre} abatido.').format(nombre=(p.nombre)))
                if defensa:                                      # te atacó primero: su banda lo entiende, y más si eres buena gente
                    sin_guerra = self.hon_baja_defensa(p, banda)
                else:
                    sin_guerra = False
                    if banda:
                        self.cambiar_rep_banda(banda, -4)        # matar a los suyos no se olvida
                    if p.tag != "evento" and not self.es_agresor(p):      # tumbar a quien te ha atacado primero es defensa propia
                        self.delito(0.6, None)
                if not sin_guerra:
                    self.guerra_baja(p)
            if p.tipo != "civil" and random.random() < 0.6 or random.random() < 0.2:
                o = Objeto("dinero", tr("Dinero en el suelo"), p.x, p.y)
                o.valor = random.randint(20, 120) if p.tipo != "civil" else random.randint(5, 50)
                self.objetos.append(o)
            self.soltar_botin(p)                                 # y la munición de su arma o, con la opción, el arma
            if p.tipo not in ("aliado", "perro", "policia"):
                self.moc_botin("caido", p.x, p.y)                # y alguna vez, algo de valor (mochila.py)
            if self.objetivo is p:
                self.objetivo = None
                if self.cfg["punteria"] == "completa":
                    self.fijar(callar=True)
        else:
            self.voz_persona(p, "dolor")                         # se queja con su voz, de hombre o de mujer
            if not getattr(p, "agresor", False):                 # le has dado tú primero: ya no vale decir que fue defensa propia
                p.provocado = True
            if p.tipo == "civil":
                self.asustar(p, 12, grito=0.0)
                self.delito(2, "agresión")
            elif not p.hostil:
                p.hostil = True
                p.estado = "ataca"

    def danar_jugador(self, dano, origen):
        j = self.j
        if self.transicion or dano <= 0 or self.cfg["invulnerable"]:
            return
        dano *= self.dificultad() * (1 - 0.02 * self.nivel("resistencia")) * self.mod_dano()
        if getattr(self, "cubierto", None):
            dano *= 0.3                                          # a cubierto te llega mucho menos
        antes = j.salud
        if j.blindaje > 0:
            abs_ = min(j.blindaje, dano * 0.8)
            j.blindaje -= abs_
            dano -= abs_
            if j.blindaje <= 0:
                self.decir(tr("El chaleco ya no aguanta más."))
        j.salud -= dano
        self.app.vibrar(min(1.0, 0.3 + dano / 40.0), 0.4, 220)
        if origen:
            self.son("dolor", vol=0.7)
        else:
            self.son("dolor", vol=0.5)
        if j.salud <= 0:
            self.morir()
            return
        for umbral in (75, 50, 25):
            if antes > umbral >= j.salud:
                extra = tr(" Pulsa Z para usar un botiquín.") if umbral <= 50 and j.objetos.get("botiquin", 0) > 0 else ""
                self.decir(tr('Salud {int}.{extra}').format(int=(int(j.salud)), extra=(extra)))
                break

    def danar_vehiculo(self, v, dano):
        if self.sv_dano_copia(v, dano):                          # un vehículo aparcado de otro jugador: lo lleva el servidor
            return
        if v.muerto or v.ardiendo >= 0:
            return
        if getattr(v, "volando", False):                         # el helicóptero de la policía: solo le hacen daño las armas pesadas
            return self.heli_danado(v, dano)
        antes = v.salud / v.salud_max
        if v is self.j.veh:                                      # el tuyo aguanta más en fácil y en normal: de un par de golpes no arde
            dano *= {"facil": 0.5, "normal": 0.75}.get(self.cfg["dificultad"], 1.0)
        v.salud -= dano
        ahora = v.salud / v.salud_max
        if v is self.j.veh:
            for u in (0.5, 0.25):
                if antes > u >= ahora > 0:
                    self.decir(tr('Vehículo al {int} por ciento.').format(int=(int(u * 100))) + (tr(" Sale humo del motor: un golpe fuerte más y arde. En un taller te lo arreglan.") if u == 0.25 else ""))
        elif v.tag == "objetivo":
            for u in (0.75, 0.5, 0.25):
                if antes > u >= ahora > 0:
                    self.decir(tr('{nombre} al {int} por ciento.').format(nombre=(v.nombre), int=(int(u * 100))))
        if v.salud <= 0:
            v.salud = 0
            v.ardiendo = 0.4 if v.tag == "objetivo" else 7.0 if v is self.j.veh else 4.5
            v.fuego = self.son("fuego", bucle=True, xy=(v.x, v.y), ref=8, maxd=90)
            if v is self.j.veh:
                self.decir(tr("¡El vehículo está ardiendo! ¡Pulsa F para salir, va a explotar!"), True)

    def explotar(self, v):
        j = self.j
        x, y = v.x, v.y
        self.son("explosion", xy=(x, y), ref=30, maxd=400)
        self.app.vibrar(1.0, 1.0, 600)
        if v is j.veh:
            self.salir_vehiculo(forzado=True)
            self.danar_jugador(95, (x, y))
        else:
            d = math.hypot(j.x - x, j.y - y) if not j.veh else j.veh.dist(x, y)
            if d < 11:
                if j.veh:
                    self.danar_vehiculo(j.veh, 50 * (1 - d / 11))
                else:
                    self.danar_jugador(15 + 60 * (1 - d / 11), (x, y))
        for p in list(self.personas):
            if not p.muerto and p.dist(x, y) < 8:
                self.danar_persona(p, 300)
        for q in getattr(v, "pasajeros", []):                    # los enemigos que venían dentro y no se habían bajado caen con él
            if not q.muerto:
                q.muerto = True
                j.stats["enemigos"] += 1
        if v.tag == "objetivo" and self.mision:
            self.mision["restos"] = (x, y)
        if self.es_mio(v):
            self.seguro_siniestro(v)                             # con seguro, te lo devuelven; sin él, se pierde (misvehiculos.py)
        if v.modelo["id"] == "blindado" and not v.tag:
            o = Objeto("dinero", tr("Sacas de dinero del furgón"), *self.mundo.punto_libre(x, y))
            o.valor = random.randint(3000, 6000)
            self.objetos.append(o)
            self.decir(tr("¡El furgón blindado revienta y las sacas de dinero quedan en el suelo! Toda la policía viene hacia aquí."))
            if self.mundo.policia:
                self.poner_busqueda(3)
        self.quitar_vehiculo(v)

    # ---------------------------------------------------------------- delitos
    def delito(self, puntos, texto=None, siempre=False):
        j = self.j
        if self.cfg["sin_policia"]:
            return
        if self.mision and self.mision["def"].get("tutorial"):        # en un tutorial no viene la policía
            return
        if self.cfg["mod_policia"]:
            puntos *= 1.5
        x, y = self.pos()
        if not siempre:
            testigo = any((p.tipo == "civil" and not p.muerto and p.dist(x, y) < 35) or
                          (p.tipo == "policia" and not p.muerto and p.dist(x, y) < 80) for p in self.personas)
            testigo = testigo or any(self.es_patrulla(v) and v.dist(x, y) < 80 for v in self.vehiculos)
            if not testigo:
                return
        if self.delito_de_servicio(puntos, texto):               # de servicio como policía: fuerza justificada, o un apercibimiento
            return
        agente = siempre or any(p.tipo == "policia" and not p.muerto and p.dist(x, y) < 80 for p in self.personas) or any(self.es_patrulla(v) and v.dist(x, y) < 80 for v in self.vehiculos)
        puntos = self.hon_delito(puntos, agente, forzado=siempre)      # los vecinos encubren o delatan según cómo te ven (honrado.py)
        if puntos <= 0:
            return
        self.cambiar_ciudadania(-0.6 * puntos)
        if j.ciudadania >= 50:
            puntos *= 0.7            # a un buen vecino se le pasan por alto las faltas pequeñas
        if j.estrellas == 0 and j.puntos_busqueda + puntos >= UMBRAL[0] and texto:
            self.decir(tr('Te han visto. Delito: {texto}.').format(texto=(texto)))
        j.puntos_busqueda += puntos
        self.sv_delito(puntos)                                   # en un servidor, la cuenta la lleva él

    def poner_busqueda(self, nivel):
        if self.cfg["sin_policia"]:
            return
        self.j.puntos_busqueda = max(self.j.puntos_busqueda, UMBRAL[max(0, min(4, nivel - 1))])
        self.sv_busqueda(nivel)

    def limpiar_busqueda(self, hablar=True):
        j = self.j
        if j.estrellas > 0 and hablar:
            self.son("policia_perdida", cat="interfaz")
            self.decir(tr("Has despistado a la policía. Ya no te buscan."))
        j.puntos_busqueda = 0.0
        j.estrellas = 0
        self.t_evasion = 0.0
        self.sv_busqueda(0)
        for p in self.personas:
            if p.tipo == "policia":
                p.hostil = False
                p.estado = "quieto"
        for v in self.vehiculos:
            if v.ia == "policia":
                v.hostil = False
        if isinstance(self.objetivo, Persona) and self.objetivo.tipo == "policia":
            self.objetivo = None

    def actualizar_policia(self, dt):
        j = self.j
        n = sum(1 for u in UMBRAL if j.puntos_busqueda >= u)
        if n > j.estrellas:
            if j.estrellas == 0:
                self.t_policia = 5.0 if not j.veh else 3.0          # la primera patrulla tarda en salir: da tiempo a reaccionar
                self.patrulla_enviada = False
            self.son("estrella_sube", cat="interfaz")
            self.app.vibrar(0.5, 0.5, 250)
            pista = tr(" Aléjate de las sirenas hasta que dejen de buscarte, o pinta el vehículo en un taller.") if j.estrellas == 0 else ""
            aviso = G.aviso_nivel(n) if self.mundo.policia and not self.sv_policia_comun() else ""      # con mucha búsqueda sale gente mejor armada: lo dicen los datos
            self.decir(tr('Nivel de búsqueda {n} de 5.{pista}').format(n=(n), pista=(pista)) + (" " + aviso if aviso else ""))
        j.estrellas = n
        if n == 0:
            return
        if self.sv_policia_comun():                              # en un servidor, perseguirte y perderte lo decide él
            self.sv_buscando(dt)
            return
        x, y = self.pos()
        # A pie se te ve menos que en un coche: basta con alejarse media manzana para que te pierdan.
        r_p, r_v = (70, 80) if j.veh else (38, 45)
        if j.veh:                                                # con el escape silenciado te oyen de menos lejos
            from . import sistemas
            r_p, r_v = r_p * sistemas.factor_oido_policia(j.veh), r_v * sistemas.factor_oido_policia(j.veh)
        cerca = any(p.tipo == "policia" and not p.muerto and p.dist(x, y) < r_p for p in self.personas) or \
            any(v.ia == "policia" and not v.muerto and v.dist(x, y) < r_v for v in self.vehiculos)
        if self.vuelo_alto():                                    # volando alto, las patrullas de tierra no te siguen
            cerca = False
        cerca = cerca or self.heli_te_tiene() or self.radar_te_tiene()      # con el helicóptero encima, o en el radar con un aparato secuestrado, no hay quien despiste a nadie
        if cerca:
            self.t_evasion = 0.0
        else:
            if getattr(self, "patrulla_enviada", True):
                self.t_evasion += dt                              # solo cuenta cuando ya hay alguien buscándote
            self.t_buscando -= dt
            if self.t_buscando <= 0:
                self.t_buscando = 1.0
                self.son("buscando", vol=0.6, cat="interfaz")
            if self.t_evasion >= (9 + 4 * n if j.veh else 7 + 3 * n) * (2.0 if self.t < self.t_represalia else 1.0):
                self.limpiar_busqueda()
                return
        self.t_policia -= dt
        if self.t_policia <= 0:
            self.t_policia = RITMO_PATRULLAS.get(n, 5.0)
            total = sum(1 for v in self.vehiculos if v.ia == "policia" and not v.muerto)
            tope = PATRULLAS.get(n, 4) - (1 if self.cfg["dificultad"] == "facil" and n >= 3 else 0)
            if total < tope and self.t_evasion < 6 and self.mundo.policia:
                self._llegar_patrulla(x, y)
            self.patrulla_enviada = True
        for v in self.vehiculos:
            if v.ia == "policia":
                v.hostil = True

    def _punto_llegada(self, x, y):
        """Un punto de la calzada a unos doscientos metros, y el sentido para venir desde él: (x, y, sentido). None si no lo hay."""
        m = self.mundo
        if m.tipo == "mar" or m.NX < 2 or m.NY < 2:
            return None
        for _ in range(6):
            dist = random.uniform(150, 230) * random.choice([-1, 1])
            if random.random() < 0.5:
                jj = m._idx(y, m.NY)
                vx = x + dist
                if not (5 < vx < m.ancho - 5):
                    continue
                d = 3 if dist > 0 else 1
                pos = (vx, m.carril("H", jj, d))
            else:
                ii = m._idx(x, m.NX)
                vy = y + dist
                if not (5 < vy < m.alto - 5):
                    continue
                d = 2 if dist > 0 else 0
                pos = (m.carril("V", ii, d), vy)
            return pos[0], pos[1], d
        return None

    def _llegar_patrulla(self, x, y):
        """Sale una patrulla a por ti. Qué agentes trae y en qué vehículo lo dice la tabla de la policía de los datos, según el nivel de búsqueda."""
        pos = self._punto_llegada(x, y)
        if pos is None:
            return
        e = G.agentes_nivel(self.j.estrellas)
        v = Vehiculo(self.modelos.get(e["vehiculo"]) or self.modelos["patrulla"], pos[0], pos[1], pos[2], "policia")
        v.agentes = e
        v.ocupado = True
        v.hostil = True
        v.vel = 12.0
        self.vehiculos.append(v)

    # ---------------------------------------------------------------- personas
    def _andar_hacia(self, p, tx, ty, vel, dt):
        dx, dy = tx - p.x, ty - p.y
        d = math.hypot(dx, dy)
        if d < 0.1:
            return
        paso = vel * dt
        nx, ny = p.x + dx / d * paso, p.y + dy / d * paso
        if self.mundo.transitable(nx, ny):
            p.x, p.y = nx, ny
        elif abs(dx) > 0.2 and self.mundo.transitable(p.x + math.copysign(paso, dx), p.y):
            p.x += math.copysign(paso, dx)
        elif abs(dy) > 0.2 and self.mundo.transitable(p.x, p.y + math.copysign(paso, dy)):
            p.y += math.copysign(paso, dy)
        else:
            # atascado contra una esquina: rodea por el eje más largo
            if abs(dx) < abs(dy) and self.mundo.transitable(p.x + paso, p.y):
                p.x += paso
            elif self.mundo.transitable(p.x, p.y + paso):
                p.y += paso

    def actualizar_personas(self, dt):
        j = self.j
        px, py = self.pos()
        vel_j = abs(j.veh.vel) if j.veh else 0.0
        for p in list(self.personas):
            if p.muerto:
                continue
            if p.tipo == "aliado":
                self.actualizar_aliado(p, dt)
                continue
            if p.tipo == "perro":
                self.actualizar_perro(p, dt)
                continue
            if p.estado == "sigue" and p.tipo == "civil":            # alguien que se ha venido contigo un rato
                self.paso_seguidor(p, dt)
                continue
            d = p.dist(px, py)
            if getattr(p, "po_id", None) is not None:            # un agente del servidor: lo mueve él
                self.sv_agente_paso(p, d, dt)
                continue
            if p.tipo == "policia" and self.agente_auxilia(p, dt):      # hay cerca alguien que te ha atacado: va a por él
                continue
            if p.tipo == "policia" and j.estrellas > 0 and not p.hostil:   # un agente que estaba a otra cosa: ahora te buscan a ti
                p.hostil, p.estado = True, "ataca"
            if p.tipo == "policia" and j.estrellas == 0:
                p.hostil = False
                if d > 45:
                    self.personas.remove(p)
                continue
            if not p.hostil:
                if p.estado == "quieto" or p.bloque is None:
                    if p.estado == "huye":
                        self._andar_hacia(p, p.x + (p.x - px), p.y + (p.y - py), 4.5, dt)
                        if p.tipo == "civil":
                            self.panico(p, d, dt)                # se le oye: chillidos y pasos a la carrera
                            if d < 24:
                                p.t_paso -= dt
                                if p.t_paso <= 0:
                                    p.t_paso = 0.3
                                    self.son("paso_npc", xy=(p.x, p.y), ref=3, maxd=28, vol=0.7, tono=random.uniform(0.9, 1.1))
                        p.t_estado -= dt
                        if p.t_estado <= 0:
                            p.estado = "quieto"
                    continue
                vel = p.vel
                if p.estado == "huye":
                    vel = 4.6
                    if p.tipo == "civil":
                        self.panico(p, d, dt)
                    p.t_estado -= dt
                    p.t_voz -= dt
                    if p.t_voz <= 0:
                        p.t_voz = 1.0
                        u0 = p.u
                        mejor = None
                        for s in (-1, 1):
                            p.u = u0 + s * 3
                            self._pos_perimetro(p)
                            dd = p.dist(px, py)
                            if mejor is None or dd > mejor[0]:
                                mejor = (dd, s)
                        p.u = u0
                        p.sentido = mejor[1]
                    if p.t_estado <= 0:
                        p.estado = "pasea"
                p.u += p.sentido * vel * dt
                self._pos_perimetro(p)
                if d < 24:
                    p.t_paso -= dt
                    if p.t_paso <= 0:
                        p.t_paso = 0.3 if p.estado == "huye" else 0.55
                        self.son("paso_npc", xy=(p.x, p.y), ref=3, maxd=28, vol=0.7, tono=random.uniform(0.9, 1.1))
                continue
            # ------------------------------------------------------ hostiles
            if getattr(p, "inofensivo", False):
                continue
            if not p.activo:
                if d < 42:
                    p.activo = True
                else:
                    continue
            if p.tipo == "banda" and self.rep_banda(getattr(p, "banda", None) or tr("Los Calaveras")) >= 30 and not getattr(p, "provocado", False):
                continue                                         # te respetan: no te hacen nada mientras no les toques
            if p.tipo == "banda" and d <= 26 and not getattr(p, "agresor", False) and self.hon_banda_deja_pasar(p):
                p.avisado, p.hostil = True, False                # buena gente: te ha visto y te deja pasar mientras no le toques
                continue
            if p.tipo == "banda" and not p.avisado:
                if d > 26:
                    p.u += p.sentido * p.vel * dt
                    self._pos_perimetro(p)
                    continue
                p.avisado = True
                self.son("grito", xy=(p.x, p.y), vol=0.5, tono=0.8)
                self.decir(tr('¡Un {nombre} te ha visto! {situar}. Pulsa Q para fijarlo.').format(nombre=(p.nombre), situar=(self.situar(p.x, p.y, tr('Está')))))
            if getattr(p, "frases", None) and not getattr(p, "ha_gritado", False) and d < 32:      # los enemigos con frases gritan la suya al verte, de uno en uno
                p.ha_gritado = True
                if self.t - getattr(self, "t_frase_enemigo", -99.0) > 5.0:
                    self.t_frase_enemigo = self.t
                    self.son("grito", xy=(p.x, p.y), vol=0.4, tono=p.tono)
                    self.decir(f"{p.nombre}: {random.choice(p.frases)}")
            if p.tipo == "policia" and self.rendido:              # te has rendido: no dispara, viene a esposarte
                if self.agente_detiene(p, d, dt):
                    return
                continue
            if d < 32 and not getattr(p, "agresor", False):
                # Viene a por ti sin que le hayas tocado: no hay que esperar al primer navajazo para que defenderse sea
                # defensa propia. Antes, si disparabas tú primero a quien se te echaba encima, el delito era tuyo.
                self.marcar_agresor(p)
            a = self.armas_d.get(p.arma or "punos", self.armas_d["punos"])
            cuerpo = a["tipo"] == "cuerpo"
            alcance = a["alcance"] if cuerpo else min(a["alcance"], 30.0)
            arresto = p.tipo == "policia" and j.estrellas == 1
            dist_obj = 1.8 if (cuerpo or arresto) else alcance * 0.6
            if d > dist_obj:
                self._andar_hacia(p, px, py, 3.7 if p.tipo == "policia" else 3.3, dt)
                p.t_paso -= dt
                if p.t_paso <= 0 and d < 30:
                    p.t_paso = 0.33
                    self.son("paso_npc", xy=(p.x, p.y), ref=3, maxd=30, vol=0.9, tono=0.85)
            if arresto:
                if d < 3.0 and vel_j < 1.5:
                    p.t_arresto += dt
                    if p.t_arresto > 1.6:
                        self.detener()
                        return
                else:
                    p.t_arresto = 0.0
                continue
            if d > alcance + (0.5 if cuerpo else 0):
                p.t_disparo = max(p.t_disparo, 0.6)
                continue
            p.t_disparo -= dt
            if not cuerpo and p.t_disparo < 0.45 and not getattr(p, "amartillado", False):
                p.amartillado = True
                self.son("amartillar", xy=(p.x, p.y), ref=5, maxd=50)
            if p.t_disparo > 0:
                continue
            p.amartillado = False
            self.marcar_agresor(p)                               # te ataca sin que tú le hayas tocado: lo tuyo ya es defensa propia
            p.ha_resistido = True
            p.t_disparo = (0.45 if a.get("automatica") else max(1.2, a["cadencia"] * 2.5)) + random.uniform(0, 0.6)
            if cuerpo:
                self.son(a["sonido"], xy=(p.x, p.y), ref=4)
                if random.random() < 0.7:
                    self.danar_jugador(a["dano"] * 0.5, (p.x, p.y))
                continue
            self.son(a["sonido"], xy=(p.x, p.y), ref=14, maxd=220, vol=0.9)
            if j.veh and "disparo_veh" not in j.recordado:       # la primera vez que te disparan yendo en un vehículo
                j.recordado.append("disparo_veh")
                self.son("notificacion", cat="interfaz")
                self.decir(tr("¡Te disparan! ") + self.DISPARO_VEH)
            prob = getattr(p, "punteria", G.PUNTERIA) * (1.0 - 0.6 * d / alcance)
            if j.agachado:
                prob *= 0.45
            if j.veh:
                prob *= 0.7
            if random.random() < prob:
                if j.veh:
                    self.son("bala_impacto", vol=0.6)
                    self.danar_vehiculo(j.veh, a["dano"] * 0.4)
                    if random.random() < 0.3:
                        self.danar_jugador(a["dano"] * 0.2, (p.x, p.y))
                else:
                    self.danar_jugador(a["dano"] * 0.4, (p.x, p.y))
            else:
                self.son("bala_silbido", pan=random.uniform(-0.9, 0.9), vol=0.5)

    def actualizar_combate(self, dt):
        j = self.j
        if j.t_ataque > 0:
            j.t_ataque -= dt
        for e in list(self.explosiones):
            e["t"] -= dt
            if e["t"] <= 0:
                self.explosiones.remove(e)
                self._estallar(e)
        t = self.app.teclas
        if not j.veh and pygame.K_SPACE in t and self.arma().get("automatica"):
            self.atacar()
        o = self.objetivo
        if o is not None:
            x, y = self.pos()
            if o.muerto or o.dist(x, y) > 260:
                self.objetivo = None
            else:
                self.t_objetivo -= dt
                if self.t_objetivo <= 0:
                    d = o.dist(x, y)
                    self.t_objetivo = max(0.25, min(1.0, d / 40.0))
                    f = min(d, 25) / d if d > 0.5 else 1.0
                    dentro = d <= self.arma()["alcance"]
                    self.son("tono_objetivo" if dentro else "tono_apuntado", xy=(x + (o.x - x) * f, y + (o.y - y) * f),
                             ref=8, maxd=80, vol=0.7, cat="interfaz")
        if j.salud < 30 and self.latido_canal is None:
            self.latido_canal = self.son("latido", bucle=True, vol=0.7)
        elif j.salud >= 30 and self.latido_canal is not None:
            self.latido_canal.parar()
            self.latido_canal = None

    # ------------------------------------------------------- muerte y arresto
    def _fin_persecucion(self):
        self.rendido = None
        self.sv_busqueda(0, fin=True)                            # en un servidor, los que iban a por ti se retiran ya
        self.limpiar_busqueda(False)
        for p in [p for p in self.personas if p.tipo == "policia"]:
            self.personas.remove(p)
        for v in [v for v in self.vehiculos if v.ia == "policia"]:
            self.quitar_vehiculo(v)
        self.objetivo = None

    def morir(self):
        if self.transicion:
            return
        self.transicion = True
        j = self.j
        self.sv_al_morir()
        self.guerra_retirada(tr("Caes en mitad de la pelea."))       # si había una guerra de barrio en marcha, se acaba
        j.stats["muertes"] += 1
        self.son("mision_fallo", cat="interfaz")
        if j.veh:
            self.salir_vehiculo(forzado=True)
        self._fin_persecucion()
        if self.trabajo:
            self.terminar_trabajo(None)
        coste = min(j.dinero, self.precio("hospital_urgencias", 150))
        j.dinero -= coste
        j.animo = max(0.0, j.animo - 12)
        j.efectos = []
        self.perder_mercancia(todo=False)
        h = self._reaparecer("hospital")
        j.salud = j.salud_max
        j.blindaje = 0.0
        j.agachado = False
        self.pasar_horas(6)
        self.cancelar_gps()

        def fin():
            self.transicion = False
            if self.mision and not self.mision_en_escena():
                self.fallar_mision(tr("Has perdido el conocimiento."))
        self.son("hospital_despertar", cat="interfaz")
        self.app.abrir(Dialogo(self.app, [(tr("Narrador"), tr('Todo se vuelve negro. Horas después despiertas en {nombre}, {nombre2}, con un vendaje nuevo y {coste} euros menos. Son las {hora_txt}.').format(nombre=(h.nombre), nombre2=(self.mundo.nombre), coste=(coste), hora_txt=(self.hora_txt())))], fin))

    def _reaparecer(self, tipo):
        """Te lleva al hospital o comisaría más cercano (de este mapa, o del principal)."""
        x, y = self.pos()
        aqui = [l for l in self.mundo.lugares.values() if l.tipo == tipo]
        if aqui:
            l = min(aqui, key=lambda l: math.hypot(l.x - x, l.y - y))
            self.teletransportar(l.x, l.y)
            return l
        todos = [l for l in self.lugares.values() if l.tipo == tipo]
        l = next((q for q in todos if q.mapa == "puerto_bravo"), todos[0])
        self.j.barco_actual = None
        if self.j.veh:
            v = self.j.veh
            if self.es_mio(v):                                   # el tuyo se queda donde estaba: no se pierde
                self.salir_vehiculo(forzado=True)
            else:
                self.j.veh = None
                self.quitar_vehiculo(v)
            self.app.radio.apagar()
        self.cambiar_mapa(l.mapa, l.x, l.y)
        return l

    def coste_multa(self):
        j = self.j
        return self.precio("multa_estrella", 150) * max(1, j.estrellas) + j.dinero // 20

    def detener(self, sin_trato=False, rendicion=False):
        """Te detienen. Con «rendicion», te has entregado tú con las manos arriba: con mucha búsqueda, la multa, el calabozo
        y lo que te quitan van con el nivel que llevabas."""
        if self.transicion:
            return
        j = self.j
        self.rendido = None
        nivel = j.estrellas
        if not sin_trato and self.cfg["multas"] and 1 <= j.estrellas <= 2 and j.dinero >= self.coste_multa() and not self.mision:
            self._trato_policia()                                # con poca búsqueda y dinero en el bolsillo, se puede arreglar
            return
        self.transicion = True
        self.guerra_retirada(tr("Te detienen en mitad de la pelea."))
        j.stats["detenciones"] += 1
        self.son("esposas", cat="interfaz")
        if j.veh:
            self.salir_vehiculo(forzado=True)
        self._fin_persecucion()
        if self.trabajo:
            self.terminar_trabajo(None)
        multa = min(j.dinero, max(self.precio("multa_minima", 100), j.dinero // 10))
        horas, todas = 8, False
        dura = rendicion and nivel >= 3
        if dura:                                                 # rendirse con mucha búsqueda: más caro cuanto más nivel
            multa, horas, todas = self._pena_rendicion(nivel)
            j.stats["rendiciones"] = j.stats.get("rendiciones", 0) + 1
        j.dinero -= multa
        for ident in [a for a in j.armas if a in self.armas_d and (self.armas_d[a]["tipo"] in ("fuego", "explosivo") or (todas and a != "punos"))]:
            del j.armas[ident]
        if todas:
            j.blindaje = 0.0
        j.arma = "punos"
        j.animo = max(0.0, j.animo - 15)
        j.reputacion = max(0.0, j.reputacion - 3)
        j.efectos = []
        requisado = self.perder_mercancia()
        if requisado:
            multa_extra = min(j.dinero, requisado * self.precio("multa_mercancia", 20))
            j.dinero -= multa_extra
            multa += multa_extra
        robados = self.moc_requisar()                            # lo robado de la mochila se queda en comisaría (mochila.py)
        quitado = []
        if requisado:
            quitado.append(tr('las {requisado} unidades de mercancía que llevabas').format(requisado=(requisado)))
        if robados:
            quitado.append(tr("el objeto robado de la mochila") if robados == 1 else tr('los {robados} objetos robados de la mochila').format(robados=(robados)))
        cargos = int(getattr(j, "cargos_helicoptero", 0) or 0)
        if cargos:                                               # los helicópteros derribados se pagan al caer
            from . import calle
            extra = min(j.dinero, int(cargos * calle.aj("helicoptero_multa")))
            j.dinero -= extra
            multa += extra
            j.cargos_helicoptero = 0
        c = self._reaparecer("comisaria")
        j.agachado = False
        self.pasar_horas(horas)
        self.cancelar_gps()

        def fin():
            self.transicion = False
            if self.mision and not self.mision_en_escena():
                self.fallar_mision(tr("Te han detenido."))
        self.son("celda", cat="interfaz")
        j.ciudadania = max(0.0, j.ciudadania - 5)
        self.hon_antecedente(1 if nivel <= 2 else 2 if nivel == 3 else 3, tr('Detención con búsqueda de nivel {max}').format(max=(max(1, nivel))) + (tr(", con ingreso en prisión") if nivel >= 4 else ""))
        if dura:
            texto = (tr('Te entregas con las manos arriba y nadie dispara. Te esposan y te llevan a {nombre}. Con nivel de búsqueda {nivel} no hay trato que valga: sales {horas} horas después, con {multa} euros menos y sin tus armas de fuego').format(nombre=(c.nombre), nivel=(nivel), horas=(horas), multa=(multa)) + (tr(", ni las demás armas, ni el chaleco") if todas else "") + tr('. Son las {hora_txt}.').format(hora_txt=(self.hora_txt())))
        else:
            texto = tr('Te esposan y te llevan a {nombre}. Tras una noche en el calabozo sales con {multa} euros menos de multa y sin tus armas de fuego. Son las {hora_txt}.').format(nombre=(c.nombre), multa=(multa), hora_txt=(self.hora_txt()))
        if cargos:
            texto += tr(' En la multa van {v} que derribaste.').format(v=(tr('el helicóptero') if cargos == 1 else tr('los {cargos} helicópteros').format(cargos=(cargos))))
        if quitado:
            texto += tr(" También te requisan ") + tr(" y ").join(quitado) + "."
        self.app.abrir(Dialogo(self.app, [(tr("Narrador"), texto)], fin))
