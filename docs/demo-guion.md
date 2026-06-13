# Guion de demo — Brújula Export (10-12 min ante Marta Sorbed)

> Preparación previa: portátil cargado, `./run.sh` arrancado ANTES de la reunión, navegador en `http://localhost:8765`, modo no molestar, brillo al máximo. Ensayar el guion completo al menos 2 veces. Plan B: si algo falla, capturas de pantalla impresas del flujo completo.

## 0. Apertura (1 min)

> "Os traigo un prototipo que construí para enseñaros cómo trabajo. Responde a una pregunta que vosotros resolvéis cada semana en consultoría: **¿dónde debería exportar este producto?** Todo lo que vais a ver corre en este portátil, sin internet, sobre datos oficiales de DataComex — los mismos de Aduanas que usáis en ESTACOM — y la metodología es transparente y discutible, que es como creo que debe ser una herramienta de análisis."

Puntos clave a colar: datos oficiales · local (sin coste de infraestructura ni APIs) · metodología abierta.

## 1. Producto estrella: vino (3 min)

Escribir "vino" en el buscador → seleccionar 2204.

1. **Ranking:** "La herramienta puntúa cada destino de 0 a 100 combinando cinco criterios: tamaño, crecimiento, estabilidad, valor unitario y accesibilidad. No es una caja negra: cada componente se ve aquí" (señalar barras apiladas). _(El nº de operadores —"espacio competitivo"— está fuera de esta extracción; cuando se cargue, vuelve como sexto criterio: ver app.js COMPONENTS.)_
2. **Chips Aragón:** "Y esta es la capa que el panel público no da: qué cuota de esta exportación sale de Aragón y de Zaragoza."
3. Clic en un país del top — **Suiza** (nº 1 con datos reales: premium, 6,4 €/kg) o **Reino Unido** (clásico reconocible, visible casi sin scroll): serie mensual ("los meses provisionales van marcados — datos 2024 en adelante pueden revisarse"), estacionalidad, valor unitario.
4. **Anticipar la pregunta inevitable:** Alemania y Francia (los gigantes) no están arriba porque caen en CAGR y van justos de €/kg — el ranking por defecto premia oportunidad, no tamaño actual. Si surge: "¿dónde está Alemania?" es el pie perfecto para el paso de los sliders: subir el peso de Tamaño y ver a los clásicos volver arriba. Convertir la objeción en demostración.
4. Mencionar de pasada: "El €/kg como proxy de posicionamiento premium hay que leerlo con cuidado — mezcla granel y embotellado; por eso a 6 dígitos se afinaría más."

## 2. Los sliders: criterio del analista (2 min)

Abrir "Ajustar criterios".

> "Esto es lo que diferencia una herramienta de un informe estático. Si la empresa es pequeña y no aguanta volatilidad, subo estabilidad y bajo tamaño… y el ranking se reordena. La herramienta no decide: **ordena la evidencia para que el analista decida**."

Mover 2 sliders, mostrar reordenación en vivo.

## 3. Momento clave: producto a elección de Marta (2-3 min)

> "Marta, dime un producto de cualquier empresa que estéis asesorando — o un código TARIC si lo tienes en la cabeza."

Buscar lo que diga → ranking al instante. Si sale un producto con poco histórico, mejor aún: enseñar el aviso de datos insuficientes ("la herramienta avisa en vez de inventar — celdas con secreto estadístico salen como n/d, nunca como cero").

Backup si no propone nada: alfalfa deshidratada (1214) — "Aragón es líder absoluto de España y los destinos son Emiratos y China; mercados que no salen en la intuición de nadie."

## 4. Capa IA + informe (2 min)

1. Volver a vino (o porcino 0203). Panel "Análisis del analista (IA)": "Los comentarios ejecutivos los genera Claude sobre los datos del panel, en mi máquina, y los reviso yo — coste marginal cero, y el criterio final siempre es humano."
2. Botón "Generar informe" → vista imprimible: "Y esto sale como entregable: ranking, metodología y cautelas. El borrador de un informe de selección de mercados en un clic."

## 5. Cierre honesto (1 min)

> "Tres límites claros: es comercio declarado (~98 % del total); no hay nombres de empresas — para eso están vuestros PIC; y mide demanda revelada del producto español, no el mercado mundial total — la siguiente capa natural sería cruzar con importaciones mundiales de Comtrade. Lo construí en [tiempo real] con datos públicos y herramientas de IA. Es la primera capa de vuestro embudo de inteligencia, automatizada."

Dejar abierta la conversación: ¿qué le añadiríais vosotros?

## Anti-demo (qué NO hacer)

- No vender la herramienta como sustituto de su consultoría — es la "primera capa", acelera al analista.
- No criticar sus paneles ESTACOM/PIC: "complementa lo que ya tenéis".
- No prometer datos que DataComex no tiene (empresas nominales, puertos, aranceles aplicados).
- No dejar que la demo pase de 12 min: mejor que pidan más.
