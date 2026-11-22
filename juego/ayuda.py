"""Textos de ayuda: teclas, tutorial y glosario de sonidos."""
from .i18n import tr
from . import catalogo_sonidos

TECLAS = {
    "general": [
        ("C", tr("dónde estoy: calle, barrio y hacia dónde miro. Con Mayúsculas añade las coordenadas")),
        ("V", tr("estado: salud, dinero, arma, nivel de búsqueda y vehículo")),
        ("T", tr("hora, día y tiempo que hace")),
        ("O", tr("objetivo de la misión o del trabajo en curso: dice primero dónde está, a cuántos metros, en qué dirección y, si se mueve, hacia dónde va, y después lo demás. "
              "Si el objetivo se mueve o corre el tiempo, una pulsación dice solo eso, y dos seguidas leen la explicación entera. En un golpe preparado con tu banda dice además la fase y quién hace qué; "
              "con un vuelo comercial o un aparato secuestrado, adónde tienes que llevarlo")),
        (tr("Mayúsculas O"), tr("volver al objetivo de la misión o del trabajo: deja cualquier desvío, lo marca en el GPS y, si está al alcance, lo deja elegido en el radar. Siempre hace lo mismo")),
        ("N", tr("descripción del lugar o del barrio en el que estás")),
        (tr("Mayúsculas N"), tr("siguiente cruce: qué calle es la próxima que te vas a cruzar hacia donde miras o conduces, y a cuántos metros está")),
        (tr("Mayúsculas V"), tr("solo el hambre, la sed, el sueño y la higiene, con la vida realista activada")),
        (tr("Mayúsculas L"), tr("dónde está el vehículo del que te bajaste: lo dice y lo marca en el GPS. Si ibas a otro sitio, al llegar al vehículo el GPS vuelve solo a ese destino. "
                         "Si tienes más vehículos, dice cuántos: están en el móvil, en Mis vehículos")),
        ("K", tr("hacia dónde miras o conduces, y hace sonar un tono desde el norte para orientarte")),
        ("F10", tr("jugando con amigos o en un servidor, escribir un mensaje: se lee en voz alta a los demás. Para abrir tu partida a tus amigos o unirte a la de uno, abre el móvil con M y entra en Jugar con amigos")),
        (tr("Mayúsculas F10"), tr("en un servidor con canales de rol, hablar en personaje: lo oye solo quien está cerca de ti")),
        (tr("Control F10"), tr("en un servidor con canales de rol, describir lo que hace tu personaje: escribes «abre la puerta» y los que están cerca oyen tu nombre y «abre la puerta»")),
        ("F9", tr("explorador de mapa: recorre la localidad con un cursor, cruce a cruce, sin mover al personaje. Tabulador dice los lugares junto al cursor e Intro marca el destino")),
        (tr("Tabulador y Mayúsculas Tabulador"), tr("radar: recorre lo que hay alrededor, de lo más cercano a lo más lejano")),
        ("B", tr("pone el GPS y la baliza hacia lo último que dijo el radar. Si ya ibas a algún sitio, es un desvío: al subir a ese vehículo, llegar junto a esa persona, llegar a ese objeto o recogerlo, o llegar a ese lugar, "
              "el GPS vuelve solo a lo que llevabas, y lo dice")),
        ("F6", tr("cambia el filtro del radar: todo, lugares, vehículos, personas u objetos")),
        ("L", tr("lista de lugares de la ciudad para marcar un destino")),
        ("G", tr("repite la indicación del GPS. En una misión, sin destino marcado, vuelve a marcar lo que pide la misión; sin misión, recupera el último destino que quitaste")),
        (tr("Mayúsculas G"), tr("quita el destino del GPS. Si estabas en un desvío, el GPS vuelve a lo que llevabas; otra pulsación quita también eso")),
        (tr("Control G"), tr("recupera el último destino o desvío que quitaste con Mayúsculas G, sin tener que buscarlo otra vez. Si ahora vas a otro sitio, entra como desvío")),
        ("M", tr("abre el móvil: misiones, lugares, explorador de mapa, marcadores, servicios, habilidades, logros, propiedades y estadísticas. En Vida, reputación y consecuencias "
              "está cómo te ve la ciudad, cómo te ve la calle y qué ganas o pierdes por ello, con tus antecedentes, tu contrato, tus estudios, tus negocios y lo que te van a cobrar")),
        (tr("Intro"), tr("interactuar: entrar en un lugar, empezar una misión, recoger un objeto o hablar")),
        ("F", tr("subir a un vehículo o bajarte")),
        (tr("Mayúsculas F"), tr("en un servidor, sacar a otro jugador de su vehículo y quedártelo: tiene que ir despacio y estar a tu lado")),
        ("Q", tr("fija al enemigo más cercano; púlsala otra vez para pasar al siguiente. Mayúsculas Q fija a cualquiera")),
        (tr("Números del 1 al 9"), tr("eligen arma. La coma pasa a la siguiente y Mayúsculas coma a la anterior")),
        ("I", tr("abre la lista de tus armas para elegir una")),
        ("P", tr("en el mar, lanza la caña para pescar; cuando oigas que pican, pulsa Espacio. En vehículos de emergencias, enciende la sirena")),
        ("Z", tr("usa un botiquín")),
        (tr("Mayúsculas H"), tr("rendirte: con la policía buscándote y un agente cerca, levantas las manos. Los agentes dejan de disparar y vienen a detenerte; no te muevas ni ataques. "
                         "Cuanto más nivel de búsqueda, más multa y más horas de calabozo, y con el nivel más alto pierdes todas las armas. Otra pulsación baja las manos")),
        (tr("Re Pág y Av Pág"), tr("repasan los mensajes anteriores. El punto repite el último")),
        (tr("Control Re Pág y Control Av Pág"), tr("van al primer mensaje del historial y al último. En Opciones, Voz, eliges si cada mensaje nuevo te lleva al final")),
        ("F1", tr("esta ayuda")),
        ("F2", tr("cambia entre conducción asistida y libre")),
        ("F3", tr("cambia el movimiento a pie entre brújula y giros")),
        ("F4", tr("activa o desactiva la baliza sonora del GPS")),
        ("F5", tr("guardado rápido, fuera de las misiones")),
        (tr("F7 y F8"), tr("bajan y suben el volumen de la música")),
        ("F12", tr("pone una marca en el registro de la sesión. Púlsala cuando notes algo raro: así, quien revise el registro sabrá en qué momento fue")),
        (tr("Escape"), tr("menú de pausa")),
    ],
    "pie": [
        (tr("Flechas"), tr("caminar. En modo brújula cada flecha va hacia un punto cardinal: arriba es norte, derecha es este. En modo giros, izquierda y derecha giran 45 grados y arriba avanza")),
        (tr("Mayúsculas izquierda con las flechas"), tr("correr. La Mayúsculas derecha no hace correr ni cambia entre andar y correr. Las combinaciones, como Mayúsculas N, valen con cualquiera de las dos y no cambian el paso")),
        (tr("W, A, S y D"), tr("escáner direccional: dice qué hay delante, a la izquierda, detrás y a la derecha, y a qué distancia está la pared")),
        (tr("Espacio"), tr("atacar o disparar. Con armas automáticas, mantenla pulsada")),
        ("R", tr("recargar")),
        (tr("Mayúsculas R"), tr("el reproductor con auriculares, si lo has comprado: lo enciende y pasa de emisora, para oír la radio y tu música a pie. Una de las emisoras es apagado")),
        ("X", tr("agacharte o levantarte. Al agacharte te aciertan menos, pero vas más lento")),
        (tr("Mayúsculas X"), tr("ponerte a cubierto tras una pared o un vehículo parado, o salir. A cubierto te alcanzan mucho menos; si te mueves, sales")),
        (tr("Retroceso"), tr("tiempo lento: todo va más despacio mientras te quede concentración. Otra pulsación lo quita")),
        ("H", tr("gritar para espantar a los peatones. De servicio como policía, da el alto a los sospechosos")),
        ("E", tr("con un arma en la mano, atracar al peatón que tengas al lado")),
        ("Y", tr("si tienes perro, le pides que busque por el olfato el objeto más cercano")),
        (tr("Mayúsculas Y"), tr("el menú de tu perro: cómo está, acariciarlo, darle de comer, mandarlo a casa o llamarlo")),
        ("J", tr("hablar con la persona que tengas al lado. Cada una tiene su nombre, su oficio y su carácter: puedes saludar, preguntar por un sitio, invitar a un café, hacer amigos o escribir lo que quieras decirle")),
        (tr("Mayúsculas J"), tr("jugando con amigos o en un servidor, dice cómo va vestido el jugador que tengas más cerca: su ropa y sus complementos. En un servidor con canales de rol, lee además su ficha, si la ha escrito. Solo lo dice cuando lo pides")),
        ("U", tr("caminar solo: con un destino marcado en el GPS, el personaje sigue la ruta él solo hasta llegar. Mantén Mayúsculas para que corra. Cualquier flecha, o la U otra vez, lo detiene")),
    ],
    "coche": [
        (tr("Flecha arriba"), tr("acelerar")),
        (tr("Flecha abajo"), tr("frenar y, parado, marcha atrás")),
        (tr("Espacio"), tr("freno de mano")),
        (tr("Flechas izquierda y derecha"), tr("en conducción asistida ponen el intermitente: el coche girará solo en el próximo cruce. En conducción libre giran el volante")),
        (tr("A y D"), tr("en conducción asistida, mantenlas para cambiar de carril: A invade el carril contrario para adelantar y D te arrima a la acera. "
                  "Pilotando un helicóptero o una avioneta, con el vuelo real, la D sube y la A baja")),
        (tr("Un toque de la A"), tr("los ajustes del piloto del GPS: activarlo y cómo conduce, Automático, Tranquilo, Normal cumpliendo las normas, "
                  "Con prisa pero cumpliendo las normas, o Con prisa saltándose las normas")),
        (tr("Frenada automática"), tr("en conducción asistida el coche frena solo si hay un vehículo delante en tu carril. Se desactiva en Opciones")),
        ("U", tr("media vuelta, con el coche casi parado. Con el piloto del GPS, la da él solo cuando el destino queda a tu espalda")),
        ("Y", tr("piloto del GPS: el coche va solo hasta el destino marcado; acelera, frena, gira, espera en los semáforos y se detiene al llegar")),
        ("E", tr("en conducción libre, endereza el coche hacia el punto cardinal más cercano")),
        ("W", tr("velocidad actual")),
        ("H", tr("claxon")),
        ("R", tr("cambia de emisora. Mayúsculas R apaga la radio")),
        (tr("Control"), tr("disparar desde el vehículo sin bajarte, con un arma de fuego en la mano: primero la Q fija a quien tengas cerca, y Control le dispara. La I cambia de arma. Con un arma automática, mantenla pulsada")),
        ("J", tr("empieza o termina un trabajo con el vehículo: taxi, ambulancia, autobús, coche patrulla o camión. Si eres agente de policía, en un coche patrulla empieza o termina el turno")),
        (tr("Helicóptero"), tr("y avioneta: vuelan por encima de edificios y tráfico y se pilotan a mano, como un barco. Con el vuelo real, flecha arriba despega, la D sube, la A baja y una nota dice la altura; "
                        "para aterrizar, frena y pulsa F. Al llegar al borde de la localidad, o con Intro en un helipuerto o un aeropuerto, eliges destino y haces la travesía: allí, las flechas llevan el rumbo y la altitud, "
                        "Tabulador es el piloto automático, Intro dice cómo va el vuelo, la N lo acelera y F1 lo explica. Con el vuelo real quitado en Opciones, se vuela siempre a la misma altura e Intro en un helipuerto te lleva de un salto")),
        (tr("En el mar"), tr("los barcos se llevan siempre a mano: izquierda y derecha giran el timón y se anuncia el rumbo. Intro junto a un muelle sirve para atracar")),
    ],
}

