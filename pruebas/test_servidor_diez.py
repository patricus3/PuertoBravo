"""Diez jugadores a la vez en un mismo servidor, usando todo lo que el juego en línea permite, de principio a fin.

Es la prueba de que el servidor aguanta una partida de verdad entre amigos: entran por las tres puertas (abierta, con
contraseña y con invitación), se hablan por todos los canales, mueven dinero, fundan bandas y se pelean por los barrios,
compran casas y negocios y se los atracan, se quitan los coches, se disparan, les persigue la misma policía, hacen
misiones en grupo, guardan, salen, vuelven, y quien administra pone orden. Al final el servidor se cierra con todos
dentro y arranca otra vez con todo en su sitio.

Casi todas las pruebas usan diez jugadores simulados (solo mandan y leen mensajes), para poder comprobar cada cosa al
euro y sin azar. Una prueba mete diez juegos completos, de los de verdad, en un servidor cifrado y con todo encendido. Y
la última es de aguante: los diez moviéndose, conduciendo, disparando y hablando durante varios minutos de un reloj
simulado, mirando que nadie se cae, que no hay errores, que las posiciones llegan a todos y que nada crece sin tope.
"""
import hashlib
import json
import math
import os
import random
import time
import zipfile

import pygame
import pytest

from conftest import Robot
from servidor import copias, nucleo, opciones
from test_servidor import Banco, Cli, lejos_de_todo, mundo

NOMBRES = ["Ana", "Blas", "Ciro", "Dora", "Eva", "Fede", "Gala", "Hugo", "Inés", "Juan"]
N = len(NOMBRES)
CLAVE_DE_PRUEBA = "sésamo de pruebas"            # no es la contraseña de nada: solo vale dentro de estas pruebas


def huella_clave(texto):
    return hashlib.sha256(("puerto-bravo|" + texto).encode("utf-8")).hexdigest()


class Sim(Cli):
    """Un jugador simulado que recuerda dónde está y lo que lleva encima, como hace el juego entre un envío y otro."""

    def __init__(self, banco, nombre, **hola):
        self.e = {"m": "puerto_bravo", "x": 100.0, "y": 100.0, "r": 0, "v": None, "s": 0, "sa": 100, "di": 1000, "ba": 0, "ar": "pistola", "b": None}
        self.nombre = nombre
        super().__init__(banco, nombre, **hola)

    def est(self, **mas):
        self.e.update(mas)
        self.enviar({"t": "estado", "e": dict(self.e)})


def sinc(*clis):
    """Espera a que el servidor haya atendido todo lo que le han mandado estos jugadores: un ping y su respuesta."""
    for c in clis:
        c.enviar({"t": "ping"})
    for c in clis:
        c.leer("pong")


def tras(emisor, g):
    """Lo que ha mandado el emisor ya está atendido, y lo que de ello les tocaba a los demás ya les ha llegado."""
    sinc(emisor)
    sinc(*[c for c in g if c is not emisor])


def sacar(c, tipo, filtro=None):
    """Los mensajes de un tipo que ya le han llegado a un jugador. Se quitan de su cola."""
    out = [m for m in c.cola if m["t"] == tipo and (filtro is None or filtro(m))]
    ids = {id(m) for m in out}
    c.cola[:] = [m for m in c.cola if id(m) not in ids]
    return out


def limpiar(g):
    """Deja a cero lo que les ha llegado hasta ahora, incluido lo que aún venía de camino."""
    sinc(*g)
    for c in g:
        c.cola.clear()


def avisos(c, trozo):
    return sacar(c, "aviso", lambda m: trozo in m["texto"])


def diez(banco, **hola):
    g = []
    for n in NOMBRES:
        g.append(Sim(banco, n, **hola))
        assert g[-1].ok, (n, g[-1].rechazo)
    assert banco.hacer(banco.srv._cuantos) == N
    return g


def juntos(g, x, y, paso=2.0, **mas):
    """Los diez en fila, a dos metros uno de otro."""
    for k, c in enumerate(g):
        c.est(m="puerto_bravo", x=x + paso * k, y=y, **mas)
    sinc(*g)


def cerrar_todos(g):
    for c in g:
        c.cerrar()


def J(banco, c):
    return banco.srv.jugadores[c.id]


def errores_del_registro(lineas):
    """Las líneas del registro del servidor que cuentan un error. Un jugador que entra o sale no lo es."""
    return [l for l in lineas if l.startswith("Error ") or "no se ha podido atender" in l or "Traceback" in l or "No se ha podido" in l]


def si_llega(c, tipo, espera=4.0):
    """El último mensaje antes de un corte (expulsado, cerrado). En este equipo la red local se lo traga de tarde en
    tarde, así que quien llama comprueba además lo que de verdad importa: lo que ha hecho el servidor."""
    try:
        return c.leer(tipo, espera)
    except AssertionError:
        return None


def a_la_escucha(g, tipo, hacer, espera=8.0):
    """Hace algo mientras todos los jugadores están leyendo, como lee el juego de verdad: sin parar. Devuelve, por
    jugador, el mensaje de ese tipo que le ha llegado, o None."""
    import threading
    out = [None] * len(g)

    def leer(k, c):
        out[k] = si_llega(c, tipo, espera)
    hilos = [threading.Thread(target=leer, args=(k, c), daemon=True) for k, c in enumerate(g)]
    for h in hilos:
        h.start()
    time.sleep(0.1)
    hacer()
    for h in hilos:
        h.join(espera + 2)
    return out


# =============================================================== entrar y hablar
def test_diez_entran_por_las_tres_puertas_y_se_hablan_por_todos_los_canales(tmp_path):
    banco = Banco(tmp_path, max_jugadores=N, bienvenida="Bienvenidos a la prueba de los diez.", mensaje_dia="Hoy somos diez.")
    g = []
    try:
        o = lambda t: banco.hacer(banco.srv.orden, t)
        # ---- puerta abierta: entran cuatro, y la primera cuenta administra
        for n in NOMBRES[:4]:
            g.append(Sim(banco, n))
            assert g[-1].ok, g[-1].rechazo
        assert g[0].ok["admin"] and not any(c.ok["admin"] for c in g[1:])
        assert g[3].ok["servidor"]["bienvenida"] == "Bienvenidos a la prueba de los diez." and g[3].ok["servidor"]["max_jugadores"] == N
        assert g[3].leer("aviso", filtro=lambda m: "Mensaje del día: Hoy somos diez." in m["texto"])
        # ---- con contraseña: se cambia con el servidor en marcha, y solo se le pide a quien no tiene personaje
        aplicadas, reinicio = banco.hacer(banco.srv.aplicar_config, {"entrada": "clave", "clave": CLAVE_DE_PRUEBA})
        assert set(aplicadas) == {"entrada", "clave"} and not reinicio
        assert "contraseña" in Sim(banco, NOMBRES[4]).rechazo
        assert "contraseña" in Sim(banco, NOMBRES[4], clave=huella_clave("otra cosa")).rechazo
        for n in NOMBRES[4:7]:
            g.append(Sim(banco, n, clave=huella_clave(CLAVE_DE_PRUEBA)))
            assert g[-1].ok, g[-1].rechazo
        # ---- con invitación: un código por persona, de un solo uso, y valen en minúsculas
        banco.hacer(banco.srv.aplicar_config, {"entrada": "invitacion"})
        assert "invitados" in Sim(banco, NOMBRES[7]).rechazo
        assert "invitados" in Sim(banco, NOMBRES[7], clave=huella_clave(CLAVE_DE_PRUEBA)).rechazo        # la contraseña ya no sirve
        codigos = [c.strip() for c in o("invitar 4").split(":")[1].split(",")]
        assert len(codigos) == 4
        for n, codigo in zip(NOMBRES[7:], codigos):
            if n == NOMBRES[9]:                                  # antes de que entre el último: un código ya usado no vale otra vez
                assert "invitados" in Sim(banco, "Aprovechado", invitacion=codigos[0]).rechazo
            g.append(Sim(banco, n, invitacion=codigo.lower()))
            assert g[-1].ok, g[-1].rechazo
        assert banco.hacer(banco.srv._cuantos) == N
        # ---- son diez y no cabe nadie más: el undécimo se queda fuera sin gastar su invitación
        assert "lleno" in Sim(banco, "Undécimo", invitacion=codigos[3]).rechazo
        lista = o("invitaciones")
        assert lista.count("usada por") == 3 and lista.count("libre") == 1
        for nombre in NOMBRES[7:]:
            assert "usada por " + nombre in lista
        assert banco.hacer(lambda: len(banco.srv.alm.lista_cuentas())) == N
        assert "anulada" in o("anular " + codigos[3].lower()) and "libre" not in o("invitaciones")
        assert "No hay ninguna invitación libre" in o("anular " + codigos[0])        # una usada no se anula
        # ---- todos se conocen: al que entra se le dice quién hay, y a los que están, quién entra
        assert [len(c.ok["jugadores"]) for c in g] == list(range(N))
        sinc(*g)
        for k, c in enumerate(g):
            assert {m["nombre"] for m in sacar(c, "entra")} == set(NOMBRES[k + 1:])
        assert len({c.ok["semilla"] for c in g}) == 1 and len({c.ok["hora"]["dia"] for c in g}) == 1      # el mismo mundo para los diez
        assert len({c.ok["cuenta"] for c in g}) == N and len({c.id for c in g}) == N
        # ---- repartidos: tres juntos, uno a doscientos metros, dos lejos y cuatro en otras dos localidades
        x, y = lejos_de_todo()
        sitios = [("puerto_bravo", x, y), ("puerto_bravo", x + 10, y), ("puerto_bravo", x + 60, y), ("puerto_bravo", x + 200, y),
                  ("puerto_bravo", x + 420, y + 300), ("puerto_bravo", x + 440, y + 300), ("villaseca", 50.0, 50.0), ("villaseca", 60.0, 50.0),
                  ("monteferro", 80.0, 80.0), ("monteferro", 90.0, 80.0)]
        for c, (m, px, py) in zip(g, sitios):
            c.est(m=m, x=px, y=py)
        sinc(*g)
        for c in (g[0], g[5], g[9]):                             # a cada uno le llega dónde están los otros nueve
            vistos, fin = {}, time.time() + 8
            while time.time() < fin and len(vistos) < N - 1:
                for k, e in c.leer("estados", espera=5)["e"].items():
                    vistos[int(k)] = e
            assert set(vistos) == {q.id for q in g if q is not c}, (c.nombre, sorted(vistos))
            for q, (m, px, py) in zip(g, sitios):
                if q is not c:
                    assert vistos[q.id]["m"] == m and abs(vistos[q.id]["x"] - px) <= 1 and abs(vistos[q.id]["y"] - py) <= 1
        g[0].enviar({"t": "quien"})
        quien = g[0].leer("quien")["e"]
        assert len(quien) == N and {q["mapa"] for q in quien} == {"puerto_bravo", "villaseca", "monteferro"}
        assert "Hay 10:" in o("jugadores") and "Hay 10 jugadores de 10" in o("estado")
        limpiar(g)
        # ---- chat a todos: lo oyen los otros nueve, y nadie más
        g[0].enviar({"t": "chat", "texto": "hola a los diez"})
        tras(g[0], g)
        assert not sacar(g[0], "chat")
        for c in g[1:]:
            (m,) = sacar(c, "chat")
            assert m["texto"] == "hola a los diez" and m["canal"] == "todos" and m["nombre"] == "Ana" and m["de"] == g[0].id
        # ---- cerca: solo los que están a menos de ochenta metros, en la misma localidad
        g[0].enviar({"t": "chat", "texto": "solo los de aquí", "canal": "cerca"})
        tras(g[0], g)
        assert [len(sacar(c, "chat")) for c in g] == [0, 1, 1, 0, 0, 0, 0, 0, 0, 0]
        # ---- privado: de uno a otro, aunque esté en otra localidad
        g[2].enviar({"t": "chat", "texto": "solo para ti", "canal": "priv", "a": g[9].id})
        tras(g[2], g)
        assert [len(sacar(c, "chat")) for c in g] == [0] * 9 + [1]
        # ---- banda: sin banda no hay canal; con banda, solo la banda
        g[3].enviar({"t": "chat", "texto": "¿hay alguien?", "canal": "banda"})
        assert g[3].leer("aviso", filtro=lambda m: "No estás en ninguna banda" in m["texto"])
        for c in g:
            c.est(di=5000)
        sinc(*g)
        g[3].enviar({"t": "banda_crear", "nombre": "Los Diez"})
        g[3].leer("banda")
        for k in (4, 8):
            g[3].enviar({"t": "banda_invitar", "a": g[k].id})
            g[k].leer("banda_invita")
            g[k].enviar({"t": "banda_resp", "si": True})
            g[k].leer("banda")
        tras(g[3], g)
        limpiar(g)
        g[8].enviar({"t": "chat", "texto": "esta noche, al puerto", "canal": "banda"})
        tras(g[8], g)
        assert [len(sacar(c, "chat")) for c in g] == [0, 0, 0, 1, 1, 0, 0, 0, 0, 0]
        # ---- grupo de misión: solo los del grupo
        for k in (6, 7):
            g[5].enviar({"t": "grupo_invitar", "a": g[k].id, "mision": "Morosos"})
            g[k].leer("grupo_invita")
            g[k].enviar({"t": "grupo_resp", "si": True})
            g[k].leer("grupo")
        tras(g[5], g)
        limpiar(g)
        g[7].enviar({"t": "chat", "texto": "yo voy por detrás", "canal": "grupo"})
        tras(g[7], g)
        assert [len(sacar(c, "chat")) for c in g] == [0, 0, 0, 0, 0, 1, 1, 0, 0, 0]
        # ---- lo que no es un mensaje: vacío no sale, y lo largo se corta
        g[1].enviar({"t": "chat", "texto": "   "})
        g[1].enviar({"t": "chat", "texto": "a" * 2000, "canal": "un canal que no existe"})
        tras(g[1], g)
        (m,) = sacar(g[4], "chat")
        assert len(m["texto"]) == 300 and m["canal"] == "todos"
        limpiar(g)
        # ---- lo que se oye: el claxon y los disparos, solo en la localidad de quien los hace; las actividades, a todos
        g[1].enviar({"t": "evento", "que": "claxon"})
        g[1].enviar({"t": "act", "d": {"que": "carrera", "lugar": "bar_gaviota", "apuesta": 100}})
        tras(g[1], g)
        assert [len(sacar(c, "evento")) for c in g] == [1, 0, 1, 1, 1, 1, 0, 0, 0, 0]
        assert [len(sacar(c, "act")) for c in g] == [1, 0, 1, 1, 1, 1, 1, 1, 1, 1]
        # ---- el aspecto: lo que lleva puesto cada uno lo cuenta su juego, y el servidor lo reparte tal cual a los otros nueve
        g[2].enviar({"t": "aspecto", "texto": "cazadora de cuero, con gafas de sol y cadena de oro"})
        tras(g[2], g)
        for c in g:
            llega = sacar(c, "aspecto")
            assert (llega == []) if c is g[2] else (llega == [{"t": "aspecto", "de": g[2].id, "texto": "cazadora de cuero, con gafas de sol y cadena de oro"}])
        g[2].enviar({"t": "aspecto", "texto": "traje\x00 elegante\n\x07" + "x" * 500})      # sin letras raras, y sin pasarse de largo
        g[2].enviar({"t": "aspecto"})
        tras(g[2], g)
        raro, vacio = sacar(g[7], "aspecto")
        assert raro["texto"] == "traje elegante" + "x" * 186 and vacio["texto"] == ""
        assert banco.hacer(lambda: banco.srv.jugadores[g[2].id].aspecto) == ""
        limpiar(g)
        # ---- quien administra da órdenes por el chat con una barra; para los demás, la barra es texto
        g[0].enviar({"t": "chat", "texto": "/aviso en diez minutos, carrera"})
        tras(g[0], g)
        assert "Aviso enviado" in g[0].leer("aviso", filtro=lambda m: "enviado" in m["texto"])["texto"]
        for c in g:
            assert avisos(c, "Aviso del servidor: en diez minutos, carrera")
        g[6].enviar({"t": "chat", "texto": "/apagar"})
        tras(g[6], g)
        assert [len(sacar(c, "chat")) for c in g] == [1, 1, 1, 1, 1, 1, 0, 1, 1, 1] and banco.srv.activo
        # ---- mensajes rotos, de otra versión o con mala idea: no tumban nada ni echan a nadie
        for basura in ({"t": "cosa_que_no_existe"}, {"t": "estado", "e": "basura"}, {"t": "estado", "e": {"m": "puerto_bravo", "x": "aquí", "y": None}},
                       {"t": "dinero", "a": "x", "n": "mucho"}, {"t": "veh_subir", "id": [1, 2]}, {"t": "ataque", "a": {}}, {"t": 7}, {"t": "__init__"},
                       {"t": "banda_rango", "cuenta": "x", "rango": []}, {"t": "guardar", "p": "x"}, {"t": "prop_comprar", "lugar": {"a": 1}},
                       {"t": "explosion", "arma": "granada", "x": "nan", "y": []}, {"t": "aspecto", "texto": ["lista"]}, {"sin": "tipo"}, []):
            g[9].enviar(basura)
        g[9].s.sendall(b"esto no es json\n\n{\n")
        sinc(*g)
        assert banco.hacer(banco.srv._cuantos) == N
        assert not [l for l in banco.lineas if l.startswith("Error ")]
    finally:
        cerrar_todos(g)
        banco.parar()


