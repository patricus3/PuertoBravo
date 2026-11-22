"""El piloto del GPS, que lleva el coche solo, comer con la vida realista y el apartado Acerca de."""
import math

import pygame

from juego import VERSION, menus_juego
from juego.menus import Menu


def _al_volante(robot, modelo="utilitario"):
    p = robot.p
    j = p.j
    x, y, rumbo = p.mundo.plaza_aparcamiento(j.x, j.y) if hasattr(p.mundo, "plaza_aparcamiento") else (j.x, j.y, 0)
    v = p.crear_vehiculo(modelo, x, y, rumbo, None)
    p._subir(v, False, callar=True)
    return v


def test_el_piloto_lleva_el_coche_solo_hasta_el_destino(robot):
    p = robot.nueva_partida()
    p.cfg["conduccion"] = "asistida"
    p.cfg["piloto_gps"] = False
    p.cfg["sucesos"] = False
    v = _al_volante(robot)
    robot.frames(10)                                                 # el coche se coloca en su carril
    x0, y0 = v.x, v.y
    destino = max((l for l in p.mundo.lugares.values() if l.tipo in ("banco", "hospital", "taller", "tienda", "farmacia")), key=lambda l: math.hypot(l.x - x0, l.y - y0))
    p.gps_a_lugar(destino, callar=True)
    lejos = math.hypot(destino.x - x0, destino.y - y0)
    assert lejos > 150 and not p.piloto_completo()
    robot.frames(60)
    assert abs(v.vel) < 0.01                                         # sin piloto y sin tocar nada, el coche no avanza
    robot.tecla(pygame.K_y)
    assert p.piloto_completo() and "va solo hasta" in robot.dicho()
    maxima = 0.0
    for _ in range(400):                                             # hasta doscientos segundos de viaje, sin pulsar una tecla
        robot.frames(15)
        maxima = max(maxima, v.vel)
        assert p.j.estrellas == 0
        if not p.gps:
            break
    assert not p.gps, f"no llegó: quedan {math.hypot(destino.x - v.x, destino.y - v.y):.0f} metros. {robot.dicho()[-300:]}"
    assert math.hypot(destino.x - v.x, destino.y - v.y) < 40 and 8 < maxima <= 14.5
    assert v.salud > v.salud_max * 0.9                               # y sin golpes
    robot.frames(90)
    assert abs(v.vel) < 3                                            # al llegar, se va parando
    # el jugador manda siempre: con el freno pisado no acelera, y la tecla Y lo apaga
    p.gps_a_lugar(next(l for l in p.mundo.lugares.values() if l is not destino and math.hypot(l.x - v.x, l.y - v.y) > 150), callar=True)
    robot.frames(60, mantener=(pygame.K_SPACE,))
    assert abs(v.vel) < 1
    robot.tecla(pygame.K_y)
    assert not p.cfg["piloto_gps"] and not p.piloto_completo()


def _cruce_despejado(p, robot):
    """Un cruce del centro, con las cuatro salidas, sin nadie más: el jugador llega por el oeste, al volante, en su carril."""
    from juego import mundo as M
    m = p.mundo
    for o in list(p.vehiculos):
        p.quitar_vehiculo(o)
    p.personas[:] = []
    i, j = m.NX // 2, m.NY // 2
    assert all(m.dir_valida(i, j, d) for d in range(4))
    v = p.crear_vehiculo("utilitario", i * M.B - 30, m.carril("H", j, 1), 1, None)
    p.j.x, p.j.y = v.x, v.y
    p._subir(v, False, callar=True)
    assert v.dir == 1 and p.modo_asistido()
    return M, m, i, j, v