TUTORIAL = [
    (tr("Narrador"), tr("Tutorial. Puedes saltarlo con Escape y repetir cualquier frase con la flecha arriba. Todas las teclas están siempre en la ayuda, con F1.")),
    (tr("Narrador"), tr("Este juego se juega solo con el oído. Usa auriculares: lo que suena a tu derecha está a tu derecha, y lo que suena apagado está detrás de ti.")),
    (tr("Narrador"), tr("A pie te mueves con las flechas. Por defecto, arriba camina hacia el norte, abajo hacia el sur, derecha al este e izquierda al oeste. Mantén Mayúsculas para correr.")),
    (tr("Narrador"), tr("La ciudad es una cuadrícula: las calles van de oeste a este y las avenidas de sur a norte. Hay un cruce cada 90 metros. Tus pasos suenan distinto en la acera, en el asfalto, en el césped y en la arena.")),
    (tr("Narrador"), tr("Pulsa C en cualquier momento para saber dónde estás. Pulsa Tabulador para recorrer con el radar lo que tienes cerca: cada cosa suena desde su posición y se anuncia con su distancia.")),
    (tr("Narrador"), tr("Las teclas W, A, S y D son tu bastón: dicen qué hay en cada dirección y a qué distancia está la pared.")),
    (tr("Narrador"), tr("Cada tipo de lugar tiene su propio sonido, que oirás al acercarte. Puedes aprenderlos todos en el menú Aprender los sonidos. Ante una puerta, pulsa Intro para entrar.")),
    (tr("Narrador"), tr("Para ir a un sitio, pulsa L, elige el lugar y pulsa Intro. El GPS te dirá por dónde ir y una baliza sonará en la dirección que debes seguir. Con G repites la indicación.")),
    (tr("Narrador"), tr("En los cruces suena el semáforo: un tictac rápido significa que puedes cruzar la calle andando hacia el norte o el sur. Un pío lento, que puedes cruzar la avenida hacia el este o el oeste.")),
    (tr("Narrador"), tr("Con F subes a un vehículo. En conducción asistida el coche sigue su carril él solo: tú aceleras con flecha arriba, frenas con flecha abajo y, antes de cada cruce, pulsas izquierda o derecha si quieres girar. Un pitido te avisa de los coches que tienes delante.")),
    (tr("Narrador"), tr("Si te metes en líos, pulsa Q para fijar al enemigo: oirás un tono que sale de donde está. Espacio ataca, R recarga y Z usa un botiquín. Desde un vehículo también puedes disparar sin bajarte: la Q fija igual y Control dispara, con un arma de fuego en la mano.")),
    (tr("Narrador"), tr("Más allá de Puerto Bravo hay otra ciudad, San Lucero, dos pueblos, Villaseca y Cala Brava, y un mar con una isla. Se llega por carretera con un vehículo, en autobús desde la estación o en barco desde un embarcadero. Por carretera, conduce hasta una salida de la ciudad y, sin bajarte, pulsa Intro. El GPS sabe guiarte entre localidades.")),
    (tr("Narrador"), tr("Para aprenderte una ciudad sin moverte, pulsa F9: el explorador de mapa mueve un cursor de cruce en cruce y te dice qué hay en cada uno.")),
    (tr("Narrador"), tr("Puedes trabajar con un taxi, repartir pizzas, conducir ambulancias, autobuses y camiones, pescar, correr carreras, comprar casas, negocios, coches y barcos, o jugarte el dinero en el casino. El móvil, con la tecla M, lo reúne todo.")),
    (tr("Narrador"), tr("Si tienes un mando de Xbox o de PlayStation, conéctalo: el juego lo reconoce solo, vibra con lo que pasa y la ayuda te dice qué hace cada botón.")),
    (tr("Narrador"), tr("Eso es todo. Explora a tu ritmo: nadie te obliga a seguir la historia. Bienvenid[o|a] a Puerto Bravo.")),
]