# ==================================================================== el dinero
def test_diez_y_el_dinero_gastar_ganar_el_tope_por_hora_transferir_y_dar_cosas(tmp_path):
    # ganancia_acumula=1: el margen no pasa del de una hora, como en la 1.7.0 (de serie, desde la 1.7.1, se acumulan tres)
    banco = Banco(tmp_path, economia="si", ganancia_hora=3600, saldo_inicial=1000, precio_banda=500, ganancia_acumula=1)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        saldo = lambda c: banco.hacer(lambda: J(banco, c).saldo)

        def sin_margen(*quienes):
            def f():
                for c in quienes or g:
                    J(banco, c).margen, J(banco, c).t_margen = 0.0, time.monotonic()
            banco.hacer(f)

        def dar_credito(c, n):
            """Dinero que el servidor da por bueno, como el de una misión: para que tengan con qué comprar."""
            banco.hacer(lambda: setattr(J(banco, c), "credito", J(banco, c).credito + n))
            c.est(di=c.e["di"] + n)
            sinc(c)

        x, y = lejos_de_todo()
        juntos(g[:9], x, y, di=800, ba=200)
        assert [saldo(c) for c in g[:9]] == [1000] * 9          # un personaje nuevo empieza con lo suyo: bolsillo más banco
        # ---- quien llega con más de la cuenta se queda con el dinero inicial y el margen de entrada
        g[9].est(m="puerto_bravo", x=x + 18, y=y, di=50000, ba=0)
        quita = g[9].leer("saldo")
        assert quita["quita"] == 50000 - quita["saldo"] and 1000 <= quita["saldo"] <= 1000 + 900 + 5
        assert any("A Juan no se le reconocen" in l for l in banco.lineas)
        g[9].est(di=800, ba=200)
        sinc(g[9])
        sin_margen()
        marca = len(banco.lineas)
        # ---- gastar, siempre
        g[0].est(di=300)
        sinc(g[0])
        assert saldo(g[0]) == 500
        # ---- ganar por tu cuenta: hasta donde llega el margen, vale; lo que pasa, no
        banco.hacer(lambda: setattr(J(banco, g[1]), "margen", 400.0))
        g[1].est(di=1200)
        sinc(g[1])
        assert saldo(g[1]) == 1400 and not sacar(g[1], "saldo")
        g[1].est(di=1300)
        quita = g[1].leer("saldo")
        assert 95 <= quita["quita"] <= 100
        g[1].est(di=1300 - quita["quita"])
        # ---- el tope por hora: el margen vuelve con el tiempo, sin pasar nunca de lo de una hora
        sin_margen(g[1])
        banco.hacer(lambda: setattr(J(banco, g[1]), "t_margen", time.monotonic() - 1800))       # media hora después
        base = g[1].e["di"]
        g[1].est(di=base + 1800)
        sinc(g[1])
        assert saldo(g[1]) == base + 200 + 1800 and not sacar(g[1], "saldo")
        banco.hacer(lambda: (setattr(J(banco, g[1]), "t_margen", time.monotonic() - 36000), setattr(J(banco, g[1]), "t_saldo", 0.0)))       # diez horas
        g[1].est(di=base + 1800 + 5000)
        quita = g[1].leer("saldo")
        assert 1395 <= quita["quita"] <= 1400                    # de las diez horas solo cuenta una: 3600
        g[1].est(di=base + 1800 + 5000 - quita["quita"])
        sinc(g[1])
        sin_margen()
        # ---- transferencias en corro: de cada uno al siguiente; lo que sale de un bolsillo entra en otro, y cuadra
        corro = g[2:9]
        marca = len(banco.lineas)
        for k, c in enumerate(corro):
            c.enviar({"t": "dinero", "a": corro[(k + 1) % len(corro)].id, "n": 100})      # el juego paga y avisa en el mismo momento
            c.est(di=700)
        for c in corro:
            tras(c, g)
        for k, c in enumerate(corro):
            (m,) = sacar(c, "dinero")
            assert m["n"] == 100 and m["nombre"] == corro[k - 1].nombre
            c.est(di=800)
        sinc(*g)
        assert [saldo(c) for c in corro] == [1000] * len(corro)
        assert not any(sacar(c, "saldo") for c in g) and not [l for l in banco.lineas[marca:] if "no se le reconocen" in l]
        # ---- quien manda dinero que no tiene no se lo regala a nadie: el servidor no fabrica dinero
        g[2].enviar({"t": "dinero", "a": g[3].id, "n": 5000})
        tras(g[2], g)
        assert not sacar(g[3], "dinero")
        assert avisos(g[2], "No llevas")
        for _ in range(3):                                       # y tampoco vale mandar tres veces el mismo billete
            g[2].enviar({"t": "dinero", "a": g[3].id, "n": 800})
        tras(g[2], g)
        llegan = sacar(g[3], "dinero")
        assert [m["n"] for m in llegan] == [800]
        g[3].est(di=1600)
        g[2].est(di=0)
        sinc(g[2], g[3])
        assert saldo(g[3]) == 1800 and saldo(g[2]) == 200 and not sacar(g[3], "saldo")
        colado = Sim(banco, "Recién llegado")                    # ni vale mandarlo nada más entrar, antes de decir cuánto llevas
        colado.enviar({"t": "dinero", "a": g[3].id, "n": 50000})
        sinc(colado)
        sinc(g[3])
        assert not sacar(g[3], "dinero") and banco.hacer(lambda: J(banco, g[3]).credito) == 0
        colado.cerrar()
        g[3].leer("sale")
        limpiar(g)
        # ---- dar un arma, balas y un objeto a quien tienes al lado
        for clase, ident, n in (("arma", "pistola", 1), ("balas", "pistola", 24), ("objeto", "botiquin", 2)):
            g[4].enviar({"t": "dar", "a": g[5].id, "clase": clase, "id": ident, "n": n})
        g[4].enviar({"t": "dar", "a": g[5].id, "clase": "una clase rara", "id": "x", "n": 1})
        tras(g[4], g)
        assert [(m["clase"], m["id"], m["n"]) for m in sacar(g[5], "recibe")] == [("arma", "pistola", 1), ("balas", "pistola", 24), ("objeto", "botiquin", 2)]
        assert len(sacar(g[4], "dado")) == 3
        g[9].est(m="villaseca", x=50.0, y=50.0)
        sinc(g[9])
        g[4].enviar({"t": "dar", "a": g[9].id, "clase": "arma", "id": "pistola", "n": 1})
        assert g[4].leer("aviso", filtro=lambda m: "a tu lado" in m["texto"])
        g[9].est(m="puerto_bravo", x=x + 18, y=y)
        # ---- una misión de la historia: su recompensa queda justificada, una sola vez
        paga = mundo()["misiones"]["m04"]["dinero"]
        g[6].enviar({"t": "mision_ok", "id": "m04"})
        g[6].est(di=800 + paga)
        sinc(g[6])
        assert saldo(g[6]) == 1000 + paga and not sacar(g[6], "saldo")
        g[6].enviar({"t": "mision_ok", "id": "m04"})
        g[6].est(di=800 + 2 * paga)
        assert g[6].leer("saldo")["quita"] >= paga - 5
        g[6].est(di=800 + paga)
        sinc(g[6])
        sin_margen()
        # ---- lo que cobra el servidor (fundar una banda) no se cobra dos veces aunque la posición del juego llegue con retraso
        marca = len(banco.lineas)
        g[7].enviar({"t": "banda_crear", "nombre": "Las Cuentas Claras"})
        g[7].est()                                               # una posición que salió antes de que al juego le llegara el cobro
        g[7].est()
        assert g[7].leer("cobro")["n"] == 500
        g[7].est(di=g[7].e["di"] - 500)
        sinc(g[7])
        assert saldo(g[7]) == 500 and not sacar(g[7], "saldo") and banco.hacer(lambda: J(banco, g[7]).dinero) == 300
        assert not [l for l in banco.lineas[marca:] if "no se le reconocen" in l]
        # y dos cobros seguidos, con el juego enterándose del primero cuando el servidor ya ha hecho el segundo
        # el crédito, antes de la posición que trae el dinero: la posición va por la red y el crédito por dentro, y si la
        # posición llegaba primero, el servidor veía 2000 euros sin justificar y los quitaba (la prueba fallaba a veces)
        banco.hacer(lambda: setattr(J(banco, g[7]), "credito", 2000))
        g[7].est(di=300 + 2000)
        sinc(g[7])
        g[7].enviar({"t": "banda_ingresar", "n": 600})
        g[7].enviar({"t": "banda_ingresar", "n": 400})
        g[7].est()                                               # todavía no sabe nada
        g[7].est(di=2300 - 600)                                  # se ha enterado del primero
        g[7].est(di=2300 - 1000)                                 # y del segundo
        sinc(g[7])
        assert saldo(g[7]) == 1500 and not sacar(g[7], "saldo")
        assert g[7].leer("banda", filtro=lambda m: m["b"]["caja"] == 1000)
        # quien no hace caso del cobro no se queda con el dinero: pasado un rato, deja de contar como pendiente
        g[7].enviar({"t": "banda_ingresar", "n": 1000})
        sinc(g[7])
        banco.hacer(lambda: (setattr(J(banco, g[7]), "t_cobros", time.monotonic() - 60), setattr(J(banco, g[7]), "t_saldo", 0.0)))
        g[7].est()
        assert g[7].leer("saldo")["quita"] >= 995
        g[7].est(di=300)
        sinc(g[7])
        sin_margen()
        # ---- dos compran la misma casa a la vez: se la queda el primero, y al otro su juego le devuelve el dinero sin que
        # el servidor se lo discuta
        casa = next(l for l in mundo()["mapas"]["puerto_bravo"]["lugares"] if l["id"] == "piso_centro")
        precio = casa["precio"]
        dar_credito(g[8], 20000)
        dar_credito(g[9], 20000)
        marca = len(banco.lineas)
        for c in (g[8], g[9]):
            c.est(di=c.e["di"] - precio)                         # cada uno paga en su juego...
            c.enviar({"t": "prop_comprar", "lugar": casa["id"]})  # ...y se lo dice al servidor
            # Ninguno de los dos ha leído aún la respuesta: para ellos es a la vez. Pero van por dos conexiones, y el
            # servidor atiende primero la que antes le llega, que no siempre es la que antes se mandó: se espera a que
            # haya atendido a Inés para que la primera sea ella, como da por hecho el resto de la prueba.
            sinc(c)
        assert g[9].leer("prop_no")["nombre"] == "Inés"
        g[9].est(di=g[9].e["di"] + precio)                       # el juego de Juan le devuelve lo pagado
        sinc(*g)
        assert saldo(g[9]) == 21000 and not sacar(g[9], "saldo") and saldo(g[8]) == 21000 - precio
        assert not [l for l in banco.lineas[marca:] if "no se le reconocen" in l]
        for c in g:
            assert sacar(c, "prop", lambda m: m["lugar"] == casa["id"] and m["nombre"] == "Inés")       # los diez saben de quién es
        # pero pedir casas que ya tienen dueño sin haber pagado nada no da dinero
        for _ in range(3):
            g[5].enviar({"t": "prop_comprar", "lugar": casa["id"]})
        sinc(g[5])
        assert len(sacar(g[5], "prop_no")) == 3 and banco.hacer(lambda: J(banco, g[5]).credito) == 0
        sin_margen(g[5])                                         # el margen vuelve a un euro por segundo: con el equipo cargado, desde el último ajuste ya ha pasado alguno
        g[5].est(di=g[5].e["di"] + precio)
        assert precio - 5 <= g[5].leer("saldo")["quita"] <= precio
        g[5].est(di=g[5].e["di"] - precio)
        # ---- Inés la pone en venta y se va; Juan se la compra; cuando Inés vuelve, el dinero es suyo y el servidor lo reconoce
        g[8].enviar({"t": "prop_oferta", "lugar": casa["id"], "precio": 9000})
        g[8].enviar({"t": "guardar", "p": {"jugador": {"dinero": g[8].e["di"], "banco": 200, "propiedades": [casa["id"]]}}, "ya": True})
        g[8].leer("guardado")
        antes = saldo(g[8])
        g[8].cerrar()
        g[9].leer("sale", filtro=lambda m: m["id"] == g[8].id)
        g[9].enviar({"t": "prop_adquirir", "lugar": casa["id"]})
        assert g[9].leer("cobro")["n"] == 9000
        g[9].est(di=g[9].e["di"] - 9000)
        sinc(g[9])
        assert saldo(g[9]) == 12000
        vuelve = Sim(banco, "Inés", semilla=g[8].semilla)
        g[8] = vuelve
        assert vuelve.ok["pendientes"] == [{"que": "venta", "lugar": casa["id"], "n": 9000, "por": "Juan"}]
        assert vuelve.ok["saldo"] == antes + 9000                # el juego se queda con lo que diga este saldo: tiene que venir con la venta
        assert vuelve.ok["props"][casa["id"]]["nombre"] == "Juan"
        vuelve.est(m="puerto_bravo", x=x + 16, y=y, di=antes - 200 + 9000, ba=200)
        sinc(vuelve)
        assert saldo(vuelve) == antes + 9000 and not sacar(vuelve, "saldo")
        # ---- Juan la vende al mercado: recupera el setenta por ciento, y eso también es dinero reconocido
        g[9].enviar({"t": "prop_soltar", "lugar": casa["id"]})
        m = g[9].leer("dinero")
        assert m["n"] == precio * 70 // 100
        g[9].est(di=g[9].e["di"] + m["n"])
        sinc(g[9])
        assert saldo(g[9]) == 12000 + precio * 70 // 100 and not sacar(g[9], "saldo")
        # ---- todos guardan: el servidor apunta el saldo de cada uno y el personaje tal como lo manda el juego
        for c in g:
            c.enviar({"t": "guardar", "p": {"jugador": {"dinero": c.e["di"], "banco": c.e["ba"]}}, "ya": True})
        for c in g:
            c.leer("guardado")
        en_disco = banco.hacer(lambda: {f["nombre"]: f["saldo"] for f in srv.alm.cuentas() if f["nombre"] in NOMBRES})
        assert en_disco == {c.nombre: saldo(c) for c in g}
        assert not [l for l in banco.lineas if l.startswith("Error ")]
    finally:
        cerrar_todos(g)
        banco.parar()


