"""El servidor en línea y los idiomas.

- Lo que lee quien administra el servidor (la consola, el registro, la ayuda de las órdenes, las opciones) va en el idioma
  del servidor: tr(). Lo que oyen los jugadores va siempre en español, tal cual que antes, y lo traduce el juego de cada
  uno: es(). Así, en un mismo servidor juega gente de idiomas distintos y los juegos anteriores siguen entendiéndolo.
- El juego reconoce cada texto del servidor en su catálogo, también los que llegan con los huecos ya rellenos.
- El servidor que va solo (Linux, NAS) lleva su catálogo reducido y elige idioma por su configuración.
"""
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from juego import i18n                       # noqa: E402
from servidor import compat, idioma, nucleo, opciones   # noqa: E402

HUECO = re.compile(r"%[sd]")


def _catalogo_en():
    with open(os.path.join(RAIZ, "data", "idiomas", "en", "textos.json"), encoding="utf-8") as f:
        return json.load(f)["textos"]


def _marcados(marca):
    """Los textos que el código del servidor marca con ``marca`` (tr o es): {texto: archivo}."""
    r = {}
    for ruta in sorted(glob.glob(os.path.join(RAIZ, "servidor", "*.py"))):
        with open(ruta, encoding="utf-8") as f:
            arbol = ast.parse(f.read())
        for n in ast.walk(arbol):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == marca and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                r[n.args[0].value] = os.path.basename(ruta)
    return r


def _entorno(**mas):
    env = {k: v for k, v in os.environ.items() if k != "PUERTOBRAVO_IDIOMA"}
    env.update(PYTHONIOENCODING="utf-8", **mas)
    return env


# ------------------------------------------------------------------ el servidor
def test_es_no_cambia_nada():
    for t in ("Ese vehículo ya no está.", "%s compra %s, en %s.", "", "texto que no existe"):
        assert idioma.es(t) is t


def test_el_servidor_habla_a_quien_lo_administra_en_su_idioma():
    try:
        assert idioma.cargar("en") == "en"
        assert idioma.tr("Servidor parado. Todo guardado.") == "Server stopped. Everything saved."
        assert idioma.tr("Un texto que no está en ningún catálogo.") == "Un texto que no está en ningún catálogo."
        assert idioma.es("Ese vehículo ya no está.") == "Ese vehículo ya no está."          # lo de los jugadores, nunca
    finally:
        idioma.cargar("es")
    assert idioma.actual() == "es" and idioma.tr("Servidor parado. Todo guardado.") == "Servidor parado. Todo guardado."


def test_con_la_variable_de_entorno_todo_lo_de_quien_administra_sale_en_ingles():
    codigo = ("from servidor import opciones, idioma\nfrom servidor.nucleo import Servidor\n"
              "print(idioma.actual()); print(opciones.POR_CLAVE['puerto'].etiqueta); print(Servidor.AYUDA_ORDENES[4][0])\n"
              "print(opciones.texto_conf().splitlines()[0]); print(opciones.POR_CLAVE['bienvenida'].defecto)")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=_entorno(PUERTOBRAVO_IDIOMA="en"), capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["en", "Port", "aviso text", "# Puerto Bravo: Ley del Asfalto online server",
                                     "Bienvenido. Juega limpio."]          # la bienvenida la oyen los jugadores: en español


