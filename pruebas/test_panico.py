"""Los peatones asustados se siguen oyendo mientras huyen, sin que una multitud lo tape todo."""
from juego.entidades import Persona


def test_quien_huye_sigue_chillando_y_no_chillan_todos_a_la_vez(robot):
    p = robot.nueva_partida()
    p.cfg["sucesos"] = False
    x, y = p.pos()
    sonados = []
    original = p.voz_panico
    p.voz_panico = lambda q: sonados.append(q) or original(q)
    gente = []
    for k in range(8):
        q = Persona("civil", x + 6 + k, y)
        p.personas.append(q)
        gente.append(q)
        p.asustar(q, 30, callar=True)
    for _ in range(12):                                          # seis segundos de huida, sin que acabe ningún chillido
        for q in gente:
            p.panico(q, 10.0, 0.5)
    assert 1 <= len([c for c in p._panico_canales if c.activo]) <= 3 and len(sonados) <= 3      # como mucho tres a la vez
    for _ in range(24):                                          # doce segundos más, acabando cada chillido al momento
        for c in p._panico_canales:
            c.fin = True
        for q in gente:
            p.panico(q, 10.0, 0.5)
    assert len(sonados) >= 12                                    # se les sigue oyendo, no solo el primer grito
    q = gente[0]
    q.t_panico = 0.0
    antes = len(sonados)
    p.panico(q, 80.0, 0.5)                                       # lejos no se le oye
    assert len(sonados) == antes