def test_el_trafico_que_gira_no_se_echa_encima_de_quien_va_con_el_piloto(robot):
    """Los dos golpes que se llevaba el coche con el piloto puesto: el de delante giraba a la derecha y, al colocarse en su
    carril nuevo, retrocedía tres metros hasta el morro del que le seguía; y el que venía de frente giraba a la izquierda
    cruzando tu carril. Si era una patrulla de ronda, además te ponía una estrella."""
    p = robot.nueva_partida()
    p.cfg["conduccion"] = "asistida"
    p.cfg["sucesos"] = False
    M, m, i, j, v = _cruce_despejado(p, robot)
    cx, cy = i * M.B, j * M.B
    # ---- el de delante gira a la derecha: sale ya dentro de su calle nueva, lejos de quien le sigue, esté a la distancia que esté
    for modelo, ia in (("sedan", "trafico"), ("patrulla", "policia")):
        for hueco in (3.6, 4.5, 5.5, 6.5, 8.0):
            v.x, v.y, v.vel = cx - hueco, m.carril("H", j, 1), 9.0
            o = p.crear_vehiculo(modelo, cx + 0.2, v.y, 1, ia)
            o.vel = 9.0
            p._en_cruce(o, i, j, lambda *a: 2)
            assert o.dir == 2 and o.x == m.carril("V", i, 2) and o.y < v.y - 3.4, (hueco, o.x, o.y)
            assert o.dist(v.x, v.y) > 4.0
            v.t_choque = 0.0
            salud, puntos = v.salud, p.j.puntos_busqueda
            p._choques_jugador(v)
            assert v.salud == salud and p.j.puntos_busqueda == puntos
            p.quitar_vehiculo(o)
    # pero si en esa calle, justo a la vuelta de la esquina, está tu coche, no se le pone encima: gira corto y frena detrás
    v.x, v.y, v.dir, v.vel = m.carril("V", i, 2), cy - 9.0, 2, 0.0
    o = p.crear_vehiculo("sedan", cx + 0.2, m.carril("H", j, 1), 1, "trafico")
    p._en_cruce(o, i, j, lambda *a: 2)
    assert o.y == cy - 1.0 and o.dist(v.x, v.y) > 6 and p._obstaculo(o)
    p.quitar_vehiculo(o)
    # el jugador gira como siempre
    v.x, v.y, v.dir, v.vel = cx + 0.2, m.carril("H", j, 1), 1, 5.0
    p._en_cruce(v, i, j, lambda *a: 2)
    assert (v.x, v.y) == (m.carril("V", i, 2), cy - 1.0)
    # ---- quien viene de frente no gira a la izquierda delante de ti; cuando ya has pasado, o si estás parado o lejos, sí
    o = p.crear_vehiculo("sedan", cx - 0.2, m.carril("H", j, 3), 3, "trafico")
    izquierda = (o.dir - 1) % 4

    def giros(n=300):
        return {p._decidir_trafico(o, i, j) for _ in range(n)}

    for lejos, vel in ((6.0, 9.0), (15.0, 9.0), (22.0, 14.0), (30.0, 14.0), (4.0, 3.0)):
        v.x, v.y, v.dir, v.vel = cx - lejos, m.carril("H", j, 1), 1, vel
        assert p._viene_de_frente(o) and giros() == {o.dir, (o.dir + 1) % 4}, (lejos, vel)
    for lejos, vel, sentido in ((-8.0, 9.0, 1), (70.0, 14.0, 1), (10.0, 0.0, 1), (10.0, 9.0, 3)):
        v.x, v.y, v.dir, v.vel = cx - lejos, m.carril("H", j, sentido), sentido, vel
        assert not p._viene_de_frente(o) and izquierda in giros(), (lejos, vel, sentido)
    p.salir_vehiculo(forzado=True)                               # a pie no hay a quien ceder el paso
    assert not p._viene_de_frente(o) and izquierda in giros()


def test_quien_gira_en_la_ultima_calle_del_mapa_no_se_queda_clavado(robot):
    """En la avenida del borde, el carril de fuera cae tres metros más allá del límite: al tráfico que giraba allí se le
    paraba el coche en seco en plena esquina, y el que venía detrás girando se lo comía."""
    p = robot.nueva_partida()
    M, m, i, j, v = _cruce_despejado(p, robot)
    p.salir_vehiculo(forzado=True)
    p.j.x, p.j.y = 5.0, 5.0
    i = m.NX - 1                                                 # la última avenida: solo se puede girar
    assert not m.dir_valida(i, j, 1) and m.dir_valida(i, j, 0)
    o = p.crear_vehiculo("sedan", i * M.B - 2.0, m.carril("H", j, 1), 1, "trafico")
    o.vel = 10.0
    for _ in range(12):
        p._mover_via(o, 1 / 30, 0.0, lambda *a: 0)
    assert o.dir == 0 and o.vel == 10.0 and o.x == m.carril("V", i, 0) and o.y > j * M.B + 1
    o.dir, o.x, o.y, o.vel = 1, i * M.B - 2.0, m.carril("H", j, 1), 10.0      # y quien sigue de frente contra el borde, se para como siempre
    for _ in range(12):
        p._mover_via(o, 1 / 30, 0.0, lambda *a: 1)
    assert o.vel == 0.0 and o.x == m.ancho


def test_con_vida_realista_se_come_por_hambre(robot):
    p = robot.nueva_partida()
    j = p.j
    comida = p.datos["comidas"][0]
    j.dinero = 500
    j.salud = j.salud_max
    p.cfg["vida_realista"] = False
    menus_juego._comprar_comida(p, comida)()
    assert "No tienes hambre: tu salud está al máximo" in robot.dicho() and j.dinero == 500
    p.cfg["vida_realista"] = True                                    # antes, con la salud entera no dejaba comer aunque tuvieras hambre
    j.hambre = 85.0
    menus_juego._comprar_comida(p, comida)()
    assert j.dinero < 500 and j.hambre <= 40 and "Estás" in robot.dicho()
    j.hambre = 0.0
    dinero = j.dinero
    menus_juego._comprar_comida(p, comida)()
    assert j.dinero == dinero and "Ahora no tienes hambre" in robot.dicho()
    p.cfg["vida_realista"] = False