def test_la_opcion_idioma_existe_y_vale_para_el_servidor_que_va_solo(tmp_path):
    o = opciones.POR_CLAVE["idioma"]
    assert o.seccion == "general" and o.defecto == "auto" and o.reinicio and {"auto", "es", "en"} <= set(o.permitidos())
    assert opciones.validar_valor("idioma", "EN") == ("en", None) and opciones.validar_valor("idioma", "xx")[1]
    # La copia para otros sistemas: el código del servidor y su catálogo reducido, sin nada del juego al lado.
    from herramientas import preparar_carpeta_servidor as carpeta
    destino = tmp_path / "solo" / "servidor"
    os.makedirs(destino / "idiomas")
    for n in os.listdir(os.path.join(RAIZ, "servidor")):
        if n.endswith(".py") or n == "mundo.json":
            shutil.copyfile(os.path.join(RAIZ, "servidor", n), destino / n)
    reducido = carpeta.catalogos_reducidos()["en"]
    assert set(reducido["textos"]) <= carpeta.textos_del_servidor() and len(reducido["textos"]) > 400
    assert "Ese vehículo ya no está." in reducido["textos"] and "Pistola" not in reducido["textos"]
    with open(destino / "idiomas" / "en.json", "w", encoding="utf-8") as f:
        json.dump(reducido, f, ensure_ascii=False)
    (tmp_path / "solo" / "servidor.conf").write_text("# en inglés\nidioma = en\n", encoding="utf-8")
    codigo = ("import os, sys\nsys.path.insert(0, os.getcwd())\nfrom servidor import idioma, opciones\n"
              "print(idioma.actual()); print(os.path.relpath(idioma.ruta_catalogo('en'), os.getcwd())); print(opciones.POR_CLAVE['puerto'].etiqueta)")
    r = subprocess.run([sys.executable, "-I", "-c", codigo], cwd=tmp_path / "solo", env=_entorno(LANG="C"), capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["en", os.path.join("servidor", "idiomas", "en.json"), "Port"]
    # sin la opción, con un sistema en «C», español
    (tmp_path / "solo" / "servidor.conf").write_text("idioma = auto\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "-c", codigo.replace("os.path.relpath(idioma.ruta_catalogo('en'), os.getcwd())", "'-'")],
                       cwd=tmp_path / "solo", env=_entorno(LANG="C", LC_ALL="C"), capture_output=True, text=True, encoding="utf-8")
    if os.name != "nt":                     # en Windows manda el idioma de Windows, que no se puede fingir aquí
        assert r.stdout.splitlines()[0] == "es"


def test_cada_texto_del_servidor_para_los_jugadores_esta_en_el_catalogo_ingles():
    cat = _catalogo_en()
    for texto, archivo in _marcados("es").items():
        assert texto in cat, (archivo, texto)
        assert HUECO.findall(cat[texto]) == HUECO.findall(texto), texto       # los mismos huecos, en el mismo orden
    for texto, archivo in _marcados("tr").items():
        assert texto in cat, (archivo, texto)


def test_lo_que_dice_el_servidor_a_los_jugadores_no_cambia(tmp_path):
    """Lo que manda el servidor sigue saliendo letra por letra como antes de marcarlo: los juegos anteriores lo entienden."""
    assert compat.texto_diferencias({"armas": ["Escopeta", "Rifle", "Bate"], "vehiculos": ["Moto"]}, {"armas": [], "vehiculos": []}) == (
        "En este servidor hay cosas que tu versión del juego no tiene. 3 armas: Escopeta, Rifle y Bate. Un vehículo: Moto. Las oirás y las "
        "verás como lo más parecido de lo que tu juego conoce; hacen el daño que marca el servidor, el mismo para todos.")
    assert compat.texto_diferencias({"armas": [], "vehiculos": []}, {"armas": list("ABCDEF"), "vehiculos": []}) == (
        "Tu juego trae cosas que este servidor no conoce. 6 armas: A, B, C, D y 2 más. Puedes usarlas en lo tuyo, pero contra otros "
        "jugadores esas armas cuentan como ir con las manos, y esos vehículos los verán como un utilitario.")
    assert nucleo.CAUSAS["apagado"] == "El servidor se ha cerrado."
    assert [o for o, _ in nucleo.Servidor.AYUDA_ORDENES][4:6] == ["aviso texto", "decir nombre: texto"]
    from test_servidor import mundo
    srv = nucleo.Servidor({"datos": str(tmp_path), "puerto": 0, "cifrado": "no", "personajes": 0}, mundo())
    enviados = []
    srv._enviar = lambda j, m, *a: enviados.append(m)
    srv._a_todos = lambda m, **k: enviados.append(m)

    class J:
        sabe = set()
    srv._anunciar_parada(J(), "reinicio", 30, 60)
    assert enviados[-1]["texto"] == ("Aviso del servidor: dentro de 30 segundos se reinicia por mantenimiento. Tu personaje se guarda solo. "
                                     "Volverá en unos minutos: vuelve a entrar entonces.")
    assert srv.orden("aviso Mañana hay quedada") == "Aviso enviado." and enviados[-1]["texto"] == "Aviso del servidor: Mañana hay quedada"
    assert srv.orden("mensaje Hoy, carreras") .startswith("Mensaje del día cambiado") and enviados[-1]["texto"] == "Mensaje del día: Hoy, carreras"
    assert srv.orden("hora") == "A esa orden le falta algo. Se escribe así: hora número (time). Sirve para esto: pone la hora del juego, de 0 a 23."
    assert srv.orden("chiribita") == "No conozco esa orden. Escribe ayuda o help."
    # las órdenes valen en español y en inglés, en cualquier servidor
    assert srv.orden("time") == srv.orden("hora") and srv.orden("KICK Nadie") == srv.orden("expulsar Nadie") == "No hay nadie con ese nombre."
    assert srv.orden("help") == srv.orden("ayuda") and srv.orden("gangs") == "No hay bandas." and srv.orden("players") == "No hay nadie."
    assert srv.orden("expulsar Nadie: pesado") == "No hay nadie con ese nombre."
    assert srv.orden("bandas") == "No hay bandas." and srv.orden("jugadores") == "No hay nadie."
    srv.t_inicio = time.time() - (86400 + 2 * 3600 + 60 + 5)
    assert srv._tiempo_en_marcha() == "1 día, 2 horas, 1 minuto"
    assert srv.orden("ayuda", "Alguien").startswith("Órdenes: ayuda (help), estado (status), jugadores (players)") and srv.orden("ayuda").startswith("Órdenes (cada una vale en español o en inglés, en cualquier servidor):\n  ayuda (help): ")


# ------------------------------------------------------------------ el juego
@pytest.fixture
def en_ingles(monkeypatch):
    monkeypatch.setenv("PUERTOBRAVO_IDIOMA", "en")
    i18n.cargar()
    assert i18n.actual() == "en"
    yield
    monkeypatch.setenv("PUERTOBRAVO_IDIOMA", "es")
    i18n.cargar()


def test_el_juego_dice_en_su_idioma_lo_que_manda_el_servidor(en_ingles):
    tr = i18n.tr_servidor
    assert tr("Ese vehículo ya no está.") == "That vehicle is no longer here."                                   # tal cual
    # con huecos: el nombre del jugador se queda; el negocio y la localidad salen de los datos del mundo y se traducen
    assert tr("Paco compra Bar La Gaviota, en Plataforma Neptuno.") == "Paco buys La Gaviota Bar, in Neptuno Platform."
    assert tr("Llevas 15 minutos sin hacer nada y el servidor te ha sacado para dejar sitio. Tu personaje está guardado: puedes volver a entrar.") == (
        "You have been idle for 15 minutes and the server has kicked you to make room. Your character is saved: you can come back in.")
    # un hueco que trae otra plantilla dentro
    assert tr("La guerra por El Muelle ha terminado: 30 a 12. El barrio pasa a Los Lobos.") == (
        "The war for El Muelle is over: 30 to 12. The neighborhood goes to Los Lobos.")
    assert tr("Un administrador te ha sacado del servidor. Motivo: spam") == "An admin has kicked you from the server. Reason: spam"
    assert tr("Bienvenido. Juega limpio.") == "Welcome. Play fair."
    # lo que no se reconoce, tal cual: lo que escribe quien administra, o un texto de otro servidor
    for t in ("Hoy hay carreras en el puerto a las diez", "", "Paco, por Bar La Gaviota"):
        assert tr(t) == t
    assert tr(None) is None


def test_reconocer_un_texto_del_servidor_es_rapido(en_ingles):
    i18n.tr_servidor("Calentar las plantillas.")
    t0 = time.perf_counter()
    for n in range(200):
        i18n.tr_servidor("%s compra %s, en %s. %d" % ("Paco", "Bar La Gaviota", "Plataforma Neptuno", n))     # ninguno se repite
    assert time.perf_counter() - t0 < 2.0


def test_en_espanol_el_juego_no_toca_nada():
    assert i18n.actual() == "es"
    assert i18n.tr_servidor("Paco compra Bar La Gaviota, en Plataforma Neptuno.") == "Paco compra Bar La Gaviota, en Plataforma Neptuno."


def test_el_juego_pasa_por_el_catalogo_lo_que_le_dice_el_servidor():
    """Los avisos, los motivos, los rechazos y lo que dicen los personajes del servidor; nunca el chat de los jugadores."""
    with open(os.path.join(RAIZ, "juego", "enlinea.py"), encoding="utf-8") as f:
        src = f.read()
    for trozo in ('self.decir(tr_servidor(str(m.get("texto", ""))))', "Motivo(tr_servidor(texto)", 'tr_servidor(str(info.get("bienvenida", "")))',
                  'self.sv_salir(tr_servidor(str(m.get("motivo") or ""))', 'motivo = tr_servidor(str(m.get("motivo") or ""))',
                  'texto=tr_servidor(str(m.get("texto", "")))'):
        assert trozo in src, trozo
    cuerpo = src[src.index("    def _svm_chat(self, m):"):src.index("    # --------------------------------------------------------------------- rol")]
    assert cuerpo.count("tr_servidor(") == 1 and 'getattr(de, "ia", False)' in cuerpo        # solo lo de los personajes del servidor


def test_el_panel_no_traduce_lo_que_oyen_los_jugadores():
    for nombre in ("motor.py", "ventana.py"):
        with open(os.path.join(RAIZ, "panel_servidor", nombre), encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r"parar\(\s*(motivo=)?tr\(", src), nombre