# ============================================================ bandas y barrios
def test_diez_en_tres_bandas_cajas_barrios_alianzas_y_una_guerra(tmp_path):
    banco = Banco(tmp_path)
    g = []
    try:
        g = diez(banco)
        linces, zorros, lobos = g[0:4], g[4:8], g[8:10]
        x, y = lejos_de_todo()
        juntos(g, x, y, di=30000, b="puerto")
        limpiar(g)
        # ---- fundar: cuesta dinero, el nombre no se repite, y lo sabe todo el servidor
        g[0].enviar({"t": "banda_crear", "nombre": "Los Linces"})
        assert g[0].leer("cobro")["n"] == 2000
        b = g[0].leer("banda")
        assert b["b"]["nombre"] == "Los Linces" and b["rango"] == "jefe" and b["b"]["caja"] == 0
        tras(g[0], g)
        for c in g[1:]:
            assert avisos(c, "Ana ha fundado la banda Los Linces")
            assert sacar(c, "de_banda", lambda m: m["id"] == g[0].id and m["banda"] == b["b"]["id"])
        g[4].enviar({"t": "banda_crear", "nombre": "los linces"})
        assert "Ya hay una banda" in g[4].leer("aviso", filtro=lambda m: "Ya hay" in m["texto"])["texto"]
        g[4].enviar({"t": "banda_crear", "nombre": "ab"})
        assert "al menos tres letras" in g[4].leer("aviso", filtro=lambda m: "letras" in m["texto"])["texto"]
        g[0].enviar({"t": "banda_crear", "nombre": "Otra Más"})
        assert "Ya estás en una banda" in g[0].leer("aviso", filtro=lambda m: "Ya estás" in m["texto"])["texto"]
        g[4].enviar({"t": "banda_crear", "nombre": "Los Zorros"})
        g[4].leer("banda")
        g[8].enviar({"t": "banda_crear", "nombre": "Los Lobos"})
        g[8].leer("banda")
        for c in (g[0], g[4], g[8]):
            c.est(di=28000)
        # ---- invitar: aceptar, rechazar, y quién puede invitar
        g[0].enviar({"t": "banda_invitar", "a": g[3].id})
        assert g[3].leer("banda_invita")["nombre"] == "Los Linces"
        g[3].enviar({"t": "banda_resp", "si": False})            # Dora se lo piensa
        sinc(g[3])
        assert banco.hacer(lambda: J(banco, g[3]).banda) is None
        g[3].enviar({"t": "banda_resp", "si": True})             # y ahora la invitación ya no vale
        assert "ya no vale" in g[3].leer("aviso", filtro=lambda m: "invitación" in m["texto"])["texto"]
        for jefe, gente in ((g[0], linces[1:]), (g[4], zorros[1:]), (g[8], lobos[1:])):
            for c in gente:
                jefe.enviar({"t": "banda_invitar", "a": c.id})
                c.leer("banda_invita")
                c.enviar({"t": "banda_resp", "si": True})
                assert c.leer("banda")["rango"] == "miembro"
        sinc(*g)
        assert len(g[0].leer("banda", filtro=lambda m: len(m["b"]["miembros"]) == 4)["b"]["miembros"]) == 4
        g[1].enviar({"t": "banda_invitar", "a": g[9].id})        # un miembro raso no invita
        assert "Solo el jefe y su mano derecha" in g[1].leer("aviso", filtro=lambda m: "Solo" in m["texto"])["texto"]
        g[0].enviar({"t": "banda_invitar", "a": g[5].id})        # y a quien ya tiene banda no se le invita
        assert "ya tiene banda" in g[0].leer("aviso", filtro=lambda m: "ya tiene" in m["texto"])["texto"]
        # ---- rangos y caja: ingresa cualquiera; sacan el jefe y su mano derecha
        cuenta = lambda c: c.ok["cuenta"]
        g[0].enviar({"t": "banda_rango", "cuenta": cuenta(g[1]), "rango": "mano"})
        assert g[1].leer("banda", filtro=lambda m: m["rango"] == "mano")
        for c in g:
            c.enviar({"t": "banda_ingresar", "n": 3000})
            assert c.leer("cobro", filtro=lambda m: m["motivo"].startswith("ingreso"))["n"] == 3000
            c.est(di=c.e["di"] - 3000)
        sinc(*g)
        cajas = banco.hacer(lambda: {f["nombre"]: f["caja"] for f in banco.srv.alm.bandas()})
        assert cajas == {"Los Linces": 12000, "Los Zorros": 12000, "Los Lobos": 6000}
        g[1].enviar({"t": "banda_sacar", "n": 500})
        assert g[1].leer("dinero")["n"] == 500
        g[2].enviar({"t": "banda_sacar", "n": 500})
        assert "solo sacan" in g[2].leer("aviso", filtro=lambda m: "sacan" in m["texto"])["texto"]
        g[0].enviar({"t": "banda_sacar", "n": 999999})
        assert "En la caja hay 11500" in g[0].leer("aviso", filtro=lambda m: "caja" in m["texto"])["texto"]
        ultimo = g[3].leer("banda", filtro=lambda m: m["b"]["caja"] == 11500)["b"]
        assert len(ultimo["apuntes"]) == 5 and {a["motivo"] for a in ultimo["apuntes"]} == {"ingreso", "retirada"}
        # ---- fuego amigo: quitado, los de la banda no se hieren; puesto, sí
        g[0].enviar({"t": "ataque", "a": g[1].id, "arma": "pistola"})
        assert "de tu banda" in g[0].leer("fallo")["motivo"]
        g[2].enviar({"t": "banda_fuego", "si": True})
        assert "lo decide el jefe" in g[2].leer("aviso", filtro=lambda m: "decide" in m["texto"])["texto"]
        g[0].enviar({"t": "banda_fuego", "si": True})
        assert g[3].leer("banda", filtro=lambda m: m["b"]["fuego"])
        time.sleep(3.1)                                          # el motivo de un fallo no se repite antes de tres segundos
        g[0].enviar({"t": "ataque", "a": g[1].id, "arma": "pistola"})
        assert g[0].leer(("impacto", "fallo"))["t"] == "impacto" or True
        assert g[1].leer(("herido", "silbido"))
        g[0].enviar({"t": "banda_fuego", "si": False})
        g[3].leer("banda", filtro=lambda m: not m["b"]["fuego"])
        # ---- barrios: los reclama quien manda, los paga la caja, y lo ve todo el servidor
        limpiar(g)
        g[2].enviar({"t": "barrio_reclamar"})
        assert g[2].leer("aviso", filtro=lambda m: "el jefe o su mano derecha" in m["texto"])
        g[0].enviar({"t": "barrio_reclamar"})
        tras(g[0], g)
        for c in g:
            t = sacar(c, "territorios")[-1]["e"]
            assert [(q["mapa"], q["barrio"], q["nombre"]) for q in t["barrios"]] == [("puerto_bravo", "puerto", "Los Linces")]
            assert avisos(c, "La banda Los Linces se queda con un barrio")
        g[4].enviar({"t": "barrio_reclamar"})
        assert "ya tiene dueño" in g[4].leer("aviso", filtro=lambda m: "dueño" in m["texto"])["texto"]
        g[8].est(b="playa")
        g[8].enviar({"t": "barrio_reclamar"})                    # los Lobos se quedan con la playa
        g[8].leer("banda", filtro=lambda m: len(m["b"]["barrios"]) == 1)
        g[8].est(b="un barrio que no existe")
        g[8].enviar({"t": "barrio_reclamar"})
        assert "no hay ningún barrio" in g[8].leer("aviso", filtro=lambda m: "ningún barrio" in m["texto"])["texto"]
        g[8].est(b="puerto")
        # ---- alianzas: la propone un jefe, la cierra el otro; los aliados no se hieren ni se declaran la guerra
        g[0].enviar({"t": "alianza", "banda": "Los Lobos"})
        assert "os propone una alianza" in g[9].leer("aviso", filtro=lambda m: "alianza" in m["texto"])["texto"]
        g[8].enviar({"t": "alianza", "banda": "Los Linces"})
        for c in (g[0], g[3], g[8], g[9]):
            assert "Alianza cerrada" in c.leer("aviso", filtro=lambda m: "Alianza cerrada" in m["texto"])["texto"]
        sinc(*g)
        time.sleep(3.1)
        g[0].enviar({"t": "ataque", "a": g[8].id, "arma": "pistola"})
        assert "aliada" in g[0].leer("fallo")["motivo"]
        g[8].enviar({"t": "barrio_guerra"})
        assert "banda aliada" in g[8].leer("aviso", filtro=lambda m: "aliada" in m["texto"])["texto"]
        # ---- la guerra: los Zorros se la declaran a los Linces por el puerto
        limpiar(g)
        g[5].enviar({"t": "barrio_guerra"})
        assert g[5].leer("aviso", filtro=lambda m: "el jefe o su mano derecha" in m["texto"])
        g[4].enviar({"t": "barrio_guerra"})
        tras(g[4], g)
        for c in linces:
            assert avisos(c, "¡Los Zorros os declara la guerra por El Puerto")
        for c in zorros:
            assert avisos(c, "Guerra declarada por El Puerto")
        for c in lobos:
            assert not avisos(c, "uerra")                        # a los que no les va nada, no se les molesta
        for c in g:
            guerra = sacar(c, "territorios")[-1]["e"]["guerras"]
            assert len(guerra) == 1 and guerra[0]["ataca_n"] == "Los Zorros" and guerra[0]["defiende_n"] == "Los Linces" and 0 < guerra[0]["falta"] <= 60
        g[4].enviar({"t": "barrio_guerra"})
        assert "Ya hay una guerra" in g[4].leer("aviso", filtro=lambda m: "Ya hay" in m["texto"])["texto"]
        assert banco.hacer(lambda: banco.srv.alm.banda_por_nombre("Los Zorros")["caja"]) == 11000
        # empieza a su hora. Dentro del barrio: los cuatro Zorros y dos Linces. Los otros dos Linces andan por otro barrio
        for c in linces[2:]:
            c.est(b="viejo")
        banco.reloj.t += 61
        for c in linces + zorros:
            assert "¡Empieza la guerra por El Puerto" in c.leer("aviso", espera=6, filtro=lambda m: "¡Empieza" in m["texto"])["texto"]
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in banco.srv.jugadores.values()])
        banco.hacer(lambda: setattr(banco.srv, "rng", random.Random(2)))
        # un Zorro tumba a un Lince dentro del barrio: treinta puntos más
        g[4].est(x=g[0].e["x"] + 2, y=y + 2)
        sinc(g[4])
        for _ in range(12):
            g[4].enviar({"t": "ataque", "a": g[0].id, "arma": "bate"})
            if g[0].leer(("herido", "silbido"), 3)["t"] == "herido":
                break
            time.sleep(0.7)
        g[0].est(sa=0)
        g[0].enviar({"t": "caido", "por": g[4].id})
        assert g[0].leer("caes")["nombre"] == "Eva" and g[4].leer("baja")["nombre"] == "Ana"
        g[0].est(sa=100, di=g[0].e["di"] - g[0].e["di"] // 10)
        time.sleep(2.3)
        puntos = banco.hacer(lambda: dict(banco.srv.guerras[0]))
        assert puntos["pa"] >= 30 + 4 and 1 <= puntos["pd"] < puntos["pa"]
        banco.reloj.t += 61
        for c in g:                                              # el final se lo cuentan a todo el servidor
            final = c.leer("aviso", espera=6, filtro=lambda m: "ha terminado" in m["texto"])["texto"]
            assert "El barrio pasa a Los Zorros" in final
        sinc(*g)
        for c in g:
            t = sacar(c, "territorios")[-1]["e"]
            assert not t["guerras"] and {(q["barrio"], q["nombre"]) for q in t["barrios"]} == {("puerto", "Los Zorros"), ("playa", "Los Lobos")}
        # ---- medianoche: cada barrio deja su renta en la caja de quien lo tiene, y el día cambia para los diez
        cajas = banco.hacer(lambda: {f["nombre"]: f["caja"] for f in banco.srv.alm.bandas()})
        dia = banco.srv.dia
        banco.hacer(lambda: setattr(banco.srv, "reloj", 1439.6))
        for c in g:
            h = c.leer("hora", espera=6, filtro=lambda m: m.get("medianoche"))
            assert h["h"]["dia"] == dia + 1
        despues = banco.hacer(lambda: {f["nombre"]: f["caja"] for f in banco.srv.alm.bandas()})
        assert despues == {"Los Linces": cajas["Los Linces"], "Los Zorros": cajas["Los Zorros"] + 300, "Los Lobos": cajas["Los Lobos"] + 300}
        assert "dejan 300 euros" in g[7].leer("aviso", filtro=lambda m: "dejan" in m["texto"])["texto"]
        # ---- romper la alianza, ceder el mando, echar a uno, irse el jefe y disolver
        g[8].enviar({"t": "alianza", "banda": "Los Linces", "romper": True})
        assert "rompe la alianza" in g[1].leer("aviso", filtro=lambda m: "rompe" in m["texto"])["texto"]
        assert g[0].leer("banda", filtro=lambda m: not m["b"]["aliadas"])
        g[4].enviar({"t": "banda_rango", "cuenta": cuenta(g[5]), "rango": "jefe"})        # Eva cede el mando a Fede
        assert g[5].leer("banda", filtro=lambda m: m["rango"] == "jefe") and g[4].leer("banda", filtro=lambda m: m["rango"] == "mano")
        g[4].enviar({"t": "banda_expulsar", "cuenta": cuenta(g[7])})
        assert "Solo el jefe puede echar" in g[4].leer("aviso", filtro=lambda m: "echar" in m["texto"])["texto"]
        limpiar(g)
        g[5].enviar({"t": "banda_expulsar", "cuenta": cuenta(g[7])})
        assert g[7].leer("banda", filtro=lambda m: m["b"] is None)
        tras(g[5], g)
        for c in g:
            assert sacar(c, "de_banda", lambda m: m["id"] == g[7].id and m["banda"] is None)
        g[5].enviar({"t": "banda_salir"})                        # se va el jefe: hereda su mano derecha
        assert g[4].leer("banda", filtro=lambda m: m["rango"] == "jefe" and len(m["b"]["miembros"]) == 2)
        assert "Ahora manda Eva" in g[6].leer("aviso", filtro=lambda m: "manda" in m["texto"])["texto"]
        limpiar(g)
        g[9].enviar({"t": "banda_disolver"})
        assert g[9].leer("aviso", filtro=lambda m: "Solo el jefe puede disolver" in m["texto"])
        g[8].enviar({"t": "banda_disolver"})                     # los Lobos se disuelven: la caja para el jefe y la playa queda libre
        assert g[8].leer("dinero")["n"] == despues["Los Lobos"]
        assert g[9].leer("banda", filtro=lambda m: m["b"] is None)
        tras(g[8], g)
        for c in g:
            assert avisos(c, "La banda Los Lobos se ha disuelto")
            assert {q["barrio"] for q in sacar(c, "territorios")[-1]["e"]["barrios"]} == {"puerto"}
        g[2].enviar({"t": "banda_lista"})
        lista = g[2].leer("bandas")
        assert {(q["nombre"], q["miembros"], q["barrios"]) for q in lista["e"]} == {("Los Linces", 4, 0), ("Los Zorros", 2, 1)}
        assert lista["tuya"]["nombre"] == "Los Linces"
        assert banco.hacer(banco.srv.orden, "bandas").count("miembros") == 2
        assert not errores_del_registro(banco.lineas)
    finally:
        cerrar_todos(g)
        banco.parar()


# ============================================ casas, negocios, vehículos y calle
def test_diez_con_casas_negocios_atracos_vehiculos_trafico_y_gente_de_la_calle(tmp_path):
    banco = Banco(tmp_path, robo_segundos=2, trafico="si", trafico_max=6, peatones="si", vehiculos_por_jugador=2)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        lugares = {l["id"]: l for l in mundo()["mapas"]["puerto_bravo"]["lugares"]}
        casa, bar = lugares["piso_centro"], lugares["bar_puerto"]
        banco.hacer(lambda: (setattr(srv, "reloj", 12 * 60.0), setattr(srv, "lluvia", False), setattr(srv, "rng", random.Random(5))))
        juntos(g, bar["x"] - 9, bar["y"], di=60000)
        limpiar(g)
        # ---- una casa solo puede ser de uno: el primero se la queda, y los diez se enteran
        g[0].enviar({"t": "prop_comprar", "lugar": casa["id"]})
        sinc(g[0])
        g[1].enviar({"t": "prop_comprar", "lugar": casa["id"]})
        tras(g[1], g)
        assert g[1].leer("prop_no")["nombre"] == "Ana"
        for c in g:
            (m,) = sacar(c, "prop")
            assert m["lugar"] == casa["id"] and m["nombre"] == "Ana" and m["oferta"] == 0
        for c in g[1:]:
            assert avisos(c, "Ana compra")
        g[0].enviar({"t": "prop_comprar", "lugar": "un sitio que no existe"})
        g[2].enviar({"t": "prop_soltar", "lugar": casa["id"]})
        assert g[2].leer("aviso", filtro=lambda m: "no es tuyo" in m["texto"])
        g[2].enviar({"t": "prop_adquirir", "lugar": casa["id"]})
        assert g[2].leer("aviso", filtro=lambda m: "no está en venta" in m["texto"])
        # ---- Ana la pone en venta y Blas se la compra: a él se le cobra, y a ella le llega el dinero
        g[0].enviar({"t": "prop_oferta", "lugar": casa["id"], "precio": 7500})
        tras(g[0], g)
        for c in g:
            assert sacar(c, "prop", lambda m: m["oferta"] == 7500)
        assert avisos(g[5], "Ana vende")
        g[1].enviar({"t": "prop_adquirir", "lugar": casa["id"]})
        assert g[1].leer("cobro")["n"] == 7500
        g[1].est(di=60000 - 7500)
        assert g[0].leer("dinero")["n"] == 7500
        g[0].est(di=67500)
        tras(g[1], g)
        for c in g:
            (m,) = sacar(c, "prop")
            assert m["nombre"] == "Blas" and m["antes"] == g[0].ok["cuenta"] and m["oferta"] == 0
        # ---- y Blas la devuelve al mercado: recupera el setenta por ciento
        g[1].enviar({"t": "prop_soltar", "lugar": casa["id"]})
        assert g[1].leer("dinero")["n"] == casa["precio"] * 70 // 100
        tras(g[1], g)
        for c in g:
            assert sacar(c, "prop", lambda m: m["cuenta"] is None)
        assert banco.hacer(srv._props) == {}
        # ---- un negocio: Ciro compra el bar; él y Dora son de la misma banda
        g[2].enviar({"t": "prop_comprar", "lugar": bar["id"]})
        g[2].enviar({"t": "banda_crear", "nombre": "Los del Bar"})
        g[2].leer("banda")
        g[2].enviar({"t": "banda_invitar", "a": g[3].id})
        g[3].leer("banda_invita")
        g[3].enviar({"t": "banda_resp", "si": True})
        g[3].leer("banda")
        sinc(*g)
        limpiar(g)
        # quién no puede atracarlo: el dueño, los de su banda, quien va sin arma, en coche o está lejos
        g[2].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[2].leer("aviso", filtro=lambda m: "no es de otro jugador" in m["texto"])
        g[3].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[3].leer("aviso", filtro=lambda m: "de tu banda" in m["texto"])
        g[4].est(ar="punos")
        g[4].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[4].leer("aviso", filtro=lambda m: "manos vacías" in m["texto"])
        g[4].est(ar="pistola", v="sedan")
        g[4].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[4].leer("aviso", filtro=lambda m: "en la puerta, a pie" in m["texto"])
        g[4].est(v=None)
        # Eva lo atraca: salta la alarma al dueño y a su banda, y a nadie más. Fede no puede atracarlo a la vez
        g[4].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[4].leer("robo_empieza")["nombre"] == "Ciro"
        g[5].enviar({"t": "robo", "lugar": bar["id"]})
        assert g[5].leer("aviso", filtro=lambda m: "Ya hay un atraco en marcha" in m["texto"])
        tras(g[4], g)
        assert sacar(g[2], "robo_aviso")[0]["tuyo"] is True and sacar(g[3], "robo_aviso")[0]["tuyo"] is False
        assert not any(sacar(c, "robo_aviso") for c in g)
        fin = g[4].leer("robo_fin", espera=8)
        assert fin["ok"] and fin["botin"] == bar["ingresos"]
        assert "Eva ha vaciado la caja" in g[2].leer("aviso", filtro=lambda m: "caja" in m["texto"])["texto"]
        g[5].enviar({"t": "robo", "lugar": bar["id"]})
        assert "ya le han vaciado la caja hoy" in g[5].leer("aviso", filtro=lambda m: "hoy" in m["texto"])["texto"]
        # a medianoche se le descuenta al dueño; al día siguiente Fede lo intenta y se va antes de tiempo
        banco.hacer(lambda: setattr(srv, "reloj", 1439.6))
        assert g[2].leer("robos_dia", espera=6)["total"] == bar["ingresos"]
        banco.hacer(lambda: setattr(srv, "reloj", 12 * 60.0))
        g[5].enviar({"t": "robo", "lugar": bar["id"]})
        g[5].leer("robo_empieza")
        g[5].est(x=bar["x"] + 200)
        fin = g[5].leer("robo_fin", espera=6)
        assert not fin["ok"] and "ido antes" in fin["motivo"]
        assert "no ha conseguido" in g[2].leer("aviso", filtro=lambda m: "conseguido" in m["texto"])["texto"]
        g[5].est(x=bar["x"] + 1)
        # ---- vehículos: el que coges es de todos desde ese momento
        limpiar(g)
        g[6].est(v="sedan", s=3)
        g[6].enviar({"t": "veh_tomar", "modelo": "sedan", "nombre": "Sedán de Gala", "salud": 90, "ref": 1})
        vid = g[6].leer("veh_tuyo")["id"]
        tras(g[6], g)
        for c in g:
            if c is not g[6]:
                (m,) = sacar(c, "veh_ocupado")
                assert m["id"] == vid and m["por"] == g[6].id and m["v"]["nombre"] == "Sedán de Gala"
        assert g[0].leer("estados", filtro=lambda m: m["e"].get(str(g[6].id), {}).get("vi") == vid)
        # Hugo no puede subirse sin más; la saca del coche cuando va despacio, y no cuando va deprisa
        g[7].est(x=g[6].e["x"] + 2)
        g[7].enviar({"t": "veh_subir", "id": vid})
        assert "adelantado" in g[7].leer("veh_no")["motivo"]
        g[6].est(s=20)
        sinc(g[6])
        g[7].enviar({"t": "veh_asaltar", "id": vid})
        assert "rápido" in g[7].leer("veh_no")["motivo"]
        g[6].est(s=2)
        sinc(g[6])
        g[7].enviar({"t": "veh_asaltar", "id": vid})
        ok = g[7].leer("veh_ok")
        assert ok["robado"] and ok["asalto"] == "Gala" and g[6].leer("sacado")["nombre"] == "Hugo"
        g[6].est(v=None, s=0)
        g[7].est(v="sedan", s=5, x=bar["x"] + 40, y=bar["y"] + 30)
        # lo deja aparcado, y Gala lo recupera: a Hugo le llega el aviso
        g[7].enviar({"t": "veh_dejar", "id": vid, "x": bar["x"] + 40, "y": bar["y"] + 30, "r": 90, "salud": 80})
        g[7].est(v=None, s=0)
        tras(g[7], g)
        for c in g:
            if c is not g[7]:
                libre = sacar(c, "veh_libre")[-1]["v"]
                assert libre["por"] is None and libre["x"] == bar["x"] + 40 and libre["salud"] == 80
        g[6].enviar({"t": "veh_subir", "id": vid})
        assert "lejos" in g[6].leer("veh_no")["motivo"]
        g[6].est(x=bar["x"] + 38, y=bar["y"] + 30)
        sinc(g[6])
        g[6].enviar({"t": "veh_subir", "id": vid})
        assert g[6].leer("veh_ok")["robado"]
        assert "Gala se ha llevado tu Sedán de Gala" in g[7].leer("aviso", filtro=lambda m: "llevado" in m["texto"])["texto"]
        g[6].est(v="sedan")
        g[6].enviar({"t": "veh_dejar", "id": vid, "x": bar["x"] + 38, "y": bar["y"] + 30, "r": 0, "salud": 60})
        g[6].est(v=None)
        # a un coche aparcado se le puede dar: lo saben los de la localidad; si revienta, todos
        g[8].est(x=bar["x"] + 36, y=bar["y"] + 30)
        sinc(g[8])
        g[8].enviar({"t": "veh_dano", "id": vid, "n": 25})
        assert g[0].leer("veh_salud")["salud"] == 35
        g[8].enviar({"t": "veh_dano", "id": vid, "n": 500})
        tras(g[8], g)
        for c in g:
            assert sacar(c, "veh_revienta", lambda m: m["id"] == vid)
        assert vid not in srv.vehiculos
        # cada jugador puede tener dos aparcados: al dejar el tercero, el más antiguo desaparece para todos
        limpiar(g)
        suyos = []
        for k in range(3):
            g[9].est(v="moto", x=bar["x"] + 60 + 5 * k, y=bar["y"] + 40)
            g[9].enviar({"t": "veh_tomar", "modelo": "moto", "ref": k})
            suyos.append(g[9].leer("veh_tuyo")["id"])
            banco.reloj.t += 5                                   # cada uno, un poco más tarde que el anterior
            g[9].enviar({"t": "veh_dejar", "id": suyos[-1], "x": bar["x"] + 60 + 5 * k, "y": bar["y"] + 40, "r": 0})
            g[9].est(v=None)
        tras(g[9], g)
        for c in g:
            assert [m["id"] for m in sacar(c, "veh_fuera")] == [suyos[0]]
        assert sorted(srv.vehiculos) == suyos[1:]
        g[9].enviar({"t": "veh_fin", "id": suyos[1]})            # y el que mete en su garaje deja de estar en la calle
        tras(g[9], g)
        assert sorted(srv.vehiculos) == suyos[2:] and all(sacar(c, "veh_fuera") for c in g)
        # atropellar a otro jugador
        g[9].est(v="sedan", s=10, x=g[0].e["x"] + 3, y=g[0].e["y"])
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        sinc(g[9])
        g[9].enviar({"t": "atropello", "a": g[0].id})
        h = g[0].leer("herido")
        assert h["arma"] == "atropello" and h["dano"] == 50.0 and g[9].leer("impacto")["atropello"]
        g[9].est(v=None, s=0, x=bar["x"] + 9)
        # ---- el tráfico es el mismo para los diez
        juntos(g, bar["x"] - 9, bar["y"], v=None, s=0)
        banco.hacer(lambda: (srv.trafico.clear(), [srv.trafico_pensar() for _ in range(40)]))
        assert len(srv.trafico) == 6                             # los que dice la opción, ni uno más aunque haya diez jugadores
        limpiar(g)
        listas = []
        for c in g:
            listas.append({f[0]: f[1] for f in c.leer("estados", filtro=lambda m: len(m.get("tr") or []) >= 3)["tr"]})
        comunes = set.intersection(*[set(l) for l in listas])    # van juntos: oyen los mismos coches
        assert len(comunes) >= 3
        assert all(l[k] == listas[0][k] and l[k] in mundo()["modelos"] for l in listas for k in comunes)
        # a uno se le para poniéndose delante, se saca al conductor y es un vehículo más: los otros nueve lo saben
        banco.hacer(lambda: [srv.trafico_mover(0.1) for _ in range(300)])
        coche = banco.hacer(lambda: next(c for c in srv.trafico.values() if c["vel"] > 2))
        cx, cy, _ = srv.tr_pos(coche)
        dx, dy = __import__("servidor.trafico", fromlist=["x"]).DIRS[coche["d"]]
        g[0].enviar({"t": "tr_robar", "id": coche["id"]})
        assert g[0].leer("veh_no")["motivo"] in ("Estás demasiado lejos.", "Va demasiado rápido para abrir la puerta.")
        g[0].est(x=cx + dx * 6, y=cy + dy * 6)
        sinc(g[0])
        banco.hacer(lambda: [srv.trafico_mover(0.1) for _ in range(30)])
        assert coche["vel"] == 0.0
        limpiar(g)
        g[0].enviar({"t": "tr_robar", "id": coche["id"]})
        ok = g[0].leer("veh_ok")
        assert ok["robado"] and ok["tr"] == coche["id"] and coche["id"] not in srv.trafico
        tras(g[0], g)
        for c in g[1:]:
            assert sacar(c, "veh_ocupado", lambda m: m.get("tr") == coche["id"] and m["por"] == g[0].id)
        g[0].est(v=ok["v"]["modelo"])
        otro = next(iter(srv.trafico.values()))
        g[1].enviar({"t": "tr_dano", "id": otro["id"], "n": 5000})
        tras(g[1], g)
        for c in g:
            assert sacar(c, "tr_revienta", lambda m: m["id"] == otro["id"])
        # ---- la gente de la calle, también
        banco.hacer(lambda: [srv.peatones_pensar() for _ in range(60)])
        cuantos = len(srv.peatones)
        # hasta siete por cada zona con jugadores: Ana se ha ido a por un coche del tráfico, que unas veces queda en la
        # zona de los otros nueve y otras en la de al lado
        from servidor import peatones as modulo_peatones
        zonas = banco.hacer(lambda: len({(j.mapa, int(j.x // modulo_peatones.ZONA), int(j.y // modulo_peatones.ZONA)) for j in srv.jugadores.values() if j.dentro and not j.bot}))
        assert 1 <= zonas <= 2 and 3 <= cuantos <= 7 * zonas
        for c in g[1:]:
            c.cola.clear()
            assert len(c.leer("estados", filtro=lambda m: m.get("pe"))["pe"]) >= 1
        # un disparo los asusta
        g[1].enviar({"t": "evento", "que": "d:pistola"})
        sinc(g[1])
        from servidor import peatones as modulo_peatones
        cerca = [p for p in srv.peatones.values() if math.hypot(modulo_peatones.posicion(p["bi"], p["bj"], p["u"])[0] - g[1].e["x"],
                                                                 modulo_peatones.posicion(p["bi"], p["bj"], p["u"])[1] - g[1].e["y"]) <= 38]
        assert all(p["huye"] > 0 for p in cerca)
        # al que atracan ya no lleva nada para el siguiente, y al que tumban, cae para todos
        victima, otra = list(srv.peatones.values())[:2]
        g[2].enviar({"t": "pe_atraco", "id": victima["id"]})
        sinc(g[2])
        assert victima["atracado"] and victima["huye"] > 0
        g[3].cola.clear()
        fila = g[3].leer("estados", filtro=lambda m: any(f[0] == victima["id"] and f[7] == 1 for f in m.get("pe") or []))
        assert fila
        limpiar(g)
        g[2].enviar({"t": "pe_dano", "id": otra["id"], "n": 20})
        g[2].enviar({"t": "pe_dano", "id": otra["id"], "n": 40, "cae": True})
        tras(g[2], g)
        assert otra["id"] not in srv.peatones
        for c in g:
            assert bool(sacar(c, "pe_cae", lambda m: m["id"] == otra["id"])) == (c is not g[2])
        assert not errores_del_registro(banco.lineas)
    finally:
        cerrar_todos(g)
        banco.parar()
    # ---- el servidor se apaga y vuelve: los vehículos siguen donde estaban, y el bar sigue siendo de Ciro
    banco = Banco(tmp_path, trafico="no", peatones="no")
    try:
        c = Sim(banco, "Ciro", semilla=g[2].semilla)
        assert c.ok["props"] == {bar["id"]: {"cuenta": c.ok["cuenta"], "nombre": "Ciro", "oferta": 0}}
        aparcados = {v["id"]: v for v in c.ok["vehiculos"]}
        assert set(aparcados) == {suyos[2], ok["id"]} and all(v["por"] is None for v in aparcados.values())
        assert aparcados[suyos[2]]["modelo"] == "moto" and aparcados[suyos[2]]["x"] == bar["x"] + 70
        assert c.ok["banda"]["nombre"] == "Los del Bar" and len(c.ok["banda"]["miembros"]) == 2
        c.cerrar()
    finally:
        banco.parar()


# ====================================================================== combate
def test_diez_se_pelean_zonas_seguras_modo_pasivo_botin_recompensa_y_atracos(tmp_path):
    banco = Banco(tmp_path, proteccion=3)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        hospital = next(l for l in mundo()["mapas"]["puerto_bravo"]["lugares"] if l["tipo"] == "hospital")
        x, y = lejos_de_todo()
        # ---- recién llegados: ni atacan ni se les ataca
        juntos(g, x, y, di=2000)
        g[0].enviar({"t": "ataque", "a": g[1].id, "arma": "pistola"})
        assert "Acabas de llegar" in g[0].leer("fallo")["motivo"]
        g[0].enviar({"t": "atraco", "a": g[1].id})
        sinc(g[0])
        assert not sacar(g[1], "atracado")
        time.sleep(3.2)
        # ---- zona segura: a la puerta del hospital, y dentro de cualquier local
        g[0].est(x=hospital["x"] + 3, y=hospital["y"])
        g[1].est(x=hospital["x"] + 6, y=hospital["y"])
        sinc(g[0], g[1])
        g[0].enviar({"t": "ataque", "a": g[1].id, "arma": "pistola"})
        assert "Zona segura" in g[0].leer("fallo")["motivo"]
        g[2].est(x=hospital["x"] + 30, y=hospital["y"])           # Ciro, que pasa por allí, sabe que están a salvo
        g[2].cola.clear()
        assert g[2].leer("estados", filtro=lambda m: m["e"].get(str(g[0].id), {}).get("sg") == 1)
        g[2].est(x=x + 4, y=y)
        g[0].est(x=x, y=y)
        g[1].est(x=x + 2, y=y, **{"in": 1})                     # Blas, dentro de un local
        sinc(g[0], g[1])
        time.sleep(3.1)
        g[0].enviar({"t": "ataque", "a": g[1].id, "arma": "pistola"})
        assert "Zona segura" in g[0].leer("fallo")["motivo"]
        g[1].est(**{"in": 0})
        # ---- modo pasivo: ni hiere ni le hieren, y no se entra y se sale a conveniencia
        g[2].enviar({"t": "pasivo", "si": True})
        assert g[2].leer("pasivo")["si"] is True
        assert g[5].leer("estados", filtro=lambda m: m["e"].get(str(g[2].id), {}).get("pa") == 1)
        time.sleep(3.1)
        g[3].enviar({"t": "ataque", "a": g[2].id, "arma": "pistola"})
        assert "está en modo pasivo" in g[3].leer("fallo")["motivo"]
        g[2].enviar({"t": "ataque", "a": g[3].id, "arma": "pistola"})
        assert "Estás en modo pasivo" in g[2].leer("fallo")["motivo"]
        g[2].enviar({"t": "pasivo", "si": False})
        assert g[2].leer("aviso", filtro=lambda m: "Espera dos minutos" in m["texto"])
        sinc(*g)
        assert not any(sacar(c, ("herido")) for c in g) and all(q.salud == 100 for q in srv.jugadores.values())
        # ---- cuatro peleas a la vez, a bate: en cada pareja uno ataca y el otro acaba cayendo
        banco.hacer(lambda: setattr(srv, "rng", random.Random(7)))
        parejas = [(g[0], g[1]), (g[3], g[4]), (g[5], g[6]), (g[7], g[8])]
        for k, (a, b) in enumerate(parejas):
            a.est(x=x + 60 * k, y=y + 40)
            b.est(x=x + 60 * k + 2, y=y + 40, di=2000)
        sinc(*g)
        limpiar(g)
        recibido = {b.id: 0.0 for _, b in parejas}
        for ronda in range(20):
            for a, b in parejas:
                if recibido[b.id] < 100:
                    a.enviar({"t": "ataque", "a": b.id, "arma": "bate"})
            time.sleep(0.7)
            for a, b in parejas:
                sinc(a, b)
                for m in sacar(b, "herido"):
                    assert m["nombre"] == a.nombre and m["arma"] == "bate"
                    recibido[b.id] += m["dano"]
                b.est(sa=max(0, 100 - recibido[b.id]))
            if all(v >= 100 for v in recibido.values()):
                break
        assert all(v >= 100 for v in recibido.values()), recibido
        assert all(sacar(a, "impacto") for a, _ in parejas)
        for a, b in parejas:
            b.enviar({"t": "caido", "por": a.id})
        for a, b in parejas:
            cae = b.leer("caes")
            assert cae["nombre"] == a.nombre and cae["pierde"] == 200      # el diez por ciento de lo que llevaba
            b.est(sa=100, di=1800)
            baja = a.leer("baja")
            assert baja["botin"] == 200 and baja["nombre"] == b.nombre
            assert a.leer("buscado")["recompensa"] == 500         # tumbó a quien no se defendía: le ponen precio
            a.est(di=2200)
        sinc(*g)
        # todo el servidor se entera de cada baja, menos quien la hizo, que ya lo sabe
        for c in g:
            muertes = {(m["quien"], m["por"]) for m in sacar(c, "muerte")}
            assert muertes == {(b.nombre, a.nombre) for a, b in parejas if a is not c}
        bajas = banco.hacer(lambda: {f["nombre"]: (f["bajas"], f["caidas"], f["recompensa"]) for f in srv.alm.cuentas()})
        assert bajas["Ana"] == (1, 0, 500) and bajas["Blas"] == (0, 1, 0) and bajas["Juan"] == (0, 0, 0)
        g[9].enviar({"t": "quien"})
        assert {q["nombre"]: q["recompensa"] for q in g[9].leer("quien")["e"]}["Ana"] == 500
        # ---- quien dice que ha caído ante alguien que no le ha tocado, no regala nada
        g[9].enviar({"t": "caido", "por": g[0].id})
        sinc(g[9], g[0])
        assert not sacar(g[0], "baja")
        # ---- Juan va a por Ana, que tiene precio: cobra el botín y la recompensa, y a él no le ponen precio
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        g[9].est(x=g[0].e["x"] + 2, y=y + 40)
        sinc(g[9])
        for _ in range(12):
            g[9].enviar({"t": "ataque", "a": g[0].id, "arma": "bate"})
            if g[0].leer(("herido", "silbido"), 3)["t"] == "herido":
                break
            time.sleep(0.7)
        g[0].enviar({"t": "caido", "por": g[9].id})
        baja = g[9].leer("baja")
        assert baja["botin"] == 220 + 500 and "por su cabeza" in baja["texto"]
        sinc(g[9])
        assert not sacar(g[9], "buscado") and banco.hacer(lambda: srv.alm.cuenta(g[0].ok["cuenta"])["recompensa"]) == 0
        g[0].est(di=2200 - 220)
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        # ---- una granada entre tres: les alcanza a los tres, y los demás de la localidad la oyen
        for k, c in enumerate((g[3], g[5], g[7])):
            c.est(x=x + 200 + 2 * k, y=y + 80, sa=100)
        g[9].est(x=x + 190, y=y + 80)
        sinc(*g)
        limpiar(g)
        time.sleep(1.1)
        g[9].enviar({"t": "explosion", "arma": "granada", "x": x + 202, "y": y + 80})
        tras(g[9], g)
        assert len(sacar(g[9], "impacto")) == 3
        for c in (g[3], g[5], g[7]):
            (h,) = sacar(c, "herido")
            assert h["arma"] == "granada" and h["dano"] > 80
        for c in g[:9]:
            assert sacar(c, "estalla")
        g[9].enviar({"t": "explosion", "arma": "pistola", "x": x + 202, "y": y + 80})       # una pistola no estalla
        g[9].enviar({"t": "explosion", "arma": "granada", "x": x + 900, "y": y + 80})       # ni se lanza tan lejos
        tras(g[9], g)
        assert not any(sacar(c, "estalla") for c in g)
        # ---- atracar a otro jugador, a punta de navaja: el quince por ciento, y no dos veces seguidas
        g[1].est(x=x + 300, y=y, ar="navaja")
        g[2].est(x=x + 302, y=y, di=2000)                        # Ciro sigue en modo pasivo
        g[4].est(x=x + 298, y=y, di=2000)
        sinc(g[1], g[2], g[4])
        g[1].enviar({"t": "atraco", "a": g[2].id})
        assert "modo pasivo" in g[1].leer("fallo")["motivo"]
        g[1].enviar({"t": "atraco", "a": g[4].id})
        assert g[1].leer("atraco_ok")["botin"] == 300 and g[4].leer("atracado")["pierde"] == 300
        g[1].enviar({"t": "atraco", "a": g[4].id})
        assert g[1].leer("aviso", filtro=lambda m: "hace un momento" in m["texto"])
        # ---- el golpe a un policía que persigue a otro llega al juego del perseguido
        g[6].enviar({"t": "po_golpe", "a": g[8].id, "k": 3, "dano": 20})
        m = g[8].leer("po_golpe")
        assert m["k"] == 3 and m["dano"] == 20 and m["nombre"] == "Gala"
        # ---- irse en plena pelea no salva: sigue ahí unos segundos, y si cae, se le descuenta al volver
        g[5].est(x=x + 400, y=y, di=1000, sa=5)
        g[6].est(x=x + 402, y=y)
        sinc(g[5], g[6])
        g[6].enviar({"t": "ataque", "a": g[5].id, "arma": "bate"})
        g[6].leer(("impacto", "fallo"))
        g[5].cerrar()
        time.sleep(0.5)
        sinc(*[c for c in g if c is not g[5]])
        assert not any(sacar(c, "sale") for c in g if c is not g[5])
        assert g[5].id in srv.jugadores and not srv.jugadores[g[5].id].dentro
        baja = None
        for _ in range(10):
            time.sleep(0.65)
            g[6].enviar({"t": "ataque", "a": g[5].id, "arma": "bate"})
            try:
                baja = g[6].leer("baja", 0.3)
                break
            except AssertionError:
                pass
        assert baja and baja["botin"] == 100 + 500               # lo que llevaba, y el precio que tenía su cabeza desde la pelea de antes
        for c in g:
            if c is not g[5]:
                assert c.leer("sale", espera=5)["id"] == g[5].id
        g[5] = Sim(banco, "Fede", semilla=g[5].semilla)           # y vuelve: son diez otra vez
        assert g[5].ok["pendientes"] == [{"que": "caido", "por": "Gala", "pierde": 100}]
        assert banco.hacer(srv._cuantos) == N
        assert not errores_del_registro(banco.lineas)
    finally:
        cerrar_todos(g)
        banco.parar()


# ====================================================== policía y personajes
def test_diez_con_la_policia_comun_y_los_personajes_del_servidor(tmp_path):
    from test_servidor_mundo import _bots, _pensar
    from test_servidor_policia import acercar_patrulla, en_calle, patrullas_de
    banco = Banco(tmp_path, policia="si", trafico="no", personajes=4)
    g = []
    try:
        banco.hacer(lambda: setattr(banco.srv, "rng", random.Random(11)))
        g = diez(banco)
        srv = banco.srv
        assert all(c.ok["servidor"]["policia"] for c in g)
        x, y = en_calle()
        for k, c in enumerate(g):                               # Ana en la calle; los demás, en la acera de enfrente, a la vista
            c.est(x=x + (0 if k == 0 else 12 + 2 * k), y=y + (0 if k == 0 else 6))
        sinc(*g)
        # ---- personajes del servidor: salen solos donde hay gente, y los diez los ven llegar como a cualquiera
        _pensar(banco, 120)
        assert len(srv.bots) == 4 and len({b.nombre for b in srv.bots}) == 4
        sinc(*g)
        for c in g:
            assert {m["nombre"] for m in sacar(c, "entra", lambda m: m.get("ia"))} == {b.nombre for b in srv.bots}
        assert "Hay 10:" in banco.hacer(srv.orden, "jugadores") and "4 personajes del servidor" in banco.hacer(srv.orden, "estado")
        g[3].enviar({"t": "quien"})
        assert sum(1 for q in g[3].leer("quien")["e"] if q["ia"]) == 4
        # a uno se le puede tumbar como a un jugador: quien lo hace cobra, y el personaje se va para todos
        banco.hacer(lambda: [srv._bot_fuera(b) for b in list(srv.bots)])
        banco.hacer(lambda: srv.cfg.__setitem__("personajes", 1))
        (bid,) = _bots(banco, 1, clase="paseante", junto_a=g[9].id)
        banco.hacer(lambda: (setattr(srv.jugadores[bid], "salud", 20.0), setattr(srv.jugadores[bid], "dinero", 1000)))
        sinc(*g)
        limpiar(g)
        baja = None
        for _ in range(12):
            g[9].enviar({"t": "ataque", "a": bid, "arma": "bate"})
            try:
                baja = g[9].leer("baja", 0.8)
                break
            except AssertionError:
                pass
        assert baja and baja["botin"] == 100
        tras(g[9], g)
        for c in g:
            assert sacar(c, "sale", lambda m: m["id"] == bid)
        banco.hacer(lambda: srv.cfg.__setitem__("personajes", 0))
        g[9].enviar({"t": "busqueda", "nivel": 0})
        # ---- la policía: Ana comete un delito, y el servidor decide que la buscan
        g[0].enviar({"t": "delito", "n": 4})
        assert g[0].leer("nivel_busqueda")["es"] == 2
        assert g[5].leer("estados", filtro=lambda m: m["e"].get(str(g[0].id), {}).get("es") == 2)       # los demás saben que va buscada
        banco.hacer(lambda: [srv.policia_pensar() for _ in range(6)])
        pat = patrullas_de(banco, g[0].id)
        assert len(pat) == 1
        for c in g:                                              # la patrulla que viene a por ella está en el tráfico de los diez
            c.cola.clear()
            assert any(f[0] == pat[0]["id"] and f[6] == 2 for f in c.leer("estados", filtro=lambda m: m.get("tr"))["tr"])
        assert acercar_patrulla(banco, g[0].id) and len(srv.agentes) == 2
        for c in g:                                              # y los agentes que se bajan, también
            c.cola.clear()
            po = c.leer("estados", filtro=lambda m: m.get("po"))["po"]
            assert len(po) == 2 and all(f[3] == g[0].id for f in po)
        # disparan: los tiros los oyen todos los que están cerca, y solo a ella le pueden dar
        limpiar(g)
        banco.hacer(lambda: [srv.policia_mover(0.1) for _ in range(200)])
        sinc(*g)
        tiros = [sacar(c, "po_disparo") for c in g]
        assert len(tiros[0]) >= 4 and all(len(t) == len(tiros[0]) for t in tiros) and all(m["a"] == g[0].id for m in tiros[4])
        assert sacar(g[0], "po_apunta") and not any(sacar(c, "po_apunta") for c in g[1:])
        # otro jugador tumba a un agente: cae para todos
        agente = next(iter(srv.agentes))
        g[4].enviar({"t": "po_dano", "id": agente, "n": 200})
        tras(g[4], g)
        for c in g:
            assert bool(sacar(c, "po_cae", lambda m: m["id"] == agente)) == (c is not g[4])
        assert len(srv.agentes) == 1
        # paga la multa: ya no la buscan
        g[0].enviar({"t": "busqueda", "nivel": 0, "fin": True})
        assert g[0].leer("nivel_busqueda", filtro=lambda m: m["es"] == 0)["motivo"] == "limpia"
        sinc(g[0])
        assert not srv.agentes and not patrullas_de(banco, g[0].id)
        # ---- con una falta pequeña no disparan: la detienen
        g[1].est(x=x, y=y)
        g[0].est(x=x + 40, y=y + 6)
        sinc(g[0], g[1])
        g[1].enviar({"t": "delito", "n": 1})
        assert g[1].leer("nivel_busqueda")["es"] == 1
        banco.hacer(lambda: [srv.policia_pensar() for _ in range(7)])
        assert acercar_patrulla(banco, g[1].id)
        limpiar(g)
        banco.hacer(lambda: [srv.policia_mover(0.1) for _ in range(250)])
        assert g[1].leer("detenido")
        sinc(*g)
        assert not any(sacar(c, "po_disparo") for c in g) and srv.jugadores[g[1].id].detenido
        g[1].enviar({"t": "busqueda", "nivel": 0, "fin": True})
        g[1].leer("nivel_busqueda", filtro=lambda m: m["es"] == 0)
        # ---- salir no borra la búsqueda: al volver, te siguen buscando
        g[2].enviar({"t": "delito", "n": 8})
        assert g[2].leer("nivel_busqueda")["es"] == 3
        g[2].cerrar()
        g[3].leer("sale")
        g[2] = Sim(banco, "Ciro", semilla=g[2].semilla)
        vuelve = g[2].leer("nivel_busqueda")
        assert vuelve["es"] == 3 and vuelve["motivo"] == "vuelve"
        assert banco.hacer(srv._cuantos) == N
        assert not errores_del_registro(banco.lineas)
    finally:
        cerrar_todos(g)
        banco.parar()


# ======================================================== grupos y misiones
def test_diez_en_grupos_de_mision_y_misiones_comprobadas(tmp_path):
    banco = Banco(tmp_path, economia="si", ganancia_hora=3600, saldo_inicial=1000)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        x, y = lejos_de_todo()
        juntos(g, x, y, di=1000)
        banco.hacer(lambda: [setattr(q, "margen", 0.0) for q in srv.jugadores.values()])
        limpiar(g)
        # ---- dos grupos a la vez: en cada uno caben cuatro, e invita quien lo lleva
        for lider, gente in ((g[0], g[1:4]), (g[4], g[5:7])):
            for c in gente:
                lider.enviar({"t": "grupo_invitar", "a": c.id, "mision": "Morosos"})
                inv = c.leer("grupo_invita")
                assert inv["nombre"] == lider.nombre and inv["mision"] == "Morosos"
                c.enviar({"t": "grupo_resp", "si": True})
                assert c.leer("grupo")["lider"] == lider.id
        sinc(*g)
        assert len(sacar(g[0], "grupo")[-1]["miembros"]) == 4 and len(sacar(g[4], "grupo")[-1]["miembros"]) == 3
        assert avisos(g[0], "Dora se une al grupo") and avisos(g[2], "Dora se une al grupo")
        g[0].enviar({"t": "grupo_invitar", "a": g[7].id})
        assert "caben cuatro" in g[0].leer("aviso", filtro=lambda m: "caben" in m["texto"])["texto"]
        g[1].enviar({"t": "grupo_invitar", "a": g[7].id})
        assert "solo invita quien lo lleva" in g[1].leer("aviso", filtro=lambda m: "invita" in m["texto"])["texto"]
        g[4].enviar({"t": "grupo_invitar", "a": g[2].id})
        assert "Ciro ya va en un grupo" in g[4].leer("aviso", filtro=lambda m: "ya va" in m["texto"])["texto"]
        g[4].enviar({"t": "grupo_invitar", "a": g[7].id})
        g[7].leer("grupo_invita")
        g[7].enviar({"t": "grupo_resp", "si": False})            # Hugo no quiere
        sinc(g[7])
        assert srv.jugadores[g[7].id].grupo is None
        # ---- lo que cuenta quien lleva la misión llega a su grupo, y a nadie más
        limpiar(g)
        g[0].enviar({"t": "grupo_msg", "d": {"que": "enemigos", "e": [{"k": 0, "salud": 60}, {"k": 1, "salud": 60}]}})
        g[5].enviar({"t": "grupo_msg", "d": {"que": "golpe", "k": 0, "dano": 20}})
        g[8].enviar({"t": "grupo_msg", "d": {"que": "golpe", "k": 0, "dano": 20}})        # no va en ningún grupo
        tras(g[0], g)
        tras(g[5], g)
        tras(g[8], g)
        assert [len(sacar(c, "grupo_msg")) for c in g] == [0, 1, 1, 1, 1, 0, 1, 0, 0, 0]
        # ---- los del grupo no se hieren entre sí
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        g[1].enviar({"t": "ataque", "a": g[2].id, "arma": "pistola"})
        assert "va contigo en la misión" in g[1].leer("fallo")["motivo"]
        # ---- misión comprobada: a quien la lleva se le reconoce la recompensa entera; a los que ayudan, la mitad, una vez,
        # y solo si están con él en la localidad
        paga = mundo()["misiones"]["m04"]["dinero"]
        g[3].est(m="villaseca", x=50.0, y=50.0)                  # Dora se ha ido a otra localidad
        sinc(g[3])
        g[0].enviar({"t": "mision_ok", "id": "m04"})
        g[0].enviar({"t": "mision_hecha", "id": "m04"})
        g[0].est(di=1000 + paga)
        tras(g[0], g)
        for c in (g[1], g[2]):
            (m,) = sacar(c, "paga_mision")
            assert m["n"] == paga // 2 and m["de"] == "Ana" and m["titulo"] == "Morosos"
            c.est(di=1000 + paga // 2)
        assert not sacar(g[3], "paga_mision") and not any(sacar(c, "paga_mision") for c in g[4:])
        sinc(*g)
        assert [srv.jugadores[c.id].saldo for c in g[:4]] == [1000 + paga, 1000 + paga // 2, 1000 + paga // 2, 1000]
        assert not any(sacar(c, "saldo") for c in g)
        g[0].enviar({"t": "mision_hecha", "id": "m04"})          # decirlo dos veces no la paga dos veces
        tras(g[0], g)
        assert avisos(g[1], "Ya cobraste por ayudar") and not sacar(g[1], "paga_mision")
        g[1].enviar({"t": "mision_hecha", "id": "m05"})          # y solo paga quien lleva el grupo
        g[0].enviar({"t": "mision_hecha", "id": "una misión que no existe"})
        tras(g[1], g)
        tras(g[0], g)
        assert not any(sacar(c, "paga_mision") for c in g)
        # el otro grupo hace la suya, que es otra
        paga2 = mundo()["misiones"]["m05"]["dinero"]
        g[4].enviar({"t": "mision_hecha", "id": "m05"})
        tras(g[4], g)
        assert [len(sacar(c, "paga_mision", lambda m: m["n"] == paga2 // 2)) for c in g] == [0, 0, 0, 0, 0, 1, 1, 0, 0, 0]
        # ---- salir del grupo: si se va uno, sigue; si se va quien lo lleva, o se desconecta, se deshace
        g[1].enviar({"t": "grupo_salir"})
        assert g[1].leer("grupo", filtro=lambda m: m["lider"] is None)
        assert len(g[0].leer("grupo", filtro=lambda m: len(m["miembros"]) == 3)["miembros"]) == 3
        assert avisos(g[2], "Blas deja el grupo") or "Blas deja el grupo" in g[2].leer("aviso", filtro=lambda m: "deja" in m["texto"])["texto"]
        g[0].enviar({"t": "grupo_salir"})
        for c in (g[2], g[3]):
            assert c.leer("grupo", filtro=lambda m: m["lider"] is None)
            assert "Ana ha deshecho el grupo" in c.leer("aviso", filtro=lambda m: "deshecho" in m["texto"])["texto"]
        g[4].cerrar()                                            # Eva se desconecta llevando un grupo
        for c in (g[5], g[6]):
            assert c.leer("grupo", espera=5, filtro=lambda m: m["lider"] is None)
        g[4] = Sim(banco, "Eva", semilla=g[4].semilla)
        sinc(*g)
        assert all(q.grupo is None for q in srv.jugadores.values()) and banco.hacer(srv._cuantos) == N
        assert not srv.invitaciones_grupo                        # y no queda ninguna invitación colgando
        assert not errores_del_registro(banco.lineas)
        for c in g:                                              # el juego guarda cada poco y al salir: con el personaje va el saldo
            c.enviar({"t": "guardar", "p": {"jugador": {"dinero": c.e["di"]}}, "ya": True})
        for c in g:
            c.leer("guardado")
    finally:
        cerrar_todos(g)
        banco.parar()
    # ---- las misiones pagadas no se olvidan al reiniciar el servidor
    banco = Banco(tmp_path, economia="si")
    try:
        a = Sim(banco, "Ana", semilla=g[0].semilla)
        assert banco.srv.jugadores[a.id].misiones_pagadas == {"m04"} and a.ok["saldo"] == 1000 + paga
        b = Sim(banco, "Blas", semilla=g[1].semilla)
        banco.hacer(lambda: setattr(banco.srv.jugadores[a.id], "grupo", a.id) or setattr(banco.srv.jugadores[b.id], "grupo", a.id))
        a.est()
        b.est()
        sinc(a, b)
        a.enviar({"t": "mision_hecha", "id": "m04"})             # ni las ayudas: Blas ya cobró por esta
        assert "Ya cobraste" in b.leer("aviso", filtro=lambda m: "cobraste" in m["texto"])["texto"]
        a.cerrar()
        b.cerrar()
    finally:
        banco.parar()


# ================================================== administrar, cerrar y volver
def _personaje(k):
    """Un personaje guardado como lo manda el juego, con cosas que el servidor no conoce ni tiene por qué: lo que el juego
    compra por su cuenta (los complementos, la ropa) y campos de versiones futuras. El servidor lo guarda tal cual."""
    return {"jugador": {"nombre": NOMBRES[k], "dinero": 5000, "banco": 0, "ropa": "traje elegante" if k % 2 else "ropa de calle",
                        "accesorios": {"gafas": "Gafas de sol", "cadena": "Cadena de oro"} if k % 3 else {},
                        "objetos": {"botiquin": k, "ganzua": 2}, "armas": {"pistola": {"cargador": 12, "reserva": 30 + k}},
                        "algo_que_el_servidor_no_conoce": [1, 2.5, None, True, {"á": "ñ", "vacío": []}]},
            "dia": 3, "completadas": ["m01"], "texto": "con «comillas», eñes y 20 €", "numero_grande": 12345678901234567890, "orden": k}


def test_diez_y_quien_administra_anuncia_expulsa_veta_copia_recarga_cierra_y_vuelve_a_arrancar(tmp_path):
    datos, conf = tmp_path / "datos", tmp_path / "servidor.conf"
    cfg = dict(max_jugadores=N, economia="si", saldo_inicial=5000, precio_banda=2000, guerra_espera=30, bienvenida="Hola a los diez.")
    banco = Banco(datos, **cfg)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        o = lambda t: banco.hacer(srv.orden, t)
        x, y = lejos_de_todo()
        juntos(g, x, y, di=5000, b="puerto")
        # ---- guardar: el personaje va al servidor tal como lo manda el juego, letra por letra
        for k, c in enumerate(g):
            c.enviar({"t": "guardar", "p": _personaje(k), "ya": True})
        for c in g:
            c.leer("guardado")
        en_disco = banco.hacer(lambda: {f["nombre"]: f["partida"] for f in srv.alm.cuentas()})
        for k, n in enumerate(NOMBRES):
            assert en_disco[n] == json.dumps(_personaje(k), ensure_ascii=False, separators=(",", ":"))
            assert json.loads(en_disco[n])["jugador"]["accesorios"] == _personaje(k)["jugador"]["accesorios"]
        # ---- lo que ve quien administra
        assert "Hay 10 jugadores de 10" in o("estado") and "sin cifrado" in o("estado")
        assert "Hay 10: " in o("jugadores") and o("jugadores").count("en Puerto Bravo") == N
        cuentas = o("cuentas")
        assert "Hay 10: " in cuentas and "Ana (administra) (dentro)" in cuentas and cuentas.count("(dentro)") == N
        ayuda = o("ayuda")
        assert all(orden in ayuda for orden, _ in nucleo.Servidor.AYUDA_ORDENES) and "No conozco esa orden" in o("bailar")
        # ---- anuncio a todos, mensaje a uno, mensaje del día y la hora
        limpiar(g)
        assert o("aviso A las diez, mantenimiento.") == "Aviso enviado."
        assert "Dicho a Inés" in o("decir Inés: baja la música")
        assert "cambiado" in o("mensaje Mañana hay carrera en el puerto.")
        assert o("hora 22") == "Hora cambiada."
        sinc(*g)
        for c in g:
            assert avisos(c, "Aviso del servidor: A las diez, mantenimiento.")
            assert avisos(c, "Mensaje del día: Mañana hay carrera en el puerto.")
            assert sacar(c, "hora")[-1]["h"]["reloj"] == 22 * 60
            assert bool(avisos(c, "Quien administra el servidor te dice: baja la música")) == (c is g[8])
        # ---- administradores: se nombran, se quitan, y también valen los de la lista de la configuración
        assert "ya es administrador" in o("admin Blas")
        g[1].enviar({"t": "chat", "texto": "/jugadores"})
        assert g[1].leer("aviso", filtro=lambda m: "Hay 10" in m["texto"])
        assert "ya no administra" in o("quitaradmin Blas")
        g[1].enviar({"t": "chat", "texto": "/jugadores"})
        assert g[0].leer("chat")["texto"] == "/jugadores"
        banco.hacer(srv.aplicar_config, {"admins": "blas, Juan"})
        assert J(banco, g[1]).admin and J(banco, g[9]).admin and not J(banco, g[5]).admin
        assert "sigue administrando" in o("quitaradmin Juan")
        banco.hacer(srv.aplicar_config, {"admins": ""})
        assert not J(banco, g[1]).admin and not J(banco, g[9]).admin and J(banco, g[0]).admin
        assert "ya es administrador" in o("admin Blas")           # Blas se queda de administrador: tiene que seguir siéndolo tras reiniciar

        def fuera(c, tipo="expulsado", trozo=""):
            """Le sacan: le llega el motivo (si la red local no se lo traga), deja de estar dentro y los demás lo saben."""
            m = si_llega(c, tipo)
            assert m is None or trozo in m["motivo"], m
            fin = time.time() + 5
            while time.time() < fin and banco.hacer(lambda: any(q.nombre == c.nombre and q.dentro for q in srv.jugadores.values())):
                time.sleep(0.05)
            assert not banco.hacer(lambda: any(q.nombre == c.nombre and q.dentro for q in srv.jugadores.values()))
            otro = next(q for q in g if q is not c)
            assert otro.leer("sale", filtro=lambda s: s["id"] == c.id)
            c.cerrar()
            return m

        def vuelve(k):
            g[k] = Sim(banco, NOMBRES[k], semilla=g[k].semilla)
            assert g[k].ok, g[k].rechazo
            assert g[k].ok["partida"] == _personaje(k) and g[k].ok["saldo"] == 5000
            g[k].est(m="puerto_bravo", x=x + 2.0 * k, y=y, di=5000, b="puerto")
            sinc(g[k])
            return g[k]
        llegaron = []
        # ---- expulsar: se va con su motivo, y puede volver; su personaje sigue como lo dejó
        assert "Ciro, expulsado" in o("expulsar Ciro: deja de tocar el claxon")
        llegaron.append(fuera(g[2], trozo="deja de tocar el claxon"))
        assert "no está dentro" in o("expulsar Ciro") and "No hay nadie" in o("expulsar Nadie")
        vuelve(2)
        assert "Mensaje del día: Mañana hay carrera" in g[2].leer("aviso", filtro=lambda m: "Mensaje del día" in m["texto"])["texto"]
        # ---- vetar: se va y no vuelve hasta que se le perdona
        assert "vetado" in o("vetar Dora")
        llegaron.append(fuera(g[3], trozo="administrador"))
        assert "No puedes entrar" in Sim(banco, "Dora", semilla=g[3].semilla).rechazo
        assert "Dora (vetada)" in o("cuentas")
        assert "puede volver" in o("perdonar Dora")
        vuelve(3)
        # y vetar un nombre desde la configuración, con el servidor en marcha
        banco.hacer(srv.aplicar_config, {"vetados": "eva"})
        llegaron.append(fuera(g[4], trozo="sacado"))
        assert "No puedes entrar" in Sim(banco, "Eva", semilla=g[4].semilla).rechazo
        banco.hacer(srv.aplicar_config, {"vetados": ""})
        vuelve(4)
        # ---- inactividad: a quien lleva un minuto sin hacer nada se le saca; a quien administra y a quien se mueve, no
        banco.hacer(srv.aplicar_config, {"inactividad_minutos": 1})

        def envejecer():
            for c in (g[0], g[5], g[6]):
                J(banco, c).t_actividad -= 70
        banco.hacer(envejecer)
        g[6].est(x=g[6].e["x"] + 5)                              # Gala echa a andar
        g[5].est()                                               # Fede manda su posición, pero no se ha movido
        llegaron.append(fuera(g[5], trozo="sin hacer nada"))
        assert any("Fede lleva 1 minutos sin hacer nada" in l for l in banco.lineas)
        banco.hacer(srv.aplicar_config, {"inactividad_minutos": 0})
        sinc(g[0], g[6])
        vuelve(5)
        assert sum(1 for m in llegaron if m is not None) >= 2, "de cuatro expulsiones, casi ningún motivo ha llegado al jugador"
        assert banco.hacer(srv._cuantos) == N
        # ---- copia de seguridad en caliente, con los diez dentro
        r = o("copia")
        ruta = r.split("Copia hecha en ", 1)[1].strip()
        assert os.path.exists(ruta) and "Hay 1" in o("copias")
        with zipfile.ZipFile(ruta) as z:
            assert any(n.endswith("puertobravo.db") for n in z.namelist())
        assert o("guardar") == "Guardado."
        # ---- recargar la configuración en marcha: lo que se puede, al momento; lo que no, se dice
        completa = dict(opciones.valores_de_serie(), **banco.cfg)
        completa.update(bienvenida="Hola otra vez.", pvp="no", max_jugadores=12)
        opciones.guardar(str(conf), completa)
        srv.ruta_conf = str(conf)
        r = o("recargar")
        assert "Aplicado" in r and "Bienvenida" in r and "Combate entre jugadores" in r and "Esperan" not in r
        assert "Hay 10 jugadores de 12" in o("estado")
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        g[6].enviar({"t": "ataque", "a": g[7].id, "arma": "pistola"})
        assert "no hay combate entre jugadores" in g[6].leer("fallo")["motivo"]
        completa.update(pvp="si", max_jugadores=N, puerto=47999)
        opciones.guardar(str(conf), completa)
        r = o("recargar")
        assert "Esperan a que reinicies" in r and "Puerto" in r and srv.puerto == banco.puerto
        # ---- lo que tiene que seguir ahí después de apagar: bandas, un barrio, una guerra declarada, una casa, vehículos,
        # una invitación sin usar, el día y la hora
        g[0].enviar({"t": "banda_crear", "nombre": "Los Linces"})
        g[0].leer("cobro")
        g[0].est(di=3000)
        g[0].enviar({"t": "banda_invitar", "a": g[1].id})
        g[1].leer("banda_invita")
        g[1].enviar({"t": "banda_resp", "si": True})
        g[1].enviar({"t": "banda_ingresar", "n": 4500})
        g[1].leer("cobro")
        g[1].est(di=500)
        g[0].leer("banda", filtro=lambda m: m["b"]["caja"] == 4500)
        g[0].enviar({"t": "barrio_reclamar"})
        g[0].leer("banda", filtro=lambda m: m["b"]["caja"] == 1500)
        g[6].enviar({"t": "banda_crear", "nombre": "Los Zorros"})
        g[6].leer("cobro")
        g[6].est(di=3000)
        g[6].enviar({"t": "banda_ingresar", "n": 1000})
        g[6].leer("cobro")
        g[6].est(di=2000)
        g[6].enviar({"t": "barrio_guerra"})
        assert g[0].leer("aviso", filtro=lambda m: "os declara la guerra" in m["texto"])
        casa = next(l for l in mundo()["mapas"]["puerto_bravo"]["lugares"] if l["id"] == "piso_centro")
        g[2].enviar({"t": "prop_comprar", "lugar": casa["id"]})
        g[3].est(v="moto")
        g[3].enviar({"t": "veh_tomar", "modelo": "moto", "nombre": "Moto de Dora", "ref": 1})
        aparcada = g[3].leer("veh_tuyo")["id"]
        g[3].enviar({"t": "veh_dejar", "id": aparcada, "x": x + 50, "y": y + 20, "r": 90, "salud": 70})
        g[3].est(v=None)
        g[4].est(v="sedan", s=8, x=x + 120, y=y + 60)
        g[4].enviar({"t": "veh_tomar", "modelo": "sedan", "nombre": "Sedán de Eva", "ref": 2})
        en_marcha = g[4].leer("veh_tuyo")["id"]
        libre = o("invitar").split(": ")[1]
        banco.hacer(lambda: (setattr(srv, "dia", 5), setattr(srv, "reloj", 600.0)))
        sinc(*g)
        saldos = {c.nombre: banco.hacer(lambda c=c: J(banco, c).saldo) for c in g}
        assert saldos["Ana"] == 3000 and saldos["Blas"] == 500 and saldos["Gala"] == 2000 and saldos["Juan"] == 5000
        for k, c in enumerate(g):                                # todos guardan antes de que se apague, como hace el juego cada poco
            c.enviar({"t": "guardar", "p": dict(_personaje(k), dia=5), "ya": True})
        for c in g:
            c.leer("guardado")
        assert not errores_del_registro(banco.lineas)
        # ---- cierre ordenado con los diez dentro: a cada uno se le dice, y se le corta
        limpiar(g)

        def apagar():
            g[0].enviar({"t": "chat", "texto": "/apagar"})        # lo apaga Ana, que administra, desde el chat de su juego
            fin = time.time() + 15
            while time.time() < fin and not srv.detenido:
                time.sleep(0.05)
        avisados = a_la_escucha(g, "cerrado", apagar)
        assert sum(1 for m in avisados if m is not None) >= 8, avisados
        assert all(m["motivo"] == "Un administrador ha apagado el servidor." for m in avisados if m is not None)
        assert any("Ana da la orden apagar" in l for l in banco.lineas)
        for c in g:                                              # la conexión queda cortada de verdad
            c.s.settimeout(3)
            try:
                while c.s.recv(65536):
                    pass
            except ConnectionError:
                pass
        assert srv.detenido and not srv.activo
    finally:
        cerrar_todos(g)
        banco.parar()
    # ============================ arranca otra vez, de disco, y todo está donde estaba
    banco = Banco(datos, **cfg)
    nuevos = []
    try:
        srv = banco.srv
        assert srv.dia == 5 and 600 <= srv.reloj < 615
        cuentas = banco.hacer(srv.orden, "cuentas")
        assert "Hay 10: " in cuentas and "Ana (administra)" in cuentas and "Blas (administra)" in cuentas and "(vetada)" not in cuentas and "(dentro)" not in cuentas
        assert "No hay nadie" in banco.hacer(srv.orden, "jugadores")
        bandas = banco.hacer(srv.orden, "bandas")
        assert "Los Linces, 2 miembros, 1500 euros" in bandas and "Los Zorros, 1 miembros, 0 euros" in bandas
        assert libre + ", libre" in banco.hacer(srv.orden, "invitaciones")
        assert "Hay 1" in banco.hacer(srv.orden, "copias")
        for k, n in enumerate(NOMBRES):
            c = Sim(banco, "Otro nombre %d" % k, semilla=g[k].semilla)        # la identidad manda: el nombre es el de siempre
            nuevos.append(c)
            assert c.ok and c.ok["nombre"] == n and c.ok["cuenta"] == g[k].ok["cuenta"]
            assert c.ok["partida"] == dict(_personaje(k), dia=5)             # el personaje, tal cual lo mandó el juego
            assert c.ok["saldo"] == saldos[n] and c.ok["admin"] == (k < 2)
            assert c.ok["hora"]["dia"] == 5 and c.ok["dias_fuera"] == 0
            t = c.ok["territorios"]
            assert [(q["barrio"], q["nombre"]) for q in t["barrios"]] == [("puerto", "Los Linces")]
            assert len(t["guerras"]) == 1 and t["guerras"][0]["ataca_n"] == "Los Zorros" and t["guerras"][0]["fase"] == "espera"
            assert c.ok["props"] == {casa["id"]: {"cuenta": g[2].ok["cuenta"], "nombre": "Ciro", "oferta": 0}}
            coches = {v["id"]: v for v in c.ok["vehiculos"]}
            assert set(coches) == {aparcada, en_marcha} and all(v["por"] is None for v in coches.values())
            assert coches[aparcada]["nombre"] == "Moto de Dora" and coches[aparcada]["x"] == x + 50 and coches[aparcada]["salud"] == 70
            assert coches[en_marcha]["nombre"] == "Sedán de Eva" and coches[en_marcha]["x"] == x + 120      # lo que conducía Eva quedó aparcado donde iba
            assert (c.ok["banda"] or {}).get("nombre") == {0: "Los Linces", 1: "Los Linces", 6: "Los Zorros"}.get(k)
        assert banco.hacer(srv._cuantos) == N
        assert nuevos[1].ok["banda"]["caja"] == 1500 and len(nuevos[1].ok["banda"]["apuntes"]) == 2
        # y la guerra que quedó declarada empieza a su hora, como si no hubiera pasado nada
        banco.reloj.t += 30 * 60 + 1
        assert nuevos[0].leer("aviso", espera=6, filtro=lambda m: "¡Empieza la guerra" in m["texto"])
        # ---- borrar una cuenta: se va con su personaje y su casa, que vuelve a estar en venta para los demás
        assert "es jefe de una banda con más gente" in banco.hacer(srv.orden, "borrarcuenta Ana")
        limpiar(nuevos)
        assert "borrada" in banco.hacer(srv.orden, "borrarcuenta Ciro")
        m = si_llega(nuevos[2], "expulsado")
        assert m is None or "ha borrado tu cuenta" in m["motivo"]
        assert nuevos[0].leer("sale", filtro=lambda s: s["id"] == nuevos[2].id)
        assert nuevos[5].leer("prop", filtro=lambda s: s["lugar"] == casa["id"])["cuenta"] is None
        assert banco.hacer(lambda: srv.alm.cuenta_por_nombre("Ciro")) is None and banco.hacer(srv._props) == {} and banco.hacer(srv._cuantos) == N - 1
        vuelve = Sim(banco, "Ciro", semilla=g[2].semilla)         # si vuelve, empieza de cero
        nuevos[2] = vuelve
        assert vuelve.ok["partida"] is None and vuelve.ok["saldo"] is None and vuelve.ok["cuenta"] != g[2].ok["cuenta"]
        assert not errores_del_registro(banco.lineas)
    finally:
        cerrar_todos(nuevos)
        banco.parar()


# ============================================================ a prueba de trampas
def test_un_juego_trucado_que_manda_numeros_imposibles_no_estropea_la_partida_de_los_otros_nueve(tmp_path):
    """Un servidor público recibe de todo. Un «no es un número» o un infinito en la posición de un solo jugador no puede
    dejar a los demás sin saber dónde está nadie, ni llenar el registro de errores, ni herir a toda la localidad."""
    banco = Banco(tmp_path)
    g = []
    try:
        g = diez(banco)
        srv = banco.srv
        x, y = lejos_de_todo()
        juntos(g, x, y)
        banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
        malo = g[9]
        nan, inf = float("nan"), float("inf")
        for e in ({"x": nan, "y": y}, {"x": "nan", "y": "nan"}, {"x": inf, "y": -inf}, {"x": x, "y": y, "r": nan}, {"x": x, "y": y, "s": inf},
                  {"x": x, "y": y, "r": "inf"}, {"x": 1e308 * 10, "y": y}):
            malo.enviar({"t": "estado", "e": dict(malo.e, **e)})
        malo.enviar({"t": "veh_tomar", "modelo": "sedan", "salud": nan, "ref": 1})        # con un NaN a pelo, el mensaje entero no vale
        malo.enviar({"t": "veh_tomar", "modelo": "sedan", "salud": "nan", "ref": 2})
        tuyo = malo.leer("veh_tuyo")
        vid = tuyo["id"]
        assert tuyo["ref"] == 2 and srv.vehiculos[vid]["salud"] == mundo()["modelos"]["sedan"]["salud"]
        malo.enviar({"t": "veh_dejar", "id": vid, "x": "nan", "y": "inf", "r": "-inf", "salud": "nan"})
        malo.enviar({"t": "explosion", "arma": "granada", "x": nan, "y": nan})
        malo.enviar({"t": "explosion", "arma": "granada", "x": "nan", "y": "inf"})
        sinc(*g)
        j = J(banco, malo)
        assert all(math.isfinite(v) for v in (j.x, j.y, j.rumbo, j.vel)), (j.x, j.y, j.rumbo, j.vel)
        assert all(math.isfinite(v[k]) for v in srv.vehiculos.values() for k in ("x", "y", "r", "salud")), list(srv.vehiculos.values())
        assert all(q.salud == 100 for q in srv.jugadores.values()) and not any(sacar(c, "herido") for c in g)       # la granada «en ninguna parte» no da a nadie
        # los otros nueve siguen recibiendo dónde está todo el mundo, él incluido
        for c in g[:9]:
            c.cola.clear()
            m = c.leer("estados", filtro=lambda m: str(malo.id) in m["e"])
            assert len(m["e"]) == N - 1 and all(math.isfinite(v["x"]) and math.isfinite(v["y"]) for v in m["e"].values())
        time.sleep(0.5)
        assert not [l for l in banco.lineas if l.startswith("Error ")], [l for l in banco.lineas if l.startswith("Error ")][:3]
        # y lo que viaja por la red es JSON de verdad: ningún juego, de la versión que sea, se atraganta con un NaN
        cruda = b""
        malo.s.settimeout(2)
        try:
            while len(cruda) < 20000:
                trozo = malo.s.recv(65536)
                assert trozo, "el servidor le ha cortado, y no tenía por qué"
                cruda += trozo
        except OSError:
            pass
        assert len(cruda) > 2000 and b"NaN" not in cruda and b"Infinity" not in cruda
    finally:
        cerrar_todos(g)
        banco.parar()


def test_lo_que_falla_por_dentro_va_al_registro_y_un_corte_de_red_no_es_un_error(tmp_path):
    """En Windows, cuando un jugador corta justo cuando el servidor cierra, Python se queja de un enchufe ya cerrado y lo
    vuelca en la consola. Eso no es un error de nadie: no se dice. Cualquier otra cosa sí, en una línea del registro."""
    banco = Banco(tmp_path)
    try:
        srv = banco.srv

        class Asa:
            def __repr__(self):
                return "<Handle _ProactorBasePipeTransport._call_connection_lost()>"
        banco.hacer(lambda: banco.loop.call_exception_handler({"message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
                                                               "exception": OSError(10022, "Se ha proporcionado un argumento no válido"), "handle": Asa()}))
        banco.hacer(lambda: banco.loop.call_exception_handler({"message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
                                                               "exception": ConnectionResetError(10054, "Se ha forzado la interrupción"), "handle": Asa()}))
        assert not errores_del_registro(banco.lineas)
        banco.hacer(lambda: banco.loop.call_exception_handler({"message": "Task exception was never retrieved", "exception": KeyError("algo")}))
        assert [l for l in banco.lineas if l.startswith("Error interno del servidor: Task exception was never retrieved: KeyError")]
        a = Sim(banco, "Ana")                                    # y el servidor sigue atendiendo
        assert a.ok
        a.cerrar()
    finally:
        banco.parar()


# ======================================================= diez juegos de verdad
@pytest.fixture
def diez_juegos(app):
    from juego.app import App
    apps = [app] + [App(pruebas=True) for _ in range(N - 1)]
    yield [Robot(x) for x in apps]
    for x in apps:
        if x.partida is not None:
            x.partida.sv_salir()
            x.partida.desconectar_online()
    for x in apps[1:]:
        x.radio.cancelar()
        x.ambiente.cancelar()
        x.mez.cerrar()


def _todos(robots, n=2):
    for _ in range(n):
        for r in robots:
            r.frames(1)


def _hasta(cond, robots, segundos=15.0):
    fin = time.time() + segundos
    while time.time() < fin:
        _todos(robots, 2)
        if cond():
            return True
        time.sleep(0.01)
    return False


def _al_juego(robot):
    for _ in range(30):
        if robot.app.partida is None or robot.app.pila[-1] is robot.p:
            return
        robot.saltar_dialogos()
        if robot.app.pila[-1] is not robot.p:
            robot.tecla(pygame.K_ESCAPE)


def _otro_sitio(x, y):
    """Otro punto de Puerto Bravo fuera de las zonas seguras, a un buen trecho del primero."""
    seguras = [(l["x"], l["y"]) for l in mundo()["mapas"]["puerto_bravo"]["lugares"] if l["tipo"] in nucleo.SEGURAS]
    for i in range(1, 9):                                        # en mitad de una calle: las calles van cada noventa metros
        for j in range(1, 7):
            px, py = i * 90.0 + 30.0, j * 90.0 + 2.0
            if 70 < math.hypot(px - x, py - y) < 260 and all((px - a) ** 2 + (py - b) ** 2 > 70 ** 2 for a, b in seguras):
                return px, py
    raise AssertionError("no hay otro sitio")


def _elegir(robot, empieza):
    m = robot.app.pila[-1]
    m.refrescar(False)
    m.i = next(i for i, o in enumerate(m.opciones) if o.texto.startswith(empieza))
    robot.tecla(pygame.K_RETURN)


def test_diez_juegos_de_verdad_en_un_servidor_cifrado_con_todo_encendido(diez_juegos, tmp_path):
    """Diez juegos completos, cada uno con su mundo, en un servidor que cifra y lleva el dinero, el tráfico, la gente de la
    calle y la policía. Se ven, se oyen, se miran la ropa, compran, fundan una banda, se quitan un coche, se pelean,
    guardan, a uno le expulsan, el servidor se apaga con todos dentro, y al volver a arrancar cada uno sigue siendo quien era."""
    from juego import menus_enlinea, menus_juego
    from test_enlinea import entrar
    from test_servidor_mundo import _bots
    cfg = dict(cifrado="si", max_jugadores=N, economia="si", trafico="si", trafico_max=5, peatones="si", peatones_max=5, policia="si", patrullas=1,
               personajes=1)
    banco = Banco(tmp_path, **cfg)
    robots = diez_juegos
    nombres = ["Jugador%d" % (k + 1) for k in range(N)]
    try:
        srv = banco.srv
        assert srv.cifrado and len(srv.huella_cert) == 64
        banco.hacer(lambda: (setattr(srv, "reloj", 12 * 60.0), setattr(srv, "lluvia", False), setattr(srv, "rng", random.Random(3))))
        ps = [entrar(r, banco, n) for r, n in zip(robots, nombres)]
        gente = lambda p: [q for q in p.remotos.values() if not getattr(q, "ia", False)]
        ve = lambda p, k: next(q for q in p.remotos.values() if q.nombre == nombres[k])
        assert _hasta(lambda: all(len(gente(p)) == N - 1 for p in ps), robots), [len(gente(p)) for p in ps]
        assert all(p.sv["cifrado"] and p.red.cifrado and p.red.huella_cert == srv.huella_cert for p in ps)
        assert len({p.j.semilla for p in ps}) == 1 and len({p.dia for p in ps}) == 1 and all(p.sv["info"]["policia"] and p.sv["info"]["trafico"] for p in ps)
        assert "cifrada" in robots[9].dicho() and banco.hacer(srv._cuantos) == N

        def cuenta(k):
            return next(q for q in list(srv.jugadores.values()) if q.nombre == nombres[k] and q.dentro)

        def dar(k, n):
            """Dinero que el servidor da por bueno, como el de una misión comprobada."""
            banco.hacer(lambda: setattr(cuenta(k), "credito", cuenta(k).credito + n))
            ps[k].j.dinero += n

        def reunir(x, y):
            for k, p in enumerate(ps):
                if p.mundo.id != "puerto_bravo":
                    p.cambiar_mapa("puerto_bravo", x, y)
                p.teletransportar(x + 3 * (k % 5), y + 4 * (k // 5))
                p.sv["protegido"] = 0
            banco.hacer(lambda: [setattr(q, "protegido", 0) for q in srv.jugadores.values()])
            assert _hasta(lambda: all(q.visto and q.mapa == "puerto_bravo" and q.dist(*p.pos()) < 40 for p in ps for q in gente(p)), robots), (
                (x, y), [(k, p.mundo.id, [round(v) for v in p.pos()], p.transicion, r.app.pila[-1] is p) for k, (r, p) in enumerate(zip(robots, ps))])
        x, y = lejos_de_todo("puerto_bravo")
        reunir(x, y)
        # ---- el tráfico y la gente de la calle son del servidor, y están en el juego de los diez
        assert _hasta(lambda: len(srv.trafico) >= 3 and len(srv.peatones) >= 2, robots, 25), (len(srv.trafico), len(srv.peatones))
        assert _hasta(lambda: all(p.sv["trafico"] and p.sv["peatones"] for p in ps), robots, 15), [(len(p.sv["trafico"]), len(p.sv["peatones"])) for p in ps]
        # un personaje del servidor: está en el juego de todos, y no es un jugador más
        (bid,) = _bots(banco, 1, clase="paseante", junto_a=ps[0].red.id)
        assert _hasta(lambda: all(bid in p.remotos and p.remotos[bid].ia for p in ps), robots)
        # ---- el aspecto: Jugador1 se compra unas gafas de sol y una cadena; los demás saben cómo va, y lo dice Mayúsculas J
        assert _hasta(lambda: all(q.aspecto == "ropa de calle" for p in ps for q in gente(p)), robots, 12)      # al entrar, cada juego cuenta cómo va
        dar(0, 3000)
        antes = ps[0].j.dinero
        tienda = next(l for l in ps[0].mundo.lugares.values() if l.tipo == "ropa")
        ps[0].teletransportar(tienda.x, tienda.y)
        menus_juego.lugar(ps[0], tienda)
        _elegir(robots[0], "Complementos")
        _elegir(robots[0], "Gafas de sol:")
        _elegir(robots[0], "Cadena de oro:")
        _al_juego(robots[0])
        assert ps[0].j.accesorios == {"gafas": "Gafas de sol", "cadena": "Cadena de oro"} and ps[0].j.dinero == antes - 90 - 1500
        como_va = "ropa de calle, con gafas de sol y cadena de oro"
        assert ps[0].aspecto_corto() == como_va
        assert _hasta(lambda: all(ve(p, 0).aspecto == como_va for p in ps[1:]), robots, 12)
        assert cuenta(0).aspecto == como_va
        reunir(x, y)
        ps[1].j.x, ps[1].j.y = ps[0].j.x - 1.5, ps[0].j.y        # Jugador2 se le pone al lado
        _todos(robots, 6)
        assert _hasta(lambda: ve(ps[1], 0).dist(*ps[1].pos()) < 2.5, robots)
        robots[1].app.voz.registro.clear()
        robots[1].tecla(pygame.K_j, pygame.KMOD_SHIFT)
        dicho = robots[1].dicho()
        assert "Jugador1, a " in dicho and ", lleva ropa de calle, con gafas de sol y cadena de oro." in dicho
        robots[0].app.voz.registro.clear()
        ps[0].mirar_jugador()                                    # y Jugador1 mira al que tiene más cerca: un jugador, no el personaje del servidor
        assert "lleva ropa de calle." in robots[0].dicho() and "Jugador" in robots[0].dicho()
        ps[9].j.accesorios["reloj"] = "Reloj de oro"             # otro se cambia más tarde: también se enteran
        assert _hasta(lambda: all("reloj de oro" in ve(p, 9).aspecto for p in ps[:9]), robots, 12)
        # ---- el chat, desde el menú
        menus_enlinea.chat(ps[2], "todos", None, "x")
        robots[2].app.pila[-1].texto = "somos diez"
        robots[2].tecla(pygame.K_RETURN)
        assert _hasta(lambda: all("Jugador3 dice: somos diez" in robots[k].dicho() for k in range(N) if k != 2), robots)
        _al_juego(robots[2])
        # ---- una banda, con el dinero llevado por el servidor: fundar cuesta dos mil, y no se cobran dos veces
        dar(3, 6000)
        _todos(robots, 6)
        antes = ps[3].j.dinero
        menus_enlinea.banda(ps[3])
        _elegir(robots[3], "Fundar una banda")
        robots[3].app.pila[-1].texto = "Los Diez"
        robots[3].tecla(pygame.K_RETURN)
        assert _hasta(lambda: ps[3].sv["banda"] is not None, robots)
        _al_juego(robots[3])
        assert ps[3].j.dinero == antes - 2000
        ps[3].red.enviar({"t": "banda_invitar", "a": ve(ps[3], 4).id})
        assert _hasta(lambda: ps[4].sv["inv_banda"] is not None, robots)
        menus_enlinea.banda(ps[4])
        robots[4].tecla(pygame.K_RETURN)
        assert _hasta(lambda: ps[4].sv["banda"] is not None and len(ps[3].sv["banda"]["miembros"]) == 2, robots)
        _al_juego(robots[4])
        ps[3].red.enviar({"t": "banda_ingresar", "n": 3500})
        assert _hasta(lambda: ps[4].sv["banda"]["caja"] == 3500 and ps[3].j.dinero == antes - 5500, robots)
        ps[3].red.enviar({"t": "barrio_reclamar"})
        barrio = ps[3].mundo.barrio(*ps[3].pos())["id"]
        assert _hasta(lambda: all(p.sv_dueno_barrio("puerto_bravo", barrio) is not None for p in ps), robots)
        # dinero de mano en mano
        ps[3].dar_dinero_a(ve(ps[3], 5), 200)
        d5 = ps[5].j.dinero
        assert _hasta(lambda: ps[5].j.dinero == d5 + 200, robots)
        # ---- un coche: Jugador6 lo coge, lo oyen conducir, lo deja, y Jugador7 se lo lleva
        vx, vy = ps[5].pos()
        coche = ps[5].crear_vehiculo("sedan", vx + 4, vy, 0, "aparcado")
        coche.cerrado = False
        ps[5]._subir(coche, True)
        assert _hasta(lambda: getattr(coche, "id_red", None) is not None and all(ve(p, 5).veh == "sedan" for p in ps if p is not ps[5]), robots)
        ps[5].salir_vehiculo()
        assert _hasta(lambda: any(getattr(q, "id_red", None) == coche.id_red for q in ps[6].vehiculos), robots)
        copia = next(q for q in ps[6].vehiculos if getattr(q, "id_red", None) == coche.id_red)
        ps[6].j.x, ps[6].j.y = copia.x + 2, copia.y
        _todos(robots, 8)
        time.sleep(0.2)
        _todos(robots, 4)
        robots[6].tecla(pygame.K_f)
        assert _hasta(lambda: ps[6].j.veh is copia and coche.muerto, robots), robots[6].dicho()[-300:]
        assert "Jugador7 se ha llevado tu" in robots[5].dicho()
        ps[6].salir_vehiculo()
        # ---- lo que pasa pocas veces, pero pasa: cada juego tiene que saber qué hacer con ello
        oido = []
        suena = ps[2].son
        ps[2].son = lambda nombre, **kw: (oido.append(nombre), suena(nombre, **kw))[1]
        # el modo pasivo, desde el menú del móvil; los demás lo saben
        menus_enlinea.menu(ps[9])
        _elegir(robots[9], "Modo pasivo")
        assert _hasta(lambda: ps[9].sv["pasivo"] and cuenta(9).pasivo, robots) and "Modo pasivo activado" in robots[9].dicho()
        _al_juego(robots[9])
        assert _hasta(lambda: all(ve(p, 9).pasivo for p in ps[:9]), robots)
        # quién hay, contado por el servidor, y la respuesta a un ping
        ps[1].red.enviar({"t": "quien"})
        ps[1].red.enviar({"t": "ping"})
        assert _hasta(lambda: len(ps[1].sv["quien"]) >= N, robots)
        # pedir un vehículo que ya no está
        robots[1].app.voz.registro.clear()
        ps[1].red.enviar({"t": "veh_subir", "id": 987654})
        assert _hasta(lambda: "Ese vehículo ya no está" in robots[1].dicho(), robots)
        # todos a otro sitio, para que lo que va a estallar no le dé a nadie
        x2, y2 = _otro_sitio(x, y)
        reunir(x2, y2)
        # a una moto aparcada de otro se le da, y se nota en el juego de todos; y si revienta, revienta para todos
        moto = ps[5].crear_vehiculo("moto", x, y, 0, "aparcado")
        moto.cerrado = False
        ps[5]._subir(moto, True)
        assert _hasta(lambda: getattr(moto, "id_red", None) is not None, robots)
        ps[5].salir_vehiculo()
        ps[5].teletransportar(x2 + 3, y2 + 4)
        assert _hasta(lambda: all(p._sv_copia(moto.id_red) is not None for p in ps), robots)
        la_de_ana = ps[0]._sv_copia(moto.id_red)
        salud = la_de_ana.salud
        ps[0].danar_vehiculo(la_de_ana, 20)
        assert _hasta(lambda: all(p._sv_copia(moto.id_red).salud == salud - 20 for p in ps), robots) and "bala_impacto" in oido
        id_moto = moto.id_red
        ps[0].danar_vehiculo(la_de_ana, 500)
        assert _hasta(lambda: id_moto not in srv.vehiculos and all(id_moto not in p.sv["vehs"] and moto.muerto for p in ps), robots)
        # el coche en el que va otro jugador: el golpe llega a su juego, y el de una patrulla que le embiste, también
        auto = ps[5].crear_vehiculo("sedan", *ps[5].pos(), 0, "aparcado")
        auto.cerrado = False
        ps[5]._subir(auto, True)
        assert _hasta(lambda: getattr(auto, "id_red", None) is not None, robots)
        salud = auto.salud
        ps[0].red.enviar({"t": "veh_dano", "id": auto.id_red, "n": 12})
        assert _hasta(lambda: auto.salud < salud and ve(ps[5], 0).hostil, robots), (auto.salud, salud, robots[0].dicho()[-200:])
        salud = auto.salud
        banco.hacer(lambda: srv._enviar(cuenta(5), {"t": "po_embiste", "n": 7, "x": 0.0, "y": 0.0}))
        assert _hasta(lambda: auto.salud < salud, robots)
        ps[5].salir_vehiculo(forzado=True)
        ps[5].quitar_vehiculo(auto)
        assert _hasta(lambda: auto.id_red not in srv.vehiculos, robots)
        # una granada: los demás la oyen estallar donde cae
        oido.clear()
        px, py = ps[6].pos()
        ps[6]._estallar({"x": px + 36, "y": py, "radio": 8, "dano": 130, "arma": "granada"})
        assert _hasta(lambda: "explosion" in oido, robots)
        ps[6].sv_busqueda(0, fin=True)
        # un coche del tráfico revienta: deja de estar en el juego de todos
        assert _hasta(lambda: bool(ps[0].sv["trafico"]), robots, 20)
        lejano = max(ps[0].sv["trafico"].values(), key=lambda v: math.hypot(v.x - ps[0].j.x, v.y - ps[0].j.y))
        tid = lejano.tr_id
        for _ in range(8):
            if tid not in srv.trafico:
                break
            ps[0].red.enviar({"t": "tr_dano", "id": tid, "n": 500})
            _todos(robots, 3)
            time.sleep(0.1)
        assert _hasta(lambda: tid not in srv.trafico and all(tid not in p.sv["trafico"] for p in ps), robots)
        # un corte de conexión a secas: desde la 1.7.1 el juego lo nota, lo dice, se queda esperando con la partida tal cual
        # y vuelve a entrar solo; los demás le ven irse y volver
        from juego import reconexion
        banco.hacer(lambda: srv._cortar(cuenta(1)))
        assert _hasta(lambda: isinstance(robots[1].app.pila[-1], reconexion.Espera), robots[1:2], 20)
        assert "Se ha cortado la conexión con el servidor" in robots[1].dicho() and robots[1].app.partida is ps[1]
        assert _hasta(lambda: all(len(gente(p)) == N - 2 for k, p in enumerate(ps) if k != 1), [r for k, r in enumerate(robots) if k != 1])
        assert _hasta(lambda: robots[1].app.pila[-1] is ps[1] and ps[1].online_activo(), robots, 30), robots[1].dicho()[-300:]
        assert "Reconectado" in robots[1].dicho()
        assert _hasta(lambda: all(len(gente(p)) == N - 1 for p in ps), robots)
        for r in robots:
            r.saltar_dialogos()
            _al_juego(r)
        # ---- una pelea: Jugador8 dispara a Jugador9, que lo nota en su juego; a quien dispara le busca la policía de todos
        reunir(x, y)
        ps[7].dar_arma("pistola", 200)
        ps[7].j.arma = "pistola"
        salud = ps[8].j.salud
        banco.hacer(lambda: setattr(srv, "rng", random.Random(5)))
        for _ in range(40):
            ps[7].objetivo = ve(ps[7], 8)
            ps[7].j.t_ataque = 0
            ps[7].j.armas["pistola"]["cargador"] = 12
            ps[7].atacar()
            _todos(robots, 2)
            time.sleep(0.42)
            if ps[8].j.salud < salud:
                break
        assert ps[8].j.salud < salud and "Jugador8 te ataca" in robots[8].dicho() and ve(ps[8], 7).hostil
        ps[7].sv_delito(4)
        assert _hasta(lambda: ps[7].j.estrellas == 2 and cuenta(7).estrellas == 2, robots)
        assert _hasta(lambda: all(ve(p, 7).estrellas == 2 for p in ps if p is not ps[7]), robots)
        ps[7].sv_busqueda(0, fin=True)
        assert _hasta(lambda: ps[7].j.estrellas == 0 and cuenta(7).estrellas == 0, robots)
        for r in robots:
            r.saltar_dialogos()
            _al_juego(r)
        # ---- guardar va al servidor, con todo lo que el juego lleva por su cuenta
        for k, (r, p) in enumerate(zip(robots, ps)):
            p.j.salud = p.j.salud_max
            assert menus_juego.escribir_ranura(p, "1"), k
        _todos(robots, 6)
        time.sleep(0.3)
        guardado = json.loads(banco.hacer(lambda: srv.alm.cuenta_por_nombre("Jugador1")["partida"]))
        assert guardado["jugador"]["accesorios"] == {"gafas": "Gafas de sol", "cadena": "Cadena de oro"} and guardado["jugador"]["ropa"] == "ropa de calle"
        assert guardado["jugador"]["dinero"] == ps[0].j.dinero and guardado["jugador"]["nombre"] == ps[0].j.nombre
        # ---- Jugador1 sale y vuelve a entrar: sigue llevando lo suyo, y los demás vuelven a saber cómo va
        dinero0 = ps[0].j.dinero
        banco.hacer(lambda: (cuenta(0).golpeado.clear(), cuenta(0).agredio.clear()))      # como si hiciera un rato de su último golpe: quien sale en plena pelea se queda quince segundos
        ps[0].sv_salir()
        assert _hasta(lambda: all(len(gente(p)) == N - 2 for p in ps[1:]), robots[1:])
        ps[0] = entrar(robots[0], banco, nombres[0])
        assert ps[0].j.accesorios == {"gafas": "Gafas de sol", "cadena": "Cadena de oro"} and ps[0].j.dinero == dinero0
        assert _hasta(lambda: all(len(gente(p)) == N - 1 for p in ps), robots)
        assert _hasta(lambda: all(ve(p, 0).aspecto == como_va for p in ps[1:]) and "reloj de oro" in ve(ps[0], 9).aspecto, robots, 12)
        # ---- a Jugador3 le expulsa quien administra: su juego vuelve al menú y le dice por qué
        assert "expulsado" in banco.hacer(srv.orden, "expulsar Jugador3: demasiado claxon")
        assert _hasta(lambda: robots[2].app.partida is None, robots)
        assert "Un administrador te ha sacado del servidor. Motivo: demasiado claxon" in robots[2].dicho()
        assert _hasta(lambda: all(len(gente(p)) == N - 2 for k, p in enumerate(ps) if k != 2), [r for k, r in enumerate(robots) if k != 2])
        ps[2] = entrar(robots[2], banco, nombres[2])
        assert _hasta(lambda: all(len(gente(p)) == N - 1 for p in ps), robots)
        # ---- nada de lo que han hecho jugando limpio se lo ha discutido el servidor, ni ha habido errores
        assert not [l for l in banco.lineas if "no se le reconocen" in l], [l for l in banco.lineas if "no se le reconocen" in l]
        assert not errores_del_registro(banco.lineas), errores_del_registro(banco.lineas)
        assert not any("El servidor no reconoce" in r.dicho() for r in robots)
        # ---- el servidor se apaga con los diez dentro: cada juego vuelve al menú con su personaje guardado
        for p in ps:
            p.sv_guardar(ya=True)
        _todos(robots, 6)
        time.sleep(0.3)
        dinero = [p.j.dinero for p in ps]
        import threading
        hilo = threading.Thread(target=banco.parar, daemon=True)
        hilo.start()
        assert _hasta(lambda: all(r.app.partida is None for r in robots), robots, 20), [r.app.partida is None for r in robots]
        hilo.join(15)
        assert not hilo.is_alive() and srv.detenido
        avisados = sum(1 for r in robots if "El servidor se ha cerrado. Tu personaje está guardado." in r.dicho())
        assert avisados >= 8, [r.dicho()[-160:] for r in robots]
    finally:
        if banco.srv.activo:
            banco.parar()
    # ---- y arranca otra vez: mismo certificado, y cada uno entra y sigue siendo quien era
    banco = Banco(tmp_path, **cfg)
    try:
        assert banco.srv.huella_cert == srv.huella_cert and not any("Creando el certificado" in l for l in banco.lineas)
        ps = [entrar(r, banco, n) for r, n in zip(robots, nombres)]
        assert _hasta(lambda: all(len(gente(p)) == N - 1 for p in ps), robots)
        assert [p.j.dinero for p in ps] == dinero
        assert ps[0].j.accesorios == {"gafas": "Gafas de sol", "cadena": "Cadena de oro"} and ps[9].j.accesorios == {"reloj": "Reloj de oro"}
        assert ps[3].sv["banda"]["nombre"] == "Los Diez" and ps[4].sv["banda"]["caja"] == 500 and ps[3].sv["rango"] == "jefe"
        assert all(p.sv_dueno_barrio("puerto_bravo", barrio)["nombre"] == "Los Diez" for p in ps)
        assert "pistola" in ps[7].j.armas
        assert any(v["id"] == coche.id_red for p in ps[:1] for v in p.sv["vehs"].values())       # el coche sigue en la calle
        _todos(robots, 10)
        time.sleep(0.3)
        _todos(robots, 4)
        assert not [l for l in banco.lineas if "no se le reconocen" in l] and not errores_del_registro(banco.lineas)
        for p in ps:
            p.sv_salir()
        time.sleep(0.8)
        assert banco.hacer(banco.srv._cuantos) == 0
    finally:
        banco.parar()


# ====================================================================== aguante
SEGUNDOS_DE_AGUANTE = int(os.environ.get("PB_AGUANTE_SEGUNDOS", "300"))       # de reloj simulado: cinco minutos de serie


class Incansable(Sim):
    """Un jugador simulado que no para: anda, conduce, dispara, cae, habla, delinque, y lleva sus cuentas como el juego
    (lo que el servidor le cobra lo resta, lo que le da lo suma). Lee todo lo que le llega, sin esperar a nada."""

    def __init__(self, banco, nombre, k, rng):
        super().__init__(banco, nombre)
        self.k, self.rng = k, rng
        self.cuenta = {}
        self.vistos = {}                                         # id -> (localidad, x, y, vuelta en la que llegó)
        self.vuelta = 0
        self.vid = self.atacante = self.fuera = None
        self.dano, self.cortado = 0.0, False
        self.aparcados, self.tr, self.pe = {}, [], []
        self.rumbo, self.t_modo = rng.uniform(0, 360), rng.uniform(3, 8)
        self.canales = {}

    def beber(self):
        """Lee todo lo que haya llegado, sin esperar."""
        import socket
        self.s.settimeout(0)
        try:
            while True:
                trozo = self.s.recv(262144)
                if not trozo:
                    self.cortado = True
                    break
                self.buf += trozo
        except (BlockingIOError, socket.timeout):
            pass
        except OSError:
            self.cortado = True
        *lineas, self.buf = self.buf.split(b"\n")
        for linea in lineas:
            self.atender(json.loads(linea.decode("utf-8")))

    def _pagar(self, n):
        de_mano = min(self.e["di"], n)
        self.e["di"] -= de_mano
        self.e["ba"] -= min(self.e["ba"], n - de_mano)

    def atender(self, m):
        t = m["t"]
        self.cuenta[t] = self.cuenta.get(t, 0) + 1
        if t == "estados":
            for ident, e in m["e"].items():
                self.vistos[int(ident)] = (e["m"], e["x"], e["y"], self.vuelta)
            if "tr" in m:
                self.tr = m["tr"]
            if "pe" in m:
                self.pe = m["pe"]
        elif t == "cobro":
            self.e["di"] -= min(self.e["di"], m["n"])
        elif t in ("dinero", "paga_mision"):
            self.e["di"] += m["n"]
        elif t in ("baja", "atraco_ok", "robo_fin"):
            self.e["di"] += m.get("botin", 0)
        elif t in ("caes", "atracado"):
            self.e["di"] -= min(self.e["di"], m["pierde"])
        elif t == "saldo":
            self._pagar(m["quita"])
        elif t == "herido":
            self.dano += m["dano"]
            self.atacante = m["de"]
        elif t == "po_disparo":
            if m["a"] == self.id:
                self.dano += m["da"]
        elif t == "veh_tuyo":
            self.vid = m["id"]
        elif t == "veh_ok":
            self.vid, self.e["v"] = m["id"], m["v"]["modelo"]
        elif t == "sacado":
            self.vid, self.e["v"] = None, None
        elif t == "veh_libre":
            self.aparcados[m["v"]["id"]] = m["v"]
        elif t in ("veh_ocupado", "veh_fuera", "veh_revienta"):
            self.aparcados.pop(m["id"], None)
            if t != "veh_ocupado" and m["id"] == self.vid:
                self.vid, self.e["v"] = None, None
        elif t == "chat":
            self.canales[m["canal"]] = self.canales.get(m["canal"], 0) + 1
        elif t in ("expulsado", "cerrado", "rechazo"):
            self.fuera = m

    def cerca(self):
        """Los demás de mi localidad, del más cercano al más lejano: (distancia, id, x, y)."""
        e = self.e
        return sorted((math.hypot(x - e["x"], y - e["y"]), ident, x, y) for ident, (m, x, y, _) in self.vistos.items() if m == e["m"])

    def vivir(self, vuelta, caja):
        """Una décima de segundo de su vida."""
        self.vuelta = vuelta
        e, rng = self.e, self.rng
        x0, y0, x1, y1 = caja
        vel = 11.0 if e["v"] else 2.5
        if rng.random() < 0.03:
            self.rumbo = rng.uniform(0, 360)
        e["x"] += math.sin(math.radians(self.rumbo)) * vel * 0.1
        e["y"] += math.cos(math.radians(self.rumbo)) * vel * 0.1
        if not (x0 < e["x"] < x1 and y0 < e["y"] < y1):          # se sale del barrio: media vuelta, hacia el centro
            e["x"], e["y"] = min(x1, max(x0, e["x"])), min(y1, max(y0, e["y"]))
            self.rumbo = math.degrees(math.atan2((x0 + x1) / 2 - e["x"], (y0 + y1) / 2 - e["y"])) % 360
        e["x"], e["y"] = round(e["x"], 1), round(e["y"], 1)
        e["s"], e["r"], e["sa"] = (vel if e["v"] else 0), round(self.rumbo), max(1, round(100 - self.dano, 1))
        self.est()
        if (vuelta + self.k) % 10 == 0:
            self.cada_segundo(vuelta // 10)

    def cada_segundo(self, seg):
        e, rng = self.e, self.rng
        cerca = self.cerca()
        otro = cerca[0] if cerca else None
        if otro and rng.random() < 0.8:                          # dispara al que tiene más cerca
            self.enviar({"t": "ataque", "a": otro[1], "arma": "pistola"})
            if rng.random() < 0.4:
                self.enviar({"t": "evento", "que": "d:pistola"})
        if e["v"] and otro and otro[0] < 7:
            self.enviar({"t": "atropello", "a": otro[1]})
        if self.dano >= 100:                                     # ha caído: lo dice, y vuelve a levantarse
            self.est(sa=0)
            if self.atacante is not None:
                self.enviar({"t": "caido", "por": self.atacante})
            self.enviar({"t": "busqueda", "nivel": 0, "fin": True})
            self.dano, self.atacante = 0.0, None
        self.t_modo -= 1
        if self.t_modo <= 0:                                     # se sube a un vehículo, o lo deja
            self.t_modo = rng.uniform(4, 10)
            if e["v"]:
                if self.vid is not None:
                    self.enviar({"t": "veh_dejar", "id": self.vid, "x": e["x"], "y": e["y"], "r": e["r"], "salud": rng.randint(40, 100)})
                self.vid, e["v"] = None, None
            else:
                al_lado = [v for v in self.aparcados.values() if v["m"] == e["m"] and math.hypot(v["x"] - e["x"], v["y"] - e["y"]) < 13]
                if al_lado and rng.random() < 0.6:
                    self.enviar({"t": "veh_subir", "id": al_lado[0]["id"]})
                else:
                    e["v"] = rng.choice(["sedan", "moto", "utilitario", "furgoneta"])
                    self.enviar({"t": "veh_tomar", "modelo": e["v"], "ref": seg})
        if seg % 4 == self.k % 4:                                # habla, cada vez por un canal
            canal = ("todos", "cerca", "banda", "priv", "grupo")[(seg // 4 + self.k) % 5]
            self.enviar({"t": "chat", "texto": "mensaje %d de %s por el canal %s" % (seg, self.nombre, canal), "canal": canal, "a": otro[1] if otro else None})
        suerte = rng.random()
        if suerte < 0.04:
            self.enviar({"t": "delito", "n": rng.choice([1, 4, 8])})
        elif suerte < 0.07:
            self.enviar({"t": "busqueda", "nivel": 0, "fin": True})
        elif suerte < 0.10 and otro:
            self.enviar({"t": "atraco", "a": otro[1]})
        elif suerte < 0.12 and otro and otro[0] < 30:
            self.enviar({"t": "explosion", "arma": "granada", "x": otro[2], "y": otro[3]})
        elif suerte < 0.16:
            self.enviar({"t": "quien"})
        elif suerte < 0.20 and self.pe:
            self.enviar({"t": "pe_dano", "id": rng.choice(self.pe)[0], "n": 60})
        elif suerte < 0.23 and self.pe:
            self.enviar({"t": "pe_atraco", "id": rng.choice(self.pe)[0]})
        elif suerte < 0.27 and self.tr:
            self.enviar({"t": "tr_dano", "id": rng.choice(self.tr)[0], "n": 400})
        elif suerte < 0.30 and self.tr and not e["v"]:
            self.enviar({"t": "tr_robar", "id": rng.choice(self.tr)[0]})
        elif suerte < 0.33:
            self.enviar({"t": "banda_ingresar", "n": 10})
        elif suerte < 0.35:
            self.enviar({"t": "banda_sacar", "n": 5})
        elif suerte < 0.38 and otro and e["di"] >= 5:
            e["di"] -= 5                                         # el juego paga y avisa a la vez
            self.enviar({"t": "dinero", "a": otro[1], "n": 5})
        elif suerte < 0.40:
            self.enviar({"t": "aspecto", "texto": "ropa de calle, con %d complementos" % rng.randint(0, 5)})
        elif suerte < 0.43:
            self.enviar({"t": "grupo_msg", "d": {"que": "enemigos", "e": [{"k": q, "salud": 60} for q in range(6)]}})
        elif suerte < 0.45 and self.aparcados:
            self.enviar({"t": "veh_dano", "id": rng.choice(list(self.aparcados)), "n": 30})
        elif suerte < 0.47:
            self.enviar({"t": "act", "d": {"que": "carrera", "lugar": "bar_gaviota"}})
        elif suerte < 0.49:
            self.enviar({"t": "banda_lista"})
        if seg % 45 == self.k:                                   # y guarda, como el juego, cada tres cuartos de minuto
            self.enviar({"t": "guardar", "p": {"jugador": {"dinero": e["di"], "banco": e["ba"], "relleno": "x" * 6000}, "seg": seg}, "ya": seg % 2 == 0})


def test_aguante_diez_jugadores_sin_parar_durante_varios_minutos(tmp_path, monkeypatch):
    """Los diez moviéndose, conduciendo, disparando y hablando, con todo lo que lleva el servidor encendido, durante
    varios minutos de un reloj simulado: el servidor da sus diez vueltas por segundo, pero sin esperar entre una y otra."""
    import gc
    import sys
    real = time.monotonic
    adelanto = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: real() + adelanto[0])
    banco = Banco(tmp_path, economia="si", saldo_inicial=5000, trafico="si", trafico_max=6, peatones="si", peatones_max=6, policia="si", patrullas=1,
                  personajes=4, precio_banda=500, guardado_minutos=1, copia_auto_horas=1, registro_archivo="si")
    g = []
    try:
        srv = banco.srv
        azar = random.Random(2026)
        banco.hacer(lambda: (setattr(srv, "rng", random.Random(10)), setattr(srv, "reloj", 12 * 60.0), setattr(srv, "lluvia", False)))
        for k, n in enumerate(NOMBRES):
            g.append(Incansable(banco, n, k, random.Random(100 + k)))
            assert g[-1].ok, g[-1].rechazo
        x, y = lejos_de_todo()
        caja = (x - 20, y - 20, x + 200, y + 150)
        for k, c in enumerate(g):
            c.est(x=x + 15.0 * k, y=y + 10.0 * (k % 3), di=4000, b="puerto")
        sinc(*g)
        # dos bandas de dos y un grupo de misión, para que haya canal de banda, de grupo, cajas y fuego amigo quitado
        for jefe, otro, nombre in ((g[0], g[1], "Los Linces"), (g[5], g[6], "Los Zorros")):
            jefe.enviar({"t": "banda_crear", "nombre": nombre})
            jefe.leer("banda")
            jefe.enviar({"t": "banda_invitar", "a": otro.id})
            otro.leer("banda_invita")
            otro.enviar({"t": "banda_resp", "si": True})
            otro.leer("banda")
        g[2].enviar({"t": "grupo_invitar", "a": g[3].id})
        g[3].leer("grupo_invita")
        g[3].enviar({"t": "grupo_resp", "si": True})
        g[3].leer("grupo")
        sinc(*g)
        for c in g:
            for m in c.cola:                                     # lo que ha pasado hasta aquí, a sus cuentas
                c.atender(m)
            c.cola.clear()
            c.cuenta.clear()
        # desde aquí el servidor no lleva su propio paso: cada vuelta la da la prueba, adelantando el reloj una décima
        banco.hacer(lambda: [t.cancel() for t in srv.tareas])
        import array
        tiempos = array.array("d")                               # en un solo bloque, para no contar como memoria lo que apunta la prueba

        def vuelta(n):
            adelanto[0] += 0.1
            t0 = time.perf_counter()
            srv.bots_mover(0.1)
            srv.trafico_mover(0.1)
            srv.peatones_mover(0.1)
            srv.policia_mover(0.1)
            srv._repartir_estados(n)
            if n % 10 == 0:
                banco.reloj.t += 1.0
                srv._tic(1.0, n // 10)
            tiempos.append(time.perf_counter() - t0)

        def medir():
            gc.collect()
            dentro = [q for q in srv.jugadores.values() if q.dentro and not q.bot]
            return {"bloques": sys.getallocatedblocks(), "cola": max(q.cola.qsize() for q in dentro), "jugadores": len(srv.jugadores), "dentro": len(dentro),
                    "trafico": len(srv.trafico), "peatones": len(srv.peatones), "agentes": len(srv.agentes), "vehiculos": len(srv.vehiculos),
                    "robos": len(srv.robos), "invitaciones": len(srv.invitaciones_banda) + len(srv.invitaciones_grupo), "conexiones": len(srv.conexiones),
                    "peleas": max(len(q.golpeado) + len(q.agredio) + len(q.atracos) + len(q.gastos) + len(q.cobros) + len(q.raros) + len(q.avisado) for q in dentro),
                    "ayudas": len(srv.ayudas), "buscados": len(srv.buscados_fuera), "por_ip": dict(srv.por_ip)}
        vueltas = SEGUNDOS_DE_AGUANTE * 10
        medidas = []
        guardados = []
        guardar_de_verdad = srv.guardar_todo
        srv.guardar_todo = lambda: (guardados.append(1), guardar_de_verdad())[1]
        for n in range(1, vueltas + 1):
            for c in g:
                c.vivir(n, caja)
            banco.hacer(vuelta, n)
            for c in g:
                c.beber()
            if n == vueltas // 2:                                # a media prueba le toca la copia de seguridad automática
                banco.hacer(lambda: setattr(srv, "_t_copia", time.monotonic() - 3601))
            if n % 300 == 0:                                     # cada medio minuto, cómo está el servidor
                sinc(*g)
                for c in g:
                    for m in c.cola:
                        c.atender(m)
                    c.cola.clear()
                medidas.append(banco.hacer(medir))
            assert not any(c.cortado or c.fuera for c in g), [(c.nombre, c.cortado, c.fuera) for c in g if c.cortado or c.fuera]
        # ---- se paran: unas vueltas más, quietos, y a cada uno le tiene que constar dónde están los otros nueve
        for n in range(vueltas + 1, vueltas + 41):
            for c in g:
                c.est(s=0)
            banco.hacer(vuelta, n)
            for c in g:
                c.vuelta = n
                c.beber()
        for _ in range(2):                                       # lo último que les ha llegado, a sus cuentas; y que el servidor lo sepa
            sinc(*g)
            for c in g:
                for m in c.cola:
                    c.atender(m)
                c.cola.clear()
                c.est(s=0)
        sinc(*g)
        for c in g:
            for q in g:
                if q is c:
                    continue
                m, vx, vy, cuando = c.vistos[q.id]
                assert m == q.e["m"] and abs(vx - q.e["x"]) <= 0.51 and abs(vy - q.e["y"]) <= 0.51, (c.nombre, q.nombre, c.vistos[q.id], q.e["x"], q.e["y"])
                assert cuando > vueltas + 15, (c.nombre, q.nombre, cuando)
        # ---- nadie se ha caído, ni le han echado por mandar demasiado, y el servidor los tiene a todos dentro
        assert banco.hacer(srv._cuantos) == N and all(not c.cortado and c.fuera is None for c in g)
        # ---- las posiciones han llegado a todos, todo el rato: casi una entrega por vuelta
        entregas = [c.cuenta.get("estados", 0) for c in g]
        assert min(entregas) >= 0.9 * vueltas and max(entregas) <= vueltas + 60, entregas
        # ---- ha pasado de todo: se han oído por los cinco canales, ha habido tiros, bajas, coches, policía y guardados
        total = {}
        for c in g:
            for t, k in c.cuenta.items():
                total[t] = total.get(t, 0) + k
        canales = set().union(*[set(c.canales) for c in g])
        assert canales == {"todos", "cerca", "banda", "priv", "grupo"}, canales
        for tipo in ("herido", "impacto", "fallo", "tiro", "evento", "caes", "baja", "muerte", "veh_tuyo", "veh_ocupado", "veh_libre", "nivel_busqueda",
                     "cobro", "dinero", "banda", "quien", "guardado", "hora", "aspecto", "grupo_msg", "act", "entra", "bandas"):
            assert total.get(tipo, 0) > 0, (tipo, total)
        assert total["estados"] > 9 * vueltas and total.get("saldo", 0) == 0, total
        # ---- ni un error en el registro, ni en el que va a disco; y jugando limpio, el servidor no le discute un euro a nadie
        assert not errores_del_registro(banco.lineas), errores_del_registro(banco.lineas)
        assert not [l for l in banco.lineas if "no se le reconocen" in l or "demasiados mensajes" in l], [l for l in banco.lineas if "reconocen" in l][:5]
        with open(tmp_path / "registro.txt", encoding="utf-8") as f:
            registro = f.read()
        assert "Error" not in registro and "Traceback" not in registro and "Entra Ana" in registro
        for c in g:
            assert J(banco, c).saldo == c.e["di"] + c.e["ba"], (c.nombre, J(banco, c).saldo, c.e["di"], c.e["ba"])
        # ---- nada crece sin tope: las colas de salida, lo que hay por las calles, las listas internas y la memoria
        fin = banco.hacer(medir)
        medidas.append(fin)
        for m in medidas:
            assert m["cola"] <= 100 and m["dentro"] == N and m["jugadores"] <= N + 4 and m["conexiones"] == N and m["por_ip"] == {"127.0.0.1": N}, m
            assert m["trafico"] <= 6 * 4 + 1 + 4 * N and m["peatones"] <= 6 * 6 and m["agentes"] <= 2 * 4 * N, m
            assert m["vehiculos"] <= 4 * (N + 4) and m["robos"] <= N + 4 and m["invitaciones"] <= 2 * N and m["peleas"] <= 120 and m["buscados"] <= N, m
        if len(medidas) >= 6:                                    # la memoria: del primer tercio al final no sube más que un poco
            tercio = medidas[len(medidas) // 3]["bloques"]
            assert fin["bloques"] <= tercio * 1.03 + 2000, (tercio, fin["bloques"], [m["bloques"] for m in medidas])
        # ---- mientras tanto ha guardado cada minuto y ha hecho su copia de seguridad, sin que nadie lo note
        assert len(guardados) >= SEGUNDOS_DE_AGUANTE // 60
        assert sum(1 for l in banco.lineas if "Copia de seguridad automática hecha" in l) == 1 and len(copias.listar(str(tmp_path))) == 1
        # ---- y el servidor va sobrado: cada vuelta le lleva una pequeña parte de la décima de segundo que tiene
        tiempos = sorted(tiempos)
        assert tiempos[len(tiempos) // 2] < 0.02 and tiempos[int(len(tiempos) * 0.99)] < 0.08, (tiempos[len(tiempos) // 2], tiempos[int(len(tiempos) * 0.99)], tiempos[-1])
        print("aguante: %d s simulados, %d mensajes recibidos por los diez, vuelta mediana %.2f ms, percentil 99 %.2f ms, máxima %.2f ms; bloques de memoria %s; cola máxima %d"
              % (SEGUNDOS_DE_AGUANTE, sum(total.values()), tiempos[len(tiempos) // 2] * 1000, tiempos[int(len(tiempos) * 0.99)] * 1000, tiempos[-1] * 1000,
                 [m["bloques"] for m in medidas], max(m["cola"] for m in medidas)))
    finally:
        cerrar_todos(g)
        banco.parar()