def test_acerca_de(robot, monkeypatch):
    abiertos = []
    monkeypatch.setattr(menus_juego.os, "startfile", lambda ruta: abiertos.append(ruta), raising=False)
    app = robot.app
    principal = app.pila[-1]
    textos = [o.texto for o in principal.opciones]
    assert textos[-2:] == ["Acerca de", "Salir"]
    principal.i = len(textos) - 2
    robot.tecla(pygame.K_RETURN)
    m = app.pila[-1]
    assert isinstance(m, Menu) and "Acerca de" in m.titulo
    lineas = [o.texto for o in m.opciones]
    assert f"versión {VERSION}" in lineas[0] and "Héctor J. Benítez Corredera" in lineas[1] and "Copyright 2026, Héctor J. Benítez Corredera" in lineas[2] and "MIT" in lineas[2]
    cafe = next(k for k, t in enumerate(lineas) if t == "Invítame a un café si te gusta mi trabajo")
    m.i = cafe
    robot.tecla(pygame.K_RETURN)
    assert abiertos == ["https://www.paypal.com/paypalme/hjbcdonaciones"] and "donaciones" in robot.dicho()
    for texto, trozo in (("Página del proyecto en GitHub", "github.com/hxebolax/PuertoBravo"), ("Avisar de un fallo o proponer una mejora", "/issues"),
                         ("Mastodon del autor", "comunidad.nvda.es"), ("Novedades de esta versión", "novedades_es.html")):
        m.i = lineas.index(texto)
        robot.tecla(pygame.K_RETURN)
        assert trozo in abiertos[-1]
    robot.tecla(pygame.K_ESCAPE)
    assert app.pila[-1] is principal


def test_un_toque_de_la_a_abre_los_ajustes_del_piloto_y_mantenerla_cambia_de_carril(robot):
    """La A al volante: un toque corto abre el menú de cómo conduce el piloto; mantenida, sigue siendo adelantar."""
    p = robot.nueva_partida()
    p.cfg["conduccion"] = "asistida"
    p.cfg["sucesos"] = False
    p.cfg["piloto_estilo"] = "auto"
    _al_volante(robot)
    robot.frames(5)
    robot.tecla(pygame.K_a)                                          # pulsar y soltar enseguida
    robot.frames(1)
    menu = robot.app.pila[-1]
    assert isinstance(menu, Menu) and "piloto" in menu.titulo.lower(), menu
    # la primera es activar o desactivar el piloto; el cursor empieza en el estilo puesto
    assert menu.i == 1
    robot.tecla(pygame.K_DOWN)
    robot.tecla(pygame.K_DOWN)
    robot.tecla(pygame.K_DOWN)                                       # auto -> tranquilo -> normal -> prisa_legal
    robot.tecla(pygame.K_RETURN)
    assert p.cfg["piloto_estilo"] == "prisa_legal" and robot.app.pila[-1] is p
    # mantenida más que un toque, no abre nada
    p._a_pulsada = pygame.time.get_ticks() - 2000
    robot.frames(2)
    assert robot.app.pila[-1] is p


def test_cada_estilo_del_piloto_corre_lo_suyo_y_con_prisa_legal_no_lo_multan(robot):
    from juego.realismo import aj
    p = robot.nueva_partida()
    p.cfg["conduccion"] = "asistida"
    p.cfg["sucesos"] = False
    p.cfg["piloto_gps"] = True
    v = _al_volante(robot)
    robot.frames(10)
    multa = aj("limite_ciudad") * (1.0 + aj("margen_velocidad") / 100.0) / 3.6
    destino = max(p.mundo.lugares.values(), key=lambda l: math.hypot(l.x - v.x, l.y - v.y))
    p.gps_a_lugar(destino, callar=True)
    p._piloto_semaforo = lambda *a: None                            # sin semáforos: solo cuenta la velocidad que busca
    for estilo in ("tranquilo", "normal", "prisa_legal", "prisa", "muy_prisa"):
        p.cfg["piloto_estilo"] = estilo
        v.vel = v.modelo["vel_max"] + 5.0                            # por encima de todas: con un frenazo enorme se queda en la suya
        p._pilotar(v, 1.0, 100.0)
        tope = v.vel
        if estilo == "tranquilo":
            assert tope <= 8.6
        elif estilo == "normal":
            assert tope <= aj("limite_ciudad") / 3.6 + 0.01
        elif estilo == "prisa_legal":
            assert aj("limite_ciudad") / 3.6 < tope < multa
        elif estilo == "prisa":
            assert abs(tope - v.modelo["vel_max"] * 0.9) < 0.01      # sin el tope de ciudad de antes
        else:
            assert abs(tope - v.modelo["vel_max"]) < 0.01            # a toda velocidad
    del p._piloto_semaforo