# Las teclas de cuando se recorre por dentro una casa, un local o una tienda. No se pueden cambiar: van aparte de las del juego.
TECLAS_RECORRIDO = [
    (tr("Flecha izquierda y flecha derecha"), tr("ir a la habitación, la sala o el pasillo de al lado. Se oyen tus pasos hacia ese lado y el juego dice adónde llegas")),
    (tr("Intro"), tr("usar el sitio donde estás. En la cocina de casa, guardar la compra, abrir la nevera o la despensa y cocinar. En un pasillo de una tienda de comida, ver sus productos: "
              "Intro o flecha derecha echa uno a la cesta y flecha izquierda lo devuelve. En la caja, pagar la cesta")),
    ("C", tr("en una tienda de comida, qué llevas en la cesta y cuánto suma. Con mando, X o Cuadrado")),
    ("F1", tr("dónde estás, qué hace Intro ahí y adónde hay que ir para que te atiendan")),
    (tr("Escape"), tr("salir. En una tienda de comida, con algo en la cesta, pregunta antes qué haces con ella: pagar, dejarla, llevártela sin pagar o seguir comprando")),
]

INTRO = [
    (tr("Narrador"), tr("Puerto Bravo. Una ciudad de mar, con un puerto que nunca duerme y una playa que nunca descansa.")),
    (tr("Narrador"), tr("Te llamas Dani Roca. Hace tres años te condenaron por un robo que no cometiste. Esta mañana se han abierto las puertas de la prisión de Monteferro.")),
    (tr("Narrador"), tr("El autobús te deja en el Barrio Viejo, donde te criaste. Llevas cincuenta euros, un botiquín y un petate. Tu tía Encarna te espera en su bar, La Gaviota, unos metros al este por la Calle Mayor.")),
]

# El glosario de Aprender los sonidos: (archivo, nombre, explicación) de los más importantes, en el orden en que conviene
# aprenderlos. Los nombres, las explicaciones y ese orden están en el catálogo de sonidos, que es el único sitio donde se escriben.
SONIDOS = [(s, catalogo_sonidos.nombre(s), catalogo_sonidos.describir(s)) for s in catalogo_sonidos.IMPORTANTES]
